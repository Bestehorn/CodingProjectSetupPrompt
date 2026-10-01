"""pytest port of tests/test_reinject.sh — the SessionStart re-inject never borrows another run's state.

The bash suite (continuous-work-reinject.sh) is the specification; every one of its 26 assertions is mirrored
here, one pytest test per bash assertion, with the bash label kept in the test id. Extra tests, marked
"(extra)" in their docstring, pin behaviour the Python API makes directly observable.

Conventions of the port:
  * bash `run` captured stdout AND stderr (`2>&1`); `run_gate` returns both concatenated.
  * bash ran under Git Bash, where paths print with `/`; the Python gate prints native paths, so the haystack
    is separator-normalized (backslash -> `/`) before a substring test. No needle contains a backslash.
  * `environ={}` always, so the real CLAUDE_PROJECT_DIR of the host session can never leak into an arena.
  * The clock is pinned to the suite's authoring date for the "notice delivered while valid" case, so the test
    checks the MECHANISM (a notice inside its Valid-until window is delivered) and does not become a time bomb
    when the real notice legitimately retires on 2026-11-15.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pytest

import gate_reinject
import hooklib as lib
import hooks

HOOKS = Path(__file__).resolve().parent.parent
MINE = "5db650ab-0e97-41fe-a5e8-45e52e41386e"
MY_RUN = "5db650ab"
SIBLING_RUN = "54a2387f"
AUTHORING_DATE = (
    "2026-10-01"  # inside the real REVISION_NOTICE.md window (Valid-until: 2026-11-15)
)

MY_STATE = f"""# Resume state
SESSION_ID: {MINE}
Status: IN_PROGRESS
Phase: FIX
CURRENT_ISSUE: 574
BRANCH: fix-issue-574-logging-floor
AWAITING_USER: none
"""
MY_STATE_SHORT = f"""SESSION_ID: {MINE}
Status: IN_PROGRESS
Phase: FIX
CURRENT_ISSUE: 574
"""

Case = Tuple[str, str, bool]  # (bash label, needle, wanted)


# ---------------------------------------------------------------------------------------------------------
# Arena helpers — each mirrors a bash function of the suite.
# ---------------------------------------------------------------------------------------------------------


def orch(arena: Path) -> Path:
    return arena / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME


def reset(arena: Path) -> None:
    """bash `reset`: a fresh orchestrator tree with an empty registry."""
    shutil.rmtree(str(arena / ".claude"), ignore_errors=True)
    orch(arena).mkdir(parents=True)
    (orch(arena) / "registry.json").write_text("{}", encoding="utf-8")


def sibling(arena: Path) -> Path:
    """bash `sibling`: a SIBLING run, freshly touched, carrying a DIFFERENT issue. This is the trap. Its mtime
    is pushed into the future so that any mtime-derived rung would have to pick it."""
    run_dir = orch(arena) / "runs" / SIBLING_RUN
    run_dir.mkdir(parents=True, exist_ok=True)
    state = run_dir / lib.RESUME_FILENAME
    state.write_text(
        "# Resume state\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 565\nBRANCH: fix-issue-565\n",
        encoding="utf-8",
    )
    future = time.time() + 600
    os.utime(str(state), (future, future))
    return state


def register(arena: Path, sid: str = MINE, run_id: str = MY_RUN) -> None:
    """The registry declares a run for `sid` at runs/<run_id>/ — exactly the bash printf."""
    (orch(arena) / "registry.json").write_text(
        json.dumps(
            {sid: {"session_id": sid, "run_id": run_id, "state_dir": f"runs/{run_id}/"}}
        ),
        encoding="utf-8",
    )


def write_state(arena: Path, run_id: str, text: str) -> Path:
    run_dir = orch(arena) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    state = run_dir / lib.RESUME_FILENAME
    state.write_text(text, encoding="utf-8")
    return state


def payload(arena: Path, sid: Optional[str] = MINE, source: str = "compact") -> str:
    data: Dict[str, str] = {
        "source": source,
        "cwd": arena.as_posix(),
        "hook_event_name": "SessionStart",
    }
    if sid is not None:
        data["session_id"] = sid
    return json.dumps(data)


def run_gate(arena: Path, payload_text: str, hooks_dir: Path = HOOKS) -> str:
    """bash `run`: the re-inject gate ALONE, cwd = arena, stdout and stderr merged, no environment leak."""
    ctx = lib.Context(
        lib.Payload.parse(payload_text), environ={}, hooks_dir=hooks_dir, cwd=arena
    )
    decision = gate_reinject.run(ctx)
    return decision.stdout + decision.stderr


def dispatch(arena: Path, payload_text: str) -> lib.Decision:
    """What the harness runs: every SessionStart gate through the one dispatcher."""
    return hooks.dispatch(
        "session-start",
        payload_text,
        host=lib.CLAUDE,
        environ={},
        cwd=arena,
        hooks_dir=HOOKS,
    )


def check(label: str, needle: str, wanted: bool, out: str) -> None:
    """bash `chk` (wanted=True) / `nchk` (wanted=False) on a separator-normalized haystack."""
    haystack = out.replace("\\", "/")
    if wanted:
        assert needle in haystack, f"{label}: wanted substring {needle!r} in:\n{out}"
    else:
        assert needle not in haystack, (
            f"{label}: FORBIDDEN substring {needle!r} present in:\n{out}"
        )


def ids(cases: Sequence[Case]) -> List[str]:
    return [case[0] for case in cases]


def spawn_session_start(
    hooks_copy: Path, arena: Path, payload_text: str
) -> "subprocess.CompletedProcess[str]":
    """`python <copy>/hooks.py session-start` exactly as the harness spawns it: payload on stdin, cwd = arena.
    CLAUDE_PROJECT_DIR and PYTHONPATH are stripped so the child can neither write into the real project nor
    import the real library behind the copy's back."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("CLAUDE_PROJECT_DIR", "PYTHONPATH")
    }
    return subprocess.run(
        [sys.executable, str(hooks_copy / "hooks.py"), "session-start"],
        input=payload_text,
        capture_output=True,
        text=True,
        errors="replace",
        cwd=str(arena),
        env=env,
        timeout=120,
        check=False,
    )


def copy_hooks(dst: Path) -> Path:
    """A copy of the hooks directory (Python files + CONTRACT_VERSION + REVISION_NOTICE.md), like the bash
    suite's `cp` of the scripts into a scratch `hooks/`."""
    shutil.copytree(
        str(HOOKS),
        str(dst),
        ignore=shutil.ignore_patterns("tests", "__pycache__", "*.sh", "*.md"),
    )
    shutil.copy2(str(HOOKS / "REVISION_NOTICE.md"), str(dst / "REVISION_NOTICE.md"))
    return dst


@pytest.fixture
def arena(tmp_path: Path) -> Path:
    arena = tmp_path / "arena"
    arena.mkdir()
    reset(arena)
    return arena


@pytest.fixture
def pinned_clock(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(lib, "today_iso", lambda: AUTHORING_DATE)
    return AUTHORING_DATE


# ---------------------------------------------------------------------------------------------------------
# 1. UNREGISTERED, with a juicy sibling sitting right there. The old hook served 565 here.
# ---------------------------------------------------------------------------------------------------------

CASE1: List[Case] = [
    ("contract is always injected", "Continuous work is in force", True),
    ("revision notice delivered while valid", "FRAMEWORK REVISION", True),
    ("unregistered says so plainly", "No orchestrator/spec run is registered", True),
    ("does NOT leak the sibling's issue number", "565", False),
    ("does NOT leak the sibling's branch", "fix-issue-565", False),
    ("does NOT leak the sibling's run dir", "54a2387f", False),
]


@pytest.mark.parametrize("label, needle, wanted", CASE1, ids=ids(CASE1))
def test_case1_unregistered_with_sibling(
    arena: Path, pinned_clock: str, label: str, needle: str, wanted: bool
) -> None:
    sibling(arena)
    check(label, needle, wanted, run_gate(arena, payload(arena)))


# ---------------------------------------------------------------------------------------------------------
# 2. BROKEN: registry declares a run, nothing on disk. Sibling still present.
# ---------------------------------------------------------------------------------------------------------

CASE2: List[Case] = [
    ("broken identity is reported as unreadable", "CANNOT BE READ", True),
    ("broken names the exact path to create", "runs/5db650ab", True),
    ("broken warns the next gate will refuse", "REFUSE", True),
    ("broken forbids inventing a label", "do NOT invent a readable run-id label", True),
    ("broken does NOT leak the sibling's issue", "565", False),
]


@pytest.mark.parametrize("label, needle, wanted", CASE2, ids=ids(CASE2))
def test_case2_broken_registered_without_state(
    arena: Path, label: str, needle: str, wanted: bool
) -> None:
    sibling(arena)
    register(arena)
    check(label, needle, wanted, run_gate(arena, payload(arena)))


def test_case2_broken_names_the_exact_native_path(arena: Path) -> None:
    """(extra) "names the exact path to create" taken literally: the registry-declared resume_state.md path,
    in the form the agent must pass to its own tools."""
    sibling(arena)
    register(arena)
    expected = orch(arena) / "runs" / MY_RUN / lib.RESUME_FILENAME
    assert str(expected) in run_gate(arena, payload(arena))


# ---------------------------------------------------------------------------------------------------------
# 3. OWNED: my own state exists at the registry-declared path. The SIBLING is touched LAST on purpose —
#    resolution is session-keyed, so an mtime rung would pick the sibling and this would fail.
# ---------------------------------------------------------------------------------------------------------

CASE3: List[Case] = [
    ("owned reports MY issue", "574", True),
    ("owned reports MY branch", "fix-issue-574-logging-floor", True),
    ("owned ignores the NEWER sibling entirely", "565", False),
    ("owned tells the agent to reconcile with reality", "reality wins", True),
    ("owned explains the append-at-end rule", "LAST occurrence", True),
]


@pytest.mark.parametrize("label, needle, wanted", CASE3, ids=ids(CASE3))
def test_case3_owned_ignores_newer_sibling(
    arena: Path, label: str, needle: str, wanted: bool
) -> None:
    mine = write_state(arena, MY_RUN, MY_STATE)
    register(arena)
    newer = sibling(
        arena
    )  # touched AFTER mine, so an mtime rung would pick the sibling
    assert newer.stat().st_mtime > mine.stat().st_mtime, (
        "test setup: the sibling must be the newer file"
    )
    check(label, needle, wanted, run_gate(arena, payload(arena)))


# ---------------------------------------------------------------------------------------------------------
# 4. Identity recovery: state under an AGENT-INVENTED dir, findable only by SESSION_ID.
# ---------------------------------------------------------------------------------------------------------

CASE4: List[Case] = [
    ("invented dir recovered via SESSION_ID", "574", True),
    ("recovery still ignores the sibling", "565", False),
]


@pytest.mark.parametrize("label, needle, wanted", CASE4, ids=ids(CASE4))
def test_case4_invented_dir_recovered_by_session_id(
    arena: Path, label: str, needle: str, wanted: bool
) -> None:
    write_state(arena, "run-issue574-20260828T194800Z", MY_STATE_SHORT)
    register(arena)  # declares runs/5db650ab/, which does not exist
    sibling(arena)
    check(label, needle, wanted, run_gate(arena, payload(arena)))


# ---------------------------------------------------------------------------------------------------------
# 5. No session id at all.
# ---------------------------------------------------------------------------------------------------------

CASE5: List[Case] = [
    ("no session id -> says it cannot identify the run", "cannot be identified", True),
    ("no session id -> still no sibling leak", "565", False),
]


@pytest.mark.parametrize("label, needle, wanted", CASE5, ids=ids(CASE5))
def test_case5_no_session_id(
    arena: Path, label: str, needle: str, wanted: bool
) -> None:
    sibling(arena)
    check(
        label,
        needle,
        wanted,
        run_gate(arena, payload(arena, sid=None, source="startup")),
    )


# ---------------------------------------------------------------------------------------------------------
# 6. THE THREE DELIVERY INVARIANTS. Each is a documented way for a SessionStart hook's text to be silently
#    DISCARDED — no error the agent can see — so each is pinned rather than trusted. Checked on the dispatcher,
#    which is what the harness runs.
# ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def owned_arena(arena: Path) -> Path:
    write_state(arena, MY_RUN, MY_STATE_SHORT)
    register(arena)
    return arena


def test_case6a_invariant_exits_0(owned_arena: Path) -> None:
    """invariant: exits 0 (SessionStart stderr never reaches the agent). For SessionStart, exit 2 shows stderr
    TO THE USER ONLY — Claude never sees it — so a non-zero exit would deliver nothing to the agent."""
    decision = dispatch(owned_arena, payload(owned_arena))
    assert decision.exit_code == 0, (
        f"expected exit 0, got {decision.exit_code}: {decision.stderr}"
    )


def test_case6b_invariant_stdout_is_plain_text_not_json_shaped(
    owned_arena: Path,
) -> None:
    """invariant: stdout is plain text, not JSON-shaped. Stdout that starts with '{' AND ends with '}' is
    PARSED as JSON, and on a parse failure the text is not added at all."""
    decision = dispatch(owned_arena, payload(owned_arena))
    assert decision.stdout.strip(), "nothing was delivered at all"
    assert not decision.stdout.startswith("{"), (
        "stdout begins with { and may be parsed as JSON"
    )


def test_case6c_invariant_stdout_under_the_10000_char_cap(owned_arena: Path) -> None:
    """invariant: stdout under the 10000-char cap; past it the text is replaced by a path + preview, which
    reads as delivered but is not. Counted in bytes like `wc -c`, which is the stricter reading."""
    decision = dispatch(owned_arena, payload(owned_arena))
    size = len(decision.stdout.encode("utf-8"))
    assert size < 10000, f"stdout is {size} bytes, at/over the 10000 cap"


def test_case6_dispatch_delivers_contract_and_my_state(owned_arena: Path) -> None:
    """(extra) The dispatcher's concatenated context carries the contract and THIS session's place — the shape
    invariants above are not satisfied vacuously by some other gate's output."""
    decision = dispatch(owned_arena, payload(owned_arena))
    assert "Continuous work is in force" in decision.stdout
    assert "574" in decision.stdout
    assert decision.exit_code == 0


# ---------------------------------------------------------------------------------------------------------
# 6b. An EXPIRED revision notice is not delivered: the `Valid-until:` line retires it, so a rollout notice
#     cannot outlive its rollout and load into every session forever.
# ---------------------------------------------------------------------------------------------------------

CASE6B: List[Case] = [
    ("expired revision notice is NOT delivered", "FRAMEWORK REVISION", False),
    ("contract still delivered without a notice", "Continuous work is in force", True),
]


@pytest.mark.parametrize("label, needle, wanted", CASE6B, ids=ids(CASE6B))
def test_case6b_expired_revision_notice(
    arena: Path, tmp_path: Path, label: str, needle: str, wanted: bool
) -> None:
    expired = tmp_path / "expired" / "hooks"
    expired.mkdir(parents=True)
    (expired / "REVISION_NOTICE.md").write_text(
        "Valid-until: 2000-01-01\n## FRAMEWORK REVISION long gone\n", encoding="utf-8"
    )
    check(
        label,
        needle,
        wanted,
        run_gate(arena, payload(arena, sid="x", source="startup"), hooks_dir=expired),
    )


def test_revision_notice_valid_until_boundary(tmp_path: Path) -> None:
    """(extra) `revision_notice(hooks_dir, today=...)`: delivered ON the Valid-until day, retired the day after,
    and the `Valid-until:` line itself is never part of the delivered body."""
    (tmp_path / "REVISION_NOTICE.md").write_text(
        "Valid-until: 2000-01-01\n## FRAMEWORK REVISION long gone\n", encoding="utf-8"
    )
    on_the_day = lib.revision_notice(tmp_path, today="2000-01-01")
    assert on_the_day is not None and "FRAMEWORK REVISION long gone" in on_the_day
    assert "Valid-until" not in on_the_day
    assert lib.revision_notice(tmp_path, today="2000-01-02") is None


def test_real_revision_notice_delivered_inside_its_window() -> None:
    """(extra) The notice shipped in the hooks directory is delivered on the suite's authoring date and is
    retired after its own Valid-until line, read from the file rather than hard-coded."""
    first = lib.read_text(HOOKS / "REVISION_NOTICE.md").splitlines()[0]
    assert first.lower().startswith("valid-until:"), (
        "REVISION_NOTICE.md must open with a Valid-until line"
    )
    until = first.split(":", 1)[1].strip()
    delivered = lib.revision_notice(HOOKS, today=AUTHORING_DATE)
    assert delivered is not None and "FRAMEWORK REVISION" in delivered
    assert lib.revision_notice(HOOKS, today=until) is not None
    assert lib.revision_notice(HOOKS, today="2999-12-31") is None


# ---------------------------------------------------------------------------------------------------------
# 7. A missing library must never break startup (SessionStart cannot block).
# ---------------------------------------------------------------------------------------------------------


def test_case7_no_library_exits_0(arena: Path, tmp_path: Path) -> None:
    """no library -> exit 0 (never breaks startup). A hooks copy WITHOUT hooklib.py, spawned exactly as the
    harness spawns it."""
    broke = copy_hooks(tmp_path / "broke" / "hooks")
    (broke / "hooklib.py").unlink()
    completed = spawn_session_start(broke, arena, '{"session_id":"x","cwd":"."}')
    assert completed.returncode == 0, (
        f"no library -> expected exit 0, got {completed.returncode}\nstderr:\n{completed.stderr[-600:]}"
    )


def test_case7_truncated_library_exits_0_without_a_crash(
    arena: Path, tmp_path: Path
) -> None:
    """(extra) A hooks copy whose hooklib.py is truncated before `def selftest` (the deliberate last definition,
    so a copy that lacks it is treated as a broken library) must still never break startup: exit 0 and no
    uncaught traceback. The dispatcher's documented degraded path delivers nothing here; the spec requires only
    that SessionStart cannot fail."""
    broke = copy_hooks(tmp_path / "truncated" / "hooks")
    source = (HOOKS / "hooklib.py").read_text(encoding="utf-8")
    marker = source.index("\ndef selftest")
    (broke / "hooklib.py").write_text(source[: marker + 1], encoding="utf-8")
    assert "def selftest" not in (broke / "hooklib.py").read_text(encoding="utf-8")
    completed = spawn_session_start(broke, arena, '{"session_id":"x","cwd":"."}')
    assert completed.returncode == 0, (
        f"truncated library -> expected exit 0, got {completed.returncode}\n{completed.stderr}"
    )
    assert "Traceback" not in completed.stderr, (
        f"uncaught exception on startup:\n{completed.stderr}"
    )
