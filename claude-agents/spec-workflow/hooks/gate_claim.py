"""claim-before-worktree — PreToolUse(Bash) gate for the issue-work-orchestrator.

An agent must not create the per-issue worktree/branch for issue N until issue N is verifiably marked
in-progress on the tracker. When the command matches `git ... worktree add ... issue-<N>` (or `-b issue-<N>-slug`),
the gate runs the project's wrapper `issue claim-check <N>` (read-only): exit 3 = OPEN and UNCLAIMED -> block;
anything else -> allow. Fail-open by design: no issue number, no wrapper, no interpreter, or any wrapper error
allows, so the gate never wedges a session on infrastructure trouble.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 — the project's own wrapper with a fixed argv, no shell

import hooklib as lib

HOOK = "claim-before-worktree"
EVENT = "pre-tool-use"  # the dispatcher runs this gate on this event
ORDER = 30  # framework gates 10..90; a project gate takes >100 (or <10 to run first)
SHELL_TOOLS = {"Bash", "shell", "execute_bash", "execute_cmd", "executeBash"}
TOOLS = SHELL_TOOLS  # PreToolUse only: the tool names this gate judges
UNCLAIMED_CODE = 3
WORKTREE_ADD_RE = re.compile(r"git\s.*worktree\s+add")
ISSUE_RE = re.compile(r"issue-(\d+)", re.IGNORECASE)


def run(ctx: lib.Context) -> lib.Decision:
    command = ctx.payload.command
    if not command or not WORKTREE_ADD_RE.search(command):
        return lib.allow()
    match = ISSUE_RE.search(command)
    if not match:
        return lib.allow()
    issue = match.group(1)

    project = ctx.project_dir
    wrapper = None
    for name in ("gitlab_wrapper.py", "github_wrapper.py"):
        candidate = project / "scripts" / name
        if candidate.is_file():
            wrapper = candidate
            break
    if wrapper is None:
        return lib.allow()
    interpreter = lib.python_interpreter(project)
    if not interpreter:
        return lib.allow()

    try:
        completed = subprocess.run(  # nosec B603 — the project's own wrapper, fixed argv, no shell
            [interpreter, str(wrapper), "issue", "claim-check", issue],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _no_verdict(ctx, issue, f"claim-check could not run ({exc.__class__.__name__}: {exc})")
    said = (completed.stdout + completed.stderr).strip()
    if completed.returncode == 0:
        return lib.allow()
    if completed.returncode != UNCLAIMED_CODE:
        # Exit 2 is the wrapper's usage error — typically a wrapper that lacks the `issue claim-check`
        # subcommand; exit 1 an API error. Neither is a verdict, and allowing SILENTLY would hide a wrapper
        # that can never answer. The note rides on stderr (exit 0 routes it to the debug log) and the log.
        return _no_verdict(ctx, issue, f"claim-check exited {completed.returncode}: {said[:200]}")
    return lib.block(
        f"BLOCKED by {HOOK} hook: issue #{issue} is OPEN and NOT yet claimed in-progress on the tracker. Creating\n"
        "its worktree now risks duplicate work. Claim it FIRST with a single verified call:\n"
        f"    {interpreter} {wrapper} issue start {issue}\n"
        "(idempotent, fail-closed). If it is already claimed elsewhere, release your local lock and select\n"
        f"another issue. claim-check said:\n{said}"
    )


def _no_verdict(ctx: lib.Context, issue: str, detail: str) -> lib.Decision:
    ctx.log(HOOK, "NO_VERDICT", f"issue={issue} {detail}")
    return lib.allow(
        stderr=(
            f"{HOOK}: no verdict for issue #{issue} — {detail}. Allowing the worktree; the claim is NOT verified. "
            "Give the wrapper a working `issue claim-check` subcommand so this gate can decide.\n"
        )
    )
