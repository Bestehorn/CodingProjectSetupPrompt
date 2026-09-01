#!/usr/bin/env bash
# spec-stop-gate.sh — Stop hook for the spec/TDD workflow. Blocks turn-end on work that is not PROVEN.
#
# It blocks (exit 2) while the workflow is mid-implementation and any of these holds:
#   - a task is marked complete ([x]) in tasks.md but has no test-evidence capture;
#   - the latest paired-test capture shows failures / errors;
#   - a green capture contains skipped/xfail tests (the vacuous-green dodge);
#   - the phase is IMPLEMENT/VERIFY but tasks.md DOES NOT EXIST (see fix 3 below).
#
# It judges PAIRED-TEST captures, not the full suite: under the CI-owns-the-test-suite
# contract the suite runs in CI on the pushed SHA, and the push itself is gated separately
# by spec-tdd-gate.sh. What this hook prevents is stopping with a task ticked off that no
# test ever exercised.
#
# Wire it as a `Stop` hook in `.claude/settings.json`; it reads the hook JSON on stdin. Exit 0 allows the turn
# to end, exit 2 blocks it and delivers the reason on stderr. Outside an implementation phase it is a no-op.
# Loop safety is this gate's own bounded consecutive-block counter, default 8 and overridable per project with
# `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` (validated in `hook_resolve_block_cap`, which clamps it to [1, 64] rather
# than letting a typo like `abc` or a `0` silently disable the brake).
#
# ---------------------------------------------------------------------------------------------------------
# FOUR FAIL-OPENS FIXED HERE, all measured on the previous version.
# ---------------------------------------------------------------------------------------------------------
#
# 1. THE MTIME BORROW. When the registry lookup failed — and it failed on every host without `jq`, because the
#    lookup was guarded by `command -v jq` with no fallback — this gate fell back to
#        ls -t "$base"/*/workflow_state.md "$base"/*/runs/*/workflow_state.md | head -1
#    i.e. THE MOST RECENTLY TOUCHED workflow state in the whole clone, belonging to whichever run touched it
#    last. With several concurrent worktrees that is routinely another run's state, so this gate could judge
#    one session against a stranger's phase and evidence. FIXED: resolution is now `hook_resolve_owned_state_file`,
#    every rung of which is session-keyed. There is no mtime rung. A session with no resolvable run of its own
#    may still use the documented single-run `spec-conductor/` location, and nothing else.
#
# 2. IDENTITY-ABSENCE READ AS NO-OBLIGATION. A missing state file produced `exit 0`. Since `session-register.sh`
#    never created one, that was the default state — and this gate had never once blocked a turn-end in a clone
#    with 189 registered sessions. FIXED: a run DECLARED in the registry with no state file is `BROKEN` and
#    blocks.
#
# 3. `tasks.md` ABSENT ALLOWED THE STOP. The gate exited 0 when the file was missing — so it switched itself
#    off in precisely the condition that means "the mandatory task list has not been written yet". An agent
#    that stopped mid-implementation before writing tasks.md was waved through by the very hook meant to catch
#    it. FIXED: absent tasks.md at phase IMPLEMENT/VERIFY now BLOCKS.
#
# 4. `stop_hook_active`. Honouring it let this policy gate block at most ONCE per continuation chain. FIXED:
#    removed; loop safety is this gate's own bounded consecutive-block counter.
set -u

# THE TRAP GOES FIRST, before anything that can abort. It used to sit after `input="$(cat)"` and after a
# `${BASH_SOURCE[0]}` expansion, both of which can abort under `set -u` (`BASH_SOURCE[0]` is unbound when bash
# reads a script from stdin), so its coverage of those lines was accidental rather than designed.
#
# FAIL CLOSED on the library: any termination that is neither a clean allow (0) nor a deliberate block (2)
# becomes a block with a named reason. Without the trap, an unreadable or partially sourced library aborts at
# status 1, which the harness treats as a NON-BLOCKING error — so the gate would fail OPEN exactly when its own
# machinery is broken.
trap 'rc=$?; if (( rc != 0 && rc != 2 )); then
        echo "spec-stop-gate: ABORTED (status $rc) before reaching a decision — refusing the stop rather than allowing it unchecked." >&2
        exit 2
      fi' EXIT

