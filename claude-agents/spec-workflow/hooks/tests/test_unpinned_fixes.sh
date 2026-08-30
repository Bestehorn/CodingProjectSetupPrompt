#!/usr/bin/env bash
# Pins for behaviours that were CORRECT in the code but guarded by NOTHING.
#
# WHY THIS FILE EXISTS
# --------------------
# An adversarial verification pass mutated the shipped hooks and re-ran all 193 assertions. Three mutations
# SURVIVED the entire suite set — meaning three fixes were real in the code and unprotected by any test:
#
#   1. The contract handshake's BLOCK direction. `test_stop_gates.sh` asserts "contract NOT acknowledged ->
#      BLOCK", but that case seeds a state the MAIN BRAKE also blocks, so the exit 2 it observes proves
#      nothing about the handshake. MEASURED: replacing `if ! hook_contract_acknowledged ...` with
#      `if false; then` left the suite reporting 24 passed, 0 failed.
#   2. Defect class 10 — existence of an evidence file read as PROOF. Making a zero-byte capture count as
#      proof again survived every suite.
#   3. Per-task failure scanning in the evidence gate. The gate scanned only the MOST RECENTLY TOUCHED
#      capture, so `3 failed, 5 passed` in an older task's capture was accepted. Proven by mtime: `touch`
#      the older file, content unchanged, and the verdict flipped from allow to block.
#
# An unpinned fix is a fix that regresses silently — which is precisely how the original incident happened, so
# these get assertions of their own. Where the exit code cannot distinguish two causes, these cases assert on
# the REFUSAL TEXT as well, because that is what actually identifies which gate fired.
set -u

HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARENA="$(mktemp -d 2>/dev/null || echo "/tmp/unpinned.$$")"
SID="abcd1234-1111-2222-3333-444455556666"
RUN8="abcd1234"
ORCH="$ARENA/.claude/agent-state/issue-work-orchestrator"
SPEC="$ARENA/.claude/specs/demo"

pass=0; fail=0
BAR="=============================================================================================="

reset_arena() {
    rm -rf "$ARENA/.claude" 2>/dev/null || true
    mkdir -p "$ORCH/runs/$RUN8" "$ARENA/.claude/hooks" "$SPEC/evidence/green"
    printf '{"%s":{"session_id":"%s","run_id":"%s","state_dir":"runs/%s/"}}' "$SID" "$SID" "$RUN8" "$RUN8" \
        > "$ORCH/registry.json"
    cp "$HOOKS/CONTRACT_VERSION" "$ARENA/.claude/hooks/CONTRACT_VERSION" 2>/dev/null || true
}

seed_resume() { # <Status> <Phase> <AWAITING_USER> <CURRENT_ISSUE>
    {
        printf 'SESSION_ID: %s\n' "$SID"
        printf 'RUN_ID: %s\n'     "$RUN8"
        printf 'MODE: unset\n'
        printf 'Status: %s\n'     "$1"
        printf 'Phase: %s\n'      "$2"
        printf 'AWAITING_USER: %s\n' "$3"
        printf 'CURRENT_ISSUE: %s\n' "$4"
        printf 'WORKABLE_ISSUES_REMAIN: no\n'
    } > "$ORCH/runs/$RUN8/resume_state.md"
}

seed_workflow() { # <Phase> <CURRENT_SPEC> [Status]
    {
        printf 'SESSION_ID: %s\n' "$SID"
        printf 'CURRENT_SPEC: %s\n' "$2"
        printf 'Phase: %s\n' "$1"
        printf 'Status: %s\n' "${3:-IN_PROGRESS}"
        printf 'CURRENT_TASK: 1\n'
    } > "$ORCH/runs/$RUN8/workflow_state.md"
}

ack() {
    local v; v="$(head -1 "$HOOKS/CONTRACT_VERSION" | tr -d '\r\n[:space:]')"
    printf 'ack\n' > "$ORCH/runs/$RUN8/contract-ack-$v"
}

PAYLOAD="$(printf '{"session_id":"%s","cwd":"%s","hook_event_name":"Stop"}' "$SID" "$ARENA")"

rc_of() { # <hook> -> exit code
    local rc
    ( cd "$ARENA" && printf '%s' "$PAYLOAD" | bash "$HOOKS/$1" >/dev/null 2>&1 )
    rc=$?
    printf '%s' "$rc"
}

