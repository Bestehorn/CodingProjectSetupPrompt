#!/usr/bin/env bash
# issue-loop-gate.sh — Stop hook. The PRIMARY mechanical brake against ending a turn on unfinished work.
#
# It enforces one sentence: while this session's run has CLAIMED tracked work and does not affirmatively say it
# is idle, finished, or escalated, the turn MAY NOT END. If the agent tries, this hook blocks (exit 2) and
# tells it to continue.
#
# Wire it as a `Stop` hook in `.claude/settings.json`; it reads the hook JSON on stdin. It is session-identity
# aware, so several concurrent runs in one clone never read each other's state. Loop safety is this gate's own
# bounded consecutive-block counter, default 8 and overridable per project with
# `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` (validated in `hook_resolve_block_cap`, which clamps it to [1, 64] rather
# than letting a typo like `abc` or a `0` silently disable the brake).
#
# ---------------------------------------------------------------------------------------------------------
# WHAT THIS HOOK GOT WRONG BEFORE, ALL MEASURED. Any one of these disabled it.
# ---------------------------------------------------------------------------------------------------------
#
# 1. IDENTITY. It resolved `runs/<state_dir>/resume_state.md` from the registry and `exit 0`d when the file was
#    absent. `session-register.sh` never created that file, so it was absent by default. Across 189 registered
#    sessions in one clone this gate had NEVER blocked a turn-end — provable from the fact that the counter
#    directory it creates only on its blocking path did not exist. FIXED: identity resolves through three
#    session-keyed rungs, and a run that is REGISTERED but has no state is `BROKEN` and BLOCKS.
#
# 2. `WORKABLE_ISSUES_REMAIN` WAS THE GATE CONDITION. It blocked only while that field was `yes`. But
#    `/work-issue <N>` sets it to `no` ON PURPOSE, so that command's runs were never gated AT ALL — the one
#    hook meant to stop an agent abandoning work mid-issue was switched off by the very command most likely to
#    need it. FIXED: that field now only chooses the WORDING, never whether to block.
#
# 3. `stop_hook_active`. It exited 0 the moment the harness set that field, which made a POLICY gate block at
#    most ONCE per continuation chain: nudge once, then free to stop on unfinished work. FIXED: removed. Loop
#    safety is this gate's own bounded, PROGRESS-AWARE counter.
#
# 4. INVISIBILITY. It was silent on allow, so being permanently inert looked identical to being satisfied.
#    FIXED: every invocation appends one line to `.hook-decisions/`. Stderr behaviour is unchanged, so the
#    "an ungated exit produces no message" oracle still holds.
#
# 5. THE BRAKE ARMED ON ONE MAGIC TOKEN. It blocked only while `Status` matched the literal `IN_PROGRESS`, so
#    every other value read as "nothing to hold" — including the value `session-register.sh` itself seeds.
#    MEASURED on a properly seeded, OWNED, pre-acked run at `Phase: IMPLEMENT` with `CURRENT_ISSUE: 574`:
#    `in progress`, `In Progress`, `in-progress`, `WORKING`, `ACTIVE`, `RUNNING` and `IMPLEMENTING` ALL exited
#    0, and nothing anywhere told the agent the vocabulary. FIXED: the polarity is inverted — an unrecognised
#    Status means WORK IN FLIGHT, and only an explicit idle/terminal value releases the brake.
#
# 6. IT COULD TRAP AN ORDINARY SESSION. `session-register.sh` now seeds and registers EVERY session, so the
#    `UNREGISTERED` no-op branch is dead for real sessions and the seeded literal was all that kept a plain
#    chat session unblocked. MEASURED: an ordinary session that recorded a Status was refused and told to
#    "FINISH issue none end to end — implement, prove, PR, CI green, merge, close". FIXED: the brake
#    additionally requires EVIDENCE THAT TRACKED WORK WAS CLAIMED.
#
# 7. THE CAP WAS A DUTY CYCLE, AND THE HANDSHAKE COULD SPEND IT. See the counter and handshake sections.
set -u

