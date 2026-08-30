#!/usr/bin/env bash
# Exercise the Stop gates against synthetic payloads. Read-only w.r.t. the repo; all state lives in a temp
# project tree that is created and destroyed here.
#
# Every case asserts an EXIT CODE, because that is the whole contract: 0 = allow the turn to end, 2 = block.
# A case that "looks right" but returns 0 where it must return 2 is the exact class of defect these gates
# were found to have, so the assertions are the point and the prose is not.
set -u

HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARENA="$(mktemp -d 2>/dev/null || echo "/tmp/gatetest.$$")"
SID="abcd1234-1111-2222-3333-444455556666"
RUN8="abcd1234"
ORCH="$ARENA/.claude/agent-state/issue-work-orchestrator"

pass=0; fail=0

reset_arena() {
    rm -rf "$ARENA/.claude" 2>/dev/null || true
    mkdir -p "$ORCH" "$ARENA/.claude/hooks"
    printf '{}' > "$ORCH/registry.json"
    # The gates read CONTRACT_VERSION from <project>/.claude/hooks/. Mirror the real one so the ack file name
    # the test writes matches the name the gate computes.
    cp "$HOOKS/CONTRACT_VERSION" "$ARENA/.claude/hooks/CONTRACT_VERSION" 2>/dev/null || true
}

register() { # $1 = state_dir value to declare
    printf '{"%s":{"session_id":"%s","run_id":"%s","state_dir":"%s"}}' "$SID" "$SID" "$RUN8" "$1" \
        > "$ORCH/registry.json"
}

seed_state() { # $1 = run dir name, $2 = Status, $3 = Phase, $4 = AWAITING_USER, $5 = WORKABLE_ISSUES_REMAIN
    mkdir -p "$ORCH/runs/$1"
    cat > "$ORCH/runs/$1/resume_state.md" <<EOF
# Resume state
SESSION_ID: $SID
RUN_ID: $RUN8
Status: $2
Phase: $3
CURRENT_ISSUE: 999
AWAITING_USER: $4
WORKABLE_ISSUES_REMAIN: $5
EOF
}

ack() { # $1 = run dir name
    local version
    version="$(head -1 "$HOOKS/CONTRACT_VERSION" | tr -d '\r\n[:space:]')"
    printf 'test ack\n' > "$ORCH/runs/$1/contract-ack-$version"
}

run_hook() { # $1 = hook file, $2 = payload -> prints exit code
    local rc
    ( cd "$ARENA" && printf '%s' "$2" | bash "$HOOKS/$1" >/dev/null 2>&1 )
    rc=$?
    printf '%s' "$rc"
}

check() { # $1 = label, $2 = expected rc, $3 = actual rc
    if [[ "$2" == "$3" ]]; then
        printf '  PASS  %-64s (exit %s)\n' "$1" "$3"; pass=$(( pass + 1 ))
    else
        printf '  FAIL  %-64s expected %s, got %s\n' "$1" "$2" "$3"; fail=$(( fail + 1 ))
    fi
}

PAYLOAD="$(printf '{"session_id":"%s","cwd":"%s","hook_event_name":"Stop"}' "$SID" "$ARENA")"
NO_SID='{"cwd":"/x","hook_event_name":"Stop"}'

echo "=============================================================================================="
echo "issue-loop-gate.sh — the PRIMARY brake"
echo "=============================================================================================="

reset_arena
check "no session_id in payload -> allow (cannot attribute)" 0 "$(run_hook issue-loop-gate.sh "$NO_SID")"

