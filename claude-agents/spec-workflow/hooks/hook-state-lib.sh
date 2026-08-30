#!/usr/bin/env bash
# hook-state-lib.sh — the ONE identity-and-state library every gate hook sources.
#
# WHY THIS FILE EXISTS — a measured incident, not a tidiness exercise.
#
# An autonomous run was instructed, in force, never to end its turn without a proven reason. It ended four
# turns anyway. The investigation found that BOTH Stop hooks whose entire purpose is to prevent that had been
# no-ops for the whole session, and neither had ever blocked a turn-end in that clone across 189 registered
# sessions. The mechanism:
#
#   * `session-register.sh` wrote `state_dir: "runs/<first-8-of-session-id>/"` into registry.json but NEVER
#     CREATED that directory or any state file in it.
#   * The agent, following its command's instruction to "derive RUN_ID", invented a readable label
#     (`run-issue574-20260828T194800Z`) and wrote its state there instead.
#   * Both gates resolve the state file from the registry and then `exit 0` when it is absent. So the two
#     namespaces never met, every gate was silently inert from turn one, and the ONLY thing opposing a stop
#     was rule text competing against a turn-taking prior. Text lost, four times.
#
# Four design rules follow from that, and every function below implements them:
#
#   1. IDENTITY IS SESSION-DERIVED, NEVER MTIME-DERIVED. A hook must never "borrow" the most recently touched
#      run directory. That fallback existed in this codebase and handed one run another run's state — the
#      agent was told a sibling's issue number was its own recorded place. Every rung in
#      `hook_resolve_run_dir` is keyed on the session id. There is no mtime rung.
#   2. AN UNRESOLVABLE IDENTITY IS A VERDICT, NOT A SHRUG. `hook_identity_verdict` distinguishes "this is not
#      an orchestrator session" (allow) from "this IS a registered run whose state is missing" (a broken run
#      the gate must refuse to let stop). Collapsing those two into `exit 0` is the bug above.
#   3. EVERY RUNG HAS A FALLBACK, BECAUSE `jq` IS OFTEN ABSENT. Measured on the development host: `jq` is not
#      installed. Code guarded by `command -v jq` alone is dead code there — which is exactly how the
#      re-inject hook came to skip the registry entirely and fall through to the mtime rung.
#   4. NO GNU-ONLY CONSTRUCT MAY DECIDE ANYTHING. A single non-portable flag can blank every field at once;
#      see `hook_state_field`, where `sed`'s `I` modifier did exactly that.
#
# Sourced by ALL FIVE hooks: session-register.sh, continuous-work-reinject.sh, issue-loop-gate.sh,
# spec-stop-gate.sh, spec-tdd-gate.sh. The resolver lives here and NOWHERE ELSE — the mtime-borrow defect was
# found INDEPENDENTLY in three separate hooks, each having hand-rolled its own registry read with its own jq
# guard and its own `ls -t` fallback. Three copies meant three chances to get it wrong, and all three took it.
#
# `hook_task_selftest` is DELIBERATELY THE LAST DEFINITION IN THIS FILE. A caller that can call it has
# sourced the whole file. That is a self-test rather than a symbol list, because an undefined FUNCTION does
# not abort under `set -u` (only an unset CONSTANT does), so a partially-sourced library would otherwise fail
# OPEN in exactly the hooks that must fail closed.

# ---------------------------------------------------------------------------------------------------------
# Constants. These are the only names a caller may rely on besides the functions.
# ---------------------------------------------------------------------------------------------------------

HOOK_ORCHESTRATOR_DIRNAME="issue-work-orchestrator"
HOOK_SINGLETON_DIRNAME="spec-conductor"
HOOK_STATE_FILENAME="workflow_state.md"
HOOK_RESUME_FILENAME="resume_state.md"

# The identity verdicts. A gate MUST branch on these and never on "is the file there".
HOOK_IDENTITY_OWNED="OWNED"                 # a session-keyed run directory with a resume_state.md
HOOK_IDENTITY_UNREGISTERED="UNREGISTERED"   # not an orchestrator/spec run at all -> gates are no-ops
HOOK_IDENTITY_BROKEN="BROKEN"               # registered as a run, but its state file is MISSING -> fail closed

# Phases/statuses at which a run is genuinely finished.
#
# The vocabulary is WIDER than the four canonical words because the test is ANCHORED, and an anchored test
# against a narrow vocabulary refuses an agent for its choice of synonym. MEASURED with Status IN_PROGRESS:
# `DONE`, `COMPLETED` and `done` passed, while `COMPLETE`, `FINISHED`, `MERGE_CLEANUP -> DONE` and
# `all tasks DONE` were all REFUSED. Over-blocking a finished run is how a gate earns its deletion, so the
# synonyms are admitted while the anchor is kept — the anchor is what stops a narrative MENTION of a terminal
# word from releasing the brake, which is the opposite error and the one that matters more.
HOOK_TERMINAL_PHASES="DONE|COMPLETE|COMPLETED|FINISHED|CLOSED|ABANDONED|ESCALATED|CANCELLED|CANCELED"

# Statuses that affirmatively mean "this run has not begun". Anything OUTSIDE this set and outside the
# terminal set is treated as work in flight — see the note on inverted polarity in `hook_status_is_idle`.
HOOK_IDLE_STATUSES="NOT_STARTED|NOT_YET_STARTED|UNSTARTED|NOT_IN_PROGRESS|NOT_WORKING|IDLE|PENDING|NEW|NONE|UNSET"

# ---------------------------------------------------------------------------------------------------------
# Rung 0 — interpreters and payload parsing.
# ---------------------------------------------------------------------------------------------------------

# Fork-free ASCII case folding. `printf | tr` costs TWO processes per call, and these are called several
# times per hook invocation.
_hook_upper() { local s="${1-}"; printf '%s' "${s^^}"; }
_hook_lower() { local s="${1-}"; printf '%s' "${s,,}"; }

_hook_python_bin() { # -> prints an interpreter that exists, or returns 1
    local candidate
    for candidate in python python3 py; do
        command -v "$candidate" >/dev/null 2>&1 && { printf '%s' "$candidate"; return 0; }
    done
    return 1
}

# hook_json_string <key> — read a top-level STRING field out of the hook payload.
#
# The payload must be in `_HOOK_JSON_INPUT` (callers set it after `input="$(cat)"`). Three rungs: jq, then a
# real JSON parser, then a pure-shell extraction. The shell rung is last because it is the least correct —
# it cannot see a value containing an escaped quote — but it is what keeps a host with neither jq nor python
# from failing open.
# The payload is parsed ONCE per process, for every key a hook needs, and the results are cached.
#
# Without this, each `hook_json_string` call spawned a fresh interpreter, and a single gate invocation made
# five of them (session_id, then `cwd` from `hook_state_base`, then `cwd` again from `hook_project_dir` via
# `hook_contract_version`, plus two registry reads). MEASURED on the development host, where `jq` is absent and
# a Windows python start costs the better part of a second: 7.5 s for ONE gate invocation, of which almost all
# was interpreter startup. A gate that adds seconds to every turn-end gets removed, which is the same outcome
# as a gate that does not work.
HOOK_PAYLOAD_PARSED=""
HOOK_PAYLOAD_SESSION_ID=""
HOOK_PAYLOAD_CWD=""
HOOK_PAYLOAD_SOURCE=""
HOOK_PAYLOAD_EVENT=""

