"""spec-stop-gate — Stop gate for the spec/TDD workflow. Blocks turn-end on work that is not PROVEN.

Blocks while the workflow is mid-implementation and any of these holds: a task is marked complete in tasks.md
but no capture covers it; a green capture shows no passing result, or failures, or skipped/xfail tests; the
latest paired-test capture is red or vacuous; the phase is IMPLEMENT/VERIFY but tasks.md or CURRENT_SPEC is
absent. It judges PAIRED-TEST captures, not the full suite (CI owns the suite; the push gate holds the push).

Fail-opens fixed here, all measured (MIGRATION.md): the mtime borrow of another run's state; a missing state
file read as no obligation; an absent tasks.md allowing the stop; `stop_hook_active`; a prefix match releasing
on `COMPLETED (was IN_PROGRESS)`; zero-byte captures read as proof; only the newest capture scanned for
failures; a placeholder CURRENT_SPEC treated as a path; the one case-sensitive comparison in the family.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import hooklib as lib

HOOK = "spec-stop-gate"
EVENT = "stop"  # the dispatcher runs this gate on this event
ORDER = 10  # framework gates 10..90; a project gate takes >100 (or <10 to run first)


def run(ctx: lib.Context) -> lib.Decision:  # noqa: C901 — the evidence gate: every release, then every refusal
    sid = ctx.session_id
    base = ctx.state_base
    counter = lib.counter_path(base, "spec", sid or "nosession")
    blocks = lib.counter_read(counter)
    cap = ctx.block_cap

    def at_cap() -> bool:
        return blocks >= cap or lib.counter_is_capped(counter)

    def allow_at_cap(reason: str) -> lib.Decision:
        lib.counter_mark_capped(counter)
        ctx.log(HOOK, "ALLOW_AT_CAP", f"blocks={blocks} reason={reason}")
        return lib.allow(
            stderr=(
                f"{HOOK}: this gate no longer objects — {blocks} consecutive blocks with no change in the evidence "
                f"({reason}). THE WORK IS NOT PROVEN; the gate is standing down so the session cannot wedge, and is "
                "NOT certifying the work. It re-arms as soon as the evidence changes.\n"
            )
        )

    def block(detail: str, message: str) -> lib.Decision:
        if not lib.counter_bump(counter):
            ctx.log(HOOK, "ALLOW_COUNTER_UNWRITABLE", f"counter={counter} reason={detail}")
            return lib.allow(
                stderr=(
                    f"{HOOK}: this gate cannot persist its block counter at {counter}, so its bounded-escape "
                    "guarantee does not hold — standing down rather than refusing without a way out. THE WORK MAY "
                    "NOT BE PROVEN.\n"
                )
            )
        ctx.log(HOOK, "BLOCK", detail)
        return lib.block(message)

    def allow(detail: str) -> lib.Decision:
        lib.counter_reset(counter)
        ctx.log(HOOK, "ALLOW", detail)
        return lib.allow()

    if sid:
        verdict, run_dir = ctx.resolve()
        if verdict == lib.BROKEN and run_dir is not None:
            if at_cap():
                return allow_at_cap("identity unrepaired")
            return block(
                f"broken identity run={sid[:8]}",
                (
                    f"{HOOK}: REFUSING the stop — this session's run state is MISSING, so no gate can judge your "
                    f"work.\n"
                    f"Create {run_dir / lib.RESUME_FILENAME} (that exact path — do not invent a run-id label) with "
                    f"plain\n"
                    f"`Name: value` lines including SESSION_ID: {sid}, then CONTINUE. Do not end the turn to report "
                    f"this.\n"
                ),
            )
        if lib.owned_workflow_missing(base, sid):
            if at_cap():
                return allow_at_cap("workflow state unrepaired")
            owned_dir = run_dir if run_dir is not None else Path(".")
            return block(
                f"owned run with no workflow state run={sid[:8]}",
                (
                    f"{HOOK} (the EVIDENCE gate): REFUSING the stop — this run OWNS state but its workflow\n"
                    "state file does not exist, so this gate cannot judge the implementation at all:\n"
                    f"    {owned_dir / lib.STATE_FILENAME}\n\n"
                    "Create that exact path with plain `Name: value` lines carrying at least SESSION_ID, "
                    "CURRENT_SPEC,\n"
                    "Phase, Status and CURRENT_TASK, then CONTINUE. If this run has no spec workflow, record\n"
                    "`CURRENT_SPEC: none` and `Phase: NOT_STARTED` and this gate will stand aside.\n"
                ),
            )

    state_file = ctx.owned_state_file()
    if state_file is None or not state_file.is_file():
        return allow(f"no workflow state owned by session {sid[:8]}")

    phase = ctx.field(state_file, "Phase")
    status = ctx.field(state_file, "Status")
    spec_value = ctx.field(state_file, "CURRENT_SPEC")

    if lib.phase_is_terminal(status):
        return allow(f"workflow status '{status}' is terminal")

    # A RECORDED ESCALATION IS HONOURED HERE TOO, to the SAME standard as the loop gate. Read from the
    # resume_state.md beside the workflow state (where the other hooks tell the agent to put it), else here.
    resume = state_file.parent / lib.RESUME_FILENAME
    awaiting = ctx.field(resume, "AWAITING_USER") or ctx.field(state_file, "AWAITING_USER")
    if lib.is_substantive_escalation(awaiting):
        return allow(f"escalation recorded: AWAITING_USER='{awaiting}'")

    if not lib.is_implementation_phase(phase):
        return allow(f"phase '{phase}' is not an implementation phase")

    # An absent CURRENT_SPEC at an implementation phase is unfinished work, not "nothing to check".
    if lib.is_placeholder(spec_value):
        if at_cap():
            return allow_at_cap("CURRENT_SPEC still unrecorded")
        return block(
            f"no CURRENT_SPEC recorded at implementation phase '{phase}'",
            (
                f"{HOOK} (the EVIDENCE gate): REFUSING the stop — phase is '{phase}' but no CURRENT_SPEC is\n"
                "recorded, so this gate cannot judge the implementation at all.\n\n"
                "Two ways out, both by APPENDING a new block at the END of\n"
                f"    {state_file}\n"
                "(hooks read the LAST occurrence of each field):\n"
                "  * you ARE implementing a spec -> record 'CURRENT_SPEC: <path to the spec directory>'\n"
                "  * this run has no spec at all -> record a Phase outside IMPLEMENT/VERIFY (for example\n"
                "    'Phase: FIX'), or a terminal 'Phase: DONE' once the work genuinely is done\n\n"
                "Then CONTINUE the work. Do not end the turn to report this.\n"
            ),
        )

    # Resolve the spec against every plausible ROOT: for the orchestrator flow the spec lives inside a
    # per-issue WORKTREE while the project dir is the main checkout.
    spec_dir = _resolve_spec_root(ctx, spec_value, ctx.field(resume, "WORKTREE"))
    if spec_dir is None:
        return allow(f"CURRENT_SPEC '{spec_value}' resolves to no directory from any known root")
    tasks = spec_dir / "tasks.md"

    # PROGRESS RESETS THE COUNT: the fingerprint is the evidence STATE, not a clock.
    fingerprint = f"{phase}|{spec_dir}|{lib.evidence_fingerprint(spec_dir)}"
    if lib.counter_note_progress(counter, fingerprint):
        lib.counter_reset(counter)
        lib.counter_note_progress(counter, fingerprint)
        blocks = 0
        ctx.log(HOOK, "PROGRESS", f"evidence changed; block count reset spec={spec_dir}")

    if not tasks.is_file():
        if at_cap():
            return allow_at_cap("tasks.md still absent")
        return block(
            f"tasks.md absent at phase '{phase}' spec={spec_dir}",
            (
                f"{HOOK}: REFUSING the stop — phase is '{phase}' but the task list does not exist:\n"
                f"    {tasks}\n\n"
                "The spec workflow requires tasks.md BEFORE implementation, and this gate used to allow the stop\n"
                "when it was missing — switching itself off in exactly the condition that means the mandatory\n"
                "artifact has not been written. Write tasks.md (test-first, dependency-ordered, every acceptance\n"
                "criterion carrying a task), then continue implementing. Do not end the turn to report this.\n\n"
                "If this project does not use a task list at all, that is a configuration mismatch rather than\n"
                "unfinished work. Record a Phase OUTSIDE IMPLEMENT/VERIFY (for example 'Phase: FIX') by appending\n"
                "a new block at the END of\n"
                f"    {state_file}\n"
                "and this gate will stand aside. Do NOT instead clear CURRENT_SPEC — at an implementation phase an\n"
                "absent spec is itself refused, for the same reason an absent task list is. A refusal whose escape\n"
                "is undiscoverable is indistinguishable from a wedge, so the escape is named here.\n"
            ),
        )

    problems = evidence_problems(spec_dir, tasks)
    if problems:
        if at_cap():
            return allow_at_cap("evidence still unproven")
        return block(
            f"unproven evidence spec={spec_dir} phase='{phase}'",
            (
                f"{HOOK}: REFUSING the stop — the implementation is not yet proven:\n"
                + "".join(problems)
                + "Finish the task, run its tests, capture the evidence, and only mark it complete when green.\n"
                "Do not end the turn to report progress; continue working.\n"
            ),
        )

    return allow(f"proven at phase '{phase}' spec={spec_dir}")


def _resolve_spec_root(ctx: lib.Context, spec_value: str, worktree: str) -> Optional[Path]:
    # The same ORDER as the push gate — project root, recorded worktree, then the value as given (which is
    # how an absolute path resolves) — so the two gates never disagree about which directory a spec is.
    candidates: List[Path] = [ctx.project_dir / spec_value]
    if worktree and not lib.is_placeholder(worktree):
        candidates.append(Path(worktree) / spec_value)
    candidates.append(Path(spec_value))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def evidence_problems(spec_dir: Path, tasks: Path) -> List[str]:  # noqa: C901 — one check per evidence defect
    """The evidence defects of a spec, one line each — shared with the push gate so the two cannot disagree."""
    problems: List[str] = []
    ids, unparseable = lib.checked_task_ids(tasks)
    for line in unparseable:
        problems.append(
            f"  - a checked task line carries no parseable task id, so its evidence cannot be located: {line}\n"
        )
    for task_id in ids:
        if lib.is_heading_id(task_id, ids):
            continue
        green = lib.capture_for_task(spec_dir, "green", task_id)
        red = lib.capture_for_task(spec_dir, "red", task_id)
        if green is None and red is None:
            problems.append(
                f"  - task {task_id} is marked complete but no capture covers it: neither "
                f"evidence/green/{task_id}.txt nor evidence/red/{task_id}.txt exists, and no wave "
                f"capture's '# tasks:' line names {task_id}.\n"
            )
            continue
        if green is not None:
            body = lib.capture_body(green)
            if not lib.has_pass_marker(body):
                problems.append(
                    f"  - task {task_id}'s green capture exists but shows NO passing result ({green}): "
                    "an empty or prose-only capture is not proof.\n"
                )
            if lib.has_failures(body):
                problems.append(
                    f"  - task {task_id}'s green capture reports failures/errors ({green}) — it is not "
                    "a passing result.\n"
                )
            if lib.has_skips(body):
                problems.append(
                    f"  - task {task_id}'s green capture reports skipped/xfail tests ({green}) — "
                    "resolve them rather than stopping.\n"
                )
    latest = lib.latest_capture(spec_dir, "green")
    if latest is not None:
        body = lib.capture_body(latest)
        if lib.has_failures(body):
            problems.append(
                f"  - latest paired-test capture ({latest}) shows failures/errors — the tests are not green.\n"
            )
        if lib.has_skips(body):
            problems.append(
                f"  - latest paired-test capture ({latest}) contains skipped/xfail tests — resolve "
                "them rather than stopping.\n"
            )
    return problems
