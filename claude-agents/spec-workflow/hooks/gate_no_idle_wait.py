"""no-idle-wait — Stop gate: a turn may not end in order to WAIT for something.

Blocks (exit 2) when the LAST assistant message of the session transcript — the file the Stop payload names in
`transcript_path` — says the turn is ending to wait for a notification: "I'm waiting on it in the background",
"its exit line will notify me", "I'll pick this up when CI finishes". A turn that ends to wait idles until a
notification that may never come. MEASURED 2026-10-10 over 30 days of three projects' transcripts: a background
task dies with the session's process, the harness reports it `stopped` and runs no turn for it (82 of 82); a
`failed` task is answered with a synthetic "No response requested." one time in four; the operator then finds an
idle session and types `/continue-work`. The same reading found the registered-run gates honoured every one of
their 1,227 refusals, so the leak was never the brake — it was the turn that ended to wait while the brake had
nothing recorded to hold (no claimed work, or its cap reached during a long VERIFY).

The sanctioned shape of a wait the session needs: do every unblocked piece of work first, then wait in the
FOREGROUND with a bounded timeout — the wrapper's `wait-run <id> --timeout-seconds 540` (GitLab: `pipeline wait
<id> --timeout-seconds 540`) under the Bash tool's 10-minute ceiling, re-issued while it exits 11 — and act on
the verdict (`parallel-by-default.md`). A background task is for output the session reads LATER while it keeps
working in the same turn, never for a wait it needs before continuing.

Fail-open, each deliberate: no `transcript_path` in the payload (Kiro); an unreadable transcript; no assistant
text in the tail; a final text that carries a Completion Block verdict line (the work is declared finished and
the other Stop gates judge that claim). Own consecutive-block counter with the family's cap, halved (the
message is the same every time; four refusals are enough to establish that the model insists), reset whenever
the final text no longer waits. Decisions are logged like every other gate's.
"""

from __future__ import annotations

import re

import hooklib as lib

HOOK = "no-idle-wait"
EVENT = "stop"  # the dispatcher runs this gate on this event
ORDER = 15  # framework gates 10..90: after the evidence gate (10), before the issue-loop brake (20)
TAIL_CHARS = 600
# The SESSION announcing that it waits — first person, or a status sentence that starts with "Waiting on". A
# sentence that only explains a wait ("you only need to wait for the deploy", "the watcher closes it when the
# deploy completes") is not the turn ending to wait, and refusing it would force four empty continuations.
_SELF = r"(?:i['’]?m|i\s+am|i['’]?ll|i\s+will|i['’]?d|we['’]?re|we\s+are|we['’]?ll|we\s+will|let\s+me|let['’]?s)"
WAIT_RE = re.compile(
    rf"\b{_SELF}\s+(?:just\s+|now\s+|still\s+|simply\s+|going\s+to\s+)?wait(?:ing)?\b"
    r"|(?:^|[.!?;:]\s+)(?:still\s+|now\s+|just\s+)?waiting\s+(?:on|for|until)\b"
    r"|\bwill\s+(?:notify|wake|re-?invoke|ping|tell)\s+me\b"
    r"|\bnotif(?:y|ies|ied)\s+me\b"
    r"|\bits\s+exit\s+line\b"
    rf"|\b{_SELF}\b[^.\n]{{0,80}}\bwhen\s+(?:ci|the\s+(?:run|pipeline|suite|deploy|job|wait|build))\s+"
    r"(?:finishes|completes|is\s+done|lands|returns|ends)\b"
    r"|\bpick\s+(?:this|it|that)\s+(?:back\s+)?up\s+when\b",
    re.IGNORECASE | re.MULTILINE,
)
# A Completion Block's verdict line: the close-out table (`CLOSE: ...`) or the orchestrator's
# `ISSUE WORK FINISHED|BLOCKED|FAILED — ...` (which also ends a single-issue run that HANDED OFF its PR).
VERDICT_RE = re.compile(
    r"^(?:CLOSE|VERDICT|RESULT|STATUS|OUTCOME):|^ISSUE WORK (?:FINISHED|BLOCKED|FAILED)\b", re.MULTILINE
)


def run(ctx: lib.Context) -> lib.Decision:
    sid = ctx.session_id or "nosession"
    counter = lib.counter_path(ctx.state_base, "wait", sid)
    text = lib.transcript_last_assistant_text(ctx.payload.transcript_path)
    if not text:
        ctx.log(HOOK, "ALLOW", "no transcript text to judge")
        return lib.allow()
    tail = text[-TAIL_CHARS:]
    match = WAIT_RE.search(tail)
    if match is None or VERDICT_RE.search(text):
        lib.counter_reset(counter)
        ctx.log(HOOK, "ALLOW", "the final text does not end the turn to wait")
        return lib.allow()

    blocks = lib.counter_read(counter)
    cap = max(1, ctx.block_cap // 2)
    phrase = " ".join(match.group(0).split())
    if blocks >= cap or lib.counter_is_capped(counter):
        lib.counter_mark_capped(counter)
        ctx.log(HOOK, "ALLOW_AT_CAP", f"blocks={blocks} phrase={phrase!r}")
        return lib.allow(
            stderr=(
                f"{HOOK}: standing down after {blocks} refusals — the turn still ends to wait ({phrase!r}). If the "
                "wait's notification never comes, this session idles until the operator types /continue-work.\n"
            )
        )
    if not lib.counter_bump(counter):
        ctx.log(HOOK, "ALLOW_COUNTER_UNWRITABLE", f"counter={counter}")
        return lib.allow()
    ctx.log(HOOK, "BLOCK", f"blocks={blocks + 1} phrase={phrase!r}")
    return lib.block(
        f"{HOOK}: this turn ends in order to WAIT ({phrase!r}). A turn that ends to wait idles until a notification "
        "that may never come: a background task dies with the session's process and a stopped task never wakes the "
        "model (measured 2026-10-10: 82 of 82). Do the unblocked work first; when nothing unblocked remains, wait in "
        "the FOREGROUND with a bounded timeout — `python scripts/<wrapper>.py wait-run <id> --timeout-seconds 540` "
        "(GitLab: `pipeline wait <id> --timeout-seconds 540`), Bash timeout 600000, re-issued while it exits 11 — "
        "then act on the verdict. Finished? End with the Completion Block verdict line. A person must act? Append "
        "an AWAITING_USER line naming the reason to resume_state.md. Then end the turn."
    )