reset_arena
check "unregistered session (plain chat) -> allow" 0 "$(run_hook issue-loop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"
check "REGISTERED but state file MISSING -> BLOCK (was the 189-session hole)" 2 "$(run_hook issue-loop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
check "contract NOT acknowledged -> BLOCK (live-session migration)" 2 "$(run_hook issue-loop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" NOT_STARTED NOT_STARTED none unknown; ack "$RUN8"
check "acked + Status NOT_STARTED -> allow" 0 "$(run_hook issue-loop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS DONE none no; ack "$RUN8"
check "acked + IN_PROGRESS + terminal Phase DONE -> allow" 0 "$(run_hook issue-loop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX "need a credential" no; ack "$RUN8"
check "acked + IN_PROGRESS + AWAITING_USER recorded -> allow" 0 "$(run_hook issue-loop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no; ack "$RUN8"
check "acked + IN_PROGRESS + non-terminal + remain=no -> BLOCK (the /work-issue hole)" 2 "$(run_hook issue-loop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none yes; ack "$RUN8"
check "acked + IN_PROGRESS + non-terminal + remain=yes -> BLOCK" 2 "$(run_hook issue-loop-gate.sh "$PAYLOAD")"

# The counter is bumped per block; at the cap the gate allows so a session cannot wedge.
reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no; ack "$RUN8"
mkdir -p "$ORCH/.stop-gate-counters"; printf '8' > "$ORCH/.stop-gate-counters/loop-$RUN8.count"
check "at BLOCK_CAP -> allow (bounded, says work is not done)" 0 "$(run_hook issue-loop-gate.sh "$PAYLOAD")"

# Identity recovery: state under an AGENT-INVENTED directory name, discoverable only via SESSION_ID.
reset_arena; register "runs/$RUN8/"; seed_state "run-issue574-20260828T194800Z" IN_PROGRESS FIX none no
ack "run-issue574-20260828T194800Z"
check "state under an invented dir, found by SESSION_ID -> BLOCK not shrug" 2 "$(run_hook issue-loop-gate.sh "$PAYLOAD")"

echo ""
echo "=============================================================================================="
echo "spec-stop-gate.sh — the evidence gate"
echo "=============================================================================================="

seed_workflow() { # $1 = run dir, $2 = Phase, $3 = CURRENT_SPEC (may be empty)
    mkdir -p "$ORCH/runs/$1"
    cat > "$ORCH/runs/$1/workflow_state.md" <<EOF
# Workflow state
SESSION_ID: $SID
CURRENT_SPEC: $3
Phase: $2
Status: IN_PROGRESS
EOF
}

reset_arena
check "no state owned -> allow" 0 "$(run_hook spec-stop-gate.sh "$PAYLOAD")"

# NOTE: this case must create NO state files. Seeding resume_state.md would make identity OWNED, and a run
# that owns state but has no workflow_state.md legitimately has no SPEC workflow — the spec gate is correctly
# a no-op for it. The BROKEN verdict is specifically "the registry declares a run and NOTHING exists".
reset_arena; register "runs/$RUN8/"
check "REGISTERED but NO state at all -> BLOCK" 2 "$(run_hook spec-stop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
# CHANGED DELIBERATELY: an OWNED run with no workflow_state.md is the BROKEN condition one file down, not
# "no spec workflow here". session-register.sh seeds BOTH files, so its absence means it was deleted or the
# seeding failed — and the previous "allow" was absence-of-state read as absence-of-obligation, the same
# shape as the original incident. The refusal names the exact path to create and the way to opt out.
check "owns resume_state but NO workflow_state -> BLOCK" 2 "$(run_hook spec-stop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
seed_workflow "$RUN8" "DESIGN" ".claude/specs/demo"
check "phase DESIGN (outside IMPLEMENT/VERIFY) -> allow" 0 "$(run_hook spec-stop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
seed_workflow "$RUN8" "IMPLEMENT" ".claude/specs/demo"
mkdir -p "$ARENA/.claude/specs/demo"
check "phase IMPLEMENT + tasks.md ABSENT -> BLOCK (was allow)" 2 "$(run_hook spec-stop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
seed_workflow "$RUN8" "IMPLEMENT" ".claude/specs/demo"
mkdir -p "$ARENA/.claude/specs/demo"
printf -- '- [x] 1 do the thing\n' > "$ARENA/.claude/specs/demo/tasks.md"
check "checked task with NO evidence capture -> BLOCK" 2 "$(run_hook spec-stop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
seed_workflow "$RUN8" "IMPLEMENT" ".claude/specs/demo"
mkdir -p "$ARENA/.claude/specs/demo/evidence/green"
printf -- '- [x] 1 do the thing\n' > "$ARENA/.claude/specs/demo/tasks.md"
printf '5 passed in 1.0s\n' > "$ARENA/.claude/specs/demo/evidence/green/1.txt"
check "checked task WITH a green capture -> allow" 0 "$(run_hook spec-stop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
seed_workflow "$RUN8" "IMPLEMENT" ".claude/specs/demo"
mkdir -p "$ARENA/.claude/specs/demo/evidence/green"
printf -- '- [x] 1 do the thing\n' > "$ARENA/.claude/specs/demo/tasks.md"
printf '4 passed, 1 skipped in 1.0s\n' > "$ARENA/.claude/specs/demo/evidence/green/1.txt"
check "green capture containing a SKIP -> BLOCK (vacuous green)" 2 "$(run_hook spec-stop-gate.sh "$PAYLOAD")"

