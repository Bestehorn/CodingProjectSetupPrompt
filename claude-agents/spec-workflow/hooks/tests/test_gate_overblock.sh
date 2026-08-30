#!/usr/bin/env bash
# Regression suite for the OVER-BLOCKING defects — every case here was MEASURED wedging a session.
#
# WHY A SEPARATE FILE FROM test_stop_gates.sh
# -------------------------------------------
# That suite asks "does the gate block when it should?". This one asks the opposite question, and the two
# failure directions are not equally visible. A gate that fails OPEN is discovered when work is lost. A gate
# that over-blocks is discovered when a human, mid-task, cannot end a turn — and the remedy they reach for is
# to DELETE THE HOOK. An over-blocking gate is therefore not a milder bug than a fail-open; it is the bug that
# removes the fail-open protection too.
#
# Each case names the finding it pins. All were measured against the shipped hooks before the fix.
set -u

HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARENA="$(mktemp -d 2>/dev/null || echo "/tmp/overblock.$$")"
SID="abcd1234-1111-2222-3333-444455556666"
RUN8="abcd1234"
ORCH="$ARENA/.claude/agent-state/issue-work-orchestrator"

pass=0; fail=0
BAR="=============================================================================================="

reset_arena() {
    rm -rf "$ARENA/.claude" 2>/dev/null || true
    mkdir -p "$ORCH" "$ARENA/.claude/hooks"
    printf '{}' > "$ORCH/registry.json"
    cp "$HOOKS/CONTRACT_VERSION" "$ARENA/.claude/hooks/CONTRACT_VERSION" 2>/dev/null || true
}

register() {
    printf '{"%s":{"session_id":"%s","run_id":"%s","state_dir":"%s"}}' "$SID" "$SID" "$RUN8" "$1" \
        > "$ORCH/registry.json"
}

seed_state() { # <run dir> <Status> <Phase> <AWAITING_USER> <WORKABLE_ISSUES_REMAIN> [CURRENT_ISSUE]
    mkdir -p "$ORCH/runs/$1"
    {
        printf '# Resume state\n'
        printf 'SESSION_ID: %s\n' "$SID"
        printf 'RUN_ID: %s\n' "$RUN8"
        printf 'MODE: unset\n'
        printf 'Status: %s\n' "$2"
        printf 'Phase: %s\n' "$3"
        printf 'AWAITING_USER: %s\n' "$4"
        printf 'WORKABLE_ISSUES_REMAIN: %s\n' "$5"
        printf 'CURRENT_ISSUE: %s\n' "${6:-999}"
    } > "$ORCH/runs/$1/resume_state.md"
}

seed_workflow() { # <run dir> <Phase> <CURRENT_SPEC>
    mkdir -p "$ORCH/runs/$1"
    {
        printf '# Workflow state\n'
        printf 'SESSION_ID: %s\n' "$SID"
        printf 'CURRENT_SPEC: %s\n' "$3"
        printf 'Phase: %s\n' "$2"
        printf 'Status: IN_PROGRESS\n'
        printf 'CURRENT_TASK: 1\n'
    } > "$ORCH/runs/$1/workflow_state.md"
}

ack() {
    local version
    version="$(head -1 "$HOOKS/CONTRACT_VERSION" | tr -d '\r\n[:space:]')"
    printf 'test ack\n' > "$ORCH/runs/$1/contract-ack-$version"
}

append() { printf '%s\n' "$2" >> "$ORCH/runs/$1/resume_state.md"; }

PAYLOAD="$(printf '{"session_id":"%s","cwd":"%s","hook_event_name":"Stop"}' "$SID" "$ARENA")"

run_hook() {
    local rc
    ( cd "$ARENA" && printf '%s' "$PAYLOAD" | bash "$HOOKS/$1" >/dev/null 2>&1 )
    rc=$?
    printf '%s' "$rc"
}

check() {
    if [[ "$2" == "$3" ]]; then printf '  PASS  %-68s (exit %s)\n' "$1" "$3"; pass=$(( pass + 1 ))
    else printf '  FAIL  %-68s expected %s, got %s\n' "$1" "$2" "$3"; fail=$(( fail + 1 )); fi
}

