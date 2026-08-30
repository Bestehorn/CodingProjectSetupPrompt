#!/usr/bin/env bash
# Exercise spec-tdd-gate.sh (PreToolUse on Bash). 0 = allow the command, 2 = block it.
#
# Two properties get more attention here than anywhere else, because this gate runs on EVERY Bash command and
# the two failure directions are asymmetric:
#   * it must NEVER block a non-commit command, whatever the state of the library or the workflow;
#   * it must ALWAYS block a commit it cannot justify, including when its own library is broken.
set -u

HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARENA="$(mktemp -d 2>/dev/null || echo "/tmp/tddgate.$$")"
SID="abcd1234-1111-2222-3333-444455556666"
RUN8="abcd1234"
ORCH="$ARENA/.claude/agent-state/issue-work-orchestrator"
CONDUCTOR="$ARENA/.claude/agent-state/spec-conductor"
SPEC="$ARENA/.claude/specs/demo"

pass=0; fail=0

reset_arena() {
    rm -rf "$ARENA/.claude" 2>/dev/null || true
    mkdir -p "$ORCH" "$CONDUCTOR" "$SPEC/evidence/green"
    printf '{}' > "$ORCH/registry.json"
}

workflow() { # $1 = target dir, $2 = Phase, $3 = CURRENT_SPEC, $4 = CURRENT_TASK
    mkdir -p "$1"
    cat > "$1/workflow_state.md" <<EOF
# Workflow state
SESSION_ID: $SID
Phase: $2
CURRENT_SPEC: $3
CURRENT_TASK: $4
EOF
}

payload() { printf '{"session_id":"%s","cwd":"%s","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"%s"}}' "$SID" "$ARENA" "$1"; }

run() { # $1 = command string -> prints exit code
    local rc
    ( cd "$ARENA" && payload "$1" | bash "$HOOKS/spec-tdd-gate.sh" >/dev/null 2>&1 )
    rc=$?
    printf '%s' "$rc"
}

check() { # $1 label, $2 expected, $3 actual
    if [[ "$2" == "$3" ]]; then printf '  PASS  %-66s (exit %s)\n' "$1" "$3"; pass=$(( pass + 1 ))
    else printf '  FAIL  %-66s expected %s, got %s\n' "$1" "$2" "$3"; fail=$(( fail + 1 )); fi
}

echo "=============================================================================================="
echo "the library-free section — must be unaffected by workflow state"
echo "=============================================================================================="

reset_arena
check "a non-commit command -> allow"                      0 "$(run 'pytest test/')"
check "'git status' -> allow"                              0 "$(run 'git status')"
check "'git commit --no-verify' -> BLOCK"                   2 "$(run 'git commit --no-verify -m x')"
check "'git commit -n' -> BLOCK"                            2 "$(run 'git commit -n -m x')"
check "plain commit, no workflow at all -> allow"          0 "$(run 'git commit -m x')"

echo ""
echo "=============================================================================================="
echo "evidence enforcement"
echo "=============================================================================================="

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo" "3"
check "IMPLEMENT, task 3, NO green capture -> BLOCK"        2 "$(run 'git commit -m x')"

reset_arena; workflow "$CONDUCTOR" DESIGN ".claude/specs/demo" "3"
check "phase DESIGN (outside IMPLEMENT/VERIFY) -> allow"    0 "$(run 'git commit -m x')"

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo" ""
check "no CURRENT_TASK recorded -> allow (transient)"       0 "$(run 'git commit -m x')"

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo" "3"
printf '5 passed in 1.2s\n' > "$SPEC/evidence/green/3.txt"
check "clean green capture -> allow"                        0 "$(run 'git commit -m x')"

# THE MEASURED FAIL-OPEN. The old predicate's escape clause was satisfied by "5 passed", so a capture
# reporting BOTH counts was allowed. Real pytest output almost always reports both.
reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo" "3"
printf '3 failed, 5 passed in 2.1s\n' > "$SPEC/evidence/green/3.txt"
check "'3 failed, 5 passed' -> BLOCK (was ALLOWED)"         2 "$(run 'git commit -m x')"

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo" "3"
printf '2 errors, 5 passed in 2.1s\n' > "$SPEC/evidence/green/3.txt"
check "'2 errors, 5 passed' -> BLOCK"                       2 "$(run 'git commit -m x')"

