#!/usr/bin/env python3
"""Optional Claude Code hook for the project-handoff skill.

Two events only:

    PreCompact (trigger=auto)      -> increment a per-session auto-compaction counter
    SessionStart (source=compact)  -> inject a one-line checkpoint when due

Design rules:
  * fail open: any problem exits 0 and never blocks the session;
  * no prompts, transcripts or file contents are stored;
  * no file is ever deleted by this script;
  * state lives outside the project, under ~/.claude/state/project-handoff.

This file is delivered disabled. Installing it requires explicit approval and a
backup of ~/.claude/settings.json. See references/compaction.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

SCHEMA = 1
THRESHOLD = 3
COOLDOWN = 3
LOCK_TIMEOUT = 1.5
LOCK_POLL = 0.05

CHECKPOINT = (
    "project-handoff：本会话已发生第 {count} 次自动压缩。"
    "仅在当前工作已到安全位置、下一步明确且换会话有具体收益时，"
    "按 project-handoff 技能评估是否在最终答复第一段给出“交接建议：”；"
    "否则忽略本条。不要因此保存记录或新建会话。"
)


def state_dir(override: str | None = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("PROJECT_HANDOFF_STATE_DIR")
    if env:
        return Path(env)
    return Path.home() / ".claude" / "state" / "project-handoff"


def session_key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8", "surrogatepass")).hexdigest()


def new_state(session_id: str) -> dict:
    return {
        "schema": SCHEMA,
        "session_id": session_id,
        "auto_count": 0,
        "next_reminder_at": THRESHOLD,
        "updated_at": time.time(),
    }


def load_state(path: Path, session_id: str) -> dict | None:
    """Return state, a fresh state, or None for corrupt/unknown schemas."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return new_state(session_id)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    count = data.get("auto_count")
    nxt = data.get("next_reminder_at")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return None
    if not isinstance(nxt, int) or isinstance(nxt, bool) or nxt < 1:
        return None
    data["session_id"] = session_id
    return data


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class FileLock:
    """Portable single-byte lock with a bounded wait.

    The lock file is created next to the state file. It is deliberately left in
    place: unlinking a lock file while another process may hold it is unsafe.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh = None

    def __enter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "a+b")
        self._fh.seek(0, os.SEEK_END)
        if self._fh.tell() == 0:
            self._fh.write(b"\0")
            self._fh.flush()
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            try:
                self._lock()
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("lock busy")
                time.sleep(LOCK_POLL)

    def _lock(self) -> None:
        self._fh.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(self) -> None:
        self._fh.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)

    def __exit__(self, *exc):
        try:
            self._unlock()
        except Exception:
            pass
        finally:
            try:
                self._fh.close()
            except Exception:
                pass
        return False


def process(event, state_dir_override: str | None = None) -> dict | None:
    """Handle one hook event. Returns hook output or None. Never raises."""
    if not isinstance(event, dict):
        return None

    name = event.get("hook_event_name")
    session_id = event.get("session_id")
    if not isinstance(name, str) or not isinstance(session_id, str) or not session_id:
        return None
    if event.get("agent_id") or event.get("agent_transcript_path"):
        return None  # subagent events are out of scope

    directory = state_dir(state_dir_override)
    path = directory / (session_key(session_id) + ".json")
    lock = path.with_name(path.name + ".lock")

    if name == "PreCompact":
        if event.get("trigger") != "auto":
            return None
        try:
            with FileLock(lock):
                state = load_state(path, session_id)
                if state is None:
                    return None
                state["auto_count"] += 1
                state["updated_at"] = time.time()
                write_state(path, state)
        except Exception:
            return None
        return None

    if name == "SessionStart":
        if event.get("source") != "compact":
            return None
        try:
            with FileLock(lock):
                state = load_state(path, session_id)
                if state is None:
                    return None
                count = state["auto_count"]
                if count < 1 or count < state["next_reminder_at"]:
                    return None
                state["next_reminder_at"] = count + COOLDOWN
                state["updated_at"] = time.time()
                write_state(path, state)
        except Exception:
            return None
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": CHECKPOINT.format(count=count),
            }
        }

    return None


def main() -> int:
    try:
        raw = sys.stdin.buffer.read()
        event = json.loads(raw.decode("utf-8-sig")) if raw.strip() else None
        result = process(event)
        if result:
            sys.stdout.buffer.write(
                json.dumps(result, ensure_ascii=False).encode("utf-8") + b"\n"
            )
            sys.stdout.buffer.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
