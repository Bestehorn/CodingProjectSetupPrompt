"""issue-loop-gate — Stop gate. The PRIMARY mechanical brake against ending a turn on unfinished work.

One sentence: while this session's run has CLAIMED tracked work and does not affirmatively say it is idle,
finished or escalated, the turn MAY NOT END. Session-identity aware; loop safety is a bounded, progress-aware
block counter (default 8, `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`, clamped to [1, 64]).

What this gate got wrong before, all measured (MIGRATION.md): identity resolved from a registry entry whose
state file never existed (inert for 189 sessions); the gate condition was WORKABLE_ISSUES_REMAIN, which
/work-issue sets to `no`; `stop_hook_active` let it block once per chain; silence on allow hid inertness;
the brake armed on one magic Status token; a seeded ordinary session was told to finish "issue none"; the cap
was a duty cycle and the handshake could spend it.
"""

from __future__ import annotations

from pathlib import Path

import hooklib as lib

HOOK = "issue-loop-gate"
EVENT = "stop"  # the dispatcher runs this gate on this event
ORDER = 20  # framework gates 10..90; a project gate takes >100 (or <10 to run first)

CONTRACT_TEXT = """THE CONTRACT, in force from now on for this run:

  * A turn ends when the WORK IS FINISHED, or when one of four Proven Exceptions applies and you have PROVEN
    it: an irreversible action, sensitive information, a genuine design fork, or a hard blocker. Nothing else.
  * Stopping in order to obtain permission to continue is FORBIDDEN. Any habit, older rule or phase
    description telling you to pause, check in, report at intervals, or seek approval before carrying on is
    VOID for the duration of the task.
  * These specifically DO NOT end a turn: an unrequested progress summary; "shall I continue?"; proposing
    next steps instead of performing them; waiting on background agents you dispatched (do the unblocked work
    meanwhile); context-window pressure (compaction is automatic and is not yours to invoke).
  * Substituting easier adjacent work for the hard task and ending on a polished report is a DISGUISED
    check-in and is the single most common form of this failure. An accurate report does not make a stop
    legitimate — the accuracy is what disguises it.
  * If a Proven Exception genuinely applies, the question has ONE shape: at most five lines — one line of
    context, two to four options each with its one-line consequence, the recommended option FIRST and marked
    (Recommended), in plain words with no ids or references the reader must look up. Reversible decisions are
    never asked: decide, record, continue. Record the question on the issue or in the spec's qa_log.md, and
    MECHANICALLY as an `AWAITING_USER` line in this run's resume_state.md naming the ACTUAL reason — for
    example `AWAITING_USER: waiting on the production credential for the smoke test`. A placeholder or a
    one-word token is rejected. Then continue with every part of the task that does not depend on the answer.
  * Independent work runs in PARALLEL — review lanes, research bursts and the tasks of a wave go out in one
    message — and a pipeline is awaited with the wrapper's blocking wait as a BACKGROUND task, never with
    sleep. The operator's time is the scarce resource.
"""


def _broken_message(sid: str, run_dir: Path) -> str:
    return f"""{HOOK}: REFUSING the stop — this session's run state is MISSING, so no gate can judge your work.

The registry declares a run for this session, but the state file it names does not exist:
    {run_dir / lib.RESUME_FILENAME}

That means every Stop gate has been INERT for this session. Fix it now, then keep working:

  1. Create that exact directory and file. Use the path above VERBATIM — do not invent a readable run-id
     label. The gates key on the registry's run id, and a hand-chosen name puts your state where nothing
     reads it. That divergence is the measured cause of an agent ending four turns while under an explicit
     instruction never to stop.
  2. The file must carry plain `Name: value` lines. A bold `**Name:**` spelling is read by NO hook, and a
     line inside a fenced code block is ignored. Include `SESSION_ID: {sid}` so a hook can recover this run
     even if its state later moves.
  3. Record these fields WITH THESE VALUES, unless you genuinely are mid-work on a tracked issue:

         SESSION_ID: {sid}
         RUN_ID: {sid[:8]}
         MODE: unset
         Status: NOT_STARTED
         Phase: NOT_STARTED
         CURRENT_ISSUE: none
         AWAITING_USER: none

     The VALUES matter as much as the names. This gate treats an UNRECOGNISED `Status` as work in flight, so
     inventing one here re-arms the gate against you. If you ARE mid-work on a tracked issue, record the real
     Status, Phase and CURRENT_ISSUE instead.
  4. Then CONTINUE the work you were doing. Do not end the turn to report this.
"""


