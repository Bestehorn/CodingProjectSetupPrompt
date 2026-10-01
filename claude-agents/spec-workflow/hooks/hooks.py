#!/usr/bin/env python
"""hooks.py — the ONE entry point for every Claude Code hook of this framework: one interpreter per event.

Usage (registered in .claude/settings.json in EXEC form, so no shell is involved):
    python .claude/hooks/hooks.py session-start     # SessionStart: register, scoped temp, re-inject
    python .claude/hooks/hooks.py pre-tool-use      # PreToolUse(Bash): env vars, push gate, claim, filing
    python .claude/hooks/hooks.py stop              # Stop: evidence gate, loop brake
    python .claude/hooks/hooks.py selftest          # prove the registered launch form executes and blocks

Why one dispatcher per event: the harness spawns one process per registered hook, and a Windows python start
costs the better part of a second — four PreToolUse gates as four processes cost four starts on EVERY shell
command. One process reads the payload once, resolves the run once, and runs every gate of the event.

Decision semantics (the harness contract: exit 0 allows, exit 2 blocks and shows stderr to the agent):
  * session-start: every gate runs; stdout is concatenated as context; exit is ALWAYS 0 (SessionStart cannot
    block, and exit 2 would show stderr to the user only).
  * pre-tool-use: gates run in order; the first block wins and ends the run; a gate that raises is skipped
    with a note on stderr (fail OPEN on an ordinary command — the push gate fails closed on a push itself).
  * stop: BOTH gates run so both decision-log lines are written; any block wins and every block message is
    delivered; a gate that raises REFUSES the stop (fail CLOSED), because a gate whose machinery is broken
    must not look like a gate that is satisfied.

THE LIBRARY IS IMPORTED DEFENSIVELY. A missing, truncated or syntax-broken `hooklib.py` would otherwise end this
process with exit 1 — a non-blocking error the harness proceeds past, i.e. every gate silently inert, which is
the exact failure class this rewrite exists to end. Without the library: a Stop REFUSES (fail closed); a
PreToolUse runs a library-free classifier that still bans `--no-verify` and still refuses a `git push` (the two
decisions that must never depend on state), and allows everything else; a SessionStart exits 0 silently.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

LIB_ERROR: Optional[str] = None
try:
    import hooklib as lib  # noqa: E402

    if not callable(getattr(lib, "selftest", None)) or not lib.selftest():
        raise ImportError(
            "hooklib.py is truncated: its last definition, selftest(), is missing"
        )
except Exception as _exc:  # noqa: BLE001 — any import failure takes the degraded paths below
    lib = None  # type: ignore[assignment]
    LIB_ERROR = f"{_exc.__class__.__name__}: {_exc}"

VERSION = "2026.10.01-python-1"
SHELL_TOOLS = {"Bash", "shell", "execute_bash", "execute_cmd", "executeBash"}
REINJECT_SOURCES = {
    "compact",
    "resume",
    "startup",
    "",
}  # an absent source (Kiro agentSpawn) re-injects

Gate = Tuple[str, Callable[[Any], Any]]


def _gates(event: str) -> List[Gate]:
    if event == "session-start":
        import gate_reinject
        import gate_scoped_temp
        import gate_session_register

        return [
            ("session-register", gate_session_register.run),
            ("scoped-temp-init", gate_scoped_temp.run),
            ("continuous-work-reinject", gate_reinject.run),
        ]
    if event == "pre-tool-use":
        import gate_claim
        import gate_filing
        import gate_no_env_vars
        import gate_tdd

        return [
            ("no-env-vars", gate_no_env_vars.run),
            ("spec-tdd-gate", gate_tdd.run),
            ("claim-before-worktree", gate_claim.run),
            ("issue-filing-gate", gate_filing.run),
        ]
    if event == "stop":
        import gate_issue_loop
        import gate_spec_stop

        return [
            ("spec-stop-gate", gate_spec_stop.run),
            ("issue-loop-gate", gate_issue_loop.run),
        ]
    raise SystemExit(
        f"hooks.py: unknown event '{event}' (expected session-start | pre-tool-use | stop | selftest)"
    )


def dispatch(
    event: str,
    payload_text: str,
    host: Any = None,
    environ: Optional[dict] = None,
    cwd: Optional[Path] = None,
    hooks_dir: Optional[Path] = None,
) -> Any:
    """Run every gate of `event` against the payload and combine their decisions into a hooklib.Decision.
    Never raises for a gate failure; requires the library (callers without it take `degraded`)."""
    if lib is None:
        raise ImportError(LIB_ERROR or "hooklib unavailable")
    payload = lib.Payload.parse(payload_text)
    ctx = lib.Context(
        payload,
        host=host or lib.CLAUDE,
        environ=environ,
        hooks_dir=hooks_dir or HERE,
        cwd=cwd,
    )
    gates = _gates(event)

    if (
        event == "pre-tool-use"
        and payload.tool_name
        and payload.tool_name not in SHELL_TOOLS
    ):
        return lib.allow()
    if event == "session-start" and payload.source not in REINJECT_SOURCES:
        gates = [g for g in gates if g[0] != "continuous-work-reinject"]

    stdout: List[str] = []
    stderr: List[str] = []
    blocked = False
    for name, gate in gates:
        try:
            decision = gate(ctx)
        except Exception:  # noqa: BLE001 — the policy per event is what matters, not the exception type
            detail = traceback.format_exc().strip().splitlines()[-1]
            if event == "stop":
                stderr.append(
                    f"{name}: ABORTED ({detail}) before reaching a decision — refusing the stop rather "
                    "than allowing it unchecked. Fix the hook or its library, then continue working.\n"
                )
                lib.decision_log(ctx.state_base, name, "ABORTED", detail)
                blocked = True
            else:
                stderr.append(f"{name}: skipped after an internal error ({detail}).\n")
                lib.decision_log(ctx.state_base, name, "ERROR", detail)
            continue
        if decision.stdout:
            stdout.append(decision.stdout)
        if decision.stderr:
            stderr.append(decision.stderr)
        if decision.blocked:
            blocked = True
            if event == "pre-tool-use":
                break
    if event == "session-start":
        blocked = False
    return lib.Decision(2 if blocked else 0, "\n".join(stdout), "".join(stderr))


# ---------------------------------------------------------------------------------------------------------
# The library-free fallback. Deliberately duplicates the two command predicates rather than importing them:
# this code must run when the library cannot be imported at all.
# ---------------------------------------------------------------------------------------------------------

_QUOTED_RE = re.compile(r'"[^"]*"|\'[^\']*\'')
_COMMIT_RE = re.compile(r"(^|[;&| ])git\s+([^;&|]*\s)?commit(\s|$)")
_PUSH_RE = re.compile(r"(^|[;&| ])git\s+([^;&|]*\s)?push(\s|$)")
_STASH_RE = re.compile(r"stash\s+push")
_BYPASS_RE = re.compile(r"(--no-verify|\s-n(\s|$))")


def degraded(event: str, payload_text: str) -> Tuple[int, str]:
    """-> (exit code, stderr) for an event when hooklib cannot be imported."""
    why = f"hooks.py: the hook library cannot be loaded ({LIB_ERROR}) — "
    if event == "stop":
        return (
            2,
            why
            + "refusing the stop rather than allowing it unchecked. Restore .claude/hooks/hooklib.py, then continue working.\n",
        )
    if event == "pre-tool-use":
        try:
            payload = json.loads(payload_text or "{}")
            command = (
                (payload.get("tool_input") or {}).get("command", "")
                if isinstance(payload, dict)
                else ""
            )
        except Exception:  # noqa: BLE001
            command = ""
        stripped = _QUOTED_RE.sub("", command if isinstance(command, str) else "")
        is_commit = bool(_COMMIT_RE.search(stripped))
        is_push = bool(_PUSH_RE.search(stripped)) and not _STASH_RE.search(stripped)
        if is_commit and _BYPASS_RE.search(stripped):
            return (
                2,
                "spec-tdd-gate: 'git commit --no-verify'/-n is forbidden. Fix the reported issue instead.\n",
            )
        if is_push and "--no-verify" in stripped:
            return (
                2,
                "spec-tdd-gate: 'git push --no-verify' is forbidden. Fix the cause instead of bypassing the hook.\n",
            )
        if is_push:
            return (
                2,
                why
                + "refusing the PUSH rather than allowing it unverified. Restore .claude/hooks/hooklib.py, then push.\n",
            )
        return 0, ""
    # session-start: never break startup. The note goes to stderr, which exit 0 routes to the debug log — the
    # agent sees nothing, but a maintainer reading the log sees WHY the gates are not judging this session.
    return (
        0,
        why
        + "no gate ran at SessionStart; the session is unregistered and ungated until the library is restored.\n",
    )


def main(argv: List[str]) -> int:
    # The harness reads UTF-8. A piped Windows python writes the console code page (cp1252) by default, which
    # turns every em dash in a refusal into U+FFFD on the agent's side. Both streams are re-encoded.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    if len(argv) < 2:
        sys.stderr.write(__doc__ or "")
        return 2
    event = argv[1]
    if event == "selftest":
        return selftest()
    if event == "version":
        sys.stdout.write(VERSION + "\n")
        return 0
    payload_text = sys.stdin.read() if not sys.stdin.isatty() else ""
    if lib is None:
        if event not in ("session-start", "pre-tool-use", "stop"):
            sys.stderr.write(f"hooks.py: unknown event '{event}'\n")
            return 2
        code, message = degraded(event, payload_text)
        if message:
            sys.stderr.write(message)
        return code
    decision = dispatch(event, payload_text)
    if decision.stdout:
        sys.stdout.write(decision.stdout)
    if decision.stderr:
        sys.stderr.write(decision.stderr)
    return decision.exit_code


# ---------------------------------------------------------------------------------------------------------
# The self-test: "a registered hook actually executes" must be checkable, because a hook that cannot start is
# a non-blocking error the harness proceeds past — indistinguishable from an allow, except here.
# ---------------------------------------------------------------------------------------------------------


def selftest() -> int:
    """Spawn this dispatcher exactly as the harness does (the `python` on PATH, no shell) against a scratch
    project, and assert: SessionStart injects the contract and logs a decision; PreToolUse blocks a bypass and
    reads a quoted command; Stop refuses a registered run that records unfinished work. Exit 1 on any FAIL."""
    python = shutil.which("python") or shutil.which("python3")
    results: List[Tuple[str, bool, str]] = []
    if lib is None:
        results.append(("hooklib.py imports", False, LIB_ERROR or "unknown"))
        return _report(results)
    results.append(("hooklib.py imports", True, str(HERE / "hooklib.py")))
    if not python:
        results.append(
            (
                "`python` resolves on PATH",
                False,
                "no python on PATH — exec-form registration cannot start",
            )
        )
        return _report(results)
    results.append(("`python` resolves on PATH", True, python))
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        (project / ".claude" / "hooks").mkdir(parents=True)
        sid = "selftest-1111-2222-3333-444455556666"

        def spawn(event: str, payload: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                [python, str(HERE / "hooks.py"), event],
                input=payload,
                capture_output=True,
                text=True,
                cwd=str(project),
                timeout=60,
                check=False,
            )

        start = spawn(
            "session-start",
            f'{{"session_id":"{sid}","cwd":"{project.as_posix()}","source":"startup",'
            '"hook_event_name":"SessionStart"}',
        )
        results.append(
            (
                "SessionStart exits 0",
                start.returncode == 0,
                f"exit {start.returncode} {start.stderr[:200]}",
            )
        )
        results.append(
            (
                "SessionStart injects the contract",
                "Continuous work is in force" in start.stdout,
                start.stdout[:120],
            )
        )
        logs = list(
            (
                project
                / ".claude"
                / "agent-state"
                / lib.ORCHESTRATOR_DIRNAME
                / ".hook-decisions"
            ).glob("*.log")
        )
        results.append(
            ("SessionStart writes a decision-log line", bool(logs), str(logs))
        )

        pre = spawn(
            "pre-tool-use",
            '{"tool_name":"Bash","tool_input":{"command":"git commit --no-verify -m x"}}',
        )
        results.append(
            (
                "PreToolUse blocks `git commit --no-verify`",
                pre.returncode == 2 and "forbidden" in pre.stderr,
                f"exit {pre.returncode}",
            )
        )
        quoted = spawn(
            "pre-tool-use",
            '{"tool_name":"Bash","tool_input":{"command":"cd \\"D:/Code Workspace/x\\" '
            '&& export AWS_PROFILE=probe && echo ok"}}',
        )
        results.append(
            (
                "PreToolUse reads a command containing quotes",
                quoted.returncode == 2,
                f"exit {quoted.returncode}",
            )
        )

        run_dir = (
            project
            / ".claude"
            / "agent-state"
            / lib.ORCHESTRATOR_DIRNAME
            / "runs"
            / sid[:8]
        )
        (run_dir / lib.RESUME_FILENAME).write_text(
            f"SESSION_ID: {sid}\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 999\nAWAITING_USER: none\n",
            encoding="utf-8",
        )
        stop = spawn(
            "stop",
            f'{{"session_id":"{sid}","cwd":"{project.as_posix()}","hook_event_name":"Stop"}}',
        )
        results.append(
            (
                "Stop refuses a run recording unfinished work",
                stop.returncode == 2 and "UNFINISHED" in stop.stderr,
                f"exit {stop.returncode} {stop.stderr[:120]}",
            )
        )
    return _report(results)


def _report(results: List[Tuple[str, bool, str]]) -> int:
    failed = 0
    for label, ok, detail in results:
        failed += 0 if ok else 1
        sys.stdout.write(
            f"  {'PASS' if ok else 'FAIL'}  {label}"
            + ("" if ok else f"\n        {detail}")
            + "\n"
        )
    sys.stdout.write(
        f"hooks selftest ({VERSION}): {len(results) - failed} passed, {failed} failed\n"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