echo "$BAR"
echo "issue-loop-gate.sh"
echo "$BAR"

# F5 — the contract handshake was evaluated BEFORE the benign checks, so a routine CONTRACT_VERSION bump
# refused the next turn-end of EVERY live session in the clone, ordinary chat sessions included.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" NOT_STARTED NOT_STARTED none unknown none
check "F5  unacked contract + NOT_STARTED -> allow" 0 "$(run_hook issue-loop-gate.sh)"

# F7 — Status IN_PROGRESS alone must not hold a turn. session-register.sh now seeds and registers EVERY
# session, so the UNREGISTERED no-op branch is dead and the seeded literal was all that kept a plain session
# unblocked. Measured: an ordinary session that recorded a Status was told to "FINISH issue none end to end".
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS WORKING none unknown none; ack "$RUN8"
check "F7  IN_PROGRESS, no tracked work claimed -> allow" 0 "$(run_hook issue-loop-gate.sh)"

# ...but the brake must keep its full reach over runs that HAVE claimed work — by issue, by MODE, or by spec.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS WORKING none unknown 574; ack "$RUN8"
check "F7  claim by CURRENT_ISSUE -> BLOCK" 2 "$(run_hook issue-loop-gate.sh)"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS WORKING none unknown none; ack "$RUN8"
append "$RUN8" "MODE: SINGLE_ISSUE"
check "F7  claim by MODE -> BLOCK" 2 "$(run_hook issue-loop-gate.sh)"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS WORKING none unknown none; ack "$RUN8"
append "$RUN8" "CURRENT_SPEC: .claude/specs/demo"
check "F7  claim by CURRENT_SPEC -> BLOCK" 2 "$(run_hook issue-loop-gate.sh)"

# F14 — WHERE THE TWO REVIEWS DISAGREED, AND HOW IT RESOLVED.
#
# The over-block review measured `Status: COMPLETED (was IN_PROGRESS)` being REFUSED and called it an
# over-block: a human reads that value as "finished". The fail-open review measured
# `Status: IN_PROGRESS - tasks 1-3 completed, 4 remaining` DISARMING the evidence gate, because a substring
# test found `completed` in it — and noted that phrasing "is not adversarial; it is how a progress note is
# naturally written".
#
# Both are the same value shape read two ways, so only one rule can hold, and FAIL DIRECTION decides it: a
# whole-value match costs a spurious refusal that names its own escape, while a substring match hands the agent
# a way to end a turn by writing a progress note. So a terminal value must be the WHOLE value, and a narrative
# Status BLOCKS. `Status: COMPLETED` or `Phase: DONE` releases, and the refusal says so.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no; ack "$RUN8"
append "$RUN8" "Status: COMPLETED (was IN_PROGRESS)"
check "F14 narrative Status -> BLOCK (whole-value match)" 2 "$(run_hook issue-loop-gate.sh)"

# ...and the escape the refusal names must actually work.
append "$RUN8" "Status: COMPLETED"
check "F14 the named escape 'Status: COMPLETED' -> allow" 0 "$(run_hook issue-loop-gate.sh)"

# The mirror image must NOT release: a narrative that merely mentions a terminal word while saying it is
# working is exactly the fail-open the whole-value match closes.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no; ack "$RUN8"
append "$RUN8" "Status: IN_PROGRESS - tasks 1-3 completed, 4 remaining"
check "F14 'IN_PROGRESS - tasks 1-3 completed' -> BLOCK" 2 "$(run_hook issue-loop-gate.sh)"

# An unambiguous negation IS in the idle vocabulary, so it releases without any narrative ambiguity.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no; ack "$RUN8"
append "$RUN8" "Status: NOT_IN_PROGRESS"
check "F14 Status 'NOT_IN_PROGRESS' -> allow" 0 "$(run_hook issue-loop-gate.sh)"