# THE TRAP GOES FIRST — before anything that can abort. It was previously installed after `input="$(cat)"` and
# after a `${BASH_SOURCE[0]}` expansion, both of which can abort under `set -u` (`BASH_SOURCE[0]` is unbound
# when bash reads a script from stdin). Nothing should depend on that accident holding.
#
# FAIL CLOSED: a gate that cannot load its own identity code must refuse, not shrug. A stale, unreadable or
# partially-sourced library previously produced `exit 0`, which is indistinguishable from "nothing to guard".
trap 'rc=$?; if (( rc != 0 && rc != 2 )); then
        echo "issue-loop-gate: ABORTED (status $rc) before reaching a decision — refusing the stop rather than allowing it unchecked. Fix the hook or its library, then continue working." >&2
        exit 2
      fi' EXIT

input="$(cat)"

lib="$(dirname "${BASH_SOURCE[0]:-$0}")/hook-state-lib.sh"
# shellcheck source=./hook-state-lib.sh
. "$lib" 2>/dev/null || {
    echo "issue-loop-gate: cannot source $lib — refusing the stop. Restore the library, then continue." >&2
    exit 2
}
command -v hook_task_selftest >/dev/null 2>&1 || {
    echo "issue-loop-gate: $lib sourced only partially (self-test symbol absent) — refusing the stop." >&2
    exit 2
}
hook_task_selftest || {
    echo "issue-loop-gate: library self-test failed — refusing the stop." >&2
    exit 2
}

_HOOK_JSON_INPUT="$input"
hook_payload_init          # parse the payload ONCE, in THIS shell: see the note in hook-state-lib.sh
sid="$(hook_json_string session_id)"
base="$(hook_state_base)"

# A session the harness gave no id for cannot be attributed to a run. Do not interfere: attributing it by any
# other means is precisely the borrow-another-run's-state bug this hook family exists to avoid.
if [[ -z "$sid" ]]; then
    hook_decision_log "$base" "issue-loop-gate" "ALLOW" "no session_id in payload"
    exit 0
fi

counter="$(hook_counter_path "$base" "loop" "$sid")"
resolved="$(hook_resolve_run_dir "$base" "$sid")"
# NORMALIZE. An empty or unrecognised verdict must not fall through: MEASURED with one `set -u` slip injected
# into the resolver, the substitution's subshell aborted, `verdict` was EMPTY, it matched neither guard,
# execution reached the field reads with an empty run dir, and the gate ALLOWED — logging
# `Status='' not IN_PROGRESS`. The EXIT trap could not see it, because the abort was in a SUBSHELL.
verdict="$(hook_normalize_verdict "${resolved%%|*}")"
run_dir="${resolved#*|}"

# ---------------------------------------------------------------------------------------------------------
# Not an orchestrator run -> no-op. This is the ONLY benign non-resolution.
# ---------------------------------------------------------------------------------------------------------
if [[ "$verdict" == "$HOOK_IDENTITY_UNREGISTERED" ]]; then
    hook_counter_reset "$counter"
    hook_decision_log "$base" "issue-loop-gate" "ALLOW" "unregistered session ${sid:0:8}"
    exit 0
fi

blocks="$(hook_counter_read "$counter")"

# at_cap is TRUE once the count is reached OR a previous turn already gave up on this run. The durable marker
# matters: resetting the counter on the cap path made the cap a DUTY CYCLE (measured: 8 refusals, 1 release,
# then 8 more, forever). Only genuine progress or a real release clears it.
at_cap() { (( blocks >= HOOK_BLOCK_CAP )) || hook_counter_is_capped "$counter"; }

allow_at_cap() { # $1 = why the cap was reached
    hook_counter_mark_capped "$counter"
    echo "issue-loop-gate: this gate no longer objects — ${blocks} consecutive blocks for run ${sid:0:8} with no change in the recorded state ($1). THE WORK IS NOT DONE; the gate is standing down so the session cannot wedge, and is NOT certifying completion. Re-launch with /continue-work (or /auto-work for a whole-backlog run) to resume. It re-arms as soon as the run records a change." >&2
    hook_decision_log "$base" "issue-loop-gate" "ALLOW_AT_CAP" "run=${sid:0:8} blocks=$blocks reason=$1"
    exit 0
}

