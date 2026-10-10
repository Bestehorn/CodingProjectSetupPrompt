#!/usr/bin/env python
"""hooks.py — the ONE entry point for every Claude Code hook of this framework: one interpreter per event.

Usage:
    python .claude/hooks/hooks.py session-start     # SessionStart: register, scoped temp, re-inject
    python .claude/hooks/hooks.py pre-tool-use      # PreToolUse: env vars, sleep, push gate, claim, filing (+ project)
    python .claude/hooks/hooks.py post-tool-use     # PostToolUse: project gates only (none shipped)
    python .claude/hooks/hooks.py stop              # Stop: evidence gate, loop brake
    python .claude/hooks/hooks.py selftest          # prove the registered launch form executes and blocks
    python .claude/hooks/hooks.py registration      # print the settings.json hooks block to install

HOW IT IS REGISTERED (exec form, `python`, through the LAUNCHER):
    { "type": "command", "command": "python",
      "args": ["-I", "-X", "utf8", "-c", "<LAUNCHER>", "pre-tool-use"], "timeout": 30 }
where <LAUNCHER> is the one-line program `LAUNCHER` below (print the exact block with `registration`). Four
things the launch buys, each from a measured incident:
  * `-I` (isolated mode): the interpreter ignores PYTHONHOME, PYTHONPATH and the other PYTHON* variables a
    session may carry; one leaked PYTHONHOME otherwise stops every hook with an interpreter that cannot find
    its own standard library. The dispatcher puts its own directory on sys.path itself.
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
  * session-start: every gate runs; stdout is MERGED as context — plain text is joined, and when any gate
    returns a JSON object (`systemMessage`, `hookSpecificOutput.additionalContext`) the parts are merged into
    ONE object, because two objects on stdout are not JSON and the harness would discard both; exit is
    ALWAYS 0 (SessionStart cannot block, and exit 2 would show stderr to the user only).
  * pre-tool-use: gates whose TOOLS match run in ORDER; the first block wins; a gate that raises is skipped
    with a note on stderr (fail OPEN on an ordinary command — the push gate fails closed on a push itself).
  * post-tool-use: the same, for gates a PROJECT declares with EVENT = "post-tool-use" (the framework ships
    none); exit 2 shows stderr to the agent although the tool already ran. `registration` emits the
    PostToolUse entry only when such a gate exists.
  * stop: EVERY gate runs so every decision-log line is written; any block wins and every block message is
    delivered; a gate that raises REFUSES the stop (fail CLOSED), because a gate whose machinery is broken
    must not look like a gate that is satisfied.

THE LIBRARY IS IMPORTED DEFENSIVELY. A missing, truncated or syntax-broken `hooklib.py` would otherwise end this
process with exit 1 — a non-blocking error the harness proceeds past, i.e. every gate silently inert, which is
the exact failure class this rewrite exists to end. Without the library: a Stop REFUSES (fail closed); a
PreToolUse runs a library-free classifier that still bans `--no-verify` and still refuses a `git push` (the two
decisions that must never depend on state), and allows everything else; a SessionStart exits 0 and prints the
one-line contract plus the reason. The degraded Stop refusal is CAPPED like every gate (default 8, the same
`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`), with its own counter file, so a broken library can never wedge a session.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess  # nosec B404 — the self-test spawns the interpreter with a fixed argv, never a shell
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

VERSION = "2026.10.10-python-4"
EVENTS = ("session-start", "pre-tool-use", "post-tool-use", "stop")
EVENT_KEYS = {
    "session-start": "SessionStart",
    "pre-tool-use": "PreToolUse",
    "post-tool-use": "PostToolUse",
    "stop": "Stop",
}
DEFAULT_BLOCK_CAP = 8
REINJECT_SOURCES = {"compact", "resume", "startup", ""}  # an absent source (Kiro agentSpawn) re-injects
CONFIG_FILENAME = "hooks.config.json"

# The launcher: the program the registration runs with `python -I -X utf8 -c <LAUNCHER> <event>`. Single quotes
# only, so it survives a JSON string and a shell double-quoted argument unchanged. `sys.argv[0]` is '-c' under
# `-c`, so the event is `sys.argv[1]` both here and inside the dispatcher.
LAUNCHER = (
    "import os,sys,runpy;"
    "p=os.path.join(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd(),'.claude','hooks','hooks.py');"
    "sys.argv=[p]+sys.argv[1:];"
    "os.path.isfile(p) and runpy.run_path(p,run_name='__main__')"
)
INTERPRETER_FLAGS = ["-I", "-X", "utf8"]
# A timed-out hook renders NO decision and the action proceeds, so a tight timeout is a fail-open. PreToolUse
# is 60 s because `claim-before-worktree` asks the tracker (its own 25 s limit) after a cold Windows start.
REGISTRATION_TIMEOUTS = {"session-start": 30, "pre-tool-use": 60, "post-tool-use": 30, "stop": 60}
# The matcher of a tool event is the UNION of the tools its discovered gates declare (`tool_matcher`); this is
# the default when no gate can be read. A gate declaring no TOOLS matches every tool, so the matcher is dropped.
REGISTRATION_MATCHERS = {"pre-tool-use": "Bash", "post-tool-use": "Bash"}
#: A project gate takes an ORDER above this (or below 10); the self-test leaves project gates out of its scratch
#: project, because their libraries (`scripts/...`) are not copied there.
PROJECT_ORDER_FLOOR = 100
ORDER_RE = re.compile(r"^ORDER\s*=\s*(-?\d+)", re.MULTILINE)

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
    if event in ("pre-tool-use", "post-tool-use") and payload.tool_name:
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
    return lib.Decision(2 if blocked else 0, merge_stdout(stdout), "".join(stderr))


def merge_stdout(parts: List[str]) -> str:  # noqa: C901 — two output grammars merged in one pass
    """One stdout from many gates. Plain text is joined with blank lines. When any part is a JSON object the
    result is ONE JSON object: `systemMessage` strings are joined, `hookSpecificOutput.additionalContext`
    strings are joined (plain-text parts join them there, so no context is lost), scalar keys keep the first
    value, and `hookSpecificOutput.hookEventName` keeps the first. Two objects on stdout would be invalid JSON."""
    parts = [p for p in parts if p and p.strip()]
    objects: List[Dict[str, Any]] = []
    texts: List[str] = []
    for part in parts:
        stripped = part.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                loaded = json.loads(stripped)
            except ValueError:
                texts.append(part)
                continue
            if isinstance(loaded, dict):
                objects.append(loaded)
                continue
        texts.append(part)
    if not objects:
        return "\n".join(texts)
    merged: Dict[str, Any] = {}
    specific: Dict[str, Any] = {}
    for obj in objects:
        for key, value in obj.items():
            if key == "hookSpecificOutput" and isinstance(value, dict):
                for skey, svalue in value.items():
                    if skey == "additionalContext" and isinstance(svalue, str):
                        specific[skey] = (specific.get(skey, "") + "\n" + svalue).strip("\n")
                    else:
                        specific.setdefault(skey, svalue)
            elif key == "systemMessage" and isinstance(value, str):
                merged[key] = (merged.get(key, "") + "\n" + value).strip("\n")
            else:
                merged.setdefault(key, value)
    if texts:
        specific["additionalContext"] = (specific.get("additionalContext", "") + "\n" + "\n".join(texts)).strip("\n")
    if specific:
        merged["hookSpecificOutput"] = specific
    return json.dumps(merged)


# ---------------------------------------------------------------------------------------------------------
# The library-free fallback. Deliberately duplicates the two command predicates rather than importing them:
# this code must run when the library cannot be imported at all.
# ---------------------------------------------------------------------------------------------------------

_QUOTED_RE = re.compile(r'"[^"]*"|\'[^\']*\'')
# `\s` in the separator class, not a space: a newline separates commands too, and `cd x` followed by
# `git push --no-verify` on the next line slipped past a space-only class (measured).
_COMMIT_RE = re.compile(r"(^|[;&|\s])git\s+([^;&|]*\s)?commit(\s|$)")
_PUSH_RE = re.compile(r"(^|[;&|\s])git\s+([^;&|]*\s)?push(\s|$)")
_STASH_RE = re.compile(r"stash\s+push")
_BYPASS_RE = re.compile(r"(--no-verify|\s-n(\s|$))")


def _degraded_payload(payload_text: str) -> Dict[str, Any]:
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _degraded_stop(payload: Dict[str, Any], why: str) -> Tuple[int, str, str]:
    """The library-free Stop refusal, CAPPED. Without a cap a broken library refused every turn-end of every
    session forever (measured); the cap stands the gate down after DEFAULT_BLOCK_CAP consecutive refusals,
    saying so, exactly as the real gates do. The counter lives beside theirs, keyed on the session."""
    sid = str(payload.get("session_id") or "")
    sid8 = re.sub(r"[^A-Za-z0-9_-]", "", sid)[:8] or "nosession"
    project = os.environ.get("CLAUDE_PROJECT_DIR") or str(payload.get("cwd") or "") or os.getcwd()
    counter = Path(project) / ".claude" / "agent-state" / "issue-work-orchestrator" / ".stop-gate-counters"
    counter = counter / f"degraded-{sid8}.count"
    raw_cap = os.environ.get("CLAUDE_CODE_STOP_HOOK_BLOCK_CAP", "")
    cap = int(raw_cap) if raw_cap.isdigit() and 1 <= int(raw_cap) <= 64 else DEFAULT_BLOCK_CAP
    try:
        blocks = int(re.sub(r"[^0-9]", "", counter.read_text(encoding="utf-8")) or "0") if counter.is_file() else 0
    except OSError:
        blocks = 0
    if blocks >= cap:
        return (
            0,
            "",
            why + f"standing down after {blocks} consecutive refusals so the session cannot wedge. THE WORK IS NOT\n"
            "JUDGED: no gate has run. Restore hooklib.py (python .claude/hooks/hooks.py selftest), then continue.\n",
        )
    try:
        counter.parent.mkdir(parents=True, exist_ok=True)
        counter.write_text(str(blocks + 1), encoding="utf-8")
    except OSError:
        return 0, "", why + "cannot count its refusals; standing down rather than refusing without a way out.\n"
    return (
        2,
        "",
        why + f"refusing the stop rather than allowing it unchecked (refusal {blocks + 1} of {cap}). Restore\n"
        "hooklib.py, then continue working.\n",
    )


def degraded(event: str, payload_text: str) -> Tuple[int, str, str]:
    """-> (exit code, stdout, stderr) for an event when hooklib cannot be imported."""
    why = f"hooks.py: the hook library cannot be loaded ({LIB_ERROR}) — "
    payload = _degraded_payload(payload_text)
    if event == "stop":
        return _degraded_stop(payload, why)
    if event in ("pre-tool-use", "post-tool-use"):
        command = (payload.get("tool_input") or {}).get("command", "")
        stripped = _QUOTED_RE.sub("", command if isinstance(command, str) else "")
        is_commit = bool(_COMMIT_RE.search(stripped))
        is_push = bool(_PUSH_RE.search(stripped)) and not _STASH_RE.search(stripped)
        if event == "post-tool-use":
            return 0, "", ""
        if is_commit and _BYPASS_RE.search(stripped):
            return 2, "", "spec-tdd-gate: 'git commit --no-verify'/-n is forbidden. Fix the reported issue instead.\n"
        if is_push and "--no-verify" in stripped:
            return (
                2,
                "",
                "spec-tdd-gate: 'git push --no-verify' is forbidden. Fix the cause instead of bypassing the hook.\n",
            )
        if is_push:
            return (
                2,
                "",
                why + "refusing the PUSH rather than allowing it unverified. Restore hooklib.py, then push.\n",
            )
        return 0, "", ""
    # session-start: never break startup, but never lose the contract either — it is exactly when the library
    # is broken that the agent must still hear it. Stdout is context; the reason goes to the debug log.
    return (
        0,
        "## Continuous work is in force (.claude/rules/continuous-work.md)\n\n"
        "A turn ends when the WORK IS FINISHED or a Proven Exception applies (irreversible action, sensitive\n"
        "information, genuine design fork, hard blocker) — never to ask permission to continue. The hook library\n"
        f"of this project is broken ({LIB_ERROR}); no gate is judging this session until\n"
        "`python .claude/hooks/hooks.py selftest` passes again — repair it as part of the work.\n",
        why + "no gate ran at SessionStart; the session is unregistered and ungated until the library is restored.\n",
    )


def tool_matcher(event: str, hooks_dir: Path) -> Optional[str]:
    """The settings.json matcher for a tool event: the union of the tools its gates declare, `|`-joined, so a
    project gate on Write or Edit is reached without a hand-edited block (the prompt forbids retyping one).
    None when some gate declares no TOOLS (it judges every tool) — the entry then carries no matcher."""
    if event not in REGISTRATION_MATCHERS:
        return None
    if lib is None:
        return REGISTRATION_MATCHERS[event]
    tools: Set[str] = set()
    for _name, _order, gate_tools, _run in discover_gates(event, hooks_dir):
        if gate_tools is None:
            return None
        tools |= gate_tools
    return "|".join(sorted(tools)) if tools else REGISTRATION_MATCHERS[event]


def registration_block(project_dir_placeholder: str = "${CLAUDE_PROJECT_DIR}") -> str:
    """The exact `hooks` block for settings.json. The launcher reads CLAUDE_PROJECT_DIR from the environment, so
    the block carries no path; the placeholder is accepted only for callers that want to show one. Re-run it
    after adding a gate on another tool: the matcher of a tool event is derived from the gates present."""
    del project_dir_placeholder
    block: Dict[str, Any] = {"hooks": {}}
    for event in EVENTS:
        if event == "post-tool-use" and not (lib is not None and discover_gates(event, HERE)):
            continue  # the framework ships no PostToolUse gate; a project that adds one gets the entry
        key = EVENT_KEYS[event]
        entry: Dict[str, Any] = {
            "hooks": [
                {
                    "type": "command",
                    "command": "python",
                    "args": [*INTERPRETER_FLAGS, "-c", LAUNCHER, event],
                    "timeout": REGISTRATION_TIMEOUTS[event],
                }
            ]
        }
        matcher = tool_matcher(event, HERE)
        if matcher is not None:
            entry = {"matcher": matcher, **entry}
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


def main(argv: List[str]) -> int:  # noqa: C901 — one subcommand dispatch, in order
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
        code, out, message = degraded(event, payload_text)
        if out:
            sys.stdout.write(out)
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


def _is_project_gate(path: Path) -> bool:
    """A `gate_*.py` whose source declares an ORDER outside the framework's 10..90 band, read WITHOUT importing
    it (a project gate may import a library the scratch project does not have)."""
    if not path.name.startswith("gate_"):
        return False
    try:
        match = ORDER_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False
    if not match:
        return False
    order = int(match.group(1))
    return order > PROJECT_ORDER_FLOOR or order < 10


def _probe_interpreter(python: str) -> Tuple[bool, str]:
    # The resolved `python` must be a REAL interpreter. The Microsoft Store alias (`WindowsApps\python.exe`)
    # has the same failure shape the bash hooks had: it resolves, it spawns, and it exits without running
    # anything — a non-blocking error the harness proceeds past. Name it, and name the remedy.
    try:
        # The SAME flags as the registration: `-I` ignores an inherited PYTHONHOME/PYTHONPATH (a uv venv exports
        # one), so a probe without them failed where the real launch passes.
        probe = subprocess.run(  # nosec B603 — the interpreter the harness itself would spawn
            [python, *INTERPRETER_FLAGS, "-c", "import sys; print(sys.executable)"],
            capture_output=True,
            text=True,
            timeout=30,
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


def selftest() -> int:
    """Install this hooks directory into a scratch project, then spawn the dispatcher exactly as the harness
    does — the `python` on PATH, exec form, the launcher — and assert: a MISSING dispatcher fails open;
    SessionStart injects the contract and logs a decision; PreToolUse blocks a bypass, refuses a foreground
    sleep poll but allows it in the background, reads a quoted command and leaves a non-shell tool alone; Stop
    refuses a registered run that records unfinished work. Exit 1 on any FAIL — including a failure of the
    self-test's own machinery: an exception here becomes a FAIL line, never a traceback, because a traceback
    discards the PASS lines that locate the break (measured: a run-dir write raised before the Stop check)."""
    results: List[Tuple[str, bool, str]] = []
    try:
        _selftest_checks(results)
    except Exception:  # noqa: BLE001 — the self-test must always end in a report
        detail = traceback.format_exc().strip().splitlines()[-1]
        results.append(("the self-test itself ran to completion", False, detail))
    return _report(results)


def _selftest_checks(results: List[Tuple[str, bool, str]]) -> None:  # noqa: C901, PLR0915 — one linear list
    if lib is None:
        results.append(("hooklib.py imports", False, LIB_ERROR or "unknown"))
        return
    results.append(("hooklib.py imports", True, str(HERE / "hooklib.py")))
    python = shutil.which("python") or shutil.which("python3")
    if not python:
        results.append(("`python` resolves on PATH", False, "no python on PATH — exec-form registration cannot start"))
        return
    results.append(("`python` resolves on PATH", True, python))
    works, detail = _probe_interpreter(python)
    results.append(("`python` on PATH is a working interpreter", works, detail))
    if not works:
        return
    off = disabled_gates(HERE)
    if off:
        results.append(("gates disabled by hooks.config.json", True, ", ".join(sorted(off))))

    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        hooks_dir = project / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True)
        for src in HERE.glob("*.py"):
            if _is_project_gate(src):
                continue  # its library under scripts/ is not in the scratch project; the project's own tests cover it
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
                [python, *INTERPRETER_FLAGS, "-c", LAUNCHER, event],
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
        if "no-foreground-sleep" not in off:
            poll = spawn(
                "pre-tool-use", '{"tool_name":"Bash","tool_input":{"command":"sleep 300; cat out.txt"}}', project
            )
            results.append(
                (
                    "PreToolUse refuses a foreground `sleep 300` poll",
                    poll.returncode == 2 and "no-foreground-sleep" in poll.stderr,
                    f"exit {poll.returncode} {poll.stderr[:120]}",
                )
            )
            background = spawn(
                "pre-tool-use",
                '{"tool_name":"Bash","tool_input":{"command":"sleep 300; cat out.txt","run_in_background":true}}',
                project,
            )
            results.append(
                (
                    "PreToolUse allows the same wait as a background task",
                    background.returncode == 0,
                    f"exit {background.returncode} {background.stderr[:120]}",
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
            # session-register seeded this directory at the SessionStart spawn above; the self-test must not
            # depend on that (the gate may be disabled, or its seeding may be the defect under test).
            run_dir.mkdir(parents=True, exist_ok=True)
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


def _report(results: List[Tuple[str, bool, str]]) -> int:
    failed = 0
    for label, ok, detail in results:
        failed += 0 if ok else 1
        sys.stdout.write(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n        {detail}") + "\n")
    sys.stdout.write(f"hooks selftest ({VERSION}): {len(results) - failed} passed, {failed} failed\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
