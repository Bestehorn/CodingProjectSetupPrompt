#!/usr/bin/env bash
# kiro-stop-gate.sh — Kiro CLI `stop` hook for the spec/TDD workflow.
#
# Wire it in an agent's JSON `hooks.stop` (stop hooks take no matcher). Kiro passes the
# event JSON on stdin with `session_id`, `cwd`, `assistant_response`. This hook BLOCKS
# turn-end when the spec workflow is mid-implementation and the work is not honestly
# proven, i.e. any of:
#   - a task is marked complete ([x]) in tasks.md but has no evidence capture;
#   - the latest evidence capture shows a failing / errored suite;
#   - a green capture contains skipped/xfail tests (vacuous-green dodge).
#
# HOW BLOCKING WORKS IN KIRO (differs from Claude Code's exit-2 Stop hook):
#   A stop hook blocks by writing `{"decision":"block","reason":"..."}` to STDOUT and
#   exiting 0. Kiro feeds `reason` back as a new user message, continuing the turn. Exit 0
#   with no JSON lets the agent stop normally.
#
# LOOP-SAFETY (redesigned for Kiro): Kiro has no `stop_hook_active` field, so this hook
# keeps a per-run consecutive-block counter next to the resolved state file. After
# STOP_BLOCK_CAP consecutive blocks it allows the stop (so it can never wedge a session),
# and ANY clean (non-blocking) pass resets the counter to 0. This mirrors Claude Code's
# "override a Stop hook after several consecutive blocks" behavior.
set -u

STOP_BLOCK_CAP="${KIRO_STOP_BLOCK_CAP:-5}"
input="$(cat)"

jqget() { command -v jq >/dev/null 2>&1 && printf '%s' "$input" | jq -r "$1" 2>/dev/null; }

emit_block() { # $1 = reason text. Writes the Kiro stop-block JSON to STDOUT, exits 0.
  local reason="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -nc --arg r "$reason" '{decision:"block", reason:$r}'
  else
    # Manual JSON escape: backslash, double-quote, newline, tab, carriage return.
    local esc
    esc="$(printf '%s' "$reason" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk 'BEGIN{ORS="\\n"}{print}')"
    printf '{"decision":"block","reason":"%s"}' "$esc"
  fi
  exit 0
}

# Project root from stdin cwd (fallback: process cwd).
cwd="$(jqget '.cwd // empty')"
[[ -z "$cwd" ]] && cwd="$(printf '%s' "$input" | grep -oE '"cwd"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*"([^"]*)"$/\1/')"
proj="."
[[ -n "$cwd" && -d "$cwd" ]] && proj="$cwd"

# Resolve the active workflow state, SESSION-AWARE: prefer this session_id's run via the
# orchestrator registry; else the most-recently-modified workflow_state.md (incl. per-run).
base="$proj/.kiro/agent-state"
state_file=""
sid="$(jqget '.session_id // empty')"
[[ -z "$sid" ]] && sid="$(printf '%s' "$input" | grep -oE '"session_id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*"([^"]*)"$/\1/')"
reg="$base/issue-work-orchestrator/registry.json"
if [[ -n "$sid" && -f "$reg" ]] && command -v jq >/dev/null 2>&1; then
  sd="$(jq -r --arg s "$sid" '.[$s].state_dir // empty' "$reg" 2>/dev/null)"
  [[ -n "$sd" && -f "$base/issue-work-orchestrator/$sd/workflow_state.md" ]] && \
    state_file="$base/issue-work-orchestrator/$sd/workflow_state.md"
fi
[[ -z "$state_file" ]] && state_file="$( { ls -t "$base"/*/workflow_state.md "$base"/*/runs/*/workflow_state.md 2>/dev/null; } | head -1)"

# Counter lives next to the resolved state (per-run); use a neutral spot if none resolved.
counter_dir="$base"
[[ -n "$state_file" && -f "$state_file" ]] && counter_dir="$(dirname "$state_file")"
counter="$counter_dir/.stop_block_count"
reset_counter() { rm -f "$counter" 2>/dev/null || true; }

