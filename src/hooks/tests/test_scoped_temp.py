"""pytest port of tests/test_scoped_temp.sh — the self-writing settings.local.json env block.

The bash suite (scoped-temp-init.sh) is the specification; its 26 assertions are mirrored here one `assert`
each, carrying the bash label as the assertion message, grouped by the bash scenario they belong to. The hook
must NEVER exit non-zero and must self-write the env block when missing — the block is per-tree (an absolute
path), a manual step per clone/worktree was skipped in practice, and a notice nobody acts on is not a
mechanism. The dangerous directions pinned here:
  * it must never clobber a settings file it cannot parse, and never fight a custom TMPDIR the user chose;
  * it must MERGE — other top-level keys and other env vars survive the write;
  * it must be silent when everything is already right (SessionStart stdout is context).

bash `run_hook` ran with CLAUDE_PROJECT_DIR=<arena>, an empty stdin and stderr discarded, observing only the
exit code and stdout; `run_hook` here builds the same Context. The "degraded host" block of the bash suite
breaks the python the script shelled out to; the Python gate's equivalent repair machinery is its atomic
write, which the port breaks instead. Tests marked "(extra)" go beyond the bash suite.
"""

from __future__ import annotations

import json
import os
import re
import types
from pathlib import Path
from typing import Dict, Optional

import pytest

import gate_scoped_temp
import hooklib as lib

HOOKS = Path(__file__).resolve().parent.parent


@pytest.fixture
def arena(tmp_path: Path) -> Path:
    """bash `new_arena`: a fresh project tree holding an empty `.claude/`."""
    arena = tmp_path / "arena"
    (arena / ".claude").mkdir(parents=True)
    return arena


def settings_of(arena: Path) -> Path:
    return arena / ".claude" / "settings.local.json"


def run_hook(
    arena: Path,
    environ: Optional[Dict[str, str]] = None,
    payload: str = "",
    cwd: Optional[Path] = None,
) -> lib.Decision:
    """bash `run_hook`: CLAUDE_PROJECT_DIR=<arena>, nothing on stdin."""
    env = {"CLAUDE_PROJECT_DIR": str(arena)} if environ is None else environ
    ctx = lib.Context(lib.Payload.parse(payload), environ=env, hooks_dir=HOOKS, cwd=cwd or arena)
    return gate_scoped_temp.run(ctx)


def json_env(arena: Path, name: str) -> str:
    """bash `json_env`: the env var's value from the arena's settings file, "" on any failure."""
    try:
        data = json.loads(settings_of(arena).read_text(encoding="utf-8")) or {}
        return (data.get("env") or {}).get(name) or ""
    except Exception:  # noqa: BLE001 — mirrors the bash helper, which printed "" on any exception
        return ""


def json_key(arena: Path, key: str) -> str:
    """bash `json_key`: json.dumps of a top-level key, "PARSE-FAIL" when the file does not parse."""
    try:
        data = json.loads(settings_of(arena).read_text(encoding="utf-8")) or {}
        return json.dumps(data.get(key))
    except Exception:  # noqa: BLE001
        return "PARSE-FAIL"


def is_absolute_like_bash(value: str) -> bool:
    """bash: `case "$v" in [A-Za-z]:*|/*)` — a drive-letter or root-anchored path."""
    return bool(re.match(r"^(?:[A-Za-z]:|/)", value)) and os.path.isabs(value)


# ---------------------------------------------------------------------------------------------------------
# self-configuration — a missing block is WRITTEN, not merely announced
# ---------------------------------------------------------------------------------------------------------


def test_no_settings_file_block_is_written(arena: Path) -> None:
    decision = run_hook(arena)
    assert decision.exit_code == 0, "no settings file: exit 0"
    assert re.search(r"takes effect.*NEXT session", decision.stdout, re.S), (
        f"no settings file: announces next-session effect; got {decision.stdout!r}"
    )
    assert settings_of(arena).is_file(), "settings file was created"
    tmpdir_val = json_env(arena, "TMPDIR")
    assert tmpdir_val.endswith("os-temp"), f"TMPDIR points at .../os-temp; got {tmpdir_val!r}"
    assert is_absolute_like_bash(tmpdir_val), f"TMPDIR is an ABSOLUTE path; got {tmpdir_val!r}"
    assert json_env(arena, "TEMP") == tmpdir_val, "TEMP matches TMPDIR"
    assert json_env(arena, "TMP") == tmpdir_val, "TMP matches TMPDIR"
    assert (arena / "tmp" / "os-temp").is_dir(), "tmp/os-temp directory exists"


def test_second_run_is_idempotent_and_silent(arena: Path) -> None:
    """Idempotence: the second run has nothing to do and nothing to say."""
    run_hook(arena)
    before = settings_of(arena).read_bytes()
    decision = run_hook(arena)
    assert decision.exit_code == 0, "second run: exit 0"
    assert decision.stdout == "", f"second run: SILENT (stdout is context); got {decision.stdout!r}"
    assert settings_of(arena).read_bytes() == before, "second run: file byte-identical"


def test_written_path_names_this_tree(arena: Path) -> None:
    """(extra) The value written is THIS tree's tmp/os-temp and the one message names that very path."""
    decision = run_hook(arena)
    target = str((arena / "tmp" / "os-temp").resolve())
    assert json_env(arena, "TMPDIR") == target
    assert target in decision.stdout


