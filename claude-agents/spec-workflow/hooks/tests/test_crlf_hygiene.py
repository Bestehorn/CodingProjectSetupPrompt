"""Regression suite for ONE defect class — the pytest port of tests/test_crlf_hygiene.sh (11 assertions).

A carriage return smuggled in through a line-oriented protocol. MEASURED: on Windows a text-mode stdout turned
every `key=value` line into `key=value\\r\\n`, the \\r rode into the session id, the registry lookup MISSED,
the identity resolved UNREGISTERED and EVERY gate went silently inert — out of a performance optimisation.

Two properties make this worth a dedicated file: the defect is INVISIBLE to inspection (`echo "[$sid]"` looks
right, the \\r just moves the cursor — only a length or byte comparison shows it), and it is a WHOLE-FAMILY
failure in the fail-open direction. So the property under test is not "python works" but "a \\r never reaches
a comparison".

The bash suite's hygiene checks on the shipped `.sh` files become checks on the shipped `.py` files, and the
behavioural cases cover every line-oriented input the library reads: the payload, a state file, the
CONTRACT_VERSION, a capture, tasks.md, a counter and the revision notice.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import hooklib as lib
import hooks

HOOKS_DIR = Path(__file__).resolve().parent.parent
SID = "deadbeef-1111-2222-3333-444455556666"
SHIPPED_PY = sorted(HOOKS_DIR.glob("*.py"))


class Arena:
    """The bash suite's arena: a registry declaring `runs/deadbeef/` and an LF resume_state.md inside it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.state_root = root / ".claude" / "agent-state"
        self.orch = self.state_root / lib.ORCHESTRATOR_DIRNAME
        self.registry = self.orch / "registry.json"
        self.runs = self.orch / "runs"
        self.run_dir = self.runs / "deadbeef"
        self.state = self.run_dir / lib.RESUME_FILENAME
        self.run_dir.mkdir(parents=True)
        self.registry.write_text(
            '{"%s":{"state_dir":"runs/deadbeef/"}}' % SID, encoding="utf-8"
        )
        self.write_state(f"SESSION_ID: {SID}\nStatus: IN_PROGRESS\n")
        self.hooks_dir = root / ".claude" / "hooks"
        self.hooks_dir.mkdir(parents=True)
        shutil.copy(HOOKS_DIR / "CONTRACT_VERSION", self.hooks_dir / "CONTRACT_VERSION")

    def write_state(self, text: str, run_dir: Path = None) -> Path:  # type: ignore[assignment]
        state = (run_dir or self.run_dir) / lib.RESUME_FILENAME
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(
            text, encoding="utf-8", newline=""
        )  # newline="" keeps a \r\n as written
        return state

    def payload_text(self) -> str:
        return '{"session_id":"%s","cwd":"%s","hook_event_name":"Stop"}' % (
            SID,
            self.root.as_posix(),
        )

    def context(self, payload_text: str) -> lib.Context:
        return lib.Context(
            lib.Payload.parse(payload_text),
            host=lib.CLAUDE,
            environ={},
            hooks_dir=HOOKS_DIR,
            cwd=self.root,
        )

    def verdict(self, session: str = SID) -> str:
        return lib.normalize_verdict(lib.resolve_run_dir(self.state_root, session)[0])


@pytest.fixture()
def arena(tmp_path: Path) -> Arena:
    return Arena(tmp_path)


# ==========================================================================================================
# the payload parse
# ==========================================================================================================


def test_session_id_is_byte_exact_with_no_extra_byte(arena: Arena) -> None:
    """session id is byte-exact; session id has no extra byte"""
    parsed = lib.Payload.parse(arena.payload_text()).session_id
    assert parsed == SID
    assert len(parsed) == len(SID)


def test_cwd_is_byte_exact_and_resolves_as_a_directory(arena: Arena) -> None:
    """cwd is byte-exact (a CR breaks -d); cwd resolves as a directory"""
    parsed = lib.Payload.parse(arena.payload_text()).cwd
    assert parsed == arena.root.as_posix()
    assert Path(parsed).is_dir()


def test_identity_still_resolves_owned_from_the_parsed_payload(arena: Arena) -> None:
    """identity still resolves -> OWNED — THE CONSEQUENCE THAT MATTERED: a \\r on the id made this UNREGISTERED"""
    ctx = arena.context(arena.payload_text())
    assert ctx.resolve() == (lib.OWNED, arena.run_dir)
    assert arena.verdict(ctx.session_id) == lib.OWNED


# ==========================================================================================================
# a CRLF state file
# ==========================================================================================================

CRLF_STATE = (
    f"SESSION_ID: {SID}\r\nStatus: IN_PROGRESS\r\nPhase: DONE\r\nCURRENT_ISSUE: 574\r\n"
)


