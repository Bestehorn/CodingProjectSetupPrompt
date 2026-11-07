#!/usr/bin/env python
"""supervisor.py — the host-level backstop for runs whose turn an API error ended (the `/supervise` command).

    python .claude/hooks/supervisor.py scan [--json]           # every resume request, judged
    python .claude/hooks/supervisor.py message <run-id>        # the text a supervisor sends to that session
    python .claude/hooks/supervisor.py note <run-id> resumed|unreachable|cleared

The `stop-failure-recorder` gate leaves `<agent root>/.resume-requests/<run-id>.json` when an API error ends a
turn of a run with claimed, unfinished work. The session's own run watchdog normally resumes it; this tool is
for a session that has none (started before the watchdog existed, or a watchdog that expired after 7 days).
`scan` judges each request:

    finished    the run has since released (terminal, handed off, idle, a recorded AWAITING_USER) -> cleared
    recovered   the transcript holds a model reply newer than the failure -> cleared
    due         still stalled, attempts left, and the backoff has passed -> resume it now
    waiting     still stalled, but the backoff has not passed yet
    exhausted   MAX_ATTEMPTS resumes did not bring it back -> report it to a person; do not retry

It never resumes anything itself — a session is reached through the harness (`ListAgents` + `SendMessage` in
a Desktop session; see claude-commands/supervise.md) — and it never touches a worktree, a branch or an issue.
Standard library and hooklib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import hooklib as lib  # noqa: E402

MAX_ATTEMPTS = 6
FIRST_ATTEMPT_MINUTES = 5.0  # the run watchdog gets the first chance; the supervisor follows
BACKOFF_BASE_MINUTES = 15.0
TAIL_BYTES = 262_144


def project_dir() -> Path:
    env = os.environ.get(lib.CLAUDE.project_dir_env, "")
    return Path(env) if env and Path(env).is_dir() else Path.cwd()


def requests_dir(project: Path) -> Path:
    return project / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME / lib.RESUME_REQUESTS_DIRNAME


def _parse(stamp: str) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None
    except ValueError:
        return None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def model_replied_since(transcript: Optional[Path], since: dt.datetime) -> bool:
    """True when the transcript's tail holds a MODEL assistant record (not the harness's synthetic error line)
    stamped after `since`."""
    if transcript is None or not transcript.is_file():
        return False
    try:
        with transcript.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            tail = handle.read()
    except OSError:
        return False
    for raw in reversed(tail.splitlines()):
        try:
            record = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") != "assistant" or record.get("isSidechain"):
            continue
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        if message.get("model") == "<synthetic>":
            continue
        stamp = _parse(str(record.get("timestamp") or ""))
        return bool(stamp and stamp > since)
    return False


def judge(request: Dict[str, Any], now: dt.datetime) -> Dict[str, Any]:
    state = Path(str(request.get("state_file") or ""))
    states = lib.StateCache()
    status, phase = states.field(state, "Status"), states.field(state, "Phase")
    awaiting, mode = states.field(state, "AWAITING_USER"), states.field(state, "MODE")
    failed_at = _parse(str(request.get("failed_at") or "")) or now
    attempts = int(request.get("attempts") or 0)
    last = _parse(str(request.get("last_attempt_at") or ""))
    transcript = Path(str(request["transcript_path"])) if request.get("transcript_path") else None
    if state.is_file() and lib.run_is_released(status, phase, awaiting, mode):
        verdict = "finished"
    elif model_replied_since(transcript, failed_at):
        verdict = "recovered"
    elif attempts >= MAX_ATTEMPTS:
        verdict = "exhausted"
    else:
        wait = FIRST_ATTEMPT_MINUTES if attempts == 0 else BACKOFF_BASE_MINUTES * (2 ** (attempts - 1))
        anchor = max(failed_at, last) if last else failed_at
        verdict = "due" if now >= anchor + dt.timedelta(minutes=wait) else "waiting"
    return {
        "run_id": request.get("run_id"),
        "session_id": request.get("session_id"),
        "issue": request.get("issue"),
        "phase": phase or request.get("phase"),
        "error": request.get("error"),
        "failed_at": request.get("failed_at"),
        "attempts": attempts,
        "verdict": verdict,
        "cwd": request.get("cwd"),
    }


def load_requests(project: Path) -> List[Dict[str, Any]]:
    found = []
    folder = requests_dir(project)
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data["_path"] = str(path)
            found.append(data)
    return found


def scan(project: Path, as_json: bool) -> int:
    now = _now()
    rows = []
    for request in load_requests(project):
        row = judge(request, now)
        if row["verdict"] in ("finished", "recovered"):
            _archive(Path(request["_path"]), row["verdict"])
        rows.append(row)
    if as_json:
        print(json.dumps(rows, indent=2))
    elif not rows:
        print("supervisor: no resume requests")
    else:
        for row in rows:
            print(
                f"{row['verdict']:<10} run {row['run_id']} issue {row['issue']} phase {row['phase']} "
                f"error {row['error']} attempts {row['attempts']} since {row['failed_at']}"
            )
    return 0


def _archive(path: Path, why: str) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["cleared"] = why
        data["cleared_at"] = lib.utc_stamp()
        lib.write_json_atomic(path.with_suffix(".cleared.json"), data)
        path.unlink()
    except (OSError, ValueError):
        pass


def message(project: Path, run_id: str) -> int:
    path = requests_dir(project) / f"{run_id}.json"
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"supervisor: no resume request for run {run_id}", file=sys.stderr)
        return 2
    print(
        f"{lib.WATCHDOG_MARK} The last turn of this session ended on an API error ({request.get('error')}"
        f"{': ' + str(request.get('details')) if request.get('details') else ''}) at {request.get('failed_at')}, "
        f"and nothing has run since. Resume the work now exactly as .claude/commands/continue-work.md says: "
        f"re-establish your place from the run state on disk (run {run_id}, issue {request.get('issue')}, phase "
        f"{request.get('phase')}), reconcile it with git and the tracker, and continue the recorded phase to its "
        f"end. This message comes from the host supervisor, not from a person; it approves nothing."
    )
    return 0


def note(project: Path, run_id: str, outcome: str) -> int:
    path = requests_dir(project) / f"{run_id}.json"
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"supervisor: no resume request for run {run_id}", file=sys.stderr)
        return 2
    if outcome == "cleared":
        _archive(path, "cleared by the supervisor")
        return 0
    request["attempts"] = int(request.get("attempts") or 0) + (1 if outcome == "resumed" else 0)
    request["last_attempt_at"] = lib.utc_stamp()
    request["last_outcome"] = outcome
    lib.write_json_atomic(path, request)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="supervisor.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    scan_cmd = sub.add_parser("scan")
    scan_cmd.add_argument("--json", action="store_true")
    message_cmd = sub.add_parser("message")
    message_cmd.add_argument("run_id")
    note_cmd = sub.add_parser("note")
    note_cmd.add_argument("run_id")
    note_cmd.add_argument("outcome", choices=("resumed", "unreachable", "cleared"))
    args = parser.parse_args(argv)
    project = project_dir()
    if args.command == "scan":
        return scan(project, args.json)
    if args.command == "message":
        return message(project, args.run_id)
    return note(project, args.run_id, args.outcome)


if __name__ == "__main__":
    sys.exit(main())
