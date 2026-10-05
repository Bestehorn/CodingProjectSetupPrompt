"""Third-round feedback from the projects, pinned: the session id is an identifier or nothing; the state base is
the declared project even when its state tree does not exist yet; a capture's summary line decides, not its
prose; task ids keep their letters; the degraded Stop refusal is capped; several gates' stdout merge into one
JSON object; a project's post-tool-use gate runs; the launcher runs the interpreter isolated."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import hooklib as lib
import hooks

HOOKS_DIR = Path(__file__).resolve().parent.parent


def _install(target: Path, truncate_library: bool = False) -> Path:
    hooks_dir = target / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    for src in HOOKS_DIR.glob("*.py"):
        shutil.copy(src, hooks_dir / src.name)
    if truncate_library:
        text = (hooks_dir / "hooklib.py").read_text(encoding="utf-8")
        (hooks_dir / "hooklib.py").write_text(text[: text.index("def selftest")], encoding="utf-8")
    return hooks_dir


def _spawn(event: str, payload: str, project: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, *hooks.INTERPRETER_FLAGS, "-c", hooks.LAUNCHER, event],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(project),
        env=env,
        timeout=60,
        check=False,
    )


def test_session_id_is_an_identifier_or_nothing() -> None:
    assert lib.Payload.parse('{"session_id":"abcd1234-1111-2222-3333-444455556666"}').session_id.startswith("abcd")
    assert lib.Payload.parse('{"session_id":"../../../x"}').session_id == ""
    assert lib.Payload.parse('{"session_id":"a/b"}').session_id == ""
    assert lib.Payload.parse('{"session_id":" x "}').session_id == "x"


def test_reinject_cannot_be_steered_outside_the_run_directory(tmp_path: Path) -> None:
    import gate_reinject

    (tmp_path / ".claude" / "agent-state" / lib.ORCHESTRATOR_DIRNAME).mkdir(parents=True)
    (tmp_path / "secret.md").write_text("Status: SECRET\n", encoding="utf-8")
    payload = json.dumps({"session_id": "../../../x", "cwd": tmp_path.as_posix(), "source": "compact"})
    ctx = lib.Context(lib.Payload.parse(payload), environ={}, hooks_dir=HOOKS_DIR, cwd=tmp_path)
    decision = gate_reinject.run(ctx)
    assert "SECRET" not in decision.stdout and "cannot be identified" in decision.stdout


def test_state_base_is_the_declared_project_even_without_a_state_tree(tmp_path: Path) -> None:
    payload = json.dumps({"session_id": "deadbeef-0000", "cwd": tmp_path.as_posix()})
    # The process cwd is the REAL repository, which has an orchestrator tree; the payload names a fresh project.
    ctx = lib.Context(lib.Payload.parse(payload), environ={}, hooks_dir=HOOKS_DIR, cwd=HOOKS_DIR)
    assert ctx.state_base == tmp_path / ".claude" / "agent-state"
    ctx_env = lib.Context(
        lib.Payload.parse("{}"), environ={"CLAUDE_PROJECT_DIR": str(tmp_path)}, hooks_dir=HOOKS_DIR, cwd=HOOKS_DIR
    )
    assert ctx_env.state_base == tmp_path / ".claude" / "agent-state"


def test_summary_line_decides_not_prose(tmp_path: Path) -> None:
    capture = tmp_path / "1.1.txt"
    capture.write_text(
        "earlier in this session 5 failed, then I fixed the import\n"
        "test_a.py::test_x PASSED\n"
        "======================== 7 passed, 2 deselected in 1.30s ========================\n",
        encoding="utf-8",
    )
    body = lib.capture_body(capture)
    assert lib.has_pass_marker(body) and not lib.has_failures(body) and not lib.has_skips(body)
    red = tmp_path / "1.2.txt"
    red.write_text("3 failed, 5 passed in 2.0s\n", encoding="utf-8")
    assert lib.has_failures(lib.capture_body(red))
    unit = tmp_path / "1.3.txt"
    unit.write_text("Ran 4 tests in 0.1s\n\nFAILED (failures=1)\n", encoding="utf-8")
    assert lib.has_failures(lib.capture_body(unit))
    prose_only = tmp_path / "1.4.txt"
    prose_only.write_text("no runner output here, 5 failed is only a phrase\n", encoding="utf-8")
    assert lib.has_failures(lib.capture_body(prose_only))  # no summary line: the body is all there is


def test_task_ids_keep_their_letters(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "- [x] 1.2 first\n- [x] **24a** second\n- [x] T-01: third\n- [x] T7) fourth\n- [x] 2. heading\n"
        "- [x] 2.1 child\n- [x] Write the parser\n- [ ] 3 open\n",
        encoding="utf-8",
    )
    ids, unparseable = lib.checked_task_ids(tasks)
    assert ids == ["1.2", "24a", "T-01", "T7", "2", "2.1"]
    assert unparseable == ["- [x] Write the parser"]
    assert lib.is_heading_id("2", ids) and not lib.is_heading_id("2.1", ids)


def test_merge_stdout_yields_one_json_object_or_plain_text() -> None:
    plain = hooks.merge_stdout(["## A\n", "## B\n"])
    assert plain.startswith("## A") and "## B" in plain and not plain.startswith("{")
    merged = json.loads(
        hooks.merge_stdout(
            [
                json.dumps(
                    {
                        "systemMessage": "one",
                        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "ctx-1"},
                    }
                ),
                "plain context",
                json.dumps({"systemMessage": "two", "hookSpecificOutput": {"additionalContext": "ctx-2"}}),
            ]
        )
    )
    assert merged["systemMessage"] == "one\ntwo"
    assert merged["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert merged["hookSpecificOutput"]["additionalContext"] == "ctx-1\nctx-2\nplain context"


def test_degraded_stop_is_capped(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _install(project, truncate_library=True)
    payload = json.dumps({"session_id": "cafe0001-1111", "cwd": project.as_posix(), "hook_event_name": "Stop"})
    codes = [_spawn("stop", payload, project).returncode for _ in range(hooks.DEFAULT_BLOCK_CAP + 1)]
    assert codes[: hooks.DEFAULT_BLOCK_CAP] == [2] * hooks.DEFAULT_BLOCK_CAP
    assert codes[-1] == 0
    last = _spawn("stop", payload, project)
    assert "standing down" in last.stderr and "NOT" in last.stderr


def test_degraded_session_start_still_delivers_the_contract(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _install(project, truncate_library=True)
    start = _spawn("session-start", json.dumps({"session_id": "cafe0002-1111", "source": "startup"}), project)
    assert start.returncode == 0
    assert "Continuous work is in force" in start.stdout and "hook library" in start.stdout


def test_a_project_post_tool_use_gate_runs_and_is_registered(tmp_path: Path) -> None:
    hooks_dir = _install(tmp_path)
    (hooks_dir / "gate_project_after_write.py").write_text(
        "import hooklib as lib\n"
        'HOOK = "project-after-write"\n'
        'EVENT = "post-tool-use"\n'
        "ORDER = 200\n"
        'TOOLS = {"Write"}\n'
        "def run(ctx):\n"
        '    hit = ctx.payload.tool_name == "Write"\n'
        '    return lib.block("project-after-write: review this file") if hit else lib.allow()\n',
        encoding="utf-8",
    )
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x.py", "content": "y"}})
    decision = hooks.dispatch("post-tool-use", payload, environ={}, cwd=tmp_path, hooks_dir=hooks_dir)
    assert decision.exit_code == 2 and "project-after-write" in decision.stderr
    assert "PostToolUse" not in json.loads(hooks.registration_block())["hooks"]  # the framework ships none


def test_launcher_runs_the_interpreter_isolated(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _install(project)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), PYTHONHOME="D:/does/not/exist", PYTHONPATH="D:/nor/this")
    completed = subprocess.run(
        [sys.executable, *hooks.INTERPRETER_FLAGS, "-c", hooks.LAUNCHER, "pre-tool-use"],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -n -m x"}}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(project),
        env=env,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 2, completed.stderr
    assert hooks.INTERPRETER_FLAGS[0] == "-I"