_hook_payload_load() {
    [[ -n "$HOOK_PAYLOAD_PARSED" ]] && return 0
    HOOK_PAYLOAD_PARSED="yes"
    local raw interpreter line key
    raw="${_HOOK_JSON_INPUT:-}"
    [[ -n "$raw" ]] || return 0
    if command -v jq >/dev/null 2>&1; then
        raw="$(printf '%s' "$raw" | jq -r '[
            (.session_id // ""), (.cwd // ""), (.source // ""), (.hook_event_name // "")
        ] | @tsv' 2>/dev/null)" && {
            IFS=$'\t' read -r HOOK_PAYLOAD_SESSION_ID HOOK_PAYLOAD_CWD HOOK_PAYLOAD_SOURCE HOOK_PAYLOAD_EVENT \
                <<<"$raw"
            HOOK_PAYLOAD_EVENT="${HOOK_PAYLOAD_EVENT%$'\r'}"   # see the \r note in the python rung below
            return 0
        }
        raw="${_HOOK_JSON_INPUT:-}"
    fi
    if interpreter="$(_hook_python_bin)"; then
        while IFS= read -r line; do
            # STRIP THE CARRIAGE RETURN. On Windows, python's text-mode stdout translates "\n" into "\r\n", so
            # every value parsed from a LINE-oriented protocol arrives with a trailing \r. MEASURED with
            # `od -c`: `session_id=abc-123\r\n`. That \r rode into the session id, so the registry lookup
            # MISSED, `hook_resolve_run_dir` answered UNREGISTERED, and EVERY gate went silently inert —
            # reproducing the original incident exactly, out of a performance optimisation. The predecessor was
            # immune only by accident: it wrote ONE value with no newline at all.
            line="${line%$'\r'}"
            key="${line%%=*}"
            case "$key" in
                session_id) HOOK_PAYLOAD_SESSION_ID="${line#*=}" ;;
                cwd)        HOOK_PAYLOAD_CWD="${line#*=}" ;;
                source)     HOOK_PAYLOAD_SOURCE="${line#*=}" ;;
                event)      HOOK_PAYLOAD_EVENT="${line#*=}" ;;
            esac
        done < <("$interpreter" -c '
import json, sys
try:
    payload = json.loads(sys.stdin.read() or "{}")
except Exception:
    sys.exit(0)
if not isinstance(payload, dict):
    sys.exit(0)
for out_key, in_key in (("session_id", "session_id"), ("cwd", "cwd"),
                        ("source", "source"), ("event", "hook_event_name")):
    value = payload.get(in_key)
    if isinstance(value, str):
        sys.stdout.write(out_key + "=" + value.replace("\n", " ") + "\n")
' <<<"$raw" 2>/dev/null)
        return 0
    fi
    # Pure-shell rung. Least correct (it cannot see an escaped quote) but it keeps a host with neither jq nor
    # python from failing open.
    HOOK_PAYLOAD_SESSION_ID="$(_hook_json_shell session_id)"
    HOOK_PAYLOAD_CWD="$(_hook_json_shell cwd)"
    HOOK_PAYLOAD_SOURCE="$(_hook_json_shell source)"
    HOOK_PAYLOAD_EVENT="$(_hook_json_shell hook_event_name)"
}

_hook_json_shell() { # <key> — the pure-shell extraction, also used as the last rung of hook_json_string
    printf '%s' "${_HOOK_JSON_INPUT:-}" |
        grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" |
        head -1 | sed -E 's/.*"([^"]*)"$/\1/'
}

# hook_payload_init — parse the payload ONCE, in the CALLER's shell.
#
# Every hook calls this immediately after setting `_HOOK_JSON_INPUT`. Without it, `sid="$(hook_json_string
# session_id)"` parses inside a subshell and the cache dies with it, so the next reader parses again — which is
# how one gate invocation came to spawn five interpreters.
hook_payload_init() { _hook_payload_load; }

hook_json_string() {
    local key="$1" value interpreter
    # Serve the four keys every hook actually reads from the one cached parse.
    case "$key" in
        session_id|cwd|source|hook_event_name)
            _hook_payload_load
            case "$key" in
                session_id)      printf '%s' "$HOOK_PAYLOAD_SESSION_ID" ;;
                cwd)             printf '%s' "$HOOK_PAYLOAD_CWD" ;;
                source)          printf '%s' "$HOOK_PAYLOAD_SOURCE" ;;
                hook_event_name) printf '%s' "$HOOK_PAYLOAD_EVENT" ;;
            esac
            return 0
            ;;
    esac
    if command -v jq >/dev/null 2>&1; then
        value="$(printf '%s' "${_HOOK_JSON_INPUT:-}" | jq -r --arg k "$key" '.[$k] // empty' 2>/dev/null)"
        [[ -n "$value" ]] && { printf '%s' "$value"; return 0; }
    fi
    if interpreter="$(_hook_python_bin)"; then
        value="$("$interpreter" -c '
import json, sys
try:
    payload = json.loads(sys.stdin.read() or "{}")
except Exception:
    sys.exit(0)
value = payload.get(sys.argv[1])
if isinstance(value, str):
    sys.stdout.write(value)
elif isinstance(value, bool):
    sys.stdout.write("true" if value else "false")
' "$key" <<<"${_HOOK_JSON_INPUT:-}" 2>/dev/null)"
        [[ -n "$value" ]] && { printf '%s' "$value"; return 0; }
    fi
    printf '%s' "${_HOOK_JSON_INPUT:-}" |
        grep -oE "\"$key\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" |
        head -1 | sed -E 's/.*"([^"]*)"$/\1/'
}

# ---------------------------------------------------------------------------------------------------------
# Rung 1 — where state lives.
# ---------------------------------------------------------------------------------------------------------

