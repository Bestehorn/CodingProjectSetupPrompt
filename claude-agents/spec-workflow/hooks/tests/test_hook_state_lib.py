"""Unit tests of hooklib.py — the pytest port of tests/test_hook_state_lib.sh (64 assertions).

The bash suite is the SPECIFICATION. Every bash assertion is mirrored here under the bash label. Where a bash
case tested a bash-only construct (`local` word-expansion, `set -u`, awk flags) the INTENT is ported: the
behaviour the construct protected.

Nothing here goes through a gate: the library is called DIRECTLY, exactly as the bash suite did, so a function
that resolves correctly only when a caller happens to hold some global cannot pass by accident.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import hooklib as lib

HOOKS_DIR = Path(__file__).resolve().parent.parent
SID = "deadbeef-1111-2222-3333-444455556666"


class Arena:
    """The scratch project the bash suite built: `<arena>/.claude/agent-state/issue-work-orchestrator/`."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.state_root = root / ".claude" / "agent-state"
        self.orch = self.state_root / lib.ORCHESTRATOR_DIRNAME
        self.registry = self.orch / "registry.json"
        self.runs = self.orch / "runs"
        self.orch.mkdir(parents=True)
        self.registry.write_text("{}", encoding="utf-8")
        hooks_dir = root / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True)
        shutil.copy(HOOKS_DIR / "CONTRACT_VERSION", hooks_dir / "CONTRACT_VERSION")

    def write_registry(self, text: str) -> None:
        self.registry.write_text(text, encoding="utf-8")

    def write_state(self, run_name: str, text: str) -> Path:
        run_dir = self.runs / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        state = run_dir / lib.RESUME_FILENAME
        state.write_text(text, encoding="utf-8", newline="")
        return state

    # hook_identity_verdict / hook_identity_run_dir
    def verdict(self, session: str = SID) -> str:
        return lib.normalize_verdict(lib.resolve_run_dir(self.state_root, session)[0])

    def run_dir(self, session: str = SID):
        return lib.resolve_run_dir(self.state_root, session)[1]


@pytest.fixture()
def arena(tmp_path: Path) -> Arena:
    return Arena(tmp_path)


# ==========================================================================================================
# identity verdicts — called with NO global named 'base' in scope
# ==========================================================================================================


def test_no_registry_entry_is_unregistered(arena: Arena) -> None:
    """no registry entry -> UNREGISTERED"""
    assert arena.verdict() == lib.UNREGISTERED


def test_entry_with_no_state_dir_key_is_broken_and_names_conventional_path(
    arena: Arena,
) -> None:
    """entry with NO state_dir key -> BROKEN; BROKEN names the conventional path"""
    arena.write_registry('{"%s":{"session_id":"%s","run_id":"deadbeef"}}' % (SID, SID))
    assert arena.verdict() == lib.BROKEN
    assert arena.run_dir() == arena.runs / "deadbeef"


def test_entry_with_empty_state_dir_is_broken(arena: Arena) -> None:
    """entry with EMPTY state_dir -> BROKEN"""
    arena.write_registry('{"%s":{"state_dir":""}}' % SID)
    assert arena.verdict() == lib.BROKEN


def test_entry_with_absolute_state_dir_is_broken(arena: Arena) -> None:
    """entry with ABSOLUTE state_dir -> BROKEN"""
    arena.write_registry('{"%s":{"state_dir":"/abs/elsewhere"}}' % SID)
    assert arena.verdict() == lib.BROKEN


def test_traversing_state_dir_is_broken_never_owned(arena: Arena) -> None:
    """TRAVERSING state_dir -> BROKEN, never OWNED (rejected as a LOCATION, still a registered run)"""
    arena.runs.mkdir()
    arena.write_registry('{"%s":{"state_dir":"runs/../../../etc/"}}' % SID)
    assert arena.verdict() == lib.BROKEN


def test_malformed_registry_with_key_present_is_broken(arena: Arena) -> None:
    """MALFORMED registry, key present -> BROKEN

    A malformed registry must not be read as "no entry": that would be a fail-open on a corrupted file. The
    bash library's last rung greps for the session id as a KEY and answers HAS, so the verdict is BROKEN.
    """
    arena.write_registry('{"%s":{"state_dir": ' % SID)
    assert arena.verdict() == lib.BROKEN


