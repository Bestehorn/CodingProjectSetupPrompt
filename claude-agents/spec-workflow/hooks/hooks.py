#!/usr/bin/env python
"""hooks.py — the ONE entry point for every Claude Code hook of this framework: one interpreter per event.

Usage:
    python .claude/hooks/hooks.py session-start     # SessionStart: register, scoped temp, re-inject
    python .claude/hooks/hooks.py pre-tool-use      # PreToolUse: env vars, push gate, claim, filing (+ project gates)
    python .claude/hooks/hooks.py stop              # Stop: evidence gate, loop brake
    python .claude/hooks/hooks.py selftest          # prove the registered launch form executes and blocks
    python .claude/hooks/hooks.py registration      # print the settings.json hooks block to install

HOW IT IS REGISTERED (exec form, `python`, through the LAUNCHER):
    { "type": "command", "command": "python",
      "args": ["-X", "utf8", "-c", "<LAUNCHER>", "pre-tool-use"], "timeout": 30 }
where <LAUNCHER> is the one-line program `LAUNCHER` below (print the exact block with `registration`). Three
things the launcher buys, each from a measured incident:
  * `-X utf8`: the payload is read and the decision written in UTF-8 whatever the console code page. A piped
    Windows python defaulted to cp1252 and changed 33 of 117 corpus decisions (27 wrong refusals).
  * `-c` + an existence check: a MISSING dispatcher exits 0 instead of python's exit 2. A worktree checked out
    from a branch that predates the install has no `.claude/hooks/hooks.py`; `python <missing file>` exits 2,
    which the harness reads as a BLOCK — a resumed worktree session had every Bash and Write call refused.
    The bash hooks failed OPEN in the same situation (exit 127 is non-blocking), and so does this.
  * `CLAUDE_PROJECT_DIR` is taken from the environment the harness exports, so the registration holds no path.

Why one dispatcher per event: the harness spawns one process per registered hook, and a Windows python start
costs the better part of a second — four PreToolUse gates as four processes cost four starts on EVERY shell
command. One process reads the payload once, resolves the run once, and runs every gate of the event.

GATE DISCOVERY. Every `gate_*.py` beside this file that declares `EVENT`, `ORDER` and `run(ctx)` is a gate;
`TOOLS` (a set of tool names, PreToolUse only; absent = every tool) is its matcher. The framework's gates use
ORDER 10..90; a PROJECT adds its own gate as `gate_<name>.py` with an ORDER above 100 (or below 10 to run
first) — no second dispatcher, no second registration. A project-specific `Write`/`Edit` gate declares
`TOOLS = {"Write", "Edit"}` and the project widens the PreToolUse matcher in settings.json to `Bash|Write|Edit`.
`hooks.config.json` beside this file, `{"disabled_gates": ["spec-tdd-gate"]}`, switches a gate off by its
HOOK name; the self-test honours it.

Decision semantics (the harness contract: exit 0 allows, exit 2 blocks and shows stderr to the agent):
  * session-start: every gate runs; stdout is concatenated as context; exit is ALWAYS 0 (SessionStart cannot
    block, and exit 2 would show stderr to the user only).
  * pre-tool-use: gates whose TOOLS match run in ORDER; the first block wins; a gate that raises is skipped
    with a note on stderr (fail OPEN on an ordinary command — the push gate fails closed on a push itself).
  * stop: EVERY gate runs so every decision-log line is written; any block wins and every block message is
    delivered; a gate that raises REFUSES the stop (fail CLOSED), because a gate whose machinery is broken
    must not look like a gate that is satisfied.

THE LIBRARY IS IMPORTED DEFENSIVELY. A missing, truncated or syntax-broken `hooklib.py` would otherwise end this
process with exit 1 — a non-blocking error the harness proceeds past, i.e. every gate silently inert, which is
the exact failure class this rewrite exists to end. Without the library: a Stop REFUSES (fail closed); a
PreToolUse runs a library-free classifier that still bans `--no-verify` and still refuses a `git push` (the two
decisions that must never depend on state), and allows everything else; a SessionStart exits 0 with a note.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

LIB_ERROR: Optional[str] = None
try:
    import hooklib as lib  # noqa: E402

    if not callable(getattr(lib, "selftest", None)) or not lib.selftest():
        raise ImportError("hooklib.py is truncated: its last definition, selftest(), is missing")
except Exception as _exc:  # noqa: BLE001 — any import failure takes the degraded paths below
    lib = None  # type: ignore[assignment]
    LIB_ERROR = f"{_exc.__class__.__name__}: {_exc}"

VERSION = "2026.10.03-python-2"
EVENTS = ("session-start", "pre-tool-use", "stop")
REINJECT_SOURCES = {"compact", "resume", "startup", ""}  # an absent source (Kiro agentSpawn) re-injects
CONFIG_FILENAME = "hooks.config.json"

# The launcher: the program the registration runs with `python -X utf8 -c <LAUNCHER> <event>`. Single quotes
# only, so it survives a JSON string and a shell double-quoted argument unchanged. `sys.argv[0]` is '-c' under
# `-c`, so the event is `sys.argv[1]` both here and inside the dispatcher.
LAUNCHER = (
    "import os,sys,runpy;"
    "p=os.path.join(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd(),'.claude','hooks','hooks.py');"
    "sys.argv=[p]+sys.argv[1:];"
    "os.path.isfile(p) and runpy.run_path(p,run_name='__main__')"
)
REGISTRATION_TIMEOUTS = {"session-start": 30, "pre-tool-use": 30, "stop": 60}
REGISTRATION_MATCHERS = {"pre-tool-use": "Bash"}

Gate = Tuple[str, int, Optional[Set[str]], Callable[[Any], Any]]


def load_config(hooks_dir: Path) -> Dict[str, Any]:
    """`hooks.config.json` beside the dispatcher; an absent or unreadable file is an empty configuration."""
    path = hooks_dir / CONFIG_FILENAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def disabled_gates(hooks_dir: Path) -> Set[str]:
    value = load_config(hooks_dir).get("disabled_gates", [])
    return {str(name) for name in value} if isinstance(value, list) else set()


def discover_gates(event: str, hooks_dir: Path) -> List[Gate]:
    """Every `gate_*.py` in hooks_dir declaring EVENT == event, as (HOOK name, ORDER, TOOLS, run), in ORDER.
    A module that fails to import is reported on stderr and skipped: one broken project gate must not take the
    framework's gates down with it (the Stop fail-closed policy applies to a gate that RUNS and raises)."""
    if str(hooks_dir) not in sys.path:
        sys.path.insert(0, str(hooks_dir))
    gates: List[Gate] = []
    for path in sorted(hooks_dir.glob("gate_*.py")):
        try:
            module = importlib.import_module(path.stem)
        except Exception as exc:  # noqa: BLE001 — see the docstring
            sys.stderr.write(
                f"hooks.py: gate module {path.name} failed to import ({exc.__class__.__name__}: {exc}); skipped.\n"
            )
            continue
        if getattr(module, "EVENT", None) != event or not callable(getattr(module, "run", None)):
            continue
        name = str(getattr(module, "HOOK", path.stem))
        order = getattr(module, "ORDER", 500)
        tools = getattr(module, "TOOLS", None)
        gates.append((name, int(order) if isinstance(order, int) else 500, set(tools) if tools else None, module.run))
    gates.sort(key=lambda g: (g[1], g[0]))
    return gates