input="$(cat)"

lib="$(dirname "${BASH_SOURCE[0]:-$0}")/hook-state-lib.sh"
# shellcheck source=./hook-state-lib.sh
. "$lib" 2>/dev/null || {
    echo "spec-stop-gate: cannot source $lib — refusing the stop. Restore the library, then continue." >&2
    exit 2
}
command -v hook_task_selftest >/dev/null 2>&1 || {
    echo "spec-stop-gate: $lib sourced only partially (self-test symbol absent) — refusing the stop." >&2
    exit 2
}
hook_task_selftest || {
    echo "spec-stop-gate: library self-test failed — refusing the stop." >&2
    exit 2
}

_HOOK_JSON_INPUT="$input"
sid="$(hook_json_string session_id)"
base="$(hook_state_base)"
counter="$(hook_counter_path "$base" "spec" "${sid:-nosession}")"

blocks="$(hook_counter_read "$counter")"

# The cap is durable, not a duty cycle: resetting the counter here made it 8-blocks-1-release-8-blocks forever.
# Only a genuine non-blocking pass (`allow`) clears the marker.
at_cap() { (( blocks >= HOOK_BLOCK_CAP )) || hook_counter_is_capped "$counter"; }
allow_at_cap() {
    hook_counter_mark_capped "$counter"
    echo "spec-stop-gate: this gate no longer objects — ${blocks} consecutive blocks with no change in the evidence ($1). THE WORK IS NOT PROVEN; the gate is standing down so the session cannot wedge, and is NOT certifying the work. It re-arms as soon as the evidence changes." >&2
    hook_decision_log "$base" "spec-stop-gate" "ALLOW_AT_CAP" "blocks=$blocks reason=$1"
    exit 0
}
# A block must be COUNTABLE, because the count is the only escape. An unwritable counter would otherwise mean
# a refusal with no way out at all.
block() { # $1 = log detail; body already printed to stderr by the caller
    if ! hook_counter_bump "$counter"; then
        echo "spec-stop-gate: this gate cannot persist its block counter at $counter, so its bounded-escape guarantee does not hold — standing down rather than refusing without a way out. THE WORK MAY NOT BE PROVEN." >&2
        hook_decision_log "$base" "spec-stop-gate" "ALLOW_COUNTER_UNWRITABLE" "counter=$counter reason=$1"
        exit 0
    fi
    hook_decision_log "$base" "spec-stop-gate" "BLOCK" "$1"
    exit 2
}
allow() { # $1 = log detail
    hook_counter_reset "$counter"
    hook_decision_log "$base" "spec-stop-gate" "ALLOW" "$1"
    exit 0
}

# A run declared in the registry with no state file has never established its state. The loop gate carries the
# full repair instructions; this gate refuses too, briefly, so a spec-only project is not left unguarded.
if [[ -n "$sid" ]]; then
    # ONE resolution, then split it. Asking three times (verdict, run dir, state file) re-ran the whole ladder
    # each time, and where `jq` is absent every rung spawns a python interpreter: measured at 11,868 ms of
    # added latency per turn-end across the two Stop gates before the library gained its per-process memo.
    resolved="$(hook_resolve_run_dir "$base" "$sid")"
    # An empty or unrecognised verdict becomes BROKEN. Measured with one `set -u` slip in the resolver: the
    # substitution's subshell aborted, the verdict was EMPTY, it matched no guard, and the gate ALLOWED — and
    # the EXIT trap could not see it, because the abort happened in a SUBSHELL.
    verdict="$(hook_normalize_verdict "${resolved%%|*}")"
    run_dir="${resolved#*|}"
    if [[ "$verdict" == "$HOOK_IDENTITY_BROKEN" ]]; then
        at_cap && allow_at_cap "identity unrepaired"
        {
            echo "spec-stop-gate: REFUSING the stop — this session's run state is MISSING, so no gate can judge your work."
            echo "Create $run_dir/$HOOK_RESUME_FILENAME (that exact path — do not invent a run-id label) with plain"
            echo "\`Name: value\` lines including SESSION_ID: $sid, then CONTINUE. Do not end the turn to report this."
        } >&2
        block "broken identity run=${sid:0:8}"
    fi
