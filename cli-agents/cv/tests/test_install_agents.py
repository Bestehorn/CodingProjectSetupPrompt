"""Tests for the discovery installer ``shared/install/install_agents.py`` (task 15.1).

The installer copies the ``cli-agents/cv/`` authoring tree to a fixed installed
root (``<.kiro>/cv-suite/``) and generates thin *discovery configs* under
``<.kiro>/agents/`` that Kiro CLI can actually find. These tests install into a
**temporary directory only** (pytest ``tmp_path`` / ``tmp_path_factory``) -- they
never write into the real ``.kiro/`` -- and assert the post-install invariants
from Requirements 16.6-16.10 and 15.1:

* exactly seven discovery configs exist, one per canonical name, with the
  ``name`` field read from the authoring config (not derived from the filename);
* every config's ``prompt`` ``file://`` URI and every rewritten shared-script
  reference resolve to **existing** files inside the installed tree;
* the orchestrator's ``availableAgents``/``trustedAgents`` equal the generated
  delegate config basenames byte-for-byte;
* both ``workspace`` and ``global`` install-root modes work (``global`` is
  simulated by pointing an explicit ``home_dir`` at a temp dir -- never via an
  environment variable);
* on a Windows host the emitted ``file:///D:/...`` URIs and the regex-escaped
  backslash ``allowedCommands`` patterns are well-formed and match the real
  installed paths.

No environment variables are read; the install location is chosen by explicit
arguments. Paths derive from this file's location so the suite runs regardless
of the invocation cwd.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

# Make ``shared/install/install_agents.py`` importable by module name without
# environment variables or an install step. Derived purely from this file's
# location (mirrors the conftest convention for ``shared/scripts``).
_INSTALL_DIR = Path(__file__).resolve().parent.parent / "shared" / "install"
if str(_INSTALL_DIR) not in sys.path:
    sys.path.insert(0, str(_INSTALL_DIR))

import install_agents as ia  # noqa: E402


# The seven canonical names per Requirement 16.3 / D-13.
EXPECTED_AGENT_NAMES = {
    "cv-orchestrator",
    "cv-editor",
    "cv-spell-format-reviewer",
    "cv-language-content-reviewer",
    "cv-jd-alignment-reviewer",
    "cv-ats-reviewer",
    "cv-hiring-manager-reviewer",
}

EXPECTED_DELEGATE_NAMES = EXPECTED_AGENT_NAMES - {"cv-orchestrator"}


# --------------------------------------------------------------------------
# Fixtures: install once per mode into a temp dir (never the real .kiro/)
# --------------------------------------------------------------------------


def _kiro_dir(mode: str, root: Path) -> Path:
    """Resolve the target ``.kiro`` dir for ``mode`` using an explicit temp root.

    ``global`` is simulated by passing the temp dir as an explicit ``home_dir``
    argument -- never by setting or reading an environment variable.
    """
    if mode == "workspace":
        return ia.kiro_dir_for_mode("workspace", workspace_root=root)
    return ia.kiro_dir_for_mode("global", home_dir=root)


@pytest.fixture(scope="module", params=["workspace", "global"])
def install_result(request, tmp_path_factory):
    """Install the suite into a fresh temp dir for each mode."""
    mode = request.param
    root = tmp_path_factory.mktemp(f"install-{mode}")
    kiro_dir = _kiro_dir(mode, root)
    result = ia.install_suite(ia.default_authoring_root(), kiro_dir, mode=mode)
    return result


@pytest.fixture(scope="module")
def scripts_install_dir(install_result) -> Path:
    return (install_result.suite_dir / "shared" / "scripts").resolve()


# --------------------------------------------------------------------------
# Sanity: the authoring root the installer infers is the cv tree
# --------------------------------------------------------------------------


def test_default_authoring_root_is_the_cv_tree():
    root = ia.default_authoring_root()
    assert root.name == "cv"
    assert (root / "orchestrator" / "KiroCLIAgent-CVOrchestrator.json").exists()
    assert (root / "shared" / "scripts").is_dir()


# --------------------------------------------------------------------------
# Seven discovery configs with correct ``name`` fields  [R16.8, 16.3, 16.4]
# --------------------------------------------------------------------------


def test_exactly_seven_discovery_configs_exist(install_result):
    configs = sorted(install_result.discovery_dir.glob("*.json"))
    assert len(configs) == 7, f"expected 7 discovery configs, found {len(configs)}"


def test_discovery_config_basenames_match_canonical_names(install_result):
    basenames = {p.stem for p in install_result.discovery_dir.glob("*.json")}
    assert basenames == EXPECTED_AGENT_NAMES


def test_each_discovery_config_name_field_matches_canonical(install_result):
    """``name`` is read from the authoring config and equals the file basename."""
    for path in install_result.discovery_dir.glob("*.json"):
        config = json.loads(path.read_text(encoding="utf-8"))
        assert config["name"] == path.stem, (
            f"{path.name}: name field {config['name']!r} != basename {path.stem!r}"
        )
        assert config["name"] in EXPECTED_AGENT_NAMES


def test_install_result_reports_seven_agents(install_result):
    assert set(install_result.agent_names()) == EXPECTED_AGENT_NAMES
    assert set(install_result.delegate_names()) == EXPECTED_DELEGATE_NAMES


# --------------------------------------------------------------------------
# Prompt URIs resolve to existing installed files  [R16.6, 16.8]
# --------------------------------------------------------------------------


def test_prompt_uri_resolves_to_existing_installed_file(install_result):
    for path in install_result.discovery_dir.glob("*.json"):
        config = json.loads(path.read_text(encoding="utf-8"))
        prompt_uri = config["prompt"]
        assert prompt_uri.startswith("file://"), prompt_uri
        resolved = ia._uri_to_path(prompt_uri)
        assert resolved is not None and resolved.exists(), (
            f"{path.name}: prompt {prompt_uri!r} does not resolve to a file"
        )
        # The resolved prompt lives inside the installed suite tree.
        assert install_result.suite_dir in resolved.parents


def test_prompt_uri_points_into_cv_suite_not_authoring_tree(install_result):
    for agent in install_result.agents:
        assert "cv-suite" in agent.prompt_uri
        assert "cli-agents" not in agent.prompt_uri


# --------------------------------------------------------------------------
# Rewritten shared-script references resolve to existing files  [R16.7, 16.10]
# --------------------------------------------------------------------------


def test_every_referenced_script_resolves_to_existing_file(install_result):
    """Each script an agent references exists at its installed path."""
    for agent in install_result.agents:
        for script_path in agent.referenced_script_paths:
            assert script_path.exists(), (
                f"{agent.canonical_name} references missing script {script_path}"
            )
            assert script_path.suffix == ".py"


def test_orchestrator_references_all_runtime_scripts(install_result):
    """The orchestrator's prompt/commands reference the shared scripts it drives."""
    orch = install_result.orchestrator
    assert orch is not None
    referenced = {p.name for p in orch.referenced_script_paths}
    # docx_normalize / input_normalize / page_count are run directly; the
    # orchestrator also hands the editor/ATS their engine paths in its prompt.
    assert {"docx_normalize.py", "input_normalize.py", "page_count.py"} <= referenced


