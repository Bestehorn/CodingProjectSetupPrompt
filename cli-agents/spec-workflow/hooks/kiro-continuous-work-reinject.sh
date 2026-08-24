#!/usr/bin/env bash
# kiro-continuous-work-reinject.sh — Kiro CLI `agentSpawn` hook. Re-seeds the
# continuous-work contract and THIS run's place in the work when an agent starts.
#
# WHY THIS EXISTS
#   A long run stalls most often when the agent has lost track of where it was. On Kiro the
#   `continuous-work` steering file is `inclusion: always`, so the CONTRACT survives
#   compaction — but the agent's POSITION in the work does not: it lives in
#   resume_state.md and only helps if the agent re-reads it. This hook reads it FOR the
#   agent and puts it into context at spawn, so a resumed or relaunched run starts knowing
#   both the rule and the next step instead of asking.
#
# KIRO LIMITATION (be honest about it): Kiro has no compaction hook. Automatic compaction
# continues the SAME session, so `agentSpawn` does NOT re-fire after it. This hook therefore
# covers launch and relaunch, not mid-session compaction. Mid-session, the always-included
# steering file plus the state files are what carry the run; `@continue-work` is the manual
# recovery path. (The Claude Code twin, continuous-work-reinject.sh, additionally binds to
# SessionStart matcher `compact`, which Kiro has no equivalent of.)
#
# HOW IT WORKS
#   An `agentSpawn` hook's STDOUT (on exit 0) is added to the agent's context. So this hook
#   prints a short block and exits 0. Output is deliberately small, and the hook is
#   fail-quiet: if it cannot determine state it prints the contract line only. It never
#   writes anything.
#
# WIRE IT in the agent's JSON `hooks.agentSpawn` (alongside kiro-session-register.sh):
#   "hooks": { "agentSpawn": [ { "command": ".kiro/hooks-bin/kiro-continuous-work-reinject.sh" } ] }
set -u

input="$(cat 2>/dev/null || true)"

jqget() { command -v jq >/dev/null 2>&1 && printf '%s' "$input" | jq -r "$1" 2>/dev/null; }
field_json() { # $1 = key; jq with grep/sed fallback
    local v; v="$(jqget ".$1 // empty")"
    [[ -n "$v" ]] && { printf '%s' "$v"; return; }
    printf '%s' "$input" | grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed -E 's/.*"([^"]*)"$/\1/'
}

sid="$(field_json session_id)"
proj="${KIRO_PROJECT_DIR:-.}"
base="$proj/.kiro/agent-state"
orch="$base/issue-work-orchestrator"

# ---------------------------------------------------------------- the contract (always)
echo "## Continuous work is in force (see the continuous-work steering rule)"
echo
echo "A turn ends only when the work is FINISHED or a Proven Exception applies (irreversible"
echo "action / sensitive information / genuine design fork / hard blocker — each needing proof"
echo "the alternatives were exhausted). Stopping to ask permission to continue is forbidden."
echo "Context pressure is never a reason to stop: compaction is automatic and you cannot"
echo "trigger it. If you must ask, keep it to a few lines and include a recommendation."
echo "If work is already in flight below, continue it — do not restart or re-plan it."

# ------------------------------------------------------- this run's place, if discoverable
run_dir=""
if [[ -n "$sid" && -f "$orch/registry.json" ]] && command -v jq >/dev/null 2>&1; then
    sd="$(jq -r --arg s "$sid" '.[$s].state_dir // empty' "$orch/registry.json" 2>/dev/null)"
    [[ -n "$sd" && -d "$orch/$sd" ]] && run_dir="$orch/$sd"
fi
[[ -z "$run_dir" && -n "$sid" && -d "$orch/runs/${sid:0:8}" ]] && run_dir="$orch/runs/${sid:0:8}"
[[ -z "$run_dir" ]] && run_dir="$( { ls -td "$orch"/runs/*/ 2>/dev/null; } | head -1)"

state=""
[[ -n "$run_dir" && -f "$run_dir/resume_state.md" ]] && state="$run_dir/resume_state.md"

if [[ -n "$state" ]]; then
    field() { grep -iE "^[*-]?[[:space:]]*$1:" "$state" | tail -1 | sed -E "s/.*$1:[[:space:]]*//I" | tr -d '\r'; }
    st="$(field 'Status')"; ph="$(field 'Phase')"; iss="$(field 'CURRENT_ISSUE')"
    wt="$(field 'CURRENT_WORKTREE')"; br="$(field 'CURRENT_BRANCH')"; pr="$(field 'CURRENT_PR')"
    rem="$(field 'WORKABLE_ISSUES_REMAIN')"; aw="$(field 'AWAITING_USER')"
    echo
    echo "## Your recorded place in the work"
    echo
    echo "State file: ${state#$proj/}"
    [[ -n "$st"  ]] && echo "- Status: $st"
    [[ -n "$ph"  ]] && echo "- Phase: $ph"
    [[ -n "$iss" ]] && echo "- Current issue: $iss"
    [[ -n "$br"  ]] && echo "- Branch: $br"
    [[ -n "$wt"  ]] && echo "- Worktree: $wt"
    [[ -n "$pr"  ]] && echo "- PR: $pr"
    [[ -n "$rem" ]] && echo "- Workable issues remain: $rem"
    [[ -n "$aw"  ]] && echo "- Awaiting user: $aw"
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

if command -v git >/dev/null 2>&1 && git -C "$proj" rev-parse --git-dir >/dev/null 2>&1; then
    dirty="$(git -C "$proj" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "${dirty:-0}" -gt 0 ]]; then
        echo
        echo "Note: the working tree has ${dirty} uncommitted change(s) — likely work in progress."
        echo "Finish and commit it per the keep-git-clean steering rule rather than treating it as done."
    fi
fi

exit 0