fi

# An OWNED run with NO workflow_state.md is the BROKEN condition one file down. It used to be reported as "no
# spec workflow here": MEASURED, a run whose registry entry and resume_state.md were present with
# `Phase: IMPLEMENT` but whose workflow_state.md had been deleted resolved OWNED, produced an empty state file,
# and this gate exited 0. Absence of state read as absence of obligation, again. Only an UNREGISTERED session
# may legitimately produce "no workflow state".
if [[ -n "$sid" ]] && hook_owned_workflow_missing "$base" "$sid"; then
    at_cap && allow_at_cap "workflow state unrepaired"
    owned_dir="$(hook_identity_run_dir "$base" "$sid")"
    {
        echo "spec-stop-gate (the EVIDENCE gate): REFUSING the stop — this run OWNS state but its workflow"
        echo "state file does not exist, so this gate cannot judge the implementation at all:"
        echo "    $owned_dir/$HOOK_STATE_FILENAME"
        echo ""
        echo "Create that exact path with plain \`Name: value\` lines carrying at least SESSION_ID, CURRENT_SPEC,"
        echo "Phase, Status and CURRENT_TASK, then CONTINUE. If this run has no spec workflow, record"
        echo "\`CURRENT_SPEC: none\` and \`Phase: NOT_STARTED\` and this gate will stand aside."
    } >&2
    block "owned run with no workflow state run=${sid:0:8}"
fi

state_file="$(hook_resolve_owned_state_file "$base" "$sid")"
[[ -n "$state_file" && -f "$state_file" ]] || allow "no workflow state owned by session ${sid:0:8}"

# Load the state file ONCE in THIS shell. Every `x="$(hook_state_field ...)"` below runs in a subshell, so a
# cache populated inside one dies with it — without this line each field read re-parsed the file, which is
# how a single invocation came to spawn eight awk processes on top of everything else.
hook_state_load "$state_file"

phase="$(hook_state_field "$state_file" Phase)"
status="$(hook_state_field "$state_file" Status)"
spec_dir="$(hook_state_field "$state_file" CURRENT_SPEC)"

# WHOLE-VALUE match, via the library function — NOT a raw `grep -qiE "^($HOOK_TERMINAL_PHASES)"`.
#
# That raw form is anchored only at the START, so it released on a PREFIX: MEASURED,
# `Status: COMPLETED (was IN_PROGRESS)` matched `^COMPLETED` and this gate ALLOWED the stop, while
# `hook_phase_is_terminal` correctly answers no for the same string. This project ADJUDICATED that exact value
# — two adversarial reviews disagreed about it, and the resolution was whole-value matching, because a
# substring test lets an agent end a turn by writing a progress note (`IN_PROGRESS - tasks 1-3 completed`
# measured as disarming this very gate). The loop gate was fixed and pinned; this gate kept the losing side.
# Route every terminal test through the library so the two gates cannot disagree again.
hook_phase_is_terminal "$status" && allow "workflow status '$status' is terminal"

