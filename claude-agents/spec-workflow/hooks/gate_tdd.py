"""spec-tdd-gate — PreToolUse(Bash) gate for the spec/TDD workflow.

Blocks (exit 2) when the command bypasses verification (`git commit --no-verify`/`-n`, `git push --no-verify`),
or is a `git push` while a task marked complete in the active spec has no capture or the newest capture is red
or riddled with skips, or is a `git push` under CI-OUTAGE MODE with no green full-suite capture. Everything
else is allowed. The gate is on PUSH, not commit: commits are cheap and frequent; the push is where evidence is
owed. `-n` is banned on commit only (on push it means --dry-run).

Failure direction: everything up to the push classification runs without touching state, so a defect in the
state code can only ever refuse a PUSH — never an ordinary shell command.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

import hooklib as lib

HOOK = "spec-tdd-gate"
EVENT = "pre-tool-use"  # the dispatcher runs this gate on this event
ORDER = 20  # framework gates 10..90; a project gate takes >100 (or <10 to run first)
SHELL_TOOLS = {"Bash", "shell", "execute_bash", "execute_cmd", "executeBash"}
TOOLS = SHELL_TOOLS  # PreToolUse only: the tool names this gate judges
BYPASS_COMMIT_RE = re.compile(r"(--no-verify|\s-n(\s|$))")


def run(ctx: lib.Context) -> lib.Decision:
    command = ctx.payload.command
    stripped = lib.strip_quoted(command)
    is_commit = lib.is_git_commit(stripped)
    is_push = lib.is_git_push(stripped)
    if not is_commit and not is_push:
        return lib.allow()

    if is_commit and BYPASS_COMMIT_RE.search(stripped):
        return lib.block(
            f"{HOOK}: 'git commit --no-verify'/-n is forbidden. The pre-commit hook is lint + security only and "
            "takes about a second — there is nothing to save by skipping it, and a bypass is how a secret or a "
            "lint regression reaches the remote. Fix the reported issue instead."
        )
    if is_push and "--no-verify" in stripped:
        return lib.block(
            f"{HOOK}: 'git push --no-verify' is forbidden. The pre-push hook is the type check, plus the full "
            "suite when CI-OUTAGE MODE is declared — and in that state it is the ONLY thing verifying this push. "
            "Fix the cause instead of bypassing the hook."
        )
    if not is_push:
        return lib.allow()  # commits carry no evidence requirement

    # From here on the command IS a push, so failing closed refuses only that push. The library self-test is
    # called HERE and not above: a truncated hooklib.py must refuse a push and nothing else.
    try:
        if not lib.selftest():
            raise RuntimeError("hooklib self-test failed")
        return _judge_push(ctx)
    except Exception as exc:  # noqa: BLE001 — any abort refuses the PUSH rather than allowing it unverified
        return lib.block(
            f"{HOOK}: ABORTED ({exc.__class__.__name__}: {exc}) before reaching a decision — "
            "refusing the PUSH rather than allowing it unverified. Fix the hook or its library, then push."
        )


def _judge_push(ctx: lib.Context) -> lib.Decision:  # noqa: C901 — one check per push precondition
    state_file = ctx.owned_state_file()
    if state_file is None or not state_file.is_file():
        return lib.allow()  # no spec workflow this session owns; the bypass bans were enforced above

    phase = ctx.field(state_file, "Phase")
    spec_value = ctx.field(state_file, "CURRENT_SPEC")
    if not lib.is_implementation_phase(phase):
        return lib.allow()
    if not spec_value.strip():
        # An unrecorded CURRENT_SPEC is judged by the Stop gate at turn-end; blocking every push would over-block.
        return lib.allow()

    spec_dir = _resolve_spec_dir(ctx, state_file, spec_value)
    problems: List[str] = []
    tasks = spec_dir / "tasks.md"
    if tasks.is_file():
        ids, _unparseable = lib.checked_task_ids(tasks)
        for task_id in ids:
            if lib.is_heading_id(task_id, ids):
                continue
            if (
                lib.capture_for_task(spec_dir, "green", task_id) is None
                and lib.capture_for_task(spec_dir, "red", task_id) is None
            ):
                problems.append(
                    f"  - task {task_id} is marked complete but no capture covers it "
                    f"(evidence/green/{task_id}.txt, evidence/red/{task_id}.txt, or a wave capture "
                    f"whose '# tasks:' line names {task_id}).\n"
                )

    latest = lib.latest_capture(spec_dir, "green")
    if latest is not None:
        body = lib.capture_body(latest)
        if lib.has_failures(body):
            problems.append(f"  - newest green capture ({latest}) shows failures/errors.\n")
        if lib.has_skips(body):
            problems.append(
                f"  - newest green capture ({latest}) contains skipped/xfail tests — resolve them, "
                "do not push around them.\n"
            )

    # CI-OUTAGE MODE: the marker lives in the SHARED git dir, so one declaration covers every worktree.
    common = _git_common_dir(ctx)
    if common is not None and (common / "ci-outage-mode").is_file():
        regress = lib.latest_capture(spec_dir, "regress")
        if regress is None:
            problems.append(
                f"  - CI-OUTAGE MODE is declared, so no CI run will verify this push, and there is no "
                f"full-suite capture under {spec_dir / 'evidence' / 'regress'}. Run "
                "'python scripts/run_tests.py' and capture it.\n"
            )
        elif lib.has_failures(lib.capture_body(regress)):
            problems.append(f"  - CI-OUTAGE MODE is declared and the newest full-suite capture ({regress}) is red.\n")

    if problems:
        return lib.block(
            f"{HOOK}: not safe to push — the work is not yet proven:\n"
            + "".join(problems)
            + "Commits are free; a push asks CI and other people to take this seriously. Finish the "
            "batch, capture the evidence, then push once."
        )
    return lib.allow()


def _resolve_spec_dir(ctx: lib.Context, state_file: Path, spec_value: str) -> Path:
    # Same order as the Stop gate's resolver: project root, recorded worktree, the value as given.
    candidates = [ctx.project_dir / spec_value]
    worktree = ctx.field(state_file.parent / lib.RESUME_FILENAME, "WORKTREE")
    if worktree and not lib.is_placeholder(worktree):
        candidates.append(Path(worktree) / spec_value)
    candidates.append(Path(spec_value))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return Path(spec_value)


def _git_common_dir(ctx: lib.Context) -> Optional[Path]:
    out = lib._git(["rev-parse", "--git-common-dir"], ctx.process_cwd)  # noqa: SLF001 — library helper
    if not out:
        return None
    common = Path(out.strip())
    # A relative --git-common-dir is relative to the CURRENT directory, not to the top level.
    return common if common.is_absolute() else ctx.process_cwd / common