def _contract_message(ctx: lib.Context, run_dir: Path, version: str) -> str:
    notice = lib.revision_notice(ctx.hooks_dir) or ""
    return f"""{HOOK}: REFUSING the stop — this run has not yet ingested the CURRENT continuous-work contract
({version}), so it may not be in your context.

{CONTRACT_TEXT}
{notice}
ACKNOWLEDGE AND CONTINUE — two steps, then carry on with the work:

  1. Create this file so this message does not repeat:
         {lib.contract_ack_file(run_dir, version)}
  2. Confirm this run's state file carries plain `Name: value` lines including `SESSION_ID: {ctx.session_id}`,
     `Status`, `Phase`, `CURRENT_ISSUE` and `AWAITING_USER`. Append corrections at the END of the
     file; hooks read the LAST occurrence of each field, ignore anything inside a fenced code block, and
     cannot see a bold `**Name:**` spelling at all.

Then RESUME the task. Do not end the turn to report having read this.
"""


def _freshness_message(ctx: lib.Context, run_dir: Path, ref: str, trunk_version: str) -> str:
    proj = ctx.project_dir
    hooks_rel = ctx.host.hooks_dir
    return f"""{HOOK}: REFUSING the stop — {ref} carries FRAMEWORK REVISION {trunk_version}; this checkout runs
{ctx.contract_version}. The rules, phase fragments, agents and hooks this session works under were REPLACED
on the trunk, and they are read from this checkout, which nobody has moved.

UPDATE THE CHECKOUT NOW, then continue the work:

  1. The sanctioned move — when BOTH of these hold:
         git -C "{proj}" status --porcelain                          # prints nothing: no work to disturb
         git -C "{proj}" merge-base --is-ancestor HEAD {ref}    # strictly behind: nothing to lose
     run
         git -C "{proj}" merge --ff-only {ref}
     A fast-forward of a clean, strictly-behind checkout is reversible (the reflog keeps the old tip) and
     moves no one else's branch; every hook re-reads its code from disk on its next call, so this session
     is on the new framework from that moment. This is the ONE case in which a run may move the shared
     local main (keep-git-clean.md).
  2. Otherwise the checkout holds work that is not yours to disturb: ask the operator in the five-line
     shape to update it, append `AWAITING_USER: waiting for the checkout to be updated to framework
     {trunk_version}` to this run's resume_state.md, and continue every part of the work that does not depend on it.
  3. Then read {hooks_rel}/REVISION_NOTICE.md and act on it, and create this file so this message does
     not repeat:
         {lib.framework_ack_file(run_dir, trunk_version)}

Do not end the turn to report having read this.
"""


def _brake_message(sid: str, state: Path, status: str, phase: str, claim: str, remain: str, issue: str) -> str:
    lines = [
        f"{HOOK} (the ISSUE-LOOP brake): REFUSING the stop — run {sid[:8]} records itself as UNFINISHED.",
        f"    Status: {status}",
        f"    Phase:  {phase}",
        f"    Claimed work: {claim}",
        "",
        "Your own state file says this run has claimed tracked work and has not recorded itself as idle,",
        "finished, or escalated — so by that record the work is not done. An unrequested summary, a progress",
        "report, or 'shall I continue?' does not end a turn. Neither does waiting on background agents you",
        "dispatched — do the unblocked work while they run.",
        "",
    ]
    if remain.strip().lower() in ("yes", "true"):
        lines += [
            f"WORKABLE_ISSUES_REMAIN is '{remain}': select the next-highest-priority unlocked workable issue",
            "YOURSELF (LOAD_ISSUES -> SELECT) and keep going. Which issue to work is your decision, not the",
            "user's.",
        ]
    elif lib.is_placeholder(issue):
        lines += [f"This run claims tracked work as {claim}. Finish it end to end before any turn ends."]
    else:
        lines += [
            f"WORKABLE_ISSUES_REMAIN is '{remain}', so this is a single-issue run: FINISH issue {issue} end to",
            "end — implement, prove, PR, CI green, merge, close — before any turn ends. That field selects",
            "this wording only; it does not and cannot release this gate.",
        ]
    lines += [
        "",
        "THE WAYS OUT, all by APPENDING a new block at the END of",
        f"    {state}",
        "(hooks read the LAST occurrence of each field):",
        "  * finished     -> 'Phase: DONE'  (or COMPLETE/COMPLETED/FINISHED/CLOSED/ABANDONED/ESCALATED)",
        "  * not begun    -> 'Status: NOT_STARTED'",
        "  * proven pause -> an 'AWAITING_USER' line naming the actual reason in full. A placeholder or a",
        "                    one-word token is rejected; write the reason you would give a person.",
    ]
    return "\n".join(lines) + "\n"


