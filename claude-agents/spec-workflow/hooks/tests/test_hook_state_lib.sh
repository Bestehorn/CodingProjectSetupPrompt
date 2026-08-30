#!/usr/bin/env bash
# Unit-test hook-state-lib.sh by calling its functions DIRECTLY.
#
# WHY THIS FILE EXISTS, SEPARATELY FROM test_stop_gates.sh
# -------------------------------------------------------
# test_stop_gates.sh drives the gates end to end, which is the right test for gate POLICY but the wrong test
# for the library: it only ever reaches the library through a caller that happens to define a global named
# `base`. A measured bug hid in exactly that gap. `hook_resolve_run_dir` contained
#
#     local base="$1" ... orch="$base/$HOOK_ORCHESTRATOR_DIRNAME"
#
# and bash expands every assignment word in a single `local` BEFORE creating any of the locals, so `$base`
# resolved to the CALLER's global. Both gates hold a global with that name, so all 24 end-to-end assertions
# passed while the function was, in isolation, broken — and inside a `$(…)` its abort produces an EMPTY
# verdict, which the gates read as "nothing to guard": a silent fail-open.
#
# So this file deliberately defines NO global named `base`, `session`, `orch`, `declared` or `run_dir`. Any
# reintroduced same-statement self-reference aborts under `set -u` and reds a case here rather than waiting
# for a caller to be renamed.
set -u

HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$HOOKS/hook-state-lib.sh"

ARENA="$(mktemp -d 2>/dev/null || echo "/tmp/libtest.$$")"
STATE_ROOT="$ARENA/.claude/agent-state"
ORCH="$STATE_ROOT/issue-work-orchestrator"
SID="deadbeef-1111-2222-3333-444455556666"
mkdir -p "$ORCH"

pass=0; fail=0
t() { # <label> <expected> <actual>
    if [[ "$2" == "$3" ]]; then printf '  PASS  %-58s %s\n' "$1" "$3"; pass=$(( pass + 1 ))
    else printf '  FAIL  %-58s expected [%s] got [%s]\n' "$1" "$2" "$3"; fail=$(( fail + 1 )); fi
}

echo "=============================================================================="
echo "identity verdicts — called with NO global named 'base' in scope"
echo "=============================================================================="

printf '{}' > "$ORCH/registry.json"
t "no registry entry -> UNREGISTERED" "UNREGISTERED" "$(hook_identity_verdict "$STATE_ROOT" "$SID")"

# The fail-open this separation of questions closes: an ENTRY exists, but `state_dir` is unusable. Every one
# of these must be BROKEN (fail closed), never UNREGISTERED (which makes every gate a no-op for a real run).
printf '{"%s":{"session_id":"%s","run_id":"deadbeef"}}' "$SID" "$SID" > "$ORCH/registry.json"
t "entry with NO state_dir key -> BROKEN" "BROKEN" "$(hook_identity_verdict "$STATE_ROOT" "$SID")"
t "  BROKEN names the conventional path" "$ORCH/runs/deadbeef" "$(hook_identity_run_dir "$STATE_ROOT" "$SID")"

printf '{"%s":{"state_dir":""}}' "$SID" > "$ORCH/registry.json"
t "entry with EMPTY state_dir -> BROKEN" "BROKEN" "$(hook_identity_verdict "$STATE_ROOT" "$SID")"

printf '{"%s":{"state_dir":"/abs/elsewhere"}}' "$SID" > "$ORCH/registry.json"
t "entry with ABSOLUTE state_dir -> BROKEN" "BROKEN" "$(hook_identity_verdict "$STATE_ROOT" "$SID")"

# Path traversal must be rejected as a LOCATION and still reported as a registered-but-broken run.
mkdir -p "$ORCH/runs"
printf '{"%s":{"state_dir":"runs/../../../etc/"}}' "$SID" > "$ORCH/registry.json"
t "TRAVERSING state_dir -> BROKEN, never OWNED" "BROKEN" "$(hook_identity_verdict "$STATE_ROOT" "$SID")"

# A malformed registry must not be read as "no entry": that would be a fail-open on a corrupted file.
printf '{"%s":{"state_dir": ' "$SID" > "$ORCH/registry.json"
t "MALFORMED registry, key present -> BROKEN" "BROKEN" "$(hook_identity_verdict "$STATE_ROOT" "$SID")"

printf '{"%s":{"state_dir":"runs/deadbeef/"}}' "$SID" > "$ORCH/registry.json"
mkdir -p "$ORCH/runs/deadbeef"
printf 'SESSION_ID: %s\nStatus: IN_PROGRESS\n' "$SID" > "$ORCH/runs/deadbeef/resume_state.md"
t "declared + state present -> OWNED" "OWNED" "$(hook_identity_verdict "$STATE_ROOT" "$SID")"
t "  OWNED names the declared dir" "$ORCH/runs/deadbeef" "$(hook_identity_run_dir "$STATE_ROOT" "$SID")"

