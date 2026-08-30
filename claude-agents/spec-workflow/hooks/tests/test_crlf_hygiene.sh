#!/usr/bin/env bash
# Regression suite for ONE defect class: a carriage return smuggled in through a line-oriented protocol.
#
# WHY THIS HAS ITS OWN FILE
# -------------------------
# On Windows, python's text-mode stdout translates "\n" into "\r\n". A payload parser that emits one
# `key=value` LINE per field therefore hands bash a trailing \r on EVERY value. MEASURED with `od -c`:
#
#     0000000  s e s s i o n _ i d = a b c - 1 2 3  \r  \n
#
# That \r rode into the session id, so the registry lookup MISSED, `hook_resolve_run_dir` answered
# UNREGISTERED, and EVERY gate went silently inert — reproducing the original incident exactly, and out of a
# PERFORMANCE OPTIMISATION rather than a logic change. The predecessor was immune only by accident: it wrote
# ONE value with no newline at all, so there was no line terminator to translate.
#
# Two properties make this worth a dedicated file:
#   * it is INVISIBLE to inspection — `echo "[$sid]"` prints what looks like a correct value, because the \r
#     just moves the cursor. Only a length or byte comparison shows it.
#   * it is a WHOLE-FAMILY failure from a single line of code, in the fail-open direction.
#
# So the property under test is not "python works" but "a \r never reaches a comparison".
set -u

HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$HOOKS/hook-state-lib.sh"

ARENA="$(mktemp -d 2>/dev/null || echo "/tmp/crlf.$$")"
ORCH="$ARENA/.claude/agent-state/issue-work-orchestrator"
SID="deadbeef-1111-2222-3333-444455556666"
mkdir -p "$ORCH/runs/deadbeef"

pass=0; fail=0
t() {
    if [[ "$2" == "$3" ]]; then printf '  PASS  %-58s %s\n' "$1" "$3"; pass=$(( pass + 1 ))
    else printf '  FAIL  %-58s expected [%s] got [%s]\n' "$1" "$2" "$3"; fail=$(( fail + 1 )); fi
}

printf '{"%s":{"state_dir":"runs/deadbeef/"}}' "$SID" > "$ORCH/registry.json"
printf 'SESSION_ID: %s\nStatus: IN_PROGRESS\n' "$SID" > "$ORCH/runs/deadbeef/resume_state.md"

PAYLOAD="$(printf '{"session_id":"%s","cwd":"%s","hook_event_name":"Stop"}' "$SID" "$ARENA")"

echo "=============================================================================="
echo "the payload parse"
echo "=============================================================================="

# Each probe runs in its own subshell so the per-process caches start cold, exactly as a fresh hook does.
parsed_sid="$( _HOOK_JSON_INPUT="$PAYLOAD"; hook_payload_init; hook_json_string session_id )"
t "session id is byte-exact"            "$SID"      "$parsed_sid"
t "session id has no extra byte"        "${#SID}"   "${#parsed_sid}"

parsed_cwd="$( _HOOK_JSON_INPUT="$PAYLOAD"; hook_payload_init; hook_json_string cwd )"
t "cwd is byte-exact (a CR breaks -d)"  "$ARENA"    "$parsed_cwd"
t "cwd resolves as a directory"         "yes"       "$( [[ -d "$parsed_cwd" ]] && echo yes || echo no )"

# THE CONSEQUENCE THAT MATTERED. A \r on the session id made this UNREGISTERED, which every gate reads as
# "nothing to guard". This is the assertion that would have caught the whole class.
verdict="$( _HOOK_JSON_INPUT="$PAYLOAD"; hook_payload_init
            hook_identity_verdict "$ARENA/.claude/agent-state" "$(hook_json_string session_id)" )"
t "identity still resolves -> OWNED"    "OWNED"     "$verdict"

echo ""
echo "=============================================================================="
echo "a CRLF state file"
echo "=============================================================================="

printf 'SESSION_ID: %s\r\nStatus: IN_PROGRESS\r\nPhase: DONE\r\nCURRENT_ISSUE: 574\r\n' "$SID" \
    > "$ORCH/runs/deadbeef/resume_state.md"
STATE="$ORCH/runs/deadbeef/resume_state.md"

status_value="$(hook_state_field "$STATE" Status)"
t "Status is clean"                  "IN_PROGRESS" "$status_value"
# A LENGTH assertion, because a trailing \r is invisible to an equality check printed on a terminal: the CR
# just returns the cursor, so `echo "[$v]"` looks correct. Length is what actually exposes it.
t "Status carries no extra byte"     "11"          "${#status_value}"
t "CURRENT_ISSUE is clean"           "574"         "$(hook_state_field "$STATE" CURRENT_ISSUE)"
t "SESSION_ID is byte-exact"         "$SID"        "$(hook_state_field "$STATE" SESSION_ID)"
# The decisive one: a trailing \r would make the whole-value match fail, so a FINISHED run would be refused.
t "a terminal Phase is recognised"   "yes" \
  "$(hook_phase_is_terminal "$(hook_state_field "$STATE" Phase)" && echo yes || echo no)"
# ...and identity recovery by SESSION_ID must still work from a CRLF file.
rm -f "$ORCH/registry.json"; printf '{}' > "$ORCH/registry.json"
mkdir -p "$ORCH/runs/invented-label"
printf 'SESSION_ID: %s\r\nStatus: IN_PROGRESS\r\n' "$SID" > "$ORCH/runs/invented-label/resume_state.md"
rm -rf "$ORCH/runs/deadbeef"
t "SESSION_ID recovery works on a CRLF file" "OWNED" \
  "$(hook_identity_verdict "$ARENA/.claude/agent-state" "$SID")"

rm -rf "$ARENA" 2>/dev/null || true

echo ""
printf 'TOTAL: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