# F14 — terminal-phase synonyms. Anchored against only four words, an agent was refused for its wording.
for phase_word in COMPLETE FINISHED CLOSED CANCELLED; do
    reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no; ack "$RUN8"
    append "$RUN8" "Phase: $phase_word"
    check "F14 terminal Phase synonym '$phase_word' -> allow" 0 "$(run_hook issue-loop-gate.sh)"
done

# ...and the anchor must still hold: a narrative MENTION of a terminal word is not a terminal phase.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no; ack "$RUN8"
append "$RUN8" "Phase: waiting to be DONE"
check "F14 'waiting to be DONE' is NOT terminal -> BLOCK" 2 "$(run_hook issue-loop-gate.sh)"

# F17 — one invisible trailing space made `none` compare unequal to `none`, which DISABLED the primary brake.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no; ack "$RUN8"
append "$RUN8" "AWAITING_USER: none   "
check "F17 AWAITING_USER 'none   ' no longer releases -> BLOCK" 2 "$(run_hook issue-loop-gate.sh)"

# ...and a real escalation still releases, with trailing whitespace tolerated.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no; ack "$RUN8"
append "$RUN8" "AWAITING_USER: genuine design fork   "
check "F17 a real escalation still releases -> allow" 0 "$(run_hook issue-loop-gate.sh)"

# F2 — the cap must be DURABLE. Resetting the counter on the allow path made it an 8-block duty cycle:
# measured 8 refusals, 1 release, then 8 more, forever.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no; ack "$RUN8"
mkdir -p "$ORCH/.stop-gate-counters"
printf '8' > "$ORCH/.stop-gate-counters/loop-$RUN8.count"
check "F2  at cap -> allow" 0 "$(run_hook issue-loop-gate.sh)"
check "F2  next turn ALSO allows (not a duty cycle)" 0 "$(run_hook issue-loop-gate.sh)"
check "F2  and the turn after that" 0 "$(run_hook issue-loop-gate.sh)"

# ...but genuine progress must RE-ARM the gate, or the marker would be a permanent off-switch.
append "$RUN8" "Phase: DONE"
check "F2  progress clears the marker (allow, and resets)" 0 "$(run_hook issue-loop-gate.sh)"
append "$RUN8" "Phase: FIX"
check "F2  gate re-arms after progress -> BLOCK" 2 "$(run_hook issue-loop-gate.sh)"

# F1 — an unwritable counter means the cap can NEVER be reached, so a block would have no escape at all.
# Measured on the swallow-failures version: 3 of 3 refusals with the counter never advancing.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no; ack "$RUN8"
mkdir -p "$ORCH/.stop-gate-counters/loop-$RUN8.count"    # a DIRECTORY at the counter's own path
check "F1  unwritable counter -> allow, not an escapeless block" 0 "$(run_hook issue-loop-gate.sh)"

echo ""
echo "$BAR"
echo "spec-stop-gate.sh"
echo "$BAR"

# F4 (CRITICAL) — the spec gate never read AWAITING_USER, while continuous-work-reinject.sh and the contract
# text issue-loop-gate.sh itself delivers BOTH instruct the agent to record exactly that field. Measured: the
# loop gate allowed and this gate still refused, telling the agent to "continue". The mechanism contradicted
# the contract it delivers, and the only exit was the block cap.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
seed_workflow "$RUN8" "IMPLEMENT" ".claude/specs/demo"
mkdir -p "$ARENA/.claude/specs/demo"
check "F4  IMPLEMENT + no tasks.md -> BLOCK (baseline)" 2 "$(run_hook spec-stop-gate.sh)"
append "$RUN8" "AWAITING_USER: genuine design fork on the retry policy"
check "F4  + recorded escalation -> allow" 0 "$(run_hook spec-stop-gate.sh)"

# F13 — the phase test was an unanchored substring, so phases meaning the OPPOSITE demanded a task list.
for bad_phase in NOT_IMPLEMENTED PRE_IMPLEMENT_REVIEW IMPLEMENTATION_PLANNING; do
    reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
    seed_workflow "$RUN8" "$bad_phase" ".claude/specs/demo"
    mkdir -p "$ARENA/.claude/specs/demo"
    check "F13 phase '$bad_phase' is not implementation -> allow" 0 "$(run_hook spec-stop-gate.sh)"