# Rung 3: state under an agent-invented directory name, recoverable ONLY via the recorded SESSION_ID.
rm -rf "$ORCH/runs"
mkdir -p "$ORCH/runs/run-issue574-20260828T194800Z"
printf 'SESSION_ID: %s\nStatus: IN_PROGRESS\n' "$SID" > "$ORCH/runs/run-issue574-20260828T194800Z/resume_state.md"
t "invented dir recovered by SESSION_ID -> OWNED" "OWNED" "$(hook_identity_verdict "$STATE_ROOT" "$SID")"
t "  and names the invented dir" "$ORCH/runs/run-issue574-20260828T194800Z" "$(hook_identity_run_dir "$STATE_ROOT" "$SID")"

# A SIBLING run's state, freshly touched, must never be adopted. This is the mtime-borrow defect.
rm -rf "$ORCH/runs"; mkdir -p "$ORCH/runs/99999999"
printf 'SESSION_ID: someone-else\nStatus: IN_PROGRESS\nCURRENT_ISSUE: 565\n' > "$ORCH/runs/99999999/resume_state.md"
touch "$ORCH/runs/99999999/resume_state.md"
t "newest SIBLING run is NOT adopted -> BROKEN" "BROKEN" "$(hook_identity_verdict "$STATE_ROOT" "$SID")"
t "  and the sibling dir is never named" "$ORCH/runs/deadbeef" "$(hook_identity_run_dir "$STATE_ROOT" "$SID")"

echo ""
echo "=============================================================================="
echo "hook_counter_read — clamping and the octal trap"
echo "=============================================================================="

COUNTER="$ARENA/probe.count"
printf '7'   > "$COUNTER"; t "plain integer"                  "7"    "$(hook_counter_read "$COUNTER")"
printf '08'  > "$COUNTER"; t "leading zero is NOT read octal" "8"    "$(hook_counter_read "$COUNTER")"
printf '009' > "$COUNTER"; t "double leading zero"            "9"    "$(hook_counter_read "$COUNTER")"
printf '0'   > "$COUNTER"; t "zero"                           "0"    "$(hook_counter_read "$COUNTER")"
printf 'abc' > "$COUNTER"; t "non-numeric -> 0"               "0"    "$(hook_counter_read "$COUNTER")"
printf '%s' "99999999999999999999999999" > "$COUNTER"
t "absurd width -> clamped, not an overflow" "9999" "$(hook_counter_read "$COUNTER")"
# The clamped value must be usable in the caller's arithmetic without aborting the gate.
if (( "$(hook_counter_read "$COUNTER")" >= HOOK_BLOCK_CAP )); then
    t "clamped value compares cleanly" "ok" "ok"
else
    t "clamped value compares cleanly" "ok" "aborted-or-false"
fi
rm -f "$COUNTER"; t "absent counter -> 0" "0" "$(hook_counter_read "$COUNTER")"

echo ""
echo "=============================================================================="
echo "hook_state_field — the parsing contract the state templates rely on"
echo "=============================================================================="

FIELDS="$ARENA/fields.md"
printf 'Status: FIRST\nStatus: LAST\n' > "$FIELDS"
t "LAST occurrence wins (append-to-correct)" "LAST" "$(hook_state_field "$FIELDS" Status)"
printf 'AWAITING_USER: need a credential: for prod\n' > "$FIELDS"
t "value may contain a colon" "need a credential: for prod" "$(hook_state_field "$FIELDS" AWAITING_USER)"
printf 'Status_Detail: nope\n' > "$FIELDS"
t "a longer field name is not matched" "" "$(hook_state_field "$FIELDS" Status)"
printf '**Status:** BOLD\n' > "$FIELDS"
t "bold spelling is INVISIBLE (documented)" "" "$(hook_state_field "$FIELDS" Status)"
printf 'Status: CRLF\r\n' > "$FIELDS"
t "CRLF is stripped" "CRLF" "$(hook_state_field "$FIELDS" Status)"
printf -- '- Status: dashed\n' > "$FIELDS"
t "list-item spelling is matched" "dashed" "$(hook_state_field "$FIELDS" Status)"
printf 'Phase: FIX\n' > "$FIELDS"
t "absent field -> empty, not an error" "" "$(hook_state_field "$FIELDS" NO_SUCH_FIELD)"
t "missing file -> empty, not an error" "" "$(hook_state_field "$ARENA/nope.md" Status)"

echo ""
echo "=============================================================================="
echo "the self-test symbol is the LAST definition (partial-source detection)"
echo "=============================================================================="

# If a future edit moves hook_task_selftest away from the end, a truncated library could define it while
# omitting later functions — and every gate's fail-closed check would pass on a broken library.
t "hook_task_selftest is the last definition" \
  "hook_task_selftest" \
  "$(grep -oE '^[a-zA-Z_][a-zA-Z_0-9]*\(\)' "$HOOKS/hook-state-lib.sh" | tail -1 | tr -d '()')"

echo ""
echo "=============================================================================="
echo "hook_resolve_block_cap - a bad override must not disable OR wedge the gate"
echo "=============================================================================="

