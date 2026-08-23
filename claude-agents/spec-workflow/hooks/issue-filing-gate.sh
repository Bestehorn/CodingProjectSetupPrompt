#!/usr/bin/env bash
# issue-filing-gate.sh — PreToolUse(Bash) gate for issue CREATION.
#
# Enforces `.claude/rules/issue-filing-discipline.md` MECHANICALLY at the one moment that
# matters: the attempt to create a tracker issue. The rule says an issue may be filed only
# for an OBSERVED defect that the fix-first evaluation decided NOT to fix directly, and
# that every filed body carries its provenance. This hook checks the provenance lines are
# there — an agent that skipped the evaluation has nothing to write on them, so the
# missing line is the detectable signature of a reflex filing.
#
# How it works:
#   - Reads the hook JSON on stdin; extracts the Bash command.
#   - Recognises an issue-CREATE call ONLY: `create-issue`, `issue create`
#     (`gh issue create`, `glab issue create`, `<host>_wrapper.py issue create`).
#     Read/update calls (`list-issues`, `get-issue`, `comment-issue`, `update-issue`,
#     `issue list/show/claim-check`) are not create calls and are allowed untouched.
#   - Builds the haystack from the command text PLUS, when the body is passed by file
#     (`--body-file` / `--description-file` / `-F`), that file's contents.
#   - BLOCKS (exit 2) when a required provenance line is provably absent:
#         Origin:            human-request | spawned-discovery | spawned-residual | agent-sweep
#         Subject:           product | process
#         Spawned-from:      #<N>   (required only when Origin is spawned-*)
#         Filing-rationale:  RESEARCH | DESIGN-OPTIONS | OUT-OF-SCOPE | HUMAN-REQUEST
#     The stderr message names the missing lines and restates the fix-first evaluation,
#     because "fix it instead" is the outcome this gate exists to make easy to choose.
#
# Fail-open by design (exit 0, with a note on stderr): the command is not a create call;
# the body comes from a source this hook cannot read (heredoc, stdin, command
# substitution, a variable, an unreadable --body-file); or the payload does not parse. It
# must NEVER wedge a session — it only stops the one unambiguous case where a create call
# is provably missing its provenance.
#
# DECLARED RESIDUALS (this gate is a floor, not a fence). It does not see: a body assembled
# through variable indirection or command substitution; a create call issued through an
# interpreter (`python -c`), a wrapper shell (`bash -c`), or a write-then-execute script; a
# tracker API call made with curl/wget (the no-git-host-bypass controls cover that surface);
# provenance lines that are present but untruthful. Those are RULE-only, by design — the
# rule text, not this script, is the authority on what may be filed.
#
# Exit codes (Claude Code hook contract):
#   0 -> allow the tool call
#   2 -> block the tool call; stderr is shown to the model as the reason
set -u

payload="$(cat)"

# Extract the Bash command from the hook JSON (python preferred; raw payload fallback).
extract_cmd() {
    if command -v python >/dev/null 2>&1; then
        printf '%s' "$payload" | python -c 'import json,sys
try:
    d=json.load(sys.stdin); print((d.get("tool_input") or {}).get("command",""))
except Exception:
    pass'
    elif command -v python3 >/dev/null 2>&1; then
        printf '%s' "$payload" | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); print((d.get("tool_input") or {}).get("command",""))
except Exception:
    pass'
    else
        printf '%s' "$payload"
    fi
}
cmd="$(extract_cmd)"
[[ -z "$cmd" ]] && exit 0   # nothing to inspect -> allow

# A command whose own verb is a text tool is talking ABOUT issue creation, not doing it.
printf '%s' "$cmd" | grep -Eq '^[[:space:]]*(grep|rg|ag|echo|printf|cat|sed|awk|less|more|head|tail|git[[:space:]]+grep)[[:space:]]' && exit 0

# Only interested in issue CREATION. Anything else: allow.
printf '%s' "$cmd" | grep -Eq '(create-issue|issue[[:space:]]+create)' || exit 0

haystack="$cmd"

# If the body/description is passed by file, add that file's contents to the haystack.
bodyfile="$(printf '%s' "$cmd" \
    | grep -oE -- '(--body-file|--description-file|-F)[[:space:]=]+[^[:space:]"'"'"']+' \
    | head -1 | sed -E 's/^(--body-file|--description-file|-F)[[:space:]=]+//')"
