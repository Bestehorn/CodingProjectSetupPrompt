"""Discovery installer for the CV Customizer Agent Suite (task 15).

Kiro CLI discovers custom agents **only** in ``.kiro/agents/`` (workspace) or
``~/.kiro/agents/`` (global); it does not scan the ``cli-agents/cv/`` authoring
tree. This module copies the authoring tree to a fixed installed root and
generates *discovery configs* in the discovery directory that point at it, per
the design's "fixed-location tree + generated discovery configs" model
[R16.8, R16.10, D-12].

Concretely, :func:`install_suite`:

1. Copies the entire authoring tree to ``<kiro-dir>/cv-suite/`` so prompts,
   ``shared/scripts/``, and ``shared/schemas/`` keep their relative layout.
2. For each of the seven agents writes a config into ``<kiro-dir>/agents/``
   named ``<canonical-name>.json`` where the canonical name is read from the
   authoring config's ``name`` field (never derived from the filename), with:

   * ``prompt`` rewritten to an **absolute** ``file://`` URI pointing at the
     installed ``prompt.md``;
   * every shared-script reference in ``toolsSettings.shell.allowedCommands``
     rewritten to the **absolute** installed script path under
     ``<kiro-dir>/cv-suite/shared/scripts/``.

3. Rewrites the shared-script references inside each installed ``prompt.md`` to
   the same absolute installed script paths.

All paths are resolved to absolute form at install time. **No environment
variables are read anywhere** and resolution never relies on the current
working directory: the authoring-tree root and the target ``.kiro`` directory
are explicit inputs [R15.1, R16.7]. Host-correct path strings are derived from
the host at install time -- absolute ``file://`` URIs (``file:///D:/.../prompt.md``
on Windows) via :meth:`pathlib.Path.as_uri`, and regex-escaped literal script
paths in ``allowedCommands`` -- so the installer remains cross-platform [D1].

A verification pass (:func:`verify_install`) confirms post-install invariants:
each generated config's on-disk ``name`` equals its canonical name, the
orchestrator's ``availableAgents``/``trustedAgents`` match the generated
delegate config basenames byte-for-byte, and every referenced prompt and script
exists at its resolved path [R16.10].
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Substring in authoring configs/prompts that locates the shared scripts dir.
AUTHORING_SCRIPTS_TOKEN = "cli-agents/cv/shared/scripts/"

#: The fixed installed-tree directory name under the ``.kiro`` install root.
SUITE_DIRNAME = "cv-suite"

#: The Kiro discovery directory name under the ``.kiro`` install root.
DISCOVERY_DIRNAME = "agents"

#: Names ignored when copying the authoring tree (caches / byproducts only).
_COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".hypothesis"
)

#: Matches an authoring shared-script reference and captures the script file.
_SCRIPT_REF_RE = re.compile(
    re.escape(AUTHORING_SCRIPTS_TOKEN) + r"([A-Za-z0-9_]+)\\?\.py"
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class InstallVerificationError(RuntimeError):
    """Raised when a post-install invariant does not hold."""


@dataclass
class InstalledAgent:
    """One installed agent: where it came from and what was generated."""

    canonical_name: str
    authoring_config_path: Path
    authoring_dir: Path
    installed_dir: Path
    installed_prompt_path: Path
    prompt_uri: str
    discovery_config_path: Path
    referenced_script_paths: list[Path] = field(default_factory=list)
    is_orchestrator: bool = False


@dataclass
class InstallResult:
    """Structured outcome of an install, suitable for verification/tests."""

    mode: str
    kiro_dir: Path
    suite_dir: Path
    discovery_dir: Path
    agents: list[InstalledAgent] = field(default_factory=list)

    @property
    def orchestrator(self) -> InstalledAgent | None:
        for agent in self.agents:
            if agent.is_orchestrator:
                return agent
        return None

    def agent_names(self) -> list[str]:
        return [a.canonical_name for a in self.agents]

    def delegate_names(self) -> list[str]:
        return [a.canonical_name for a in self.agents if not a.is_orchestrator]


# ---------------------------------------------------------------------------
# Mode / path resolution (explicit inputs only -- never the environment)
# ---------------------------------------------------------------------------


def default_authoring_root() -> Path:
    """The ``cli-agents/cv/`` authoring root inferred from this file's location.

    ``install_agents.py`` lives at ``cli-agents/cv/shared/install/`` so the
    authoring root is three parents up. Derived purely from ``__file__`` -- no
    environment variables and no reliance on the current working directory.
    """
    return Path(__file__).resolve().parents[2]


def kiro_dir_for_mode(
    mode: str,
    *,
    workspace_root: Path | None = None,
    home_dir: Path | None = None,
) -> Path:
    """Resolve the target ``.kiro`` directory for an install ``mode``.

    * ``"workspace"`` -> ``<workspace_root>/.kiro`` (requires ``workspace_root``).
    * ``"global"``    -> ``<home_dir>/.kiro`` (requires an explicit ``home_dir``;
      this installer never calls :meth:`Path.home` or reads ``$HOME`` /
      ``%USERPROFILE%``).

    Both ``workspace_root`` and ``home_dir`` are explicit inputs so the choice of
    install location is fully caller-controlled with no environment access.
    """
    if mode == "workspace":
        if workspace_root is None:
            raise ValueError("workspace mode requires an explicit workspace_root")
        return Path(workspace_root).resolve() / ".kiro"
    if mode == "global":
        if home_dir is None:
            raise ValueError(
                "global mode requires an explicit home_dir "
                "(this installer never reads environment variables)"
            )
        return Path(home_dir).resolve() / ".kiro"
    raise ValueError(f"unknown install mode {mode!r} (expected 'workspace' or 'global')")


# ---------------------------------------------------------------------------
# Agent discovery within the authoring tree
# ---------------------------------------------------------------------------


def _find_agent_configs(authoring_root: Path) -> list[Path]:
    """Return the seven ``KiroCLIAgent-*.json`` config paths, sorted by path.

    Only immediate agent subdirectories of the authoring root are scanned;
    ``shared/`` and ``tests/`` never contain an agent config.
    """
    configs: list[Path] = []
    for child in sorted(authoring_root.iterdir()):
        if not child.is_dir() or child.name in {"shared", "tests"}:
            continue
        configs.extend(sorted(child.glob("KiroCLIAgent-*.json")))
    return configs


def _prompt_relpath(prompt_field: str) -> str:
    """Extract the agent-relative prompt path from a ``file://`` ``prompt`` field."""
    value = prompt_field
    if value.startswith("file://"):
        value = value[len("file://") :]
    value = value.lstrip("/")
    if value.startswith("./"):
        value = value[2:]
    return value


