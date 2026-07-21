#!/usr/bin/env bash
# claim-before-worktree.sh — PreToolUse(Bash) gate for the issue-work-orchestrator.
#
# Enforces the "claim before you work" rule MECHANICALLY: an agent must not
# create the per-issue git worktree/branch for issue N until issue N is
# verifiably marked in-progress on the remote tracker. This is the deterministic
# belt to the `issue start` command's suspenders — even if an agent skips or
# fumbles the claim, it is physically stopped at the moment it tries to start
# work, which is exactly where the historical "dropped in-progress label ->
# duplicate work" failures happened.
#
# How it works:
#   - Reads the hook JSON on stdin; extracts the Bash command.
#   - If the command creates a worktree/branch for an issue — matching
#     `git worktree add ... issue-<N>` OR `-b issue-<N>[-slug]` — it extracts N
#     and runs the project's git wrapper `issue claim-check <N>` (read-only).
#   - claim-check exit codes: 0 = claimed or not-open (allow), 3 = OPEN and
#     UNCLAIMED (block), other = error.
#   - BLOCKS (exit 2) ONLY on the positive "open + unclaimed" signal (3).
#
# Fail-open by design: if no issue number parses, the wrapper/config is absent,
# or claim-check errors for any other reason (network/auth/timeout), the hook
# exits 0 (allow). It must NEVER wedge a session on infrastructure trouble — it
# only stops the one unambiguous case where the tracker says the issue is not
# yet claimed.
#
# Exit codes (Claude Code hook contract):
#   0 -> allow the tool call
#   2 -> block the tool call; stderr is shown to the model as the reason
set -u

# Exit code the wrapper's `issue claim-check` uses for "open + unclaimed".
UNCLAIMED_CODE=3

payload="$(cat)"

# Extract the Bash command from the hook JSON (python preferred; grep fallback).
extract_cmd() {
    if command -v python >/dev/null 2>&1; then
        printf '%s' "$payload" | python -c 'import json,sys
try:
    d=json.load(sys.stdin); print((d.get("tool_input") or {}).get("command",""))
except Exception:
    pass'
    elif command -v python3 >/dev/null 2>&1; then
        printf '%s' "$payload" | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); print((d.get("tool_input") or {}).get("command",""))
except Exception:
    pass'
    else
        printf '%s' "$payload"
    fi
}
cmd="$(extract_cmd)"

# Only interested in worktree creation. Anything else: allow.
printf '%s' "$cmd" | grep -Eq 'git[[:space:]].*worktree[[:space:]]+add' || exit 0

# Extract the issue number from `issue-<N>` (worktree path or `-b issue-<N>-slug`
# branch name — the orchestrator's mandated naming). First match wins.
issue="$(printf '%s' "$cmd" | grep -oiE 'issue-[0-9]+' | head -1 | grep -oE '[0-9]+')"
[[ -z "$issue" ]] && exit 0   # no issue number -> not an orchestrator worktree; allow

# Locate the git wrapper. Prefer the project dir the harness exposes.
proj="${CLAUDE_PROJECT_DIR:-.}"
wrapper=""
for cand in "$proj/scripts/gitlab_wrapper.py" "$proj/scripts/github_wrapper.py" \
            "scripts/gitlab_wrapper.py" "scripts/github_wrapper.py"; do
    [[ -f "$cand" ]] && { wrapper="$cand"; break; }
done
[[ -z "$wrapper" ]] && exit 0   # no wrapper installed -> cannot check; allow

# Pick a python interpreter (prefer a project venv if present).
py=""
for cand in "$proj/venv/Scripts/python.exe" "$proj/venv/bin/python" python python3; do
    command -v "$cand" >/dev/null 2>&1 && { py="$cand"; break; }
done
[[ -z "$py" ]] && exit 0   # no interpreter -> allow

# Run the read-only claim check. Capture output for the block message.
out="$("$py" "$wrapper" issue claim-check "$issue" 2>&1)"
rc=$?

if [[ "$rc" -eq "$UNCLAIMED_CODE" ]]; then
    echo "BLOCKED by claim-before-worktree hook: issue #$issue is OPEN and NOT yet" >&2
    echo "claimed in-progress on the tracker. Creating its worktree now risks" >&2
    echo "duplicate work. Claim it FIRST with a single verified call:" >&2
    echo "    $py $wrapper issue start $issue" >&2
    echo "(idempotent, fail-closed). If it is already claimed elsewhere, release" >&2
    echo "your local lock and select another issue. claim-check said:" >&2
    echo "$out" >&2
    exit 2
fi

# rc 0 (claimed / not-open) OR any error (fail-open): allow.
exit 0