# A block is only legitimate if it can be COUNTED, because the count is the escape. If the counter cannot be
# persisted (a read-only tree, a directory occupying the path, a Windows MAX_PATH overrun) the cap would never
# be reached and the gate would refuse forever. MEASURED on the swallow-failures version: 3 of 3 refusals with
# the counter never advancing. So a failed bump stands the gate down instead of blocking with no escape.
block_or_stand_down() { # $1 = decision-log detail, $2 = short reason
    if ! hook_counter_bump "$counter"; then
        echo "issue-loop-gate: this gate cannot persist its block counter at $counter, so its bounded-escape guarantee does not hold — standing down rather than refusing with no way out. THE WORK MAY NOT BE DONE. Fix the counter path, then re-run." >&2
        hook_decision_log "$base" "issue-loop-gate" "ALLOW_COUNTER_UNWRITABLE" "run=${sid:0:8} counter=$counter reason=$2"
        exit 0
    fi
    hook_decision_log "$base" "issue-loop-gate" "BLOCK" "$1"
}

# ---------------------------------------------------------------------------------------------------------
# BROKEN identity -> FAIL CLOSED. A run registered in the registry whose state file does not exist has never
# established its state, which is itself a contract violation. Allowing the stop here is the exact hole that
# let four turns end unopposed.
# ---------------------------------------------------------------------------------------------------------
if [[ "$verdict" == "$HOOK_IDENTITY_BROKEN" ]]; then
    at_cap && allow_at_cap "identity unrepaired"
    block_or_stand_down "broken identity run=${sid:0:8} expected=$run_dir" "broken identity"
    cat >&2 <<MSG
issue-loop-gate: REFUSING the stop — this session's run state is MISSING, so no gate can judge your work.

The registry declares a run for this session, but the state file it names does not exist:
    $run_dir/$HOOK_RESUME_FILENAME

