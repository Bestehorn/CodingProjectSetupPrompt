"""archive-after-verdict — PreToolUse gate: a work session is archived only AFTER its SESSION verdict is printed.

Measured 2026-11-01 (chess): in every turn that archived a session — 56 of them, before the delivery redesign and
after — the close-out verdict was never printed; the archive replaced the report, and the operator found an archived
session whose last words were "Session archived." (docs/reports/session-endings-analysis-2026-11-01.md). So
`archive_session` is refused unless an assistant text of the CURRENT turn (since the last real user prompt) holds
`SESSION: CAN CLOSE — …`: print the verdict, then archive; a NEEDS YOU or NOT DONE session is never archived.

Judges only that tool, and only for a registered work run (MODE SINGLE_ISSUE / ISSUE_LOOP / BACKLOG / AUTO): a plain
chat the operator asks to archive is not this gate's business. Fail open without a readable transcript (Kiro has
neither the tool nor a transcript). A PreToolUse refusal cannot wedge a session: the turn may still end.
"""

from __future__ import annotations

import hooklib as lib

HOOK = "archive-after-verdict"
EVENT = "pre-tool-use"  # the dispatcher runs this gate on this event
ORDER = 45  # framework gates 10..90: after the issue-filing gate (40)
ARCHIVE_TOOL = "mcp__ccd_session_mgmt__archive_session"
TOOLS = {ARCHIVE_TOOL}  # PreToolUse only: the tool names this gate judges


def _printed_can_close(turn: lib.TurnView) -> bool:
    """The LAST SESSION head printed in the turn is CAN CLOSE (a later NOT DONE withdraws an earlier CAN CLOSE)."""
    last = None
    for text in turn.texts:
        last = lib.session_head(text) or last
    return last == "CAN CLOSE"


def run(ctx: lib.Context) -> lib.Decision:
    if ctx.payload.tool_name != ARCHIVE_TOOL:
        return lib.allow()
    verdict, run_dir = ctx.resolve()
    if verdict != lib.OWNED or run_dir is None:
        return lib.allow()
    if not lib.mode_is_work_run(ctx.field(run_dir / lib.RESUME_FILENAME, "MODE")):
        return lib.allow()
    turn = lib.transcript_current_turn(ctx.payload.transcript_path)
    if turn is None:
        ctx.log(HOOK, "ALLOW", "no readable transcript to judge")
        return lib.allow()
    if _printed_can_close(turn):
        ctx.log(HOOK, "ALLOW", "the last SESSION verdict printed in this turn is CAN CLOSE")
        return lib.allow()
    ctx.log(HOOK, "BLOCK", "archive before a CAN CLOSE verdict in this turn")
    return lib.block(
        f"{HOOK}: REFUSED — the last SESSION verdict of this turn is not `SESSION: CAN CLOSE — …`, so archiving now\n"
        "would hide the session's verdict from the operator (or close a session that is not done).\n"
        "Print the SESSION block first (its head line, then the table, nothing after it), THEN archive. A session\n"
        "whose verdict is NEEDS YOU or NOT DONE is never archived.\n"
    )