def test_declared_and_present_state_is_owned_and_names_declared_dir(
    arena: Arena,
) -> None:
    """declared + state present -> OWNED; OWNED names the declared dir"""
    arena.write_registry('{"%s":{"state_dir":"runs/deadbeef/"}}' % SID)
    arena.write_state("deadbeef", f"SESSION_ID: {SID}\nStatus: IN_PROGRESS\n")
    assert arena.verdict() == lib.OWNED
    assert arena.run_dir() == arena.runs / "deadbeef"


def test_invented_dir_recovered_by_session_id(arena: Arena) -> None:
    """invented dir recovered by SESSION_ID -> OWNED; and names the invented dir (rung 3)"""
    arena.write_registry('{"%s":{"state_dir":"runs/deadbeef/"}}' % SID)
    invented = "run-issue574-20260828T194800Z"
    arena.write_state(invented, f"SESSION_ID: {SID}\nStatus: IN_PROGRESS\n")
    assert arena.verdict() == lib.OWNED
    assert arena.run_dir() == arena.runs / invented


def test_newest_sibling_run_is_not_adopted(arena: Arena) -> None:
    """newest SIBLING run is NOT adopted -> BROKEN; and the sibling dir is never named (the mtime borrow)"""
    arena.write_registry('{"%s":{"state_dir":"runs/deadbeef/"}}' % SID)
    sibling = arena.write_state(
        "99999999",
        "SESSION_ID: someone-else\nStatus: IN_PROGRESS\nCURRENT_ISSUE: 565\n",
    )
    sibling.touch()
    assert arena.verdict() == lib.BROKEN
    assert arena.run_dir() == arena.runs / "deadbeef"


# ==========================================================================================================
# hook_counter_read — clamping and the octal trap
# ==========================================================================================================


@pytest.mark.parametrize(
    "label, content, expected",
    [
        ("plain integer", "7", 7),
        ("leading zero is NOT read octal", "08", 8),
        ("double leading zero", "009", 9),
        ("zero", "0", 0),
        ("non-numeric -> 0", "abc", 0),
        (
            "absurd width -> clamped, not an overflow",
            "99999999999999999999999999",
            9999,
        ),
    ],
)
def test_counter_read(tmp_path: Path, label: str, content: str, expected: int) -> None:
    counter = tmp_path / "probe.count"
    counter.write_text(content, encoding="utf-8")
    assert lib.counter_read(counter) == expected, label


def test_clamped_counter_value_compares_cleanly(tmp_path: Path) -> None:
    """clamped value compares cleanly — usable in the caller's `blocks >= cap` without aborting the gate"""
    counter = tmp_path / "probe.count"
    counter.write_text("99999999999999999999999999", encoding="utf-8")
    value = lib.counter_read(counter)
    assert isinstance(value, int)
    assert value >= lib.resolve_block_cap(None)


def test_absent_counter_reads_zero(tmp_path: Path) -> None:
    """absent counter -> 0"""
    assert lib.counter_read(tmp_path / "probe.count") == 0


# ==========================================================================================================
# hook_state_field — the parsing contract the state templates rely on
# ==========================================================================================================


def _field(tmp_path: Path, content: str, name: str) -> str:
    fields = tmp_path / "fields.md"
    fields.write_text(content, encoding="utf-8", newline="")
    return lib.StateCache().field(fields, name)


def test_state_field_last_occurrence_wins(tmp_path: Path) -> None:
    """LAST occurrence wins (append-to-correct)"""
    assert _field(tmp_path, "Status: FIRST\nStatus: LAST\n", "Status") == "LAST"


def test_state_field_value_may_contain_a_colon(tmp_path: Path) -> None:
    """value may contain a colon"""
    assert (
        _field(
            tmp_path, "AWAITING_USER: need a credential: for prod\n", "AWAITING_USER"
        )
        == "need a credential: for prod"
    )