def test_no_authoring_script_token_remains_in_generated_configs(install_result):
    """The authoring ``cli-agents/cv/shared/scripts/`` token is fully rewritten."""
    for path in install_result.discovery_dir.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert ia.AUTHORING_SCRIPTS_TOKEN not in text, (
            f"{path.name} still contains the authoring scripts token"
        )


def test_no_authoring_script_token_remains_in_installed_prompts(install_result):
    for agent in install_result.agents:
        if agent.installed_prompt_path.exists():
            text = agent.installed_prompt_path.read_text(encoding="utf-8")
            assert ia.AUTHORING_SCRIPTS_TOKEN not in text, (
                f"{agent.canonical_name} prompt still contains the authoring token"
            )


# --------------------------------------------------------------------------
# Orchestrator delegates == generated delegate basenames (byte-for-byte) [R16.10]
# --------------------------------------------------------------------------


def test_orchestrator_delegates_match_generated_config_basenames(install_result):
    orch_path = install_result.orchestrator.discovery_config_path
    orch = json.loads(orch_path.read_text(encoding="utf-8"))
    subagent = orch["toolsSettings"]["subagent"]

    generated_delegate_basenames = {
        p.stem
        for p in install_result.discovery_dir.glob("*.json")
        if p.stem != "cv-orchestrator"
    }

    for key in ("availableAgents", "trustedAgents"):
        entries = subagent[key]
        # byte-for-byte: same set, and each entry has a matching config file.
        assert set(entries) == generated_delegate_basenames, (
            f"{key} {sorted(entries)} != {sorted(generated_delegate_basenames)}"
        )
        assert set(entries) == EXPECTED_DELEGATE_NAMES
        for entry in entries:
            assert (install_result.discovery_dir / f"{entry}.json").exists()


