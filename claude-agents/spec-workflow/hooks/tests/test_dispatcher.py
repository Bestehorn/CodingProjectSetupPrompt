"""The dispatcher's own contract: gate discovery, a project's gate, the disable switch, the per-gate tool
matcher, the launcher, and the registration block. These are the properties two project runs asked for after
the first install (a fixed gate list, no way to switch a gate off, every non-shell tool allowed before any gate
ran, a missing dispatcher read as a block)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import hooks

HOOKS_DIR = Path(__file__).resolve().parent.parent


def _install(target: Path) -> Path:
    hooks_dir = target / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    for src in HOOKS_DIR.glob("*.py"):
        shutil.copy(src, hooks_dir / src.name)
    return hooks_dir


def _spawn(event: str, payload: str, project: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", hooks.LAUNCHER, event],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(project),
        env=env,
        timeout=60,
        check=False,
    )


def test_framework_gates_are_discovered_in_order() -> None:
    names = [g[0] for g in hooks.discover_gates("pre-tool-use", HOOKS_DIR)]
    assert names == ["no-env-vars", "spec-tdd-gate", "claim-before-worktree", "issue-filing-gate"]
    assert [g[0] for g in hooks.discover_gates("stop", HOOKS_DIR)] == ["spec-stop-gate", "issue-loop-gate"]
    assert [g[0] for g in hooks.discover_gates("session-start", HOOKS_DIR)] == [
        "session-register",
        "scoped-temp-init",
        "continuous-work-reinject",
    ]


def test_a_project_gate_joins_the_event_without_a_second_registration(tmp_path: Path) -> None:
    hooks_dir = _install(tmp_path)
    (hooks_dir / "gate_project_write.py").write_text(
        "import hooklib as lib\n"
        'HOOK = "project-write-gate"\n'
        'EVENT = "pre-tool-use"\n'
        "ORDER = 200\n"
        'TOOLS = {"Write", "Edit"}\n'
        "def run(ctx):\n"
        '    content = (ctx.payload.data.get("tool_input") or {}).get("content", "")\n'
        '    return lib.block("project-write-gate: no TODO markers") if "TODO" in content else lib.allow()\n',
        encoding="utf-8",
    )
    names = [g[0] for g in hooks.discover_gates("pre-tool-use", hooks_dir)]
    assert names[-1] == "project-write-gate" and len(names) == 5
    write_payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x.py", "content": "# TODO"}})
    decision = hooks.dispatch("pre-tool-use", write_payload, environ={}, cwd=tmp_path, hooks_dir=hooks_dir)
    assert decision.exit_code == 2 and "project-write-gate" in decision.stderr
    # The framework's shell gates do not see the Write call, and the project gate does not see a Bash call.
    bash_payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo TODO"}})
    assert hooks.dispatch("pre-tool-use", bash_payload, environ={}, cwd=tmp_path, hooks_dir=hooks_dir).exit_code == 0


def test_hooks_config_disables_a_gate_by_name(tmp_path: Path) -> None:
    hooks_dir = _install(tmp_path)
    (hooks_dir / hooks.CONFIG_FILENAME).write_text(json.dumps({"disabled_gates": ["spec-tdd-gate"]}), encoding="utf-8")
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit --no-verify -m x"}})
    assert hooks.dispatch("pre-tool-use", payload, environ={}, cwd=tmp_path, hooks_dir=hooks_dir).exit_code == 0
    (hooks_dir / hooks.CONFIG_FILENAME).unlink()
    assert hooks.dispatch("pre-tool-use", payload, environ={}, cwd=tmp_path, hooks_dir=hooks_dir).exit_code == 2


def test_a_broken_project_gate_does_not_take_the_framework_gates_down(tmp_path: Path) -> None:
    hooks_dir = _install(tmp_path)
    (hooks_dir / "gate_project_broken.py").write_text("this is not python\n", encoding="utf-8")
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit --no-verify -m x"}})
    decision = hooks.dispatch("pre-tool-use", payload, environ={}, cwd=tmp_path, hooks_dir=hooks_dir)
    assert decision.exit_code == 2 and "forbidden" in decision.stderr


@pytest.mark.skipif(shutil.which("python") is None and shutil.which("python3") is None, reason="no python on PATH")
def test_launcher_fails_open_without_a_dispatcher_and_decides_with_one(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push --no-verify"}})
    missing = _spawn("pre-tool-use", payload, empty)
    assert missing.returncode == 0, missing.stderr
    project = tmp_path / "project"
    _install(project)
    installed = _spawn("pre-tool-use", payload, project)
    assert installed.returncode == 2 and "forbidden" in installed.stderr


def test_registration_block_is_the_launcher_in_exec_form() -> None:
    block = json.loads(hooks.registration_block())
    for key in ("SessionStart", "PreToolUse", "Stop"):
        entry = block["hooks"][key][0]["hooks"][0]
        assert entry["command"] == "python"
        assert entry["args"][:3] == ["-X", "utf8", "-c"] and entry["args"][3] == hooks.LAUNCHER
    assert block["hooks"]["PreToolUse"][0]["matcher"] == "Bash"
    assert block["hooks"]["PreToolUse"][0]["hooks"][0]["args"][-1] == "pre-tool-use"
    assert "${" not in hooks.LAUNCHER and '"' not in hooks.LAUNCHER
