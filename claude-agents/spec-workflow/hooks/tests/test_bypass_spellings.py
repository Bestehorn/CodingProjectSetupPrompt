"""The push gate's bypass classifier, as a corpus in both directions. A text classifier let 37 of 79 bypass
spellings through and refused `-- -n` (a project's measurement); the token classifier is pinned here, block arm
and allow arm, so a regression in either direction is a red test and not a transcript."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import gate_tdd
import hooklib as lib

HOOKS_DIR = Path(__file__).resolve().parent.parent

BLOCKED = [
    "git commit -n -m x",
    "git commit --no-verify -m x",
    "git commit --no-verif -m x",
    "git commit --no-veri -m x",
    "git commit -an -m x",
    "git commit -qn -m x",
    "git commit -na -m x",
    "git commit -m x -n",
    "git commit -m x --no-verify",
    "git -C sub commit -n -m x",
    "git --no-pager commit -n -m x",
    "git -c core.hooksPath=/dev/null commit -m x",
    "git -c core.hookspath= commit -m x",
    'git -ccore.hooksPath=/tmp/none commit -m "x"',
    "git config core.hooksPath /tmp/none",
    "git config --local core.hookspath .nohooks",
    "git config --unset core.hooksPath",
    "cd sub\ngit commit -n -m x",
    "echo a && git commit -n -m b",
    "echo a; git push --no-verify",
    "git push --no-verify",
    "git push --no-veri origin main",
    "git push origin main --no-verify",
    "git -c core.hooksPath=/x push origin main",
    '"C:/Program Files/Git/bin/git.exe" commit -n -m x',
    "/usr/bin/git commit -n -m x",
    "git commit -m 'a' -n 2>&1",
    "git commit -n -m 'use -n carefully'",
    "git commit \\\n  -n -m x",
]

ALLOWED = [
    "git commit -m x",
    "git commit -am x",
    "git commit -m 'use -n carefully'",
    'git commit -m "--no-verify is forbidden"',
    "git commit -mn",
    "git commit -m x -- -n",
    "git commit -m x -- --no-verify",
    "git commit -m --no-verify",  # the MESSAGE is "--no-verify": -m takes the next word (measured: refused)
    "git commit --message --no-verify",
    "git commit -am --no-verify",  # the cluster ends with a value letter, so the next word is its value
    "git commit -F -n",  # the message FILE is named "-n"
    "git push -o --no-verify origin main",  # a push option for the server, not a hook bypass
    "git push",
    "git push -n origin main",
    "git push --dry-run",
    "git push --no-verbose",
    "git stash push -m x",
    "git log -n 5",
    "git diff --name-only",
    "git config --get core.hooksPath",
    "git config --list",
    "git config user.name x",
    "grep -n 'git commit' file.txt",
    "echo 'git commit -n'",
    "git commit -m 'x' && git push origin main",
    "git rebase -n",
    "python scripts/run_tests.py -n 4",
]


def _ctx(tmp_path: Path, command: str) -> lib.Context:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return lib.Context(lib.Payload.parse(payload), environ={}, hooks_dir=HOOKS_DIR, cwd=tmp_path)


@pytest.mark.parametrize("command", BLOCKED)
def test_bypass_spelling_is_refused(tmp_path: Path, command: str) -> None:
    decision = gate_tdd.run(_ctx(tmp_path, command))
    assert decision.exit_code == 2, f"{command!r} was allowed"
    assert "forbidden" in decision.stderr or "hooksPath" in decision.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_non_bypass_is_allowed(tmp_path: Path, command: str) -> None:
    decision = gate_tdd.run(_ctx(tmp_path, command))
    assert decision.exit_code == 0, f"{command!r} was refused: {decision.stderr}"


def test_classification_sees_every_simple_command() -> None:
    found = gate_tdd.classify("git commit -m x && git push origin main")
    assert found.is_commit and found.is_push and not found.bypass
    assert gate_tdd.classify("git stash push -m x").is_push is False
    assert gate_tdd.classify("git commit -m x -- -n").bypass == ""


def test_unbalanced_quote_falls_back_to_text_classification() -> None:
    assert gate_tdd.classify("git commit -n -m 'unterminated").bypass
    assert gate_tdd.classify("echo 'unterminated").is_commit is False