stderr_of() { # <hook> -> the refusal text
    ( cd "$ARENA" && printf '%s' "$PAYLOAD" | bash "$HOOKS/$1" 2>&1 >/dev/null )
}

check() {
    if [[ "$2" == "$3" ]]; then printf '  PASS  %-66s (%s)\n' "$1" "$3"; pass=$(( pass + 1 ))
    else printf '  FAIL  %-66s expected %s, got %s\n' "$1" "$2" "$3"; fail=$(( fail + 1 )); fi
}

has() { # <label> <needle> <haystack>
    if grep -qiF -- "$2" <<<"$3"; then printf '  PASS  %s\n' "$1"; pass=$(( pass + 1 ))
    else printf '  FAIL  %s\n        text did not contain: %s\n' "$1" "$2"; fail=$(( fail + 1 )); fi
}

hasnt() { # <label> <needle> <haystack>
    if grep -qiF -- "$2" <<<"$3"; then printf '  FAIL  %s\n        text unexpectedly contained: %s\n' "$1" "$2"; fail=$(( fail + 1 ))
    else printf '  PASS  %s\n' "$1"; pass=$(( pass + 1 )); fi
}

echo "$BAR"
echo "1. The contract handshake's BLOCK direction, identified by its TEXT not its exit code"
echo "$BAR"

# The state here is one the MAIN BRAKE would also block, which is exactly why the exit code alone cannot pin
# the handshake — so assert on which refusal actually fired.
reset_arena; seed_resume IN_PROGRESS FIX none 999
out="$(stderr_of issue-loop-gate.sh)"
check "unacked contract -> BLOCK"                                2 "$(rc_of issue-loop-gate.sh)"
has   "  and the HANDSHAKE is what refused (names the contract)" "continuous-work contract" "$out"
has   "  and it names the deployed version"                      "$(head -1 "$HOOKS/CONTRACT_VERSION" | tr -d '\r\n[:space:]')" "$out"
has   "  and it names the ack file to create"                    "contract-ack-" "$out"
hasnt "  and it is NOT the main brake's message"                 "records itself as UNFINISHED" "$out"

# Once acked, the SAME state must still block — but now via the main brake, with the other message. This is the
# control that proves the two refusals are distinguishable at all.
ack
out="$(stderr_of issue-loop-gate.sh)"
check "acked, same state -> still BLOCK"                         2 "$(rc_of issue-loop-gate.sh)"
has   "  and now it IS the main brake"                           "records itself as UNFINISHED" "$out"
hasnt "  and the handshake no longer fires"                      "continuous-work contract" "$out"

echo ""
echo "$BAR"
echo "2. Defect class 10 — a capture must SHOW a pass, not merely EXIST"
echo "$BAR"

prep_spec() { # <task list> ; caller writes captures afterwards
    reset_arena; seed_resume IN_PROGRESS FIX none 999; ack
    seed_workflow IMPLEMENT ".claude/specs/demo"
    printf '%s' "$1" > "$SPEC/tasks.md"
}

prep_spec '- [x] 1 do the thing
'
: > "$SPEC/evidence/green/1.txt"                      # ZERO BYTES
out="$(stderr_of spec-stop-gate.sh)"
check "zero-byte capture -> BLOCK"                               2 "$(rc_of spec-stop-gate.sh)"
has   "  and it says the capture shows no passing result"        "shows NO passing result" "$out"

printf 'ran the tests, all good\n' > "$SPEC/evidence/green/1.txt"   # prose only, no counter
check "prose-only capture -> BLOCK"                              2 "$(rc_of spec-stop-gate.sh)"

printf '5 passed in 1.0s\n' > "$SPEC/evidence/green/1.txt"
check "a real passing capture -> allow"                          0 "$(rc_of spec-stop-gate.sh)"

echo ""
echo "$BAR"
echo "3. Per-task failure scanning — the verdict must not depend on file MTIME"
echo "$BAR"

# THE MEASURED FAIL-OPEN. Two checked tasks; task 1's capture reports a real failure; task 2's is written
# LATER so it is the most-recently-touched. Scanning only the newest capture accepted the `3 failed`.
prep_spec '- [x] 1 first task
- [x] 2 second task
'
printf '3 failed, 5 passed in 2.0s\n' > "$SPEC/evidence/green/1.txt"
sleep 1
printf '10 passed in 1.0s\n'          > "$SPEC/evidence/green/2.txt"
out="$(stderr_of spec-stop-gate.sh)"
check "older capture reporting failures -> BLOCK"                2 "$(rc_of spec-stop-gate.sh)"
has   "  and it names the offending TASK's own capture"          "task 1" "$out"

