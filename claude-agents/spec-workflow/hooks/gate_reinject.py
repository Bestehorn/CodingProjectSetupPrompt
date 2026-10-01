"""continuous-work-reinject — SessionStart (compact | resume | startup; Kiro: agentSpawn).

Puts back into context the two things an agent is likeliest to have lost: the continuous-work contract and THIS
session's own recorded place in the work. The first turn after a compaction is the likeliest moment for a
spurious stop. Identity comes from the session-keyed resolver — there is no mtime rung, because a previous
implementation handed one session another run's issue, branch and worktree as its own.

SessionStart stdout is injected as context; exit 2 would show stderr to the user only. So this always exits 0,
prints a small block, and writes nothing but its decision-log line. It also carries the two live-session
migration channels: the framework revision notice and the trunk-freshness check.
"""

from __future__ import annotations

from typing import List

import hooklib as lib

HOOK = "continuous-work-reinject"

CONTRACT = """A turn ends when the WORK IS FINISHED, or when one of four Proven Exceptions applies AND you have proven it:
an irreversible action, sensitive information, a genuine design fork, or a hard blocker. Nothing else.

Stopping in order to obtain permission to continue is FORBIDDEN. Any habit, older rule, prior session or
phase description telling you to pause periodically, check in, report at intervals, or seek approval before
carrying on is VOID for the duration of the task.

None of these ends a turn:
  * an unrequested summary, status report or progress recap — report when the work is DONE, not partway;
  * "shall I continue?" / "should I proceed?" / "let me know if you want me to go on";
  * proposing the next steps instead of performing them;
  * waiting on background agents YOU dispatched — do the unblocked work while they run;
  * context-window pressure. Compaction is automatic and is not yours to invoke.

Substituting easier adjacent work for the hard task and ending on a polished report is a DISGUISED check-in,
and is the single most common form of this failure. An accurate, evidence-backed report does not make a stop
legitimate — the accuracy is what disguises it.

If a Proven Exception genuinely applies, ask in ONE shape: at most five lines — one line of context, two to
four options each with a one-line consequence, the recommended option FIRST and marked (Recommended), plain
words with nothing the reader must look up. Reversible decisions are never asked: decide, record, continue.
Record the question where the work lives (the issue, or the spec's qa_log.md) and add an AWAITING_USER line
to this run's resume_state.md naming the ACTUAL reason (e.g. `AWAITING_USER: waiting on the production
credential for the smoke test`) — a placeholder or a one-word token is REJECTED — then immediately continue
with every part of the task that does not depend on the answer.

Independent work runs in PARALLEL (review lanes, research, the tasks of a wave: one message), and a pipeline
is awaited with the wrapper's blocking wait as a BACKGROUND task, never with sleep.
"""


