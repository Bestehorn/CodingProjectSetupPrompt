"""continuous-work-reinject on a RESUMED session: the previous process's background tasks are gone and the
harness runs no turn for them (measured 2026-10-10: 82 of 82 stopped tasks), so the first turn after a resume
must be told to re-issue its waits in the foreground rather than sit until a notification that never comes."""

from __future__ import annotations

import json
from pathlib import Path

import gate_reinject
import hooklib as lib

HOOKS = Path(__file__).resolve().parent.parent


def _run(arena: Path, source: str) -> str:
    (arena / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME).mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"cwd": arena.as_posix(), "source": source, "hook_event_name": "SessionStart"})
    ctx = lib.Context(lib.Payload.parse(payload), environ={}, hooks_dir=HOOKS, cwd=arena)
    return gate_reinject.run(ctx).stdout


def test_resume_names_the_lost_background_tasks_and_the_foreground_wait(tmp_path: Path) -> None:
    out = _run(tmp_path / "arena", "resume")
    assert "RESUMED" in out and "previous process" in out
    assert "`stopped`" in out and "FOREGROUND" in out and "--timeout-seconds 540" in out
    assert "Do not summarize" in out


def test_startup_and_compact_keep_their_own_wording(tmp_path: Path) -> None:
    startup = _run(tmp_path / "a", "startup")
    compact = _run(tmp_path / "b", "compact")
    # The revision notice mentions the resume case too, so the RESUME sentence itself is what must be absent.
    assert "RESUMED in a new process" not in startup and "Session start (source: startup)" in startup
    assert "RESUMED in a new process" not in compact and "COMPACTED" in compact
