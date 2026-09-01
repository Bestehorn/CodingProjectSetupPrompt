#!/usr/bin/env bash
# Exercise spec-tdd-gate.sh (PreToolUse on Bash). 0 = allow the command, 2 = block it.
#
# Two properties get more attention here than anywhere else, because this gate runs on EVERY Bash command and
# the two failure directions are asymmetric:
#   * it must NEVER block a non-push command (commits included — they carry no evidence requirement),
#     whatever the state of the library or the workflow;
#   * it must ALWAYS block a push it cannot justify, including when its own library is broken.
set -u

HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARENA="$(mktemp -d 2>/dev/null || echo "/tmp/tddgate.$$")"
SID="abcd1234-1111-2222-3333-444455556666"
RUN8="abcd1234"
ORCH="$ARENA/.claude/agent-state/issue-work-orchestrator"
CONDUCTOR="$ARENA/.claude/agent-state/spec-conductor"
SPEC="$ARENA/.claude/specs/demo"
SPEC_OTHER="$ARENA/.claude/specs/other"

pass=0; fail=0

reset_arena() {
    rm -rf "$ARENA/.claude" 2>/dev/null || true
    mkdir -p "$ORCH" "$CONDUCTOR" "$SPEC/evidence/green" "$SPEC/evidence/regress" "$SPEC_OTHER/evidence/green"
    printf '{}' > "$ORCH/registry.json"
}

workflow() { # $1 = target dir, $2 = Phase, $3 = CURRENT_SPEC
    mkdir -p "$1"
    cat > "$1/workflow_state.md" <<EOF
# Workflow state
SESSION_ID: $SID
Phase: $2
CURRENT_SPEC: $3
EOF
}

tasksfile() { # $1 = spec dir, $2.. = checked task lines to write
    local dir="$1"; shift
    { printf '# Tasks\n'; for line in "$@"; do printf '%s\n' "$line"; done; } > "$dir/tasks.md"
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
echo "the library-free section — classification and bans, unaffected by workflow state"
echo "=============================================================================================="

reset_arena
check "a non-git command -> allow"                          0 "$(run 'pytest test/')"
check "'git status' -> allow"                               0 "$(run 'git status')"
check "'git commit --no-verify' -> BLOCK"                    2 "$(run 'git commit --no-verify -m x')"
check "'git commit -n' -> BLOCK"                             2 "$(run 'git commit -n -m x')"
check "'git push --no-verify' -> BLOCK"                      2 "$(run 'git push --no-verify')"
check "'git push -n' (dry-run, not a bypass) -> allow"      0 "$(run 'git push -n')"
check "'git stash push' is not a remote push -> allow"      0 "$(run 'git stash push')"
check "plain commit, no workflow at all -> allow"           0 "$(run 'git commit -m x')"
check "plain push, no workflow at all -> allow"             0 "$(run 'git push')"

# Commits NEVER owe evidence, even mid-implementation with nothing proven: commit early, commit often.
reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
check "IMPLEMENT, unproven task: a COMMIT is still free"    0 "$(run 'git commit -m x')"
# A commit whose MESSAGE mentions pushing must be classified by the stripped command, not the quote.
check "commit -m \\\"prepare for push\\\" -> allow (not a push)" 0 "$(run 'git commit -m \"prepare for push\"')"

echo ""
echo "=============================================================================================="
echo "evidence enforcement — on the PUSH"
echo "=============================================================================================="

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
check "IMPLEMENT, checked task, NO capture -> BLOCK push"   2 "$(run 'git push')"
# Global options must not defeat classification: every orchestrator push is `git -C <worktree> push`.
check "'git -C . push' is still a push -> BLOCK"            2 "$(run 'git -C . push')"

reset_arena; workflow "$CONDUCTOR" DESIGN ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
check "phase DESIGN (outside IMPLEMENT/VERIFY) -> allow"    0 "$(run 'git push')"

# The phase match is a WORD, uppercased — `implement` gates, `NOT_IMPLEMENTED` does not.
reset_arena; workflow "$CONDUCTOR" implement ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
check "lowercase 'Phase: implement' still gates -> BLOCK"   2 "$(run 'git push')"

reset_arena; workflow "$CONDUCTOR" NOT_IMPLEMENTED ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
check "'NOT_IMPLEMENTED' is not an implement phase -> allow" 0 "$(run 'git push')"

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ""
check "no CURRENT_SPEC recorded -> allow (transient)"       0 "$(run 'git push')"

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
printf '5 passed in 1.2s\n' > "$SPEC/evidence/green/3.txt"
check "checked task with clean green capture -> allow"      0 "$(run 'git push')"

# A checked HEADING whose children are checked must not demand its own capture.
reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] **1. Heading**' '- [x] 1.1 Leaf'
printf '5 passed in 1.2s\n' > "$SPEC/evidence/green/1.1.txt"
check "checked heading needs no capture of its own -> allow" 0 "$(run 'git push')"

