"""pytest port of test_gate_overblock.sh — regression suite for the OVER-BLOCKING defects.

WHY A SEPARATE FILE FROM test_stop_gates.py: that suite asks "does the gate block when it should?". This one
asks the opposite question, and the two failure directions are not equally visible. A gate that fails OPEN is
discovered when work is lost. A gate that over-blocks is discovered when a human, mid-task, cannot end a turn —
and the remedy they reach for is to DELETE THE HOOK. An over-blocking gate is therefore not a milder bug than a
fail-open; it is the bug that removes the fail-open protection too.

Each case names the finding it pins (F1..F17); all were measured against the shipped hooks before the fix. The
bash suite is the SPECIFICATION: every bash `check` is one pytest assertion here, with its label kept.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict, Optional

import pytest

import gate_issue_loop
import gate_session_register
import gate_spec_stop
import hooklib as lib

HOOKS_DIR = Path(__file__).resolve().parent.parent
SID = "abcd1234-1111-2222-3333-444455556666"
RUN8 = "abcd1234"


def contract_version_text() -> str:
    first = (HOOKS_DIR / "CONTRACT_VERSION").read_text(encoding="utf-8").splitlines()[0]
    return "".join(first.split())


class Arena:
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
        self,
        run: str,
        status: str,
        phase: str,
        awaiting: str,
        remain: str,
        issue: str = "999",
    ) -> None:
        run_dir = self.orch / "runs" / run
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / lib.RESUME_FILENAME).write_text(
            "# Resume state\n"
            f"SESSION_ID: {SID}\n"
            f"RUN_ID: {RUN8}\n"
            "MODE: unset\n"
            f"Status: {status}\n"
            f"Phase: {phase}\n"
            f"AWAITING_USER: {awaiting}\n"
            f"WORKABLE_ISSUES_REMAIN: {remain}\n"
            f"CURRENT_ISSUE: {issue}\n",
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
            "Status: IN_PROGRESS\n"
            "CURRENT_TASK: 1\n",
            encoding="utf-8",
        )

    def ack(self, run: str) -> None:
        ack = self.orch / "runs" / run / f"contract-ack-{contract_version_text()}"
        ack.write_text("test ack\n", encoding="utf-8")

    def append(self, run: str, line: str) -> None:
        """Append one `Name: value` line to resume_state.md — the way the hooks tell the agent to correct a field."""
        with (self.orch / "runs" / run / lib.RESUME_FILENAME).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def counter(self, name: str) -> Path:
        return self.orch / ".stop-gate-counters" / f"{name}-{RUN8}.count"

    def spec_dir(self, name: str = "demo") -> Path:
        return self.root / ".claude" / "specs" / name

    def payload(self) -> str:
        return json.dumps({"session_id": SID, "cwd": self.root.as_posix(), "hook_event_name": "Stop"})

    def ctx(self, payload: Optional[str] = None, environ: Optional[Dict[str, str]] = None) -> lib.Context:
        return lib.Context(
            lib.Payload.parse(self.payload() if payload is None else payload),
            environ={} if environ is None else environ,
            hooks_dir=HOOKS_DIR,
            cwd=self.root,
        )

    def loop(self) -> lib.Decision:
        return gate_issue_loop.run(self.ctx())

    def spec(self) -> lib.Decision:
        return gate_spec_stop.run(self.ctx())

    def register_session(self) -> lib.Decision:
        """session-register on a SessionStart payload — what the bash piped into session-register.sh."""
        payload = json.dumps({"session_id": SID, "source": "startup", "cwd": self.root.as_posix()})
        return gate_session_register.run(self.ctx(payload))


@pytest.fixture
def arena(tmp_path: Path) -> Arena:
    return Arena(tmp_path / "arena")


def _seed_working_run(arena: Arena) -> None:
    """register + seed IN_PROGRESS/FIX/none/no + ack: a run that has claimed issue 999 and is mid-work."""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.ack(RUN8)


# =========================================================================================================
# issue-loop-gate
# =========================================================================================================


def test_f5_unacked_contract_with_not_started_allows(arena: Arena) -> None:
    """F5  unacked contract + NOT_STARTED -> allow

    The contract handshake was evaluated BEFORE the benign checks, so a routine CONTRACT_VERSION bump refused
    the next turn-end of EVERY live session in the clone, ordinary chat sessions included."""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "NOT_STARTED", "NOT_STARTED", "none", "unknown", issue="none")
    assert arena.loop().exit_code == 0


def test_f7_in_progress_with_no_tracked_work_claimed_allows(arena: Arena) -> None:
    """F7  IN_PROGRESS, no tracked work claimed -> allow

    Status IN_PROGRESS alone must not hold a turn. Measured: an ordinary session that recorded a Status was told
    to "FINISH issue none end to end"."""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "WORKING", "none", "unknown", issue="none")
    arena.ack(RUN8)
    assert arena.loop().exit_code == 0


def test_f7_claim_by_current_issue_blocks(arena: Arena) -> None:
    """F7  claim by CURRENT_ISSUE -> BLOCK"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "WORKING", "none", "unknown", issue="574")
    arena.ack(RUN8)
    assert arena.loop().exit_code == 2