done

# ...while the genuine implementation phases must still gate.
for good_phase in IMPLEMENT IMPLEMENTING VERIFY VERIFYING; do
    reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
    seed_workflow "$RUN8" "$good_phase" ".claude/specs/demo"
    mkdir -p "$ARENA/.claude/specs/demo"
    check "F13 phase '$good_phase' IS implementation -> BLOCK" 2 "$(run_hook spec-stop-gate.sh)"
done

# F9 — a placeholder CURRENT_SPEC must be treated as ABSENT rather than as a literal path: treating `none` as a
# path refused every turn-end on `none/tasks.md`, which nothing could create.
#
# But ABSENT at an IMPLEMENTATION phase is itself refused, and that is the other review's finding 5: allowing
# there is byte-for-byte the fail-open this gate's header claims to have fixed as FIX 3, applied one rung up.
# So the two reviews agree on the mechanism and disagree on the verdict, and the verdict resolves to BLOCK —
# with BOTH escapes named in the message (record a real CURRENT_SPEC, or record a Phase outside
# IMPLEMENT/VERIFY). What matters for THIS finding is that the refusal is about an unrecorded spec and never
# about the unopenable path `none/tasks.md`.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
seed_workflow "$RUN8" "IMPLEMENT" "none"
check "F9  CURRENT_SPEC 'none' at IMPLEMENT -> BLOCK (spec unrecorded)" 2 "$(run_hook spec-stop-gate.sh)"
if ( cd "$ARENA" && printf '%s' "$PAYLOAD" | bash "$HOOKS/spec-stop-gate.sh" 2>&1 >/dev/null ) | grep -q 'none/tasks.md'; then
    check "F9  ...and NOT about the path 'none/tasks.md'" "absent" "present"
else
    check "F9  ...and NOT about the path 'none/tasks.md'" "absent" "absent"
fi
# ...while a placeholder spec OUTSIDE an implementation phase is simply nothing to judge.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
seed_workflow "$RUN8" "DESIGN" "none"
check "F9  CURRENT_SPEC 'none' outside IMPLEMENT -> allow" 0 "$(run_hook spec-stop-gate.sh)"

# F8 — for the orchestrator flow this gate exists to serve, the spec lives inside a per-issue WORKTREE while
# CLAUDE_PROJECT_DIR is the main checkout. Measured: a real spec with a real tasks.md and a green capture was
# refused on every turn, and the agent could not repair it.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
seed_workflow "$RUN8" "IMPLEMENT" ".claude/specs/retry"
append "$RUN8" "WORKTREE: $ARENA/.claude/worktrees/issue-42"
mkdir -p "$ARENA/.claude/worktrees/issue-42/.claude/specs/retry/evidence/green"
printf -- '- [x] 1 do the thing\n' > "$ARENA/.claude/worktrees/issue-42/.claude/specs/retry/tasks.md"
printf '5 passed in 1.0s\n' > "$ARENA/.claude/worktrees/issue-42/.claude/specs/retry/evidence/green/1.txt"
check "F8  spec inside a recorded WORKTREE is found -> allow" 0 "$(run_hook spec-stop-gate.sh)"

# ...and the worktree spec must still be JUDGED, not merely located.
rm -f "$ARENA/.claude/worktrees/issue-42/.claude/specs/retry/evidence/green/1.txt"
check "F8  worktree spec with missing evidence -> BLOCK" 2 "$(run_hook spec-stop-gate.sh)"

# F8b — an unresolvable CURRENT_SPEC means the gate cannot SEE the work, not that the work is unproven.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
seed_workflow "$RUN8" "IMPLEMENT" ".claude/specs/nowhere-at-all"
check "F8b unresolvable CURRENT_SPEC -> allow (cannot judge)" 0 "$(run_hook spec-stop-gate.sh)"

