"""The session endings (2026-11-02, project-docs/session-endings-analysis-2026-11-01.md):

* session-verdict: a released work run ENDS with `SESSION: CAN CLOSE | NEEDS YOU | NOT DONE — …` and its table;
* archive-after-verdict: a work session is archived only after its CAN CLOSE verdict is printed in that turn;
* issue-loop-gate: HANDED_OFF releases only after the wrapper's `check-handoff` exits 0; QUEUED says how to wait;
* continuous-work-reinject: a released run is never told to arm a watchdog (E1);
* no-idle-wait: a SESSION verdict is a Completion Block.
The transcripts are written the way the harness writes them: one JSON record per line.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import pytest

import gate_archive_verdict
import gate_issue_loop
import gate_no_idle_wait
import gate_reinject
import gate_session_verdict
import hooklib as lib
import hooks

HOOKS_DIR = Path(__file__).resolve().parent.parent
SID = "beef5678-1111-2222-3333-444455556666"
SINGLE_DONE = "MODE: SINGLE_ISSUE\nStatus: COMPLETED\nPhase: DONE\nCURRENT_ISSUE: 1486\nAWAITING_USER: none\n"
NINE_ROWS = "\n".join(f"| {n} | check {n} | ✅ | fine |" for n in range(1, 10))
CLOSE_FORM = (
    "SESSION: CAN CLOSE — 9/9 checks\n\n| # | Check | ✓ | Detail |\n|---|---|---|---|\n"
    f"{NINE_ROWS}\n\nIssues\n- #1486 worked → landed — PR #1519\n"
)


@pytest.fixture
def arena(tmp_path: Path) -> Path:
    root = tmp_path / "arena"
    (root / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME).mkdir(parents=True)
    return root


def seed_run(arena: Path, body: str) -> Path:
    run_dir = arena / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME / "runs" / SID[:8]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / lib.RESUME_FILENAME).write_text(f"SESSION_ID: {SID}\n{body}", encoding="utf-8")
    # as session-register seeds it: no spec workflow, so the evidence gate stands aside
    (run_dir / "workflow_state.md").write_text(
        f"SESSION_ID: {SID}\nCURRENT_SPEC: none\nPhase: NOT_STARTED\nStatus: NOT_STARTED\n", encoding="utf-8"
    )
    lib.contract_ack_file(run_dir, lib.contract_version(arena)).write_text("ack\n", encoding="utf-8")
    return run_dir


def prompt(text: str, meta: bool = False) -> dict:
    record = {"type": "user", "message": {"role": "user", "content": text}}
    if meta:
        record["isMeta"] = True
    return record


def said(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "model": "claude", "content": [{"type": "text", "text": text}]},
    }


def called(name: str) -> dict:
    block = {"type": "tool_use", "id": "t1", "name": name, "input": {}}
    return {"type": "assistant", "message": {"role": "assistant", "model": "claude", "content": [block]}}


def result() -> dict:
    content = [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]
    return {"type": "user", "message": {"role": "user", "content": content}}


def transcript(tmp_path: Path, *records: dict) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def context(arena: Path, path: Optional[Path], environ: Optional[dict] = None, **extra: object) -> lib.Context:
    payload = {"session_id": SID, "cwd": arena.as_posix(), "hook_event_name": "Stop", **extra}
    if path is not None:
        payload["transcript_path"] = str(path)
    return lib.Context(lib.Payload.parse(json.dumps(payload)), environ=environ or {}, hooks_dir=HOOKS_DIR, cwd=arena)


def verdict(arena: Path, path: Optional[Path], environ: Optional[dict] = None) -> lib.Decision:
    return gate_session_verdict.run(context(arena, path, environ))


# ------------------------------------------------------------------------------------------- session-verdict


@pytest.mark.parametrize(
    ("state", "head"),
    [
        (SINGLE_DONE, "CAN CLOSE — 2/2 issues delivered"),
        (SINGLE_DONE.replace("none", "waiting on the operator to approve the prod deploy"), "NEEDS YOU — approve prod"),
        (SINGLE_DONE, "NOT DONE — #1462 waits for the queue; the steward has it"),
    ],
)
def test_a_valid_block_ends_the_turn(arena: Path, tmp_path: Path, state: str, head: str) -> None:
    seed_run(arena, state)
    block = f"Answering your question first.\n\nSESSION: {head}\n\n" + lib.SESSION_TEMPLATE.split("\n", 2)[2]
    assert verdict(arena, transcript(tmp_path, prompt("go"), said(block))).exit_code == 0


def test_the_template_itself_passes(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    assert verdict(arena, transcript(tmp_path, prompt("go"), said(lib.SESSION_TEMPLATE))).exit_code == 0


def test_text_after_the_table_is_refused(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    decision = verdict(arena, transcript(tmp_path, prompt("go"), said(lib.SESSION_TEMPLATE + "\n- What shipped: x")))
    assert decision.exit_code == 2 and "text after the table" in decision.stderr
    assert lib.SESSION_TEMPLATE.splitlines()[0] in decision.stderr, "the block message prints the template"


def test_a_prose_ending_is_refused(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    decision = verdict(arena, transcript(tmp_path, prompt("go"), said("Issue #1486 is merged. What shipped: ...")))
    assert decision.exit_code == 2 and "no `SESSION:" in decision.stderr


def test_needs_you_without_a_recorded_reason_is_refused(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    block = lib.SESSION_TEMPLATE.replace("CAN CLOSE — 2/2 issues delivered", "NEEDS YOU — approve it")
    decision = verdict(arena, transcript(tmp_path, prompt("go"), said(block)))
    assert decision.exit_code == 2 and "no AWAITING_USER" in decision.stderr


def test_can_close_with_a_recorded_reason_is_refused(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE.replace("AWAITING_USER: none", "AWAITING_USER: waiting on the prod credential"))
    decision = verdict(arena, transcript(tmp_path, prompt("go"), said(lib.SESSION_TEMPLATE)))
    assert decision.exit_code == 2 and "the head is NEEDS YOU" in decision.stderr


def test_an_unreleased_run_is_the_brakes_business(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 1486\n")
    assert verdict(arena, transcript(tmp_path, prompt("go"), said("still working"))).exit_code == 0


@pytest.mark.parametrize("mode", ["unset", "SPEC", "none"])
def test_a_run_that_is_not_a_work_run_is_not_judged(arena: Path, tmp_path: Path, mode: str) -> None:
    seed_run(arena, SINGLE_DONE.replace("SINGLE_ISSUE", mode))
    assert verdict(arena, transcript(tmp_path, prompt("go"), said("done, in prose"))).exit_code == 0


def test_a_plain_chat_is_not_judged(arena: Path, tmp_path: Path) -> None:
    assert verdict(arena, transcript(tmp_path, prompt("hi"), said("hello in prose"))).exit_code == 0


def test_a_watchdog_tick_is_exempt(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    path = transcript(
        tmp_path,
        prompt("go"),
        said(lib.SESSION_TEMPLATE),
        prompt(lib.WATCHDOG_PROMPT, meta=True),
        said("idle"),
    )
    assert verdict(arena, path).exit_code == 0


def test_a_task_notification_does_not_start_a_turn(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    path = transcript(
        tmp_path,
        prompt("go"),
        said(lib.SESSION_TEMPLATE),
        prompt("<task-notification><status>completed</status></task-notification>"),
        said("The background run finished; nothing changes."),
    )
    assert verdict(arena, path).exit_code == 2, "the turn's last text is prose, so the verdict must be repeated"


def test_an_archive_after_a_valid_can_close_is_exempt(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    close = "<command-name>/close-session</command-name>"
    path = transcript(
        tmp_path,
        prompt(close),
        said(CLOSE_FORM),
        called(gate_archive_verdict.ARCHIVE_TOOL),
        result(),
        said("Session archived."),
    )
    assert verdict(arena, path).exit_code == 0
    bare = transcript(
        tmp_path,
        prompt(close),
        said("All clean."),
        called(gate_archive_verdict.ARCHIVE_TOOL),
        result(),
        said("Archived."),
    )
    assert verdict(arena, bare).exit_code == 2, "an archive does not replace the verdict"


def test_the_close_session_form_with_its_issues_block_passes(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    path = transcript(tmp_path, prompt("<command-name>/close-session</command-name>"), said(CLOSE_FORM))
    assert verdict(arena, path).exit_code == 0
    other = transcript(tmp_path, prompt("<command-name>/work-issue</command-name>"), said(CLOSE_FORM))
    assert verdict(arena, other).exit_code == 2, "the Issues block belongs to the close-out form only"


def test_no_transcript_fails_open(arena: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    assert verdict(arena, None).exit_code == 0


def test_the_cap_stands_the_gate_down(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    path = transcript(tmp_path, prompt("go"), said("prose"))
    environ = {"CLAUDE_CODE_STOP_HOOK_BLOCK_CAP": "4"}
    codes = [verdict(arena, path, environ).exit_code for _ in range(3)]
    assert codes == [2, 2, 0], "cap 4 // 2 = 2 refusals, then it stands down with a note"
    assert lib.counter_is_capped(lib.counter_path(arena / ".claude" / "agent-state", "verdict", SID))


def test_a_turn_an_earlier_gate_refuses_is_not_piled_on(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    ctx = context(arena, transcript(tmp_path, prompt("go"), said("prose")))
    ctx.blocked_by.append("no-idle-wait")
    assert gate_session_verdict.run(ctx).exit_code == 0


# ---------------------------------------------------------------------------------------- archive-after-verdict


def archive(arena: Path, path: Optional[Path], tool: str = gate_archive_verdict.ARCHIVE_TOOL) -> lib.Decision:
    return gate_archive_verdict.run(context(arena, path, tool_name=tool, hook_event_name="PreToolUse"))


def test_an_archive_after_a_can_close_verdict_in_the_turn_is_allowed(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    assert archive(arena, transcript(tmp_path, prompt("close"), said(CLOSE_FORM))).exit_code == 0


def test_an_archive_without_a_verdict_is_refused(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    decision = archive(arena, transcript(tmp_path, prompt("close"), said("Everything is clean.")))
    assert decision.exit_code == 2 and "SESSION: CAN CLOSE" in decision.stderr


def test_a_verdict_of_an_earlier_turn_does_not_count(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    path = transcript(
        tmp_path, prompt("work"), said(lib.SESSION_TEMPLATE), prompt("now archive it"), said("Archiving.")
    )
    assert archive(arena, path).exit_code == 2


def test_a_not_done_verdict_never_archives(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    block = lib.SESSION_TEMPLATE.replace("CAN CLOSE — 2/2 issues delivered", "NOT DONE — #1462 is queued")
    assert archive(arena, transcript(tmp_path, prompt("close"), said(block))).exit_code == 2


def test_the_archive_gate_fails_open_and_stays_in_scope(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    assert archive(arena, None).exit_code == 0, "no transcript"
    assert archive(arena, transcript(tmp_path, prompt("x"), said("y")), tool="Bash").exit_code == 0, "another tool"
    seed_run(arena, SINGLE_DONE.replace("SINGLE_ISSUE", "unset"))
    assert archive(arena, transcript(tmp_path, prompt("archive this chat"), said("ok"))).exit_code == 0, "a plain chat"


# ---------------------------------------------------------------------------------- issue-loop: check-handoff


FAKE_WRAPPER = """import sys, time
args = sys.argv[1:]
if args[:1] == ["check-handoff"]:
    number = args[1]
    if number in ("1486", "1"):
        print("may be handed off"); sys.exit(0)
    if number == "1488":
        print("open item not post-deploy: update the operator guide"); sys.exit(4)
    if number == "500":
        print("API error"); sys.exit(1)
    if number == "900":
        time.sleep(5); sys.exit(0)
