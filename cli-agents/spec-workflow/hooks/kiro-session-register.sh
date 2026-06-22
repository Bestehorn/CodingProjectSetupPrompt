#!/usr/bin/env bash
# kiro-session-register.sh — Kiro CLI `agentSpawn` hook (the analog of Claude Code's
# SessionStart hook). Records this run's identity so the issue-work-orchestrator and the
# gate hooks can tell WHICH run owns the session when several runs share one clone.
#
# Wire it in an agent's JSON `hooks.agentSpawn`. Kiro passes the event JSON on stdin with
# (at least) `hook_event_name`, `cwd`, and `session_id`. This hook upserts an entry keyed
# by session_id into the orchestrator's registry.json so:
#   - the running agent can read registry.json to learn its own session_id / run_id and
#     create its runs/<run-id>/ state subtree;
#   - the stop / preToolUse gate hooks can map the current session_id back to its run and
#     read ONLY that run's state instead of guessing by global file recency.
#
# Differences from the Claude Code version (session-register.sh):
#   - reads the project root from the stdin `cwd` field (Kiro has no $CLAUDE_PROJECT_DIR);
#   - trigger is `agentSpawn`, not SessionStart.
# It is intentionally minimal and non-blocking: a best-effort registry write must never
# break agent startup. If jq is unavailable it falls back to a grep/sed extraction.
set -u

input="$(cat)"

field_json() { # $1 = key; jq with grep/sed fallback
    local v=""
    command -v jq >/dev/null 2>&1 && v="$(printf '%s' "$input" | jq -r ".$1 // empty" 2>/dev/null)"
    [[ -n "$v" ]] && { printf '%s' "$v"; return; }
    printf '%s' "$input" | grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed -E 's/.*"([^"]*)"$/\1/'
}

sid="$(field_json session_id)"
[[ -z "$sid" ]] && exit 0   # nothing to record; do not disturb startup
cwd="$(field_json cwd)"

# Resolve the project root: prefer the stdin cwd, else the process cwd.
proj="."
[[ -n "$cwd" && -d "$cwd" ]] && proj="$cwd"

reg_dir="$proj/.kiro/agent-state/issue-work-orchestrator"
mkdir -p "$reg_dir" 2>/dev/null || exit 0
reg="$reg_dir/registry.json"
[[ -f "$reg" ]] || echo '{}' > "$reg"

run_id="${sid:0:8}"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"

# Upsert the entry. Use jq if available; otherwise leave the file as a valid {} that the
# agent reconciles on first read — the hook's job is just to guarantee the session_id is
# recorded for lookup.
if command -v jq >/dev/null 2>&1; then
    tmp="$reg.tmp.$$"
    if jq --arg sid "$sid" --arg rid "$run_id" --arg cwd "$cwd" --arg ts "$ts" '
        .[$sid] = ((.[$sid] // {}) + {
            session_id: $sid, run_id: $rid, cwd: $cwd,
            state_dir: ("runs/" + $rid + "/"),
            status: ((.[$sid].status) // "starting"),
            started_at: ((.[$sid].started_at) // $ts),
            last_heartbeat: $ts })' "$reg" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$reg" 2>/dev/null || rm -f "$tmp"
    else
        rm -f "$tmp"
    fi
fi

exit 0
