"""The delivery redesign's hook layer (2026-10-26, project-docs/delivery-redesign-2026-10-26.md):

* merge-steward: where config/delivery.json says merge = steward, no agent writes the trunk directly;
* HANDED_OFF releases a SINGLE-issue run and never a loop run (the issue-loop brake);
* the run watchdog: the brake names it when the Stop payload shows none armed; the re-inject arms it;
* stop-failure-recorder + supervisor.py: an API-error turn end is recorded and judged for a resume;
* wait_for.py: the sanctioned bounded wait for something local.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import gate_issue_loop
import gate_merge_steward
import gate_reinject
import gate_stop_failure
import hooklib as lib
import hooks
import supervisor
import wait_for

HOOKS_DIR = Path(__file__).resolve().parent.parent
SID = "feed1234-1111-2222-3333-444455556666"


@pytest.fixture
def arena(tmp_path: Path) -> Path:
    root = tmp_path / "arena"
    (root / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME).mkdir(parents=True)
    return root


def steward_project(arena: Path, trunk: str = "main") -> Path:
    (arena / "config").mkdir(exist_ok=True)
    (arena / "config" / "delivery.json").write_text(
        json.dumps({"merge": "steward", "verification": "watcher", "trunk": trunk}), encoding="utf-8"
    )
    return arena


def bash(arena: Path, command: str) -> lib.Decision:
    payload = {"session_id": SID, "cwd": arena.as_posix(), "tool_name": "Bash", "tool_input": {"command": command}}
    ctx = lib.Context(lib.Payload.parse(json.dumps(payload)), environ={}, hooks_dir=HOOKS_DIR, cwd=arena)
    return gate_merge_steward.run(ctx)


def seed_run(arena: Path, body: str) -> Path:
    run_dir = arena / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME / "runs" / SID[:8]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / lib.RESUME_FILENAME).write_text(f"SESSION_ID: {SID}\n{body}", encoding="utf-8")
    lib.contract_ack_file(run_dir, lib.contract_version(arena)).write_text("ack\n", encoding="utf-8")
    return run_dir


def stop(arena: Path, **extra: object) -> lib.Decision:
    payload = {"session_id": SID, "cwd": arena.as_posix(), "hook_event_name": "Stop", **extra}
    ctx = lib.Context(lib.Payload.parse(json.dumps(payload)), environ={}, hooks_dir=HOOKS_DIR, cwd=arena)
    return gate_issue_loop.run(ctx)


# ------------------------------------------------------------------------------------------- merge-steward


@pytest.mark.parametrize(
    "command",
    [
        "python scripts/github_wrapper.py merge-pr 77 --method merge",
        'cd "D:/Code Workspace/x" && venv/Scripts/python.exe scripts/gitlab_wrapper.py mr merge 12',
        "gh pr merge 77 --squash",
        "glab mr merge 12",
        "git push origin main",
        'git -C "D:/Code Workspace/x/.claude/worktrees/issue-7" push origin HEAD:main',
        "git push origin +main",
        "git push origin issue-7:refs/heads/main",
        "git push --all origin",
        "git push origin --delete main",
        "python scripts/merge_steward.py --token-stdin tick",
        "python scripts/merge_steward.py --token-file credentials/x.txt verdict --sha abc --conclusion success",
        "python scripts/merge_steward.py tick --dry-run",
        "curl -X PUT https://api.github.com/repos/o/r/pulls/7/merge",
    ],
)
def test_the_trunk_is_written_only_by_the_steward(arena: Path, command: str) -> None:
    decision = bash(steward_project(arena), command)
    assert decision.exit_code == 2, command
    assert "enqueue-pr" in decision.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin issue-7-fix-timeout",
        'git -C "D:/w/issue-7" push origin issue-7-fix-timeout:issue-7-fix-timeout',
        "python scripts/github_wrapper.py enqueue-pr 77",
        "python scripts/merge_steward.py status",
        'git commit -m "after review: git push origin main; gh pr merge 7"',
        "git push origin maintenance",
        "python scripts/run_tests.py test/test_merge_steward.py -k verdict",
        "python -m pytest test/test_github_wrapper.py -k merge-pr",
        "python scripts/merge_steward.py status --json",
    ],
)
def test_everything_else_passes(arena: Path, command: str) -> None:
    assert bash(steward_project(arena), command).exit_code == 0, command


def test_a_project_without_the_steward_is_not_judged(arena: Path) -> None:
    assert bash(arena, "python scripts/github_wrapper.py merge-pr 77").exit_code == 0
    assert bash(arena, "git push origin main").exit_code == 0


def test_the_configured_trunk_name_is_the_one_protected(arena: Path) -> None:
    steward_project(arena, trunk="develop")
    assert bash(arena, "git push origin develop").exit_code == 2
    assert bash(arena, "git push origin main").exit_code == 0


def test_a_broken_delivery_config_fails_open(arena: Path) -> None:
    (arena / "config").mkdir()
    (arena / "config" / "delivery.json").write_text("{not json", encoding="utf-8")
    assert bash(arena, "git push origin main").exit_code == 0


# ------------------------------------------------------------------------------------------------ hand-off


def test_handed_off_releases_a_single_issue_run(arena: Path) -> None:
    seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: HANDED_OFF\nCURRENT_ISSUE: 412\n")
    assert stop(arena).exit_code == 0


@pytest.mark.parametrize("mode", ["unset", "SPEC", "none"])
def test_handed_off_releases_nothing_but_a_single_issue_run(arena: Path, mode: str) -> None:
    """A run whose MODE was lost (a resume that did not carry it) or is not single-issue keeps its brake."""
    seed_run(arena, f"MODE: {mode}\nStatus: IN_PROGRESS\nPhase: HANDED_OFF\nCURRENT_ISSUE: 412\n")
    assert stop(arena).exit_code == 2


@pytest.mark.parametrize("mode", ["AUTO", "ISSUE_LOOP", "issue-loop"])
def test_handed_off_never_releases_a_loop_run(arena: Path, mode: str) -> None:
    seed_run(arena, f"MODE: {mode}\nStatus: IN_PROGRESS\nPhase: HANDED_OFF\nCURRENT_ISSUE: 412\n")
    decision = stop(arena)
    assert decision.exit_code == 2
    assert "SELECT the next workable issue" in decision.stderr


def test_handed_off_must_be_the_whole_value(arena: Path) -> None:
    seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: HANDED_OFF (PR queued)\nCURRENT_ISSUE: 4\n")
    assert stop(arena).exit_code == 2


# ------------------------------------------------------------------------------------------------ watchdog


def test_the_brake_names_an_unarmed_watchdog(arena: Path) -> None:
    seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 4\n")
    decision = stop(arena, session_crons=[])
    assert decision.exit_code == 2 and lib.WATCHDOG_MARK in decision.stderr and "CronCreate" in decision.stderr


def test_an_armed_or_unknown_watchdog_is_not_mentioned(arena: Path) -> None:
    seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 4\n")
    armed = [{"id": "c1", "schedule": lib.WATCHDOG_CRON, "recurring": True, "prompt": lib.WATCHDOG_PROMPT}]
    assert "CronCreate" not in stop(arena, session_crons=armed).stderr
    assert "CronCreate" not in stop(arena).stderr, "an older harness that sends no session_crons is not nagged"


def test_the_reinject_arms_the_watchdog_of_a_registered_run(arena: Path) -> None:
    seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 4\n")
    payload = {"session_id": SID, "cwd": arena.as_posix(), "source": "startup", "hook_event_name": "SessionStart"}
    ctx = lib.Context(lib.Payload.parse(json.dumps(payload)), environ={}, hooks_dir=HOOKS_DIR, cwd=arena)
    out = gate_reinject.run(ctx).stdout
    assert lib.WATCHDOG_PROMPT in out and lib.WATCHDOG_CRON in out
    payload["source"] = "compact"
    ctx = lib.Context(lib.Payload.parse(json.dumps(payload)), environ={}, hooks_dir=HOOKS_DIR, cwd=arena)
    assert lib.WATCHDOG_PROMPT not in gate_reinject.run(ctx).stdout, "a compaction keeps the process and its cron"


def test_kiro_is_never_told_to_arm_a_cron(arena: Path) -> None:
    seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 4\n")
    payload = {"session_id": SID, "cwd": arena.as_posix(), "hook_event_name": "agentSpawn"}
    ctx = lib.Context(lib.Payload.parse(json.dumps(payload)), host=lib.KIRO, environ={}, hooks_dir=HOOKS_DIR, cwd=arena)
    out = gate_reinject.run(ctx).stdout
    assert "Arm this process's run watchdog" not in out and lib.WATCHDOG_PROMPT not in out


# ------------------------------------------------------------------------------------ stop-failure + supervisor


def fail(arena: Path, error: str = "authentication_failed", transcript: Path | None = None) -> lib.Decision:
    payload = {
        "session_id": SID,
        "cwd": arena.as_posix(),
        "hook_event_name": "StopFailure",
        "error": error,
        "error_details": "401 Unauthorized",
        "last_assistant_message": "API Error: 401 Unauthorized",
    }
    if transcript is not None:
        payload["transcript_path"] = str(transcript)
    ctx = lib.Context(lib.Payload.parse(json.dumps(payload)), environ={}, hooks_dir=HOOKS_DIR, cwd=arena)
    return gate_stop_failure.run(ctx)


def request_of(arena: Path) -> Path:
    return supervisor.requests_dir(arena) / f"{SID[:8]}.json"


def test_an_api_error_on_unfinished_work_queues_a_resume(arena: Path) -> None:
    run_dir = seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 4\n")
    assert fail(arena).exit_code == 0
    record = json.loads((run_dir / "stop_failure.json").read_text(encoding="utf-8"))
    assert record["failures"][-1]["error"] == "authentication_failed"
    request = json.loads(request_of(arena).read_text(encoding="utf-8"))
    assert request["issue"] == "4" and request["attempts"] == 0


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: HANDED_OFF\nCURRENT_ISSUE: 4\n", "server_error"),
        ("MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 4\n", "billing_error"),
        ("MODE: unset\nStatus: NOT_STARTED\nPhase: NOT_STARTED\nCURRENT_ISSUE: none\n", "server_error"),
        (
            "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 4\n"
            "AWAITING_USER: waiting on the production credential for the smoke test\n",
            "server_error",
        ),
    ],
)
def test_no_resume_is_queued_for_released_unclaimed_or_incurable(arena: Path, body: str, error: str) -> None:
    run_dir = seed_run(arena, body)
    assert fail(arena, error).exit_code == 0
    assert (run_dir / "stop_failure.json").is_file(), "the failure is recorded either way"
    assert not request_of(arena).exists()


def test_the_dispatcher_never_blocks_a_stop_failure(arena: Path) -> None:
    seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 4\n")
    payload = json.dumps({"session_id": SID, "cwd": arena.as_posix(), "hook_event_name": "StopFailure"})
    decision = hooks.dispatch("stop-failure", payload, environ={}, cwd=arena, hooks_dir=HOOKS_DIR)
    assert decision.exit_code == 0


def test_the_registration_carries_the_stop_failure_event() -> None:
    block = json.loads(hooks.registration_block())
    entry = block["hooks"]["StopFailure"][0]["hooks"][0]
    assert entry["args"][-1] == "stop-failure"


def _rewrite(path: Path, **fields: object) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_the_supervisor_judges_due_waiting_and_exhausted(arena: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 4\n")
    fail(arena)
    now = supervisor._now()
    request = json.loads(request_of(arena).read_text(encoding="utf-8"))
    assert supervisor.judge(request, now)["verdict"] == "waiting", "the run's own watchdog gets the first minutes"
    request["failed_at"] = "2026-01-01T00:00:00Z"
    assert supervisor.judge(request, now)["verdict"] == "due"
    request["attempts"] = supervisor.MAX_ATTEMPTS
    assert supervisor.judge(request, now)["verdict"] == "exhausted"


def test_the_supervisor_clears_a_run_that_finished_or_recovered(arena: Path, tmp_path: Path) -> None:
    run_dir = seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 4\n")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("", encoding="utf-8")
    fail(arena, transcript=transcript)
    request = json.loads(request_of(arena).read_text(encoding="utf-8"))
    reply = {"type": "assistant", "timestamp": "2099-01-01T00:00:00Z", "message": {"model": "claude", "content": []}}
    transcript.write_text(json.dumps(reply) + "\n", encoding="utf-8")
    assert supervisor.judge(request, supervisor._now())["verdict"] == "recovered"
    with (run_dir / lib.RESUME_FILENAME).open("a", encoding="utf-8") as handle:
        handle.write("Phase: DONE\n")
    assert supervisor.judge(request, supervisor._now())["verdict"] == "finished"


def test_note_counts_attempts_and_the_message_carries_the_mark(
    arena: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 4\n")
    fail(arena)
    monkeypatch.setenv(lib.CLAUDE.project_dir_env, str(arena))
    assert supervisor.main(["note", SID[:8], "resumed"]) == 0
    assert json.loads(request_of(arena).read_text(encoding="utf-8"))["attempts"] == 1
    assert supervisor.main(["message", SID[:8]]) == 0
    text = capsys.readouterr().out
    assert lib.WATCHDOG_MARK in text and "continue-work.md" in text and "approves nothing" in text
    assert supervisor.main(["note", SID[:8], "cleared"]) == 0
    assert not request_of(arena).exists()


# ------------------------------------------------------------------------------------------------ wait_for


def test_wait_for_finds_a_file_and_a_line(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("collecting\n=== 12 passed in 3.1s ===\n", encoding="utf-8")
    assert wait_for.main(["--file", str(target), "--timeout-seconds", "1"]) == wait_for.EXIT_FOUND
    assert wait_for.main(["--file", str(target), "--line", r"\d+ passed", "--timeout-seconds", "1"]) == 0


def test_wait_for_times_out_with_exit_11(tmp_path: Path) -> None:
    assert wait_for.main(["--file", str(tmp_path / "never"), "--timeout-seconds", "0.2"]) == wait_for.EXIT_TIMEOUT


def test_wait_for_gives_up_when_the_writer_ended(tmp_path: Path) -> None:
    done = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    pid = int(done.stdout.strip())
    code = wait_for.main(["--file", str(tmp_path / "never"), "--pid", str(pid), "--timeout-seconds", "5"])
    assert code == wait_for.EXIT_GONE


def test_wait_for_refuses_a_timeout_over_the_tool_ceiling(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        wait_for.main(["--file", str(tmp_path / "x"), "--timeout-seconds", "900"])
