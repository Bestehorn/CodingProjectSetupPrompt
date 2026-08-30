#!/usr/bin/env bash
# spec-tdd-gate.sh — PreToolUse(Bash) gate for the spec/TDD workflow.
#
# Wire as a PreToolUse hook with matcher "Bash" in .claude/settings.json. It reads the hook JSON on stdin,
# inspects the Bash command, and BLOCKS (exit 2) when:
#   (a) the command bypasses verification: `git commit --no-verify` / `-n`, or
#   (b) the command is `git commit` while the active spec has no fresh GREEN evidence for the task in
#       progress.
# Otherwise it allows the command (exit 0).
#
# Exit 2 feeds the stderr message back to Claude, so it learns why it was blocked and what to do.
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
#    routinely another run's state, so this gate would gate one session's commit on a stranger's task id and
#    evidence — blocking a legitimate commit, or waving through an unproven one, depending on whose state was
#    newest. FIXED: resolution is `hook_resolve_owned_state_file`, every rung of which is session-keyed. There
#    is no mtime rung. A session with no resolvable run of its own still uses the documented single-run
#    `spec-conductor/` location, which is what keeps a plain `spec-conductor` run working.
#
# 2. A RED CAPTURE COULD PASS THE GATE. The check was
#        grep -qiE 'failed|error' && ! grep -qiE '0 failed|no failures|[1-9][0-9]* passed'
#    whose second clause is satisfied by ANY capture containing a passing count. MEASURED: a capture reading
#    `3 failed, 5 passed in 2.1s` was ALLOWED, because "5 passed" matched the escape clause. Since real
#    pytest output almost always reports both counts, the failure check was close to unreachable. FIXED: the
#    predicate is now `[1-9][0-9]* failed|[1-9][0-9]* error`, matching spec-stop-gate.sh — it fires on a
#    non-zero count and ignores `0 failed`, so no escape clause is needed at all.
#
# 3. A LIBRARY ABORT FAILED OPEN. There was no EXIT trap, so a `set -u` abort or an unreadable state file
#    exited 1 — which the harness treats as a NON-BLOCKING error, allowing the commit. FIXED: an EXIT trap
#    maps any unexpected status to exit 2.
#
#    The trap is installed DELIBERATELY LATE, and the position is load-bearing. This gate runs on EVERY Bash
#    command, so failing closed from the top would refuse every shell command in the session the moment the
#    library had a problem — catastrophically disproportionate. Instead the two cheap, library-free decisions
#    run FIRST: a non-commit command exits 0, and the bypass-flag ban blocks. Only a `git commit` reaches the
#    library, so failing closed can only ever refuse a COMMIT — which is precisely the act this gate exists
#    to hold. Keep that ordering if you edit this file.
set -u

input="$(cat)"

# ---------------------------------------------------------------------------------------------------------
# LIBRARY-FREE SECTION. Everything above the trap must stay free of the library, so that a broken library
# cannot affect any command other than a commit. See fix 3.
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

# Only act on git commit commands. Everything else leaves this gate untouched and unblocked.
if ! grep -qE '(^|[;&| ])git[[:space:]]+commit([[:space:]]|$)' <<<"$cmd"; then
  exit 0
fi

# (a) Ban verification bypass outright. This decision is INDEPENDENT of workflow state on purpose: a session
# owning no spec workflow is still refused, so the ban cannot be escaped by having no state.
if grep -qE '(--no-verify|[[:space:]]-n([[:space:]]|$))' <<<"$cmd"; then
  echo "spec-tdd-gate: 'git commit --no-verify'/-n is forbidden — commits must pass the pre-commit hook and be backed by green test evidence. Fix the failing checks instead of bypassing them." >&2
  exit 2
fi

# ---------------------------------------------------------------------------------------------------------
# From here on the command IS a git commit, so failing closed refuses only that commit.
# ---------------------------------------------------------------------------------------------------------
trap 'rc=$?; if (( rc != 0 && rc != 2 )); then
        echo "spec-tdd-gate: ABORTED (status $rc) before reaching a decision — refusing the COMMIT rather than allowing it unverified. Fix the hook or its library, then commit." >&2
        exit 2
      fi' EXIT

