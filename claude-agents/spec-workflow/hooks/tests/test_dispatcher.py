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

import hooks

HOOKS_DIR = Path(__file__).resolve().parent.parent


def _install(target: Path) -> Path:
    """The FRAMEWORK's hooks in a scratch project. A project's own gates (ORDER outside 10..90) stay out, so these
    tests judge the framework alone in a project that has gates of its own (one project measured this file
    failing on the first project gate it added)."""
    hooks_dir = target / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    for src in HOOKS_DIR.glob("*.py"):
        if not hooks._is_project_gate(src):
            shutil.copy(src, hooks_dir / src.name)
    return hooks_dir


def _framework(event: str, hooks_dir: Path = HOOKS_DIR) -> list:
    return [g for g in hooks.discover_gates(event, hooks_dir) if 10 <= g[1] <= hooks.PROJECT_ORDER_FLOOR]


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


def _present_in_order(event: str, expected: list[str]) -> None:
    """The framework's gates are discovered, in this relative order. A project's own gates (ORDER above 100, or
    below 10) may stand anywhere among them: three projects' first project gate broke an exact-list assertion."""
    names = [g[0] for g in hooks.discover_gates(event, HOOKS_DIR)]
    missing = [name for name in expected if name not in names]
    assert not missing, f"{event}: framework gates missing from discovery: {missing}; discovered {names}"
    positions = [names.index(name) for name in expected]
    assert positions == sorted(positions), f"{event}: framework gates out of order: {names}"


def test_framework_gates_are_discovered_in_order() -> None:
    _present_in_order(
        "pre-tool-use",
        [
            "no-env-vars",
            "no-foreground-sleep",
            "spec-tdd-gate",
            "claim-before-worktree",
            "merge-steward",
            "issue-filing-gate",
        ],
    )
    _present_in_order("stop", ["spec-stop-gate", "no-idle-wait", "issue-loop-gate"])
    _present_in_order("stop-failure", ["stop-failure-recorder"])
    _present_in_order("session-start", ["session-register", "scoped-temp-init", "continuous-work-reinject"])


def test_registration_matcher_is_the_union_of_the_gates_tools(tmp_path: Path) -> None:
    """A project gate on Write joins the PreToolUse matcher without a hand-edited block."""
    hooks_dir = _install(tmp_path)
    framework = hooks.tool_matcher("pre-tool-use", hooks_dir)
    assert framework is not None and set(framework.split("|")) == {
        "Bash",
        "shell",
        "execute_bash",
        "execute_cmd",
        "executeBash",
    }, "the shell tools of both hosts, which the same gates serve"
    # Module names unique to this test: discover_gates imports by module name, and sys.modules keeps the first
    # module of a name for the whole pytest process, so two tests must not write different gates under one name.
    (hooks_dir / "gate_union_write.py").write_text(
        "import hooklib as lib\n"
        "HOOK = 'union-write'\nEVENT = 'pre-tool-use'\nORDER = 150\nTOOLS = {'Write', 'Edit'}\n"
        "def run(ctx):\n    return lib.allow()\n",
        encoding="utf-8",
    )
    matcher = hooks.tool_matcher("pre-tool-use", hooks_dir)
    assert matcher is not None and set(matcher.split("|")) >= {"Bash", "Write", "Edit"}
    (hooks_dir / "gate_union_any.py").write_text(
        "import hooklib as lib\nHOOK = 'union-any'\nEVENT = 'pre-tool-use'\nORDER = 160\n"
        "def run(ctx):\n    return lib.allow()\n",
        encoding="utf-8",
    )
    assert hooks.tool_matcher("pre-tool-use", hooks_dir) is None, "a gate without TOOLS judges every tool"
    assert hooks._is_project_gate(hooks_dir / "gate_union_write.py")
    assert not hooks._is_project_gate(hooks_dir / "gate_tdd.py")


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
    assert names[-1] == "project-write-gate" and len(names) == len(_framework("pre-tool-use")) + 1
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
        flags = len(hooks.INTERPRETER_FLAGS)
        assert entry["args"][:flags] == hooks.INTERPRETER_FLAGS and entry["args"][flags] == "-c"
        assert entry["args"][flags + 1] == hooks.LAUNCHER
    # A project gate without TOOLS judges every tool, and then the entry carries no matcher at all.
    matcher = block["hooks"]["PreToolUse"][0].get("matcher")
    assert matcher is None or "Bash" in matcher.split("|"), f"the shell tool must be matched; matcher was {matcher!r}"
    assert block["hooks"]["PreToolUse"][0]["hooks"][0]["args"][-1] == "pre-tool-use"
    assert "${" not in hooks.LAUNCHER and '"' not in hooks.LAUNCHER


