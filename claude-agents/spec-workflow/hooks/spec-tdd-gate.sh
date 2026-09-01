#!/usr/bin/env bash
# spec-tdd-gate.sh — PreToolUse(Bash) gate for the spec/TDD workflow.
#
# Wire as a PreToolUse hook with matcher "Bash" in .claude/settings.json. It reads the
# hook JSON on stdin, inspects the Bash command, and BLOCKS (exit 2) when:
#   (a) the command bypasses verification: `git commit --no-verify` / `-n`, or
#       `git push --no-verify`;
#   (b) the command is `git push` while a task marked complete in the active spec has no
#       test-evidence capture, or the newest capture is red or riddled with skips;
#   (c) the command is `git push` while CI-OUTAGE MODE is declared and no green
#       full-suite capture exists — because in that state nothing downstream will run
#       the suite either.
# Otherwise it allows the command (exit 0).
#
# Exit 2 feeds the stderr message back to Claude, so it learns why it was blocked and what to do.
#
# WHY THE GATE IS ON PUSH AND NOT ON COMMIT
#   It used to block `git commit` unless the current task had a green capture. On a project
#   whose suite takes an hour that made every commit cost an hour, so agents batched
#   everything into one enormous commit and the history stopped being reviewable — the
#   opposite of what the gate was for.
#   Commits are now cheap (the pre-commit hook is lint + security only) and are meant to be
#   frequent. The PUSH is the boundary where evidence is owed, because a push is what asks
#   CI — and other people — to take the work seriously. See the CI-owns-the-test-suite rule.
#
#   Note this gate does NOT require a local full-suite run before a push. CI runs the suite
#   on the pushed SHA and is authoritative. What it requires is that the per-task paired
#   tests the workflow already captured are actually green.
#
# `-n` IS BANNED ON COMMIT ONLY, DELIBERATELY: for `git commit` it means --no-verify, but
# for `git push` it means --dry-run, which is harmless and occasionally useful.
#
# ---------------------------------------------------------------------------------------------------------
# THREE DEFECTS FIXED HERE, each measured on the previous version.
# ---------------------------------------------------------------------------------------------------------
#
# 1. THE MTIME BORROW — the same defect found in spec-stop-gate.sh and continuous-work-reinject.sh, making
#    this its THIRD instance. The registry lookup was guarded by `command -v jq` with NO fallback, so on a
#    host without jq (measured: the development host) it never ran, and resolution fell through to
#        ls -t "$base"/*/workflow_state.md "$base"/*/runs/*/workflow_state.md | head -1
#    i.e. THE MOST RECENTLY TOUCHED workflow state anywhere in the clone. With concurrent worktrees that is
#    routinely another run's state, so this gate would gate one session's push on a stranger's task ids and
#    evidence — blocking a legitimate push, or waving through an unproven one, depending on whose state was
#    newest. FIXED: resolution is `hook_resolve_owned_state_file`, every rung of which is session-keyed. There
#    is no mtime rung. A session with no resolvable run of its own still uses the documented single-run
#    `spec-conductor/` location, which is what keeps a plain `spec-conductor` run working.
#
# 2. A RED CAPTURE COULD PASS THE GATE. The check was
#        grep -qiE 'failed|error' && ! grep -qiE '0 failed|no failures|[1-9][0-9]* passed'
#    whose second clause is satisfied by ANY capture containing a passing count. MEASURED: a capture reading
#    `3 failed, 5 passed in 2.1s` was ALLOWED, because "5 passed" matched the escape clause. Since real
#    pytest output almost always reports both counts, the failure check was close to unreachable. FIXED: the
#    predicate is now anchored on a non-zero SUMMARY COUNTER, matching spec-stop-gate.sh — it fires on
#    `[1-9][0-9]* failed` and ignores `0 failed`, so no escape clause is needed at all.
#
# 3. A LIBRARY ABORT FAILED OPEN. There was no EXIT trap, so a `set -u` abort or an unreadable state file
#    exited 1 — which the harness treats as a NON-BLOCKING error, allowing the push. FIXED: an EXIT trap
#    maps any unexpected status to exit 2.
#
#    The trap is installed DELIBERATELY LATE, and the position is load-bearing. This gate runs on EVERY Bash
#    command, so failing closed from the top would refuse every shell command in the session the moment the
#    library had a problem — catastrophically disproportionate. Instead the cheap, library-free decisions
#    run FIRST: a non-push command exits 0, and the bypass-flag bans block. Only a `git push` reaches the
#    library, so failing closed can only ever refuse a PUSH — which is precisely the act this gate exists
#    to hold. Keep that ordering if you edit this file.
set -u