bodyfile_unreadable="no"
if [[ -n "$bodyfile" ]]; then
    proj="${CLAUDE_PROJECT_DIR:-.}"
    resolved=""
    for cand in "$bodyfile" "$proj/$bodyfile"; do
        [[ -f "$cand" ]] && { resolved="$cand"; break; }
    done
    if [[ -n "$resolved" ]]; then
        haystack="$haystack
$(cat "$resolved" 2>/dev/null)"
    else
        bodyfile_unreadable="yes"
    fi
fi

# Collect the missing provenance lines.
missing=""
printf '%s' "$haystack" | grep -Eiq 'Origin:[[:space:]]*(human-request|spawned-discovery|spawned-residual|agent-sweep)' \
    || missing="$missing Origin:"
printf '%s' "$haystack" | grep -Eiq 'Subject:[[:space:]]*(product|process)' \
    || missing="$missing Subject:"
printf '%s' "$haystack" | grep -Eiq 'Filing-rationale:[[:space:]]*(RESEARCH|DESIGN-OPTIONS|OUT-OF-SCOPE|HUMAN-REQUEST)' \
    || missing="$missing Filing-rationale:"
if printf '%s' "$haystack" | grep -Eiq 'Origin:[[:space:]]*spawned-(discovery|residual)'; then
    printf '%s' "$haystack" | grep -Eiq 'Spawned-from:[[:space:]]*#?[0-9]+' \
        || missing="$missing Spawned-from:"
fi

[[ -z "$missing" ]] && exit 0   # provenance complete -> allow

# Provenance is incomplete. Before blocking, check whether the body was even readable:
# an unresolvable body source means "cannot verify", which fails OPEN.
if [[ "$bodyfile_unreadable" == "yes" ]]; then
    echo "issue-filing-gate: --body-file '$bodyfile' is not readable from here; provenance" >&2
    echo "  not verified. Allowing. The four Origin/Subject/Spawned-from/Filing-rationale" >&2
    echo "  lines are still required by .claude/rules/issue-filing-discipline.md." >&2
    exit 0
fi
if printf '%s' "$cmd" | grep -Eq '\$\(|`|<<|\$[A-Za-z_{]'; then
    echo "issue-filing-gate: the issue body is assembled from a source this hook cannot" >&2
    echo "  read (command substitution, heredoc, or a variable); provenance not verified." >&2
    echo "  Allowing. The four provenance lines are still required by" >&2
    echo "  .claude/rules/issue-filing-discipline.md." >&2
    exit 0
fi

echo "BLOCKED by issue-filing-gate: this issue body is missing required provenance" >&2
echo "line(s):$missing" >&2
echo "" >&2
echo "First re-run the fix-first evaluation (.claude/rules/issue-filing-discipline.md):" >&2
echo "  1. Blocking the current task?  -> fix it in the current change, do not file." >&2
echo "  2. Small and clear (a few lines, no design choice, no new dependency)?" >&2
echo "     -> FIX IT NOW and do not file. This is the expected outcome for most" >&2
echo "        defects noticed in passing." >&2
echo "  3. Needs extensive RESEARCH, an evaluation of DESIGN-OPTIONS, or is" >&2
echo "     OUT-OF-SCOPE for the current task (or a human asked: HUMAN-REQUEST)?" >&2
echo "     -> file it, and say which one." >&2
echo "  4. None of the above? -> one line in docs/findings-ledger.md, then move on." >&2
echo "     Filing nothing is a valid and expected outcome." >&2
echo "" >&2
echo "If the evaluation still says FILE, put these lines in the issue body (prefer" >&2
echo "delegating the filing to the issue-intake agent, which emits them):" >&2
echo "  Origin: human-request|spawned-discovery|spawned-residual|agent-sweep" >&2
echo "  Subject: product|process" >&2
echo "  Spawned-from: #<N>            (only when Origin is spawned-*)" >&2
echo "  Filing-rationale: RESEARCH|DESIGN-OPTIONS|OUT-OF-SCOPE|HUMAN-REQUEST — <why>" >&2
exit 2