# hook_state_base — the .claude/agent-state directory.
#
# A LADDER, not a single guess. It used to fall back to the RELATIVE `.claude/agent-state` whenever
# `CLAUDE_PROJECT_DIR` was unset or unresolvable, so the hook looked under whatever cwd it inherited, found
# nothing, and every gate no-opped. MEASURED with the variable unset and cwd `/tmp/worktree`, against a session
# whose genuine state recorded `Status: IN_PROGRESS`: exit 0, no message, and a brand-new empty
# `.hook-decisions/` tree appeared under the wrong root — the only trace that anything had happened.
#
# Candidates are tried in order and the first one that actually CONTAINS an orchestrator state tree wins, so a
# stray empty directory cannot shadow the real one.
# Candidates are produced LAZILY, one rung at a time. A `for candidate in "$(cmd1)" "$(cmd2)"` loop expands
# EVERY substitution before the first iteration, so the common case (`CLAUDE_PROJECT_DIR` set and correct)
# still paid a `git rev-parse` and a JSON parse on every single hook invocation. That cost is paid twice per
# turn-end by the two Stop gates and twice more at SessionStart, and this family already had a measured latency
# problem (11,868 ms per turn-end before the resolver was memoized). Cheap rungs must stay cheap.
HOOK_STATE_BASE_CACHE=""
hook_state_base() {
    [[ -n "$HOOK_STATE_BASE_CACHE" ]] && { printf '%s' "$HOOK_STATE_BASE_CACHE"; return 0; }
    local candidate first="" rung
    for rung in project payload gitroot pwd; do
        case "$rung" in
            project) candidate="${CLAUDE_PROJECT_DIR:-}" ;;
            payload) candidate="$(hook_json_string cwd 2>/dev/null)" ;;
            gitroot) candidate="$(git rev-parse --show-toplevel 2>/dev/null)" ;;
            pwd)     candidate="$PWD" ;;
        esac
        [[ -n "$candidate" && -d "$candidate" ]] || continue
        [[ -z "$first" ]] && first="$candidate/.claude/agent-state"
        if [[ -d "$candidate/.claude/agent-state/$HOOK_ORCHESTRATOR_DIRNAME" ]]; then
            HOOK_STATE_BASE_CACHE="$candidate/.claude/agent-state"
            printf '%s' "$HOOK_STATE_BASE_CACHE"
            return 0
        fi
    done
    # No candidate has an orchestrator tree yet (a first run, or a project that has none). Use the first
    # resolvable root rather than a bare relative path, so a decision log cannot land in an unrelated cwd.
    HOOK_STATE_BASE_CACHE="${first:-.claude/agent-state}"
    printf '%s' "$HOOK_STATE_BASE_CACHE"
}

HOOK_PROJECT_DIR_CACHE=""
hook_project_dir() { # -> the project root, or "." when nothing resolves. Lazy and cached, per the note above.
    [[ -n "$HOOK_PROJECT_DIR_CACHE" ]] && { printf '%s' "$HOOK_PROJECT_DIR_CACHE"; return 0; }
    local candidate rung
    for rung in project payload pwd; do
        case "$rung" in
            project) candidate="${CLAUDE_PROJECT_DIR:-}" ;;
            payload) candidate="$(hook_json_string cwd 2>/dev/null)" ;;
            pwd)     candidate="$PWD" ;;
        esac
        if [[ -n "$candidate" && -d "$candidate" ]]; then
            HOOK_PROJECT_DIR_CACHE="$candidate"
            printf '%s' "$HOOK_PROJECT_DIR_CACHE"
            return 0
        fi
    done
    HOOK_PROJECT_DIR_CACHE="."
    printf '%s' "$HOOK_PROJECT_DIR_CACHE"
}

# hook_state_field <file> <Name> — the LAST occurrence of a plain `Name: value` line.
#
# Last-occurrence-wins is right for an append-only run record: the newest entry is the current one. Four
# consequences a caller must know, all measured:
#   * a block at the TOP of the file is what a human reads and what NO hook reads;
#   * a bold `**Name:** value` spelling is matched by NOTHING here — only a SINGLE leading `*` or `-` is
#     stripped, so a bold field is invisible rather than merely out-competed;
#   * a `Name: value` line inside a ``` or ~~~ FENCE is IGNORED. Without fence tracking an example, a quoted
#     instruction or a pasted transcript became an authoritative field, and last-occurrence-wins made a late
#     example beat the real record. MEASURED: a fenced `Status: inside a fenced code block` was returned as
#     the run's Status;
#   * leading AND trailing whitespace is stripped. Measured consequences of not trimming the tail, one per
#     direction: `AWAITING_USER: none ` compared unequal to `none` and so read as a recorded escalation,
#     DISABLING the primary brake; and `CURRENT_SPEC: x ` produced the unopenable path `x /tasks.md`, which
#     refused every turn-end with no escape an agent could find.
#
# THE PORTABILITY BUG THIS REPLACES, because it is the worst single defect found in this family. The previous
# implementation ended in `sed -E "s/.*${name}:[[:space:]]*//I"`. The trailing `I` is a GNU extension: BSD and
# macOS `sed` reject it, exit 1, print nothing — and this function still returned status 0. So EVERY field of
# EVERY file read EMPTY on those hosts (Status, Phase, AWAITING_USER, CURRENT_SPEC, SESSION_ID), which every
# gate reads as "nothing to guard". One non-portable flag silently disabled the entire family. GNU's own
# `--posix` mode proves it is an extension: `sed --posix -E 's/x//I'` fails with `unknown option to 's''.
# The greedy `.*` was a second defect in the same expression — `Phase: IMPLEMENT_PHASE: 3` returned `3`,
# because it stripped to the LAST occurrence of the name.
#
# ONE `awk` pass, POSIX only. Case-insensitivity comes from `toupper()`, which is POSIX awk — NOT from a
# per-character bracket pattern built in the shell. An earlier revision built `[sS][tT]...` by looping over the
# field name with two `tr` forks PER CHARACTER: MEASURED, that made a single blocking gate invocation take
# 80 seconds (10.7 s user, 30.5 s sys — almost entirely process creation), because a ten-character field name
# cost twenty forks and each hook reads six to eight fields. Correct and unusably slow is still broken.
# ONE awk pass PER FILE, cached. A hook reads six to eight fields from the same file, and each read used to be
# its own process. Combined with the per-character pattern builder that preceded it, a single blocking gate
# invocation MEASURED 80 seconds, 30.5 s of it in the kernel creating processes. Correct and unusably slow is
# still broken: a gate that adds tens of seconds to every turn-end gets removed, which is the same outcome as a
# gate that does not work.
#
# The cache is per-PROCESS and per-FILE, so it cannot serve a stale value across turns, and reading a second
# file in the same invocation simply replaces it.
HOOK_STATE_CACHE_FILE=""
HOOK_STATE_CACHE_DATA=""

