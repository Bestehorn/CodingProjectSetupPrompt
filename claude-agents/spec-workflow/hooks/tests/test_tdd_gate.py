"""Port of tests/test_tdd_gate.sh — the PreToolUse push gate (gate_tdd), 0 = allow the command, 2 = block it.

The bash suite is the SPECIFICATION; every one of its 44 `check` assertions appears here once, under the same
label, as a `check(label, expected, actual)` call. Two properties get more attention than anywhere else,
because this gate runs on EVERY Bash command and the two failure directions are asymmetric:
  * it must NEVER block a non-push command (commits included — they carry no evidence requirement),
    whatever the state of the library or the workflow;
  * it must ALWAYS block a push it cannot justify, including when its own library is broken.

Standard library + pytest only; Python 3.9 compatible.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import gate_tdd  # noqa: E402
import hooklib as lib  # noqa: E402

SID = "abcd1234-1111-2222-3333-444455556666"
RUN8 = "abcd1234"
ALLOW = 0
BLOCK = 2


def check(label: str, expected: int, actual: int) -> None:
    """One bash `check` == one pytest assertion, under the bash label."""
    assert actual == expected, f"{label}: expected exit {expected}, got {actual}"


# ---------------------------------------------------------------------------------------------------------
# The arena: a scratch project with the orchestrator tree, the conductor singleton dir and two spec dirs,
# exactly as the bash suite's reset_arena() lays them out.
# ---------------------------------------------------------------------------------------------------------


class Arena:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.orch = root / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME
        self.conductor = root / ".claude" / "agent-state" / lib.SINGLETON_DIRNAME
        self.spec = root / ".claude" / "specs" / "demo"
        self.spec_other = root / ".claude" / "specs" / "other"
        self.reset()

    def reset(self) -> None:
        shutil.rmtree(self.root / ".claude", ignore_errors=True)
        for folder in (
            self.orch,
            self.conductor,
            self.spec / "evidence" / "green",
            self.spec / "evidence" / "regress",
            self.spec_other / "evidence" / "green",
        ):
            folder.mkdir(parents=True, exist_ok=True)
        (self.orch / "registry.json").write_text("{}", encoding="utf-8")

    def workflow(self, target: Path, phase: str, current_spec: str) -> None:
        target.mkdir(parents=True, exist_ok=True)
        (target / lib.STATE_FILENAME).write_text(
            f"# Workflow state\nSESSION_ID: {SID}\nPhase: {phase}\nCURRENT_SPEC: {current_spec}\n",
            encoding="utf-8",
        )

    @staticmethod
    def tasksfile(spec_dir: Path, *lines: str) -> None:
        (spec_dir / "tasks.md").write_text(
            "# Tasks\n" + "".join(line + "\n" for line in lines), encoding="utf-8"
        )

    @staticmethod
    def write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def payload(self, command: str) -> str:
        return json.dumps(
            {
                "session_id": SID,
                "cwd": str(self.root),
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
        )

    def run(self, command: str) -> int:
        """The gate's verdict on one command — the direct equivalent of `payload | bash spec-tdd-gate.sh`."""
        ctx = lib.Context(
            lib.Payload.parse(self.payload(command)),
            environ={},
            hooks_dir=HOOKS_DIR,
            cwd=self.root,
        )
        return gate_tdd.run(ctx).exit_code

    def git_init(self) -> None:
        subprocess.run(
            ["git", "init", "-q", "."],
            cwd=str(self.root),
            check=True,
            capture_output=True,
            text=True,
        )


@pytest.fixture()
def arena(tmp_path: Path) -> Arena:
    return Arena(tmp_path)


def make_newest(path: Path, *others: Path) -> None:
    """Give `path` an mtime strictly later than every `others` — the deterministic form of the suite's `touch`."""
    latest = max(
        [p.stat().st_mtime for p in others if p.exists()] + [path.stat().st_mtime]
    )
    stamp = latest + 100
    os.utime(str(path), (stamp, stamp))


# =========================================================================================================
# the library-free section — classification and bans, unaffected by workflow state
# =========================================================================================================