[[ -n "$state_file" && -f "$state_file" ]] || { reset_counter; exit 0; }   # no active workflow

phase="$(grep -iE '^[*-]?[[:space:]]*Phase:' "$state_file" | tail -1 | sed -E 's/.*Phase:[[:space:]]*//')"
status="$(grep -iE '^[*-]?[[:space:]]*Status:' "$state_file" | tail -1 | sed -E 's/.*Status:[[:space:]]*//')"
spec_dir="$(grep -iE '^[*-]?[[:space:]]*CURRENT_SPEC:' "$state_file" | tail -1 | sed -E 's/.*CURRENT_SPEC:[[:space:]]*//' | tr -d '\r')"

# Once the workflow is COMPLETED, never block.
grep -qiE 'COMPLETED' <<<"$status" && { reset_counter; exit 0; }

case "$phase" in
  *IMPLEMENT*|*VERIFY*) : ;;
  *) reset_counter; exit 0 ;;
esac

[[ -n "$spec_dir" ]] || { reset_counter; exit 0; }
[[ "$spec_dir" != /* && -d "$proj/$spec_dir" ]] && spec_dir="$proj/$spec_dir"
tasks="$spec_dir/tasks.md"
[[ -f "$tasks" ]] || { reset_counter; exit 0; }

problems=""

# 1. Every completed task ([x]) must have an evidence capture (green for impl, red for
#    test-writing). Task IDs are the leading number of a checked task line.
while IFS= read -r line; do
  id="$(sed -E 's/^[[:space:]]*-[[:space:]]*\[[xX]\][[:space:]]*([0-9]+(\.[0-9]+)?).*/\1/' <<<"$line")"
  [[ "$id" == "$line" ]] && continue           # no numeric id parsed
  if [[ ! -f "$spec_dir/evidence/green/${id}.txt" && ! -f "$spec_dir/evidence/red/${id}.txt" ]]; then
    problems+="  - task ${id} is marked complete but has no evidence capture (evidence/green/${id}.txt or evidence/red/${id}.txt)."$'\n'
  fi
done < <(grep -E '^[[:space:]]*-[[:space:]]*\[[xX]\]' "$tasks")

# 2. The most recent green/regress capture must not show failures.
latest_green="$(ls -t "$spec_dir"/evidence/green/*.txt "$spec_dir"/evidence/regress/*.txt 2>/dev/null | head -1)"
if [[ -n "$latest_green" ]]; then
  if grep -qiE '[1-9][0-9]* failed|[1-9][0-9]* error' "$latest_green"; then
    problems+="  - latest test capture ($latest_green) shows failures/errors — the suite is not green."$'\n'
  fi
  if grep -qiE 'skipped|xfail|xpassed' "$latest_green"; then
    problems+="  - latest test capture ($latest_green) contains skipped/xfail tests — resolve them rather than stopping."$'\n'
  fi
fi

if [[ -z "$problems" ]]; then
  reset_counter
  exit 0
fi

# There are problems → consider blocking, bounded by STOP_BLOCK_CAP consecutive blocks.
n=0
[[ -f "$counter" ]] && n="$(tr -dc '0-9' < "$counter" 2>/dev/null)"; n="${n:-0}"
if (( n >= STOP_BLOCK_CAP )); then
  reset_counter
  echo "kiro-stop-gate: still unproven after ${n} consecutive blocks — allowing stop so the session cannot wedge. Resolve the remaining items before resuming." >&2
  exit 0
fi
echo $(( n + 1 )) > "$counter" 2>/dev/null || true

reason="kiro-stop-gate: not safe to stop — the implementation is not yet proven:
${problems}Continue: finish the task, run its tests, capture the evidence, and only mark it complete when green."
emit_block "$reason"