input="$(cat)"

# ---------------------------------------------------------------------------------------------------------
# LIBRARY-FREE SECTION. Everything above the trap must stay free of the library, so that a broken library
# cannot affect any command other than a push. See fix 3.
# ---------------------------------------------------------------------------------------------------------

# Extract the Bash command from the hook JSON. Prefer jq; fall back to grep. This one HAS a fallback and
# always did — unlike the registry read in fix 1.
cmd=""
if command -v jq >/dev/null 2>&1; then
  cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)"
fi
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

# (a) Ban verification bypass outright. This decision is INDEPENDENT of workflow state on purpose: a session
# owning no spec workflow is still refused, so the ban cannot be escaped by having no state.
if (( is_commit == 1 )) && grep -qE '(--no-verify|[[:space:]]-n([[:space:]]|$))' <<<"$stripped"; then
  echo "spec-tdd-gate: 'git commit --no-verify'/-n is forbidden. The pre-commit hook is lint + security only and takes about a second — there is nothing to save by skipping it, and a bypass is how a secret or a lint regression reaches the remote. Fix the reported issue instead." >&2
  exit 2
fi
if (( is_push == 1 )) && grep -qE '(--no-verify)' <<<"$stripped"; then
  echo "spec-tdd-gate: 'git push --no-verify' is forbidden. The pre-push hook is the type check, plus the full suite when CI-OUTAGE MODE is declared — and in that state it is the ONLY thing verifying this push. Fix the cause instead of bypassing the hook." >&2
  exit 2
fi

# Commits carry no evidence requirement: commit early, commit often.
if (( is_push == 0 )); then
  exit 0
fi

# ---------------------------------------------------------------------------------------------------------
# From here on the command IS a git push, so failing closed refuses only that push.
# ---------------------------------------------------------------------------------------------------------
trap 'rc=$?; if (( rc != 0 && rc != 2 )); then
        echo "spec-tdd-gate: ABORTED (status $rc) before reaching a decision — refusing the PUSH rather than allowing it unverified. Fix the hook or its library, then push." >&2
        exit 2
      fi' EXIT

lib="$(dirname "${BASH_SOURCE[0]}")/hook-state-lib.sh"
# shellcheck source=./hook-state-lib.sh
. "$lib" 2>/dev/null || {
    echo "spec-tdd-gate: cannot source $lib — refusing the push. Restore the library, then push." >&2
    exit 2
}
command -v hook_task_selftest >/dev/null 2>&1 || {
    echo "spec-tdd-gate: $lib sourced only partially (self-test symbol absent) — refusing the push." >&2
    exit 2
}
hook_task_selftest || {
    echo "spec-tdd-gate: library self-test failed — refusing the push." >&2
    exit 2
}

_HOOK_JSON_INPUT="$input"
hook_payload_init          # parse the payload ONCE, in THIS shell: see the note in hook-state-lib.sh
sid="$(hook_json_string session_id)"
state_base="$(hook_state_base)"

# Session-keyed resolution only. A spec-conductor run has no registry entry, resolves UNREGISTERED, and so
# legitimately uses the documented single-run location — the library handles that, and nothing else.
state_file="$(hook_resolve_owned_state_file "$state_base" "$sid")"
if [[ -z "$state_file" || ! -f "$state_file" ]]; then
  # No spec workflow this session owns — the bypass bans above have already been enforced.
  exit 0
fi

# Load the state file ONCE in THIS shell. Every `x="$(hook_state_field ...)"` below runs in a subshell, so a
# cache populated inside one dies with it — without this line each field read re-parsed the file.
hook_state_load "$state_file"

phase="$(hook_state_field "$state_file" Phase)"
spec_dir="$(hook_state_field "$state_file" CURRENT_SPEC)"

