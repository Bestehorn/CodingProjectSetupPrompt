#!/usr/bin/env bash
# Prove continuous-work-reinject.sh never borrows another run's state.
set -u
HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARENA="$(mktemp -d)"
ORCH="$ARENA/.claude/agent-state/issue-work-orchestrator"
MINE="5db650ab-0e97-41fe-a5e8-45e52e41386e"
pass=0; fail=0
chk() { if grep -qF "$2" <<<"$3"; then printf '  PASS  %s\n' "$1"; pass=$((pass+1));
        else printf '  FAIL  %s\n        wanted substring: %s\n' "$1" "$2"; fail=$((fail+1)); fi; }
nchk() { if grep -qF "$2" <<<"$3"; then printf '  FAIL  %s\n        FORBIDDEN substring present: %s\n' "$1" "$2"; fail=$((fail+1));
         else printf '  PASS  %s\n' "$1"; pass=$((pass+1)); fi; }

reset() { rm -rf "$ARENA/.claude"; mkdir -p "$ORCH"; printf '{}' > "$ORCH/registry.json"; }
# A SIBLING run, freshly touched, carrying a DIFFERENT issue. This is the trap.
sibling() {
    mkdir -p "$ORCH/runs/54a2387f"
    cat > "$ORCH/runs/54a2387f/resume_state.md" <<EOF
# Resume state
Status: IN_PROGRESS
Phase: FIX
CURRENT_ISSUE: 565
BRANCH: fix-issue-565
EOF
    touch "$ORCH/runs/54a2387f/resume_state.md"
}
run() { ( cd "$ARENA" && printf '{"session_id":"%s","source":"compact","cwd":"%s","hook_event_name":"SessionStart"}' "$1" "$ARENA" | bash "$HOOKS/continuous-work-reinject.sh" 2>&1 ); }

echo "=============================================================================="
echo "continuous-work-reinject.sh"
echo "=============================================================================="

# 1. UNREGISTERED, with a juicy sibling sitting right there. The old hook served 565 here.
reset; sibling
out="$(run "$MINE")"
chk  "contract is always injected"                    "Continuous work is in force" "$out"
chk  "unregistered says so plainly"                   "No orchestrator/spec run is registered" "$out"
nchk "does NOT leak the sibling's issue number"       "565" "$out"
nchk "does NOT leak the sibling's branch"             "fix-issue-565" "$out"
nchk "does NOT leak the sibling's run dir"            "54a2387f" "$out"

# 2. BROKEN: registry declares a run, nothing on disk. Sibling still present.
reset; sibling
printf '{"%s":{"session_id":"%s","run_id":"5db650ab","state_dir":"runs/5db650ab/"}}' "$MINE" "$MINE" > "$ORCH/registry.json"
out="$(run "$MINE")"
chk  "broken identity is reported as unreadable"      "CANNOT BE READ" "$out"
chk  "broken names the exact path to create"          "runs/5db650ab" "$out"
chk  "broken warns the next gate will refuse"         "REFUSE" "$out"
chk  "broken forbids inventing a label"               "do NOT invent a readable run-id label" "$out"
nchk "broken does NOT leak the sibling's issue"       "565" "$out"

# 3. OWNED: my own state exists at the registry-declared path. Sibling still newer? touch mine LAST is
#    irrelevant — resolution is session-keyed, so order must not matter. Touch the SIBLING last on purpose.
reset
mkdir -p "$ORCH/runs/5db650ab"
cat > "$ORCH/runs/5db650ab/resume_state.md" <<EOF
# Resume state
SESSION_ID: $MINE
Status: IN_PROGRESS
Phase: FIX
CURRENT_ISSUE: 574
BRANCH: fix-issue-574-logging-floor
AWAITING_USER: none
EOF
printf '{"%s":{"session_id":"%s","run_id":"5db650ab","state_dir":"runs/5db650ab/"}}' "$MINE" "$MINE" > "$ORCH/registry.json"
sibling   # touched AFTER mine, so an mtime rung would pick the sibling
out="$(run "$MINE")"
chk  "owned reports MY issue"                         "574" "$out"
chk  "owned reports MY branch"                        "fix-issue-574-logging-floor" "$out"
nchk "owned ignores the NEWER sibling entirely"       "565" "$out"
chk  "owned tells the agent to reconcile with reality" "reality wins" "$out"
chk  "owned explains the append-at-end rule"          "LAST occurrence" "$out"