def test_non_git_command_allowed(arena: Arena) -> None:
    check("a non-git command -> allow", ALLOW, arena.run("pytest test/"))


def test_git_status_allowed(arena: Arena) -> None:
    check("'git status' -> allow", ALLOW, arena.run("git status"))


def test_commit_no_verify_blocked(arena: Arena) -> None:
    check(
        "'git commit --no-verify' -> BLOCK",
        BLOCK,
        arena.run("git commit --no-verify -m x"),
    )


def test_commit_dash_n_blocked(arena: Arena) -> None:
    check("'git commit -n' -> BLOCK", BLOCK, arena.run("git commit -n -m x"))


def test_push_no_verify_blocked(arena: Arena) -> None:
    check("'git push --no-verify' -> BLOCK", BLOCK, arena.run("git push --no-verify"))


def test_push_dash_n_is_dry_run_allowed(arena: Arena) -> None:
    check(
        "'git push -n' (dry-run, not a bypass) -> allow",
        ALLOW,
        arena.run("git push -n"),
    )


def test_stash_push_is_not_a_remote_push(arena: Arena) -> None:
    check(
        "'git stash push' is not a remote push -> allow",
        ALLOW,
        arena.run("git stash push"),
    )


def test_plain_commit_no_workflow_allowed(arena: Arena) -> None:
    check(
        "plain commit, no workflow at all -> allow", ALLOW, arena.run("git commit -m x")
    )


def test_plain_push_no_workflow_allowed(arena: Arena) -> None:
    check("plain push, no workflow at all -> allow", ALLOW, arena.run("git push"))


def test_commit_is_free_mid_implementation(arena: Arena) -> None:
    """Commits NEVER owe evidence, even mid-implementation with nothing proven: commit early, commit often."""
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    check(
        "IMPLEMENT, unproven task: a COMMIT is still free",
        ALLOW,
        arena.run("git commit -m x"),
    )
    # A commit whose MESSAGE mentions pushing must be classified by the stripped command, not the quote.
    check(
        'commit -m "prepare for push" -> allow (not a push)',
        ALLOW,
        arena.run('git commit -m "prepare for push"'),
    )


# =========================================================================================================
# evidence enforcement — on the PUSH
# =========================================================================================================


def test_checked_task_without_capture_blocks_push(arena: Arena) -> None:
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    check(
        "IMPLEMENT, checked task, NO capture -> BLOCK push",
        BLOCK,
        arena.run("git push"),
    )
    # Global options must not defeat classification: every orchestrator push is `git -C <worktree> push`.
    check("'git -C . push' is still a push -> BLOCK", BLOCK, arena.run("git -C . push"))


