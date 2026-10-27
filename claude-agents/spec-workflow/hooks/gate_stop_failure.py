"""stop-failure-recorder — StopFailure: record a turn that an API error ended, so the work is resumed, not lost.

Claude Code fires StopFailure INSTEAD of Stop when a turn ends on an API error (authentication_failed,
server_error, rate_limit, invalid_request, ...). The event has no decision control — no hook can continue the
turn — so this gate RECORDS: the failure into the run's `stop_failure.json` (the last 20, with the error, its
details and the rendered message) and, when the run has claimed work that it has not released, a resume
request under `<agent root>/.resume-requests/<run-id>.json` for `.claude/hooks/supervisor.py`. The session's
own run watchdog (a session-only CronCreate job, continuous-work.md) fires once the session is idle and
resumes the recorded work; the supervisor is the host-level backstop for a session without one.

MEASURED 2026-10-25 (project-docs/wait-time-analysis-2026-10-25.md): 17 turns ended on 401/403 authentication
errors or a provider 400 idled a median 7.5 h each, 95 h in all, until a person typed /continue-work.

Always exits 0 and prints nothing (StopFailure output is ignored); logs its decision like every gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import hooklib as lib

HOOK = "stop-failure-recorder"
EVENT = "stop-failure"  # the dispatcher runs this gate on this event
ORDER = 10  # framework gates 10..90; a project gate takes >100 (or <10 to run first)
HISTORY = 20
#: Errors no retry can cure; recorded, never queued for a resume.
NOT_RESUMABLE = {"billing_error", "account_on_hold", "oauth_org_not_allowed", "model_not_found"}


def _load(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(lib.read_text(path) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def run(ctx: lib.Context) -> lib.Decision:
    sid = ctx.session_id
    error = ctx.payload.string("error") or "unknown"
    details = ctx.payload.string("error_details")[:300]
    message = ctx.payload.string("last_assistant_message")[:300]
    if not sid:
        ctx.log(HOOK, "NO_SESSION", f"error={error}")
        return lib.allow()
    verdict, run_dir = ctx.resolve()
    if verdict != lib.OWNED or run_dir is None:
        ctx.log(HOOK, "UNREGISTERED", f"session={sid[:8]} error={error}")
        return lib.allow()
    stamp = lib.utc_stamp()
    record_path = run_dir / "stop_failure.json"
    record = _load(record_path)
    failures: List[Dict[str, Any]] = [f for f in record.get("failures", []) if isinstance(f, dict)]
    failures.append({"at": stamp, "error": error, "details": details, "message": message})
    record = {"session_id": sid, "failures": failures[-HISTORY:], "last_failure_at": stamp}
    lib.write_json_atomic(record_path, record)

    state = run_dir / lib.RESUME_FILENAME
    status = ctx.field(state, "Status")
    phase = ctx.field(state, "Phase")
    awaiting = ctx.field(state, "AWAITING_USER")
    mode = ctx.field(state, "MODE")
    issue = ctx.field(state, "CURRENT_ISSUE")
    claimed = not lib.is_placeholder(issue) or (
        not lib.is_placeholder(mode) and bool(lib.CLAIMING_MODE_RE.match(mode.replace("-", "_")))
    )
    released = lib.run_is_released(status, phase, awaiting, mode)
    if error in NOT_RESUMABLE or not claimed or released:
        why = "not resumable" if error in NOT_RESUMABLE else ("no claimed work" if not claimed else "run released")
        ctx.log(HOOK, "RECORDED", f"run={run_dir.name} error={error} ({why})")
        return lib.allow()
    requests = ctx.state_base / lib.ORCHESTRATOR_DIRNAME / lib.RESUME_REQUESTS_DIRNAME
    request_path = requests / f"{run_dir.name}.json"
    request = _load(request_path)
    request.update(
        {
            "session_id": sid,
            "run_id": run_dir.name,
            "state_file": str(state),
            "cwd": ctx.payload.cwd or str(ctx.project_dir),
            "transcript_path": str(ctx.payload.transcript_path or ""),
            "issue": issue,
            "phase": phase,
            "error": error,
            "details": details,
            "failed_at": stamp,
            "attempts": int(request.get("attempts") or 0),
            "last_attempt_at": request.get("last_attempt_at") or "",
        }
    )
    lib.write_json_atomic(request_path, request)
    ctx.log(HOOK, "RESUME_REQUESTED", f"run={run_dir.name} issue={issue} phase={phase} error={error}")
    return lib.allow()
