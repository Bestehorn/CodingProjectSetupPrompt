#!/usr/bin/env bash
# kiro-tdd-gate.sh — Kiro CLI `preToolUse` gate for the spec/TDD workflow.
#
# Wire it in an agent's JSON `hooks.preToolUse` with `matcher: "shell"` (the Kiro shell
# tool; aliases execute_bash/execute_cmd). Kiro passes the event JSON on stdin with
# `tool_name`, `tool_input`, `session_id`, `cwd`. This hook inspects the shell command and
# BLOCKS (exit 2 — the documented preToolUse block code, STDERR returned to the LLM) when:
#   (a) the command bypasses verification: `git commit --no-verify` / `-n`, or
#       `git push --no-verify`;
#   (b) the command is `git push` while a task marked complete in the active spec has no
#       test-evidence capture, or the newest capture is red or riddled with skips;
#   (c) the command is `git push` while CI-OUTAGE MODE is declared and no green full-suite
#       capture exists — because in that state nothing downstream will run the suite either.
# Otherwise it allows the command (exit 0).
#
# WHY THE GATE IS ON PUSH AND NOT ON COMMIT
#   It used to block `git commit` unless the current task had a green capture. On a project
#   whose suite takes an hour that made every commit cost an hour, so agents batched
#   everything into one enormous commit and the history stopped being reviewable — the
#   opposite of what the gate was for.
#   Commits are now cheap (the pre-commit hook is lint + security only) and are meant to be
#   frequent. The PUSH is the boundary where evidence is owed, because a push is what asks
#   CI — and other people — to take the work seriously. See the ci-owns-the-test-suite
#   steering rule.
#
#   Note this gate does NOT require a local full-suite run before a push. CI runs the suite
#   on the pushed SHA and is authoritative. What it requires is that the per-task paired
#   tests the workflow already captured are actually green.
#
# `-n` IS BANNED ON COMMIT ONLY, DELIBERATELY: for `git commit` it means --no-verify, but
# for `git push` it means --dry-run, which is harmless and occasionally useful.
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

# Match against the command with quoted strings REMOVED. Otherwise a commit whose message
# mentions pushing (`git commit -m "prepare for push"`) is classified as a push and gated
# against evidence it does not owe. The `([^;&|]*[[:space:]])?` allows for global options,
# which matters because every orchestrator command is `git -C <worktree> …`.
stripped="$(sed -E 's/"[^"]*"//g; s/'"'"'[^'"'"']*'"'"'//g' <<<"$cmd")"

is_commit=0
is_push=0
grep -qE '(^|[;&| ])git[[:space:]]+([^;&|]*[[:space:]])?commit([[:space:]]|$)' <<<"$stripped" && is_commit=1
grep -qE '(^|[;&| ])git[[:space:]]+([^;&|]*[[:space:]])?push([[:space:]]|$)' <<<"$stripped" && is_push=1
# `git stash push` is not a remote push.
grep -qE 'stash[[:space:]]+push' <<<"$stripped" && is_push=0

# Not a commit or a push: nothing here applies.
if (( is_commit == 0 && is_push == 0 )); then
  exit 0
fi

# (a) Ban verification bypass outright.
if (( is_commit == 1 )) && grep -qE '(--no-verify|[[:space:]]-n([[:space:]]|$))' <<<"$stripped"; then
  echo "kiro-tdd-gate: 'git commit --no-verify'/-n is forbidden. The pre-commit hook is lint + security only and takes about a second — there is nothing to save by skipping it, and a bypass is how a secret or a lint regression reaches the remote. Fix the reported issue instead." >&2
  exit 2
fi
if (( is_push == 1 )) && grep -qE '(--no-verify)' <<<"$stripped"; then
  echo "kiro-tdd-gate: 'git push --no-verify' is forbidden. The pre-push hook is the type check, plus the full suite when CI-OUTAGE MODE is declared — and in that state it is the ONLY thing verifying this push. Fix the cause instead of bypassing the hook." >&2
  exit 2
fi

# Commits carry no evidence requirement: commit early, commit often.
if (( is_push == 0 )); then
  exit 0
fi

# ---------------------------------------------------------------------------------------
# From here on the command is a push. Locate the active spec workflow's state,
# SESSION-AWARE so concurrent runs don't cross-talk. Preferred: map this session_id -> its
# run via the orchestrator registry and use that run's runs/<run-id>/workflow_state.md.
# Fallback (e.g. a spec-conductor run with no registry entry): most-recently-modified
# workflow_state.md under any agent-state dir.
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

# Only gate pushes during implementation/verification. A spec-artifact push during the
# design phases has no tests to be green yet, by construction.
case "$phase" in
  *IMPLEMENT*|*VERIFY*) : ;;
  *) exit 0 ;;