def test_phase_design_is_outside_the_gate(arena: Arena) -> None:
    arena.workflow(arena.conductor, "DESIGN", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    check(
        "phase DESIGN (outside IMPLEMENT/VERIFY) -> allow", ALLOW, arena.run("git push")
    )


def test_lowercase_implement_still_gates(arena: Arena) -> None:
    """The phase match is a WORD, uppercased — `implement` gates, `NOT_IMPLEMENTED` does not."""
    arena.workflow(arena.conductor, "implement", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    check(
        "lowercase 'Phase: implement' still gates -> BLOCK",
        BLOCK,
        arena.run("git push"),
    )


def test_not_implemented_is_not_an_implement_phase(arena: Arena) -> None:
    arena.workflow(arena.conductor, "NOT_IMPLEMENTED", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    check(
        "'NOT_IMPLEMENTED' is not an implement phase -> allow",
        ALLOW,
        arena.run("git push"),
    )


def test_no_current_spec_is_transient(arena: Arena) -> None:
    arena.workflow(arena.conductor, "IMPLEMENT", "")
    check("no CURRENT_SPEC recorded -> allow (transient)", ALLOW, arena.run("git push"))


def test_clean_green_capture_allows(arena: Arena) -> None:
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    arena.write(arena.spec / "evidence" / "green" / "3.txt", "5 passed in 1.2s\n")
    check(
        "checked task with clean green capture -> allow", ALLOW, arena.run("git push")
    )


def test_wave_capture_covers_every_task_it_names(arena: Arena) -> None:
    """A WAVE capture (`# tasks:` header) covers every task it names — and only those."""
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 1.1 TEST: parser", "- [x] 1.2 IMPL: parser")
    arena.write(
        arena.spec / "evidence" / "green" / "wave-1.txt",
        "# tasks: 1.1, 1.2\n7 passed in 1.3s\n",
    )
    check(
        "wave capture naming both checked tasks -> allow", ALLOW, arena.run("git push")
    )


def test_wave_capture_covers_only_the_tasks_it_names(arena: Arena) -> None:
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(
        arena.spec,
        "- [x] 1.1 TEST: parser",
        "- [x] 1.2 IMPL: parser",
        "- [x] 2.1 IMPL: writer",
    )
    arena.write(
        arena.spec / "evidence" / "green" / "wave-1.txt",
        "# tasks: 1.1, 1.2\n7 passed in 1.3s\n",
    )
    check(
        "checked task no wave capture names -> BLOCK push", BLOCK, arena.run("git push")
    )


def test_checked_heading_needs_no_capture(arena: Arena) -> None:
    """A checked HEADING whose children are checked must not demand its own capture."""
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] **1. Heading**", "- [x] 1.1 Leaf")
    arena.write(arena.spec / "evidence" / "green" / "1.1.txt", "5 passed in 1.2s\n")
    check(
        "checked heading needs no capture of its own -> allow",
        ALLOW,
        arena.run("git push"),
    )


def test_pure_test_task_red_capture_is_its_evidence(arena: Arena) -> None:
    """A pure TEST task's red capture IS its evidence."""
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 2. Write the failing test")
    arena.write(arena.spec / "evidence" / "red" / "2.txt", "1 failed in 0.3s\n")
    check("TEST task with red capture -> allow", ALLOW, arena.run("git push"))


def test_failed_and_passed_counts_block(arena: Arena) -> None:
    """THE MEASURED FAIL-OPEN. The old predicate's escape clause was satisfied by "5 passed", so a capture
    reporting BOTH counts was allowed. Real pytest output almost always reports both."""
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    arena.write(
        arena.spec / "evidence" / "green" / "3.txt", "3 failed, 5 passed in 2.1s\n"
    )
    check("'3 failed, 5 passed' -> BLOCK (was ALLOWED)", BLOCK, arena.run("git push"))


def test_errors_and_passed_counts_block(arena: Arena) -> None:
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    arena.write(
        arena.spec / "evidence" / "green" / "3.txt", "2 errors, 5 passed in 2.1s\n"
    )
    check("'2 errors, 5 passed' -> BLOCK", BLOCK, arena.run("git push"))


def test_zero_failed_does_not_over_block(arena: Arena) -> None:
    """...while a zero count must NOT over-block, which is why the predicate needs no escape clause."""
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    arena.write(
        arena.spec / "evidence" / "green" / "3.txt", "0 failed, 5 passed in 2.1s\n"
    )
    check("'0 failed, 5 passed' -> allow (no over-block)", ALLOW, arena.run("git push"))


def test_skip_counter_is_a_vacuous_green(arena: Arena) -> None:
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    arena.write(
        arena.spec / "evidence" / "green" / "3.txt", "4 passed, 1 skipped in 1.0s\n"
    )
    check(
        "capture containing a SKIP -> BLOCK (vacuous green)",
        BLOCK,
        arena.run("git push"),
    )


def test_comment_mentioning_failures_is_not_a_failure(arena: Arena) -> None:
    """The two measured OVER-block escapes: comment lines are stripped, and predicates anchor on a
    SUMMARY COUNTER — a test merely NAMED like a skip must not read as one."""
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    arena.write(
        arena.spec / "evidence" / "green" / "3.txt",
        "# earlier this run: 3 failed, now fixed\n5 passed in 1.2s\n",
    )
    check(
        "comment mentioning failures is not a failure -> allow",
        ALLOW,
        arena.run("git push"),
    )


def test_test_named_skipped_is_not_a_skip(arena: Arena) -> None:
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    arena.write(
        arena.spec / "evidence" / "green" / "3.txt",
        "test_reports_skipped_reason PASSED\n5 passed in 1.2s\n",
    )
    check(
        "a test NAMED ...skipped... is not a skip -> allow",
        ALLOW,
        arena.run("git push"),
    )


# =========================================================================================================
# CI-OUTAGE MODE — a push with no CI run behind it owes a full-suite capture
# =========================================================================================================


def test_ci_outage_mode_owes_a_green_full_suite_capture(arena: Arena) -> None:
    arena.workflow(arena.conductor, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")
    arena.write(arena.spec / "evidence" / "green" / "3.txt", "5 passed in 1.2s\n")
    arena.git_init()
    marker = arena.root / ".git" / "ci-outage-mode"
    marker.touch()
    regress = arena.spec / "evidence" / "regress" / "full.txt"

    check("outage declared, NO regress capture -> BLOCK", BLOCK, arena.run("git push"))
    arena.write(regress, "3 failed, 90 passed in 60s\n")
    check(
        "outage declared, RED full-suite capture -> BLOCK", BLOCK, arena.run("git push")
    )
    arena.write(regress, "93 passed in 61s\n")
    check(
        "outage declared, GREEN full-suite capture -> allow",
        ALLOW,
        arena.run("git push"),
    )
    marker.unlink()
    regress.unlink()
    check("outage cleared -> no regress capture owed", ALLOW, arena.run("git push"))


# =========================================================================================================
# identity — a push must never be judged on ANOTHER run's spec
# =========================================================================================================


def test_push_is_judged_on_this_sessions_own_run(arena: Arena) -> None:
    """A sibling run, touched LAST, whose spec is fully proven. This session's own run points at a spec with a
    checked task and NO capture. An mtime-borrowing gate reads the sibling's state and ALLOWS the push."""
    registry = {SID: {"session_id": SID, "run_id": RUN8, "state_dir": f"runs/{RUN8}/"}}
    (arena.orch / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    own = arena.orch / "runs" / RUN8
    arena.write(own / lib.RESUME_FILENAME, f"SESSION_ID: {SID}\nStatus: IN_PROGRESS\n")
    arena.workflow(own, "IMPLEMENT", ".claude/specs/demo")
    arena.tasksfile(arena.spec, "- [x] 3. Do the thing")

    sibling = arena.orch / "runs" / "99999999"
    arena.write(
        sibling / lib.RESUME_FILENAME, "SESSION_ID: someone-else\nStatus: IN_PROGRESS\n"
    )
    arena.workflow(sibling, "IMPLEMENT", ".claude/specs/other")
    arena.tasksfile(arena.spec_other, "- [x] 9. Their thing")
    other_capture = arena.spec_other / "evidence" / "green" / "9.txt"
    arena.write(other_capture, "5 passed in 1.0s\n")
    make_newest(
        sibling / lib.STATE_FILENAME, own / lib.STATE_FILENAME
    )  # newest, so an mtime rung would pick it
    check(
        "sibling's proven spec does NOT excuse my unproven one",
        BLOCK,
        arena.run("git push"),
    )

    # And the converse: my OWN proven spec is honoured even when a sibling is unproven and newer.
    arena.write(arena.spec / "evidence" / "green" / "3.txt", "5 passed in 1.0s\n")
    other_capture.unlink()
    make_newest(sibling / lib.STATE_FILENAME, own / lib.STATE_FILENAME)
    check(
        "my own proven spec is honoured despite a newer sibling",
        ALLOW,
        arena.run("git push"),
    )


# =========================================================================================================
# fail-closed on a broken library — but ONLY for pushes
# =========================================================================================================
#
# The dispatcher is spawned exactly as the harness spawns it (`python <copy>/hooks.py pre-tool-use`, payload on
# stdin) from a copy of the hooks directory whose library is broken two ways:
#   partial — hooklib.py truncated before `def selftest` (the header of hooklib.py promises that a caller which
#             can call selftest() imported the whole module, so a truncated copy fails closed on a push);
#   missing — hooklib.py absent altogether.
# A PUSH must be refused (exit 2); an ordinary command and a commit must still run (exit 0); the bypass bans
# must still fire (exit 2).

VARIANTS = ("partial", "missing")


def broken_hooks_copy(tmp_path: Path, variant: str) -> Path:
    copy = tmp_path / f"broken-{variant}" / "hooks"
    copy.mkdir(parents=True)
    for source in HOOKS_DIR.iterdir():
        if source.is_file() and (
            source.suffix == ".py"
            or source.name in ("CONTRACT_VERSION", "REVISION_NOTICE.md")
        ):
            shutil.copy(str(source), str(copy / source.name))
    library = copy / "hooklib.py"
    if variant == "partial":
        text = library.read_text(encoding="utf-8")
        cut = text.index("\ndef selftest")
        library.write_text(text[:cut] + "\n", encoding="utf-8")
    else:
        library.unlink()
    return copy


def spawn_dispatcher(copy: Path, project: Path, command: str) -> int:
    payload = json.dumps(
        {
            "session_id": SID,
            "cwd": str(project),
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    )
    env: Dict[str, str] = {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "PYTHONPATH",
            "PYTHONSAFEPATH",
            "CLAUDE_PROJECT_DIR",
            "KIRO_PROJECT_DIR",
        )
    }
    completed = subprocess.run(
        [sys.executable, str(copy / "hooks.py"), "pre-tool-use"],
        input=payload,
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return completed.returncode


@pytest.mark.parametrize("variant", VARIANTS)
def test_broken_library_refuses_a_push(tmp_path: Path, variant: str) -> None:
    copy = broken_hooks_copy(tmp_path, variant)
    project = tmp_path / "project"
    project.mkdir()
    check(
        f"{variant} library: a PUSH is refused",
        BLOCK,
        spawn_dispatcher(copy, project, "git push"),
    )


@pytest.mark.parametrize("variant", VARIANTS)
def test_broken_library_lets_a_non_push_run(tmp_path: Path, variant: str) -> None:
    """The critical asymmetry: an ordinary command must still run. A gate that refused every Bash call when its
    library broke would be removed by the first person it inconvenienced."""
    copy = broken_hooks_copy(tmp_path, variant)
    project = tmp_path / "project"
    project.mkdir()
    check(
        f"{variant} library: a NON-push still runs",
        ALLOW,
        spawn_dispatcher(copy, project, "pytest test/"),
    )


@pytest.mark.parametrize("variant", VARIANTS)
def test_broken_library_leaves_a_commit_free(tmp_path: Path, variant: str) -> None:
    """A COMMIT never reaches the library, so a broken library must not tax it either."""
    copy = broken_hooks_copy(tmp_path, variant)
    project = tmp_path / "project"
    project.mkdir()
    check(
        f"{variant} library: a COMMIT is still free",
        ALLOW,
        spawn_dispatcher(copy, project, "git commit -m x"),
    )


@pytest.mark.parametrize("variant", VARIANTS)
def test_broken_library_commit_bypass_ban_still_fires(
    tmp_path: Path, variant: str
) -> None:
    """...and the bypass bans must still fire, since they sit above the library section."""
    copy = broken_hooks_copy(tmp_path, variant)
    project = tmp_path / "project"
    project.mkdir()
    check(
        f"{variant} library: the commit --no-verify ban still fires",
        BLOCK,
        spawn_dispatcher(copy, project, "git commit --no-verify -m x"),
    )


@pytest.mark.parametrize("variant", VARIANTS)
def test_broken_library_push_bypass_ban_still_fires(
    tmp_path: Path, variant: str
) -> None:
    copy = broken_hooks_copy(tmp_path, variant)
    project = tmp_path / "project"
    project.mkdir()
    check(
        f"{variant} library: the push --no-verify ban still fires",
        BLOCK,
        spawn_dispatcher(copy, project, "git push --no-verify"),
    )