That means every Stop gate has been INERT for this session. Fix it now, then keep working:

  1. Create that exact directory and file. Use the path above VERBATIM — do not invent a readable run-id
     label. The gates key on the registry's run id, and a hand-chosen name puts your state where nothing
     reads it. That divergence is the measured cause of an agent ending four turns while under an explicit
     instruction never to stop.
  2. The file must carry plain \`Name: value\` lines. A bold \`**Name:**\` spelling is read by NO hook, and a
     line inside a fenced code block is ignored. Include \`SESSION_ID: $sid\` so a hook can recover this run
     even if its state later moves.
  3. Record these fields WITH THESE VALUES, unless you genuinely are mid-work on a tracked issue:

         SESSION_ID: $sid
         RUN_ID: ${sid:0:8}
         MODE: unset
         Status: NOT_STARTED
         Phase: NOT_STARTED
         CURRENT_ISSUE: none
         AWAITING_USER: none

     The VALUES matter as much as the names. This gate treats an UNRECOGNISED \`Status\` as work in flight, so
     inventing one here re-arms the gate against you. If you ARE mid-work on a tracked issue, record the real
     Status, Phase and CURRENT_ISSUE instead.
  4. Then CONTINUE the work you were doing. Do not end the turn to report this.
MSG
    exit 2
fi

state="$run_dir/$HOOK_RESUME_FILENAME"

# Load the state file ONCE in THIS shell. Every `x="$(hook_state_field ...)"` below runs in a subshell, so a
# cache populated inside one dies with it — without this line each field read re-parsed the file, which is
# how a single invocation came to spawn eight awk processes on top of everything else.
hook_state_load "$state"

status="$(hook_state_field "$state" Status)"
phase="$(hook_state_field "$state" Phase)"
awaiting="$(hook_state_field "$state" AWAITING_USER)"
remain="$(hook_state_field "$state" WORKABLE_ISSUES_REMAIN)"
issue="$(hook_state_field "$state" CURRENT_ISSUE)"
mode="$(hook_state_field "$state" MODE)"
spec="$(hook_state_field "$state" CURRENT_SPEC)"
branch="$(hook_state_field "$state" BRANCH)"

# PROGRESS RESETS THE COUNT. The cap message used to claim "N consecutive blocks WITHOUT PROGRESS" while
# nothing measured progress — the counter simply counted blocks. A run advancing every turn reached the cap
# identically to one spinning in place, and was then told it had made no progress and allowed to stop. Now a
# CHANGE in the fields this gate reads clears the count, so a working run never reaches the cap and the message
# is true when it is printed.
if hook_counter_note_progress "$counter" "$status|$phase|$issue|$awaiting|$branch|$remain"; then
    hook_counter_reset "$counter"
    hook_counter_note_progress "$counter" "$status|$phase|$issue|$awaiting|$branch|$remain" >/dev/null 2>&1 || true
    blocks=0
    hook_decision_log "$base" "issue-loop-gate" "PROGRESS" "run=${sid:0:8} recorded state changed; count reset"
fi

# ---------------------------------------------------------------------------------------------------------
# THE RELEASES. Each is an AFFIRMATIVE statement by the run that the turn may end. Anything else holds.
# ---------------------------------------------------------------------------------------------------------

# 1. The run says it has not begun. Only an explicit idle vocabulary counts — an unrecognised Status is work in
#    flight (see fail-open 5 in the header).
if hook_status_is_idle "$status"; then
    hook_counter_reset "$counter"
    hook_decision_log "$base" "issue-loop-gate" "ALLOW" "run=${sid:0:8} Status='$status' is idle"
    exit 0
fi

# 2. The run says it is finished.
if hook_phase_is_terminal "$phase" || hook_phase_is_terminal "$status"; then
    hook_counter_reset "$counter"
    hook_decision_log "$base" "issue-loop-gate" "ALLOW" "run=${sid:0:8} terminal Phase='$phase' Status='$status'"
    exit 0
fi

# 3. The run has recorded a Proven Exception. This is a SELF-ISSUED permission slip, so it must be SUBSTANTIVE
#    rather than merely present: measured releases included `<reason>` (the literal this gate itself used to
#    print, so an agent copying the instruction verbatim disarmed it), `unset` (the idiom the seed establishes
#    via `MODE: unset`), `no`, `false` and `0`.
if hook_is_substantive_escalation "$awaiting"; then
    hook_counter_reset "$counter"
    hook_decision_log "$base" "issue-loop-gate" "ALLOW" "run=${sid:0:8} AWAITING_USER='$awaiting'"
    exit 0
fi

# 4. The run has claimed no tracked work, so this is not the work this gate governs. Required because every
#    session is now seeded and OWNED — without it, an ordinary chat session that recorded a Status was refused
#    and told to finish "issue none". Every orchestrator entry point records at least one of these (the claim
#    step sets CURRENT_ISSUE; the spec workflow sets CURRENT_SPEC), so the brake keeps its full reach.
claim=""
hook_field_is_placeholder "$issue" || claim="issue=$issue"
if [[ -z "$claim" ]] && ! hook_field_is_placeholder "$mode"; then
    # Hyphens are normalised to underscores before matching. `/work-issue` instructed `MODE: single-issue`,
    # which this predicate did NOT match — and an unmatched MODE means LESS blocking, so the failure direction
    # was a fail-open. The command now says `SINGLE_ISSUE`, and the gate accepts either spelling rather than
    # depending on a document and a regex staying in step.
    grep -qiE '^(ISSUE_LOOP|SINGLE_ISSUE|SPEC|BACKLOG|AUTO)' <<<"${mode//-/_}" && claim="mode=$mode"
fi
[[ -z "$claim" ]] && ! hook_field_is_placeholder "$spec" && claim="spec=$spec"
if [[ -z "$claim" ]]; then
    hook_counter_reset "$counter"
    hook_decision_log "$base" "issue-loop-gate" "ALLOW" \
        "run=${sid:0:8} Status='$status' but no tracked work claimed (issue='$issue' mode='$mode' spec='$spec')"
    exit 0
fi

# ---------------------------------------------------------------------------------------------------------
# CONTRACT HANDSHAKE — how a LIVE session picks up a newly deployed contract without restarting.
#
# POSITION: this runs AFTER every release check above, and that ordering is load-bearing twice over.
#   * Evaluated BEFORE them, a routine `CONTRACT_VERSION` bump refused the next turn-end of EVERY live session
#     in the clone — ordinary chat sessions at `Status: NOT_STARTED` included — and delivered a 25-line
#     orchestrator contract to each. MEASURED on a freshly seeded plain session, pre-acked at one version and
#     then bumped.
#   * It must also never PREEMPT the real brake. When it sat above the brake AND could stand the gate down at
#     the cap, an unacked run got 8 blocks and then a FREE STOP on genuinely unfinished work, recurring every
#     9th attempt forever (measured: attempts 1-8 exit 2, attempt 9 exit 0, attempt 10 exit 2). So at cap this
#     branch does NOT stand down: it writes the ack itself and FALLS THROUGH to the brake below. A migration
#     convenience must not be able to spend the brake's budget.
# ---------------------------------------------------------------------------------------------------------
if ! hook_contract_acknowledged "$run_dir"; then
    if at_cap; then
        printf 'auto-acknowledged after %s blocks; the contract was delivered but never acknowledged\n' "$blocks" \
            > "$(hook_contract_ack_file "$run_dir")" 2>/dev/null || true
        hook_decision_log "$base" "issue-loop-gate" "CONTRACT_AUTO_ACK" \
            "run=${sid:0:8} blocks=$blocks; falling through to the brake rather than standing down"
    else
        block_or_stand_down "contract $(hook_contract_version) unacked run=${sid:0:8}" "contract unacknowledged"
        cat >&2 <<MSG
issue-loop-gate: REFUSING the stop — this run has not yet ingested the CURRENT continuous-work contract
($(hook_contract_version)), so it may not be in your context.

THE CONTRACT, in force from now on for this run:

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
  * If a Proven Exception genuinely applies: keep it to a few lines, give a recommendation, record it on the
    issue or in the spec's qa_log.md, and record it MECHANICALLY as an \`AWAITING_USER\` line in this run's
    resume_state.md naming the ACTUAL reason — for example
    \`AWAITING_USER: waiting on the production credential for the smoke test\`. A placeholder or a one-word
    token is rejected; the reason has to be a reason. Then continue with every part of the task that does not
    depend on the answer.

ACKNOWLEDGE AND CONTINUE — two steps, then carry on with the work:

  1. Create this file so this message does not repeat:
         $(hook_contract_ack_file "$run_dir")
  2. Confirm this run's state file carries plain \`Name: value\` lines including \`SESSION_ID: $sid\`,
     \`Status\`, \`Phase\`, \`CURRENT_ISSUE\` and \`AWAITING_USER\`. Append corrections at the END of the
     file; hooks read the LAST occurrence of each field, ignore anything inside a fenced code block, and
     cannot see a bold \`**Name:**\` spelling at all.

Then RESUME the task. Do not end the turn to report having read this.
MSG
        exit 2
    fi
fi

# ---------------------------------------------------------------------------------------------------------
# THE PRIMARY BRAKE. Work is claimed, and the run has not said it is idle, finished, or escalated -> hold.
# ---------------------------------------------------------------------------------------------------------
at_cap && allow_at_cap "still working at phase '$phase'"
block_or_stand_down \
    "run=${sid:0:8} working phase='$phase' status='$status' claim='$claim' remain='$remain'" "unfinished work"

{
    echo "issue-loop-gate (the ISSUE-LOOP brake): REFUSING the stop — run ${sid:0:8} records itself as UNFINISHED."
    echo "    Status: $status"
    echo "    Phase:  $phase"
    echo "    Claimed work: $claim"
    echo ""
    echo "Your own state file says this run has claimed tracked work and has not recorded itself as idle,"
    echo "finished, or escalated — so by that record the work is not done. An unrequested summary, a progress"
    echo "report, or 'shall I continue?' does not end a turn. Neither does waiting on background agents you"
    echo "dispatched — do the unblocked work while they run."
    echo ""
    if grep -qiE '^(yes|true)$' <<<"$remain"; then
        echo "WORKABLE_ISSUES_REMAIN is '$remain': select the next-highest-priority unlocked workable issue"
        echo "YOURSELF (LOAD_ISSUES -> SELECT) and keep going. Which issue to work is your decision, not the"
        echo "user's."
    elif hook_field_is_placeholder "$issue"; then
        echo "This run claims tracked work as $claim. Finish it end to end before any turn ends."
    else
        echo "WORKABLE_ISSUES_REMAIN is '$remain', so this is a single-issue run: FINISH issue $issue end to"
        echo "end — implement, prove, PR, CI green, merge, close — before any turn ends. That field selects"
        echo "this wording only; it does not and cannot release this gate."
    fi
    echo ""
    echo "THE WAYS OUT, all by APPENDING a new block at the END of"
    echo "    $state"
    echo "(hooks read the LAST occurrence of each field):"
    echo "  * finished     -> 'Phase: DONE'  (or COMPLETE/COMPLETED/FINISHED/CLOSED/ABANDONED/ESCALATED)"
    echo "  * not begun    -> 'Status: NOT_STARTED'"
    echo "  * proven pause -> an 'AWAITING_USER' line naming the actual reason in full. A placeholder or a"
    echo "                    one-word token is rejected; write the reason you would give a person."
} >&2
exit 2
