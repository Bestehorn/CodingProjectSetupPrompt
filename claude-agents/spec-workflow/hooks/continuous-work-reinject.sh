#!/usr/bin/env bash
# continuous-work-reinject.sh — SessionStart hook (matcher: compact|resume|startup).
#
# Puts two things back into context at the moments an agent is likeliest to have lost them: the
# continuous-work contract, and THIS session's own recorded place in the work. The first turn after an
# automatic compaction is the likeliest moment for a spurious stop, because the conversation holding the
# agent's place was just summarized away.
#
# ---------------------------------------------------------------------------------------------------------
# THE DEFECT THIS HOOK IS WRITTEN TO AVOID — measured, and it caused real damage.
# ---------------------------------------------------------------------------------------------------------
#
# A previous implementation of this idea resolved "which run am I?" like this:
#
#     if [[ -n "$sid" && -f registry.json ]] && command -v jq >/dev/null 2>&1; then ... fi
#     [[ -z "$run_dir" && -n "$sid" && -d "runs/${sid:0:8}" ]] && run_dir="runs/${sid:0:8}"
#     [[ -z "$run_dir" ]] && run_dir="$( ls -td runs/*/ | head -1)"      # <-- THE DEFECT
#
# Two things went wrong at once. `jq` was ABSENT on the host, and that branch had no fallback, so the registry
# was never consulted at all. Then the last line picked THE MOST RECENTLY TOUCHED RUN DIRECTORY, with no
# ownership check — so a session working issue 574 was told, as "your recorded place in the work", that its
# current issue was 571, on another run's branch, in another run's worktree. The agent then reasoned about a
# sibling's state and had to be corrected by the user twice.
#
# It is worth being precise about how bad that fallback is: the library's own resolver REFUSES to borrow state
# it cannot attribute, citing the bug class by name, while this hook borrowed the newest one it could find.
# Two opposite policies in one repository, and the permissive one was the one that spoke to the agent.
#
# So this hook has NO mtime rung. Identity comes from `hook_resolve_run_dir`, every rung of which is keyed on
# the session id. When identity cannot be resolved it SAYS SO. Telling an agent "I could not identify your
# run" is strictly better than telling it a stranger's issue number with total confidence.
#
# ---------------------------------------------------------------------------------------------------------
# HOW IT WORKS, AND HOW TO WIRE IT
# ---------------------------------------------------------------------------------------------------------
#
# SessionStart is one of the few events whose plain stdout Claude Code injects as context the model can see
# and act on. So this hook prints a block and exits 0. It can never block: exit 2 on SessionStart shows
# stderr TO THE USER ONLY, and the agent never sees it. It never writes anything except its decision log.
#
# Matchers: compact = after auto/manual compaction, resume = --continue/--resume, startup = a fresh session
# in a project with work already in flight.
#
#   "SessionStart": [
#     { "matcher": "compact|resume|startup",
#       "hooks": [ { "type": "command",
#                    "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/continuous-work-reinject.sh" } ] }
#   ]
#
# Output is deliberately small — it is injected on every matching session start, and past 10,000 characters
# the harness replaces the text with a path plus a preview, which READS as delivered but is not.
set -u

input="$(cat)"

lib="$(dirname "${BASH_SOURCE[0]}")/hook-state-lib.sh"
# shellcheck source=./hook-state-lib.sh
. "$lib" 2>/dev/null || exit 0          # SessionStart cannot block; never break startup
command -v hook_task_selftest >/dev/null 2>&1 || exit 0
hook_task_selftest || exit 0

_HOOK_JSON_INPUT="$input"
hook_payload_init          # parse the payload ONCE, in THIS shell: see the note in hook-state-lib.sh
sid="$(hook_json_string session_id)"
source_kind="$(hook_json_string source)"
base="$(hook_state_base)"

# The contract goes in unconditionally. It is short, it is the whole point of the hook, and a session that
# does not need it loses nothing by seeing it.
printf '## Continuous work is in force (.claude/rules/continuous-work.md)\n\n'

