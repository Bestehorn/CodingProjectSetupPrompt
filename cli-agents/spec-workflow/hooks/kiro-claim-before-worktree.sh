#!/usr/bin/env bash
# kiro-claim-before-worktree.sh — Kiro CLI `preToolUse` gate for the issue-work-orchestrator.
#
# Wire it in the orchestrator agent's JSON `hooks.preToolUse` with `matcher: "shell"`
# (the Kiro shell tool; aliases execute_bash/execute_cmd). Kiro passes the event JSON on
# stdin with `tool_name`, `tool_input`, `session_id`, `cwd`.
#
# Enforces "claim before you work" MECHANICALLY: an agent must not create the per-issue
# git worktree/branch for issue N until issue N is verifiably marked in-progress on the
# remote tracker. This is the deterministic belt to the `issue start` command's
# suspenders — the historical "dropped in-progress label -> duplicate work" failures
# happened at exactly this moment (worktree creation before a verified claim).
#
# It matches `git worktree add ... issue-<N>` / `-b issue-<N>[-slug]`, extracts N, and
# runs the project's git wrapper `issue claim-check <N>` (read-only). claim-check exit
# codes: 0 = claimed or not-open (allow), 3 = OPEN and UNCLAIMED (block), other = error.
# It BLOCKS (exit 2 — the documented preToolUse block code, STDERR returned to the LLM)
# ONLY on the positive exit-3 signal.
#
# Fail-open by design: if no issue number parses, the wrapper is absent, or claim-check
# errors for any other reason (network/auth/timeout), it exits 0 (allow). It must NEVER
# wedge a session on infrastructure trouble.
#
# Differences from the Claude Code version (claim-before-worktree.sh): matcher/tool is
# `shell` not `Bash`; project root comes from the stdin `cwd` field (Kiro has no
# $CLAUDE_PROJECT_DIR). The exit-2-blocks contract is identical.
set -u

UNCLAIMED_CODE=3

input="$(cat)"

jqget() { command -v jq >/dev/null 2>&1 && printf '%s' "$input" | jq -r "$1" 2>/dev/null; }

# Project root from stdin cwd (fallback: process cwd).
cwd="$(jqget '.cwd // empty')"
[[ -z "$cwd" ]] && cwd="$(printf '%s' "$input" | grep -oE '"cwd"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*"([^"]*)"$/\1/')"
proj="."
[[ -n "$cwd" && -d "$cwd" ]] && proj="$cwd"

# Extract the shell command from the event JSON. Prefer jq; fall back to grep.
cmd="$(jqget '.tool_input.command // empty')"
if [[ -z "$cmd" ]]; then
  cmd="$(printf '%s' "$input" | grep -oE '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*:[[:space:]]*"(.*)"/\1/')"
fi

# Only interested in worktree creation. Anything else: allow.
printf '%s' "$cmd" | grep -Eq 'git[[:space:]].*worktree[[:space:]]+add' || exit 0

# Extract the issue number from `issue-<N>` (worktree path or `-b issue-<N>-slug`).
issue="$(printf '%s' "$cmd" | grep -oiE 'issue-[0-9]+' | head -1 | grep -oE '[0-9]+')"
[[ -z "$issue" ]] && exit 0

# Locate the git wrapper under the project root.
wrapper=""
for cand in "$proj/scripts/gitlab_wrapper.py" "$proj/scripts/github_wrapper.py"; do
    [[ -f "$cand" ]] && { wrapper="$cand"; break; }
done
[[ -z "$wrapper" ]] && exit 0

# Pick a python interpreter (prefer a project venv if present).
py=""
for cand in "$proj/venv/Scripts/python.exe" "$proj/venv/bin/python" python python3; do
    command -v "$cand" >/dev/null 2>&1 && { py="$cand"; break; }
done
[[ -z "$py" ]] && exit 0

out="$("$py" "$wrapper" issue claim-check "$issue" 2>&1)"
rc=$?

if [[ "$rc" -eq "$UNCLAIMED_CODE" ]]; then
    echo "kiro-claim-before-worktree: issue #$issue is OPEN and NOT yet claimed in-progress" >&2
    echo "on the tracker. Creating its worktree now risks duplicate work. Claim it FIRST" >&2
    echo "with a single verified call: $py $wrapper issue start $issue (idempotent," >&2
    echo "fail-closed). If it is already claimed elsewhere, release your local lock and" >&2
    echo "select another issue. claim-check said: $out" >&2
    exit 2
fi

exit 0