hook_state_load() { # <file> — parse every `Name: value` line once into the cache
    local file="$1"
    [[ "$file" == "$HOOK_STATE_CACHE_FILE" ]] && return 0
    HOOK_STATE_CACHE_FILE="$file"
    HOOK_STATE_CACHE_DATA=""
    [[ -f "$file" ]] || return 0
    HOOK_STATE_CACHE_DATA="$(awk '
        # Toggle fence state and never read a line inside one.
        /^[[:space:]]*(```|~~~)/ { fence = 1 - fence; next }
        fence { next }
        {
            line = $0
            sub(/\r$/, "", line)
            idx = index(line, ":")
            if (idx > 1) {
                key = substr(line, 1, idx - 1)
                # Strip at most ONE leading list/emphasis marker, so `**Name:**` stays unmatched.
                sub(/^[[:space:]]*[*-]?[[:space:]]*/, "", key)
                sub(/[[:space:]]+$/, "", key)
                if (key ~ /^[A-Za-z_][A-Za-z_0-9]*$/) {
                    value = substr(line, idx + 1)
                    sub(/^[[:space:]]+/, "", value)
                    sub(/[[:space:]]+$/, "", value)
                    # LAST occurrence wins, so a later line overwrites an earlier one.
                    seen[toupper(key)] = value
                }
            }
        }
        END { for (k in seen) print k "\t" seen[k] }
    ' "$file" 2>/dev/null)"
    return 0
}

# hook_state_field <file> <Name> — the LAST occurrence of a plain `Name: value` line.
#
# Four consequences a caller must know, all measured:
#   * a block at the TOP of the file is what a human reads and what NO hook reads (last occurrence wins);
#   * a bold `**Name:** value` spelling is matched by NOTHING — only a SINGLE leading `*` or `-` is stripped,
#     so a bold field is invisible rather than merely out-competed;
#   * a `Name: value` line inside a fenced code block is IGNORED. Without fence tracking, an example, a quoted
#     instruction or a pasted transcript became an authoritative field, and last-occurrence-wins made a late
#     example beat the real record. MEASURED: a fenced `Status: inside a fenced code block` was returned as the
#     run's Status;
#   * leading AND trailing whitespace is stripped. Measured consequences of not trimming the tail, one per
#     direction: `AWAITING_USER: none ` compared unequal to `none` and so read as a recorded escalation,
#     DISABLING the primary brake; and `CURRENT_SPEC: x ` produced the unopenable path `x /tasks.md`, refusing
#     every turn-end with no escape an agent could find.
#
# THE PORTABILITY BUG THIS REPLACES, because it is the worst single defect found in this family. The previous
# implementation ended in `sed -E "s/.*${name}:[[:space:]]*//I"`. The trailing `I` is a GNU extension: BSD and
# macOS `sed` reject it, exit 1, print nothing — and the function still returned status 0. So EVERY field of
# EVERY file read EMPTY on those hosts (Status, Phase, AWAITING_USER, CURRENT_SPEC, SESSION_ID), which every
# gate reads as "nothing to guard". One non-portable flag silently disabled the entire family. GNU's own
# `--posix` mode proves it is an extension. The greedy `.*` was a second defect in the same expression:
# `Phase: IMPLEMENT_PHASE: 3` returned `3`, because it stripped to the LAST occurrence of the name.
# Case-insensitivity now comes from POSIX awk's `toupper()`.
hook_state_field() {
    local file="$1" want="$2" line key
    hook_state_load "$file"
    [[ -n "$HOOK_STATE_CACHE_DATA" ]] || return 0
    want="$(_hook_upper "$want")"
    while IFS= read -r line; do
        line="${line%$'\r'}"                  # see the \r note in _hook_payload_load
        key="${line%%$'\t'*}"
        if [[ "$key" == "$want" ]]; then
            printf '%s' "${line#*$'\t'}"
            return 0
        fi
    done <<<"$HOOK_STATE_CACHE_DATA"
    return 0
}

# hook_field_is_placeholder <value> — 0 when the value means "nothing recorded here".
#
# The seeded state files use `none` for CURRENT_ISSUE, BRANCH, WORKTREE and PR, so an agent following the
# file's own conventions writes `CURRENT_SPEC: none` — and a gate that treats that as a path refuses on
# `none/tasks.md` forever. The `<...>` shape is here for a sharper reason: the gates' own messages once
# printed the literal `AWAITING_USER: <reason>`, so an agent copying the instruction VERBATIM disarmed the
# brake with the string the gate itself supplied.
hook_field_is_placeholder() {
    local value="${1-}"
    [[ -z "$value" ]] && return 0
    # Any angle-bracketed template token, e.g. `<reason>`, `<N>`, `<your-run-id>`.
    case "$value" in '<'*'>') return 0 ;; esac
    case "$(_hook_lower "$value")" in
        none|-|--|n/a|na|unset|unknown|empty|null|nil|tbd|todo|pending|placeholder|xxx) return 0 ;;
        *) return 1 ;;
    esac
}

# hook_is_substantive_escalation <value> — 0 when AWAITING_USER names a real, recorded reason.
#
# `AWAITING_USER` is a SELF-ISSUED permission slip: the only thing standing between an agent and an
# unconditional stop. Guarding it with a two-item deny-list was not a guard. MEASURED as releasing the brake:
# `<reason>` (the literal the gate itself printed), `unset` (the idiom the seed establishes via `MODE: unset`),
# `no`, `false`, `0`, `?`. A minimum length is required for the same reason this project requires one on
# `--carveout-reason`: a reason too short to be a reason is not one.
HOOK_MIN_ESCALATION_REASON=12

hook_is_substantive_escalation() {
    local value="${1-}"
    hook_field_is_placeholder "$value" && return 1
    case "$(_hook_lower "$value")" in
        no|false|0|1|true|yes|y|n|'?'|'??'|waiting|blocked|ask|question) return 1 ;;
    esac
    (( ${#value} >= HOOK_MIN_ESCALATION_REASON ))
}

# hook_status_is_idle <status> — 0 when the run affirmatively says it has NOT begun.
#
# POLARITY IS INVERTED HERE ON PURPOSE, and it is the most important decision in this file. The brake used to
# arm only on the exact token `IN_PROGRESS`, so every other value was read as "nothing to hold" — including
# the value `session-register.sh` itself seeds. MEASURED against the real gate on a properly seeded, OWNED,
# pre-acked run recording `Phase: IMPLEMENT` and `CURRENT_ISSUE: 574`, every one of these exited 0:
# `in progress`, `In Progress`, `in-progress`, `WORKING`, `ACTIVE`, `RUNNING`, `IMPLEMENTING`. Nothing anywhere
# told the agent the vocabulary, so the brake depended on it guessing one magic string.
#
# So an UNRECOGNISED status now means WORK IN FLIGHT, and only an explicit idle or terminal value releases the
# brake. That direction is the safe one: a novel status word costs a spurious refusal (visible, recoverable,
# and it names the escape), whereas under the old polarity it cost the whole guarantee (silent).
# Both predicates match the WHOLE value, case-insensitively, with no fork. The whole-value match is
# load-bearing in both directions: unanchored, a narrative value released or re-armed a brake by accident
# (measured: `IN_PROGRESS - tasks 1-3 completed` disarmed the evidence gate, and `COMPLETED (was IN_PROGRESS)`
# re-armed the loop gate), while a too-narrow vocabulary refused an agent merely for its choice of synonym.
hook_status_is_idle() {
    local status
    status="$(_hook_upper "${1-}")"
    [[ -z "$status" ]] && return 0
    case "$status" in
        NOT_STARTED|NOT_YET_STARTED|UNSTARTED|NOT_IN_PROGRESS|NOT_WORKING|IDLE|PENDING|NEW|NONE|UNSET)
            return 0 ;;
        *) return 1 ;;
    esac
}

hook_phase_is_terminal() { # <phase or status>
    local value
    value="$(_hook_upper "${1-}")"
    case "$value" in
        DONE|COMPLETE|COMPLETED|FINISHED|CLOSED|ABANDONED|ESCALATED|CANCELLED|CANCELED) return 0 ;;
        *) return 1 ;;
    esac
}

# hook_registry_has_session <registry.json> <session_id> — 0 when this session has an ENTRY at all.
#
# A SEPARATE question from `hook_registry_state_dir`, and conflating the two was a fail-open: "is this session
# a registered run?" must not be answered by "did its `state_dir` value parse into a well-formed `runs/…`
# path", because an entry whose `state_dir` is absent, empty, misspelled, absolute or path-traversing then
# reads as UNREGISTERED — as an ordinary chat session — and every gate becomes a no-op for a run that IS
# registered.
#
# Each rung must print a SENTINEL to be believed. Inferring the answer from the exit status alone was a
# measured fail-open: exit 1 meant "entry absent, authoritative", but exit 1 is also what an interpreter that
# never ran the program produces — a broken shim, a `sitecustomize` ImportError, a stub launcher, a venv with
# a missing stdlib. MEASURED with such a python on PATH: this returned "authoritatively absent" for a session
# that WAS in registry.json, and the verdict became UNREGISTERED. A sentinel can only be emitted by a program
# that actually ran.
# BOTH registry questions are answered by ONE call and cached, because they are always asked together and each
# rung is a process spawn. Asking separately doubled the interpreter cost of every identity resolution on a
# host without `jq`.
#
# The cached answer is the sentinel-prefixed string `HAS:<state_dir>` or `MISS:`, or empty when no rung could
# answer at all.
HOOK_REGISTRY_CACHE_KEY=""
HOOK_REGISTRY_CACHE_VALUE=""

_hook_registry_load() { # <registry.json> <session_id> -> populates HOOK_REGISTRY_CACHE_VALUE
    local registry="$1" session="$2" interpreter answer cache_key
    cache_key="$1|$2"
    [[ "$cache_key" == "$HOOK_REGISTRY_CACHE_KEY" ]] && return 0
    HOOK_REGISTRY_CACHE_KEY="$cache_key"
    HOOK_REGISTRY_CACHE_VALUE=""
    [[ -n "$session" && -f "$registry" ]] || return 0

    if command -v jq >/dev/null 2>&1; then
        answer="$(jq -r --arg s "$session" \
            'if has($s) then "HAS:" + ((.[$s].state_dir // "") | tostring) else "MISS:" end' \
            "$registry" 2>/dev/null)"
        answer="${answer%$'\r'}"          # see the \r note in _hook_payload_load
        case "$answer" in
            HAS:*|MISS:*) HOOK_REGISTRY_CACHE_VALUE="$answer"; return 0 ;;
        esac
    fi
    if interpreter="$(_hook_python_bin)"; then
        answer="$("$interpreter" -c '
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        registry = json.load(handle)
except Exception:
    sys.exit(0)
if not isinstance(registry, dict):
    sys.exit(0)
if sys.argv[2] not in registry:
    sys.stdout.write("MISS:")
else:
    entry = registry.get(sys.argv[2])
    value = entry.get("state_dir") if isinstance(entry, dict) else None
    sys.stdout.write("HAS:" + (value if isinstance(value, str) else ""))
' "$registry" "$session" 2>/dev/null)"
        case "$answer" in
            HAS:*|MISS:*) HOOK_REGISTRY_CACHE_VALUE="$answer"; return 0 ;;
        esac
    fi
    # Pure-shell rung. Does the session id appear as a KEY, and if so what state_dir does its own object give?
    # The sed range is SCOPED to that object so this can never return a neighbour's state_dir — without the
    # scoping, this rung is how one run ends up gated on another run's state.
    if grep -qE "\"$session\"[[:space:]]*:" "$registry" 2>/dev/null; then
        answer="HAS:$(sed -n "/\"$session\"[[:space:]]*:[[:space:]]*{/,/}/p" "$registry" 2>/dev/null |
            grep -oE '"state_dir"[[:space:]]*:[[:space:]]*"[^"]*"' |
            head -1 | sed -E 's/.*"([^"]*)"$/\1/')"
    else
        answer="MISS:"
    fi
    HOOK_REGISTRY_CACHE_VALUE="$answer"
}

# NOTE ON SUBSHELLS, because it is what makes the cache work at all. This function is called DIRECTLY (not in
# a `$(…)`) by `hook_resolve_run_dir`, so the load it triggers populates the cache in the CALLER's shell. The
# `hook_registry_state_dir` call that follows IS in a subshell, and it therefore inherits that populated cache
# and spawns nothing. Reverse the order and the saving disappears silently.
hook_registry_has_session() {
    _hook_registry_load "$1" "$2"
    case "$HOOK_REGISTRY_CACHE_VALUE" in
        HAS:*) return 0 ;;
    esac
    # MISS, or no rung could answer. An unanswerable read is NOT reported as "present" — but note that it is
    # also not reported as authoritative absence anywhere a caller could confuse the two: `hook_resolve_run_dir`
    # only ever uses a true return to mean "registered".
    return 1
}

# hook_registry_state_dir <registry.json> <session_id> — that session's declared state_dir, or empty.
# Served from the same single cached query as `hook_registry_has_session`.
hook_registry_state_dir() {
    _hook_registry_load "$1" "$2"
    case "$HOOK_REGISTRY_CACHE_VALUE" in
        HAS:*) printf '%s' "${HOOK_REGISTRY_CACHE_VALUE#HAS:}" ;;
    esac
    return 0
}

# ---------------------------------------------------------------------------------------------------------
# Rung 2 — resolving WHICH run owns this session. Session-keyed rungs only; no mtime rung, ever.
# ---------------------------------------------------------------------------------------------------------

# hook_find_run_dir_by_session <base> <session_id> — find the runs/*/ whose resume_state.md records this id.
#
# This rung exists specifically to repair the incident in this file's header: an agent that invented its own
# readable run-id label put its state where neither the registry path nor the sid-prefix path names it — but
# the state file itself records `SESSION_ID:`. Matching on that is still SESSION-DERIVED, so it can only ever
# return state belonging to this session.
#
# ONE grep, not three processes per candidate. The previous loop called `hook_state_field` per directory,
# forking grep+tail+sed each time, and paid that on every Stop event for every session rungs 1 and 2 did not
# resolve — i.e. every ordinary chat session AND every BROKEN run, which is the incident's own shape. MEASURED
# on the incident host: 0 dirs 4.1 s, 5 dirs 9.2 s, 20 dirs 13.4 s, 40 dirs 23.1 s (~0.48 s/dir), and the spec
# gate paid it two or three times per event. At the 189 run directories that clone had accumulated, a turn-end
# would have cost minutes. A gate slow enough to be resented is a gate that gets removed.
hook_find_run_dir_by_session() {
    local base="$1" session="$2" hit
    [[ -n "$session" && -d "$base/$HOOK_ORCHESTRATOR_DIRNAME/runs" ]] || return 0
    hit="$(grep -lE "^[[:space:]]*[sS][eE][sS][sS][iI][oO][nN]_[iI][dD][[:space:]]*:[[:space:]]*$session[[:space:]]*$" \
        "$base/$HOOK_ORCHESTRATOR_DIRNAME"/runs/*/"$HOOK_RESUME_FILENAME" 2>/dev/null | head -1)"
    [[ -n "$hit" ]] && printf '%s' "$(dirname "$hit")"
    return 0
}

# MEMOIZED for the lifetime of the process. Resolution is expensive where `jq` is absent (each rung spawns a
# python interpreter) and `spec-stop-gate.sh` asked the same question three times. MEASURED before this cache:
# the two Stop gates added 11,868 ms to EVERY turn-end and the SessionStart pair added 13,022 ms.
#
# The cache is per-PROCESS and every hook invocation is a fresh process, so it cannot serve a stale answer
# across turns. It is keyed on both arguments, so a caller passing a different base or session is never handed
# another key's result.
HOOK_RESOLVE_CACHE_KEY=""
HOOK_RESOLVE_CACHE_VALUE=""

_hook_resolve_emit() { # <cache key> <verdict> <run dir> -> memoize, then print "<verdict>|<run dir>"
    HOOK_RESOLVE_CACHE_KEY="$1"
    HOOK_RESOLVE_CACHE_VALUE="$2|$3"
    printf '%s' "$HOOK_RESOLVE_CACHE_VALUE"
}

# hook_resolve_run_dir <base> <session_id> — prints "<verdict>|<run_dir>".
#
# Rungs, in order, ALL session-keyed:
#   1. the registry's declared state_dir for this session;
#   2. the conventional runs/<first-8-of-session-id>/;
#   3. a runs/*/ whose resume_state.md records this SESSION_ID.
#
# Verdicts:
#   OWNED        — a run directory was resolved AND it has a resume_state.md.
#   BROKEN       — this session IS a registered run but no rung found a state file. A run that never
#                  established its state is itself a contract violation, so a gate must fail CLOSED on it
#                  rather than treat it as "no workflow here".
#   UNREGISTERED — the registry knows nothing about this session and no rung found state. A plain chat
#                  session looks exactly like this, so gates MUST be no-ops for it.
hook_resolve_run_dir() {
    local base="$1" session="$2" declared="" run_dir="" registered="no" cache_key
    cache_key="$1|$2"
    if [[ "$cache_key" == "$HOOK_RESOLVE_CACHE_KEY" && -n "$HOOK_RESOLVE_CACHE_VALUE" ]]; then
        printf '%s' "$HOOK_RESOLVE_CACHE_VALUE"
        return 0
    fi
    # `orch` MUST be assigned in a SEPARATE statement. Bash expands every assignment word in a single `local`
    # BEFORE creating any of the locals, so `local base="$1" orch="$base/x"` does not see the new `base` — it
    # silently reads the CALLER's global of that name, or aborts under `set -u` when the caller has none.
    # MEASURED on bash 5.2.37: this function resolved correctly only because both gates happen to hold a
    # global named `base`; called from anywhere else it aborted, and inside a `$(…)` that abort yields an
    # EMPTY verdict, which the gates read as "nothing to guard" — a silent fail-open, and the same shape as
    # the incident in this file's header. Renaming a caller's variable would have disabled both gates.
    local orch="$base/$HOOK_ORCHESTRATOR_DIRNAME"

    # Two INDEPENDENT questions, deliberately asked separately (see hook_registry_has_session):
    #   "is this session a registered run?"  decides BROKEN vs UNREGISTERED
    #   "where does it say its state lives?" decides WHERE to look
    hook_registry_has_session "$orch/registry.json" "$session" && registered="yes"

    declared="$(hook_registry_state_dir "$orch/registry.json" "$session")"
    # A declared state_dir must name a run INSIDE the orchestrator subtree. Reject anything else: the value is
    # interpolated into a path, and one containing "../" would let a session be gated on state it does not own.
    case "$declared" in
        runs/*) [[ "$declared" == *..* ]] && declared="" ;;
        *) declared="" ;;
    esac

    if [[ -n "$declared" && -f "$orch/${declared%/}/$HOOK_RESUME_FILENAME" ]]; then
        _hook_resolve_emit "$cache_key" "$HOOK_IDENTITY_OWNED" "$orch/${declared%/}"
        return 0
    fi
    if [[ -n "$session" && -f "$orch/runs/${session:0:8}/$HOOK_RESUME_FILENAME" ]]; then
        _hook_resolve_emit "$cache_key" "$HOOK_IDENTITY_OWNED" "$orch/runs/${session:0:8}"
        return 0
    fi
    run_dir="$(hook_find_run_dir_by_session "$base" "$session")"
    if [[ -n "$run_dir" ]]; then
        _hook_resolve_emit "$cache_key" "$HOOK_IDENTITY_OWNED" "$run_dir"
        return 0
    fi
    # Nothing resolved. Whether that is benign turns on whether this session is a REGISTERED run — not on
    # whether its `state_dir` happened to parse.
    if [[ "$registered" == "yes" ]]; then
        if [[ -n "$declared" ]]; then
            _hook_resolve_emit "$cache_key" "$HOOK_IDENTITY_BROKEN" "$orch/${declared%/}"
        else
            _hook_resolve_emit "$cache_key" "$HOOK_IDENTITY_BROKEN" "$orch/runs/${session:0:8}"
        fi
        return 0
    fi
    _hook_resolve_emit "$cache_key" "$HOOK_IDENTITY_UNREGISTERED" ""
    return 0
}

# hook_normalize_verdict <verdict> — force any unrecognised value to BROKEN (fail closed).
#
# A gate must never branch on a verdict it does not recognise. MEASURED: with one `set -u` slip injected into
# the resolver — standing in for any future edit — the command substitution's subshell aborted, `resolved` was
# EMPTY, the verdict matched neither the UNREGISTERED nor the BROKEN guard, execution fell through with
# `run_dir` empty, every field read empty, and the gate ALLOWED while logging `Status='' not IN_PROGRESS`. The
# EXIT trap could not help: the abort happened in a SUBSHELL, so the parent's status was never non-zero.
hook_normalize_verdict() {
    case "${1-}" in
        "$HOOK_IDENTITY_OWNED"|"$HOOK_IDENTITY_UNREGISTERED"|"$HOOK_IDENTITY_BROKEN") printf '%s' "$1" ;;
        *) printf '%s' "$HOOK_IDENTITY_BROKEN" ;;
    esac
}

hook_identity_verdict() { # <base> <session_id> -> just the verdict word, normalized
    hook_normalize_verdict "$(hook_resolve_run_dir "$1" "$2" | cut -d'|' -f1)"
}

hook_identity_run_dir() { # <base> <session_id> -> just the run dir (may be empty)
    hook_resolve_run_dir "$1" "$2" | cut -d'|' -f2
}

# hook_resolve_owned_state_file <base> <session_id> — the workflow_state.md this session owns, or empty.
#
# The singleton fallback is keyed on whether the run's own state DECLARES A SPEC, not on the session being
# UNREGISTERED. It used to be keyed on the verdict, and seeding every session made that branch DEAD: no real
# session is UNREGISTERED any more, so the gate read the seeded `workflow_state.md` (empty `CURRENT_SPEC`,
# `Phase: NOT_STARTED`), allowed, and never looked at the conductor's own state. MEASURED: with
# `spec-conductor/workflow_state.md` recording `Phase: IMPLEMENT` and a spec with no `tasks.md`, the gate
# exited 0 logging `phase 'NOT_STARTED' is outside IMPLEMENT/VERIFY` — it judged the seed, not the workflow.
#
# Both candidates are FIXED paths, so this never reaches another run's per-run state.
hook_resolve_owned_state_file() {
    local base="$1" session="$2" resolved verdict run_dir own singleton
    resolved="$(hook_resolve_run_dir "$base" "$session")"
    verdict="$(hook_normalize_verdict "${resolved%%|*}")"
    run_dir="${resolved#*|}"
    singleton="$base/$HOOK_SINGLETON_DIRNAME/$HOOK_STATE_FILENAME"

    if [[ "$verdict" == "$HOOK_IDENTITY_OWNED" ]]; then
        own="$run_dir/$HOOK_STATE_FILENAME"
        if [[ -f "$own" ]] && ! hook_field_is_placeholder "$(hook_state_field "$own" CURRENT_SPEC)"; then
            printf '%s' "$own"
            return 0
        fi
        if [[ -f "$singleton" ]] && ! hook_field_is_placeholder "$(hook_state_field "$singleton" CURRENT_SPEC)"; then
            printf '%s' "$singleton"
            return 0
        fi
        [[ -f "$own" ]] && printf '%s' "$own"
        return 0
    fi
    if [[ "$verdict" == "$HOOK_IDENTITY_UNREGISTERED" ]]; then
        [[ -f "$singleton" ]] && printf '%s' "$singleton"
    fi
    return 0
}

# hook_owned_workflow_missing <base> <session_id> — 0 when the run is OWNED but has NO workflow_state.md.
#
# That is the BROKEN condition one file down, and it used to be reported as "no spec workflow here": MEASURED,
# a run whose registry entry and resume_state.md were present with `Phase: IMPLEMENT` but whose
# workflow_state.md had been deleted resolved OWNED, produced an empty state file, and the spec gate exited 0.
# Absence of state read as absence of obligation, again. Only an UNREGISTERED session may legitimately produce
# "no workflow state".
hook_owned_workflow_missing() {
    local base="$1" session="$2" resolved verdict run_dir
    resolved="$(hook_resolve_run_dir "$base" "$session")"
    verdict="$(hook_normalize_verdict "${resolved%%|*}")"
    run_dir="${resolved#*|}"
    [[ "$verdict" == "$HOOK_IDENTITY_OWNED" ]] || return 1
    [[ -n "$run_dir" && ! -f "$run_dir/$HOOK_STATE_FILENAME" ]]
}

# ---------------------------------------------------------------------------------------------------------
# Rung 3 — the CONTRACT VERSION handshake. This is how a LIVE session picks up a newly deployed contract.
# ---------------------------------------------------------------------------------------------------------
#
# The problem it solves: a rule file added to `.claude/rules/` does not walk into a running session's context,
# and neither does a new agent definition. Something has to PUSH the new contract in.
#
# What makes an already-registered Stop hook the right vehicle: the registration names the interpreter and the
# script PATH, never the script's CONTENTS, so every invocation spawns a fresh interpreter that reads the file
# from disk. And a Stop hook's event cadence is self-scheduling — it fires exactly when the agent attempts the
# act the contract governs, in every session, without waiting for a compaction that may never come.
#
# The delivery channel is a BLOCK (exit 2), because that is the only thing the agent sees: the vendor documents
# that a hook blocking with exit 2 has its stderr delivered to Claude as the reason to continue, while "stderr
# from a hook that exits 0 goes to the debug log only, never the transcript, and Claude never sees it". Exit 2
# is also preferred over the JSON `{"decision":"block"}` form on FAIL DIRECTION: a hook exiting 2 still blocks
# even when its stdout fails JSON schema validation, whereas a JSON-only decision that fails validation becomes
# a non-blocking error and the action proceeds. See hooks/MIGRATION.md §2 for the quotes.
#
# NOT the reason, though an earlier revision of this comment said so: hook registrations are NOT snapshotted at
# session start. The vendor documents the opposite — "direct edits to hooks in settings files are normally
# picked up automatically by the file watcher" — so a NEWLY registered hook usually does reach a live session.
# The design stands on guaranteed TIMING, not on unreachability.

HOOK_CONTRACT_VERSION_CACHE=""
hook_contract_version() { # -> the deployed contract version (cached; read several times per invocation)
    [[ -n "$HOOK_CONTRACT_VERSION_CACHE" ]] && { printf '%s' "$HOOK_CONTRACT_VERSION_CACHE"; return 0; }
    local file
    file="$(hook_project_dir)/.claude/hooks/CONTRACT_VERSION"
    if [[ -f "$file" ]]; then
        local first=""
        # See the note in hook_counter_read: no `||` clause, because a file with no trailing newline makes
        # `read` return non-zero AFTER assigning.
        read -r first < "$file" 2>/dev/null
        HOOK_CONTRACT_VERSION_CACHE="${first//[[:space:]]/}"
    fi
    HOOK_CONTRACT_VERSION_CACHE="${HOOK_CONTRACT_VERSION_CACHE:-unversioned}"
    printf '%s' "$HOOK_CONTRACT_VERSION_CACHE"
}

# The version is SANITISED into a filename-safe token. `tr -d '\r\n[:space:]'` removes whitespace but not path
# separators, so a version containing `/` yielded a nested, unwritable ack path and the run could NEVER
# acknowledge the contract. MEASURED with `2026.08/30-x`: the ack write failed
# `No such file or directory` and `hook_contract_acknowledged` returned false permanently — which, before the
# handshake was made non-preemptive, meant a repeating block-then-free-stop cycle forever.
hook_contract_ack_file() { # <run_dir> -> the path whose EXISTENCE means "this run has ingested the contract"
    local version
    version="$(hook_contract_version)"
    printf '%s/contract-ack-%s' "$1" "${version//[^A-Za-z0-9._-]/_}"
}

hook_contract_acknowledged() { # <run_dir> -> 0 when this run has already ingested the current contract
    local run_dir="$1"
    [[ -n "$run_dir" ]] || return 0          # nothing to migrate for a session with no run
    [[ -f "$(hook_contract_ack_file "$run_dir")" ]]
}

# ---------------------------------------------------------------------------------------------------------
# Rung 4 — bounded block counters, so a policy gate can never wedge a session.
# ---------------------------------------------------------------------------------------------------------
#
# The gates used to read the harness's `stop_hook_active` field and exit 0 the moment it was true. That made a
# POLICY gate block at most ONCE per continuation chain: the agent was nudged once and then free to stop on
# unproven work. These counters replace it. The vendor independently ends a turn after 8 consecutive blocks, so
# the default of 8 matches that ceiling rather than inventing one.

# Exposed as a FUNCTION taking the raw value as an ARGUMENT, so the validation is unit-testable without setting
# an environment variable anywhere (this project forbids that, and a control whose validation can only be
# exercised by breaking another rule does not get exercised).
#
# MEASURED on the raw `${VAR:-8}` form: `abc` aborted with `abc: unbound variable` and `1abc` with
# `value too great for base`, and the gates' EXIT trap converted both into exit 2 BEFORE the counter could
# advance — a permanent refusal with no cap to reach, from a single typo in the documented knob. `0` and a
# negative value made `at_cap` true on the FIRST block, so both gates allowed immediately while printing a
# message that read like a bounded give-up. A knob that silently disables the brake is worse than no knob.
hook_resolve_block_cap() { # <raw value> -> a validated integer in [1, 64]
    local raw="${1-}" cap=8
    [[ "$raw" =~ ^[0-9]+$ ]] && cap="$raw"
    (( cap < 1 )) && cap=1
    (( cap > 64 )) && cap=64
    printf '%s' "$cap"
}

HOOK_BLOCK_CAP="$(hook_resolve_block_cap "${CLAUDE_CODE_STOP_HOOK_BLOCK_CAP:-}")"

hook_counter_path() { # <base> <name> <session_id>
    printf '%s/%s/.stop-gate-counters/%s-%s.count' "$1" "$HOOK_ORCHESTRATOR_DIRNAME" "$2" "${3:0:8}"
}

# hook_counter_read <counter path> -> an integer, 0 when absent or unreadable.
#
# CLAMPED to four digits. A corrupted counter would otherwise overflow bash arithmetic in the caller's
# `(( blocks >= CAP ))`, and because the gates map any unexpected exit status to a refusal, that would wedge
# the session in a permanent block. Clamping high is the safe direction: an absurd value reads as "cap
# reached", which stands the gate down while SAYING the work is not done, rather than looping forever.
hook_counter_read() {
    local counter="$1" value="" raw=""
    if [[ -f "$counter" ]]; then
        # NO `|| raw=""` here. `read` returns NON-ZERO when it reaches EOF without hitting a delimiter, but it
        # has ALREADY assigned what it read. `hook_counter_bump` writes with `printf` and no trailing newline,
        # so every counter file hits that path — and clearing the variable on the non-zero return made every
        # count read as 0, which made `at_cap` unreachable and `hook_counter_bump`'s own read-back verification
        # fail. MEASURED: the gate stood down with ALLOW_COUNTER_UNWRITABLE on a perfectly writable counter.
        read -r raw < "$counter" 2>/dev/null
        value="${raw//[^0-9]/}"          # fork-free equivalent of `tr -dc '0-9'`
    fi
    value="${value:-0}"
    if (( ${#value} > 4 )); then
        printf '9999'
        return 0
    fi
    # `10#` forces base 10. Without it bash reads a leading-zero string as OCTAL, so a corrupted `08` or `09`
    # is not merely wrong but an arithmetic ERROR ("value too great for base") — which the gates' EXIT trap
    # would turn into a permanent refusal.
    printf '%s' "$(( 10#$value ))"
}

# hook_counter_bump <counter path> -> 0 when the increment LANDED, non-zero when it did not.
#
# The return value is the contract, and it is what makes the cap a guarantee instead of a hope. This function
# used to swallow every failure. MEASURED with a DIRECTORY occupying the counter path — equally a read-only
# checkout, an antivirus lock, or a Windows MAX_PATH overrun on a deep worktree — the counter stayed at 0
# forever, `at_cap` was never true, and the gate refused EVERY turn-end with no escape whatsoever (3 of 3
# refusals, counter never advancing). A caller that cannot count its blocks must not block.
hook_counter_bump() {
    local counter="$1" current
    current="$(hook_counter_read "$counter")"
    mkdir -p "$(dirname "$counter")" 2>/dev/null || return 1
    printf '%s' "$(( current + 1 ))" > "$counter" 2>/dev/null || return 1
    # Verify it actually landed. A successful write to a full disk can still yield an empty file.
    [[ "$(hook_counter_read "$counter")" == "$(( current + 1 ))" ]]
}

hook_counter_reset() { # <counter path>
    rm -f "$1" 2>/dev/null || true
    rm -f "$1.capped" 2>/dev/null || true
    rm -f "$1.fingerprint" 2>/dev/null || true
}

# The DURABLE give-up marker. `allow_at_cap` used to call `hook_counter_reset`, which made the cap a DUTY
# CYCLE rather than an escape: MEASURED over eleven consecutive Stop events, attempts 1-8 were refused,
# attempt 9 was released and reset the counter, and attempts 10-11 began refusing again. For a user trying to
# end a session that is 8 forced continuations, one exit, then 8 more — and the message "allowing the stop so
# the session cannot wedge" was false, because the session was wedged at 8-of-9.
hook_counter_mark_capped() { # <counter path>
    mkdir -p "$(dirname "$1")" 2>/dev/null || return 1
    printf 'capped\n' > "$1.capped" 2>/dev/null || return 1
}

hook_counter_is_capped() { # <counter path> -> 0 when this run has already given up on this gate
    [[ -f "$1.capped" ]]
}

# hook_counter_note_progress <counter path> <fingerprint> -> 0 when the fingerprint CHANGED (progress).
#
# The cap message used to claim "N consecutive blocks WITHOUT PROGRESS", and nothing measured progress: the
# counter was incremented on every block and reset only on an allow, so it counted consecutive BLOCKS. A run
# being refused while it advances every turn — exactly the behaviour the gate exists to produce — reached the
# cap identically to one spinning in place, and was then told it had made no progress. Either measure it or
# stop claiming it; this measures it, so a working run never reaches the cap.
hook_counter_note_progress() {
    local counter="$1" fingerprint="$2" previous=""
    # No `||` clause: `read` returns non-zero at EOF-without-newline but has already assigned (see
    # hook_counter_read). The fingerprint is written with `printf` and no newline, so this is that case.
    [[ -f "$counter.fingerprint" ]] && read -r previous < "$counter.fingerprint" 2>/dev/null
    if [[ "$previous" != "$fingerprint" ]]; then
        mkdir -p "$(dirname "$counter")" 2>/dev/null || return 1
        printf '%s' "$fingerprint" > "$counter.fingerprint" 2>/dev/null || true
        [[ -n "$previous" ]]        # a FIRST observation is not progress; a CHANGE is
        return $?
    fi
    return 1
}

# hook_decision_log <base> <hook name> <decision> <detail> — one line per invocation, to a FILE.
#
# Deliberately a file and not stderr. A Stop gate that printed on every ALLOW would retire the oracle that an
# ungated exit produces no message, and this project has a test asserting exactly that. But a gate that is
# silent on allow is also a gate whose permanent inertness is INVISIBLE — which is how the incident in this
# file's header went unnoticed for 189 sessions. A log file gives observability without touching the stderr
# contract.
hook_decision_log() {
    local base="$1" name="$2" decision="$3" detail="$4" log_dir log_file stamp
    log_dir="$base/$HOOK_ORCHESTRATOR_DIRNAME/.hook-decisions"
    mkdir -p "$log_dir" 2>/dev/null || return 0
    # ONE `date` call, not two: the day and the full stamp come from the same invocation.
    stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"
    log_file="$log_dir/${stamp%%T*}.log"
    [[ "$stamp" == unknown ]] && log_file="$log_dir/undated.log"
    printf '%s\t%s\t%s\t%s\n' "$stamp" "$name" "$decision" "$detail" >> "$log_file" 2>/dev/null || true
}

# ---------------------------------------------------------------------------------------------------------
# THE SELF-TEST MUST REMAIN THE LAST DEFINITION IN THIS FILE. See the header.
# ---------------------------------------------------------------------------------------------------------
hook_task_selftest() { return 0; }