# 4. Identity recovery: state under an AGENT-INVENTED dir, findable only by SESSION_ID.
reset
mkdir -p "$ORCH/runs/run-issue574-20260828T194800Z"
cat > "$ORCH/runs/run-issue574-20260828T194800Z/resume_state.md" <<EOF
SESSION_ID: $MINE
Status: IN_PROGRESS
Phase: FIX
CURRENT_ISSUE: 574
EOF
printf '{"%s":{"session_id":"%s","run_id":"5db650ab","state_dir":"runs/5db650ab/"}}' "$MINE" "$MINE" > "$ORCH/registry.json"
sibling
out="$(run "$MINE")"
chk  "invented dir recovered via SESSION_ID"          "574" "$out"
nchk "recovery still ignores the sibling"             "565" "$out"

# 5. No session id at all.
reset; sibling
out="$( ( cd "$ARENA" && printf '{"source":"startup","cwd":"%s"}' "$ARENA" | bash "$HOOKS/continuous-work-reinject.sh" 2>&1 ) )"
chk  "no session id -> says it cannot identify the run" "cannot be identified" "$out"
nchk "no session id -> still no sibling leak"           "565" "$out"

# 6. THE THREE DELIVERY INVARIANTS. Each is a documented way for a SessionStart hook's text to be silently
#    DISCARDED — no error the agent can see — so each is pinned rather than trusted.
reset
mkdir -p "$ORCH/runs/5db650ab"
cat > "$ORCH/runs/5db650ab/resume_state.md" <<EOF
SESSION_ID: $MINE
Status: IN_PROGRESS
Phase: FIX
CURRENT_ISSUE: 574
EOF
printf '{"%s":{"session_id":"%s","run_id":"5db650ab","state_dir":"runs/5db650ab/"}}' "$MINE" "$MINE" > "$ORCH/registry.json"
( cd "$ARENA" && printf '{"session_id":"%s","source":"compact","cwd":"%s"}' "$MINE" "$ARENA" \
    | bash "$HOOKS/continuous-work-reinject.sh" > "$ARENA/o.txt" 2>"$ARENA/e.txt" )
rc=$?
# (a) It must exit 0. For SessionStart, exit 2 shows stderr TO THE USER ONLY — Claude never sees it — so a
#     non-zero exit would deliver nothing to the agent.
if [[ "$rc" == "0" ]]; then printf '  PASS  invariant: exits 0 (SessionStart stderr never reaches the agent)\n'; pass=$((pass+1));
else printf '  FAIL  invariant: expected exit 0, got %s\n' "$rc"; fail=$((fail+1)); fi
# (b) Its stdout must not look like hook JSON. Stdout that starts with '{' AND ends with '}' is PARSED as
#     JSON, and on a parse failure the text is not added at all.
if [[ "$(head -c1 "$ARENA/o.txt")" != "{" ]]; then printf '  PASS  invariant: stdout is plain text, not JSON-shaped\n'; pass=$((pass+1));
else printf '  FAIL  invariant: stdout begins with { and may be parsed as JSON\n'; fail=$((fail+1)); fi
# (c) It must stay under the 10,000-character output cap; past it the text is replaced by a path + preview,
#     which reads as delivered but is not.
if (( "$(wc -c < "$ARENA/o.txt")" < 10000 )); then printf '  PASS  invariant: stdout under the 10000-char cap (%s bytes)\n' "$(wc -c < "$ARENA/o.txt")"; pass=$((pass+1));
else printf '  FAIL  invariant: stdout is %s bytes, at/over the 10000 cap\n' "$(wc -c < "$ARENA/o.txt")"; fail=$((fail+1)); fi

# 7. A missing library must never break startup (SessionStart cannot block).
BROKE="$(mktemp -d)"; mkdir -p "$BROKE/hooks"; cp "$HOOKS/continuous-work-reinject.sh" "$BROKE/hooks/"
( cd "$BROKE" && printf '{"session_id":"x","cwd":"."}' | bash hooks/continuous-work-reinject.sh >/dev/null 2>&1 )
rc=$?
if [[ "$rc" == "0" ]]; then printf '  PASS  no library -> exit 0 (never breaks startup)\n'; pass=$((pass+1));
else printf '  FAIL  no library -> expected exit 0, got %s\n' "$rc"; fail=$((fail+1)); fi
rm -rf "$BROKE" "$ARENA"

echo ""
printf 'TOTAL: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
