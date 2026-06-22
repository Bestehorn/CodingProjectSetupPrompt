#!/usr/bin/env bash
# kiro-tdd-gate.sh — Kiro CLI `preToolUse` gate for the spec/TDD workflow.
#
# Wire it in an agent's JSON `hooks.preToolUse` with `matcher: "shell"` (the Kiro shell
# tool; aliases execute_bash/execute_cmd). Kiro passes the event JSON on stdin with
# `tool_name`, `tool_input`, `session_id`, `cwd`. This hook inspects the shell command and
# BLOCKS (exit 2 — the documented preToolUse block code, STDERR returned to the LLM) when:
#   (a) the command bypasses verification: `git commit --no-verify` / `-n`, or
#   (b) the command is `git commit` while the active spec has no fresh GREEN evidence for
#       the task currently in progress.
# Otherwise it allows the command (exit 0).
#
# Differences from the Claude Code version (spec-tdd-gate.sh):
#   - matcher/tool is `shell`, not `Bash`; the command is still at tool_input.command;
#   - project root comes from the stdin `cwd` field (Kiro has no $CLAUDE_PROJECT_DIR);
#   - state lives under .kiro/agent-state/ instead of .claude/agent-state/.
# The exit-2-blocks contract is identical to Claude Code's PreToolUse, so the blocking
# logic is unchanged.
set -u

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

# Only act on git commit commands.
if ! grep -qE '(^|[;&| ])git[[:space:]]+commit([[:space:]]|$)' <<<"$cmd"; then
  exit 0
fi

# (a) Ban verification bypass outright.
if grep -qE '(--no-verify|[[:space:]]-n([[:space:]]|$))' <<<"$cmd"; then
  echo "kiro-tdd-gate: 'git commit --no-verify'/-n is forbidden — commits must pass the pre-commit hook and be backed by green test evidence. Fix the failing checks instead of bypassing them." >&2
  exit 2
fi

# Locate the active spec workflow's state, SESSION-AWARE so concurrent runs don't
# cross-talk. Preferred: map this session_id -> its run via the orchestrator registry and
# use that run's runs/<run-id>/workflow_state.md. Fallback (e.g. a spec-conductor run with
# no registry entry): most-recently-modified workflow_state.md under any agent-state dir.
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
if [[ -z "$state_file" ]]; then
  state_file="$( { ls -t "$base"/*/workflow_state.md "$base"/*/runs/*/workflow_state.md 2>/dev/null; } | head -1)"
fi

if [[ -z "$state_file" || ! -f "$state_file" ]]; then
  # No active spec workflow — nothing more to enforce here.
  exit 0
fi

phase="$(grep -iE '^[*-]?[[:space:]]*Phase:' "$state_file" | tail -1 | sed -E 's/.*Phase:[[:space:]]*//')"
spec_dir="$(grep -iE '^[*-]?[[:space:]]*CURRENT_SPEC:' "$state_file" | tail -1 | sed -E 's/.*CURRENT_SPEC:[[:space:]]*//' | tr -d '\r')"
task_id="$(grep -iE '^[*-]?[[:space:]]*CURRENT_TASK:' "$state_file" | tail -1 | sed -E 's/.*CURRENT_TASK:[[:space:]]*//' | tr -d '\r')"

# Only gate commits during implementation/verification.
case "$phase" in
  *IMPLEMENT*|*VERIFY*) : ;;
  *) exit 0 ;;
esac

if [[ -z "$spec_dir" || -z "$task_id" ]]; then
  # Can't identify the task; do not hard-block (non-blocking exit 0).
  exit 0
fi
# spec_dir recorded relative to the project root; resolve it.
[[ "$spec_dir" != /* && -d "$proj/$spec_dir" ]] && spec_dir="$proj/$spec_dir"

green="$spec_dir/evidence/green/${task_id}.txt"
if [[ ! -f "$green" ]]; then
  echo "kiro-tdd-gate: no green evidence for task '$task_id' at $green — run the paired tests and capture a passing result before committing." >&2
  exit 2
fi

# The green capture must actually be passing and free of skip/xfail dodges.
if grep -qiE 'failed|error' "$green" && ! grep -qiE '0 failed|no failures|[1-9][0-9]* passed' "$green"; then
  echo "kiro-tdd-gate: green evidence for task '$task_id' shows failures — not safe to commit." >&2
  exit 2
fi
if grep -qiE 'skipped|xfail|xpassed' "$green"; then
  echo "kiro-tdd-gate: green evidence for task '$task_id' contains skipped/xfail tests — resolve them, do not commit around them." >&2
  exit 2
fi

exit 0
