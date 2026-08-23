#!/usr/bin/env bash
# kiro-issue-filing-gate.sh — Kiro CLI `preToolUse` gate for issue CREATION.
#
# Wire it in every agent that can reach the tracker (issue-intake, product-management,
# doc-review, dead-code, issue-housekeeping, issue-work-orchestrator) under
# `hooks.preToolUse` with `matcher: "execute_bash"` — the same matcher every other gate in
# `.kiro/hooks-bin/` uses. Kiro passes the event JSON on stdin with `tool_name`,
# `tool_input`, `session_id`, `cwd`. RESIDUAL: the fleet's agents also carry the
# `executePwsh` tool, and a create call issued through THAT tool is not matched here; no
# `executePwsh` matcher is wired because that matcher value is unverified against the Kiro
# CLI docs and an invalid matcher would risk the agent config, which is a worse failure
# than the gap.
#
# Enforces `.kiro/steering/issue-filing-discipline.md` MECHANICALLY at the one moment that
# matters: the attempt to create a tracker issue. The rule says an issue may be filed only
# for an OBSERVED defect that the fix-first evaluation decided NOT to fix directly, and
# that every filed body carries its provenance. This hook checks the provenance lines are
# there — an agent that skipped the evaluation has nothing to write on them, so the
# missing line is the detectable signature of a reflex filing.
#
# It recognises an issue-CREATE call ONLY: `create-issue`, `issue create` (`gh issue
# create`, `glab issue create`, `<host>_wrapper.py issue create`). Read/update calls
# (`list-issues`, `get-issue`, `comment-issue`, `update-issue`, `issue list/show/
# claim-check`) are not create calls and are allowed untouched. It BLOCKS (exit 2 — the
# documented preToolUse block code, STDERR returned to the LLM) when a required provenance
# line is provably absent from the command text and any readable `--body-file`:
#     Origin:           human-request | spawned-discovery | spawned-residual | agent-sweep
#     Subject:          product | process
#     Spawned-from:     #<N>   (required only when Origin is spawned-*)
#     Filing-rationale: RESEARCH | DESIGN-OPTIONS | OUT-OF-SCOPE | HUMAN-REQUEST
#
# Fail-open by design (exit 0, with a note on stderr): not a create call; a body this hook
# cannot read (heredoc, stdin, command substitution, a variable, an unreadable
# --body-file); or an unparseable payload. It must NEVER wedge a session.
#
# DECLARED RESIDUALS (a floor, not a fence): a body assembled by variable indirection or
# command substitution; a create call issued through an interpreter (`python -c`), a
# wrapper shell (`bash -c`), or write-then-execute; a tracker API call made with
# curl/wget; provenance lines that are present but untruthful. Those are RULE-only by
# design — the steering file, not this script, is the authority on what may be filed.
#
# Differences from the Claude Code version (issue-filing-gate.sh): project root comes from
# the stdin `cwd` field (Kiro has no $CLAUDE_PROJECT_DIR) and the rule lives under
# `.kiro/steering/`. The exit-2-blocks contract is identical.
set -u

input="$(cat)"

jqget() { command -v jq >/dev/null 2>&1 && printf '%s' "$input" | jq -r "$1" 2>/dev/null; }