def test_state_field_longer_name_is_not_matched(tmp_path: Path) -> None:
    """a longer field name is not matched"""
    assert _field(tmp_path, "Status_Detail: nope\n", "Status") == ""


def test_state_field_bold_spelling_is_invisible(tmp_path: Path) -> None:
    """bold spelling is INVISIBLE (documented)"""
    assert _field(tmp_path, "**Status:** BOLD\n", "Status") == ""


def test_state_field_crlf_is_stripped(tmp_path: Path) -> None:
    """CRLF is stripped"""
    assert _field(tmp_path, "Status: CRLF\r\n", "Status") == "CRLF"


def test_state_field_list_item_spelling_is_matched(tmp_path: Path) -> None:
    """list-item spelling is matched"""
    assert _field(tmp_path, "- Status: dashed\n", "Status") == "dashed"


def test_state_field_absent_field_is_empty(tmp_path: Path) -> None:
    """absent field -> empty, not an error"""
    assert _field(tmp_path, "Phase: FIX\n", "NO_SUCH_FIELD") == ""


def test_state_field_missing_file_is_empty(tmp_path: Path) -> None:
    """missing file -> empty, not an error"""
    assert lib.StateCache().field(tmp_path / "nope.md", "Status") == ""


# ==========================================================================================================
# the self-test symbol is the LAST definition (partial-source detection)
# ==========================================================================================================


def test_selftest_is_the_last_definition() -> None:
    """hook_task_selftest is the last definition -> `selftest` is the last top-level def of hooklib.py"""
    tree = ast.parse((HOOKS_DIR / "hooklib.py").read_text(encoding="utf-8"))
    definitions = [
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    ]
    assert definitions[-1].name == "selftest"


def _stage_hooks_copy(target: Path, truncate: bool) -> None:
    """A copy of the shipped hooks; with `truncate`, hooklib.py is cut just before `def selftest`."""
    for path in HOOKS_DIR.iterdir():
        if path.suffix == ".py" or path.name in (
            "CONTRACT_VERSION",
            "REVISION_NOTICE.md",
        ):
            shutil.copy(path, target / path.name)
    if truncate:
        source = (target / "hooklib.py").read_text(encoding="utf-8")
        cut = source.index("def selftest(")
        (target / "hooklib.py").write_text(source[:cut], encoding="utf-8")
        assert "def selftest" not in (target / "hooklib.py").read_text(encoding="utf-8")


