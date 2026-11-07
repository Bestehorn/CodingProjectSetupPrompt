"""no-idle-wait: a turn may not end in order to wait. The gate reads the LAST assistant text of the transcript
the Stop payload names; the fixtures write that transcript line by line, as the harness does."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import gate_no_idle_wait
import hooklib as lib

HOOKS_DIR = Path(__file__).resolve().parent.parent
SID = "abcd1234-1111-2222-3333-444455556666"


def record(kind: str, text: str, *, model: str = "claude", tool_use: bool = False) -> str:
    content = [{"type": "text", "text": text}] if text else []
    if tool_use:
        content.append({"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "echo"}})
    return json.dumps({"type": kind, "message": {"role": kind, "model": model, "content": content}})


def write_transcript(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def decide(arena: Path, transcript: Path | None, environ: dict | None = None) -> lib.Decision:
    payload = {"session_id": SID, "cwd": arena.as_posix(), "hook_event_name": "Stop"}
    if transcript is not None:
        payload["transcript_path"] = str(transcript)
    ctx = lib.Context(lib.Payload.parse(json.dumps(payload)), environ=environ or {}, hooks_dir=HOOKS_DIR, cwd=arena)
    return gate_no_idle_wait.run(ctx)


@pytest.fixture
def arena(tmp_path: Path) -> Path:
    root = tmp_path / "arena"
    (root / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME).mkdir(parents=True)
    return root


WAITING = (
    "Trunk's CI on the merge commit is running, and I'm waiting on it in the background. "
    "The dev deploy follows it and gives task 6.2's verdict."
)
NOTIFY = "The patch is ready. I'm waiting for the gated red run to finish; its exit line will notify me."
WORKING = "Wave 7 is green: 14 passed. Next I'll open the PR and write the issue note."
VERDICT = "CLOSE: NO — 1 blocker\n| Step | State | Detail |\n|---|---|---|\n| 3 | CI | waiting for run 123 |"


def test_a_turn_that_ends_to_wait_in_the_background_is_refused(arena: Path, tmp_path: Path) -> None:
    transcript = write_transcript(tmp_path / "t.jsonl", record("user", "go"), record("assistant", WAITING))
    decision = decide(arena, transcript)
    assert decision.exit_code == 2
    assert "FOREGROUND" in decision.stderr and "--timeout-seconds 540" in decision.stderr
    assert "background task dies with the session's process" in decision.stderr


@pytest.mark.parametrize(
    "text",
    [
        "Waiting on CI run 8821.",
        "Pushed once. I'll pick this up when the pipeline finishes.",
        "Everything unblocked is done, so I'll wait for the deploy.",
    ],
)
def test_a_session_announcing_its_own_wait_is_refused(arena: Path, tmp_path: Path, text: str) -> None:
    transcript = write_transcript(tmp_path / "t.jsonl", record("assistant", text))
    assert decide(arena, transcript).exit_code == 2, text


@pytest.mark.parametrize(
    "text",
    [
        "Nothing to change on your side; you only need to wait for the deploy if you want to watch it.",
        "PR #77 is queued. The watcher closes issue #412 when the deploy completes; there is nothing to wait for.",
        "The steward lands it: a session never waits on the trunk run.",
    ],
)
def test_explaining_a_wait_is_not_ending_the_turn_to_wait(arena: Path, tmp_path: Path, text: str) -> None:
    transcript = write_transcript(tmp_path / "t.jsonl", record("assistant", text))
    assert decide(arena, transcript).exit_code == 0, text


def test_its_exit_line_will_notify_me_is_refused(arena: Path, tmp_path: Path) -> None:
    transcript = write_transcript(tmp_path / "t.jsonl", record("assistant", NOTIFY))
    assert decide(arena, transcript).exit_code == 2


def test_a_working_final_text_is_allowed_and_resets_the_counter(arena: Path, tmp_path: Path) -> None:
    transcript = write_transcript(tmp_path / "t.jsonl", record("assistant", WAITING))
    assert decide(arena, transcript).exit_code == 2
    counter = lib.counter_path(arena / ".claude" / "agent-state", "wait", SID)
    assert lib.counter_read(counter) == 1
    write_transcript(transcript, record("assistant", WORKING))
    assert decide(arena, transcript).exit_code == 0
    assert lib.counter_read(counter) == 0, "a final text that does not wait resets the consecutive count"


def test_a_completion_block_verdict_is_the_other_gates_business(arena: Path, tmp_path: Path) -> None:
    transcript = write_transcript(tmp_path / "t.jsonl", record("assistant", VERDICT))
    assert decide(arena, transcript).exit_code == 0


def test_no_transcript_path_allows(arena: Path) -> None:
    assert decide(arena, None).exit_code == 0


def test_a_missing_transcript_allows(arena: Path, tmp_path: Path) -> None:
    assert decide(arena, tmp_path / "absent.jsonl").exit_code == 0


def test_the_synthetic_no_response_is_skipped(arena: Path, tmp_path: Path) -> None:
    """The harness's own `<synthetic>` message is not the model's final text; the one before it is."""
    transcript = write_transcript(
        tmp_path / "t.jsonl",
        record("assistant", WAITING),
        record("user", "<task-notification><status>stopped</status></task-notification>"),
        record("assistant", "No response requested.", model="<synthetic>"),
    )
    assert decide(arena, transcript).exit_code == 2


def test_the_last_text_decides_not_an_earlier_one(arena: Path, tmp_path: Path) -> None:
    transcript = write_transcript(
        tmp_path / "t.jsonl",
        record("assistant", WAITING),
        record("assistant", "", tool_use=True),
        record("user", "result"),
        record("assistant", WORKING),
    )
    assert decide(arena, transcript).exit_code == 0


def test_the_cap_is_half_the_familys_and_stands_the_gate_down(arena: Path, tmp_path: Path) -> None:
    transcript = write_transcript(tmp_path / "t.jsonl", record("assistant", NOTIFY))
    environ = {"CLAUDE_CODE_STOP_HOOK_BLOCK_CAP": "4"}
    codes = [decide(arena, transcript, environ).exit_code for _ in range(3)]
    assert codes == [2, 2, 0], "cap 4 // 2 = 2 refusals, then it stands down with a note"
    assert lib.counter_is_capped(lib.counter_path(arena / ".claude" / "agent-state", "wait", SID))


def test_transcript_tool_calls_since_counts_only_assistant_tool_calls(tmp_path: Path) -> None:
    transcript = write_transcript(tmp_path / "t.jsonl", record("assistant", WORKING))
    counter = tmp_path / "counters" / "loop-abcd1234.count"
    assert lib.transcript_tool_calls_since(counter, transcript) is None, "the first observation is not progress"
    tool_result = json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}})
    quoted = json.dumps({"type": "user", "message": {"content": '"type":"tool_use" quoted in a prompt'}})
    with transcript.open("a", encoding="utf-8") as handle:
        for _ in range(3):
            handle.write(record("assistant", "", tool_use=True) + "\n")
            handle.write(tool_result + "\n")
        handle.write(quoted + "\n")
    assert lib.transcript_tool_calls_since(counter, transcript) == 3
    assert lib.transcript_tool_calls_since(counter, transcript) == 0, "nothing appended since the last look"
    assert lib.transcript_tool_calls_since(counter, None) is None