# The cap is interpolated into `(( blocks >= HOOK_BLOCK_CAP ))` inside a gate whose EXIT trap turns any
# unexpected status into a REFUSAL. Measured on the raw `${VAR:-8}` form: `abc` aborted with
# `abc: unbound variable` and `1abc` with `value too great for base`, and the trap converted both into exit 2
# BEFORE the counter could advance - a permanent refusal with no cap to reach, from a single typo. `0` and a
# blank value failed the other way and silently switched the gate off. It takes the raw value as an ARGUMENT so
# this can be tested without setting an environment variable, which this project forbids.
t "default when unset"                     "8"  "$(hook_resolve_block_cap "")"
t "a valid override is honoured"           "3"  "$(hook_resolve_block_cap "3")"
t "non-numeric falls back to the default"  "8"  "$(hook_resolve_block_cap "abc")"
t "partly-numeric falls back"              "8"  "$(hook_resolve_block_cap "1abc")"
t "whitespace falls back"                  "8"  "$(hook_resolve_block_cap " ")"
t "zero clamps up (not an off-switch)"     "1"  "$(hook_resolve_block_cap "0")"
t "absurd value clamps down"               "64" "$(hook_resolve_block_cap "100000")"
if (( "$(hook_resolve_block_cap "abc")" >= 1 )); then t "result is always valid arithmetic" "ok" "ok"
else t "result is always valid arithmetic" "ok" "aborted"; fi
t "the live constant is in range" "ok" "$( (( HOOK_BLOCK_CAP >= 1 && HOOK_BLOCK_CAP <= 64 )) && echo ok )"

echo ""
echo "=============================================================================="
echo "counter contract - a block must be COUNTABLE and a cap must be DURABLE"
echo "=============================================================================="

CDIR="$ARENA/counters"; mkdir -p "$CDIR"
OK="$CDIR/ok.count"
t "bump reports success when it lands" "0" "$(hook_counter_bump "$OK"; echo $?)"
t "  and the value advanced"           "1" "$(hook_counter_read "$OK")"
hook_counter_bump "$OK" >/dev/null
t "second bump advances again"         "2" "$(hook_counter_read "$OK")"

# An UNWRITABLE counter must be REPORTED, not swallowed. Swallowing it meant the cap was never reached, so the
# gate refused every turn-end with no escape at all (measured: 3 of 3 refusals, counter never advancing).
BAD="$CDIR/blocked.count"; mkdir -p "$BAD"    # a DIRECTORY occupying the counter's own path
if hook_counter_bump "$BAD" 2>/dev/null; then
    t "bump on an unwritable path reports failure" "nonzero" "zero (swallowed)"
else
    t "bump on an unwritable path reports failure" "nonzero" "nonzero"
fi

# The give-up marker must SURVIVE, or the cap is a duty cycle (measured: 8 refusals, 1 release, then 8 more).
t "not capped initially"                "no"  "$(hook_counter_is_capped "$OK" && echo yes || echo no)"
hook_counter_mark_capped "$OK"
t "capped after marking"                "yes" "$(hook_counter_is_capped "$OK" && echo yes || echo no)"
t "  and the marker persists"           "yes" "$(hook_counter_is_capped "$OK" && echo yes || echo no)"
hook_counter_reset "$OK"
t "a genuine reset clears the marker"   "no"  "$(hook_counter_is_capped "$OK" && echo yes || echo no)"
t "  and clears the count"              "0"   "$(hook_counter_read "$OK")"

echo ""
echo "=============================================================================="
echo "hook_field_is_placeholder - every spelling of nothing-recorded"
echo "=============================================================================="

for v in "" "none" "NONE" "-" "n/a" "unset" "empty" "null" "tbd"; do
    t "placeholder: [$v]" "yes" "$(hook_field_is_placeholder "$v" && echo yes || echo no)"
done
for v in "574" ".claude/specs/x" "design fork on retry policy" "0"; do
    t "real value:   [$v]" "no" "$(hook_field_is_placeholder "$v" && echo yes || echo no)"
done

echo ""
echo "=============================================================================="
echo "trailing whitespace is stripped - it broke BOTH directions"
echo "=============================================================================="

WS="$ARENA/ws.md"
# `AWAITING_USER: none ` compared unequal to `none`, so it read as a recorded escalation and DISABLED the
# primary brake. `CURRENT_SPEC: x ` produced the unopenable path `x /tasks.md` and blocked every turn-end.
printf 'AWAITING_USER: none   
' > "$WS"
t "trailing spaces stripped"        "none" "$(hook_state_field "$WS" AWAITING_USER)"
t "  so it reads as a placeholder"  "yes"  "$(hook_field_is_placeholder "$(hook_state_field "$WS" AWAITING_USER)" && echo yes || echo no)"
printf 'CURRENT_SPEC: .claude/specs/x 	
' > "$WS"
t "trailing tab stripped"           ".claude/specs/x" "$(hook_state_field "$WS" CURRENT_SPEC)"

rm -rf "$ARENA" 2>/dev/null || true

echo ""
printf 'TOTAL: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
