#!/usr/bin/env bash
# session-register.sh — SessionStart hook. Establishes this session's run identity ON DISK.
#
# Wire as a SessionStart hook in .claude/settings.json. Claude Code passes session_id, cwd, source and
# hook_event_name on stdin.
#
# WHAT CHANGED, AND WHY IT IS THE HIGHEST-VALUE FIX IN THIS DIRECTORY
#
# This hook used to write `state_dir: "runs/<first-8-of-session-id>/"` into registry.json and stop there. It
# never created that directory, and it never created a state file in it. Both Stop gates resolve their state
# file from the registry and then `exit 0` when it is absent — so until an agent happened to create exactly
# that path, every gate was a silent no-op. Measured consequence: in one clone, across 189 registered
# sessions, neither Stop gate had EVER blocked a turn-end, and an agent explicitly instructed never to stop
# without a proven reason ended four turns unopposed.
#
# The agent could not reasonably close that gap either. Its command said "derive RUN_ID" from the registry;
# it produced a readable label (`run-issue574-...`) and wrote state there. Nothing told it that the gates key
# on a DIFFERENT string, and nothing detected the divergence.
#
# So this hook now SEEDS the state, rather than describing where state ought to go:
#   * it creates `runs/<run-id>/` and writes `resume_state.md` + `workflow_state.md` if absent;
#   * the seed records `SESSION_ID`, which lets `hook_find_run_dir_by_session` recover a run even if an agent
#     later writes state under a different directory name;
#   * it PRE-ACKNOWLEDGES the current contract version, because a session that started under this hook
#     started under the current contract by construction and must not be blocked to be told so;
#   * the registry upsert has a python rung, because `jq` is absent on the development host and the previous
#     jq-only upsert therefore wrote NO ENTRY AT ALL there.
#
# It remains non-blocking and best-effort: SessionStart hooks cannot block, and a registry write must never
# break session startup. It does NOT decide which run owns which issue — that is the agent's locking job. It
# only makes identity resolvable.
#
# No environment variable carries the session id; identity flows via the stdin session_id and this on-disk
# state, consistent with the no-environment-vars rule.
set -u

input="$(cat)"

# shellcheck source=./hook-state-lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/hook-state-lib.sh" 2>/dev/null || exit 0
_HOOK_JSON_INPUT="$input"
# Fail SAFE rather than fail closed: this is a SessionStart hook, it cannot block, and a half-sourced library
# must not break startup. The gates are where a missing library must fail closed.
command -v hook_task_selftest >/dev/null 2>&1 || exit 0
hook_task_selftest || exit 0

sid="$(hook_json_string session_id)"
[[ -z "$sid" ]] && exit 0   # nothing to record; do not disturb startup
cwd="$(hook_json_string cwd)"
source_kind="$(hook_json_string source)"

base="$(hook_state_base)"
orch="$base/$HOOK_ORCHESTRATOR_DIRNAME"
mkdir -p "$orch" 2>/dev/null || exit 0

registry="$orch/registry.json"
[[ -f "$registry" ]] || printf '{}' > "$registry" 2>/dev/null || exit 0

run_id="${sid:0:8}"
state_dir="runs/$run_id"
run_dir="$orch/$state_dir"
stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"

# ---------------------------------------------------------------------------------------------------------
# 1. SEED the run's state FIRST. This ordering is load-bearing — see the header note on ordering.
# ---------------------------------------------------------------------------------------------------------
mkdir -p "$run_dir" 2>/dev/null || {
    hook_decision_log "$base" "session-register" "SEED_FAILED" "run=$run_id could not create $run_dir"
    exit 0
}

# `resume_state.md` — what issue-loop-gate.sh reads. Every field it branches on is present from turn one, so
# the gate evaluates real values instead of exiting on a missing file.
if [[ ! -f "$run_dir/$HOOK_RESUME_FILENAME" ]]; then
    cat > "$run_dir/$HOOK_RESUME_FILENAME" <<SEED 2>/dev/null || true
# Resume state — run $run_id

