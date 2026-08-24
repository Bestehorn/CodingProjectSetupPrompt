#!/usr/bin/env bash
# continuous-work-reinject.sh — SessionStart hook. Re-seeds the continuous-work contract
# and THIS run's place in the work at the moments a long run is most likely to stall.
#
# WHY THIS EXISTS
#   The first turn after an automatic compaction is the single most likely moment for a
#   spurious "shall I continue?" stop: the conversation that held the agent's place has
#   just been summarized away. `.claude/rules/continuous-work.md` is re-injected from disk
#   (unscoped rules always are), but the agent's POSITION in the work is not — it lives in
#   resume_state.md and only helps if the agent re-reads it. This hook reads it FOR the
#   agent and puts it straight into context, so the post-compaction turn starts knowing
#   both the rule and the next step.
#
# HOW IT WORKS
#   SessionStart is one of the few events whose plain stdout Claude Code injects as
#   context the model can see and act on. So this hook simply prints a short block and
#   exits 0. It can never block (exit 2 on SessionStart only shows stderr to the user).
#
# WIRE IT (matchers: compact = after auto/manual compaction, resume = --continue/--resume,
# startup = a fresh session in a project with work already in flight):
#   "SessionStart": [
#     { "matcher": "compact|resume|startup",
#       "hooks": [ { "type": "command",
#                    "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/continuous-work-reinject.sh" } ] }
#   ]
#
# Output is deliberately small (it is injected on every matching session start) and the
# hook is fail-quiet: if it cannot determine state it prints the contract line only, and
# if it cannot do even that it exits 0 silently. It never writes anything.
set -u

input="$(cat 2>/dev/null || true)"

jqget() { command -v jq >/dev/null 2>&1 && printf '%s' "$input" | jq -r "$1" 2>/dev/null; }
field_json() { # $1 = key; jq with grep/sed fallback
    local v; v="$(jqget ".$1 // empty")"
    [[ -n "$v" ]] && { printf '%s' "$v"; return; }
    printf '%s' "$input" | grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed -E 's/.*"([^"]*)"$/\1/'
}

sid="$(field_json session_id)"
src="$(field_json source)"     # startup | resume | clear | compact | fork
[[ -z "$src" ]] && src="unknown"

proj="${CLAUDE_PROJECT_DIR:-.}"
base="$proj/.claude/agent-state"
orch="$base/issue-work-orchestrator"

# ---------------------------------------------------------------- the contract (always)
echo "## Continuous work is in force (.claude/rules/continuous-work.md)"
echo
if [[ "$src" == "compact" ]]; then
  echo "The conversation was just COMPACTED. Details of earlier tool calls and reasoning are"
  echo "gone; the work is not. Do NOT restart, re-plan, summarize, or ask whether to continue —"
  echo "re-read the state below plus any file you still need, then resume the recorded step."
else
  echo "Session start (source: ${src}). If work is already in flight below, continue it."
fi
echo
echo "Reminder: a turn ends only when the work is FINISHED or a Proven Exception applies"
echo "(irreversible action / sensitive information / genuine design fork / hard blocker —"
echo "each needing proof the alternatives were exhausted). Stopping to ask permission to"
echo "continue is forbidden. Context pressure is never a reason to stop. If you must ask,"
echo "keep it to a few lines and include a recommendation."

# ------------------------------------------------------- this run's place, if discoverable
run_dir=""
if [[ -n "$sid" && -f "$orch/registry.json" ]] && command -v jq >/dev/null 2>&1; then
    sd="$(jq -r --arg s "$sid" '.[$s].state_dir // empty' "$orch/registry.json" 2>/dev/null)"
    [[ -n "$sd" && -d "$orch/$sd" ]] && run_dir="$orch/$sd"
fi
# Fallbacks: the conventional per-session dir, else the most recently touched run.
[[ -z "$run_dir" && -n "$sid" && -d "$orch/runs/${sid:0:8}" ]] && run_dir="$orch/runs/${sid:0:8}"
[[ -z "$run_dir" ]] && run_dir="$( { ls -td "$orch"/runs/*/ 2>/dev/null; } | head -1)"

state=""
[[ -n "$run_dir" && -f "$run_dir/resume_state.md" ]] && state="$run_dir/resume_state.md"

if [[ -n "$state" ]]; then
    field() { grep -iE "^[*-]?[[:space:]]*$1:" "$state" | tail -1 | sed -E "s/.*$1:[[:space:]]*//I" | tr -d '\r'; }
    st="$(field 'Status')"; ph="$(field 'Phase')"; iss="$(field 'CURRENT_ISSUE')"
    wt="$(field 'CURRENT_WORKTREE')"; br="$(field 'CURRENT_BRANCH')"; pr="$(field 'CURRENT_PR')"
    rem="$(field 'WORKABLE_ISSUES_REMAIN')"; aw="$(field 'AWAITING_USER')"; mode="$(field 'MODE')"
    echo
    echo "## Your recorded place in the work"
    echo
    echo "State file: ${state#$proj/}"
    [[ -n "$mode" ]] && echo "- MODE: $mode"
    [[ -n "$st"   ]] && echo "- Status: $st"
    [[ -n "$ph"   ]] && echo "- Phase: $ph"
    [[ -n "$iss"  ]] && echo "- Current issue: $iss"
    [[ -n "$br"   ]] && echo "- Branch: $br"
    [[ -n "$wt"   ]] && echo "- Worktree: $wt"
    [[ -n "$pr"   ]] && echo "- PR: $pr"
    [[ -n "$rem"  ]] && echo "- Workable issues remain: $rem"
    [[ -n "$aw"   ]] && echo "- Awaiting user: $aw"
    echo
    if [[ -n "$aw" && "$aw" != "none" && "$aw" != "-" ]]; then
        echo "An escalation/approval wait is recorded. Verify it is still real; if it has been"
        echo "answered or has cleared, set AWAITING_USER to none and carry on."
    else
        echo "Resume this phase now. Verify the recorded state against reality first"
        echo "(git -C <worktree> status, git worktree list, the issue and PR via the wrapper) —"
        echo "reality wins; reconcile the file to it. Never redo a step the evidence shows is done."
    fi
else
    # No orchestrator run: still give the agent something concrete to reattach to.
    wf="$( { ls -t "$base"/*/workflow_state.md "$base"/*/runs/*/workflow_state.md 2>/dev/null; } | head -1)"
    if [[ -n "$wf" && -f "$wf" ]]; then
        echo
        echo "## Active spec workflow"
        echo
        echo "State file: ${wf#$proj/}"
        grep -iE "^[*-]?[[:space:]]*(CURRENT_SPEC|Phase|Status):" "$wf" 2>/dev/null | tail -5 | sed 's/^/- /'
        echo
        echo "Re-read that spec's tasks.md and decision log, then continue the recorded phase."
    fi
fi

# A dirty tree at session start almost always means unfinished work, not a stopping point.
if command -v git >/dev/null 2>&1 && git -C "$proj" rev-parse --git-dir >/dev/null 2>&1; then
    dirty="$(git -C "$proj" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "${dirty:-0}" -gt 0 ]]; then
        echo
        echo "Note: the working tree has ${dirty} uncommitted change(s) — likely work in progress."
        echo "Finish and commit it per keep-git-clean.md rather than treating it as done."
    fi
fi

exit 0