# ---------------------------------------------------------------------------
# Rewriting helpers
# ---------------------------------------------------------------------------


def _scripts_prefix_literal(suite_dir: Path) -> str:
    """Absolute installed ``shared/scripts/`` prefix as a literal host path."""
    return str((suite_dir / "shared" / "scripts").resolve()) + os.sep


def _rewrite_allowed_command(command: str, scripts_prefix_literal: str) -> str:
    """Rewrite a single ``allowedCommands`` regex to the installed script path.

    The authoring token is replaced by the **regex-escaped** absolute installed
    scripts prefix so the resulting pattern matches the literal installed path
    (backslash separators on Windows are escaped correctly) [D1]. Commands that
    do not reference a shared script (e.g. the editor's ``tmp/.../*.py`` wrapper
    patterns) are returned unchanged.
    """
    if AUTHORING_SCRIPTS_TOKEN not in command:
        return command
    return command.replace(AUTHORING_SCRIPTS_TOKEN, re.escape(scripts_prefix_literal))


def _referenced_script_names(text: str) -> list[str]:
    """Return the distinct ``<script>.py`` filenames referenced in ``text``."""
    seen: list[str] = []
    for match in _SCRIPT_REF_RE.finditer(text):
        name = match.group(1) + ".py"
        if name not in seen:
            seen.append(name)
    return seen


# ---------------------------------------------------------------------------
# Core install
# ---------------------------------------------------------------------------


def _copy_authoring_tree(authoring_root: Path, suite_dir: Path) -> None:
    """Copy the authoring tree to ``suite_dir`` (clean install), ignoring caches."""
    if suite_dir.exists():
        if suite_dir.name != SUITE_DIRNAME:
            raise ValueError(
                f"refusing to remove non-suite directory {suite_dir}"
            )
        shutil.rmtree(suite_dir)
    shutil.copytree(authoring_root, suite_dir, ignore=_COPY_IGNORE)