esac

if [[ -z "$spec_dir" ]]; then
  # Can't identify the spec; do not hard-block (non-blocking exit 0).
  exit 0
fi
# spec_dir recorded relative to the project root; resolve it.
[[ "$spec_dir" != /* && -d "$proj/$spec_dir" ]] && spec_dir="$proj/$spec_dir"

tasks="$spec_dir/tasks.md"
problems=""

# (b) Every task marked complete must have a capture. An IMPL task produces a green
#     paired-test capture; a pure TEST task produces a red one (that IS its evidence).
if [[ -f "$tasks" ]]; then
  while IFS= read -r line; do
    id="$(sed -E 's/^[[:space:]]*-[[:space:]]*\[[xX]\][[:space:]]*([0-9]+(\.[0-9]+)?).*/\1/' <<<"$line")"
    [[ "$id" == "$line" ]] && continue           # no numeric id parsed
    if [[ ! -f "$spec_dir/evidence/green/${id}.txt" && ! -f "$spec_dir/evidence/red/${id}.txt" ]]; then
      problems+="  - task ${id} is marked complete but has no capture (evidence/green/${id}.txt or evidence/red/${id}.txt)."$'\n'
    fi
  done < <(grep -E '^[[:space:]]*-[[:space:]]*\[[xX]\]' "$tasks")
fi

# The newest green capture must actually be passing and free of skip/xfail dodges.
# Predicates are anchored on a runner SUMMARY COUNTER, never a bare word, and comment
# lines are stripped first — a test NAME containing "skipped" or an agent's own
# '# earlier this run: 3 failed' annotation must not be read as a failing/vacuous run
# (mirrors spec-tdd-gate.sh: the twin gates read the same capture format and must not
# disagree about what it means).
latest_green="$( { ls -t "$spec_dir"/evidence/green/*.txt 2>/dev/null; } | head -1)"
if [[ -n "$latest_green" ]]; then
  capture="$(grep -vE '^[[:space:]]*#' "$latest_green" 2>/dev/null)"
  if grep -qiE '[1-9][0-9]* (failed|failure|failures|error|errors)\b' <<<"$capture"; then
    problems+="  - newest green capture ($latest_green) shows failures/errors."$'\n'
  fi
  if grep -qiE '[1-9][0-9]* (skipped|xfailed|xfail|xpassed|deselected)\b' <<<"$capture"; then
    problems+="  - newest green capture ($latest_green) contains skipped/xfail tests — resolve them, do not push around them."$'\n'
  fi
fi

# (c) CI-OUTAGE MODE: the pushed SHA will get no CI run, so the full suite must have been
#     run locally. The marker lives in the SHARED git dir, so one declaration covers every
#     worktree of the clone. A relative --git-common-dir is relative to the CURRENT
#     directory, NOT to the top level of the working tree — joining it against
#     --show-toplevel resolves outside the repo entirely when the cwd is a subdirectory.
git_common="$(git -C "$proj" rev-parse --git-common-dir 2>/dev/null || true)"
if [[ -n "$git_common" ]]; then
  case "$git_common" in
    /*|[A-Za-z]:*) ;;
    *) git_common="$proj/$git_common" ;;
  esac
  if [[ -f "$git_common/ci-outage-mode" ]]; then
    latest_regress="$( { ls -t "$spec_dir"/evidence/regress/*.txt 2>/dev/null; } | head -1)"
    if [[ -z "$latest_regress" ]]; then
      problems+="  - CI-OUTAGE MODE is declared, so no CI run will verify this push, and there is no full-suite capture under $spec_dir/evidence/regress/. Run 'python scripts/run_tests.py' and capture it."$'\n'
    else
      regress_capture="$(grep -vE '^[[:space:]]*#' "$latest_regress" 2>/dev/null)"
      if grep -qiE '[1-9][0-9]* (failed|failure|failures|error|errors)\b' <<<"$regress_capture"; then
        problems+="  - CI-OUTAGE MODE is declared and the newest full-suite capture ($latest_regress) is red."$'\n'
      fi
    fi
  fi
fi

if [[ -n "$problems" ]]; then
  echo "kiro-tdd-gate: not safe to push — the work is not yet proven:" >&2
  printf '%s' "$problems" >&2
  echo "Commits are free; a push asks CI and other people to take this seriously. Finish the batch, capture the evidence, then push once." >&2
  exit 2
fi

exit 0