def test_delegate_name_field_byte_identical_to_orchestrator_entry(install_result):
    """Each delegate's on-disk ``name`` matches the orchestrator entry exactly."""
    orch = json.loads(
        install_result.orchestrator.discovery_config_path.read_text(encoding="utf-8")
    )
    available = orch["toolsSettings"]["subagent"]["availableAgents"]
    for entry in available:
        delegate_cfg = json.loads(
            (install_result.discovery_dir / f"{entry}.json").read_text(encoding="utf-8")
        )
        assert delegate_cfg["name"] == entry  # byte-for-byte


# --------------------------------------------------------------------------
# Installed tree preserves the shared layout  [R16.8]
# --------------------------------------------------------------------------


def test_installed_tree_preserves_scripts_and_schemas(install_result, scripts_install_dir):
    for script in (
        "docx_edit.py",
        "docx_normalize.py",
        "input_normalize.py",
        "page_count.py",
        "ats_structural.py",
    ):
        assert (scripts_install_dir / script).exists()

    schemas_dir = install_result.suite_dir / "shared" / "schemas"
    for schema in (
        "finding.schema.json",
        "change_list.schema.json",
        "resume_state.schema.json",
    ):
        assert (schemas_dir / schema).exists()


def test_installed_tree_preserves_every_agent_prompt(install_result):
    for agent in install_result.agents:
        assert agent.installed_prompt_path.exists(), (
            f"{agent.canonical_name}: installed prompt missing"
        )


def test_install_excludes_cache_directories(install_result):
    """Caches/byproducts are not copied into the installed tree."""
    for junk in ("__pycache__", ".pytest_cache", ".hypothesis"):
        assert not list(install_result.suite_dir.rglob(junk)), (
            f"{junk} should be excluded from the installed tree"
        )


# --------------------------------------------------------------------------
# allowedCommands: valid regexes that match the real installed script paths
# (Windows-correct, regex-escaped backslash paths -- D1)
# --------------------------------------------------------------------------


def _interp_and_script(cmd: str, escaped_prefix: str) -> tuple[str, str] | None:
    """Return ``(plain_interpreter, script_basename)`` for a rewritten command.

    Returns ``None`` if the command does not reference a shared script (e.g. the
    editor's ``tmp/.../apply_changes.py`` wrapper patterns).
    """
    idx = cmd.find(escaped_prefix)
    if idx == -1:
        return None
    interp_token = cmd.split(" ", 1)[0]
    plain_interp = interp_token.replace("\\.", ".").replace("\\\\", "\\")
    rest = cmd[idx + len(escaped_prefix) :]
    match = re.match(r"([A-Za-z0-9_]+)\\?\.py", rest)
    assert match is not None, f"could not extract script name from {cmd!r}"
    return plain_interp, match.group(1) + ".py"


def test_allowed_commands_are_valid_regexes_matching_installed_paths(
    install_result, scripts_install_dir
):
    escaped_prefix = re.escape(str(scripts_install_dir) + os.sep)
    checked = 0
    for path in install_result.discovery_dir.glob("*.json"):
        config = json.loads(path.read_text(encoding="utf-8"))
        commands = (
            config.get("toolsSettings", {}).get("shell", {}).get("allowedCommands", [])
        )
        for cmd in commands:
            # Every allowedCommand must be a compilable regex.
            compiled = re.compile(cmd)
            parsed = _interp_and_script(cmd, escaped_prefix)
            if parsed is None:
                continue
            plain_interp, script_name = parsed
            script_abs = scripts_install_dir / script_name
            assert script_abs.exists(), f"{cmd!r} -> missing {script_abs}"
            # The regex-escaped pattern matches a literal invocation of the
            # real installed script path.
            literal = f"{plain_interp} {script_abs} --out result.json"
            assert compiled.match(literal), (
                f"pattern {cmd!r} does not match literal {literal!r}"
            )
            checked += 1
    assert checked > 0, "expected at least one shared-script allowedCommand"


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific path emission")
def test_windows_file_uri_emission(install_result):
    """On Windows, prompt URIs are ``file:///D:/...`` with forward slashes."""
    for agent in install_result.agents:
        uri = agent.prompt_uri
        assert re.match(r"^file:///[A-Za-z]:/", uri), uri
        assert "\\" not in uri, f"file URI must use forward slashes: {uri}"


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific path emission")
def test_windows_allowed_commands_use_escaped_backslashes(install_result, scripts_install_dir):
    """On Windows, script ``allowedCommands`` carry regex-escaped backslashes."""
    escaped_prefix = re.escape(str(scripts_install_dir) + os.sep)
    assert "\\\\" in escaped_prefix  # the escaped form doubles each backslash
    orch = json.loads(
        install_result.orchestrator.discovery_config_path.read_text(encoding="utf-8")
    )
    commands = orch["toolsSettings"]["shell"]["allowedCommands"]
    script_commands = [c for c in commands if escaped_prefix in c]
    assert script_commands, "orchestrator should have script allowedCommands"
    for cmd in script_commands:
        assert "\\\\" in cmd, f"expected escaped backslashes in {cmd!r}"