# A RECORDED ESCALATION IS HONOURED HERE TOO. This gate did not read `AWAITING_USER` at all, while
# `continuous-work-reinject.sh` and the contract text `issue-loop-gate.sh` itself delivers BOTH instruct the
# agent to record exactly that field and then keep working. MEASURED: after appending
# `AWAITING_USER: design fork on retry policy`, the loop gate allowed (rc=0) and this gate still refused
# (rc=2) while telling the agent to "continue" — so an agent that did precisely what it was told was trapped,
# with the block cap as its only exit. A mechanism must not contradict the contract it delivers.
#
# Read from `resume_state.md` beside the workflow state, because that is where the field is recorded and where
# the other two hooks tell the agent to put it; fall back to the workflow state for a run that put it there.
# The SAME substance test the loop gate applies — `hook_is_substantive_escalation`, not the weaker
# "is it a placeholder" check this gate used to use. The two gates read the SAME field and must not disagree
# about whether it counts, and the weaker form was measurably more permissive: a one-word token such as
# `AWAITING_USER: waiting` released THIS gate while the loop gate rejected it. That asymmetry is harmless only
# while both gates are registered — in a spec-only project where this is the ONLY Stop gate, it is a fail-open,
# and it hands the agent a way to end a turn with a word instead of a reason. `AWAITING_USER` is a
# self-issued permission slip; both gates hold it to the same standard.
awaiting="$(hook_state_field "$(dirname "$state_file")/$HOOK_RESUME_FILENAME" AWAITING_USER)"
[[ -n "$awaiting" ]] || awaiting="$(hook_state_field "$state_file" AWAITING_USER)"
hook_is_substantive_escalation "$awaiting" && allow "escalation recorded: AWAITING_USER='$awaiting'"

# The phase is matched as a WORD, not a substring. Measured with the unanchored `*IMPLEMENT*|*VERIFY*` form:
# `NOT_IMPLEMENTED`, `PRE_IMPLEMENT_REVIEW`, `IMPLEMENTATION_PLANNING` and `REVIEW (next: IMPLEMENT)` were all
# treated as implementation phases and refused for a missing `tasks.md` — four phases that mean the opposite of
# one.
# Compared in UPPERCASE. This `case` was the ONLY case-sensitive state comparison in the whole hook family —
# every other read is case-insensitive — so `Phase: implement` silently took the allow arm and switched the
# gate off, while logging a line that read like a correct decision. An agent had no signal that this one field
# behaved differently from its neighbours.
phase_uc="$(printf '%s' "$phase" | tr '[:lower:]' '[:upper:]')"
case "$phase_uc" in
    IMPLEMENT|IMPLEMENT_*|IMPLEMENTING|VERIFY|VERIFY_*|VERIFYING) : ;;
    *) allow "phase '$phase' is not an implementation phase" ;;
esac

# AN ABSENT `CURRENT_SPEC` AT AN IMPLEMENTATION PHASE IS UNFINISHED WORK, NOT "NOTHING TO CHECK".
#
# This is FIX 3's own reasoning, applied one rung higher — where it was previously missing. The gate used to
# `allow` here, which is byte-for-byte the fail-open its header claims to have fixed: MEASURED, a seeded
# `workflow_state.md` plus `Phase: IMPLEMENT` and `Status: IN_PROGRESS` exited 0 logging
# `ALLOW no CURRENT_SPEC recorded`, and the (correct, working) absent-tasks.md refusal only fired once a real
# CURRENT_SPEC was appended. So an agent that stopped mid-implementation before recording its spec was waved
# through by the very hook meant to catch exactly that.
#
# It is reached ONLY past the phase check above, so the phase genuinely is IMPLEMENT/VERIFY. A placeholder
# value (`none`, empty, `<spec>`) is treated as absent rather than as a path — measured, treating `none` as a
# path refused every turn-end on `none/tasks.md`, which nothing could create. Both escapes are named in the
# message, because a refusal whose escape is undiscoverable is indistinguishable from a wedge.
if hook_field_is_placeholder "$spec_dir"; then
    at_cap && allow_at_cap "CURRENT_SPEC still unrecorded"
    {
        echo "spec-stop-gate (the EVIDENCE gate): REFUSING the stop — phase is '$phase' but no CURRENT_SPEC is"
        echo "recorded, so this gate cannot judge the implementation at all."
        echo ""
        echo "Two ways out, both by APPENDING a new block at the END of"
        echo "    $state_file"
        echo "(hooks read the LAST occurrence of each field):"
        echo "  * you ARE implementing a spec -> record 'CURRENT_SPEC: <path to the spec directory>'"
        echo "  * this run has no spec at all -> record a Phase outside IMPLEMENT/VERIFY (for example"
        echo "    'Phase: FIX'), or a terminal 'Phase: DONE' once the work genuinely is done"
        echo ""
        echo "Then CONTINUE the work. Do not end the turn to report this."
    } >&2
    block "no CURRENT_SPEC recorded at implementation phase '$phase'"