# ...while a zero count must NOT over-block, which is why the predicate needs no escape clause.
reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo" "3"
printf '0 failed, 5 passed in 2.1s\n' > "$SPEC/evidence/green/3.txt"
check "'0 failed, 5 passed' -> allow (no over-block)"       0 "$(run 'git commit -m x')"

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo" "3"
printf '4 passed, 1 skipped in 1.0s\n' > "$SPEC/evidence/green/3.txt"
check "capture containing a SKIP -> BLOCK (vacuous green)"  2 "$(run 'git commit -m x')"

echo ""
echo "=============================================================================================="
echo "identity — a commit must never be judged on ANOTHER run's task"
echo "=============================================================================================="

# A sibling run, touched LAST, whose task 9 has a green capture. This session's own run records task 3 with
# NO capture. An mtime-borrowing gate reads the sibling's state and ALLOWS the commit.
reset_arena
printf '{"%s":{"session_id":"%s","run_id":"%s","state_dir":"runs/%s/"}}' "$SID" "$SID" "$RUN8" "$RUN8" > "$ORCH/registry.json"
mkdir -p "$ORCH/runs/$RUN8"
printf 'SESSION_ID: %s\nStatus: IN_PROGRESS\n' "$SID" > "$ORCH/runs/$RUN8/resume_state.md"
workflow "$ORCH/runs/$RUN8" IMPLEMENT ".claude/specs/demo" "3"
mkdir -p "$ORCH/runs/99999999"
printf 'SESSION_ID: someone-else\nStatus: IN_PROGRESS\n' > "$ORCH/runs/99999999/resume_state.md"
workflow "$ORCH/runs/99999999" IMPLEMENT ".claude/specs/demo" "9"
printf '5 passed in 1.0s\n' > "$SPEC/evidence/green/9.txt"
touch "$ORCH/runs/99999999/workflow_state.md"      # newest, so an mtime rung would pick it
check "sibling's proven task does NOT excuse my unproven one" 2 "$(run 'git commit -m x')"

# And the converse: my OWN proven task is honoured even when a sibling is unproven and newer.
printf '5 passed in 1.0s\n' > "$SPEC/evidence/green/3.txt"
rm -f "$SPEC/evidence/green/9.txt"
touch "$ORCH/runs/99999999/workflow_state.md"
check "my own proven task is honoured despite a newer sibling" 0 "$(run 'git commit -m x')"

echo ""
echo "=============================================================================================="
echo "fail-closed on a broken library — but ONLY for commits"
echo "=============================================================================================="

for variant in partial missing; do
    BROKEN="$(mktemp -d 2>/dev/null || echo "/tmp/tddbroken.$$")"
    mkdir -p "$BROKEN/hooks"
    cp "$HOOKS/spec-tdd-gate.sh" "$BROKEN/hooks/"
    if [[ "$variant" == "partial" ]]; then
        printf '# truncated: no hook_task_selftest\nHOOK_ORCHESTRATOR_DIRNAME=x\n' > "$BROKEN/hooks/hook-state-lib.sh"
    fi
    ( cd "$BROKEN" && printf '{"session_id":"%s","cwd":".","tool_input":{"command":"git commit -m x"}}' "$SID" \
        | bash hooks/spec-tdd-gate.sh >/dev/null 2>&1 )
    check "$variant library: a COMMIT is refused"           2 "$?"
    # The critical asymmetry: an ordinary command must still run. A gate that refused every Bash call when its
    # library broke would be removed by the first person it inconvenienced.
    ( cd "$BROKEN" && printf '{"session_id":"%s","cwd":".","tool_input":{"command":"pytest test/"}}' "$SID" \
        | bash hooks/spec-tdd-gate.sh >/dev/null 2>&1 )
    check "$variant library: a NON-commit still runs"        0 "$?"
    # ...and the bypass ban must still fire, since it sits above the library section.
    ( cd "$BROKEN" && printf '{"session_id":"%s","cwd":".","tool_input":{"command":"git commit --no-verify -m x"}}' "$SID" \
        | bash hooks/spec-tdd-gate.sh >/dev/null 2>&1 )
    check "$variant library: the --no-verify ban still fires" 2 "$?"
    rm -rf "$BROKEN" 2>/dev/null || true
done

rm -rf "$ARENA" 2>/dev/null || true

echo ""
printf 'TOTAL: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