Seeded by \`session-register.sh\` at $stamp (SessionStart, source: ${source_kind:-unknown}).

**Read this before editing.** The hooks read the LAST occurrence of each \`Name: value\` line below, so
CORRECT A VALUE BY APPENDING A NEW BLOCK AT THE END OF THIS FILE — never by editing the block below and never
by prepending. A bold \`**Name:** value\` spelling is read by NO hook at all. Any prose summary you add for a
human reader must be PROSE, with no \`Name: value\` lines, so it cannot be mistaken for the authority.

\`SESSION_ID\` is load-bearing: it is how a hook recovers this run if state is ever written under a
differently-named directory. Do not remove it and do not change it.

SESSION_ID: $sid
RUN_ID: $run_id
STATE_DIR: $state_dir
MODE: unset
Status: NOT_STARTED
Phase: NOT_STARTED
CURRENT_ISSUE: none
BRANCH: none
WORKTREE: none
PR: none
WORKABLE_ISSUES_REMAIN: unknown
AWAITING_USER: none
SEED
fi

# `workflow_state.md` — what spec-stop-gate.sh and spec-tdd-gate.sh read.
if [[ ! -f "$run_dir/$HOOK_STATE_FILENAME" ]]; then
    cat > "$run_dir/$HOOK_STATE_FILENAME" <<SEED 2>/dev/null || true
# Workflow state — run $run_id

Seeded by \`session-register.sh\` at $stamp. Append corrections at the END; see \`resume_state.md\`.

SESSION_ID: $sid
RUN_ID: $run_id
CURRENT_SPEC:
Phase: NOT_STARTED
Status: NOT_STARTED
CURRENT_TASK: none
SEED
fi


# The registry is upserted ONLY if the state file it will point at actually exists. Writing the entry first
# and seeding second MANUFACTURED the `BROKEN` identity both Stop gates fail closed on: MEASURED with
# `$orch/runs` occupied by a regular file (equally a full disk, a permissions denial, or a Windows MAX_PATH
# overrun on a deep worktree), this hook exited 0, the registry held a complete entry naming
# `runs/<run-id>/`, no state file existed, and BOTH gates then refused every turn-end — with no stderr and no
# decision-log line to explain why. Inertness is the correct failure mode here and a wedge is not, so on a
# seeding failure the registry is left alone and the session resolves UNREGISTERED.
if [[ ! -f "$run_dir/$HOOK_RESUME_FILENAME" ]]; then
    hook_decision_log "$base" "session-register" "SEED_FAILED" "run=$run_id state absent after seeding; registry left untouched"
    exit 0
fi

# ---------------------------------------------------------------------------------------------------------
# 2. Upsert the registry entry, ONLY once the state it points at exists. jq, then python.
# ---------------------------------------------------------------------------------------------------------
upserted=0
if command -v jq >/dev/null 2>&1; then
    tmp="$registry.tmp.$$"
    if jq --arg sid "$sid" --arg rid "$run_id" --arg sd "$state_dir/" --arg cwd "$cwd" --arg ts "$stamp" '
        .[$sid] = ((.[$sid] // {}) + {
            session_id: $sid, run_id: $rid, cwd: $cwd, state_dir: $sd,
            status: ((.[$sid].status) // "starting"),
            started_at: ((.[$sid].started_at) // $ts),
            last_heartbeat: $ts })' "$registry" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$registry" 2>/dev/null && upserted=1
    fi
    rm -f "$tmp" 2>/dev/null || true
fi
if (( upserted == 0 )) && interpreter="$(_hook_python_bin)"; then
    "$interpreter" - "$registry" "$sid" "$run_id" "$state_dir/" "$cwd" "$stamp" <<'PY' 2>/dev/null || true
import json, os, sys, tempfile

registry_path, sid, run_id, state_dir, cwd, stamp = sys.argv[1:7]
try:
    with open(registry_path, encoding="utf-8") as handle:
        registry = json.load(handle)
    if not isinstance(registry, dict):
        registry = {}
except Exception:
    registry = {}

entry = registry.get(sid) if isinstance(registry.get(sid), dict) else {}
entry.update(
    {
        "session_id": sid,
        "run_id": run_id,
        "cwd": cwd,
        "state_dir": state_dir,
        "status": entry.get("status") or "starting",
        "started_at": entry.get("started_at") or stamp,
        "last_heartbeat": stamp,
    }
)
registry[sid] = entry

directory = os.path.dirname(os.path.abspath(registry_path)) or "."
handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False)
try:
    json.dump(registry, handle, indent=4, sort_keys=True)
    handle.write("\n")
    handle.close()
    os.replace(handle.name, registry_path)
except Exception:
    handle.close()
    try:
        os.unlink(handle.name)
    except OSError:
        pass
PY
fi

# ---------------------------------------------------------------------------------------------------------
# 3. Pre-acknowledge the current contract.
# ---------------------------------------------------------------------------------------------------------
# A session whose state this hook just seeded is, by construction, running under the contract version shipped
# alongside this hook — the rules were in its context at startup. Blocking it once to "deliver" a contract it
# already has would be a gratuitous interruption. The handshake in issue-loop-gate.sh therefore fires only
# for runs that PREDATE the deployment, which is exactly the migration case it exists for.
ack="$(hook_contract_ack_file "$run_dir")"
[[ -f "$ack" ]] || printf 'acknowledged at %s by session-register.sh (seeded under this contract)\n' \
    "$stamp" > "$ack" 2>/dev/null || true

hook_decision_log "$base" "session-register" "SEEDED" "run=$run_id source=${source_kind:-unknown}"

exit 0