fi

# Resolve the spec against every plausible ROOT. For the orchestrator flow this gate exists to serve, the spec
# lives inside a per-issue WORKTREE while `CLAUDE_PROJECT_DIR` is the main checkout. MEASURED with the single
# conditional rebase: a real spec with a real `tasks.md` and a green capture under
# `.claude/worktrees/issue-42/` was refused on every turn, and the agent could not repair it — it cannot make
# the main checkout contain another tree's spec.
spec_root=""
recorded_worktree="$(hook_state_field "$(dirname "$state_file")/$HOOK_RESUME_FILENAME" WORKTREE)"
for candidate_root in "$spec_dir" "${CLAUDE_PROJECT_DIR:-}/$spec_dir" "$recorded_worktree/$spec_dir"; do
    # Skip a candidate whose prefix was empty, which would otherwise probe an absolute path by accident.
    [[ "$candidate_root" == "/$spec_dir" ]] && continue
    if [[ -n "$candidate_root" && -d "$candidate_root" ]]; then
        spec_root="$candidate_root"
        break
    fi
done
# An unresolvable path means the gate cannot SEE the work — not that the work is unproven. Allow, and record
# the reason, so a misconfiguration is visible in the log instead of being silently enforced as a refusal.
[[ -n "$spec_root" ]] || allow "CURRENT_SPEC '$spec_dir' resolves to no directory from any known root"
spec_dir="$spec_root"
tasks="$spec_dir/tasks.md"

# PROGRESS RESETS THE COUNT — the same treatment the loop gate gets, and for the same reason. Without it this
# gate's own stand-down message ("N consecutive blocks with no change in the evidence") was a claim it never
# measured: the counter simply counted blocks, so a run capturing new evidence every turn reached the cap
# identically to one spinning in place, and was then told the evidence had not changed and allowed to stop.
#
# The fingerprint is the evidence STATE, not a clock: the phase, the spec, and the name+size of every capture
# under this spec. Capturing a new result, or a capture growing, changes it; re-running the same turn does not.
evidence_fingerprint="$phase|$spec_dir|$(
    { ls -l "$spec_dir"/evidence/*/*.txt 2>/dev/null | awk '{print $5, $NF}'; } | sort | tr '\n' ';'
)"
if hook_counter_note_progress "$counter" "$evidence_fingerprint"; then
    hook_counter_reset "$counter"
    hook_counter_note_progress "$counter" "$evidence_fingerprint" >/dev/null 2>&1 || true
    blocks=0
    hook_decision_log "$base" "spec-stop-gate" "PROGRESS" "evidence changed; block count reset spec=$spec_dir"
fi

# FIX 3: an absent task list at an implementation phase is unfinished work, not "nothing to check".
if [[ ! -f "$tasks" ]]; then
    at_cap && allow_at_cap "tasks.md still absent"
    {
        echo "spec-stop-gate: REFUSING the stop — phase is '$phase' but the task list does not exist:"
        echo "    $tasks"
        echo ""
        echo "The spec workflow requires tasks.md BEFORE implementation, and this gate used to allow the stop"
        echo "when it was missing — switching itself off in exactly the condition that means the mandatory"
        echo "artifact has not been written. Write tasks.md (test-first, dependency-ordered, every acceptance"
        echo "criterion carrying a task), then continue implementing. Do not end the turn to report this."
        echo ""
        echo "If this project does not use a task list at all, that is a configuration mismatch rather than"
        echo "unfinished work. Record a Phase OUTSIDE IMPLEMENT/VERIFY (for example 'Phase: FIX') by appending"
        echo "a new block at the END of"
        echo "    $state_file"
        echo "and this gate will stand aside. Do NOT instead clear CURRENT_SPEC — at an implementation phase an"
        echo "absent spec is itself refused, for the same reason an absent task list is. A refusal whose escape"
        echo "is undiscoverable is indistinguishable from a wedge, so the escape is named here."
    } >&2
    block "tasks.md absent at phase '$phase' spec=$spec_dir"
fi

problems=""

# 1. Every completed task ([x]) must have an evidence capture. A parent heading (e.g. "- [x] 0. Extend …")
#    is not a unit of work and never gets a bare "0.txt"; its proof lives in its subtasks' captures. So an id
#    that is a strict PREFIX of another checked id is treated as a heading and skipped.
#    Inline emphasis is stripped first, and a checked line whose id CANNOT be parsed is counted as a PROBLEM
#    rather than skipped. Skipping it made the evidence requirement DISAPPEAR for ordinary markdown: MEASURED
#    with an empty evidence directory, both `- [x] **1.1** Write the parser` and `- [x] Write the parser`
#    exited 0 and logged the run as `proven`. Unparseable must not mean unrequired.
checked_ids=""
unparseable=0
while IFS= read -r line; do
    stripped="${line//\*\*/}"
    id="$(sed -E 's/^[[:space:]]*-[[:space:]]*\[[xX]\][[:space:]]*([0-9]+(\.[0-9]+)*).*/\1/' <<<"$stripped")"
    if [[ "$id" == "$stripped" ]]; then
        unparseable=$(( unparseable + 1 ))
        problems+="  - a checked task line carries no parseable task id, so its evidence cannot be located: ${line}"$'\n'
        continue
    fi
    checked_ids+="$id"$'\n'
