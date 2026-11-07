"""Port of tests/test_unpinned_fixes.sh — pins for behaviours that were CORRECT in the code but guarded by NOTHING.

WHY THIS FILE EXISTS
--------------------
An adversarial verification pass mutated the shipped hooks and re-ran every assertion. Three mutations SURVIVED
the entire suite set — three fixes that were real in the code and unprotected by any test:

  1. The contract handshake's BLOCK direction. "contract NOT acknowledged -> BLOCK" seeds a state the MAIN
     BRAKE also blocks, so the exit 2 it observes proves nothing about the handshake.
  2. Defect class 10 — existence of an evidence file read as PROOF. A zero-byte capture counted as proof.
  3. Per-task failure scanning in the evidence gate. Only the MOST RECENTLY TOUCHED capture was scanned, so
     `3 failed, 5 passed` in an older task's capture was accepted — proven by mtime alone.

An unpinned fix is a fix that regresses silently, so these get assertions of their own. Where the exit code
cannot distinguish two causes, these cases assert on the REFUSAL TEXT as well, because that is what actually
identifies which gate fired. The bash suite is the SPECIFICATION; every one of its 32 assertions (`check`,
`has`, `hasnt`) appears here once, under the same label.

Each bash case needs ONE gate's verdict, so the gates are called directly: gate_issue_loop.run(ctx) for
issue-loop-gate.sh and gate_spec_stop.run(ctx) for spec-stop-gate.sh.

Standard library + pytest only; Python 3.9 compatible.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import gate_issue_loop  # noqa: E402
import gate_spec_stop  # noqa: E402
import hooklib as lib  # noqa: E402

SID = "abcd1234-1111-2222-3333-444455556666"
RUN8 = "abcd1234"
ALLOW = 0
BLOCK = 2

DEPLOYED_VERSION = "".join((HOOKS_DIR / "CONTRACT_VERSION").read_text(encoding="utf-8").splitlines()[0].split())

HANDSHAKE_NEEDLE = "continuous-work contract"
BRAKE_NEEDLE = "records itself as UNFINISHED"


def check(label: str, expected: int, actual: int) -> None:
    assert actual == expected, f"{label}: expected exit {expected}, got {actual}"


def has(label: str, needle: str, haystack: str) -> None:
    """bash `has`: grep -qiF — a case-insensitive fixed-string search of the refusal text."""
    assert needle.lower() in haystack.lower(), (
        f"{label}\n        text did not contain: {needle}\n--- text ---\n{haystack}"
    )


def hasnt(label: str, needle: str, haystack: str) -> None:
    assert needle.lower() not in haystack.lower(), (
        f"{label}\n        text unexpectedly contained: {needle}\n--- text ---\n{haystack}"
    )


# ---------------------------------------------------------------------------------------------------------
# The arena, laid out as the bash suite's reset_arena(): a registered run for this session, the deployed
# CONTRACT_VERSION copied in, one spec with an evidence/green folder.
# ---------------------------------------------------------------------------------------------------------


class Arena:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.orch = root / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME
        self.run_dir = self.orch / "runs" / RUN8
        self.hooks = root / ".claude" / "hooks"
        self.spec = root / ".claude" / "specs" / "demo"
        self.green = self.spec / "evidence" / "green"
        self.reset()

    def reset(self) -> None:
        shutil.rmtree(self.root / ".claude", ignore_errors=True)
        for folder in (self.run_dir, self.hooks, self.green):
            folder.mkdir(parents=True, exist_ok=True)
        registry = {SID: {"session_id": SID, "run_id": RUN8, "state_dir": f"runs/{RUN8}/"}}
        (self.orch / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
        shutil.copy(str(HOOKS_DIR / "CONTRACT_VERSION"), str(self.hooks / "CONTRACT_VERSION"))

    def seed_resume(self, status: str, phase: str, awaiting: str, issue: str) -> None:
        (self.run_dir / lib.RESUME_FILENAME).write_text(
            f"SESSION_ID: {SID}\nRUN_ID: {RUN8}\nMODE: unset\nStatus: {status}\nPhase: {phase}\n"
            f"AWAITING_USER: {awaiting}\nCURRENT_ISSUE: {issue}\nWORKABLE_ISSUES_REMAIN: no\n",
            encoding="utf-8",
        )

    def seed_workflow(self, phase: str, current_spec: str, status: str = "IN_PROGRESS") -> None:
        (self.run_dir / lib.STATE_FILENAME).write_text(
            f"SESSION_ID: {SID}\nCURRENT_SPEC: {current_spec}\nPhase: {phase}\nStatus: {status}\nCURRENT_TASK: 1\n",
            encoding="utf-8",
        )

    def ack(self) -> None:
        (self.run_dir / f"contract-ack-{DEPLOYED_VERSION}").write_text("ack\n", encoding="utf-8")

    def tasks(self, text: str) -> None:
        (self.spec / "tasks.md").write_text(text, encoding="utf-8")

    def capture(self, name: str, text: str) -> Path:
        path = self.green / name
        path.write_text(text, encoding="utf-8")
        return path

    def prep_spec(self, task_list: str) -> None:
        """bash prep_spec: a registered, acked, mid-IMPLEMENT run on the demo spec; the caller writes captures."""
        self.reset()
        self.seed_resume("IN_PROGRESS", "FIX", "none", "999")
        self.ack()
        self.seed_workflow("IMPLEMENT", ".claude/specs/demo")
        self.tasks(task_list)

    def ctx(self) -> lib.Context:
        payload = json.dumps({"session_id": SID, "cwd": str(self.root), "hook_event_name": "Stop"})
        return lib.Context(lib.Payload.parse(payload), environ={}, hooks_dir=HOOKS_DIR, cwd=self.root)

    def loop_gate(self) -> lib.Decision:
        return gate_issue_loop.run(self.ctx())

    def spec_gate(self) -> lib.Decision:
        return gate_spec_stop.run(self.ctx())


@pytest.fixture()
def arena(tmp_path: Path) -> Arena:
    return Arena(tmp_path)


def order_mtimes(older: Path, newer: Path) -> None:
    """Make `older` strictly older than `newer` — the deterministic form of the suite's `sleep 1` between writes."""
    base = max(older.stat().st_mtime, newer.stat().st_mtime)
    os.utime(str(older), (base, base))
    os.utime(str(newer), (base + 100, base + 100))