def test_a_gate_written_after_a_discovery_is_discovered(tmp_path: Path) -> None:
    """The path finder caches a directory listing; discovery must drop that cache, or a gate written after the
    first discovery in a process is missed (the matcher test was flaky without it)."""
    hooks_dir = _install(tmp_path)
    before = [g[0] for g in hooks.discover_gates("pre-tool-use", hooks_dir)]
    (hooks_dir / "gate_late_arrival.py").write_text(
        "import hooklib as lib\nHOOK = 'late-arrival'\nEVENT = 'pre-tool-use'\nORDER = 170\nTOOLS = {'Bash'}\n"
        "def run(ctx):\n    return lib.allow()\n",
        encoding="utf-8",
    )
    after = [g[0] for g in hooks.discover_gates("pre-tool-use", hooks_dir)]
    assert "late-arrival" not in before and after[-1] == "late-arrival"


def _settings(project: Path, block: dict) -> None:
    (project / ".claude").mkdir(parents=True, exist_ok=True)
    (project / ".claude" / "settings.json").write_text(json.dumps(block, indent=2), encoding="utf-8")


def test_registration_check_compares_the_pasted_block(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    assert hooks.registration_check(project)[0] == 2, "no settings.json"
    _settings(project, {"permissions": {}, **json.loads(hooks.registration_block())})
    assert hooks.registration_check(project)[0] == 0, "the printed block, pasted"
    pasted = json.loads(hooks.registration_block())
    pasted["hooks"]["PreToolUse"][0]["matcher"] = "Bash"
    pasted["hooks"].setdefault("PostToolUse", []).append(
        {"matcher": "Edit", "hooks": [{"type": "command", "command": "npx prettier --write"}]}
    )
    _settings(project, pasted)
    code, report = hooks.registration_check(project)
    assert code == 1 and "PreToolUse: matcher is 'Bash'" in report
    assert "PostToolUse" not in report, "a project's own hook in the same file is not the framework's business"
    del pasted["hooks"]["Stop"]
    _settings(project, pasted)
    assert "Stop: no framework entry" in hooks.registration_check(project)[1]
    stale = json.loads(hooks.registration_block())
    stale["hooks"]["Notification"] = [stale["hooks"]["Stop"][0]]
    _settings(project, stale)
    assert "Notification: a framework entry" in hooks.registration_check(project)[1]


def test_registration_check_tolerates_the_projects_own_hooks(tmp_path: Path) -> None:
    """The setup prompt lets a project keep its own hooks beside the framework's (the "union"): an extra entry in
    a framework event and an event of its own are both fine, and the check passes."""
    project = tmp_path / "project"
    project.mkdir()
    block = json.loads(hooks.registration_block())
    own = {"type": "command", "command": "python", "args": ["scripts/project_guard.py"], "timeout": 10}
    block["hooks"]["PreToolUse"].append({"matcher": "Write|Edit", "hooks": [own]})
    block["hooks"]["Stop"].insert(0, {"hooks": [dict(own, args=["scripts/notify.py"])]})
    block["hooks"]["PostToolUse"] = [{"matcher": "Edit", "hooks": [dict(own, args=["scripts/fmt.py"])]}]
    _settings(project, block)
    code, report = hooks.registration_check(project)
    assert code == 0, report
    (project / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
    assert hooks.registration_check(project)[0] == 2


def test_registration_check_runs_from_the_command_line(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _install(project)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    env.pop("PYTHONPATH", None)

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(project / ".claude" / "hooks" / "hooks.py"), "registration", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=60,
            check=False,
        )

    assert run("--check").returncode == 2, "nothing pasted yet"
    _settings(project, json.loads(run().stdout))  # the block THIS installation prints, pasted
    done = run("--check")
    assert done.returncode == 0, done.stdout + done.stderr