done < <(grep -E '^[[:space:]]*-[[:space:]]*\[[xX]\]' "$tasks" 2>/dev/null)

while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    # A heading: some other checked id extends this one with a further dotted component.
    if grep -qE "^${id}\." <<<"$checked_ids"; then
        continue
    fi
    green_capture="$spec_dir/evidence/green/${id}.txt"
    red_capture="$spec_dir/evidence/red/${id}.txt"
    if [[ ! -f "$green_capture" && ! -f "$red_capture" ]]; then
        problems+="  - task ${id} is marked complete but has no evidence capture (evidence/green/${id}.txt or evidence/red/${id}.txt)."$'\n'
        continue
    fi
    # EXISTENCE IS NOT PROOF. The check used to stop at `-f`, so ABSENCE of a failure string was treated as
    # PRESENCE of a passing result: MEASURED, two ZERO-BYTE files at `evidence/green/1.1.txt` and `1.2.txt`
    # produced exit 0 and the log line `ALLOW proven at phase 'IMPLEMENT'`. A capture must AFFIRMATIVELY show a
    # passing run. Only GREEN captures are held to this — a `red/` capture is supposed to show a failure.
    if [[ -f "$green_capture" ]]; then
        task_capture="$(grep -vE '^[[:space:]]*#' "$green_capture" 2>/dev/null)"
        if ! grep -qiE '[1-9][0-9]* passed|passed in |^OK$|all tests passed|[1-9][0-9]* tests? ok' <<<"$task_capture"; then
            problems+="  - task ${id}'s green capture exists but shows NO passing result (evidence/green/${id}.txt): an empty or prose-only capture is not proof."$'\n'
        fi
        # EVERY task's OWN capture is scanned for failures, not just the most recently touched one.
        #
        # MEASURED live fail-open: with two checked tasks, `evidence/green/1.txt` reading
        # `3 failed, 5 passed in 2.0s` and `evidence/green/2.txt` written one second later, this gate exited 0
        # and never read the `3 failed`. `touch evidence/green/1.txt` — content unchanged — then produced
        # exit 2. Same bytes, opposite verdict, decided by FILE MTIME. That is the same mtime-dependence this
        # whole change exists to remove (see the header's fix 1), surviving inside the evidence check itself,
        # and it defeated the failure-detection half of the gate for any spec with more than one task.
        #
        # An affirmative pass marker was never sufficient on its own either: `3 failed, 5 passed` satisfies it.
        # Absence of a failure counter has to be checked per task, on that task's own proof.
        if grep -qiE '[1-9][0-9]* (failed|failure|failures|error|errors)\b' <<<"$task_capture"; then
            problems+="  - task ${id}'s green capture reports failures/errors (evidence/green/${id}.txt) — it is not a passing result."$'\n'
        fi
        if grep -qiE '[1-9][0-9]* (skipped|xfailed|xfail|xpassed|deselected)\b' <<<"$task_capture"; then
            problems+="  - task ${id}'s green capture reports skipped/xfail tests (evidence/green/${id}.txt) — resolve them rather than stopping."$'\n'
        fi
    fi