def test_crlf_state_status_is_clean_and_carries_no_extra_byte(arena: Arena) -> None:
    """Status is clean; Status carries no extra byte (a LENGTH assertion — a trailing \\r is invisible)"""
    state = arena.write_state(CRLF_STATE)
    status = lib.StateCache().field(state, "Status")
    assert status == "IN_PROGRESS"
    assert len(status) == 11


def test_crlf_state_current_issue_and_session_id_are_clean(arena: Arena) -> None:
    """CURRENT_ISSUE is clean; SESSION_ID is byte-exact"""
    state = arena.write_state(CRLF_STATE)
    states = lib.StateCache()
    assert states.field(state, "CURRENT_ISSUE") == "574"
    assert states.field(state, "SESSION_ID") == SID


def test_crlf_state_terminal_phase_is_recognised(arena: Arena) -> None:
    """a terminal Phase is recognised — a trailing \\r would fail the whole-value match and refuse a FINISHED run"""
    state = arena.write_state(CRLF_STATE)
    assert lib.phase_is_terminal(lib.StateCache().field(state, "Phase")) is True


def test_session_id_recovery_works_on_a_crlf_file(arena: Arena) -> None:
    """SESSION_ID recovery works on a CRLF file -> OWNED (rung 3 on an invented directory name)"""
    arena.registry.write_text("{}", encoding="utf-8")
    invented = arena.runs / "invented-label"
    arena.write_state(f"SESSION_ID: {SID}\r\nStatus: IN_PROGRESS\r\n", run_dir=invented)
    shutil.rmtree(arena.run_dir)
    assert arena.verdict() == lib.OWNED
    assert lib.resolve_run_dir(arena.state_root, SID) == (lib.OWNED, invented)


# ==========================================================================================================
# hygiene of the shipped sources: no CR byte may ride into an installed hook
# ==========================================================================================================


def test_shipped_python_sources_exist() -> None:
    assert {"hooklib.py", "hooks.py"} <= {path.name for path in SHIPPED_PY}


@pytest.mark.parametrize("path", SHIPPED_PY, ids=[path.name for path in SHIPPED_PY])
def test_shipped_python_source_has_no_cr_bytes(path: Path) -> None:
    assert b"\r" not in path.read_bytes(), f"{path.name} carries a carriage return"


# ==========================================================================================================
# a CRLF payload: CRLF between fields, and a CR INSIDE a field value, must both read clean
# ==========================================================================================================


def test_crlf_separated_payload_parses_to_the_same_values(arena: Arena) -> None:
    text = (
        '{\r\n  "session_id": "%s",\r\n  "cwd": "%s",\r\n  "hook_event_name": "Stop"\r\n}\r\n'
        % (SID, arena.root.as_posix())
    )
    payload = lib.Payload.parse(text)
    assert payload.session_id == SID
    assert payload.cwd == arena.root.as_posix()
    assert payload.event == "Stop"


def test_cr_inside_a_payload_value_is_stripped_before_any_comparison(
    arena: Arena,
) -> None:
    """A \\r on the session id or the cwd (JSON-escaped, as a text-mode writer would emit it) never reaches
    the registry lookup or the directory test."""
    text = '{"session_id":"%s\\r","cwd":"%s\\r","hook_event_name":"Stop\\r"}' % (
        SID,
        arena.root.as_posix(),
    )
    payload = lib.Payload.parse(text)
    assert payload.session_id == SID
    assert len(payload.session_id) == len(SID)
    assert payload.cwd == arena.root.as_posix()
    assert Path(payload.cwd).is_dir()
    assert payload.event == "Stop"
    assert arena.context(text).resolve() == (lib.OWNED, arena.run_dir)


def test_stop_event_still_reaches_the_run_through_a_cr_contaminated_payload(
    arena: Arena,
) -> None:
    """End to end: a CRLF payload whose id carries a \\r, against a CRLF state file recording unfinished work,
    must REFUSE the stop. The incident's shape was exit 0 here: the id missed the registry, UNREGISTERED,
    every gate inert."""
    arena.write_state(
        f"SESSION_ID: {SID}\r\nStatus: IN_PROGRESS\r\nPhase: FIX\r\nCURRENT_ISSUE: 999\r\n"
        "AWAITING_USER: none\r\n"
    )
    # The contract handshake is an EARLIER rung of the loop gate than the brake; acknowledge it so the brake
    # is the gate that speaks (the handshake has its own suites).
    lib.contract_ack_file(arena.run_dir, lib.contract_version(arena.root)).write_text(
        "acked\n", encoding="utf-8"
    )
    text = (
        '{\r\n"session_id":"%s\\r",\r\n"cwd":"%s",\r\n"hook_event_name":"Stop"\r\n}\r\n'
        % (SID, arena.root.as_posix())
    )
    decision = hooks.dispatch(
        "stop", text, host=lib.CLAUDE, environ={}, cwd=arena.root, hooks_dir=HOOKS_DIR
    )
    assert decision.exit_code == 2, decision.stderr
    assert "issue-loop-gate" in decision.stderr
    assert "UNFINISHED" in decision.stderr
    assert (
        "run deadbeef" in decision.stderr
    )  # the run was reached BY ITS OWN id, not borrowed


