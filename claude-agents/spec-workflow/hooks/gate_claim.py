"""claim-before-worktree — PreToolUse(Bash) gate for the issue-work-orchestrator.

An agent must not create the per-issue worktree/branch for issue N until issue N is verifiably marked
in-progress on the tracker. When the command matches `git ... worktree add ... issue-<N>` (or `-b issue-<N>-slug`),
the gate runs the project's wrapper `issue claim-check <N>` (read-only): exit 3 = OPEN and UNCLAIMED -> block;
anything else -> allow. Fail-open by design: no issue number, no wrapper, no interpreter, or any wrapper error
allows, so the gate never wedges a session on infrastructure trouble.
"""

from __future__ import annotations

import re
import subprocess

import hooklib as lib

HOOK = "claim-before-worktree"
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
        completed = subprocess.run(
            [interpreter, str(wrapper), "issue", "claim-check", issue],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return lib.allow()
    if completed.returncode != UNCLAIMED_CODE:
        return lib.allow()
    said = (completed.stdout + completed.stderr).strip()
    return lib.block(
        f"BLOCKED by {HOOK} hook: issue #{issue} is OPEN and NOT yet claimed in-progress on the tracker. Creating\n"
        "its worktree now risks duplicate work. Claim it FIRST with a single verified call:\n"
        f"    {interpreter} {wrapper} issue start {issue}\n"
        "(idempotent, fail-closed). If it is already claimed elsewhere, release your local lock and select\n"
        f"another issue. claim-check said:\n{said}"
    )