# A pure TEST task's red capture IS its evidence.
reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 2. Write the failing test'
mkdir -p "$SPEC/evidence/red"
printf '1 failed in 0.3s\n' > "$SPEC/evidence/red/2.txt"
check "TEST task with red capture -> allow"                 0 "$(run 'git push')"

# THE MEASURED FAIL-OPEN. The old predicate's escape clause was satisfied by "5 passed", so a capture
# reporting BOTH counts was allowed. Real pytest output almost always reports both.
reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
printf '3 failed, 5 passed in 2.1s\n' > "$SPEC/evidence/green/3.txt"
check "'3 failed, 5 passed' -> BLOCK (was ALLOWED)"         2 "$(run 'git push')"

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
printf '2 errors, 5 passed in 2.1s\n' > "$SPEC/evidence/green/3.txt"
check "'2 errors, 5 passed' -> BLOCK"                       2 "$(run 'git push')"

# ...while a zero count must NOT over-block, which is why the predicate needs no escape clause.
reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
printf '0 failed, 5 passed in 2.1s\n' > "$SPEC/evidence/green/3.txt"
check "'0 failed, 5 passed' -> allow (no over-block)"       0 "$(run 'git push')"

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
printf '4 passed, 1 skipped in 1.0s\n' > "$SPEC/evidence/green/3.txt"
check "capture containing a SKIP -> BLOCK (vacuous green)"  2 "$(run 'git push')"

# The two measured OVER-block escapes: comment lines are stripped, and predicates anchor on a
# SUMMARY COUNTER — a test merely NAMED like a skip must not read as one.
reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
printf '# earlier this run: 3 failed, now fixed\n5 passed in 1.2s\n' > "$SPEC/evidence/green/3.txt"
check "comment mentioning failures is not a failure -> allow" 0 "$(run 'git push')"

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
printf 'test_reports_skipped_reason PASSED\n5 passed in 1.2s\n' > "$SPEC/evidence/green/3.txt"
check "a test NAMED ...skipped... is not a skip -> allow"   0 "$(run 'git push')"

echo ""
echo "=============================================================================================="
echo "CI-OUTAGE MODE — a push with no CI run behind it owes a full-suite capture"
echo "=============================================================================================="

reset_arena; workflow "$CONDUCTOR" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
printf '5 passed in 1.2s\n' > "$SPEC/evidence/green/3.txt"
( cd "$ARENA" && git init -q . 2>/dev/null )
touch "$ARENA/.git/ci-outage-mode"
check "outage declared, NO regress capture -> BLOCK"        2 "$(run 'git push')"
printf '3 failed, 90 passed in 60s\n' > "$SPEC/evidence/regress/full.txt"
check "outage declared, RED full-suite capture -> BLOCK"    2 "$(run 'git push')"
printf '93 passed in 61s\n' > "$SPEC/evidence/regress/full.txt"
check "outage declared, GREEN full-suite capture -> allow"  0 "$(run 'git push')"
rm -f "$ARENA/.git/ci-outage-mode"
rm -f "$SPEC/evidence/regress/full.txt"
check "outage cleared -> no regress capture owed"           0 "$(run 'git push')"
rm -rf "$ARENA/.git" 2>/dev/null || true

echo ""
echo "=============================================================================================="
echo "identity — a push must never be judged on ANOTHER run's spec"
echo "=============================================================================================="