reset_arena; register "runs/$RUN8/"; seed_state "$RUN8" IN_PROGRESS FIX none no
seed_workflow "$RUN8" "IMPLEMENT" ".claude/specs/demo"
mkdir -p "$ARENA/.claude/specs/demo/evidence/green"
printf -- '- [x] 0 parent heading\n- [x] 0.1 subtask\n' > "$ARENA/.claude/specs/demo/tasks.md"
printf '5 passed\n' > "$ARENA/.claude/specs/demo/evidence/green/0.1.txt"
check "parent heading needs no capture of its own -> allow" 0 "$(run_hook spec-stop-gate.sh "$PAYLOAD")"

echo ""
echo "=============================================================================================="
echo "FAIL-CLOSED on a broken library (both gates)"
echo "=============================================================================================="

BROKEN_ARENA="$(mktemp -d 2>/dev/null || echo "/tmp/gatebroken.$$")"
mkdir -p "$BROKEN_ARENA/hooks"
for h in issue-loop-gate.sh spec-stop-gate.sh; do
    cp "$HOOKS/$h" "$BROKEN_ARENA/hooks/$h"
done
printf '# deliberately truncated: no hook_task_selftest\nHOOK_ORCHESTRATOR_DIRNAME=x\n' \
    > "$BROKEN_ARENA/hooks/hook-state-lib.sh"
for h in issue-loop-gate.sh spec-stop-gate.sh; do
    ( cd "$BROKEN_ARENA" && printf '%s' "$PAYLOAD" | bash "hooks/$h" >/dev/null 2>&1 )
    check "$h with a PARTIAL library -> BLOCK (fail closed)" 2 "$?"
done
rm -rf "$BROKEN_ARENA" 2>/dev/null || true

for h in issue-loop-gate.sh spec-stop-gate.sh; do
    MISSING="$(mktemp -d 2>/dev/null || echo "/tmp/gatemissing.$$")"
    mkdir -p "$MISSING/hooks"; cp "$HOOKS/$h" "$MISSING/hooks/$h"
    ( cd "$MISSING" && printf '%s' "$PAYLOAD" | bash "hooks/$h" >/dev/null 2>&1 )
    check "$h with NO library at all -> BLOCK (fail closed)" 2 "$?"
    rm -rf "$MISSING" 2>/dev/null || true
done

rm -rf "$ARENA" 2>/dev/null || true

echo ""
echo "=============================================================================================="
printf 'TOTAL: %d passed, %d failed\n' "$pass" "$fail"
echo "=============================================================================================="
[[ "$fail" -eq 0 ]]