def test_f7_claim_by_mode_blocks(arena: Arena) -> None:
    """F7  claim by MODE -> BLOCK"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "WORKING", "none", "unknown", issue="none")
    arena.ack(RUN8)
    arena.append(RUN8, "MODE: SINGLE_ISSUE")
    assert arena.loop().exit_code == 2


def test_f7_claim_by_current_spec_blocks(arena: Arena) -> None:
    """F7  claim by CURRENT_SPEC -> BLOCK"""
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "WORKING", "none", "unknown", issue="none")
    arena.ack(RUN8)
    arena.append(RUN8, "CURRENT_SPEC: .claude/specs/demo")
    assert arena.loop().exit_code == 2


def test_f14_narrative_status_blocks_and_the_named_escape_allows(arena: Arena) -> None:
    """F14 narrative Status -> BLOCK (whole-value match); F14 the named escape 'Status: COMPLETED' -> allow

    A terminal value must be the WHOLE value, and a narrative Status BLOCKS: a whole-value match costs a
    spurious refusal that names its own escape, while a substring match hands the agent a way to end a turn by
    writing a progress note."""
    _seed_working_run(arena)
    arena.append(RUN8, "Status: COMPLETED (was IN_PROGRESS)")
    assert arena.loop().exit_code == 2, "F14 narrative Status -> BLOCK (whole-value match)"
    arena.append(RUN8, "Status: COMPLETED")
    assert arena.loop().exit_code == 0, "F14 the named escape 'Status: COMPLETED' -> allow"


def test_f14_in_progress_narrative_mentioning_completed_blocks(arena: Arena) -> None:
    """F14 'IN_PROGRESS - tasks 1-3 completed' -> BLOCK

    The mirror image must NOT release: a narrative that merely mentions a terminal word while saying it is
    working is exactly the fail-open the whole-value match closes."""
    _seed_working_run(arena)
    arena.append(RUN8, "Status: IN_PROGRESS - tasks 1-3 completed, 4 remaining")
    assert arena.loop().exit_code == 2


def test_f14_status_not_in_progress_allows(arena: Arena) -> None:
    """F14 Status 'NOT_IN_PROGRESS' -> allow (an unambiguous negation IS in the idle vocabulary)"""
    _seed_working_run(arena)
    arena.append(RUN8, "Status: NOT_IN_PROGRESS")
    assert arena.loop().exit_code == 0


@pytest.mark.parametrize("phase_word", ["COMPLETE", "FINISHED", "CLOSED", "CANCELLED"])
def test_f14_terminal_phase_synonym_allows(arena: Arena, phase_word: str) -> None:
    """F14 terminal Phase synonym '<word>' -> allow (anchored against only four words, an agent was refused
    for its wording)"""
    _seed_working_run(arena)
    arena.append(RUN8, f"Phase: {phase_word}")
    assert arena.loop().exit_code == 0


def test_f14_waiting_to_be_done_is_not_terminal_blocks(arena: Arena) -> None:
    """F14 'waiting to be DONE' is NOT terminal -> BLOCK (a narrative MENTION of a terminal word is not a
    terminal phase)"""
    _seed_working_run(arena)
    arena.append(RUN8, "Phase: waiting to be DONE")
    assert arena.loop().exit_code == 2


def test_f17_awaiting_user_none_with_trailing_spaces_blocks(arena: Arena) -> None:
    """F17 AWAITING_USER 'none   ' no longer releases -> BLOCK

    One invisible trailing space made `none` compare unequal to `none`, which DISABLED the primary brake."""
    _seed_working_run(arena)
    arena.append(RUN8, "AWAITING_USER: none   ")
    assert arena.loop().exit_code == 2


def test_f17_real_escalation_with_trailing_spaces_allows(arena: Arena) -> None:
    """F17 a real escalation still releases -> allow (trailing whitespace tolerated)"""
    _seed_working_run(arena)
    arena.append(RUN8, "AWAITING_USER: genuine design fork   ")
    assert arena.loop().exit_code == 0


def test_f2_cap_is_durable_and_progress_rearms(arena: Arena) -> None:
    """F2  at cap -> allow; next turn ALSO allows (not a duty cycle); and the turn after that; progress clears
    the marker (allow, and resets); gate re-arms after progress -> BLOCK

    The cap must be DURABLE. Resetting the counter on the allow path made it an 8-block duty cycle: measured 8
    refusals, 1 release, then 8 more, forever. But genuine progress must RE-ARM the gate, or the marker would be
    a permanent off-switch."""
    _seed_working_run(arena)
    arena.counter("loop").parent.mkdir(parents=True)
    arena.counter("loop").write_text("8", encoding="utf-8")
    assert arena.loop().exit_code == 0, "F2  at cap -> allow"
    assert arena.loop().exit_code == 0, "F2  next turn ALSO allows (not a duty cycle)"
    assert arena.loop().exit_code == 0, "F2  and the turn after that"
    arena.append(RUN8, "Phase: DONE")
    assert arena.loop().exit_code == 0, "F2  progress clears the marker (allow, and resets)"
    arena.append(RUN8, "Phase: FIX")
    assert arena.loop().exit_code == 2, "F2  gate re-arms after progress -> BLOCK"


def test_f1_unwritable_counter_allows_rather_than_escapeless_block(
    arena: Arena,
) -> None:
    """F1  unwritable counter -> allow, not an escapeless block

    An unwritable counter means the cap can NEVER be reached, so a block would have no escape at all."""
    _seed_working_run(arena)
    arena.counter("loop").mkdir(parents=True)  # a DIRECTORY at the counter's own path
    assert arena.loop().exit_code == 0


# =========================================================================================================
# spec-stop-gate
# =========================================================================================================


def _seed_implementing(
    arena: Arena,
    phase: str,
    spec: str = ".claude/specs/demo",
    make_spec_dir: bool = True,
) -> None:
    arena.register(f"runs/{RUN8}/")
    arena.seed_state(RUN8, "IN_PROGRESS", "FIX", "none", "no")
    arena.seed_workflow(RUN8, phase, spec)
    if make_spec_dir:
        arena.spec_dir().mkdir(parents=True, exist_ok=True)


def test_f4_recorded_escalation_releases_the_spec_gate(arena: Arena) -> None:
    """F4  IMPLEMENT + no tasks.md -> BLOCK (baseline); F4  + recorded escalation -> allow

    (CRITICAL) The spec gate never read AWAITING_USER, while the re-inject hook and the contract text the loop
    gate delivers BOTH instruct the agent to record exactly that field. Measured: the loop gate allowed and this
    gate still refused, telling the agent to "continue"."""
    _seed_implementing(arena, "IMPLEMENT")
    assert arena.spec().exit_code == 2, "F4  IMPLEMENT + no tasks.md -> BLOCK (baseline)"
    arena.append(RUN8, "AWAITING_USER: genuine design fork on the retry policy")
    assert arena.spec().exit_code == 0, "F4  + recorded escalation -> allow"


@pytest.mark.parametrize("bad_phase", ["NOT_IMPLEMENTED", "PRE_IMPLEMENT_REVIEW", "IMPLEMENTATION_PLANNING"])
def test_f13_phase_that_is_not_implementation_allows(arena: Arena, bad_phase: str) -> None:
    """F13 phase '<bad_phase>' is not implementation -> allow (the phase test was an unanchored substring, so
    phases meaning the OPPOSITE demanded a task list)"""
    _seed_implementing(arena, bad_phase)
    assert arena.spec().exit_code == 0


@pytest.mark.parametrize("good_phase", ["IMPLEMENT", "IMPLEMENTING", "VERIFY", "VERIFYING"])
def test_f13_genuine_implementation_phase_blocks(arena: Arena, good_phase: str) -> None:
    """F13 phase '<good_phase>' IS implementation -> BLOCK"""
    _seed_implementing(arena, good_phase)
    assert arena.spec().exit_code == 2


def test_f9_placeholder_spec_at_implement_blocks_about_the_spec_not_the_path(
    arena: Arena,
) -> None:
    """F9  CURRENT_SPEC 'none' at IMPLEMENT -> BLOCK (spec unrecorded); F9  ...and NOT about the path
    'none/tasks.md'

    A placeholder CURRENT_SPEC must be treated as ABSENT rather than as a literal path: treating `none` as a
    path refused every turn-end on `none/tasks.md`, which nothing could create. ABSENT at an IMPLEMENTATION phase
    is itself refused, with BOTH escapes named."""
    _seed_implementing(arena, "IMPLEMENT", spec="none", make_spec_dir=False)
    decision = arena.spec()
    assert decision.exit_code == 2, "F9  CURRENT_SPEC 'none' at IMPLEMENT -> BLOCK (spec unrecorded)"
    assert "none/tasks.md" not in decision.stderr, "F9  ...and NOT about the path 'none/tasks.md'"


def test_f9_placeholder_spec_outside_implement_allows(arena: Arena) -> None:
    """F9  CURRENT_SPEC 'none' outside IMPLEMENT -> allow (simply nothing to judge)"""
    _seed_implementing(arena, "DESIGN", spec="none", make_spec_dir=False)
    assert arena.spec().exit_code == 0


def test_f8_spec_inside_recorded_worktree_is_found_and_judged(arena: Arena) -> None:
    """F8  spec inside a recorded WORKTREE is found -> allow; F8  worktree spec with missing evidence -> BLOCK

    For the orchestrator flow the spec lives inside a per-issue WORKTREE while the project dir is the main
    checkout. Measured: a real spec with a real tasks.md and a green capture was refused on every turn."""
    _seed_implementing(arena, "IMPLEMENT", spec=".claude/specs/retry", make_spec_dir=False)
    worktree = arena.root / ".claude" / "worktrees" / "issue-42"
    arena.append(RUN8, f"WORKTREE: {worktree.as_posix()}")
    spec = worktree / ".claude" / "specs" / "retry"
    (spec / "evidence" / "green").mkdir(parents=True)
    (spec / "tasks.md").write_text("- [x] 1 do the thing\n", encoding="utf-8")
    (spec / "evidence" / "green" / "1.txt").write_text("5 passed in 1.0s\n", encoding="utf-8")
    assert arena.spec().exit_code == 0, "F8  spec inside a recorded WORKTREE is found -> allow"
    (spec / "evidence" / "green" / "1.txt").unlink()  # ...and the worktree spec must still be JUDGED
    assert arena.spec().exit_code == 2, "F8  worktree spec with missing evidence -> BLOCK"


def test_f8b_unresolvable_current_spec_allows(arena: Arena) -> None:
    """F8b unresolvable CURRENT_SPEC -> allow (cannot judge): the gate cannot SEE the work, which is not the
    same as the work being unproven"""
    _seed_implementing(arena, "IMPLEMENT", spec=".claude/specs/nowhere-at-all", make_spec_dir=False)
    assert arena.spec().exit_code == 0


@pytest.mark.parametrize(
    "label, capture, expected",
    [
        (
            "F10 a test NAME containing 'skipped' -> allow",
            "test_reports_skipped_reason PASSED\n1000 passed in 12s\n",
            0,
        ),
        (
            "F10 a COMMENT mentioning failures -> allow",
            "# earlier this run: 3 failed, now fixed\n1000 passed in 12s\n",
            0,
        ),
        (
            "F10 a real '1 skipped' summary -> BLOCK",
            "999 passed, 1 skipped in 12s\n",
            2,
        ),
        ("F10 a real '3 failed' summary -> BLOCK", "997 passed, 3 failed in 12s\n", 2),
        ("F10 a real '2 errors' summary -> BLOCK", "2 errors, 5 passed in 12s\n", 2),
        (
            "F10 explicit ZERO counters -> allow",
            "1000 passed, 0 failed, 0 skipped in 12s\n",
            0,
        ),
    ],
)
def test_f10_evidence_predicates_anchor_on_a_counter_not_a_word(
    arena: Arena, label: str, capture: str, expected: int
) -> None:
    """F10 — the evidence predicates matched a bare WORD anywhere in the capture, so a test NAME or a comment
    blocked the turn. The only escape was to EDIT THE EVIDENCE FILE, i.e. to falsify the proof."""
    _seed_implementing(arena, "IMPLEMENT")
    green = arena.spec_dir() / "evidence" / "green"
    green.mkdir(parents=True)
    (arena.spec_dir() / "tasks.md").write_text("- [x] 1 do the thing\n", encoding="utf-8")
    (green / "1.txt").write_text(capture, encoding="utf-8")
    assert arena.spec().exit_code == expected, label


# =========================================================================================================
# session-register — a seeding failure must leave the session INERT, not WEDGED
# =========================================================================================================


def test_f6_seeding_failure_leaves_the_session_inert(arena: Arena) -> None:
    """F6  register exits 0 when seeding is impossible; registry left UNTOUCHED (so the session is inert);
    loop gate therefore does NOT block; spec gate therefore does NOT block

    The registry entry was written BEFORE the state was seeded, and a seeding failure was a silent exit 0. That
    MANUFACTURED the BROKEN identity both gates fail closed on: with `runs` occupied by a regular file, the
    registry held a complete entry, no state existed, and BOTH gates refused every turn-end."""
    (arena.orch / "runs").write_text("not a directory\n", encoding="utf-8")
    assert arena.register_session().exit_code == 0, "F6  register exits 0 when seeding is impossible"
    registry = (arena.orch / "registry.json").read_text(encoding="utf-8")
    assert SID not in registry, "F6  registry left UNTOUCHED (so the session is inert)"
    assert arena.loop().exit_code == 0, "F6  loop gate therefore does NOT block"
    assert arena.spec().exit_code == 0, "F6  spec gate therefore does NOT block"


def test_f6_happy_path_seeds_and_registers(arena: Arena) -> None:
    """F6  happy path seeds the state file; writes the registry entry; a freshly seeded session is not blocked"""
    arena.register_session()
    assert (arena.orch / "runs" / RUN8 / lib.RESUME_FILENAME).is_file(), "F6  happy path seeds the state file"
    registry = (arena.orch / "registry.json").read_text(encoding="utf-8")
    assert SID in registry, "F6  happy path writes the registry entry"
    assert arena.loop().exit_code == 0, "F6  a freshly seeded session is not blocked"