def run(ctx: lib.Context) -> lib.Decision:
    out: List[str] = []
    rule = f"{ctx.host.rules_dir}/continuous-work.md"
    out.append(f"## Continuous work is in force ({rule})\n")
    source = ctx.payload.source or "unknown"
    if source == "compact":
        out.append(
            "The conversation was just COMPACTED. Details of earlier tool calls and reasoning are gone; the WORK\n"
            "is not. Do NOT restart, re-plan, summarize, or ask whether to continue — re-read the state below plus\n"
            "any file you still need, then resume the recorded step.\n"
        )
    else:
        out.append(
            f"Session start (source: {source}). If work is already in flight below, continue it.\n"
        )
    out.append(CONTRACT)

    notice = lib.revision_notice(ctx.hooks_dir)
    if notice:
        out.append(notice)

    stale = lib.framework_stale(ctx.project_dir, ctx.contract_version, ctx.host)
    if stale is not None:
        ref, version = stale
        out.append(
            f"FRAMEWORK STALE: {ref} carries framework {version}; this checkout runs {ctx.contract_version}. The rules,\n"
            "phases and agents you were loaded with were replaced. If `git status --porcelain` in the checkout prints\n"
            f"nothing and HEAD is an ancestor of {ref}, run `git merge --ff-only {ref}` there (the one sanctioned move\n"
            f"of local main); otherwise ask the operator, in five lines, to update the checkout. Then read\n"
            f"{ctx.host.hooks_dir}/REVISION_NOTICE.md.\n"
        )

    sid = ctx.session_id
    out.append("## Your recorded place in the work\n")
    if not sid:
        out.append(
            "The harness supplied no session id, so this run cannot be identified. Read your own state file "
            "before acting.\n"
        )
        return lib.allow(stdout="\n".join(out))

    base = ctx.state_base
    verdict, run_dir = ctx.resolve()
    if verdict == lib.OWNED and run_dir is not None:
        state = run_dir / lib.RESUME_FILENAME
        lines = [f"State file: {state}"]
        for name in (
            "MODE",
            "Status",
            "Phase",
            "CURRENT_ISSUE",
            "BRANCH",
            "WORKTREE",
            "PR",
            "WORKABLE_ISSUES_REMAIN",
            "AWAITING_USER",
        ):
            value = ctx.field(state, name) or "(unrecorded)"
            lines.append(f"- {name + ':':<24} {value}")
        out.append("\n".join(lines) + "\n")
        if lib.is_substantive_escalation(ctx.field(state, "AWAITING_USER")):
            out.append(
                "An escalation/approval wait IS recorded above. Verify it is still real before anything else: if it\n"
                "has been answered, or has cleared, append `AWAITING_USER: none` at the END of that file and carry\n"
                "on. While it genuinely stands, work every part of the task that does NOT depend on the answer —\n"
                "a recorded wait is never a licence to idle.\n"
            )
        else:
            out.append(
                "Resume this phase NOW. Verify the record against reality first (git status in the worktree, the\n"
                "issue and PR via the wrapper) — reality wins; reconcile the file to it. Never redo a step the\n"
                "evidence shows is done. Correct a field by APPENDING a new block at the END of that file: every hook\n"
                "reads the LAST occurrence, so an edit at the top is read by nobody.\n"
            )
        ctx.log(HOOK, "INJECTED", f"run={sid[:8]} source={source}")
    elif verdict == lib.BROKEN:
        expected = (
            (run_dir / lib.RESUME_FILENAME) if run_dir is not None else "(unknown)"
        )
        out.append(
            "CANNOT BE READ. The registry declares a run for this session, but its state file does not exist:\n"
            f"    {expected}\n\n"
            "Every Stop gate is therefore judging this session on nothing, and the next one will REFUSE your\n"
            "turn-end until this is repaired. Create that exact path — do NOT invent a readable run-id label,\n"
            "because the gates key on the registry run id and a hand-chosen name puts your state where nothing\n"
            f"reads it. Include a plain `SESSION_ID: {sid}` line. Then carry on with the work.\n"
        )
        ctx.log(HOOK, "BROKEN", f"run={sid[:8]} expected={expected}")
    else:
        out.append(
            "No orchestrator/spec run is registered for this session, so there is no recorded place to restore.\n"
            "That is normal for an ordinary session. It is NOT an invitation to guess: this hook deliberately\n"
            'does not fall back to "the most recently touched run", because doing so previously handed one\n'
            "session another run's issue number, branch and worktree as though they were its own.\n"
        )
        singleton = lib.resolve_owned_state_file(base, sid, ctx.states)
        if singleton is not None and singleton.is_file():
            lines = [
                "A single-run spec workflow IS recorded at the shared location:",
                f"    {singleton}",
            ]
            for name in ("CURRENT_SPEC", "Phase", "Status", "CURRENT_TASK"):
                lines.append(
                    f"- {name + ':':<24} {ctx.field(singleton, name) or '(unrecorded)'}"
                )
            lines.append(
                "Re-read that spec's tasks.md and its decision log, then continue the recorded phase."
            )
            out.append("\n".join(lines) + "\n")
            ctx.log(
                HOOK,
                "UNREGISTERED_SINGLETON",
                f"session={sid[:8]} spec_state={singleton}",
            )
        else:
            ctx.log(HOOK, "UNREGISTERED", f"session={sid[:8]}")

    dirty = lib._git(["status", "--porcelain"], ctx.project_dir)  # noqa: SLF001 — library helper
    if dirty and dirty.strip():
        count = len([line for line in dirty.splitlines() if line.strip()])
        out.append(
            f"Note: the working tree has {count} uncommitted change(s) — likely work in progress. Finish and "
            "commit\nit per keep-git-clean.md rather than treating it as done.\n"
        )
    return lib.allow(stdout="\n".join(out))