def _stop(hooks_copy: Path, arena: Arena) -> subprocess.CompletedProcess:
    payload = '{"session_id":"%s","cwd":"%s","hook_event_name":"Stop"}' % (
        SID,
        arena.root.as_posix(),
    )
    return subprocess.run(
        [sys.executable, str(hooks_copy / "hooks.py"), "stop"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(arena.root),
        timeout=60,
        check=False,
    )


def test_truncated_library_lacking_selftest_makes_stop_refuse(
    tmp_path: Path, arena: Arena
) -> None:
    """The INTENT of the last-definition case: a truncated library could define every function the gates
    use while omitting the self-test symbol — and the gates' fail-closed check must then REFUSE the stop
    rather than pass on a broken library. Baseline first: the intact copy allows an unregistered session."""
    intact = tmp_path / "intact"
    intact.mkdir()
    _stage_hooks_copy(intact, truncate=False)
    baseline = _stop(intact, arena)
    assert baseline.returncode == 0, baseline.stderr

    truncated = tmp_path / "truncated"
    truncated.mkdir()
    _stage_hooks_copy(truncated, truncate=True)
    refused = _stop(truncated, arena)
    assert refused.returncode == 2, (
        f"a hooklib.py copy lacking `selftest` must make the stop event refuse (fail closed); "
        f"exit {refused.returncode}, stderr: {refused.stderr!r}"
    )


# ==========================================================================================================
# hook_resolve_block_cap - a bad override must not disable OR wedge the gate
# ==========================================================================================================


@pytest.mark.parametrize(
    "label, raw, expected",
    [
        ("default when unset", "", 8),
        ("a valid override is honoured", "3", 3),
        ("non-numeric falls back to the default", "abc", 8),
        ("partly-numeric falls back", "1abc", 8),
        ("whitespace falls back", " ", 8),
        ("zero clamps up (not an off-switch)", "0", 1),
        ("absurd value clamps down", "100000", 64),
    ],
)
def test_resolve_block_cap(label: str, raw: str, expected: int) -> None:
    assert lib.resolve_block_cap(raw) == expected, label


def test_resolve_block_cap_result_is_always_valid_arithmetic() -> None:
    """result is always valid arithmetic"""
    value = lib.resolve_block_cap("abc")
    assert isinstance(value, int)
    assert value >= 1
    assert (
        lib.resolve_block_cap(None) == lib.DEFAULT_BLOCK_CAP
    )  # an absent variable, not a typo


def test_live_block_cap_constant_is_in_range(arena: Arena) -> None:
    """the live constant is in range"""
    assert 1 <= lib.DEFAULT_BLOCK_CAP <= 64
    ctx = lib.Context(
        lib.Payload.parse("{}"), environ={}, hooks_dir=HOOKS_DIR, cwd=arena.root
    )
    assert 1 <= ctx.block_cap <= 64


# ==========================================================================================================
# counter contract - a block must be COUNTABLE and a cap must be DURABLE
# ==========================================================================================================


def test_counter_bump_reports_success_and_advances(tmp_path: Path) -> None:
    """bump reports success when it lands; and the value advanced; second bump advances again"""
    counter = tmp_path / "counters" / "ok.count"
    assert lib.counter_bump(counter) is True
    assert lib.counter_read(counter) == 1
    assert lib.counter_bump(counter) is True
    assert lib.counter_read(counter) == 2


def test_counter_bump_on_unwritable_path_reports_failure(tmp_path: Path) -> None:
    """bump on an unwritable path reports failure — a DIRECTORY occupying the counter's own path"""
    blocked = tmp_path / "counters" / "blocked.count"
    blocked.mkdir(parents=True)
    assert lib.counter_bump(blocked) is False


def test_capped_marker_is_durable_until_a_genuine_reset(tmp_path: Path) -> None:
    """not capped initially; capped after marking; and the marker persists; a genuine reset clears the
    marker; and clears the count"""
    counter = tmp_path / "counters" / "ok.count"
    lib.counter_bump(counter)
    lib.counter_bump(counter)
    assert lib.counter_is_capped(counter) is False
    assert lib.counter_mark_capped(counter) is True
    assert lib.counter_is_capped(counter) is True
    assert (
        lib.counter_is_capped(counter) is True
    )  # a second look: the marker is a FILE, not process state
    lib.counter_reset(counter)
    assert lib.counter_is_capped(counter) is False
    assert lib.counter_read(counter) == 0


# ==========================================================================================================
# hook_field_is_placeholder - every spelling of nothing-recorded
# ==========================================================================================================


@pytest.mark.parametrize(
    "value", ["", "none", "NONE", "-", "n/a", "unset", "empty", "null", "tbd"]
)
def test_placeholder_spellings(value: str) -> None:
    assert lib.is_placeholder(value) is True, f"placeholder: [{value}]"


@pytest.mark.parametrize(
    "value", ["574", ".claude/specs/x", "design fork on retry policy", "0"]
)
def test_real_values_are_not_placeholders(value: str) -> None:
    assert lib.is_placeholder(value) is False, f"real value: [{value}]"


# ==========================================================================================================
# trailing whitespace is stripped - it broke BOTH directions
# ==========================================================================================================


def test_trailing_spaces_stripped_so_value_reads_as_placeholder(tmp_path: Path) -> None:
    """trailing spaces stripped; so it reads as a placeholder (`none ` had DISABLED the primary brake)"""
    value = _field(tmp_path, "AWAITING_USER: none   \n", "AWAITING_USER")
    assert value == "none"
    assert lib.is_placeholder(value) is True


def test_trailing_tab_stripped(tmp_path: Path) -> None:
    """trailing tab stripped (`x \\t` had produced the unopenable path `x /tasks.md`)"""
    assert (
        _field(tmp_path, "CURRENT_SPEC: .claude/specs/x \t\n", "CURRENT_SPEC")
        == ".claude/specs/x"
    )