def _generate_agent(
    config_path: Path,
    authoring_root: Path,
    suite_dir: Path,
    discovery_dir: Path,
) -> InstalledAgent:
    """Generate one discovery config + rewrite its installed prompt."""
    config = json.loads(config_path.read_text(encoding="utf-8"))

    canonical_name = config.get("name")
    if not isinstance(canonical_name, str) or not canonical_name:
        raise InstallVerificationError(
            f"authoring config {config_path} has no usable 'name' field"
        )

    authoring_dir = config_path.parent
    rel_dir = authoring_dir.relative_to(authoring_root)
    installed_dir = (suite_dir / rel_dir).resolve()

    prompt_rel = _prompt_relpath(config.get("prompt", "file://prompt.md"))
    installed_prompt_path = (installed_dir / prompt_rel).resolve()
    prompt_uri = installed_prompt_path.as_uri()

    scripts_prefix_literal = _scripts_prefix_literal(suite_dir)

    # Collect every shared-script filename this agent references, from the
    # authoring allowedCommands, *before* the patterns are rewritten.
    referenced_names: list[str] = []

    def _note_scripts(text: str) -> None:
        for name in _referenced_script_names(text):
            if name not in referenced_names:
                referenced_names.append(name)

    # --- rewrite the discovery config (prompt + allowedCommands) -----------
    config["prompt"] = prompt_uri
    shell_settings = config.get("toolsSettings", {}).get("shell")
    if isinstance(shell_settings, dict) and isinstance(
        shell_settings.get("allowedCommands"), list
    ):
        for cmd in shell_settings["allowedCommands"]:
            _note_scripts(cmd)
        shell_settings["allowedCommands"] = [
            _rewrite_allowed_command(cmd, scripts_prefix_literal)
            for cmd in shell_settings["allowedCommands"]
        ]

    discovery_config_path = discovery_dir / f"{canonical_name}.json"
    discovery_config_path.write_text(
        json.dumps(config, indent=4, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # --- rewrite shared-script references inside the installed prompt ------
    if installed_prompt_path.exists():
        prompt_text = installed_prompt_path.read_text(encoding="utf-8")
        _note_scripts(prompt_text)
        rewritten_prompt = prompt_text.replace(
            AUTHORING_SCRIPTS_TOKEN, scripts_prefix_literal
        )
        if rewritten_prompt != prompt_text:
            installed_prompt_path.write_text(rewritten_prompt, encoding="utf-8")

    scripts_dir = (suite_dir / "shared" / "scripts").resolve()
    referenced_script_paths = [scripts_dir / name for name in referenced_names]

    subagent_settings = config.get("toolsSettings", {}).get("subagent", {})
    is_orchestrator = "availableAgents" in subagent_settings

    return InstalledAgent(
        canonical_name=canonical_name,
        authoring_config_path=config_path,
        authoring_dir=authoring_dir,
        installed_dir=installed_dir,
        installed_prompt_path=installed_prompt_path,
        prompt_uri=prompt_uri,
        discovery_config_path=discovery_config_path,
        referenced_script_paths=referenced_script_paths,
        is_orchestrator=is_orchestrator,
    )


def install_suite(
    authoring_root: Path,
    kiro_dir: Path,
    *,
    mode: str = "workspace",
    verify: bool = True,
) -> InstallResult:
    """Install the suite into ``kiro_dir`` from ``authoring_root``.

    ``authoring_root`` is the ``cli-agents/cv/`` directory and ``kiro_dir`` is the
    target ``.kiro`` directory (``<workspace>/.kiro`` or ``<home>/.kiro``); both
    are resolved to absolute form. The installed tree lands at
    ``<kiro_dir>/cv-suite/`` and discovery configs at ``<kiro_dir>/agents/``.

    Returns an :class:`InstallResult`. When ``verify`` is true (default) a
    verification pass runs and raises :class:`InstallVerificationError` on any
    mismatch before returning.
    """
    authoring_root = Path(authoring_root).resolve()
    kiro_dir = Path(kiro_dir).resolve()

    if not authoring_root.is_dir():
        raise FileNotFoundError(f"authoring root not found: {authoring_root}")

    suite_dir = (kiro_dir / SUITE_DIRNAME).resolve()
    discovery_dir = (kiro_dir / DISCOVERY_DIRNAME).resolve()

    config_paths = _find_agent_configs(authoring_root)
    if not config_paths:
        raise InstallVerificationError(
            f"no KiroCLIAgent-*.json configs found under {authoring_root}"
        )

    _copy_authoring_tree(authoring_root, suite_dir)
    discovery_dir.mkdir(parents=True, exist_ok=True)

    result = InstallResult(
        mode=mode, kiro_dir=kiro_dir, suite_dir=suite_dir, discovery_dir=discovery_dir
    )
    for config_path in config_paths:
        result.agents.append(
            _generate_agent(config_path, authoring_root, suite_dir, discovery_dir)
        )

    if verify:
        verify_install(result)
    return result


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_install(result: InstallResult) -> None:
    """Verify post-install invariants; raise on the first violation [R16.10].

    Checks:

    * each generated discovery config exists and its on-disk ``name`` equals the
      canonical name and the file basename (``<name>.json``) byte-for-byte;
    * each config's ``prompt`` ``file://`` URI resolves to an existing file;
    * every referenced shared script exists at its resolved installed path;
    * exactly one orchestrator exists and its ``availableAgents`` and
      ``trustedAgents`` equal the set of generated delegate names byte-for-byte,
      with a matching ``<name>.json`` discovery config for each entry.
    """
    if not result.agents:
        raise InstallVerificationError("no agents were installed")

    delegate_names = set(result.delegate_names())

    for agent in result.agents:
        path = agent.discovery_config_path
        if not path.exists():
            raise InstallVerificationError(f"discovery config missing: {path}")

        if path.name != f"{agent.canonical_name}.json":
            raise InstallVerificationError(
                f"discovery config basename {path.name!r} does not match "
                f"canonical name {agent.canonical_name!r}"
            )

        config = json.loads(path.read_text(encoding="utf-8"))
        if config.get("name") != agent.canonical_name:
            raise InstallVerificationError(
                f"config {path} 'name' is {config.get('name')!r}, "
                f"expected {agent.canonical_name!r}"
            )

        prompt_path = _uri_to_path(config.get("prompt", ""))
        if prompt_path is None or not prompt_path.exists():
            raise InstallVerificationError(
                f"config {path} prompt does not resolve to an existing file: "
                f"{config.get('prompt')!r}"
            )

        for script_path in agent.referenced_script_paths:
            if not script_path.exists():
                raise InstallVerificationError(
                    f"agent {agent.canonical_name} references missing script: "
                    f"{script_path}"
                )

    orchestrators = [a for a in result.agents if a.is_orchestrator]
    if len(orchestrators) != 1:
        raise InstallVerificationError(
            f"expected exactly one orchestrator, found {len(orchestrators)}"
        )

    orch_config = json.loads(
        orchestrators[0].discovery_config_path.read_text(encoding="utf-8")
    )
    subagent = orch_config.get("toolsSettings", {}).get("subagent", {})
    for key in ("availableAgents", "trustedAgents"):
        entries = subagent.get(key)
        if not isinstance(entries, list):
            raise InstallVerificationError(
                f"orchestrator config missing toolsSettings.subagent.{key}"
            )
        if set(entries) != delegate_names:
            raise InstallVerificationError(
                f"orchestrator {key} {sorted(entries)} != "
                f"generated delegate names {sorted(delegate_names)}"
            )
        for entry in entries:
            expected = result.discovery_dir / f"{entry}.json"
            if not expected.exists():
                raise InstallVerificationError(
                    f"orchestrator {key} entry {entry!r} has no discovery "
                    f"config at {expected}"
                )


def _uri_to_path(uri: str) -> Path | None:
    """Convert a ``file://`` URI back to a host path (inverse of ``as_uri``)."""
    if not uri.startswith("file://"):
        return None
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    parsed = urlparse(uri)
    return Path(url2pathname(parsed.path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install_agents.py",
        description=(
            "Install the CV Customizer Agent Suite into a Kiro-discoverable "
            "location. Install location is chosen by explicit arguments only; "
            "no environment variables are ever read."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("workspace", "global"),
        default="workspace",
        help="Install scope: 'workspace' (<workspace-root>/.kiro) or 'global' "
        "(<home-dir>/.kiro). Default: workspace.",
    )
    parser.add_argument(
        "--authoring-root",
        type=Path,
        default=None,
        help="Path to the cli-agents/cv/ authoring tree. Default: inferred from "
        "this script's location.",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Workspace root for --mode workspace. Default: inferred repo root.",
    )
    parser.add_argument(
        "--home-dir",
        type=Path,
        default=None,
        help="Home directory for --mode global. REQUIRED for global installs "
        "(passed explicitly; never read from the environment).",
    )
    parser.add_argument(
        "--kiro-dir",
        type=Path,
        default=None,
        help="Explicit target .kiro directory. Overrides --mode/--workspace-root/"
        "--home-dir when given.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the post-install verification pass.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    authoring_root = (
        args.authoring_root.resolve()
        if args.authoring_root is not None
        else default_authoring_root()
    )

    if args.kiro_dir is not None:
        kiro_dir = args.kiro_dir.resolve()
    else:
        workspace_root = args.workspace_root
        if args.mode == "workspace" and workspace_root is None:
            # Repo root is two parents above the authoring root.
            workspace_root = authoring_root.parents[1]
        try:
            kiro_dir = kiro_dir_for_mode(
                args.mode, workspace_root=workspace_root, home_dir=args.home_dir
            )
        except ValueError as exc:
            parser.error(str(exc))

    try:
        result = install_suite(
            authoring_root, kiro_dir, mode=args.mode, verify=not args.no_verify
        )
    except (InstallVerificationError, FileNotFoundError) as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 1

    print(f"Installed suite tree:   {result.suite_dir}")
    print(f"Discovery configs dir:  {result.discovery_dir}")
    for agent in result.agents:
        role = "orchestrator" if agent.is_orchestrator else "delegate"
        print(f"  - {agent.canonical_name:<28} ({role}) -> {agent.discovery_config_path.name}")
    print(f"Installed and verified {len(result.agents)} agent configs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