def dispatch(  # noqa: C901 — the per-event policy, in one place
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
    if event not in EVENTS:
        raise SystemExit(f"hooks.py: unknown event '{event}' (expected {' | '.join(EVENTS)} | selftest | registration)")
    directory = hooks_dir or HERE
    payload = lib.Payload.parse(payload_text)
    ctx = lib.Context(payload, host=host or lib.CLAUDE, environ=environ, hooks_dir=directory, cwd=cwd)
    off = disabled_gates(directory)
    gates = [g for g in discover_gates(event, directory) if g[0] not in off]
    if event == "session-start" and payload.source not in REINJECT_SOURCES:
        gates = [g for g in gates if g[0] != "continuous-work-reinject"]
    if event == "pre-tool-use" and payload.tool_name:
        gates = [g for g in gates if g[2] is None or payload.tool_name in g[2]]

    stdout: List[str] = []
    stderr: List[str] = []
    blocked = False
    for name, _order, _tools, gate in gates:
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
            why + "refusing the stop rather than allowing it unchecked. Restore hooklib.py, then continue working.\n",
        )
    if event == "pre-tool-use":
        try:
            payload = json.loads(payload_text or "{}")
            command = (payload.get("tool_input") or {}).get("command", "") if isinstance(payload, dict) else ""
        except Exception:  # noqa: BLE001
            command = ""
        stripped = _QUOTED_RE.sub("", command if isinstance(command, str) else "")
        is_commit = bool(_COMMIT_RE.search(stripped))
        is_push = bool(_PUSH_RE.search(stripped)) and not _STASH_RE.search(stripped)
        if is_commit and _BYPASS_RE.search(stripped):
            return 2, "spec-tdd-gate: 'git commit --no-verify'/-n is forbidden. Fix the reported issue instead.\n"
        if is_push and "--no-verify" in stripped:
            return (
                2,
                "spec-tdd-gate: 'git push --no-verify' is forbidden. Fix the cause instead of bypassing the hook.\n",
            )
        if is_push:
            return 2, why + "refusing the PUSH rather than allowing it unverified. Restore hooklib.py, then push.\n"
        return 0, ""
    # session-start: never break startup. The note goes to stderr, which exit 0 routes to the debug log — the
    # agent sees nothing, but a maintainer reading the log sees WHY the gates are not judging this session.
    return (
        0,
        why + "no gate ran at SessionStart; the session is unregistered and ungated until the library is restored.\n",
    )