# WHY THE SOURCE MATTERS. `compact` is the case this hook exists for: the conversation that held the agent's
# place was just summarized away, so the likeliest wrong move is to restart, re-plan, or ask whether to carry
# on. Naming the compaction explicitly is what makes the state block below read as a place to RESUME rather
# than as background information. The other sources get the same contract and a shorter framing.
if [[ "$source_kind" == "compact" ]]; then
    printf 'The conversation was just COMPACTED. Details of earlier tool calls and reasoning are gone; the WORK\n'
    printf 'is not. Do NOT restart, re-plan, summarize, or ask whether to continue — re-read the state below plus\n'
    printf 'any file you still need, then resume the recorded step.\n\n'
else
    printf 'Session start (source: %s). If work is already in flight below, continue it.\n\n' "${source_kind:-unknown}"
fi

cat <<'CONTRACT'
A turn ends when the WORK IS FINISHED, or when one of four Proven Exceptions applies AND you have proven it:
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

If a Proven Exception genuinely applies: keep it to a few lines, include a recommendation, record it where the
work lives (the issue, or the spec's qa_log.md), and add an AWAITING_USER line to this run's resume_state.md
naming the ACTUAL reason (e.g. `AWAITING_USER: waiting on the production credential for the smoke test`) — a
placeholder or a one-word token is REJECTED, so the reason has to be a reason —
then immediately continue with every part of the task that does not depend on the answer.
CONTRACT

if [[ -z "$sid" ]]; then
    printf '\n## Your recorded place in the work\n\nThe harness supplied no session id, so this run cannot be identified. Read your own state file before acting.\n'
    exit 0
fi

resolved="$(hook_resolve_run_dir "$base" "$sid")"
# NORMALIZE, like every other library consumer. An empty or unrecognised verdict — which a `set -u` abort
# inside the resolver's subshell produces — would otherwise fall through this hook's `case` to the
# UNREGISTERED arm and tell the agent "no run is registered for this session". That is the wrong answer in the
# most consequential direction available to THIS hook: it is the one that speaks to the agent, and saying "you
# have no recorded place" to a run that HAS one invites exactly the guessing this hook exists to stop.
verdict="$(hook_normalize_verdict "${resolved%%|*}")"
run_dir="${resolved#*|}"
state="$run_dir/$HOOK_RESUME_FILENAME"

printf '\n## Your recorded place in the work\n\n'

case "$verdict" in
"$HOOK_IDENTITY_OWNED")
    printf 'State file: %s\n' "$state"
    for field in MODE Status Phase CURRENT_ISSUE BRANCH WORKTREE PR WORKABLE_ISSUES_REMAIN AWAITING_USER; do
        value="$(hook_state_field "$state" "$field")"
        printf -- '- %-24s %s\n' "$field:" "${value:-(unrecorded)}"
    done
    # A RECORDED ESCALATION GETS ITS OWN INSTRUCTION, because "resume this phase now" is the wrong advice for
    # a run that is legitimately waiting: the right first act is to check whether the wait is still real. The
    # predicate is `hook_is_substantive_escalation` and NOT the `!= none && != -` comparison a previous
    # implementation used — that form accepted `<reason>` (the literal the gates themselves printed), `unset`
    # (the idiom the seed establishes via `MODE: unset`), `no`, `false` and `0` as genuine escalations, so it
    # would announce a wait that nobody had recorded and invite the agent to sit on it.
    if hook_is_substantive_escalation "$(hook_state_field "$state" AWAITING_USER)"; then
        printf '\nAn escalation/approval wait IS recorded above. Verify it is still real before anything else: if it\n'
        printf 'has been answered, or has cleared, append `AWAITING_USER: none` at the END of that file and carry\n'
        printf 'on. While it genuinely stands, work every part of the task that does NOT depend on the answer —\n'
        printf 'a recorded wait is never a licence to idle.\n'
    else
        printf '\nResume this phase NOW. Verify the record against reality first (git status in the worktree, the\n'
        printf 'issue and PR via the wrapper) — reality wins; reconcile the file to it. Never redo a step the\n'
        printf 'evidence shows is done. Correct a field by APPENDING a new block at the END of that file: every hook\n'
        printf 'reads the LAST occurrence, so an edit at the top is read by nobody.\n'
    fi
    hook_decision_log "$base" "continuous-work-reinject" "INJECTED" "run=${sid:0:8} source=${source_kind:-unknown}"
    ;;
