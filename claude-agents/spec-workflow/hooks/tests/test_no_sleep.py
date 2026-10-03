"""The no-foreground-sleep gate (gate_no_sleep): 0 = allow the command, 2 = block it.

The gate runs on EVERY shell command, so the two directions are asymmetric exactly as for the push gate: an
over-blocked settle-sleep or script-write gets the hook deleted, while a missed poll costs a login shell per
wake-up. Every case below names which direction it pins. Standard library + pytest only; Python 3.9 compatible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import gate_no_sleep
import hooklib as lib
import hooks

HOOKS_DIR = Path(__file__).resolve().parent.parent
ALLOW = 0
BLOCK = 2


def decide(command: str, tmp_path: Path, background: bool = False, tool: str = "Bash") -> lib.Decision:
    tool_input = {"command": command}
    if background:
        tool_input["run_in_background"] = True
    payload = json.dumps(
        {
            "session_id": "abcd1234-1111-2222-3333-444455556666",
            "cwd": str(tmp_path),
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
        }
    )
    ctx = lib.Context(lib.Payload.parse(payload), environ={}, hooks_dir=HOOKS_DIR, cwd=tmp_path)
    return gate_no_sleep.run(ctx)


# ---------------------------------------------------------------------------------------------------------
# the BLOCK direction: the measured poll shapes
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "sleep 300; cat out.txt",
        'sleep 240; echo "=== push output so far ===" && cat "D:\\\\Temp\\\\tasks\\\\b64.output"',
        "sleep 540; cd worktree && ./venv/Scripts/python.exe scripts/gitlab_wrapper.py pipeline status 561",
        "sleep 10",
        "sleep 5m && echo done",
        "sleep 1h",
        "(sleep 30; echo late) ",
        "Start-Sleep -Seconds 60",
        "Start-Sleep -s 120; Get-Content out.txt",
        "powershell -NoProfile -Command Start-Sleep 60",
        "timeout /t 120",
        "TIMEOUT.EXE /T 30 /NOBREAK",
    ],
)
def test_a_long_foreground_wait_is_blocked(command: str, tmp_path: Path) -> None:
    decision = decide(command, tmp_path)
    assert decision.exit_code == BLOCK, f"{command!r}: expected a block, got {decision.stderr!r}"
    assert "no-foreground-sleep" in decision.stderr


@pytest.mark.parametrize(
    "command",
    [
        "for v1 in $(seq 1 40); do v2=$(python wrapper.py pipeline status 5); echo $v2; sleep 15; done",
        "while ! test -f tmp/done; do sleep $INTERVAL; done",
        "until grep -q green status.txt; do sleep 2; done",
        "for i in 1 2 3; do curl localhost; sleep 1; done",
        "while ($true) { Start-Sleep 5; if (Test-Path x) { break } }",
    ],
)
def test_any_sleep_inside_a_loop_is_blocked(command: str, tmp_path: Path) -> None:
    """a loop around a sleep is polling by definition — the interval, readable or not, does not matter"""
    assert decide(command, tmp_path).exit_code == BLOCK


def test_the_refusal_names_both_sanctioned_shapes(tmp_path: Path) -> None:
    decision = decide("sleep 300 && python scripts/github_wrapper.py get-run 42", tmp_path)
    assert decision.exit_code == BLOCK
    assert "run_in_background: true" in decision.stderr, "the refusal names the background form of the same command"
    assert "wait-run" in decision.stderr and "pipeline wait" in decision.stderr, "the refusal names the wrapper waits"
    assert "parallel-by-default.md" in decision.stderr, "the refusal cites the rule"


# ---------------------------------------------------------------------------------------------------------
# the ALLOW direction: everything that must NOT be refused (an over-blocking gate gets deleted)
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "echo hi",
        "git log -n 5",
        "python scripts/run_tests.py test/test_x.py",
        "sleep 2 && curl -s localhost:8000/health",  # a settle sleep under the threshold
        "sleep 9.9",
        "sleep 500ms",  # unreadable to GNU sleep's grammar: not a readable long wait, no loop -> allow
        "Start-Sleep -Milliseconds 500",
        "timeout 30 pytest test/",  # GNU timeout bounds a command; it is not cmd.exe's `timeout /t`
        'echo "sleep 300"',  # quoted text is not a command
        "git commit -m 'sleep 600 between polls was the bug'",
        "sleep $N",  # unreadable interval, no loop: fail open
        "cat > tmp/poll.sh <<'EOF'\nwhile true; do sleep 30; done\nEOF\nchmod +x tmp/poll.sh",
        "cat <<EOF > notes.md\nNever sleep 600 in a tool call.\nEOF",
        'python -c "import time; time.sleep(60)"',  # quoted; python's own sleep is not this gate's subject
        "asleep 300",  # not the sleep command
        "my_sleep 300",
    ],
)
def test_ordinary_and_settle_commands_pass(command: str, tmp_path: Path) -> None:
    decision = decide(command, tmp_path)
    assert decision.exit_code == ALLOW, f"{command!r}: wrongly refused: {decision.stderr!r}"


@pytest.mark.parametrize(
    "command",
    [
        "sleep 300; cat out.txt",
        "for i in $(seq 1 40); do python wrapper.py pipeline status 5; sleep 15; done",
        "Start-Sleep -Seconds 600",
    ],
)
def test_the_same_wait_as_a_background_task_is_allowed(command: str, tmp_path: Path) -> None:
    """`run_in_background: true` is the sanctioned shape: one call, one process tree, completion re-invokes"""
    assert decide(command, tmp_path, background=True).exit_code == ALLOW


def test_an_empty_command_is_allowed(tmp_path: Path) -> None:
    assert decide("", tmp_path).exit_code == ALLOW


def test_a_crlf_payload_is_read_like_an_lf_one(tmp_path: Path) -> None:
    assert decide("sleep 300\r\ncat out.txt", tmp_path).exit_code == BLOCK
    assert decide("cat > x.sh <<'EOF'\r\nsleep 300\r\nEOF\r\n", tmp_path).exit_code == ALLOW


# ---------------------------------------------------------------------------------------------------------
# through the dispatcher: discovery, order, the tool matcher
# ---------------------------------------------------------------------------------------------------------


def test_the_gate_is_discovered_between_env_vars_and_the_push_gate() -> None:
    names = [g[0] for g in hooks.discover_gates("pre-tool-use", HOOKS_DIR)]
    assert names.index("no-env-vars") < names.index("no-foreground-sleep") < names.index("spec-tdd-gate")


def test_the_dispatcher_blocks_a_foreground_poll_and_leaves_a_write_tool_alone(tmp_path: Path) -> None:
    poll = json.dumps({"tool_name": "Bash", "tool_input": {"command": "sleep 300; cat out.txt"}})
    decision = hooks.dispatch("pre-tool-use", poll, environ={}, cwd=tmp_path, hooks_dir=HOOKS_DIR)
    assert decision.exit_code == BLOCK and "no-foreground-sleep" in decision.stderr
    background = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "sleep 300; cat out.txt", "run_in_background": True}}
    )
    assert hooks.dispatch("pre-tool-use", background, environ={}, cwd=tmp_path, hooks_dir=HOOKS_DIR).exit_code == ALLOW
    write = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "poll.sh", "content": "sleep 300"}})
    assert hooks.dispatch("pre-tool-use", write, environ={}, cwd=tmp_path, hooks_dir=HOOKS_DIR).exit_code == ALLOW