if args[:1] == ["check-landed"]:
    numbers = args[1:]
    if "500" in numbers:
        print("API error"); sys.exit(1)
    if "1537" in numbers:
        print("PR #1537: still queued"); print("PR #1539: returned: queue-conflict"); sys.exit(4)
    print("every PR has landed"); sys.exit(0)
sys.exit(2)
"""


def with_wrapper(arena: Path) -> Path:
    (arena / "scripts").mkdir(exist_ok=True)
    (arena / "scripts" / "github_wrapper.py").write_text(FAKE_WRAPPER, encoding="utf-8")
    return arena


def brake(arena: Path) -> lib.Decision:
    return gate_issue_loop.run(context(arena, None))


def handed_off(issue: str, awaiting: str = "none") -> str:
    return (
        f"MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: HANDED_OFF\nCURRENT_ISSUE: {issue}\nPR: 1519\n"
        f"AWAITING_USER: {awaiting}\n"
    )


def test_a_hand_off_check_handoff_accepts_is_released(arena: Path) -> None:
    seed_run(with_wrapper(arena), handed_off("1486"))
    assert brake(arena).exit_code == 0


def test_a_hand_off_check_handoff_refuses_is_held_with_its_reasons(arena: Path) -> None:
    seed_run(with_wrapper(arena), handed_off("1488"))
    decision = brake(arena)
    assert decision.exit_code == 2
    assert "open item not post-deploy: update the operator guide" in decision.stderr
    assert "wait-landed 1519 --timeout-seconds 540" in decision.stderr


def test_every_issue_of_the_run_must_pass(arena: Path) -> None:
    seed_run(with_wrapper(arena), handed_off("1486, 1488"))
    decision = brake(arena)
    assert decision.exit_code == 2 and "#1488" in decision.stderr and "#1486" not in decision.stderr


def test_a_recorded_reason_releases_before_the_hand_off_check(arena: Path) -> None:
    seed_run(with_wrapper(arena), handed_off("1488", "the operator must run the live smoke check on prod"))
    assert brake(arena).exit_code == 0


@pytest.mark.parametrize("issue", ["500", "none"])
def test_no_verdict_fails_open_with_a_note(arena: Path, issue: str) -> None:
    seed_run(with_wrapper(arena), handed_off(issue))
    decision = brake(arena)
    assert decision.exit_code == 0 and "no verdict on the hand-off" in decision.stderr


def test_a_missing_wrapper_fails_open(arena: Path) -> None:
    seed_run(arena, handed_off("1488"))
    assert brake(arena).exit_code == 0


def test_a_check_that_times_out_fails_open(arena: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate_issue_loop, "HANDOFF_TIMEOUT_SECONDS", 1)
    seed_run(with_wrapper(arena), handed_off("900"))
    decision = brake(arena)
    assert decision.exit_code == 0 and "could not run" in decision.stderr


def steward_config(arena: Path) -> None:
    (arena / "config").mkdir(exist_ok=True)
    (arena / "config" / "delivery.json").write_text(
        json.dumps({"merge": "steward", "verification": "watcher", "trunk": "main"}), encoding="utf-8"
    )


def done(issue: str, phase: str = "DONE") -> str:
    return (
        f"MODE: SINGLE_ISSUE\nStatus: COMPLETED\nPhase: {phase}\nCURRENT_ISSUE: {issue}\nPR: 1519\n"
        "AWAITING_USER: none\n"
    )


def test_done_under_the_steward_is_checked_like_a_hand_off(arena: Path) -> None:
    steward_config(with_wrapper(arena))
    seed_run(arena, done("1488"))
    decision = brake(arena)
    assert (
        decision.exit_code == 2 and "Phase DONE" in decision.stderr and "update the operator guide" in decision.stderr
    )
    seed_run(arena, done("1486"))
    assert brake(arena).exit_code == 0, "a delivered issue passes check-handoff and is released"


def test_done_without_queue_delivery_is_not_checked(arena: Path) -> None:
    seed_run(with_wrapper(arena), done("1488"))
    decision = brake(arena)
    assert decision.exit_code == 0 and "no verdict" not in decision.stderr


@pytest.mark.parametrize("phase", ["ABANDONED", "ESCALATED", "CANCELLED"])
def test_an_honest_non_completion_is_not_checked(arena: Path, phase: str) -> None:
    steward_config(with_wrapper(arena))
    seed_run(arena, done("1488", phase))
    assert brake(arena).exit_code == 0


def test_a_queued_run_is_told_how_to_wait(arena: Path) -> None:
    seed_run(
        with_wrapper(arena), "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: QUEUED\nCURRENT_ISSUE: 1462\nPR: 1540\n"
    )
    decision = brake(arena)
    assert decision.exit_code == 2
    assert "scripts/github_wrapper.py wait-landed 1540 --timeout-seconds 540" in decision.stderr
    assert "Exit 10" in decision.stderr


def test_one_refusal_per_turn_end(arena: Path, tmp_path: Path) -> None:
    """The brake refuses an unready hand-off; the verdict gate (released by the library's reading) stays quiet."""
    seed_run(with_wrapper(arena), handed_off("1488"))
    path = transcript(tmp_path, prompt("go"), said("Handed off."))
    payload = {"session_id": SID, "cwd": arena.as_posix(), "hook_event_name": "Stop", "transcript_path": str(path)}
    decision = hooks.dispatch("stop", json.dumps(payload), environ={}, cwd=arena, hooks_dir=HOOKS_DIR)
    assert decision.exit_code == 2
    assert "issue-loop-gate" in decision.stderr and "session-verdict" not in decision.stderr


def test_a_finished_run_without_its_verdict_is_refused_through_the_dispatcher(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    path = transcript(tmp_path, prompt("go"), said("Issue #1486 is closed. Details follow."))
    payload = {"session_id": SID, "cwd": arena.as_posix(), "hook_event_name": "Stop", "transcript_path": str(path)}
    decision = hooks.dispatch("stop", json.dumps(payload), environ={}, cwd=arena, hooks_dir=HOOKS_DIR)
    assert decision.exit_code == 2 and "session-verdict" in decision.stderr


# --------------------------------------------------------------------------------------- reinject and idle-wait


def startup(arena: Path) -> str:
    payload = {"session_id": SID, "cwd": arena.as_posix(), "source": "startup", "hook_event_name": "SessionStart"}
    ctx = lib.Context(lib.Payload.parse(json.dumps(payload)), environ={}, hooks_dir=HOOKS_DIR, cwd=arena)
    return gate_reinject.run(ctx).stdout


@pytest.mark.parametrize(
    "state",
    [
        SINGLE_DONE,
        handed_off("1486"),
        SINGLE_DONE.replace("COMPLETED", "IDLE"),
        SINGLE_DONE.replace("Phase: DONE", "Phase: ESCALATED"),
        "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: FIX\nAWAITING_USER: waiting on the prod credential\n",
    ],
)
def test_a_finished_run_is_never_told_to_arm_a_watchdog(arena: Path, state: str) -> None:
    seed_run(arena, state)
    out = startup(arena)
    assert "Arm this process's run watchdog" not in out and lib.WATCHDOG_PROMPT not in out


@pytest.mark.parametrize(
    "state",
    [
        "MODE: unset\nStatus: NOT_STARTED\nPhase: NOT_STARTED\nCURRENT_ISSUE: none\nAWAITING_USER: none\n",
        "MODE: SINGLE_ISSUE\nStatus: IDLE\nPhase: LOAD_ISSUES\n",
    ],
)
def test_the_idle_seed_is_told_to_arm_it(arena: Path, state: str) -> None:
    """The commands arm the watchdog exactly as the session-start context prints it — so the fresh seed gets it."""
    seed_run(arena, state)
    assert lib.WATCHDOG_PROMPT in startup(arena)


def test_an_unfinished_run_still_arms_it(arena: Path) -> None:
    seed_run(arena, "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: QUEUED\nCURRENT_ISSUE: 1462\n")
    assert lib.WATCHDOG_PROMPT in startup(arena)


def test_a_session_verdict_counts_as_a_completion_block(arena: Path, tmp_path: Path) -> None:
    text = "Nothing is left for me to wait for.\n\n" + lib.SESSION_TEMPLATE.replace(
        "CAN CLOSE — 2/2 issues delivered", "NOT DONE — waiting for the deploy check, the watcher has it"
    )
    path = transcript(tmp_path, prompt("go"), said(text))
    assert gate_no_idle_wait.run(context(arena, path)).exit_code == 0


# ------------------------------------------------------------------------------------------------ the library


def test_the_current_turn_reader(tmp_path: Path) -> None:
    path = transcript(
        tmp_path,
        prompt("first"),
        said("old"),
        prompt("second"),
        said("a"),
        called("Bash"),
        result(),
        prompt("Stop hook feedback: refused", meta=True),
        said("b"),
    )
    turn = lib.transcript_current_turn(path)
    assert turn is not None and turn.prompt == "second"
    assert turn.events == [("text", "a"), ("tool", "Bash"), ("text", "b")]
    assert lib.transcript_current_turn(None) is None
    assert lib.transcript_current_turn(tmp_path / "absent.jsonl") is None


def test_the_last_session_line_decides(tmp_path: Path) -> None:
    text = "Earlier: SESSION: NOT DONE — old\n\n" + lib.SESSION_TEMPLATE
    assert lib.session_head(text) == "CAN CLOSE"
    head, problems = lib.session_verdict_problems("SESSION: CAN CLOSE — " + "x" * 200 + "\n\n|a|\n|-|\n", False, False)
    assert head == "CAN CLOSE" and any("characters after the dash" in p for p in problems)


def _names(event: str) -> List[str]:
    return [g[0] for g in hooks.discover_gates(event, HOOKS_DIR)]


# ------------------------------------------------------------------------------------- review fixes 1, 2, 4-7


@pytest.mark.parametrize(
    ("row", "named"),
    [
        ("| #1488 | blocked: deploy red | 4/4 | #1519 landed | you |", "#1488"),
        ("| #1488 | returned: queue-conflict | 3/4 | #1519 | backlog |", "#1488"),
        ("| #1488 | not started | — | — | backlog |", "#1488"),
    ],
)
def test_can_close_must_be_true_for_every_issue_row(arena: Path, tmp_path: Path, row: str, named: str) -> None:
    seed_run(arena, SINGLE_DONE)
    block = lib.SESSION_TEMPLATE.replace("| #1488 | closed | 4/4 | #1519 landed | — |", row)
    decision = verdict(arena, transcript(tmp_path, prompt("go"), said(block)))
    assert decision.exit_code == 2 and f"row {named}" in decision.stderr


def test_a_bold_now_cell_still_counts(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    block = lib.SESSION_TEMPLATE.replace("| closed |", "| **closed** |")
    assert verdict(arena, transcript(tmp_path, prompt("go"), said(block))).exit_code == 0


def test_can_close_with_a_failed_close_out_check_is_refused(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    form = CLOSE_FORM.replace("| 3 | check 3 | ✅ | fine |", "| 3 | check 3 | ❌ | run red |")
    decision = verdict(arena, transcript(tmp_path, prompt("<command-name>/close-session</command-name>"), said(form)))
    assert decision.exit_code == 2 and "check 3 (check 3) is ❌" in decision.stderr


def test_can_close_on_an_escalated_run_is_refused(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE.replace("Phase: DONE", "Phase: ESCALATED"))
    decision = verdict(arena, transcript(tmp_path, prompt("go"), said(lib.SESSION_TEMPLATE)))
    assert decision.exit_code == 2 and "ESCALATED" in decision.stderr


def test_another_table_gets_no_row_check(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    block = "SESSION: CAN CLOSE — the backlog is empty\n\n| Backlog | Count |\n|---|---|\n| workable | 0 |\n"
    assert verdict(arena, transcript(tmp_path, prompt("go"), said(block))).exit_code == 0


def loop_done(queued: str) -> str:
    return f"MODE: ISSUE_LOOP\nStatus: COMPLETED\nPhase: DONE\nCURRENT_ISSUE: none\nQUEUED_PRS: {queued}\n"


def test_a_loop_is_done_only_when_its_queued_prs_landed(arena: Path) -> None:
    seed_run(with_wrapper(arena), loop_done("#1536 #1537"))
    decision = brake(arena)
    assert decision.exit_code == 2
    assert "PR #1537: still queued" in decision.stderr and "PR #1539: returned: queue-conflict" in decision.stderr
    assert "wait-landed 1536 --timeout-seconds 540" in decision.stderr
    assert "wait-landed 1537 --timeout-seconds 540" in decision.stderr
    seed_run(arena, loop_done("1536, 1538"))
    assert brake(arena).exit_code == 0, "every queued PR landed"


@pytest.mark.parametrize("queued", ["none", ""])
def test_a_loop_without_queued_prs_is_not_checked(arena: Path, queued: str) -> None:
    seed_run(with_wrapper(arena), loop_done(queued))
    decision = brake(arena)
    assert decision.exit_code == 0 and "no verdict" not in decision.stderr


def test_check_landed_without_a_verdict_fails_open(arena: Path) -> None:
    seed_run(with_wrapper(arena), loop_done("#500"))
    decision = brake(arena)
    assert decision.exit_code == 0 and "no verdict on this loop's queued PRs" in decision.stderr


def two_wrappers(arena: Path, host: str = "") -> Path:
    (arena / "scripts").mkdir(exist_ok=True)
    for name, code in (("github", 4), ("gitlab", 0)):
        (arena / "scripts" / f"{name}_wrapper.py").write_text(
            f"import sys\nprint('answered by {name}')\nsys.exit({code})\n", encoding="utf-8"
        )
    if host:
        (arena / "config").mkdir(exist_ok=True)
        (arena / "config" / "delivery.json").write_text(json.dumps({"host": host}), encoding="utf-8")
    return arena


def test_the_queue_hosts_wrapper_answers(arena: Path) -> None:
    seed_run(two_wrappers(arena, "github"), handed_off("1486"))
    decision = brake(arena)
    assert decision.exit_code == 2 and "answered by github" in decision.stderr
    assert lib.project_wrapper(arena) == arena / "scripts" / "github_wrapper.py"


def test_without_a_host_the_old_order_stands(arena: Path) -> None:
    two_wrappers(arena)
    assert lib.project_wrapper(arena) == arena / "scripts" / "gitlab_wrapper.py"
    two_wrappers(arena, "gitlab")
    assert lib.project_wrapper(arena) == arena / "scripts" / "gitlab_wrapper.py"


def test_a_queued_loop_is_told_to_record_and_go_on(arena: Path) -> None:
    seed_run(
        with_wrapper(arena), "MODE: ISSUE_LOOP\nStatus: IN_PROGRESS\nPhase: QUEUED\nCURRENT_ISSUE: 1462\nPR: 1540\n"
    )
    decision = brake(arena)
    assert decision.exit_code == 2 and "QUEUED_PRS" in decision.stderr and "LOAD_ISSUES" in decision.stderr
    assert "wait-landed 1540 --timeout-seconds 540     (Bash" not in decision.stderr


def test_a_queued_single_issue_waits_on_one_pr_number(arena: Path) -> None:
    seed_run(
        with_wrapper(arena),
        "MODE: SINGLE_ISSUE\nStatus: IN_PROGRESS\nPhase: QUEUED\nCURRENT_ISSUE: 1462\nPR: #1540 (queued)\n",
    )
    decision = brake(arena)
    assert (
        "wait-landed 1540 --timeout-seconds 540" in decision.stderr
        and "#1540 (queued) --timeout" not in decision.stderr
    )


@pytest.mark.parametrize(
    "head",
    [
        "**SESSION: CAN CLOSE — 2/2 issues delivered**",
        "## SESSION: CAN CLOSE — 2/2 issues delivered",
        "> SESSION: CAN CLOSE — 2/2 issues delivered",
        "_SESSION: CAN CLOSE – 2/2 issues delivered_",
        "SESSION: CAN CLOSE - 2/2 issues delivered",
        "SESSION: CAN CLOSE: 2/2 issues delivered",
    ],
)
def test_readable_variants_of_the_head_are_accepted(arena: Path, tmp_path: Path, head: str) -> None:
    seed_run(arena, SINGLE_DONE)
    block = head + "\n\n" + lib.SESSION_TEMPLATE.split("\n", 2)[2]
    assert verdict(arena, transcript(tmp_path, prompt("go"), said(block))).exit_code == 0, head


def test_a_fenced_block_and_an_issues_colon_are_accepted(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    fenced = "```text\n" + lib.SESSION_TEMPLATE + "```\n"
    assert verdict(arena, transcript(tmp_path, prompt("go"), said(fenced))).exit_code == 0
    form = CLOSE_FORM.replace("\nIssues\n", "\nIssues:\n")
    path = transcript(tmp_path, prompt("<command-name>/close-session</command-name>"), said(form))
    assert verdict(arena, path).exit_code == 0


def test_the_last_head_of_the_turn_decides_the_archive(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE)
    withdrawn = lib.SESSION_TEMPLATE.replace("CAN CLOSE — 2/2 issues delivered", "NOT DONE — a train went red")
    path = transcript(tmp_path, prompt("close"), said(CLOSE_FORM), said(withdrawn))
    decision = archive(arena, path)
    assert decision.exit_code == 2 and "last SESSION verdict" in decision.stderr


def test_a_stale_question_says_how_to_clear_it(arena: Path, tmp_path: Path) -> None:
    seed_run(arena, SINGLE_DONE.replace("AWAITING_USER: none", "AWAITING_USER: waiting on the prod credential"))
    decision = verdict(arena, transcript(tmp_path, prompt("go"), said(lib.SESSION_TEMPLATE)))
    assert decision.exit_code == 2 and "AWAITING_USER: none" in decision.stderr


def test_the_new_gates_are_registered_where_they_belong() -> None:
    assert _names("stop").index("issue-loop-gate") < _names("stop").index("session-verdict")
    matcher = hooks.tool_matcher("pre-tool-use", HOOKS_DIR)
    assert matcher is None or gate_archive_verdict.ARCHIVE_TOOL in matcher.split("|")