"$HOOK_IDENTITY_BROKEN")
    printf 'CANNOT BE READ. The registry declares a run for this session, but its state file does not exist:\n'
    printf '    %s\n\n' "$state"
    printf 'Every Stop gate is therefore judging this session on nothing, and the next one will REFUSE your\n'
    printf 'turn-end until this is repaired. Create that exact path — do NOT invent a readable run-id label,\n'
    printf 'because the gates key on the registry run id and a hand-chosen name puts your state where nothing\n'
    printf 'reads it. Include a plain `SESSION_ID: %s` line. Then carry on with the work.\n' "$sid"
    hook_decision_log "$base" "continuous-work-reinject" "BROKEN" "run=${sid:0:8} expected=$state"
    ;;
*)
    printf 'No orchestrator/spec run is registered for this session, so there is no recorded place to restore.\n'
    printf 'That is normal for an ordinary session. It is NOT an invitation to guess: this hook deliberately\n'
    printf 'does not fall back to "the most recently touched run", because doing so previously handed one\n'
    printf 'session another run’s issue number, branch and worktree as though they were its own.\n'
    # THE SINGLE-RUN SPEC WORKFLOW IS STILL WORTH SURFACING, and it can be surfaced SAFELY. A previous
    # implementation reached for it with
    #     ls -t "$base"/*/workflow_state.md "$base"/*/runs/*/workflow_state.md | head -1
    # which is the same mtime borrow as the run-directory defect, one directory up: with several concurrent
    # runs it names whichever run touched its state last. `hook_resolve_owned_state_file` gives the intent
    # without the borrow — for an UNREGISTERED session it returns ONLY the documented single-run
    # `spec-conductor/workflow_state.md`, which is a FIXED path and can never be another run's per-run state.
    spec_state="$(hook_resolve_owned_state_file "$base" "$sid")"
    if [[ -n "$spec_state" && -f "$spec_state" ]]; then
        printf '\nA single-run spec workflow IS recorded at the shared location:\n'
        printf '    %s\n' "$spec_state"
        for field in CURRENT_SPEC Phase Status CURRENT_TASK; do
            value="$(hook_state_field "$spec_state" "$field")"
            printf -- '- %-24s %s\n' "$field:" "${value:-(unrecorded)}"
        done
        printf 'Re-read that spec'"'"'s tasks.md and its decision log, then continue the recorded phase.\n'
        hook_decision_log "$base" "continuous-work-reinject" "UNREGISTERED_SINGLETON" \
            "session=${sid:0:8} spec_state=$spec_state"
    else
        hook_decision_log "$base" "continuous-work-reinject" "UNREGISTERED" "session=${sid:0:8}"
    fi
    ;;
esac

# A DIRTY TREE AT SESSION START IS ALMOST ALWAYS UNFINISHED WORK, not a stopping point — and it is the one
# signal available even when no run state resolves at all, which is exactly the UNREGISTERED/BROKEN case above.
# Read-only: `git status --porcelain` never mutates anything.
proj="$(hook_project_dir)"
if command -v git >/dev/null 2>&1 && git -C "$proj" rev-parse --git-dir >/dev/null 2>&1; then
    dirty="$(git -C "$proj" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "${dirty:-0}" -gt 0 ]]; then
        printf '\nNote: the working tree has %s uncommitted change(s) — likely work in progress. Finish and commit\n' "$dirty"
        printf 'it per keep-git-clean.md rather than treating it as done.\n'
    fi
fi

exit 0