# ==========================================================================================================
# a CRLF CONTRACT_VERSION
# ==========================================================================================================


def test_crlf_contract_version_reads_clean(arena: Arena) -> None:
    (arena.hooks_dir / "CONTRACT_VERSION").write_text(
        "2026.09.30-continuous-work-2\r\n", encoding="utf-8", newline=""
    )
    version = lib.contract_version(arena.root)
    assert version == "2026.09.30-continuous-work-2"
    assert "\r" not in version
    assert arena.context(arena.payload_text()).contract_version == version
    ack = lib.contract_ack_file(arena.run_dir, version)
    assert ack.name == "contract-ack-2026.09.30-continuous-work-2"


def test_crlf_contract_version_reads_the_first_line_only(arena: Arena) -> None:
    (arena.hooks_dir / "CONTRACT_VERSION").write_text(
        "v-first\r\nv-second\r\n", encoding="utf-8", newline=""
    )
    assert lib.contract_version(arena.root) == "v-first"


# ==========================================================================================================
# CRLF captures, tasks.md, counters, the revision notice
# ==========================================================================================================


def _spec_with_crlf_captures(tmp_path: Path) -> Path:
    spec_dir = tmp_path / ".claude" / "specs" / "feature"
    green = spec_dir / "evidence" / "green"
    green.mkdir(parents=True)
    (green / "wave-1.txt").write_text(
        "# tasks: 1.1 1.2\r\n$ pytest -q\r\n3 passed in 0.10s\r\n",
        encoding="utf-8",
        newline="",
    )
    (green / "2.1.txt").write_text(
        "$ make test\r\nOK\r\n", encoding="utf-8", newline=""
    )
    return spec_dir


def test_crlf_wave_capture_header_covers_its_tasks(tmp_path: Path) -> None:
    """`# tasks: 1.1 1.2\\r\\n` names 1.1 and 1.2 as whole tokens; a \\r on the last token must not hide it."""
    spec_dir = _spec_with_crlf_captures(tmp_path)
    wave = spec_dir / "evidence" / "green" / "wave-1.txt"
    assert lib.capture_for_task(spec_dir, "green", "1.1") == wave
    assert lib.capture_for_task(spec_dir, "green", "1.2") == wave
    assert lib.capture_for_task(spec_dir, "green", "1.10") is None
    assert (
        lib.capture_for_task(spec_dir, "green", "2.1")
        == spec_dir / "evidence" / "green" / "2.1.txt"
    )


def test_crlf_capture_body_still_shows_its_pass_marker(tmp_path: Path) -> None:
    """`OK\\r\\n` must satisfy the anchored `^OK$`, and `3 passed\\r\\n` the counter predicate."""
    spec_dir = _spec_with_crlf_captures(tmp_path)
    green = spec_dir / "evidence" / "green"
    wave_body = lib.capture_body(green / "wave-1.txt")
    ok_body = lib.capture_body(green / "2.1.txt")
    assert "\r" not in wave_body and "\r" not in ok_body
    assert lib.has_pass_marker(wave_body) is True
    assert lib.has_pass_marker(ok_body) is True
    assert lib.has_failures(wave_body) is False
    assert lib.has_skips(wave_body) is False


def test_crlf_tasks_md_checked_ids_parse(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "# Tasks\r\n- [x] 1.1 write the failing test\r\n- [ ] 1.2 implement\r\n"
        "- [X] **2.1** bold id\r\n- [x] no id here\r\n",
        encoding="utf-8",
        newline="",
    )
    ids, unparseable = lib.checked_task_ids(tasks)
    assert ids == ["1.1", "2.1"]
    assert unparseable == ["- [x] no id here"]
    assert all("\r" not in line for line in unparseable)


def test_crlf_counter_file_reads_its_integer(tmp_path: Path) -> None:
    counter = tmp_path / "probe.count"
    counter.write_text("7\r\n", encoding="utf-8", newline="")
    assert lib.counter_read(counter) == 7


def test_crlf_revision_notice_body_is_clean_and_validity_is_honoured(
    tmp_path: Path,
) -> None:
    (tmp_path / "REVISION_NOTICE.md").write_text(
        "Valid-until: 2026-12-31\r\n# Notice\r\nline one\r\n",
        encoding="utf-8",
        newline="",
    )
    body = lib.revision_notice(tmp_path, today="2026-10-01")
    assert body == "# Notice\nline one\n"
    assert lib.revision_notice(tmp_path, today="2027-01-01") is None