# --------------------------------------------------------------------------
# Mode handling and no-environment-variables guarantees  [R15.1]
# --------------------------------------------------------------------------


def test_workspace_and_global_install_into_distinct_roots(tmp_path):
    ws_root = tmp_path / "ws"
    home_root = tmp_path / "home"
    ws_root.mkdir()
    home_root.mkdir()

    ws = ia.install_suite(
        ia.default_authoring_root(),
        ia.kiro_dir_for_mode("workspace", workspace_root=ws_root),
        mode="workspace",
    )
    gl = ia.install_suite(
        ia.default_authoring_root(),
        ia.kiro_dir_for_mode("global", home_dir=home_root),
        mode="global",
    )

    assert ws.suite_dir == (ws_root / ".kiro" / "cv-suite").resolve()
    assert gl.suite_dir == (home_root / ".kiro" / "cv-suite").resolve()
    assert ws.suite_dir != gl.suite_dir
    # Both produce the full set of discovery configs.
    assert set(ws.agent_names()) == EXPECTED_AGENT_NAMES
    assert set(gl.agent_names()) == EXPECTED_AGENT_NAMES


def test_global_mode_requires_explicit_home_dir():
    """No env vars: global mode must be given an explicit home dir."""
    with pytest.raises(ValueError):
        ia.kiro_dir_for_mode("global", home_dir=None)


def test_workspace_mode_requires_explicit_workspace_root():
    with pytest.raises(ValueError):
        ia.kiro_dir_for_mode("workspace", workspace_root=None)


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        ia.kiro_dir_for_mode("user", home_dir=Path("."))


def test_installer_source_reads_no_environment_variables():
    """Static guard: the installer never touches the process environment or cwd."""
    source = (_INSTALL_DIR / "install_agents.py").read_text(encoding="utf-8")
    for forbidden in ("os.environ", "os.getenv", "getenv(", "expanduser", "Path.home()", "os.getcwd"):
        assert forbidden not in source, f"installer must not use {forbidden!r}"


# --------------------------------------------------------------------------
# Re-install idempotency and verification failure detection
# --------------------------------------------------------------------------


def test_reinstall_is_idempotent(tmp_path):
    kiro_dir = ia.kiro_dir_for_mode("workspace", workspace_root=tmp_path)
    first = ia.install_suite(ia.default_authoring_root(), kiro_dir, mode="workspace")
    second = ia.install_suite(ia.default_authoring_root(), kiro_dir, mode="workspace")

    assert set(first.agent_names()) == set(second.agent_names())
    first_configs = {
        p.name: p.read_text(encoding="utf-8")
        for p in first.discovery_dir.glob("*.json")
    }
    second_configs = {
        p.name: p.read_text(encoding="utf-8")
        for p in second.discovery_dir.glob("*.json")
    }
    assert first_configs == second_configs


def test_verify_install_raises_on_name_mismatch(tmp_path):
    kiro_dir = ia.kiro_dir_for_mode("workspace", workspace_root=tmp_path)
    result = ia.install_suite(ia.default_authoring_root(), kiro_dir, mode="workspace")

    # Tamper with one generated config's ``name`` and re-verify.
    victim = result.orchestrator.discovery_config_path
    config = json.loads(victim.read_text(encoding="utf-8"))
    config["name"] = "cv-not-the-orchestrator"
    victim.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")

    with pytest.raises(ia.InstallVerificationError):
        ia.verify_install(result)


def test_verify_install_raises_on_missing_prompt(tmp_path):
    kiro_dir = ia.kiro_dir_for_mode("workspace", workspace_root=tmp_path)
    result = ia.install_suite(ia.default_authoring_root(), kiro_dir, mode="workspace")

    # Remove an installed prompt the config points at.
    result.agents[0].installed_prompt_path.unlink()

    with pytest.raises(ia.InstallVerificationError):
        ia.verify_install(result)


def test_main_cli_workspace_install(tmp_path, capsys):
    """The CLI entry point performs a verified workspace install into a temp dir."""
    rc = ia.main(
        [
            "--mode",
            "workspace",
            "--workspace-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Installed and verified 7 agent configs." in out
    discovery = (tmp_path / ".kiro" / "agents").resolve()
    assert len(list(discovery.glob("*.json"))) == 7