done <<<"$checked_ids"

# 2. The most recent PAIRED-TEST capture must not show failures or vacuous greens.
#    Deliberately scoped to evidence/green/ and NOT evidence/regress/. Under the
#    CI-owns-the-test-suite contract, a regress capture is the CI run's output for the
#    pushed SHA (or a CI-outage full-suite run) rather than this workflow's own paired-test
#    format — and a CI log legitimately contains failure/skip counters about OTHER jobs (a
#    gate-skipped deploy, a failed sibling matrix leg), which would block every stop for no
#    reason. The CI verdict is governed by remote-ci-must-pass.md and the orchestrator,
#    which read structured wrapper output; this hook only judges the local captures whose
#    format the workflow itself produces.
latest_green="$(ls -t "$spec_dir"/evidence/green/*.txt 2>/dev/null | head -1)"
if [[ -n "$latest_green" ]]; then
    # Both predicates are anchored on a runner SUMMARY COUNTER, never on a bare word. Measured with the loose
    # forms: a capture containing the test NAME `test_reports_skipped_reason PASSED` alongside
    # `1000 passed in 12s` was refused for "contains skipped/xfail tests", and one containing the comment
    # `# earlier this run: 3 failed, now fixed` was refused for showing failures. Neither block was fixable
    # except by EDITING THE EVIDENCE FILE, i.e. the gate pressured the agent into falsifying its own proof,
    # which is the worst incentive an evidence gate can create.
    # COMMENT lines are excluded before the counters are read. A runner summary never begins with `#`, but an
    # agent annotating its own capture does — and measured, `# earlier this run: 3 failed, now fixed` beside
    # `1000 passed in 12s` was refused, with editing the evidence as the only escape. Excluding `#` lines is
    # deliberately the narrowest possible carve-out: every real runner line is still read.
    capture="$(grep -vE '^[[:space:]]*#' "$latest_green" 2>/dev/null)"
    if grep -qiE '[1-9][0-9]* (failed|failure|failures|error|errors)\b' <<<"$capture"; then
        problems+="  - latest paired-test capture ($latest_green) shows failures/errors — the tests are not green."$'\n'
    fi
    if grep -qiE '[1-9][0-9]* (skipped|xfailed|xfail|xpassed|deselected)\b' <<<"$capture"; then
        problems+="  - latest paired-test capture ($latest_green) contains skipped/xfail tests — resolve them rather than stopping."$'\n'
    fi
fi

if [[ -n "$problems" ]]; then
    at_cap && allow_at_cap "evidence still unproven"
    {
        echo "spec-stop-gate: REFUSING the stop — the implementation is not yet proven:"
        printf '%s' "$problems"
        echo "Finish the task, run its tests, capture the evidence, and only mark it complete when green."
        echo "Do not end the turn to report progress; continue working."
    } >&2
    block "unproven evidence spec=$spec_dir phase='$phase'"
fi

allow "proven at phase '$phase' spec=$spec_dir"
