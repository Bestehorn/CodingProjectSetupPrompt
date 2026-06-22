#!/usr/bin/env bash
# kiro-loop-gate.sh — Kiro CLI `stop` hook for the issue-work-orchestrator.
#
# Enforces the orchestrator's core rule mechanically: while an orchestrator run is ACTIVE
# and workable (open, not-in-progress) issues remain, the agent MUST keep working — it may
# NOT end the turn to ask "which issue next?" or "should I continue?". If it tries to stop
# in that state, this hook BLOCKS turn-end and tells it to select the next issue.
#
# Session-identity aware (supports multiple concurrent runs in one clone): it reads the
# `session_id` Kiro passes on stdin, maps the session to its run via registry.json, and
# reads ONLY that run's runs/<run-id>/resume_state.md. It blocks only when, for THIS run:
#   Status=IN_PROGRESS AND WORKABLE_ISSUES_REMAIN=yes AND AWAITING_USER is none.
# Outside an orchestrator session (no registry entry / no state) it is a no-op.
#
# HOW BLOCKING WORKS IN KIRO (differs from Claude Code's exit-2 Stop hook):
#   A stop hook blocks by writing `{"decision":"block","reason":"..."}` to STDOUT and
#   exiting 0. Kiro feeds `reason` back as a new user message, continuing the turn.
#
# LOOP-SAFETY (redesigned for Kiro): Kiro has no `stop_hook_active` field, so this hook
# keeps a per-run consecutive-block counter in the run directory. After LOOP_BLOCK_CAP
# consecutive blocks it allows the stop (so it can never wedge a session); any
# non-blocking pass resets the counter. Wire it in the orchestrator agent's JSON
# `hooks.stop` (alongside kiro-stop-gate.sh).
set -u

LOOP_BLOCK_CAP="${KIRO_LOOP_BLOCK_CAP:-8}"
input="$(cat)"

jqget() { command -v jq >/dev/null 2>&1 && printf '%s' "$input" | jq -r "$1" 2>/dev/null; }
field_json() { # $1 = key; jq with grep/sed fallback
    local v; v="$(jqget ".$1 // empty")"
    [[ -n "$v" ]] && { printf '%s' "$v"; return; }
    printf '%s' "$input" | grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed -E 's/.*"([^"]*)"$/\1/'
}

emit_block() { # $1 = reason text. Writes the Kiro stop-block JSON to STDOUT, exits 0.
  local reason="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -nc --arg r "$reason" '{decision:"block", reason:$r}'
  else
    local esc
    esc="$(printf '%s' "$reason" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk 'BEGIN{ORS="\\n"}{print}')"
    printf '{"decision":"block","reason":"%s"}' "$esc"
  fi
  exit 0
}

sid="$(field_json session_id)"
[[ -z "$sid" ]] && exit 0   # cannot identify the run -> do not interfere

# Project root from stdin cwd (fallback: process cwd).
cwd="$(field_json cwd)"
proj="."
[[ -n "$cwd" && -d "$cwd" ]] && proj="$cwd"

base="$proj/.kiro/agent-state/issue-work-orchestrator"
reg="$base/registry.json"
[[ -f "$reg" ]] || exit 0   # no orchestrator runs registered

# Resolve this session's run_id / state_dir from the registry.
run_dir=""
if command -v jq >/dev/null 2>&1; then
    sd="$(jq -r --arg s "$sid" '.[$s].state_dir // empty' "$reg" 2>/dev/null)"
    [[ -n "$sd" ]] && run_dir="$base/$sd"
fi
# Fallback: derive runs/<first-8-of-sid>/ if the registry has no usable state_dir.
[[ -z "$run_dir" ]] && run_dir="$base/runs/${sid:0:8}"

state="$run_dir/resume_state.md"
counter="$run_dir/.loop_block_count"
reset_counter() { rm -f "$counter" 2>/dev/null || true; }

[[ -f "$state" ]] || exit 0   # this session is not an active orchestrator run

field() { grep -iE "^[*-]?[[:space:]]*$1:" "$state" | tail -1 | sed -E "s/.*$1:[[:space:]]*//I" | tr -d '\r'; }
status="$(field 'Status')"; remain="$(field 'WORKABLE_ISSUES_REMAIN')"; awaiting="$(field 'AWAITING_USER')"

grep -qiE 'IN_PROGRESS' <<<"$status" || { reset_counter; exit 0; }
if [[ -n "$awaiting" && "$awaiting" != "none" && "$awaiting" != "-" ]]; then
    reset_counter
    exit 0   # a genuine, recorded escalation/approval wait is the one allowed pause
fi
if grep -qiE '^(yes|true)$' <<<"$remain"; then
    # Bounded loop-safety: stop blocking after LOOP_BLOCK_CAP consecutive blocks.
    n=0
    [[ -f "$counter" ]] && n="$(tr -dc '0-9' < "$counter" 2>/dev/null)"; n="${n:-0}"
    if (( n >= LOOP_BLOCK_CAP )); then
        reset_counter
        echo "kiro-loop-gate: ${n} consecutive blocks for run ${sid:0:8} — allowing stop so the session cannot wedge. Re-launch to resume the backlog." >&2
        exit 0
    fi
    echo $(( n + 1 )) > "$counter" 2>/dev/null || true
    emit_block "kiro-loop-gate: run ${sid:0:8} is IN_PROGRESS and workable (open, not-in-progress) issues remain.
Do NOT stop to ask which issue to work next or whether to continue — that is the agent's decision, not the user's.
Select the next-highest-priority unlocked workable issue yourself (LOAD_ISSUES -> SELECT) and keep working. Stop only at DONE (no workable issue) or a genuine recorded escalation (set AWAITING_USER with a reason in this run's resume_state.md)."
fi
reset_counter
exit 0