def run(ctx: lib.Context) -> lib.Decision:  # noqa: C901 — the brake: every release, then every refusal, in order
    sid = ctx.session_id
    base = ctx.state_base
    if not sid:
        # A session the harness gave no id for cannot be attributed to a run. Attributing it any other way is
        # the borrow-another-run's-state bug this family exists to avoid.
        ctx.log(HOOK, "ALLOW", "no session_id in payload")
        return lib.allow()

    counter = lib.counter_path(base, "loop", sid)
    verdict, run_dir = ctx.resolve()

    if verdict == lib.UNREGISTERED or run_dir is None and verdict != lib.BROKEN:
        lib.counter_reset(counter)
        ctx.log(HOOK, "ALLOW", f"unregistered session {sid[:8]}")
        return lib.allow()

    blocks = lib.counter_read(counter)
    cap = ctx.block_cap

    def at_cap() -> bool:
        # TRUE once the count is reached OR a previous turn already gave up on this run. Durable, so the cap
        # is an escape and not a duty cycle (measured: 8 refusals, 1 release, 8 more, forever).
        return blocks >= cap or lib.counter_is_capped(counter)

    def allow_at_cap(reason: str) -> lib.Decision:
        lib.counter_mark_capped(counter)
        ctx.log(HOOK, "ALLOW_AT_CAP", f"run={sid[:8]} blocks={blocks} reason={reason}")
        return lib.allow(
            stderr=(
                f"{HOOK}: this gate no longer objects — {blocks} consecutive blocks for run {sid[:8]} with no change "
                f"in the recorded state ({reason}). THE WORK IS NOT DONE; the gate is standing down so the session "
                "cannot wedge, and is NOT certifying completion. Re-launch with /continue-work (or /auto-work for a "
                "whole-backlog run) to resume. It re-arms as soon as the run records a change.\n"
            )
        )

    def block_or_stand_down(detail: str, reason: str, message: str) -> lib.Decision:
        # A block is only legitimate if it can be COUNTED, because the count is the escape.
        if not lib.counter_bump(counter):
            ctx.log(
                HOOK,
                "ALLOW_COUNTER_UNWRITABLE",
                f"run={sid[:8]} counter={counter} reason={reason}",
            )
            return lib.allow(
                stderr=(
                    f"{HOOK}: this gate cannot persist its block counter at {counter}, so its bounded-escape "
                    "guarantee does not hold — standing down rather than refusing with no way out. THE WORK MAY NOT "
                    "BE DONE. Fix the counter path, then re-run.\n"
                )
            )
        ctx.log(HOOK, "BLOCK", detail)
        return lib.block(message)

    if run_dir is None:  # every verdict but OWNED returned above; a Stop gate that raises fails closed
        raise RuntimeError(f"{HOOK}: verdict {verdict!r} resolved no run directory")
    if verdict == lib.BROKEN:
        if at_cap():
            return allow_at_cap("identity unrepaired")
        return block_or_stand_down(
            f"broken identity run={sid[:8]} expected={run_dir}",
            "broken identity",
            _broken_message(sid, run_dir),
        )

    state = run_dir / lib.RESUME_FILENAME
    status = ctx.field(state, "Status")
    phase = ctx.field(state, "Phase")
    awaiting = ctx.field(state, "AWAITING_USER")
    remain = ctx.field(state, "WORKABLE_ISSUES_REMAIN")
    issue = ctx.field(state, "CURRENT_ISSUE")
    mode = ctx.field(state, "MODE")
    spec = ctx.field(state, "CURRENT_SPEC")
    branch = ctx.field(state, "BRANCH")

    # PROGRESS RESETS THE COUNT, so a working run never reaches the cap and the cap message is true.
    fingerprint = "|".join([status, phase, issue, awaiting, branch, remain])
    if lib.counter_note_progress(counter, fingerprint):
        lib.counter_reset(counter)
        lib.counter_note_progress(counter, fingerprint)
        blocks = 0
        ctx.log(HOOK, "PROGRESS", f"run={sid[:8]} recorded state changed; count reset")

    # THE RELEASES. Each is an AFFIRMATIVE statement by the run that the turn may end. Anything else holds.
    if lib.status_is_idle(status):
        lib.counter_reset(counter)
        ctx.log(HOOK, "ALLOW", f"run={sid[:8]} Status='{status}' is idle")
        return lib.allow()
    if lib.phase_is_terminal(phase) or lib.phase_is_terminal(status):
        lib.counter_reset(counter)
        ctx.log(HOOK, "ALLOW", f"run={sid[:8]} terminal Phase='{phase}' Status='{status}'")
        return lib.allow()
    if lib.is_substantive_escalation(awaiting):
        lib.counter_reset(counter)
        ctx.log(HOOK, "ALLOW", f"run={sid[:8]} AWAITING_USER='{awaiting}'")
        return lib.allow()

    # The run must have CLAIMED tracked work: every session is seeded and OWNED, so without this an ordinary
    # session that recorded a Status was told to finish "issue none".
    claim = ""
    if not lib.is_placeholder(issue):
        claim = f"issue={issue}"
    elif not lib.is_placeholder(mode) and lib.CLAIMING_MODE_RE.match(mode.replace("-", "_")):
        claim = f"mode={mode}"
    elif not lib.is_placeholder(spec):
        claim = f"spec={spec}"
    if not claim:
        lib.counter_reset(counter)
        ctx.log(
            HOOK,
            "ALLOW",
            f"run={sid[:8]} Status='{status}' but no tracked work claimed (issue='{issue}' mode='{mode}' "
            f"spec='{spec}')",
        )
        return lib.allow()

    # CONTRACT HANDSHAKE — AFTER every release (a routine bump must not refuse idle sessions) and never
    # standing the gate down at the cap (it auto-acks and FALLS THROUGH to the brake).
    version = ctx.contract_version
    if not lib.contract_acknowledged(run_dir, version):
        if at_cap():
            _write_ack(
                lib.contract_ack_file(run_dir, version),
                f"auto-acknowledged after {blocks} blocks; the contract was delivered but never acknowledged\n",
            )
            ctx.log(
                HOOK,
                "CONTRACT_AUTO_ACK",
                f"run={sid[:8]} blocks={blocks}; falling through to the brake rather than standing down",
            )
        else:
            return block_or_stand_down(
                f"contract {version} unacked run={sid[:8]}",
                "contract unacknowledged",
                _contract_message(ctx, run_dir, version),
            )

    # FRAMEWORK FRESHNESS — a fetched trunk carries a newer framework than this checkout. Same shape. Cached
    # on the tracking refs' fingerprint: three git calls per turn-end was the measured cost of asking anew.
    stale = lib.framework_stale_cached(
        ctx.project_dir, version, ctx.host, cache_dir=ctx.state_base / lib.ORCHESTRATOR_DIRNAME
    )
    if stale is not None:
        ref, trunk_version = stale
        ack = lib.framework_ack_file(run_dir, trunk_version)
        if not ack.is_file():
            if at_cap():
                _write_ack(
                    ack,
                    f"auto-acknowledged after {blocks} blocks; the framework notice was delivered "
                    "but never acknowledged\n",
                )
                ctx.log(
                    HOOK,
                    "FRAMEWORK_AUTO_ACK",
                    f"run={sid[:8]} trunk={trunk_version} blocks={blocks}; falling through to the brake",
                )
            else:
                return block_or_stand_down(
                    f"framework stale local={version} trunk={trunk_version} run={sid[:8]}",
                    "framework stale",
                    _freshness_message(ctx, run_dir, ref, trunk_version),
                )

    # THE PRIMARY BRAKE.
    if at_cap():
        return allow_at_cap(f"still working at phase '{phase}'")
    return block_or_stand_down(
        f"run={sid[:8]} working phase='{phase}' status='{status}' claim='{claim}' remain='{remain}'",
        "unfinished work",
        _brake_message(sid, state, status, phase, claim, remain, issue),
    )


def _write_ack(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass
