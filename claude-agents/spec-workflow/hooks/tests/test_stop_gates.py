"""pytest port of test_stop_gates.sh — the Stop gates against synthetic payloads.

Every case asserts an EXIT CODE, because that is the whole contract: 0 = allow the turn to end, 2 = block.
A case that "looks right" but returns 0 where it must return 2 is the exact class of defect these gates were
found to have, so the assertions are the point and the prose is not.

The bash suite is the SPECIFICATION: each test carries its bash label in the docstring. Where the bash ran one
gate SCRIPT and asserted its exit code, this port calls that gate's `run(ctx)` directly and asserts
`Decision.exit_code`. All state lives in a per-test `tmp_path` arena; the real checkout is never touched, and
`environ={}` keeps the real CLAUDE_PROJECT_DIR out of every gate.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

import pytest

import gate_issue_loop
import gate_spec_stop
import hooklib as lib

HOOKS_DIR = Path(__file__).resolve().parent.parent
SID = "abcd1234-1111-2222-3333-444455556666"
RUN8 = "abcd1234"
NO_SID_PAYLOAD = '{"cwd":"/x","hook_event_name":"Stop"}'


def contract_version_text() -> str:
    """First line of the real CONTRACT_VERSION with all whitespace removed — what the bash `ack` computed with
    `head -1 | tr -d` of CR, LF and spaces, so the ack file name the test writes is the one the gate computes."""
    first = (HOOKS_DIR / "CONTRACT_VERSION").read_text(encoding="utf-8").splitlines()[0]
    return "".join(first.split())


class Arena:
    """A scratch project tree: `.claude/agent-state/issue-work-orchestrator/registry.json` plus a copy of the
    real CONTRACT_VERSION under `.claude/hooks/`, exactly as the bash `reset_arena` built it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.orch = root / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME
        self.reset()

    def reset(self) -> None:
        shutil.rmtree(self.root / ".claude", ignore_errors=True)
        self.orch.mkdir(parents=True)
        (self.root / ".claude" / "hooks").mkdir(parents=True)
        (self.orch / "registry.json").write_text("{}", encoding="utf-8")
        shutil.copy(
            HOOKS_DIR / "CONTRACT_VERSION",
            self.root / ".claude" / "hooks" / "CONTRACT_VERSION",
        )

    def register(self, state_dir: str) -> None:
        entry = {SID: {"session_id": SID, "run_id": RUN8, "state_dir": state_dir}}
        (self.orch / "registry.json").write_text(json.dumps(entry), encoding="utf-8")

    def seed_state(
        self, run: str, status: str, phase: str, awaiting: str, remain: str
    ) -> None:
        run_dir = self.orch / "runs" / run
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / lib.RESUME_FILENAME).write_text(
            "# Resume state\n"
            f"SESSION_ID: {SID}\n"
            f"RUN_ID: {RUN8}\n"
            f"Status: {status}\n"
            f"Phase: {phase}\n"
            "CURRENT_ISSUE: 999\n"
            f"AWAITING_USER: {awaiting}\n"
            f"WORKABLE_ISSUES_REMAIN: {remain}\n",
            encoding="utf-8",
        )

    def seed_workflow(self, run: str, phase: str, spec: str) -> None:
        run_dir = self.orch / "runs" / run
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / lib.STATE_FILENAME).write_text(
            "# Workflow state\n"
            f"SESSION_ID: {SID}\n"
            f"CURRENT_SPEC: {spec}\n"
            f"Phase: {phase}\n"
            "Status: IN_PROGRESS\n",
            encoding="utf-8",
        )

    def ack(self, run: str) -> None:
        ack = self.orch / "runs" / run / f"contract-ack-{contract_version_text()}"
        ack.write_text("test ack\n", encoding="utf-8")

    def set_counter(self, name: str, value: str) -> None:
        counters = self.orch / ".stop-gate-counters"
        counters.mkdir(parents=True, exist_ok=True)
        (counters / f"{name}-{RUN8}.count").write_text(value, encoding="utf-8")

    def spec_dir(self, name: str = "demo") -> Path:
        return self.root / ".claude" / "specs" / name

    def payload(self) -> str:
        return json.dumps(
            {"session_id": SID, "cwd": self.root.as_posix(), "hook_event_name": "Stop"}
        )

    def ctx(
        self, payload: Optional[str] = None, environ: Optional[Dict[str, str]] = None
    ) -> lib.Context:
        return lib.Context(
            lib.Payload.parse(self.payload() if payload is None else payload),
            environ={} if environ is None else environ,
            hooks_dir=HOOKS_DIR,
            cwd=self.root,
        )

    def loop(self, payload: Optional[str] = None) -> lib.Decision:
        return gate_issue_loop.run(self.ctx(payload))

    def spec(self, payload: Optional[str] = None) -> lib.Decision:
        return gate_spec_stop.run(self.ctx(payload))


@pytest.fixture
def arena(tmp_path: Path) -> Arena:
    return Arena(tmp_path / "arena")


# =========================================================================================================
# issue-loop-gate — the PRIMARY brake
# =========================================================================================================


def test_loop_no_session_id_allows(arena: Arena) -> None:
    """no session_id in payload -> allow (cannot attribute)"""
    assert arena.loop(NO_SID_PAYLOAD).exit_code == 0


def test_loop_unregistered_session_allows(arena: Arena) -> None:
    """unregistered session (plain chat) -> allow"""
    assert arena.loop().exit_code == 0


def test_loop_registered_but_state_missing_blocks(arena: Arena) -> None:
    """REGISTERED but state file MISSING -> BLOCK (was the 189-session hole)"""
    arena.register(f"runs/{RUN8}/")
    assert arena.loop().exit_code == 2


def test_loop_contract_not_acknowledged_blocks(arena: Arena) -> None:
    """contract NOT acknowledged -> BLOCK (live-session migration)"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    assert arena.loop().exit_code == 2


def test_loop_acked_not_started_allows(arena: Arena) -> None:
    """acked + Status NOT_STARTED -> allow"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "NOT_STARTED", "NOT_STARTED", "none", "unknown")
    arena.ack(RUN8)
    assert arena.loop().exit_code == 0


def test_loop_acked_terminal_phase_done_allows(arena: Arena) -> None:
    """acked + IN_PROGRESS + terminal Phase DONE -> allow"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "DONE", "none", "no")
    arena.ack(RUN8)
    assert arena.loop().exit_code == 0


def test_loop_acked_awaiting_user_recorded_allows(arena: Arena) -> None:
    """acked + IN_PROGRESS + AWAITING_USER recorded -> allow"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "need a credential", "no")
    arena.ack(RUN8)
    assert arena.loop().exit_code == 0


def test_loop_acked_in_progress_remain_no_blocks(arena: Arena) -> None:
    """acked + IN_PROGRESS + non-terminal + remain=no -> BLOCK (the /work-issue hole)"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.ack(RUN8)
    assert arena.loop().exit_code == 2


def test_loop_acked_in_progress_remain_yes_blocks(arena: Arena) -> None:
    """acked + IN_PROGRESS + non-terminal + remain=yes -> BLOCK"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "yes")
    arena.ack(RUN8)
    assert arena.loop().exit_code == 2


def test_loop_at_block_cap_allows(arena: Arena) -> None:
    """at BLOCK_CAP -> allow (bounded, says work is not done)

    The counter is bumped per block; at the cap the gate allows so a session cannot wedge."""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.ack(RUN8)
    arena.set_counter("loop", "8")
    assert arena.loop().exit_code == 0


def test_loop_state_under_invented_dir_found_by_session_id_blocks(arena: Arena) -> None:
    """state under an invented dir, found by SESSION_ID -> BLOCK not shrug

    Identity recovery: state under an AGENT-INVENTED directory name, discoverable only via SESSION_ID."""
    invented = "run-issue574-20260828T194800Z"
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(invented, "IN_PROGRESS", "FIX", "none", "no")
    arena.ack(invented)
    assert arena.loop().exit_code == 2


# =========================================================================================================
# spec-stop-gate — the evidence gate
# =========================================================================================================


def test_spec_no_state_owned_allows(arena: Arena) -> None:
    """no state owned -> allow"""
    assert arena.spec().exit_code == 0


def test_spec_registered_but_no_state_at_all_blocks(arena: Arena) -> None:
    """REGISTERED but NO state at all -> BLOCK

    This case must create NO state files. Seeding resume_state.md would make identity OWNED; the BROKEN verdict
    is specifically "the registry declares a run and NOTHING exists"."""
    arena.register(f"runs/{RUN8}/")
    assert arena.spec().exit_code == 2


def test_spec_owns_resume_state_but_no_workflow_state_blocks(arena: Arena) -> None:
    """owns resume_state but NO workflow_state -> BLOCK

    An OWNED run with no workflow_state.md is the BROKEN condition one file down, not "no spec workflow here":
    session-register seeds BOTH files, so its absence means it was deleted or the seeding failed."""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    assert arena.spec().exit_code == 2


def test_spec_phase_design_allows(arena: Arena) -> None:
    """phase DESIGN (outside IMPLEMENT/VERIFY) -> allow"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.seed_workflow(RUN8, "DESIGN", ".claude/specs/demo")
    assert arena.spec().exit_code == 0


def test_spec_implement_with_tasks_absent_blocks(arena: Arena) -> None:
    """phase IMPLEMENT + tasks.md ABSENT -> BLOCK (was allow)"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.seed_workflow(RUN8, "IMPLEMENT", ".claude/specs/demo")
    arena.spec_dir().mkdir(parents=True)
    assert arena.spec().exit_code == 2


def test_spec_checked_task_without_capture_blocks(arena: Arena) -> None:
    """checked task with NO evidence capture -> BLOCK"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.seed_workflow(RUN8, "IMPLEMENT", ".claude/specs/demo")
    arena.spec_dir().mkdir(parents=True)
    (arena.spec_dir() / "tasks.md").write_text(
        "- [x] 1 do the thing\n", encoding="utf-8"
    )
    assert arena.spec().exit_code == 2


def test_spec_checked_task_with_green_capture_allows(arena: Arena) -> None:
    """checked task WITH a green capture -> allow"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.seed_workflow(RUN8, "IMPLEMENT", ".claude/specs/demo")
    green = arena.spec_dir() / "evidence" / "green"
    green.mkdir(parents=True)
    (arena.spec_dir() / "tasks.md").write_text(
        "- [x] 1 do the thing\n", encoding="utf-8"
    )
    (green / "1.txt").write_text("5 passed in 1.0s\n", encoding="utf-8")
    assert arena.spec().exit_code == 0


def test_spec_green_capture_containing_skip_blocks(arena: Arena) -> None:
    """green capture containing a SKIP -> BLOCK (vacuous green)"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.seed_workflow(RUN8, "IMPLEMENT", ".claude/specs/demo")
    green = arena.spec_dir() / "evidence" / "green"
    green.mkdir(parents=True)
    (arena.spec_dir() / "tasks.md").write_text(
        "- [x] 1 do the thing\n", encoding="utf-8"
    )
    (green / "1.txt").write_text("4 passed, 1 skipped in 1.0s\n", encoding="utf-8")
    assert arena.spec().exit_code == 2


def test_spec_parent_heading_needs_no_capture_allows(arena: Arena) -> None:
    """parent heading needs no capture of its own -> allow"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.seed_workflow(RUN8, "IMPLEMENT", ".claude/specs/demo")
    green = arena.spec_dir() / "evidence" / "green"
    green.mkdir(parents=True)
    (arena.spec_dir() / "tasks.md").write_text(
        "- [x] 0 parent heading\n- [x] 0.1 subtask\n", encoding="utf-8"
    )
    (green / "0.1.txt").write_text("5 passed\n", encoding="utf-8")
    assert arena.spec().exit_code == 0


def test_spec_wave_capture_naming_both_tasks_allows(arena: Arena) -> None:
    """wave capture naming both checked tasks -> allow

    WAVE captures: concurrently implemented tasks share ONE test run, so one capture proves several tasks.
    The `# tasks:` header names them."""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.seed_workflow(RUN8, "IMPLEMENT", ".claude/specs/demo")
    green = arena.spec_dir() / "evidence" / "green"
    green.mkdir(parents=True)
    (arena.spec_dir() / "tasks.md").write_text(
        "- [x] 1.1 TEST: parser\n- [x] 1.2 IMPL: parser\n", encoding="utf-8"
    )
    (green / "wave-1.txt").write_text(
        "# tasks: 1.1 1.2\n7 passed in 1.3s\n", encoding="utf-8"
    )
    assert arena.spec().exit_code == 0


def test_spec_checked_task_no_wave_capture_names_blocks(arena: Arena) -> None:
    """checked task no wave capture names -> BLOCK"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.seed_workflow(RUN8, "IMPLEMENT", ".claude/specs/demo")
    green = arena.spec_dir() / "evidence" / "green"
    green.mkdir(parents=True)
    (arena.spec_dir() / "tasks.md").write_text(
        "- [x] 1.1 TEST: parser\n- [x] 1.2 IMPL: parser\n- [x] 2.1 IMPL: writer\n",
        encoding="utf-8",
    )
    (green / "wave-1.txt").write_text(
        "# tasks: 1.1 1.2\n7 passed in 1.3s\n", encoding="utf-8"
    )
    assert arena.spec().exit_code == 2


def test_spec_wave_header_1_1_does_not_cover_task_1_10_blocks(arena: Arena) -> None:
    """wave header '1.1' does NOT cover task '1.10' -> BLOCK"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.seed_workflow(RUN8, "IMPLEMENT", ".claude/specs/demo")
    green = arena.spec_dir() / "evidence" / "green"
    green.mkdir(parents=True)
    (arena.spec_dir() / "tasks.md").write_text(
        "- [x] 1.10 IMPL: tenth\n", encoding="utf-8"
    )
    (green / "wave-1.txt").write_text(
        "# tasks: 1.1\n7 passed in 1.3s\n", encoding="utf-8"
    )
    assert arena.spec().exit_code == 2


