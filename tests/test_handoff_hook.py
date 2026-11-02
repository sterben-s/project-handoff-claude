#!/usr/bin/env python3
"""Synthetic tests for handoff_hook.py. Standard library only.

Run with:
    python -X utf8 tests/test_handoff_hook.py

These tests exercise the script's own logic. They do not prove that a live
Claude Code build delivers the hook events or injects additionalContext.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "handoff_hook.py"


def load_module():
    spec = importlib.util.spec_from_file_location("handoff_hook", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = load_module()


def event(name, sid="s-1", **extra):
    payload = {"hook_event_name": name, "session_id": sid}
    payload.update(extra)
    return payload


def state_file(root, sid):
    return Path(root) / (mod.session_key(sid) + ".json")


def read_state(root, sid):
    return json.loads(state_file(root, sid).read_text(encoding="utf-8"))


def test_manual_compaction_not_counted():
    with tempfile.TemporaryDirectory() as root:
        assert mod.process(event("PreCompact", trigger="manual"), root) is None
        assert not state_file(root, "s-1").exists()
        assert mod.process(event("SessionStart", source="compact"), root) is None


def test_threshold_and_cooldown():
    with tempfile.TemporaryDirectory() as root:
        for _ in range(2):
            mod.process(event("PreCompact", trigger="auto"), root)
        assert read_state(root, "s-1")["auto_count"] == 2
        assert mod.process(event("SessionStart", source="compact"), root) is None

        mod.process(event("PreCompact", trigger="auto"), root)
        out = mod.process(event("SessionStart", source="compact"), root)
        assert out is not None
        data = out["hookSpecificOutput"]
        assert data["hookEventName"] == "SessionStart"
        assert "第 3 次" in data["additionalContext"]

        state = read_state(root, "s-1")
        assert state["auto_count"] == 3
        assert state["next_reminder_at"] == 6

        # A second compact SessionStart must not repeat the same reminder.
        assert mod.process(event("SessionStart", source="compact"), root) is None

        for _ in range(3):
            mod.process(event("PreCompact", trigger="auto"), root)
        out = mod.process(event("SessionStart", source="compact"), root)
        assert out is not None
        assert "第 6 次" in out["hookSpecificOutput"]["additionalContext"]
        assert read_state(root, "s-1")["next_reminder_at"] == 9


def test_manual_between_autos_does_not_count():
    with tempfile.TemporaryDirectory() as root:
        mod.process(event("PreCompact", trigger="auto"), root)
        mod.process(event("PreCompact", trigger="manual"), root)
        mod.process(event("PreCompact", trigger="auto"), root)
        assert read_state(root, "s-1")["auto_count"] == 2


def test_sessions_are_isolated():
    with tempfile.TemporaryDirectory() as root:
        for _ in range(3):
            mod.process(event("PreCompact", "session-a", trigger="auto"), root)
        assert mod.process(event("SessionStart", "session-b", source="compact"), root) is None
        out = mod.process(event("SessionStart", "session-a", source="compact"), root)
        assert out is not None


def test_missing_or_bad_fields_fail_open():
    with tempfile.TemporaryDirectory() as root:
        cases = [
            None,
            "text",
            3,
            [],
            {},
            {"hook_event_name": "PreCompact"},
            {"hook_event_name": "PreCompact", "session_id": ""},
            {"session_id": "s-1"},
            {"hook_event_name": "Unknown", "session_id": "s-1"},
        ]
        for case in cases:
            assert mod.process(case, root) is None


def test_subagent_events_ignored():
    with tempfile.TemporaryDirectory() as root:
        assert (
            mod.process(
                event("PreCompact", trigger="auto", agent_id="agent-1"), root
            )
            is None
        )
        assert not state_file(root, "s-1").exists()


def test_corrupt_state_is_preserved():
    with tempfile.TemporaryDirectory() as root:
        path = state_file(root, "s-1")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json", encoding="utf-8")
        assert mod.process(event("PreCompact", trigger="auto"), root) is None
        assert path.read_text(encoding="utf-8") == "not json"


def test_invalid_utf8_state_fails_open():
    with tempfile.TemporaryDirectory() as root:
        path = state_file(root, "s-1")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\x00bad")
        assert mod.process(event("PreCompact", trigger="auto"), root) is None


def test_cli_utf8_bom_and_silent_success():
    with tempfile.TemporaryDirectory() as root:
        env = {**os.environ, "PROJECT_HANDOFF_STATE_DIR": root}
        payload = b"\xef\xbb\xbf" + json.dumps(
            event("PreCompact", "cli-1", trigger="auto")
        ).encode("utf-8")
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT)],
            input=payload,
            capture_output=True,
            env=env,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == b""
        assert read_state(root, "cli-1")["auto_count"] == 1


def test_cli_emits_checkpoint_json():
    with tempfile.TemporaryDirectory() as root:
        env = {**os.environ, "PROJECT_HANDOFF_STATE_DIR": root}
        for _ in range(3):
            mod.process(event("PreCompact", "cli-2", trigger="auto"), root)
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT)],
            input=json.dumps(event("SessionStart", "cli-2", source="compact")).encode(
                "utf-8"
            ),
            capture_output=True,
            env=env,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout.decode("utf-8"))
        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "第 3 次" in output["hookSpecificOutput"]["additionalContext"]


def test_cli_malformed_stdin_exits_zero():
    with tempfile.TemporaryDirectory() as root:
        env = {**os.environ, "PROJECT_HANDOFF_STATE_DIR": root}
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT)],
            input=b"not json at all",
            capture_output=True,
            env=env,
            timeout=30,
        )
        assert result.returncode == 0
        assert result.stdout == b""


def test_concurrent_processes_do_not_lose_updates():
    with tempfile.TemporaryDirectory() as root:
        env = {**os.environ, "PROJECT_HANDOFF_STATE_DIR": root}
        payload = json.dumps(
            event("PreCompact", "concurrent", trigger="auto")
        ).encode("utf-8")
        procs = [
            subprocess.Popen(
                [sys.executable, "-X", "utf8", str(SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            for _ in range(6)
        ]
        for proc in procs:
            proc.communicate(payload, timeout=60)
        assert read_state(root, "concurrent")["auto_count"] == 6


TESTS = [
    test_manual_compaction_not_counted,
    test_threshold_and_cooldown,
    test_manual_between_autos_does_not_count,
    test_sessions_are_isolated,
    test_missing_or_bad_fields_fail_open,
    test_subagent_events_ignored,
    test_corrupt_state_is_preserved,
    test_invalid_utf8_state_fails_open,
    test_cli_utf8_bom_and_silent_success,
    test_cli_emits_checkpoint_json,
    test_cli_malformed_stdin_exits_zero,
    test_concurrent_processes_do_not_lose_updates,
]


def main():
    failed = 0
    for test in TESTS:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - test runner reports all failures
            failed += 1
            print(f"FAIL {test.__name__}: {exc!r}")
        else:
            print(f"ok   {test.__name__}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