# =========================================================================================================
# 1. The contract handshake's BLOCK direction, identified by its TEXT not its exit code
# =========================================================================================================


def test_unacked_contract_blocks_via_the_handshake_not_the_brake(arena: Arena) -> None:
    """The state here is one the MAIN BRAKE would also block, which is exactly why the exit code alone cannot
    pin the handshake — so assert on which refusal actually fired."""
    arena.seed_resume("IN_PROGRESS", "FIX", "none", "999")
    decision = arena.loop_gate()
    out = decision.stderr
    check("unacked contract -> BLOCK", BLOCK, decision.exit_code)
    has(
        "  and the HANDSHAKE is what refused (names the contract)",
        HANDSHAKE_NEEDLE,
        out,
    )
    has("  and it names the deployed version", DEPLOYED_VERSION, out)
    has("  and it names the ack file to create", "contract-ack-", out)
    hasnt("  and it is NOT the main brake's message", BRAKE_NEEDLE, out)

    # Once acked, the SAME state must still block — but now via the main brake, with the other message. This is
    # the control that proves the two refusals are distinguishable at all.
    arena.ack()
    decision = arena.loop_gate()
    out = decision.stderr
    check("acked, same state -> still BLOCK", BLOCK, decision.exit_code)
    has("  and now it IS the main brake", BRAKE_NEEDLE, out)
    hasnt("  and the handshake no longer fires", HANDSHAKE_NEEDLE, out)


# =========================================================================================================
# 2. Defect class 10 — a capture must SHOW a pass, not merely EXIST
# =========================================================================================================


def test_a_capture_must_show_a_pass_not_merely_exist(arena: Arena) -> None:
    arena.prep_spec("- [x] 1 do the thing\n")
    arena.capture("1.txt", "")  # ZERO BYTES
    decision = arena.spec_gate()
    check("zero-byte capture -> BLOCK", BLOCK, decision.exit_code)
    has(
        "  and it says the capture shows no passing result",
        "shows NO passing result",
        decision.stderr,
    )

    arena.capture("1.txt", "ran the tests, all good\n")  # prose only, no counter
    check("prose-only capture -> BLOCK", BLOCK, arena.spec_gate().exit_code)

    arena.capture("1.txt", "5 passed in 1.0s\n")
    check("a real passing capture -> allow", ALLOW, arena.spec_gate().exit_code)


# =========================================================================================================
# 3. Per-task failure scanning — the verdict must not depend on file MTIME
# =========================================================================================================


