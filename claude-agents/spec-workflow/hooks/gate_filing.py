"""issue-filing-gate — PreToolUse(Bash) gate for issue CREATION.

Enforces issue-filing-discipline at the one moment that matters: the attempt to create a tracker issue. It
recognises a CREATE call only (`create-issue`, `issue create`) and blocks when a required provenance line is
provably absent from the command text plus any readable `--body-file`:
    Origin:            human-request | spawned-discovery | spawned-residual | agent-sweep
    Subject:           product | process
    Spawned-from:      #<N>   (only when Origin is spawned-*)
    Filing-rationale:  RESEARCH | DESIGN-OPTIONS | OUT-OF-SCOPE | HUMAN-REQUEST
Fail-open: not a create call; a body this gate cannot read (heredoc, substitution, variable, unreadable file).
Declared residuals: bodies assembled indirectly, create calls through an interpreter or wrapper shell, API calls
via curl, and untruthful lines are RULE-only by design.
"""

from __future__ import annotations

import re

import hooklib as lib

HOOK = "issue-filing-gate"
TEXT_TOOL_RE = re.compile(
    r"^\s*(grep|rg|ag|echo|printf|cat|sed|awk|less|more|head|tail|Select-String|Get-Content|"
    r"Write-Output|git\s+grep)\s"
)
CREATE_RE = re.compile(r"(create-issue|issue\s+create)")
BODYFILE_RE = re.compile(r"(--body-file|--description-file|-F)[\s=]+([^\s\"']+)")
INDIRECT_RE = re.compile(r"\$\(|`|<<|\$[A-Za-z_{]")
ORIGIN_RE = re.compile(
    r"Origin:\s*(human-request|spawned-discovery|spawned-residual|agent-sweep)",
    re.IGNORECASE,
)
SUBJECT_RE = re.compile(r"Subject:\s*(product|process)", re.IGNORECASE)
RATIONALE_RE = re.compile(
    r"Filing-rationale:\s*(RESEARCH|DESIGN-OPTIONS|OUT-OF-SCOPE|HUMAN-REQUEST)",
    re.IGNORECASE,
)
SPAWNED_RE = re.compile(r"Origin:\s*spawned-(discovery|residual)", re.IGNORECASE)
SPAWNED_FROM_RE = re.compile(r"Spawned-from:\s*#?[0-9]+", re.IGNORECASE)


def run(ctx: lib.Context) -> lib.Decision:
    command = ctx.payload.command
    if not command:
        return lib.allow()
    if TEXT_TOOL_RE.match(command):
        return lib.allow()  # talking ABOUT issue creation, not doing it
    if not CREATE_RE.search(command):
        return lib.allow()
    rule = f"{ctx.host.rules_dir}/issue-filing-discipline.md"

    haystack = command
    bodyfile_unreadable = False
    bodyfile = ""
    match = BODYFILE_RE.search(command)
    if match:
        bodyfile = match.group(2)
        resolved = None
        for candidate in (lib.Path(bodyfile), ctx.project_dir / bodyfile):
            if candidate.is_file():
                resolved = candidate
                break
        if resolved is not None:
            haystack = haystack + "\n" + lib.read_text(resolved)
        else:
            bodyfile_unreadable = True

    missing = []
    if not ORIGIN_RE.search(haystack):
        missing.append("Origin:")
    if not SUBJECT_RE.search(haystack):
        missing.append("Subject:")
    if not RATIONALE_RE.search(haystack):
        missing.append("Filing-rationale:")
    if SPAWNED_RE.search(haystack) and not SPAWNED_FROM_RE.search(haystack):
        missing.append("Spawned-from:")
    if not missing:
        return lib.allow()

    if bodyfile_unreadable:
        return lib.allow(
            stderr=(
                f"{HOOK}: --body-file '{bodyfile}' is not readable from here; provenance not verified. Allowing.\n"
                f"  The four Origin/Subject/Spawned-from/Filing-rationale lines are still required by {rule}.\n"
            )
        )
    if INDIRECT_RE.search(command):
        return lib.allow(
            stderr=(
                f"{HOOK}: the issue body is assembled from a source this hook cannot read (command substitution,\n"
                f"  heredoc, or a variable); provenance not verified. Allowing. The four provenance lines are still\n"
                f"  required by {rule}.\n"
            )
        )

    return lib.block(
        f"BLOCKED by {HOOK}: this issue body is missing required provenance line(s): {' '.join(missing)}\n\n"
        f"First re-run the fix-first evaluation ({rule}):\n"
        "  1. Blocking the current task?  -> fix it in the current change, do not file.\n"
        "  2. Small and clear (a few lines, no design choice, no new dependency)?\n"
        "     -> FIX IT NOW and do not file. This is the expected outcome for most\n"
        "        defects noticed in passing.\n"
        "  3. Needs extensive RESEARCH, an evaluation of DESIGN-OPTIONS, or is\n"
        "     OUT-OF-SCOPE for the current task (or a human asked: HUMAN-REQUEST)?\n"
        "     -> file it, and say which one.\n"
        "  4. None of the above? -> one line in docs/findings-ledger.md, then move on.\n"
        "     Filing nothing is a valid and expected outcome.\n\n"
        "If the evaluation still says FILE, put these lines in the issue body (prefer\n"
        "delegating the filing to the issue-intake agent, which emits them):\n"
        "  Origin: human-request|spawned-discovery|spawned-residual|agent-sweep\n"
        "  Subject: product|process\n"
        "  Spawned-from: #<N>            (only when Origin is spawned-*)\n"
        "  Filing-rationale: RESEARCH|DESIGN-OPTIONS|OUT-OF-SCOPE|HUMAN-REQUEST — <why>"
    )