def registration_block(project_dir_placeholder: str = "${CLAUDE_PROJECT_DIR}") -> str:
    """The exact `hooks` block for settings.json. The launcher reads CLAUDE_PROJECT_DIR from the environment, so
    the block carries no path; the placeholder is accepted only for callers that want to show one."""
    del project_dir_placeholder
    block: Dict[str, Any] = {"hooks": {}}
    for event, key in (("session-start", "SessionStart"), ("pre-tool-use", "PreToolUse"), ("stop", "Stop")):
        entry: Dict[str, Any] = {
            "hooks": [
                {
                    "type": "command",
                    "command": "python",
                    "args": ["-X", "utf8", "-c", LAUNCHER, event],
                    "timeout": REGISTRATION_TIMEOUTS[event],
                }
            ]
        }
        if event in REGISTRATION_MATCHERS:
            entry = {"matcher": REGISTRATION_MATCHERS[event], **entry}
        block["hooks"][key] = [entry]
    return json.dumps(block, indent=2) + "\n"


def _utf8_streams() -> None:
    # The harness reads and writes UTF-8. A piped Windows python defaults to the console code page (cp1252) on
    # every stream, which mis-decodes the payload and turns every em dash in a refusal into U+FFFD. `-X utf8`
    # in the registration covers the common path; this covers direct invocations (tests, Kiro, the self-test).
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv: List[str]) -> int:
    _utf8_streams()
    if len(argv) < 2:
        sys.stderr.write(__doc__ or "")
        return 2
    event = argv[1]
    if event == "selftest":
        return selftest()
    if event == "version":
        sys.stdout.write(VERSION + "\n")
        return 0
    if event == "registration":
        sys.stdout.write(registration_block())
        return 0
    if event not in EVENTS:
        sys.stderr.write(
            f"hooks.py: unknown event '{event}' (expected {' | '.join(EVENTS)} | selftest | registration)\n"
        )
        return 2
    payload_text = sys.stdin.read() if not sys.stdin.isatty() else ""
    if lib is None:
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


def _probe_interpreter(python: str) -> Tuple[bool, str]:
    # The resolved `python` must be a REAL interpreter. The Microsoft Store alias (`WindowsApps\python.exe`)
    # has the same failure shape the bash hooks had: it resolves, it spawns, and it exits without running
    # anything — a non-blocking error the harness proceeds past. Name it, and name the remedy.
    try:
        probe = subprocess.run(  # nosec B603 — the interpreter the harness itself would spawn
            [python, "-c", "import sys; print(sys.executable)"], capture_output=True, text=True, timeout=30
        )
        rc, out, err = probe.returncode, probe.stdout.strip(), probe.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        rc, out, err = 1, "", str(exc)
    is_alias = "WindowsApps" in python
    works = rc == 0 and bool(out) and not is_alias
    remedy = (
        " — this is the Microsoft Store alias. Disable it under Settings > Apps > Advanced app settings > "
        "App execution aliases, or put a real Python installation ahead of it on PATH. Every exec-form hook "
        "AND every `python` command the agent runs resolves the same way, so nothing works until it is fixed."
        if is_alias
        else ""
    )
    return works, f"{python} -> exit {rc}: {err[:160] or out}{remedy}"