# Project root from stdin cwd (fallback: process cwd).
cwd="$(jqget '.cwd // empty')"
[[ -z "$cwd" ]] && cwd="$(printf '%s' "$input" | grep -oE '"cwd"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*"([^"]*)"$/\1/')"
proj="."
[[ -n "$cwd" && -d "$cwd" ]] && proj="$cwd"

# Extract the shell command from the event JSON. Prefer jq, then a JSON parse via python,
# and only then the grep fallback. The ORDER matters here in a way it does not for the
# other Kiro gates: the grep pattern stops at the first `"` in the value, so an inline
# `--body "Origin: ..."` is TRUNCATED away and the provenance would look absent. Blocking
# on a truncated read would be a false block, so `extract_mode` records which reader
# answered and the gate refuses to block on a grep-truncated command (see below).
extract_mode="none"
cmd="$(jqget '.tool_input.command // empty')"
[[ -n "$cmd" ]] && extract_mode="jq"
if [[ -z "$cmd" ]]; then
  for pybin in python python3; do
    command -v "$pybin" >/dev/null 2>&1 || continue
    cmd="$(printf '%s' "$input" | "$pybin" -c 'import json,sys
try:
    d=json.load(sys.stdin); print((d.get("tool_input") or {}).get("command",""))
except Exception:
    pass')"
    [[ -n "$cmd" ]] && { extract_mode="python"; break; }
  done
fi
if [[ -z "$cmd" ]]; then
  cmd="$(printf '%s' "$input" | grep -oE '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*:[[:space:]]*"(.*)"/\1/')"
  [[ -n "$cmd" ]] && extract_mode="grep"
fi
[[ -z "$cmd" ]] && exit 0   # nothing to inspect -> allow

# A command whose own verb is a text tool is talking ABOUT issue creation, not doing it.
printf '%s' "$cmd" | grep -Eq '^[[:space:]]*(grep|rg|ag|echo|printf|cat|sed|awk|less|more|head|tail|Select-String|Get-Content|Write-Output|git[[:space:]]+grep)[[:space:]]' && exit 0

# Only interested in issue CREATION. Anything else: allow.
printf '%s' "$cmd" | grep -Eq '(create-issue|issue[[:space:]]+create)' || exit 0

haystack="$cmd"

# If the body/description is passed by file, add that file's contents to the haystack.
bodyfile="$(printf '%s' "$cmd" \
    | grep -oE -- '(--body-file|--description-file|-F)[[:space:]=]+[^[:space:]"'"'"']+' \
    | head -1 | sed -E 's/^(--body-file|--description-file|-F)[[:space:]=]+//')"
bodyfile_unreadable="no"
if [[ -n "$bodyfile" ]]; then
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

# Provenance is incomplete. An unresolvable body source means "cannot verify" -> fail open.
if [[ "$extract_mode" == "grep" ]]; then
    echo "kiro-issue-filing-gate: neither jq nor python was available, so the command was" >&2
    echo "  read with a pattern that truncates at the first quote; an inline issue body" >&2
    echo "  cannot be inspected. Allowing. The four Origin/Subject/Spawned-from/" >&2
    echo "  Filing-rationale lines are still required by" >&2
    echo "  .kiro/steering/issue-filing-discipline.md." >&2
    exit 0
fi
if [[ "$bodyfile_unreadable" == "yes" ]]; then
    echo "kiro-issue-filing-gate: --body-file '$bodyfile' is not readable from here;" >&2
    echo "  provenance not verified. Allowing. The four Origin/Subject/Spawned-from/" >&2
    echo "  Filing-rationale lines are still required by" >&2
    echo "  .kiro/steering/issue-filing-discipline.md." >&2
    exit 0
fi
if printf '%s' "$cmd" | grep -Eq '\$\(|`|<<|\$[A-Za-z_{]'; then
    echo "kiro-issue-filing-gate: the issue body is assembled from a source this hook" >&2
    echo "  cannot read (command substitution, heredoc, or a variable); provenance not" >&2
    echo "  verified. Allowing. The four provenance lines are still required by" >&2
    echo "  .kiro/steering/issue-filing-discipline.md." >&2
    exit 0
fi

echo "BLOCKED by kiro-issue-filing-gate: this issue body is missing required provenance" >&2
echo "line(s):$missing" >&2
echo "" >&2
echo "First re-run the fix-first evaluation (.kiro/steering/issue-filing-discipline.md):" >&2
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
echo "delegating the filing to the issue-intake-agent, which emits them):" >&2
echo "  Origin: human-request|spawned-discovery|spawned-residual|agent-sweep" >&2
echo "  Subject: product|process" >&2
echo "  Spawned-from: #<N>            (only when Origin is spawned-*)" >&2
echo "  Filing-rationale: RESEARCH|DESIGN-OPTIONS|OUT-OF-SCOPE|HUMAN-REQUEST — <why>" >&2
exit 2
