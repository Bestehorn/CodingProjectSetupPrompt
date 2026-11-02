"""session-verdict — Stop gate: a registered work run that is done for now ENDS with the SESSION verdict.

The operator decides from ONE glance whether to close a session. So when a run whose MODE is SINGLE_ISSUE,
ISSUE_LOOP, BACKLOG or AUTO is RELEASED (finished, handed off, idle or waiting on a recorded AWAITING_USER — the
releases `hooklib.run_is_released` names), the LAST assistant text of the turn must hold

    SESSION: CAN CLOSE — … | SESSION: NEEDS YOU — <the one decision> | SESSION: NOT DONE — <what is left>

followed by its table (header row always present) and NOTHING else — except, for /close-session, its `Issues`
block. NEEDS YOU exactly when an AWAITING_USER reason is recorded. Measured 2026-11-01 (chess, the 16 sessions after
the delivery redesign): 0 of 10 `/close-session` turns printed their verdict, and the work-issue endings were
prose or a block whose header said "FINISHED — 0 closed" next to "Status IN_PROGRESS" (project-docs/
session-endings-analysis-2026-11-01.md).

Not judged: an unregistered or broken session, a run of any other MODE, a run that is NOT released (the issue-loop
brake judges it), a turn that an earlier Stop gate of this dispatch already refuses, a turn a `[run-watchdog]` tick
started (it answers `idle`), a turn that archived the session AFTER printing a valid CAN CLOSE block, and a host
without a transcript (Kiro): fail open. Own consecutive-block counter, half the family's cap; it stands down with a
note, and resets on a passing turn.
"""

from __future__ import annotations

import hooklib as lib

HOOK = "session-verdict"
EVENT = "stop"  # the dispatcher runs this gate on this event
ORDER = 25  # framework gates 10..90: after the issue-loop brake (20), which judges an unreleased run first
ARCHIVE_TOOL_SUFFIX = "archive_session"


def _archived_after_can_close(
    turn: lib.TurnView, awaiting_substantive: bool, allow_issues: bool, phase: str, status: str
) -> bool:
    """True when the turn printed a VALID, TRUE `SESSION: CAN CLOSE` block and archived the session after it: the
    archived session's last line may then be the harness's "archived" note — the verdict is right above it."""
    valid = False
    for kind, value in turn.events:
        if kind == "text":
            head, problems = lib.session_verdict_problems(value, awaiting_substantive, allow_issues, phase, status)
            if head == "CAN CLOSE" and not problems:
                valid = True
        elif kind == "tool" and value.endswith(ARCHIVE_TOOL_SUFFIX) and valid:
            return True
    return False


def _message(problems: list, rules_doc: str) -> str:
    return (
        f"{HOOK}: REFUSING the stop — this run is done for now, so its LAST message is the SESSION verdict the\n"
        f"operator closes the session on, and it is not: {'; '.join(problems)}.\n"
        "End with exactly this shape (an answer to anything you were asked comes BEFORE it; NOTHING after the table):\n"
        "\n"
        f"{lib.SESSION_TEMPLATE}\n"
        "The head is ONE of:\n"
        "  SESSION: CAN CLOSE — …        every row closed, landed — deploy check pending, or filed; nothing waits for\n"
        "                                the operator; the close-out is done\n"
        "  SESSION: NEEDS YOU — <one line> exactly when an AWAITING_USER reason is recorded\n"
        "  SESSION: NOT DONE — <one line> what is left, and who has it\n"
        "Now is one of: closed · landed — deploy check pending · returned: <why> · blocked: <why> · filed ·\n"
        "not started.\n"
        "Tasks are ticked/total re-read from the tracker. In the desktop app the wrap_up recap repeats the SESSION\n"
        f"line. ({rules_doc})\n"
    )


def run(ctx: lib.Context) -> lib.Decision:  # noqa: C901 — one exemption per line, in order
    sid = ctx.session_id
    if not sid:
        return lib.allow()
    if ctx.blocked_by:
        ctx.log(HOOK, "ALLOW", f"an earlier Stop gate refuses this turn ({', '.join(ctx.blocked_by)})")
        return lib.allow()
    verdict, run_dir = ctx.resolve()
    if verdict != lib.OWNED or run_dir is None:
        return lib.allow()
    state = run_dir / lib.RESUME_FILENAME
    status, phase = ctx.field(state, "Status"), ctx.field(state, "Phase")
    awaiting, mode = ctx.field(state, "AWAITING_USER"), ctx.field(state, "MODE")
    if not lib.mode_is_work_run(mode):
        return lib.allow()
    if not lib.run_is_released(status, phase, awaiting, mode):
        ctx.log(HOOK, "ALLOW", f"run={sid[:8]} not released (Phase='{phase}'): the brake judges it")
        return lib.allow()
    turn = lib.transcript_current_turn(ctx.payload.transcript_path)
    if turn is None:
        ctx.log(HOOK, "ALLOW", "no readable transcript to judge")
        return lib.allow()
    counter = lib.counter_path(ctx.state_base, "verdict", sid)
    if turn.is_watchdog_tick:
        lib.counter_reset(counter)
        ctx.log(HOOK, "ALLOW", f"run={sid[:8]} a watchdog tick")
        return lib.allow()
    awaiting_substantive = lib.is_substantive_escalation(awaiting)
    allow_issues = turn.prompt is None or "/close-session" in (turn.prompt or "")
    if _archived_after_can_close(turn, awaiting_substantive, allow_issues, phase, status):
        lib.counter_reset(counter)
        ctx.log(HOOK, "ALLOW", f"run={sid[:8]} archived after a CAN CLOSE verdict")
        return lib.allow()
    texts = turn.texts
    head, problems = lib.session_verdict_problems(
        texts[-1] if texts else "", awaiting_substantive, allow_issues, phase, status
    )
    if not problems:
        lib.counter_reset(counter)
        ctx.log(HOOK, "ALLOW", f"run={sid[:8]} SESSION: {head}")
        return lib.allow()

    blocks = lib.counter_read(counter)
    cap = max(1, ctx.block_cap // 2)
    if blocks >= cap or lib.counter_is_capped(counter):
        lib.counter_mark_capped(counter)
        ctx.log(HOOK, "ALLOW_AT_CAP", f"run={sid[:8]} blocks={blocks} problems={problems}")
        return lib.allow(
            stderr=(
                f"{HOOK}: standing down after {blocks} refusals — this session still does not end with its SESSION "
                "verdict, so the operator cannot tell from the ending whether to close it.\n"
            )
        )
    if not lib.counter_bump(counter):
        ctx.log(HOOK, "ALLOW_COUNTER_UNWRITABLE", f"counter={counter}")
        return lib.allow()
    ctx.log(HOOK, "BLOCK", f"run={sid[:8]} blocks={blocks + 1} head={head} problems={problems}")
    return lib.block(_message(problems, f"{ctx.host.config_dir}/docs/delivery.md"))