# Only gate pushes during implementation/verification — a spec-artifact push during the design
# phases has no tests to be green yet, by construction. Matched as a WORD and in UPPERCASE,
# exactly as spec-stop-gate.sh does: the unanchored `*IMPLEMENT*|*VERIFY*` form treats
# `NOT_IMPLEMENTED`, `PRE_IMPLEMENT_REVIEW` and `IMPLEMENTATION_PLANNING` as implementation
# phases, and a case-SENSITIVE comparison lets `Phase: implement` silently switch the gate off.
phase_uc="$(printf '%s' "$phase" | tr '[:lower:]' '[:upper:]')"
case "$phase_uc" in
  IMPLEMENT|IMPLEMENT_*|IMPLEMENTING|VERIFY|VERIFY_*|VERIFYING) : ;;
  *) exit 0 ;;
esac

if [[ -z "$spec_dir" ]]; then
  # Cannot identify the spec. Deliberately NOT a block: an unrecorded CURRENT_SPEC is judged by
  # spec-stop-gate.sh at turn-end; blocking every push in that window would be over-blocking.
  exit 0
fi
[[ -n "${CLAUDE_PROJECT_DIR:-}" && -d "$CLAUDE_PROJECT_DIR/$spec_dir" ]] && spec_dir="$CLAUDE_PROJECT_DIR/$spec_dir"

tasks="$spec_dir/tasks.md"
problems=""

# (b) Every task marked complete must have a capture. An IMPL task produces a green
#     paired-test capture; a pure TEST task produces a red one (that IS its evidence).
#     Ids are parsed with bold markers stripped and headings skipped (an id another checked
#     id extends with a further dotted component), matching spec-stop-gate.sh — the two
#     gates read the same tasks.md and must not disagree about what it says.
if [[ -f "$tasks" ]]; then
  checked_ids=""
  while IFS= read -r line; do
    line_stripped="${line//\*\*/}"
    id="$(sed -E 's/^[[:space:]]*-[[:space:]]*\[[xX]\][[:space:]]*([0-9]+(\.[0-9]+)*).*/\1/' <<<"$line_stripped")"
    [[ "$id" == "$line_stripped" ]] && continue    # no numeric id parsed
    checked_ids+="$id"$'\n'
  done < <(grep -E '^[[:space:]]*-[[:space:]]*\[[xX]\]' "$tasks" 2>/dev/null)

  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    if grep -qE "^${id}\." <<<"$checked_ids"; then
      continue
    fi
    if [[ ! -f "$spec_dir/evidence/green/${id}.txt" && ! -f "$spec_dir/evidence/red/${id}.txt" ]]; then
      problems+="  - task ${id} is marked complete but has no capture (evidence/green/${id}.txt or evidence/red/${id}.txt)."$'\n'
    fi
  done <<<"$checked_ids"
fi

# The newest green capture must actually be passing and free of skip/xfail dodges.
# Both predicates are anchored on a runner SUMMARY COUNTER and read the capture with COMMENT
# lines stripped — matching spec-stop-gate.sh exactly, because the two gates read the SAME
# evidence files and must not disagree about what they mean (a test NAMED
# `test_reports_skipped_reason` is not a skip; `# earlier this run: 3 failed, now fixed` is
# not a failure).
latest_green="$(ls -t "$spec_dir"/evidence/green/*.txt 2>/dev/null | head -1)"
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
#     worktree of the clone.
# A relative --git-common-dir is relative to the CURRENT directory, NOT to the top level of
# the working tree — joining it against --show-toplevel resolves outside the repo entirely
# when the cwd is a subdirectory, which is exactly the case for a hook run from a session.
git_common="$(git rev-parse --git-common-dir 2>/dev/null || true)"
if [[ -n "$git_common" ]]; then
  case "$git_common" in
    /*|[A-Za-z]:*) ;;
    *) git_common="$PWD/$git_common" ;;
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
  echo "spec-tdd-gate: not safe to push — the work is not yet proven:" >&2
  printf '%s' "$problems" >&2
  echo "Commits are free; a push asks CI and other people to take this seriously. Finish the batch, capture the evidence, then push once." >&2
  exit 2
fi

exit 0
