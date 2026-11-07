"""The repository layout guard: every asset is where its kind says, and every reference to one resolves.

The prompts, client READMEs and shipped docs name framework files by path. A path that no longer exists is not
caught anywhere else: it surfaces as an agent in some consumer project failing to find a file. These tests fail
on it here instead. Historical records (docs/reports/, .kiro/specs/, the agent design notes) describe the layout
as it was when they were written and are deliberately not checked; docs/README.md maps old paths to new.

Run: ``python scripts/run_tests.py test/test_layout.py`` (needs git on PATH).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL = re.compile(r"^(docs/reports/|\.kiro/specs/|docs/design/agents/.*\.txt$)")

# Directories that exist only in the framework, so a path under one of them is a framework reference. Paths
# such as scripts/, src/aws_config.py or docs/lessons-learned.md are the TARGET project's and are not checked.
FRAMEWORK_PATH = re.compile(
    r"(?<![\w./-])(?:prompts|clients|src/hooks|src/payload|templates|docs/reports|docs/design)/[^\s`'\"()\[\]|,;>…]*"
)
OLD_LAYOUT = re.compile(
    r"(?<![\w./-])(?:claude-agents|cli-agents|claude-commands|kiro-prompts|project-docs)/"
    r"|\b[\w-]+\.py\.template\b"
    r"|\b(?:ClaudeCodeSetupPrompt|KiroProjectSetupPrompt|FrameworkUpdatePrompt|PythonProjectSetupPrompt)\b"
)
OLD_TO_NEW_MAP = "docs/README.md"  # names the old layout on purpose: it is the map from old paths to new
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
# Trees installed into a project: a relative link inside them is relative to the PROJECT, not to this repository.
INSTALLED = re.compile(r"^clients/(common|claude|kiro)/(agents|commands|rules|docs|phases|prompts)/")


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout
    return [f for f in out.split("\0") if f]


def live_text_files() -> list[tuple[str, str]]:
    files = []
    for f in tracked():
        if HISTORICAL.match(f) or f == "test/test_layout.py":
            continue
        try:
            files.append((f, (ROOT / f).read_text(encoding="utf-8")))
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    return files


def resolves(token: str) -> bool:
    token = token.rstrip(".:")
    cut = min((token.index(c) for c in "$<{[" if c in token), default=None)
    if cut is not None:  # a placeholder (`<name>.json`, `$a.md`): the directory before it must exist
        return (ROOT / token[:cut]).parent.is_dir()
    if "*" in token:
        return any(ROOT.glob(token))
    return (ROOT / token).exists()


def test_every_framework_path_named_in_a_live_file_exists() -> None:
    missing = []
    for f, text in live_text_files():
        for m in FRAMEWORK_PATH.finditer(text):
            token = m.group(0)
            if token.endswith("-"):  # a path broken across two lines of prose
                continue
            if not resolves(token):
                line = text.count("\n", 0, m.start()) + 1
                missing.append(f"{f}:{line}: {token}")
    assert not missing, "framework paths that do not exist:\n" + "\n".join(missing)


def test_no_live_file_names_the_old_layout() -> None:
    found = []
    for f, text in live_text_files():
        if f == OLD_TO_NEW_MAP:
            continue
        for m in OLD_LAYOUT.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            found.append(f"{f}:{line}: {m.group(0)}")
    assert not found, "old-layout names (see docs/README.md for the new paths):\n" + "\n".join(found)


def test_relative_markdown_links_resolve() -> None:
    broken = []
    for f, text in live_text_files():
        if not f.endswith(".md") or INSTALLED.match(f):
            continue
        for m in MD_LINK.finditer(text):
            target = m.group(1).split("#", 1)[0]
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target):
                continue
            if not (ROOT / f).parent.joinpath(target).exists():
                broken.append(f"{f}: {m.group(1)}")
    assert not broken, "relative links that do not resolve:\n" + "\n".join(broken)


def test_python_lives_only_in_src_test_and_scripts() -> None:
    stray = [f for f in tracked() if f.endswith(".py") and not f.startswith(("src/", "test/", "scripts/"))]
    assert not stray, f"Python outside src/, test/ and scripts/: {stray}"


@pytest.mark.parametrize("path", sorted((ROOT / "clients" / "kiro" / "agents").glob("*.json")), ids=lambda p: p.stem)
def test_a_kiro_agent_is_stored_under_its_install_name(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["name"] == path.stem, "Kiro discovers an agent by file name, which must equal its `name`"
    prompt = data.get("prompt", "")
    if prompt.startswith("file://"):
        assert (path.parent / prompt[len("file://") :]).is_file(), f"{prompt} is installed beside the JSON"


@pytest.mark.parametrize("path", sorted((ROOT / "clients" / "claude" / "agents").glob("*.md")), ids=lambda p: p.stem)
def test_a_claude_agent_is_stored_under_its_name(path: Path) -> None:
    head = path.read_text(encoding="utf-8").split("---", 2)
    assert len(head) == 3 and head[0] == "", f"{path.name}: no YAML front matter"
    names = re.findall(r"^name:\s*(\S+)\s*$", head[1], re.M)
    assert names == [path.stem], f"{path.name}: front-matter name {names} != file name"


def test_the_archive_is_ignored_at_the_root_only() -> None:
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "/archive/" in lines, "archive/ holds local-only material and must stay out of git"
    assert "archive/" not in lines and "archive" not in lines, (
        "an unanchored archive/ also ignores docs/archive/, which memory_compile.py writes and must stay tracked"
    )
    assert not [f for f in tracked() if f.startswith("archive/")]


@pytest.mark.parametrize(
    "probe",
    [
        "docs/reports/new-report.md",
        "docs/design/agents/new-note.md",
        "docs/archive/rule-incidents/x.md",
        "clients/common/docs/x.md",
        "clients/claude/agents/x.md",
        "clients/kiro/agents/x.json",
        "src/hooks/gate_x.py",
        "src/payload/scripts/x.py",
        "templates/docs/x.md",
        "prompts/x.txt",
        "test/test_x.py",
    ],
)
def test_a_new_file_in_a_tracked_directory_is_not_ignored(probe: str) -> None:
    """An unanchored ignore rule (`reports/`, `archive/`) silently swallows new files in a same-named subdirectory."""
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-v", probe], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 1, f"{probe} would be ignored by: {result.stdout.strip()}"