# =========================================================================================================
# issue-loop-gate — FRAMEWORK FRESHNESS handshake (a fetched trunk carries a newer framework)
# =========================================================================================================
# A git fixture: the checkout's CONTRACT_VERSION is OLD while refs/remotes/origin/main carries a NEWER one —
# the state of every clone on a machine nobody has pulled on after the framework revision merged.

OLD_FRAMEWORK = "2000.01.01-contract-1"
NEW_FRAMEWORK = "9999.12.31-contract-9"


class Freshness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.orch = root / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME
        self.run_dir = self.orch / "runs" / RUN8

    def git(self, *args: str) -> None:
        # `core.hooksPath` points at an EMPTY directory: a machine-wide hook (measured: a corporate commit
        # scanner installed through the system git config) must not run against this throwaway fixture — it
        # stalled the `commit` for the full 60 s timeout, and nothing under test depends on git hooks.
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "-c",
                "commit.gpgsign=false",
                "-c",
                f"core.hooksPath={self.no_hooks.as_posix()}",
                *args,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )

    def build(self) -> None:
        self.root.mkdir(parents=True)
        self.no_hooks = self.root.parent / "no-hooks"
        self.no_hooks.mkdir()
        try:
            self.git("init", "-q", "-b", "main", ".")
        except subprocess.CalledProcessError:
            self.git("init", "-q", ".")
            self.git("checkout", "-q", "-b", "main")
        hooks = self.root / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "CONTRACT_VERSION").write_text(OLD_FRAMEWORK + "\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "checkout")
        (hooks / "CONTRACT_VERSION").write_text(NEW_FRAMEWORK + "\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "trunk")
        self.git(
            "update-ref", "refs/remotes/origin/main", "HEAD"
        )  # stands in for a fetch: the tracking ref is read
        self.git(
            "reset", "-q", "--hard", "HEAD~1"
        )  # the checkout stays on the OLD framework
        self.git(
            "remote", "add", "origin", str(self.root)
        )  # the scan walks `git remote`; a name is all it needs
        self.run_dir.mkdir(parents=True)
        (self.orch / "registry.json").write_text(
            json.dumps(
                {SID: {"session_id": SID, "run_id": RUN8, "state_dir": f"runs/{RUN8}/"}}
            ),
            encoding="utf-8",
        )
        (self.run_dir / lib.RESUME_FILENAME).write_text(
            f"SESSION_ID: {SID}\nRUN_ID: {RUN8}\nStatus: IN_PROGRESS\nPhase: FIX\nCURRENT_ISSUE: 999\n"
            "AWAITING_USER: none\nWORKABLE_ISSUES_REMAIN: yes\n",
            encoding="utf-8",
        )
        # the contract handshake is done
        (self.run_dir / f"contract-ack-{OLD_FRAMEWORK}").write_text(
            "test ack\n", encoding="utf-8"
        )

    def run(self) -> lib.Decision:
        payload = json.dumps(
            {"session_id": SID, "cwd": self.root.as_posix(), "hook_event_name": "Stop"}
        )
        ctx = lib.Context(
            lib.Payload.parse(payload), environ={}, hooks_dir=HOOKS_DIR, cwd=self.root
        )
        return gate_issue_loop.run(ctx)


@pytest.fixture
def fw(tmp_path: Path) -> Freshness:
    if shutil.which("git") is None:
        pytest.skip("the freshness handshake fixture needs git on PATH")
    fixture = Freshness(tmp_path / "fw")
    fixture.build()
    return fixture


def test_freshness_stale_framework_not_yet_told_blocks(fw: Freshness) -> None:
    """stale framework, not yet told -> BLOCK; the refusal names the trunk's framework version, gives the
    sanctioned fast-forward, and names the ack file to create"""
    decision = fw.run()
    assert decision.exit_code == 2
    assert f"FRAMEWORK REVISION {NEW_FRAMEWORK}" in decision.stderr, (
        "the refusal names the trunk's framework version"
    )
    assert "merge --ff-only origin/main" in decision.stderr, (
        "the refusal gives the sanctioned fast-forward"
    )
    assert f"framework-ack-{NEW_FRAMEWORK}" in decision.stderr, (
        "the refusal names the ack file to create"
    )


def test_freshness_told_once_falls_through_to_the_brake(fw: Freshness) -> None:
    """told once -> falls through to the brake on unfinished work -> BLOCK; a run already told is NOT told
    again; the brake, not the handshake, refuses the acked run"""
    fw.run()  # the first refusal delivers the notice
    (fw.run_dir / f"framework-ack-{NEW_FRAMEWORK}").write_text(
        "ack\n", encoding="utf-8"
    )
    decision = fw.run()
    assert decision.exit_code == 2
    assert "FRAMEWORK REVISION" not in decision.stderr, (
        "a run already told is NOT told again"
    )
    assert "records itself as UNFINISHED" in decision.stderr, (
        "the brake, not the handshake, refuses the acked run"
    )


def test_freshness_trunk_at_checkout_version_is_not_stale(fw: Freshness) -> None:
    """trunk at the checkout's own version -> no freshness refusal"""
    fw.git(
        "update-ref", "refs/remotes/origin/main", "HEAD"
    )  # trunk == checkout: nothing is stale
    for ack in fw.run_dir.glob("framework-ack-*"):
        ack.unlink()
    decision = fw.run()
    assert "FRAMEWORK REVISION" not in decision.stderr


# =========================================================================================================
# FAIL-CLOSED on a broken library (both gates)
# =========================================================================================================
# The bash ran each gate script with a PARTIAL library (truncated before its last function) and with NO library,
# and required exit 2 from each. In Python one interpreter (`hooks.py stop`) runs both Stop gates, so one spawn
# covers both: a copy of the hooks directory whose hooklib.py is truncated before `def selftest` (or missing)
# must make `python hooks.py stop` exit 2 — spawned exactly as the harness spawns it, with the payload on stdin.


def _hooks_copy(tmp_path: Path) -> Path:
    copy = tmp_path / "hooks-copy"
    copy.mkdir()
    for source in HOOKS_DIR.glob("*.py"):
        shutil.copy(source, copy / source.name)
    shutil.copy(HOOKS_DIR / "CONTRACT_VERSION", copy / "CONTRACT_VERSION")
    return copy


def _spawn_stop(copy: Path, arena: Arena) -> subprocess.CompletedProcess:
    # The spawned interpreter reads os.environ: keep the real project dir, cap and any PYTHONPATH out of it.
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONPATH", lib.CLAUDE.project_dir_env, lib.CLAUDE.block_cap_env)
    }
    return subprocess.run(
        [sys.executable, str(copy / "hooks.py"), "stop"],
        input=arena.payload(),
        capture_output=True,
        text=True,
        cwd=str(arena.root),
        env=env,
        timeout=120,
        check=False,
    )


def test_fail_closed_control_healthy_copy_allows(arena: Arena, tmp_path: Path) -> None:
    """control (not in the bash suite): with an INTACT library the same spawn against an unregistered arena
    allows, so the two refusals below can only come from the broken library"""
    completed = _spawn_stop(_hooks_copy(tmp_path), arena)
    assert completed.returncode == 0, completed.stderr


def test_fail_closed_partial_library_blocks(arena: Arena, tmp_path: Path) -> None:
    """issue-loop-gate / spec-stop-gate with a PARTIAL library -> BLOCK (fail closed)"""
    copy = _hooks_copy(tmp_path)
    library = copy / "hooklib.py"
    text = library.read_text(encoding="utf-8")
    library.write_text(
        text[: text.index("def selftest")], encoding="utf-8"
    )  # deliberately truncated: no selftest
    completed = _spawn_stop(copy, arena)
    assert completed.returncode == 2, (
        f"exit {completed.returncode}; stderr: {completed.stderr[-400:]}"
    )
    # Not in the bash suite: the exit 2 must be the gate's refusal naming the broken library, not the
    # interpreter's own exit 2 for a script it could not open.
    assert "hooklib" in completed.stderr, completed.stderr[-400:]


def test_fail_closed_missing_library_blocks(arena: Arena, tmp_path: Path) -> None:
    """issue-loop-gate / spec-stop-gate with NO library at all -> BLOCK (fail closed)"""
    copy = _hooks_copy(tmp_path)
    (copy / "hooklib.py").unlink()
    completed = _spawn_stop(copy, arena)
    assert completed.returncode == 2, (
        f"exit {completed.returncode}; stderr: {completed.stderr[-400:]}"
    )
    assert "hooklib" in completed.stderr, completed.stderr[-400:]