# The control that proves mtime is no longer the discriminator: make task 1 the NEWEST without changing a byte.
touch "$SPEC/evidence/green/1.txt"
check "same bytes, task 1 now newest -> still BLOCK"             2 "$(rc_of spec-stop-gate.sh)"

# ...and the mirror: a skip counter in an older capture must also be caught.
printf '9 passed, 1 skipped in 2.0s\n' > "$SPEC/evidence/green/1.txt"
sleep 1
printf '10 passed in 1.0s\n'           > "$SPEC/evidence/green/2.txt"
check "older capture reporting a SKIP -> BLOCK"                  2 "$(rc_of spec-stop-gate.sh)"

# Both clean -> allow. Without this the three cases above could all pass on a gate that blocks unconditionally.
printf '5 passed in 1.0s\n'  > "$SPEC/evidence/green/1.txt"
printf '10 passed in 1.0s\n' > "$SPEC/evidence/green/2.txt"
check "both captures clean -> allow (non-vacuity control)"       0 "$(rc_of spec-stop-gate.sh)"

# A COMMENT in an older capture must not block, exactly as for the newest one.
printf '# earlier: 3 failed, now fixed\n5 passed in 1.0s\n' > "$SPEC/evidence/green/1.txt"
check "a COMMENT mentioning failures -> allow"                   0 "$(rc_of spec-stop-gate.sh)"

echo ""
echo "$BAR"
echo "4. The two Stop gates must agree on what a terminal value is"
echo "$BAR"

# The evidence gate used a raw `grep -qiE "^($HOOK_TERMINAL_PHASES)"`, anchored only at the START, so it
# released on a PREFIX while the loop gate (using the library) refused the same string. A narrative Status is
# the value this project adjudicated: whole-value only.
prep_spec '- [x] 1 do the thing
'
# no capture at all, so the gate has a reason to block unless a Status releases it
seed_workflow IMPLEMENT ".claude/specs/demo" "COMPLETED (was IN_PROGRESS)"
check "spec gate: narrative Status does NOT release"             2 "$(rc_of spec-stop-gate.sh)"
seed_workflow IMPLEMENT ".claude/specs/demo" "COMPLETED"
check "spec gate: bare COMPLETED DOES release"                   0 "$(rc_of spec-stop-gate.sh)"

# And the loop gate must give the same answers for the same two strings.
reset_arena; seed_resume "COMPLETED (was IN_PROGRESS)" FIX none 999; ack
check "loop gate: narrative Status does NOT release"             2 "$(rc_of issue-loop-gate.sh)"
reset_arena; seed_resume "COMPLETED" FIX none 999; ack
check "loop gate: bare COMPLETED DOES release"                   0 "$(rc_of issue-loop-gate.sh)"

echo ""
echo "$BAR"
echo "5. ...and they must agree on what counts as an ESCALATION"
echo "$BAR"

# The evidence gate used the WEAKER `hook_field_is_placeholder` test while the loop gate used
# `hook_is_substantive_escalation`. A one-word token therefore released one gate and not the other — harmless
# only while BOTH are registered, and a fail-open in a spec-only project where the evidence gate is the only
# Stop hook. Both now apply the substance test, so these four cases must give matching verdicts.
for token in "waiting" "no" "0" "<reason>"; do
    prep_spec '- [x] 1 do the thing
'
    # no capture -> the gate has a reason to block unless the escalation releases it
    seed_resume IN_PROGRESS FIX "$token" 999; ack
    seed_workflow IMPLEMENT ".claude/specs/demo"
    check "spec gate: token AWAITING_USER '$token' does NOT release" 2 "$(rc_of spec-stop-gate.sh)"
    check "loop gate: same token does NOT release"                   2 "$(rc_of issue-loop-gate.sh)"
done

# A real reason releases BOTH.
prep_spec '- [x] 1 do the thing
'
seed_resume IN_PROGRESS FIX "waiting on the production credential for the smoke test" 999; ack
seed_workflow IMPLEMENT ".claude/specs/demo"
check "spec gate: a substantive reason DOES release"             0 "$(rc_of spec-stop-gate.sh)"
check "loop gate: a substantive reason DOES release"             0 "$(rc_of issue-loop-gate.sh)"

rm -rf "$ARENA" 2>/dev/null || true

echo ""
printf 'TOTAL: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