def test_every_tasks_capture_is_scanned_regardless_of_mtime(arena: Arena) -> None:
    """THE MEASURED FAIL-OPEN. Two checked tasks; task 1's capture reports a real failure; task 2's is written
    LATER so it is the most-recently-touched. Scanning only the newest capture accepted the `3 failed`."""
    arena.prep_spec("- [x] 1 first task\n- [x] 2 second task\n")
    first = arena.capture("1.txt", "3 failed, 5 passed in 2.0s\n")
    second = arena.capture("2.txt", "10 passed in 1.0s\n")
    order_mtimes(older=first, newer=second)
    decision = arena.spec_gate()
    check("older capture reporting failures -> BLOCK", BLOCK, decision.exit_code)
    has("  and it names the offending TASK's own capture", "task 1", decision.stderr)

    # The control that proves mtime is no longer the discriminator: make task 1 the NEWEST without changing a byte.
    order_mtimes(older=second, newer=first)
    check(
        "same bytes, task 1 now newest -> still BLOCK",
        BLOCK,
        arena.spec_gate().exit_code,
    )

    # ...and the mirror: a skip counter in an older capture must also be caught.
    arena.capture("1.txt", "9 passed, 1 skipped in 2.0s\n")
    arena.capture("2.txt", "10 passed in 1.0s\n")
    order_mtimes(older=first, newer=second)
    check("older capture reporting a SKIP -> BLOCK", BLOCK, arena.spec_gate().exit_code)

    # Both clean -> allow. Without this the three cases above could all pass on a gate that blocks unconditionally.
    arena.capture("1.txt", "5 passed in 1.0s\n")
    arena.capture("2.txt", "10 passed in 1.0s\n")
    check(
        "both captures clean -> allow (non-vacuity control)",
        ALLOW,
        arena.spec_gate().exit_code,
    )

    # A COMMENT in an older capture must not block, exactly as for the newest one.
    arena.capture("1.txt", "# earlier: 3 failed, now fixed\n5 passed in 1.0s\n")
    order_mtimes(older=first, newer=second)
    check("a COMMENT mentioning failures -> allow", ALLOW, arena.spec_gate().exit_code)


# =========================================================================================================
# 4. The two Stop gates must agree on what a terminal value is
# =========================================================================================================


def test_spec_gate_releases_on_a_whole_terminal_value_only(arena: Arena) -> None:
    """The evidence gate used a raw `grep -qiE "^(TERMINAL)"`, anchored only at the START, so it released on a
    PREFIX while the loop gate refused the same string. Whole-value only."""
    arena.prep_spec("- [x] 1 do the thing\n")
    # no capture at all, so the gate has a reason to block unless a Status releases it
    arena.seed_workflow("IMPLEMENT", ".claude/specs/demo", "COMPLETED (was IN_PROGRESS)")
    check(
        "spec gate: narrative Status does NOT release",
        BLOCK,
        arena.spec_gate().exit_code,
    )
    arena.seed_workflow("IMPLEMENT", ".claude/specs/demo", "COMPLETED")
    check("spec gate: bare COMPLETED DOES release", ALLOW, arena.spec_gate().exit_code)


def test_loop_gate_gives_the_same_terminal_answers(arena: Arena) -> None:
    """And the loop gate must give the same answers for the same two strings."""
    arena.reset()
    arena.seed_resume("COMPLETED (was IN_PROGRESS)", "FIX", "none", "999")
    arena.ack()
    check(
        "loop gate: narrative Status does NOT release",
        BLOCK,
        arena.loop_gate().exit_code,
    )
    arena.reset()
    arena.seed_resume("COMPLETED", "FIX", "none", "999")
    arena.ack()
    check("loop gate: bare COMPLETED DOES release", ALLOW, arena.loop_gate().exit_code)


# =========================================================================================================
# 5. ...and they must agree on what counts as an ESCALATION
# =========================================================================================================
#
# The evidence gate used the WEAKER placeholder test while the loop gate used the substance test. A one-word
# token therefore released one gate and not the other — harmless only while BOTH are registered, and a
# fail-open in a spec-only project where the evidence gate is the only Stop hook. Both now apply the substance
# test, so these cases must give matching verdicts.


@pytest.mark.parametrize("token", ["waiting", "no", "0", "<reason>"])
def test_a_token_awaiting_user_releases_neither_gate(arena: Arena, token: str) -> None:
    arena.prep_spec("- [x] 1 do the thing\n")
    # no capture -> the gate has a reason to block unless the escalation releases it
    arena.seed_resume("IN_PROGRESS", "FIX", token, "999")
    arena.ack()
    arena.seed_workflow("IMPLEMENT", ".claude/specs/demo")
    check(
        f"spec gate: token AWAITING_USER '{token}' does NOT release",
        BLOCK,
        arena.spec_gate().exit_code,
    )
    check("loop gate: same token does NOT release", BLOCK, arena.loop_gate().exit_code)


def test_a_substantive_reason_releases_both_gates(arena: Arena) -> None:
    arena.prep_spec("- [x] 1 do the thing\n")
    arena.seed_resume(
        "IN_PROGRESS",
        "FIX",
        "waiting on the production credential for the smoke test",
        "999",
    )
    arena.ack()
    arena.seed_workflow("IMPLEMENT", ".claude/specs/demo")
    check(
        "spec gate: a substantive reason DOES release",
        ALLOW,
        arena.spec_gate().exit_code,
    )
    check(
        "loop gate: a substantive reason DOES release",
        ALLOW,
        arena.loop_gate().exit_code,
    )