# F10 — the evidence predicates matched a bare WORD anywhere in the capture, so a test NAME or a comment
# blocked the turn. The only escape was to EDIT THE EVIDENCE FILE, i.e. to falsify the proof — the worst
# incentive an evidence gate can create.
prep_evidence() { # <capture text>
    reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
    seed_workflow "$RUN8" "IMPLEMENT" ".claude/specs/demo"
    mkdir -p "$ARENA/.claude/specs/demo/evidence/green"
    printf -- '- [x] 1 do the thing\n' > "$ARENA/.claude/specs/demo/tasks.md"
    printf '%s' "$1" > "$ARENA/.claude/specs/demo/evidence/green/1.txt"
}

prep_evidence 'test_reports_skipped_reason PASSED
1000 passed in 12s
'
check "F10 a test NAME containing 'skipped' -> allow" 0 "$(run_hook spec-stop-gate.sh)"

prep_evidence '# earlier this run: 3 failed, now fixed
1000 passed in 12s
'
check "F10 a COMMENT mentioning failures -> allow" 0 "$(run_hook spec-stop-gate.sh)"

# ...while a genuine summary counter must still block, in both directions.
prep_evidence '999 passed, 1 skipped in 12s
'
check "F10 a real '1 skipped' summary -> BLOCK" 2 "$(run_hook spec-stop-gate.sh)"

prep_evidence '997 passed, 3 failed in 12s
'
check "F10 a real '3 failed' summary -> BLOCK" 2 "$(run_hook spec-stop-gate.sh)"

prep_evidence '2 errors, 5 passed in 12s
'
check "F10 a real '2 errors' summary -> BLOCK" 2 "$(run_hook spec-stop-gate.sh)"

prep_evidence '1000 passed, 0 failed, 0 skipped in 12s
'
check "F10 explicit ZERO counters -> allow" 0 "$(run_hook spec-stop-gate.sh)"

echo ""
echo "$BAR"
echo "session-register.sh — a seeding failure must leave the session INERT, not WEDGED"
echo "$BAR"

# F6 — the registry entry was written BEFORE the state was seeded, and a seeding failure was a silent exit 0.
# That MANUFACTURED the BROKEN identity both gates fail closed on: measured with `runs` occupied by a regular
# file, the hook exited 0, the registry held a complete entry, no state existed, and BOTH gates then refused
# every turn-end with no stderr and no log line to explain why. Inertness is the correct failure mode here.
reset_arena
printf 'not a directory\n' > "$ORCH/runs"
( cd "$ARENA" && printf '{"session_id":"%s","source":"startup","cwd":"%s"}' "$SID" "$ARENA" \
    | bash "$HOOKS/session-register.sh" >/dev/null 2>&1 )
check "F6  register exits 0 when seeding is impossible" 0 "$?"
if grep -q "$SID" "$ORCH/registry.json" 2>/dev/null; then
    check "F6  registry left UNTOUCHED (so the session is inert)" "absent" "present"
else
    check "F6  registry left UNTOUCHED (so the session is inert)" "absent" "absent"
fi
check "F6  loop gate therefore does NOT block" 0 "$(run_hook issue-loop-gate.sh)"
check "F6  spec gate therefore does NOT block" 0 "$(run_hook spec-stop-gate.sh)"

# ...and on the happy path it must both seed AND register.
reset_arena
( cd "$ARENA" && printf '{"session_id":"%s","source":"startup","cwd":"%s"}' "$SID" "$ARENA" \
    | bash "$HOOKS/session-register.sh" >/dev/null 2>&1 )
if [[ -f "$ORCH/runs/$RUN8/resume_state.md" ]]; then
    check "F6  happy path seeds the state file" "yes" "yes"
else
    check "F6  happy path seeds the state file" "yes" "no"
fi
if grep -q "$SID" "$ORCH/registry.json" 2>/dev/null; then
    check "F6  happy path writes the registry entry" "yes" "yes"
else
    check "F6  happy path writes the registry entry" "yes" "no"
fi
check "F6  a freshly seeded session is not blocked" 0 "$(run_hook issue-loop-gate.sh)"

rm -rf "$ARENA" 2>/dev/null || true

echo ""
printf 'TOTAL: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