lib="$(dirname "${BASH_SOURCE[0]}")/hook-state-lib.sh"
# shellcheck source=./hook-state-lib.sh
. "$lib" 2>/dev/null || {
    echo "spec-tdd-gate: cannot source $lib — refusing the commit. Restore the library, then commit." >&2
    exit 2
}
command -v hook_task_selftest >/dev/null 2>&1 || {
    echo "spec-tdd-gate: $lib sourced only partially (self-test symbol absent) — refusing the commit." >&2
    exit 2
}
hook_task_selftest || {
    echo "spec-tdd-gate: library self-test failed — refusing the commit." >&2
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
  # No spec workflow this session owns — the bypass ban above has already been enforced.
  exit 0
fi

# Load the state file ONCE in THIS shell. Every `x="$(hook_state_field ...)"` below runs in a subshell, so a
# cache populated inside one dies with it — without this line each field read re-parsed the file, which is
# how a single invocation came to spawn eight awk processes on top of everything else.
hook_state_load "$state_file"

phase="$(hook_state_field "$state_file" Phase)"
spec_dir="$(hook_state_field "$state_file" CURRENT_SPEC)"
task_id="$(hook_state_field "$state_file" CURRENT_TASK)"

# Only gate commits during implementation/verification. Matched as a WORD and in UPPERCASE, exactly as
# spec-stop-gate.sh does: the unanchored `*IMPLEMENT*|*VERIFY*` form treats `NOT_IMPLEMENTED`,
# `PRE_IMPLEMENT_REVIEW` and `IMPLEMENTATION_PLANNING` as implementation phases, and being the only
# case-SENSITIVE state comparison in the family meant `Phase: implement` silently switched this gate off while
# logging what read like a correct decision.
phase_uc="$(printf '%s' "$phase" | tr '[:lower:]' '[:upper:]')"
case "$phase_uc" in
  IMPLEMENT|IMPLEMENT_*|IMPLEMENTING|VERIFY|VERIFY_*|VERIFYING) : ;;
  *) exit 0 ;;
esac

if [[ -z "$spec_dir" || -z "$task_id" ]]; then
  # Cannot identify the task. Deliberately NOT a block: unlike a missing tasks.md at an implementation phase
  # (which spec-stop-gate.sh does block, because the artifact is mandatory), an unrecorded CURRENT_TASK is a
  # normal transient state between tasks, and blocking every commit in that window would be over-blocking.
  exit 0
fi
[[ -n "${CLAUDE_PROJECT_DIR:-}" && -d "$CLAUDE_PROJECT_DIR/$spec_dir" ]] && spec_dir="$CLAUDE_PROJECT_DIR/$spec_dir"

green="$spec_dir/evidence/green/${task_id}.txt"
if [[ ! -f "$green" ]]; then
  echo "spec-tdd-gate: no green evidence for task '$task_id' at $green — run the paired tests and capture a passing result before committing." >&2
  exit 2
fi

# The green capture must actually be passing and free of skip/xfail dodges.
#
# BOTH predicates are anchored on a runner SUMMARY COUNTER and read the capture with COMMENT lines stripped —
# matching spec-stop-gate.sh exactly, because the two gates read the SAME evidence files and must not disagree
# about what they mean. The failure predicate already counted (fix 2 above): an earlier escape clause was
# satisfied by any passing count, so `3 failed, 5 passed` was ALLOWED. The SKIP predicate was left matching a
# bare word, which is the mirror error in the over-block direction: a capture containing the test NAME
# `test_reports_skipped_reason PASSED` beside `1000 passed in 12s` refused the commit, and the only escape was
# to EDIT THE EVIDENCE FILE — an evidence gate must never make falsifying the proof the cheapest way forward.
capture="$(grep -vE '^[[:space:]]*#' "$green" 2>/dev/null)"
if grep -qiE '[1-9][0-9]* (failed|failure|failures|error|errors)\b' <<<"$capture"; then
  echo "spec-tdd-gate: green evidence for task '$task_id' shows failures/errors — not safe to commit. Fix the tests, re-run, and re-capture." >&2
  exit 2
fi
if grep -qiE '[1-9][0-9]* (skipped|xfailed|xfail|xpassed|deselected)\b' <<<"$capture"; then
  echo "spec-tdd-gate: green evidence for task '$task_id' reports skipped/xfail tests — resolve them, do not commit around them." >&2
  exit 2
fi

exit 0
