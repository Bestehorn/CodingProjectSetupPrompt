"""session-register — SessionStart (Kiro: agentSpawn). Establishes this session's run identity ON DISK.

It SEEDS the run's state rather than describing where state ought to go: `runs/<run-id>/` with a
resume_state.md and a workflow_state.md carrying every field the gates branch on, then the registry entry —
ONLY once the state it points at exists (writing the entry first manufactured the BROKEN identity both Stop
gates fail closed on). It pre-acknowledges the current contract, because a session seeded under this hook
started under the current contract by construction. Non-blocking and best-effort: it must never break startup.
"""

from __future__ import annotations

import json
import os
import time

import hooklib as lib

HOOK = "session-register"
EVENT = "session-start"  # the dispatcher runs this gate on this event
ORDER = 10  # framework gates 10..90; a project gate takes >100 (or <10 to run first)


def run(ctx: lib.Context) -> lib.Decision:  # noqa: C901 — seed, register, acknowledge, in order
    sid = ctx.session_id
    if not sid:
        return lib.allow()
    base = ctx.state_base
    orch = base / lib.ORCHESTRATOR_DIRNAME
    try:
        orch.mkdir(parents=True, exist_ok=True)
    except OSError:
        return lib.allow()
    registry = orch / "registry.json"
    if not registry.is_file():
        try:
            registry.write_text("{}", encoding="utf-8")
        except OSError:
            return lib.allow()

    run_id = sid[:8]
    state_dir = f"runs/{run_id}"
    run_dir = orch / state_dir
    stamp = lib.utc_stamp()
    source = ctx.payload.source or "unknown"

    # 1. SEED the run's state FIRST.
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        ctx.log(HOOK, "SEED_FAILED", f"run={run_id} could not create {run_dir}")
        return lib.allow()
    resume = run_dir / lib.RESUME_FILENAME
    if not resume.is_file():
        _write(
            resume,
            f"""# Resume state — run {run_id}

Seeded by `{HOOK}` at {stamp} (SessionStart, source: {source}).

**Read this before editing.** The hooks read the LAST occurrence of each `Name: value` line below, so
CORRECT A VALUE BY APPENDING A NEW BLOCK AT THE END OF THIS FILE — never by editing the block below and never
by prepending. A bold `**Name:** value` spelling is read by NO hook at all. Any prose summary you add for a
human reader must be PROSE, with no `Name: value` lines, so it cannot be mistaken for the authority.

`SESSION_ID` is load-bearing: it is how a hook recovers this run if state is ever written under a
differently-named directory. Do not remove it and do not change it.

SESSION_ID: {sid}
RUN_ID: {run_id}
STATE_DIR: {state_dir}
MODE: unset
Status: NOT_STARTED
Phase: NOT_STARTED
CURRENT_ISSUE: none
BRANCH: none
WORKTREE: none
PR: none
WORKABLE_ISSUES_REMAIN: unknown
AWAITING_USER: none
""",
        )
    workflow = run_dir / lib.STATE_FILENAME
    if not workflow.is_file():
        _write(
            workflow,
            f"""# Workflow state — run {run_id}

Seeded by `{HOOK}` at {stamp}. Append corrections at the END; see `resume_state.md`.

SESSION_ID: {sid}
RUN_ID: {run_id}
CURRENT_SPEC:
Phase: NOT_STARTED
Status: NOT_STARTED
CURRENT_TASK: none
""",
        )
    if not resume.is_file():
        ctx.log(
            HOOK,
            "SEED_FAILED",
            f"run={run_id} state absent after seeding; registry left untouched",
        )
        return lib.allow()

    # 2. Upsert the registry entry, ONLY once the state it points at exists — under a lock, because several
    #    sessions start concurrently in one clone and an unlocked read-modify-write drops a sibling's entry.
    #    A registry that does not PARSE is never overwritten: rewriting it from this one entry would delete
    #    every concurrent session's entry (measured). The run still resolves through the `runs/<sid8>/` rung.
    upserted = _upsert_registry(registry, sid, run_id, state_dir, ctx.payload.cwd, stamp)
    if upserted is None:
        ctx.log(HOOK, "REGISTRY_UNREADABLE", f"run={run_id} registry left untouched; resolution via runs/{run_id}/")
    elif not upserted:
        ctx.log(HOOK, "REGISTRY_LOCKED", f"run={run_id} could not take {registry}.lock; resolution via runs/{run_id}/")

    # 3. Pre-acknowledge the current contract.
    ack = lib.contract_ack_file(run_dir, ctx.contract_version)
    if not ack.is_file():
        _write(ack, f"acknowledged at {stamp} by {HOOK} (seeded under this contract)\n")

    ctx.log(HOOK, "SEEDED", f"run={run_id} source={source}")
    return lib.allow()


def _write(path, text: str) -> None:
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass


LOCK_ATTEMPTS = 40
LOCK_INTERVAL_SECONDS = 0.05
LOCK_STALE_SECONDS = 10.0


def _upsert_registry(registry, sid: str, run_id: str, state_dir: str, cwd: str, stamp: str):
    """-> True when written, False when the lock could not be taken, None when the registry does not parse."""
    lock = registry.parent / "registry.lock"
    taken = False
    for _ in range(LOCK_ATTEMPTS):
        try:
            os.mkdir(lock)  # atomic create-or-fail on every filesystem, NTFS included
            taken = True
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
                    os.rmdir(lock)  # a crashed sibling left it; the next attempt takes it
                    continue
            except OSError:
                pass
            time.sleep(LOCK_INTERVAL_SECONDS)
        except OSError:
            return False
    if not taken:
        return False
    try:
        raw = lib.read_text(registry)
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        entry = data.get(sid) if isinstance(data.get(sid), dict) else {}
        entry.update(
            {
                "session_id": sid,
                "run_id": run_id,
                "cwd": cwd,
                "state_dir": state_dir + "/",
                "status": entry.get("status") or "starting",
                "started_at": entry.get("started_at") or stamp,
                "last_heartbeat": stamp,
            }
        )
        data[sid] = entry
        return lib.write_json_atomic(registry, data)
    finally:
        try:
            os.rmdir(lock)
        except OSError:
            pass