def selftest() -> int:  # noqa: C901, PLR0915 — one linear list of checks, reported together
    """Install this hooks directory into a scratch project, then spawn the dispatcher exactly as the harness
    does — the `python` on PATH, exec form, the launcher — and assert: a MISSING dispatcher fails open;
    SessionStart injects the contract and logs a decision; PreToolUse blocks a bypass and reads a quoted
    command; Stop refuses a registered run that records unfinished work. Exit 1 on any FAIL."""
    results: List[Tuple[str, bool, str]] = []
    if lib is None:
        results.append(("hooklib.py imports", False, LIB_ERROR or "unknown"))
        return _report(results)
    results.append(("hooklib.py imports", True, str(HERE / "hooklib.py")))
    python = shutil.which("python") or shutil.which("python3")
    if not python:
        results.append(("`python` resolves on PATH", False, "no python on PATH — exec-form registration cannot start"))
        return _report(results)
    results.append(("`python` resolves on PATH", True, python))
    works, detail = _probe_interpreter(python)
    results.append(("`python` on PATH is a working interpreter", works, detail))
    if not works:
        return _report(results)
    off = disabled_gates(HERE)
    if off:
        results.append(("gates disabled by hooks.config.json", True, ", ".join(sorted(off))))

    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        hooks_dir = project / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True)
        for src in HERE.glob("*.py"):
            shutil.copy(src, hooks_dir / src.name)
        for extra in ("CONTRACT_VERSION", CONFIG_FILENAME):
            if (HERE / extra).is_file():
                shutil.copy(HERE / extra, hooks_dir / extra)
        empty = Path(tmp) / "empty"
        empty.mkdir()
        sid = "selftest-1111-2222-3333-444455556666"

        def spawn(event: str, payload: str, project_dir: Path) -> subprocess.CompletedProcess:
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir))
            return subprocess.run(  # nosec B603 — exactly the harness's own launch
                [python, "-X", "utf8", "-c", LAUNCHER, event],
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(project_dir),
                env=env,
                timeout=60,
                check=False,
            )

        missing = spawn("pre-tool-use", '{"tool_name":"Bash","tool_input":{"command":"git push"}}', empty)
        results.append(
            (
                "a MISSING dispatcher fails open (exit 0), not as a block",
                missing.returncode == 0,
                f"exit {missing.returncode} {missing.stderr[:160]}",
            )
        )

        start = spawn(
            "session-start",
            f'{{"session_id":"{sid}","cwd":"{project.as_posix()}","source":"startup","hook_event_name":"SessionStart"}}',
            project,
        )
        results.append(("SessionStart exits 0", start.returncode == 0, f"exit {start.returncode} {start.stderr[:200]}"))
        results.append(
            ("SessionStart injects the contract", "Continuous work is in force" in start.stdout, start.stdout[:120])
        )
        logs = list((project / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME / ".hook-decisions").glob("*.log"))
        results.append(("SessionStart writes a decision-log line", bool(logs), str(logs)))

        if "spec-tdd-gate" not in off:
            pre = spawn(
                "pre-tool-use", '{"tool_name":"Bash","tool_input":{"command":"git commit --no-verify -m x"}}', project
            )
            results.append(
                (
                    "PreToolUse blocks `git commit --no-verify`",
                    pre.returncode == 2 and "forbidden" in pre.stderr,
                    f"exit {pre.returncode}",
                )
            )
        if "no-env-vars" not in off:
            quoted = spawn(
                "pre-tool-use",
                '{"tool_name":"Bash","tool_input":{"command":"cd \\"D:/Code Workspace/x\\" '
                '&& export aws_profile=probe — ok"}}',
                project,
            )
            results.append(
                (
                    "PreToolUse reads a quoted, non-ASCII, lower-case command in UTF-8",
                    quoted.returncode == 2,
                    f"exit {quoted.returncode} {quoted.stderr[:120]}",
                )
            )
        write_call = spawn(
            "pre-tool-use",
            '{"tool_name":"Write","tool_input":{"file_path":"x.py","content":"git push --no-verify"}}',
            project,
        )
        results.append(
            (
                "PreToolUse leaves a non-shell tool to its own gates",
                write_call.returncode == 0,
                f"exit {write_call.returncode}",
            )
        )

        if "issue-loop-gate" not in off:
            run_dir = project / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME / "runs" / sid[:8]
            (run_dir / lib.RESUME_FILENAME).write_text(
                f"SESSION_ID: {sid}\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 999\nAWAITING_USER: none\n",
                encoding="utf-8",
            )
            stop = spawn(
                "stop", f'{{"session_id":"{sid}","cwd":"{project.as_posix()}","hook_event_name":"Stop"}}', project
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
        sys.stdout.write(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n        {detail}") + "\n")
    sys.stdout.write(f"hooks selftest ({VERSION}): {len(results) - failed} passed, {failed} failed\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