# A sibling run, touched LAST, whose spec is fully proven. This session's own run points at a spec with a
# checked task and NO capture. An mtime-borrowing gate reads the sibling's state and ALLOWS the push.
reset_arena
printf '{"%s":{"session_id":"%s","run_id":"%s","state_dir":"runs/%s/"}}' "$SID" "$SID" "$RUN8" "$RUN8" > "$ORCH/registry.json"
mkdir -p "$ORCH/runs/$RUN8"
printf 'SESSION_ID: %s\nStatus: IN_PROGRESS\n' "$SID" > "$ORCH/runs/$RUN8/resume_state.md"
workflow "$ORCH/runs/$RUN8" IMPLEMENT ".claude/specs/demo"
tasksfile "$SPEC" '- [x] 3. Do the thing'
mkdir -p "$ORCH/runs/99999999"
printf 'SESSION_ID: someone-else\nStatus: IN_PROGRESS\n' > "$ORCH/runs/99999999/resume_state.md"
workflow "$ORCH/runs/99999999" IMPLEMENT ".claude/specs/other"
tasksfile "$SPEC_OTHER" '- [x] 9. Their thing'
printf '5 passed in 1.0s\n' > "$SPEC_OTHER/evidence/green/9.txt"
touch "$ORCH/runs/99999999/workflow_state.md"      # newest, so an mtime rung would pick it
check "sibling's proven spec does NOT excuse my unproven one" 2 "$(run 'git push')"

# And the converse: my OWN proven spec is honoured even when a sibling is unproven and newer.
printf '5 passed in 1.0s\n' > "$SPEC/evidence/green/3.txt"
rm -f "$SPEC_OTHER/evidence/green/9.txt"
touch "$ORCH/runs/99999999/workflow_state.md"
check "my own proven spec is honoured despite a newer sibling" 0 "$(run 'git push')"

echo ""
echo "=============================================================================================="
echo "fail-closed on a broken library — but ONLY for pushes"
echo "=============================================================================================="

for variant in partial missing; do
    BROKEN="$(mktemp -d 2>/dev/null || echo "/tmp/tddbroken.$$")"
    mkdir -p "$BROKEN/hooks"
    cp "$HOOKS/spec-tdd-gate.sh" "$BROKEN/hooks/"
    if [[ "$variant" == "partial" ]]; then
        printf '# truncated: no hook_task_selftest\nHOOK_ORCHESTRATOR_DIRNAME=x\n' > "$BROKEN/hooks/hook-state-lib.sh"
    fi
    ( cd "$BROKEN" && printf '{"session_id":"%s","cwd":".","tool_input":{"command":"git push"}}' "$SID" \
        | bash hooks/spec-tdd-gate.sh >/dev/null 2>&1 )
    check "$variant library: a PUSH is refused"             2 "$?"
    # The critical asymmetry: an ordinary command must still run. A gate that refused every Bash call when its
    # library broke would be removed by the first person it inconvenienced.
    ( cd "$BROKEN" && printf '{"session_id":"%s","cwd":".","tool_input":{"command":"pytest test/"}}' "$SID" \
        | bash hooks/spec-tdd-gate.sh >/dev/null 2>&1 )
    check "$variant library: a NON-push still runs"          0 "$?"
    # A COMMIT never reaches the library, so a broken library must not tax it either.
    ( cd "$BROKEN" && printf '{"session_id":"%s","cwd":".","tool_input":{"command":"git commit -m x"}}' "$SID" \
        | bash hooks/spec-tdd-gate.sh >/dev/null 2>&1 )
    check "$variant library: a COMMIT is still free"         0 "$?"
    # ...and the bypass bans must still fire, since they sit above the library section.
    ( cd "$BROKEN" && printf '{"session_id":"%s","cwd":".","tool_input":{"command":"git commit --no-verify -m x"}}' "$SID" \
        | bash hooks/spec-tdd-gate.sh >/dev/null 2>&1 )
    check "$variant library: the commit --no-verify ban still fires" 2 "$?"
    ( cd "$BROKEN" && printf '{"session_id":"%s","cwd":".","tool_input":{"command":"git push --no-verify"}}' "$SID" \
        | bash hooks/spec-tdd-gate.sh >/dev/null 2>&1 )
    check "$variant library: the push --no-verify ban still fires" 2 "$?"
    rm -rf "$BROKEN" 2>/dev/null || true
done

rm -rf "$ARENA" 2>/dev/null || true

echo ""
printf 'TOTAL: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
