#!/usr/bin/env python3
"""Install or remove the optional project-handoff hooks in settings.json.

What it changes: only the hook entries that call this skill's handoff_hook.py,
under two events (PreCompact, SessionStart). Everything else is preserved.

Safety rules:
  * a timestamped backup is written before any change;
  * --dry-run prints the plan and writes nothing;
  * file contents are never printed - only event names and counts;
  * if the existing settings file is not valid JSON, it stops without writing;
  * no file is ever deleted (uninstall only removes hook entries).

Usage:
    python hooks/install.py --dry-run
    python hooks/install.py
    python hooks/install.py --uninstall
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_NAME = "handoff_hook.py"
MARKER = "handoff_hook.py"

EVENTS = (
    # event name, matcher
    ("PreCompact", "auto"),
    ("SessionStart", "compact"),
)


def default_skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def default_settings() -> Path:
    return Path.home() / ".claude" / "settings.json"


def is_ours(entry: object) -> bool:
    """True when this hook entry calls handoff_hook.py."""
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks") or []:
        if not isinstance(hook, dict):
            continue
        values = [hook.get("command"), hook.get("commandWindows")]
        values.extend(hook.get("args") or [])
        for value in values:
            if isinstance(value, str) and MARKER in value:
                return True
    return False


def our_entry(python_exe: str, script: Path) -> dict:
    return {
        "type": "command",
        "command": python_exe,
        "args": ["-X", "utf8", str(script)],
        "timeout": 10,
    }


def merge(settings: dict, python_exe: str, script: Path) -> tuple[dict, list[str]]:
    data = copy.deepcopy(settings)
    hooks = data.get("hooks")
    if hooks is None:
        hooks = {}
        data["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise SystemExit("settings.json: 'hooks' exists but is not an object; aborting.")

    removed = 0
    for event, matcher in EVENTS:
        existing = hooks.get(event)
        if existing is not None and not isinstance(existing, list):
            raise SystemExit(f"settings.json: hooks.{event} is not a list; aborting.")
        kept = []
        for entry in existing or []:
            if is_ours(entry):
                removed += 1
            else:
                kept.append(entry)
        kept.append({"matcher": matcher, "hooks": [our_entry(python_exe, script)]})
        hooks[event] = kept

    note = [f"replaced {removed} existing entry(ies) of this skill"] if removed else []
    return data, note


def unmerge(settings: dict) -> tuple[dict, list[str]]:
    data = copy.deepcopy(settings)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data, ["no 'hooks' object; nothing to remove"]
    removed = 0
    for event, _matcher in EVENTS:
        existing = hooks.get(event)
        if not isinstance(existing, list):
            continue
        kept = [entry for entry in existing if not is_ours(entry)]
        removed += len(existing) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        data.pop("hooks", None)
    return data, [f"removed {removed} entry(ies)"]


def write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install project-handoff hooks.")
    parser.add_argument("--settings", type=Path, default=default_settings())
    parser.add_argument("--skill-dir", type=Path, default=default_skill_dir())
    parser.add_argument("--python", dest="python_exe", default=sys.executable)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)

    script = (args.skill_dir / "scripts" / SCRIPT_NAME).resolve()
    settings_path = args.settings.expanduser().resolve()

    if not args.uninstall and not script.is_file():
        print(f"error: hook script not found: {script}", file=sys.stderr)
        return 2

    if settings_path.is_file():
        try:
            original = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            print(f"error: cannot parse {settings_path}: {type(exc).__name__}", file=sys.stderr)
            print("aborting without changes; fix or back up the file first.", file=sys.stderr)
            return 2
        if not isinstance(original, dict):
            print("error: settings.json is not a JSON object; aborting.", file=sys.stderr)
            return 2
    else:
        original = {}

    if args.uninstall:
        updated, notes = unmerge(original)
        action = "remove"
    else:
        updated, notes = merge(original, args.python_exe, script)
        action = "install"

    print(f"action      : {action}")
    print(f"settings    : {settings_path}")
    if not args.uninstall:
        print(f"python      : {args.python_exe}")
        print(f"hook script : {script}")
    print(f"top-level keys: {', '.join(sorted(updated)) or '(none)'}")
    for note in notes:
        print(f"note        : {note}")

    if updated == original:
        print("result      : no change needed")
        return 0

    changes = [k for k in set(original) | set(updated) if original.get(k) != updated.get(k)]
    print(f"changed keys: {', '.join(sorted(changes))}")

    if args.dry_run:
        print("result      : dry run, nothing written")
        return 0

    if settings_path.is_file():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = settings_path.with_name(settings_path.name + f".bak-{stamp}")
        backup.write_bytes(settings_path.read_bytes())
        try:
            backup.chmod(0o600)
        except OSError:
            pass  # Windows has no POSIX mode; the user profile is already private
        print(f"backup      : {backup}")

    write_atomic(settings_path, updated)
    print("result      : written")
    if not args.uninstall:
        print("next        : start a new session; after one compaction check")
        print(f"              {Path.home() / '.claude' / 'state' / 'project-handoff'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