# ---------------------------------------------------------------------------------------------------------
# merge semantics — never overwrite, never fight
# ---------------------------------------------------------------------------------------------------------


def test_merge_preserves_other_keys_and_env_vars(arena: Path) -> None:
    """Other top-level keys and other env vars survive the merge."""
    settings_of(arena).write_text('{"permissions":{"allow":["Bash(ls:*)"]},"env":{"FOO":"bar"}}', encoding="utf-8")
    decision = run_hook(arena)
    assert decision.exit_code == 0, "merge run: exit 0"
    assert json_key(arena, "permissions") == '{"allow": ["Bash(ls:*)"]}', "other top-level key survives"
    assert json_env(arena, "FOO") == "bar", "other env var survives"
    assert json_env(arena, "TMPDIR").endswith("os-temp"), "TMPDIR added beside FOO"


def test_custom_tmpdir_is_respected(arena: Path) -> None:
    """A custom TMPDIR is respected: silent, nothing written."""
    settings_of(arena).write_text('{"env":{"TMPDIR":"/my/custom/tempdir"}}', encoding="utf-8")
    before = settings_of(arena).read_bytes()
    decision = run_hook(arena)
    assert decision.exit_code == 0, "custom TMPDIR: exit 0"
    assert decision.stdout == "", f"custom TMPDIR: silent; got {decision.stdout!r}"
    assert settings_of(arena).read_bytes() == before, "custom TMPDIR: file untouched"


def test_malformed_json_is_never_touched(arena: Path) -> None:
    """A file that does not parse is NEVER touched."""
    settings_of(arena).write_text("{oops, not json", encoding="utf-8")
    before = settings_of(arena).read_bytes()
    decision = run_hook(arena)
    assert decision.exit_code == 0, "malformed JSON: exit 0"
    assert re.search(r"not a valid.*JSON", decision.stdout, re.S), (
        f"malformed JSON: says so instead of clobbering; got {decision.stdout!r}"
    )
    assert settings_of(arena).read_bytes() == before, "malformed JSON: file byte-identical"


def test_json_array_settings_is_never_touched(arena: Path) -> None:
    """A JSON array is an invalid settings shape: same never-touch rule."""
    settings_of(arena).write_text("[1,2,3]", encoding="utf-8")
    before = settings_of(arena).read_bytes()
    decision = run_hook(arena)
    assert settings_of(arena).read_bytes() == before, "JSON-array settings: file byte-identical"
    assert decision.exit_code == 0  # (extra) exit is ALWAYS 0
    assert re.search(r"not a valid.*JSON", decision.stdout, re.S)  # (extra) reported, not silently skipped


# ---------------------------------------------------------------------------------------------------------
# degraded hosts — a broken repair still exits 0 and still speaks
# ---------------------------------------------------------------------------------------------------------


def test_broken_write_machinery_exits_0_and_speaks(arena: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """bash: python/python3 shims that `exit 9`. Here the atomic write itself fails: the hook must fall back
    to the notice, write nothing, and still exit 0."""

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError(9, "repair machinery unavailable (shim exit 9)")

    monkeypatch.setattr(gate_scoped_temp, "tempfile", types.SimpleNamespace(NamedTemporaryFile=boom))
    decision = run_hook(arena)
    assert decision.exit_code == 0, "broken python: exit 0"
    assert "settings.local.json" in decision.stdout, (
        f"broken python: notice names the settings file; got {decision.stdout!r}"
    )
    assert not settings_of(arena).exists(), "broken python: nothing written"
    assert (arena / "tmp" / "os-temp").is_dir(), "broken python: tmp/os-temp still created"


# ---------------------------------------------------------------------------------------------------------
# (extra) project-dir resolution: CLAUDE_PROJECT_DIR, then the payload cwd, then the process cwd.
# ---------------------------------------------------------------------------------------------------------


def test_project_dir_resolution_order(tmp_path: Path) -> None:
    by_env, by_payload, by_cwd = (tmp_path / name for name in ("by-env", "by-payload", "by-cwd"))
    for root in (by_env, by_payload, by_cwd):
        (root / ".claude").mkdir(parents=True)

    run_hook(
        by_env,
        environ={"CLAUDE_PROJECT_DIR": str(by_env)},
        payload=json.dumps({"cwd": by_payload.as_posix()}),
        cwd=by_cwd,
    )
    assert (
        settings_of(by_env).is_file() and not settings_of(by_payload).exists() and not settings_of(by_cwd).exists()
    ), "CLAUDE_PROJECT_DIR wins over the payload cwd and the process cwd"

    run_hook(
        by_payload,
        environ={},
        payload=json.dumps({"cwd": by_payload.as_posix()}),
        cwd=by_cwd,
    )
    assert settings_of(by_payload).is_file() and not settings_of(by_cwd).exists(), (
        "without CLAUDE_PROJECT_DIR the payload cwd is the project"
    )

    run_hook(by_cwd, environ={}, payload="", cwd=by_cwd)
    assert settings_of(by_cwd).is_file(), "with neither, the process cwd is the project"
    assert json_env(by_cwd, "TMPDIR") == str((by_cwd / "tmp" / "os-temp").resolve())
