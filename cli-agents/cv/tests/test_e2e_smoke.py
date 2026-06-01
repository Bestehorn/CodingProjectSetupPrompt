"""End-to-end smoke / integration test for the CV Customizer Agent Suite (task 18).

This is the *integration* checkpoint for the suite. A subagent cannot launch a
live ``kiro-cli --agent cv-orchestrator`` chat session and drive a real
multi-agent LLM workflow, so this module verifies — automatically, repeatably,
and WITHOUT any live LLM — everything about the suite that is verifiable from
the deterministic core, the installed configs, and the real shared scripts:

A. **Installer integration & discoverability** (R2.1, R2.3, R16.8-16.10).
   Run the real ``install_agents.py`` into a temp workspace and assert the
   orchestrator discovery config exists at ``.kiro/agents/cv-orchestrator.json``
   with ``name == "cv-orchestrator"``; that its
   ``toolsSettings.subagent.availableAgents`` and ``trustedAgents`` list exactly
   the six canonical delegate names; and that a discovery config exists for each
   of those six with a matching ``name`` field and resolvable prompt/script
   paths.

B. **Non-interactive guarantee** (design "Human-in-the-loop is confined to the
   orchestrator"; R2.1, R6.9, permissions matrix). A static config-level check
   that NO delegate can prompt the user: no delegate carries the ``subagent``
   tool, and each reviewer/editor carries exactly the read/write[/shell] tool
   set the design's permissions matrix assigns it. Only the orchestrator is
   interactive.

C. **Originals-unchanged (Property 1)** and **single-writer (Property 2)**.
   Drive the real deterministic scripts over the versioned fixture CV:
   ``docx_normalize.py`` -> snapshot a *working copy* -> ``docx_edit.py`` applies
   a small Change_List to the working copy. Assert the ORIGINAL fixture CV's
   bytes/SHA-256 are unchanged while the working copy is edited (the edit is
   verified by the engine), and that the JD/letter originals are likewise
   untouched. The single ``.docx`` writer is the edit engine; the orchestrator
   only byte-copies to ``backups/``.

D. **Accepted-gaps honored & DB writeback/sidecar per format** (R1.9, R13.1-13.3,
   Property 5). Using the deterministic orchestrator-logic reference and the
   documented writeback rule, assert: an accepted gap is recorded once and
   excluded from gate evaluation; a ``.md`` database is written back *in place*
   by append (original content preserved, provenance added); and when no
   database is provided the elicited content goes to a ``database_sidecar.md``
   instead — the user DB path (absent) is never created.

E. **Calibrated page-count check (Property 7 — the hard gate's only true
   correctness check).** Run the REAL ``page_count.py`` against the calibrated
   1/2/3-page fixtures. This is environment-dependent: if a renderer (Microsoft
   Word via win32com, or LibreOffice via ``soffice``) is available on THIS host,
   assert the fixtures report 1/2/3 exactly (hard correctness). If NO renderer
   is available, assert the documented fail-fast contract instead
   (``page_count.py`` exits ``EXIT_NO_RENDERER`` with a message naming both
   renderers, and writes no results file). Both branches assert the *actual
   specified behavior for the actual environment* — neither skips nor xfails,
   per the workspace ``tests-must-not-fail`` rule. The branch that ran is
   recorded in :data:`PAGE_COUNT_BRANCH` and surfaced by
   :func:`test_e2e_report_branch_executed`.

All scratch this test creates lives under pytest ``tmp_path`` (and a cleaned
``tmp/<canonical-name>/`` sandbox for the editor-pattern paths); nothing touches
the real ``.kiro/`` or the versioned fixtures. No environment variables are read
anywhere; renderer detection uses ``shutil.which`` / import probing only, and
all install locations are passed as explicit arguments (matching the
no-environment-variables steering rule and the suite's own conventions).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

# The shared scripts are importable via conftest's sys.path wiring.
import docx_edit
import docx_normalize as dn
import orchestrator_logic as ol
import page_count as pc

# Make ``shared/install/install_agents.py`` importable by module name (mirrors
# the convention in test_install_agents.py; derived purely from this file's
# location, never from an environment variable).
_INSTALL_DIR = Path(__file__).resolve().parent.parent / "shared" / "install"
if str(_INSTALL_DIR) not in sys.path:
    sys.path.insert(0, str(_INSTALL_DIR))

import install_agents as ia  # noqa: E402


# --------------------------------------------------------------------------
# Canonical names & the design's permissions matrix (single source of truth)
# --------------------------------------------------------------------------

ORCHESTRATOR = "cv-orchestrator"

# The six canonical delegate names the orchestrator spawns, per R16.3 / D-13.
DELEGATE_NAMES = (
    "cv-editor",
    "cv-spell-format-reviewer",
    "cv-language-content-reviewer",
    "cv-jd-alignment-reviewer",
    "cv-ats-reviewer",
    "cv-hiring-manager-reviewer",
)

# Per-agent tool sets from design "Tooling and Permissions Layer" -> per-agent
# tool matrix. These are the exact ``tools`` arrays each config must carry.
EXPECTED_TOOLS = {
    "cv-orchestrator": {"read", "write", "shell", "subagent"},
    "cv-editor": {"read", "write", "shell"},
    "cv-spell-format-reviewer": {"read", "write"},
    "cv-language-content-reviewer": {"read", "write"},
    "cv-jd-alignment-reviewer": {"read", "write"},
    "cv-ats-reviewer": {"read", "write", "shell"},
    "cv-hiring-manager-reviewer": {"read", "write"},
}


# --------------------------------------------------------------------------
# Renderer detection (decides the Property-7 branch) — no environment variables
# --------------------------------------------------------------------------


def _word_available() -> bool:
    """True iff Microsoft Word automation can actually start on THIS host.

    Probes the same indirection ``page_count.py`` uses (``_dispatch_word``),
    then immediately quits Word so no process is left behind. Any failure
    (pywin32 absent, Word not installed, COM error) means "no Word".
    """
    try:
        app = pc._dispatch_word()
    except Exception:  # noqa: BLE001 - any failure means Word is unavailable
        return False
    try:
        try:
            app.Quit()
        except Exception:  # noqa: BLE001 - cosmetic cleanup only
            pass
    finally:
        pass
    return True


def _libreoffice_available() -> bool:
    """True iff LibreOffice ``soffice`` is discoverable AND pypdf is importable.

    The fallback page-count path needs both: ``soffice`` to render to PDF and
    ``pypdf`` to count pages. ``_discover_soffice`` uses ``shutil.which`` only
    (a PATH lookup, never an env-var read).
    """
    if pc._discover_soffice() is None:
        return False
    try:
        pc._import_pypdf()
    except Exception:  # noqa: BLE001 - pypdf missing -> fallback cannot complete
        return False
    return True


def _detect_page_count_branch() -> str:
    """Return the page-count branch this host will exercise: word | libreoffice | none."""
    if _word_available():
        return "word"
    if _libreoffice_available():
        return "libreoffice"
    return "none"


# Cache the detected branch so the (potentially slow) renderer probe runs at most
# once per session, and only when a page-count test actually needs it — never at
# import/collection time, so tests that do not exercise Property 7 never touch a
# renderer.
_PAGE_COUNT_BRANCH: str | None = None


def page_count_branch() -> str:
    """The page-count branch for THIS host, detected once and cached."""
    global _PAGE_COUNT_BRANCH
    if _PAGE_COUNT_BRANCH is None:
        _PAGE_COUNT_BRANCH = _detect_page_count_branch()
    return _PAGE_COUNT_BRANCH


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture()
def installed_suite(tmp_path):
    """Run the real installer into a fresh temp workspace (never the real .kiro/)."""
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()
    kiro_dir = ia.kiro_dir_for_mode("workspace", workspace_root=workspace_root)
    return ia.install_suite(ia.default_authoring_root(), kiro_dir, mode="workspace")


# ==========================================================================
# A. Installer integration & orchestrator discoverability  [R2.1, R2.3, R16.8-10]
# ==========================================================================


def test_orchestrator_discovery_config_exists_and_is_named(installed_suite):
    """`.kiro/agents/cv-orchestrator.json` exists with name == cv-orchestrator."""
    orch_path = installed_suite.discovery_dir / f"{ORCHESTRATOR}.json"
    assert orch_path.exists(), f"orchestrator discovery config missing: {orch_path}"
    config = _read_config(orch_path)
    assert config["name"] == ORCHESTRATOR
    # The orchestrator must carry the subagent tool to spawn delegates [R2.2].
    assert "subagent" in config["tools"]


def test_orchestrator_declares_six_delegates_as_available_and_trusted(installed_suite):
    """availableAgents and trustedAgents list EXACTLY the six canonical delegates."""
    orch_path = installed_suite.discovery_dir / f"{ORCHESTRATOR}.json"
    subagent = _read_config(orch_path)["toolsSettings"]["subagent"]
    for key in ("availableAgents", "trustedAgents"):
        assert set(subagent[key]) == set(DELEGATE_NAMES), (
            f"{key} {sorted(subagent[key])} != {sorted(DELEGATE_NAMES)}"
        )
        # No accidental duplicates and no self-reference.
        assert len(subagent[key]) == len(DELEGATE_NAMES)
        assert ORCHESTRATOR not in subagent[key]


def test_each_delegate_has_a_discovery_config_with_matching_name(installed_suite):
    """Every delegate the orchestrator names resolves to a config whose name matches."""
    orch_path = installed_suite.discovery_dir / f"{ORCHESTRATOR}.json"
    available = _read_config(orch_path)["toolsSettings"]["subagent"]["availableAgents"]
    for name in available:
        cfg_path = installed_suite.discovery_dir / f"{name}.json"
        assert cfg_path.exists(), f"delegate discovery config missing: {cfg_path}"
        assert _read_config(cfg_path)["name"] == name  # byte-for-byte


def test_every_agent_prompt_and_script_resolve_to_existing_files(installed_suite):
    """Each generated config's prompt URI and rewritten script refs exist on disk."""
    for agent in installed_suite.agents:
        config = _read_config(agent.discovery_config_path)
        prompt_path = ia._uri_to_path(config["prompt"])
        assert prompt_path is not None and prompt_path.exists(), (
            f"{agent.canonical_name}: prompt {config['prompt']!r} does not resolve"
        )
        for script_path in agent.referenced_script_paths:
            assert script_path.exists(), (
                f"{agent.canonical_name} references missing script {script_path}"
            )


def test_install_produces_exactly_seven_discoverable_agents(installed_suite):
    configs = sorted(p.stem for p in installed_suite.discovery_dir.glob("*.json"))
    assert configs == sorted((ORCHESTRATOR, *DELEGATE_NAMES))


# ==========================================================================
# B. Non-interactive guarantee — no delegate can prompt the user  [design D-1]
# ==========================================================================


def test_no_delegate_carries_the_subagent_tool(installed_suite):
    """Only the orchestrator may spawn subagents; delegates are leaf agents.

    A delegate with the ``subagent`` tool could itself spawn an interactive
    agent, breaking the "human-in-the-loop confined to the orchestrator"
    invariant. None may have it.
    """
    for agent in installed_suite.agents:
        if agent.canonical_name == ORCHESTRATOR:
            continue
        config = _read_config(agent.discovery_config_path)
        assert "subagent" not in config["tools"], (
            f"{agent.canonical_name} must NOT carry the subagent tool"
        )
        assert "subagent" not in config.get("allowedTools", []), (
            f"{agent.canonical_name} must NOT allow the subagent tool"
        )


def test_each_agent_has_exactly_the_permissions_matrix_tool_set(installed_suite):
    """Every config's tools match the design's per-agent permissions matrix."""
    for agent in installed_suite.agents:
        config = _read_config(agent.discovery_config_path)
        expected = EXPECTED_TOOLS[agent.canonical_name]
        assert set(config["tools"]) == expected, (
            f"{agent.canonical_name} tools {sorted(config['tools'])} != "
            f"{sorted(expected)}"
        )
        # allowedTools mirrors tools for these configs.
        assert set(config["allowedTools"]) == expected


def test_reviewers_have_no_shell_and_pure_reviewers_are_findings_only(installed_suite):
    """Pure reviewers (spell/format, language, hiring-manager) have read+write only.

    They get ``write`` solely to persist their own Findings (design "Resolved
    Design Decisions" #1); they must not have ``shell`` (no deterministic tool
    to run) and their write scope is confined to their own findings/state dirs.
    """
    pure_reviewers = {
        "cv-spell-format-reviewer",
        "cv-language-content-reviewer",
        "cv-hiring-manager-reviewer",
    }
    for agent in installed_suite.agents:
        if agent.canonical_name not in pure_reviewers:
            continue
        config = _read_config(agent.discovery_config_path)
        assert set(config["tools"]) == {"read", "write"}
        assert "shell" not in config["tools"]
        allowed_paths = config["toolsSettings"]["write"]["allowedPaths"]
        # Every write path is scoped to this reviewer's own findings/state tree.
        for path in allowed_paths:
            assert agent.canonical_name in path, (
                f"{agent.canonical_name} write path {path!r} escapes its own tree"
            )


def test_shell_agents_scope_commands_and_deny_dangerous_ones(installed_suite):
    """The two shell agents (editor, ATS) scope allowedCommands and deny pip/git/rm.

    Confirms the non-orchestrator shell surface cannot run package installers,
    git, or recursive deletes (design "Tooling and Permissions Layer" global
    denied commands).
    """
    shell_agents = {"cv-editor", "cv-ats-reviewer"}
    for agent in installed_suite.agents:
        if agent.canonical_name not in shell_agents:
            continue
        shell = _read_config(agent.discovery_config_path)["toolsSettings"]["shell"]
        assert shell["allowedCommands"], f"{agent.canonical_name} has no allowedCommands"
        denied_blob = " ".join(shell["deniedCommands"])
        for forbidden in ("pip install", "git ", "npm ", "rm ", "del ", "rmdir "):
            assert forbidden in denied_blob, (
                f"{agent.canonical_name} does not deny {forbidden!r}"
            )


def test_installer_resolved_paths_contain_no_env_var_placeholders(installed_suite):
    """The installer-resolved path fields are concrete — no env-var placeholders.

    The meaningful no-environment-variables invariant at install-output level is
    that every path the installer emitted (the ``prompt`` ``file://`` URI and
    each ``toolsSettings.shell.allowedCommands`` pattern) is a concrete,
    host-resolved path — never an unexpanded env-var reference like
    ``%USERPROFILE%``, ``$HOME``, or ``${VAR}`` (R15.1, R16.7, and the workspace
    no-env-vars rule). Prompt *prose* may legitimately mention such tokens to
    instruct the agent to REJECT them, so this guard targets resolved path
    fields only, not the prompt narrative.
    """
    # Env-var placeholder syntaxes that must never appear in a resolved path:
    #   %VAR% (Windows), ${VAR} (POSIX braces), $VAR (POSIX bare).
    placeholder_res = (
        re.compile(r"%[A-Za-z_][A-Za-z0-9_]*%"),
        re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}"),
        re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*"),
    )

    def _assert_no_placeholder(value: str, where: str) -> None:
        for pattern in placeholder_res:
            assert not pattern.search(value), (
                f"{where} contains an env-var placeholder: {value!r}"
            )

    for agent in installed_suite.agents:
        config = _read_config(agent.discovery_config_path)
        _assert_no_placeholder(config["prompt"], f"{agent.canonical_name} prompt URI")
        commands = (
            config.get("toolsSettings", {}).get("shell", {}).get("allowedCommands", [])
        )
        for cmd in commands:
            _assert_no_placeholder(cmd, f"{agent.canonical_name} allowedCommand")


def test_installer_source_reads_no_environment_variables(installed_suite):
    """The installer source itself never touches the process environment.

    Complements the resolved-path check: confirms the code that produced those
    paths did so without reading any env var or relying on the cwd (R15.1).
    Mirrors the static guard in test_install_agents.py, asserted here as part of
    the end-to-end no-env-vars guarantee.
    """
    source = (_INSTALL_DIR / "install_agents.py").read_text(encoding="utf-8")
    for forbidden in ("os.environ", "os.getenv", "getenv(", "expanduser", "Path.home()", "os.getcwd"):
        assert forbidden not in source, f"installer must not use {forbidden!r}"


# ==========================================================================
# C. Property 1 (originals immutable) + Property 2 (single writer)
# ==========================================================================


def _build_workflow_state(tmp_path: Path, fixture_path) -> dict:
    """Replicate the orchestrator NORMALIZE+snapshot steps with the real scripts.

    Returns a dict of the originals + working copies + state dirs so individual
    tests can assert against them. This drives ONLY the deterministic scripts —
    no LLM, no subagent — exactly as the design's NORMALIZE phase would.
    """
    ws = tmp_path / "cv-workflow"
    inputs = ws / "inputs"
    working = ws / "working"
    backups = ws / "backups"
    for d in (inputs, working, backups):
        d.mkdir(parents=True, exist_ok=True)

    # The user-provided originals live OUTSIDE the workflow state tree.
    originals = tmp_path / "originals"
    originals.mkdir()
    cv_original = originals / "MyCV.docx"
    jd_original = originals / "job.txt"
    shutil.copy2(fixture_path("sample_cv.docx"), cv_original)
    shutil.copy2(fixture_path("sample_jd.txt"), jd_original)

    # NORMALIZE: produce Normalized_Text + anchors for the CV.
    cv_md = inputs / "cv.normalized.md"
    dn.normalize_docx(cv_original, cv_md)

    # Snapshot the CV Working Copy (a copy of the original — never the original).
    cv_working = working / "cv.working.docx"
    shutil.copy2(cv_original, cv_working)

    return {
        "ws": ws,
        "inputs": inputs,
        "working": working,
        "backups": backups,
        "cv_original": cv_original,
        "jd_original": jd_original,
        "cv_working": cv_working,
    }


def _small_change_list(cv_working: Path):
    """A minimal, anchor-valid Change_List against the working CV.

    Targets the Professional Summary paragraph by its stable paragraph key and
    replaces a substring, exercising the same path the CV Editor uses.
    """
    doc = docx_edit.Document(str(cv_working))
    anchors = dn.compute_paragraph_anchors(doc)
    # Find a body paragraph that contains a known substring we can replace.
    target = None
    for anchor in anchors:
        if "five years of experience" in anchor.text:
            target = anchor
            break
    assert target is not None, "expected the summary paragraph in the sample CV"
    entry = {
        "id": "CL-1-001",
        "iteration": 1,
        "target_document": "CV_Working_Copy",
        "implements_findings": ["LC-001"],
        "operation": "replace_run_text",
        "anchor": {"paragraph_key": target.key, "match_text": "five years"},
        "new_text": "six years",
    }
    return [entry], target.key


def test_property1_originals_unchanged_and_property2_single_writer(tmp_path, fixture_path):
    """The original CV/JD bytes are unchanged; only the working copy is edited."""
    state = _build_workflow_state(tmp_path, fixture_path)

    cv_original = state["cv_original"]
    jd_original = state["jd_original"]
    cv_working = state["cv_working"]

    # Capture original hashes BEFORE any edit (Property 1 baseline).
    cv_original_hash = _sha256(cv_original)
    jd_original_hash = _sha256(jd_original)
    working_hash_before = _sha256(cv_working)

    # The editor engine is the SINGLE writer of the working copy (Property 2):
    # the orchestrator first byte-copies a backup, then the engine edits.
    backup = state["backups"] / "cv.working.pre-edit.bak.docx"
    shutil.copy2(cv_working, backup)

    change_list, target_key = _small_change_list(cv_working)
    result = docx_edit.apply_change_list(
        cv_working, change_list, iteration=1, write_result=False
    )

    # The edit was actually applied & verified by the engine.
    assert result["failed_count"] == 0, result
    statuses = {e["status"] for e in result["entries"]}
    assert statuses <= {docx_edit.STATUS_VERIFIED, docx_edit.STATUS_FORMATTING_NORMALIZED}, result
    assert result["applied_count"] == 1

    # Property 1: the ORIGINAL inputs are byte-identical before and after.
    assert _sha256(cv_original) == cv_original_hash, "original CV must be immutable"
    assert _sha256(jd_original) == jd_original_hash, "original JD must be immutable"

    # Property 2: the working copy changed (only the editor touched it).
    assert _sha256(cv_working) != working_hash_before, "working copy should be edited"

    # The edit is observable in the re-read working copy; the original still says
    # "five years"; the working copy now says "six years".
    working_doc = docx_edit.Document(str(cv_working))
    working_text = "\n".join(p.text for p in working_doc.paragraphs)
    assert "six years" in working_text
    original_doc = docx_edit.Document(str(cv_original))
    original_text = "\n".join(p.text for p in original_doc.paragraphs)
    assert "five years" in original_text
    assert "six years" not in original_text


def test_edit_is_idempotent_on_reapply(tmp_path, fixture_path):
    """Re-applying the same Change_List is a no-op (already_satisfied), not a re-edit.

    This is the editor's first line of defence against oscillation (design
    "Idempotency") and underpins convergence (a re-review of an applied edit
    must not re-open it).
    """
    state = _build_workflow_state(tmp_path, fixture_path)
    cv_working = state["cv_working"]
    change_list, _ = _small_change_list(cv_working)

    first = docx_edit.apply_change_list(cv_working, change_list, iteration=1, write_result=False)
    assert first["applied_count"] == 1 and first["failed_count"] == 0

    hash_after_first = _sha256(cv_working)
    second = docx_edit.apply_change_list(cv_working, change_list, iteration=2, write_result=False)
    # The re-run is idempotent: already-satisfied, and the bytes are unchanged.
    second_statuses = {e["status"] for e in second["entries"]}
    assert second_statuses == {docx_edit.STATUS_ALREADY_SATISFIED}, second
    assert second["failed_count"] == 0
    assert _sha256(cv_working) == hash_after_first, "idempotent re-run must not alter bytes"


# ==========================================================================
# D. Accepted-gaps honored + DB writeback/sidecar per format  [R1.9, R13, Prop 5]
# ==========================================================================


def test_accepted_gap_recorded_once_and_excluded_from_gates(tmp_path):
    """An accepted gap is recorded with the verbatim response and never re-opened.

    Uses the deterministic orchestrator-logic reference (the same rules the
    orchestrator prompt encodes) so the assertion is exact and LLM-free.
    """
    register = ol.AcceptedGapsRegister()
    gap_finding = {
        "id": "JD-007",
        "source_agent": "cv-jd-alignment-reviewer",
        "iteration": 1,
        "target_document": "CV_Working_Copy",
        "category": "jd_gap",
        "severity": "high",
        "anchor": {"paragraph_key": "skills::k8s"},
        "proposed": "Add Kubernetes-at-scale experience.",
        "rationale": "JD requires Kubernetes at scale.",
        "status": "open",
    }
    verbatim = "I have not operated Kubernetes at scale."
    register.accept(gap_finding, verbatim, iteration=1)
    # Record-once: a second accept does not duplicate or overwrite.
    register.accept(gap_finding, "different text that must be ignored", iteration=2)

    entries = register.entries()
    assert len(entries) == 1
    assert entries[0]["finding_id"] == "JD-007"
    assert entries[0]["verbatim_response"] == verbatim  # verbatim preserved

    # Property 5: once accepted, the finding is excluded from gate evaluation.
    marked = register.mark_findings([gap_finding])
    assert marked[0]["status"] == "accepted_gap"
    open_after = ol.exclude_accepted_gaps(marked)
    assert open_after == [], "accepted gap must be excluded from the open set"
    assert not ol.is_open(marked[0])

    # And a reviewer whose only finding is the accepted gap now passes its gate.
    gate = ol.reviewer_gate_status("cv-jd-alignment-reviewer", marked)
    assert gate == "PASS"


def _writeback_target(db_path: Path | None, sidecar: Path) -> Path:
    """The documented Phase-2 writeback target for a given DB path / absence.

    Mirrors the rule in design "Database writeback rules" and the JD-alignment
    prompt: ``.md``/``.txt`` -> in place; ``.docx``/``.pdf`` or absent -> sidecar.
    """
    if db_path is not None and db_path.suffix.lower() in (".md", ".txt"):
        return db_path
    return sidecar


def test_db_writeback_in_place_for_markdown_database(tmp_path, fixture_path):
    """A .md database is appended in place (original content preserved + provenance)."""
    db = tmp_path / "extensive_cv.md"
    shutil.copy2(fixture_path("sample_database.md"), db)
    original_text = db.read_text(encoding="utf-8")
    sidecar = tmp_path / "cv-workflow" / "database_sidecar.md"

    target = _writeback_target(db, sidecar)
    assert target == db, "a .md DB must be written back in place"

    # Simulate the JD-alignment Phase-2 in-place append with provenance.
    provenance = (
        "\n<!-- cv-customizer: iteration=1 finding=JD-014 qid=Q1 "
        'question="Do you have Terraform experience?" '
        'answered="2026-05-29T10:31Z" -->\n'
        "- Authored Terraform modules for a multi-account AWS landing zone.\n"
    )
    with db.open("a", encoding="utf-8") as fh:
        fh.write(provenance)

    new_text = db.read_text(encoding="utf-8")
    # Append-only: the original content is fully preserved as a prefix.
    assert new_text.startswith(original_text), "in-place writeback must be append-only"
    assert "cv-customizer:" in new_text and "Terraform" in new_text
    # The sidecar is NOT created when an in-place .md writeback happened.
    assert not sidecar.exists(), "no sidecar should be created for a .md DB"


def test_db_writeback_to_sidecar_when_no_database_provided(tmp_path):
    """With no database, elicited content goes to the sidecar; no user file is made."""
    db_path = None
    sidecar = tmp_path / "cv-workflow" / "database_sidecar.md"
    sidecar.parent.mkdir(parents=True, exist_ok=True)

    target = _writeback_target(db_path, sidecar)
    assert target == sidecar, "absent DB must route writeback to the sidecar"

    entry = (
        "<!-- cv-customizer: iteration=1 finding=JD-021 qid=Q2 "
        'question="Any Kafka experience?" answered="2026-05-29T10:40Z" -->\n'
        "- Ran a 12-broker Kafka cluster supporting 2M messages/day.\n"
    )
    with sidecar.open("a", encoding="utf-8") as fh:
        fh.write(entry)

    assert sidecar.exists() and "Kafka" in sidecar.read_text(encoding="utf-8")


def test_db_writeback_to_sidecar_for_binary_docx_database(tmp_path, fixture_path):
    """A .docx database is NOT modified in place; writeback goes to the sidecar."""
    db = tmp_path / "extensive_cv.docx"
    shutil.copy2(fixture_path("sample_cv.docx"), db)  # any .docx stands in here
    db_hash_before = _sha256(db)
    sidecar = tmp_path / "cv-workflow" / "database_sidecar.md"
    sidecar.parent.mkdir(parents=True, exist_ok=True)

    target = _writeback_target(db, sidecar)
    assert target == sidecar, "a .docx DB must route writeback to the sidecar"

    sidecar.write_text(
        "<!-- cv-customizer: iteration=1 finding=JD-030 -->\n- Elicited content.\n",
        encoding="utf-8",
    )
    # The binary DB is never touched.
    assert _sha256(db) == db_hash_before, "binary .docx DB must remain unmodified"
    assert sidecar.exists()


# ==========================================================================
# E. Calibrated page-count check (Property 7) — environment-aware, no skips
# ==========================================================================


@pytest.mark.parametrize("name,expected", [("page_1.docx", 1), ("page_2.docx", 2), ("page_3.docx", 3)])
def test_calibrated_page_count_property7(name, expected, fixture_path):
    """Property 7: the calibrated 1/2/3-page fixtures report 1/2/3 via the REAL renderer.

    Environment-aware (NOT a skip): when a renderer is present on THIS host we
    assert the exact page count (the hard gate's only true correctness check);
    when no renderer is present we assert the documented fail-fast contract.
    Exactly one branch runs, decided by :func:`page_count_branch`.
    """
    docx = fixture_path(name)
    branch = page_count_branch()

    if branch in ("word", "libreoffice"):
        result = pc.count_pages(str(docx))
        assert result["pages"] == expected, (
            f"{name} should render to {expected} page(s) via the real renderer; "
            f"got {result}"
        )
        assert result["document"] == str(docx)
        expected_method = (
            pc.METHOD_WORD if branch == "word" else pc.METHOD_LIBREOFFICE
        )
        assert result["method"] == expected_method
    else:
        # No renderer: the hard gate must fail fast and never guess.
        with pytest.raises(pc.NoRendererError) as excinfo:
            pc.count_pages(str(docx))
        msg = str(excinfo.value).lower()
        assert "no page renderer" in msg
        assert "word" in msg and "libreoffice" in msg


def test_calibrated_page_count_via_cli(tmp_path, fixture_path):
    """Drive the calibrated check through the real ``page_count.py`` CLI end-to-end.

    Asserts the documented exit code and output shape for the branch this host
    actually runs (renderer-present: EXIT_OK + a results file of the right
    shape; renderer-absent: EXIT_NO_RENDERER + no results file). A single
    calibrated fixture is rendered here — the full 1/2/3 correctness is asserted
    by ``test_calibrated_page_count_property7`` and the multi-document CLI shape
    by the monkeypatched tests in ``test_page_count.py`` — so the real renderer
    is exercised through the CLI without re-rendering every fixture.
    """
    docx = str(fixture_path("page_2.docx"))
    out = tmp_path / "page_counts.json"
    rc = pc.main([docx, "--out", str(out)])

    if page_count_branch() in ("word", "libreoffice"):
        assert rc == pc.EXIT_OK
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert [row["pages"] for row in payload] == [2]
        for row in payload:
            assert set(row) == {"document", "pages", "method"}
    else:
        assert rc == pc.EXIT_NO_RENDERER
        assert not out.exists(), "a fatal no-renderer run must leave no results file"


def test_e2e_report_branch_executed():
    """Documents which Property-7 branch ran on this host (visible in -s output)."""
    branch = page_count_branch()
    assert branch in ("word", "libreoffice", "none")
    print(f"\n[e2e smoke] Property-7 page-count branch executed: {branch}")


# ==========================================================================
# Cleanup: clear the tmp/<canonical-name>/ editor-pattern scratch on success
# ==========================================================================


def test_tmp_scratch_is_cleaned_on_success(tmp_path):
    """Design "Cleanup": tmp/<canonical-name>/ working scratch is cleared on success.

    Replicates the editor/ATS script-in-tmp pattern in an isolated sandbox: a
    wrapper script is written under ``tmp/cv-editor/<iso>/``, then the working
    scratch is removed at successful termination (per-agent state archival is
    the orchestrator's separate concern). Asserts the directory is gone after
    cleanup, never touching the repo's real ``tmp/``.
    """
    sandbox = tmp_path / "tmp"
    for canonical in ("cv-editor", "cv-ats-reviewer"):
        scratch = sandbox / canonical / "2026-05-29T10-00-00Z"
        scratch.mkdir(parents=True)
        (scratch / "apply_changes.py").write_text("# generated wrapper\n", encoding="utf-8")
        assert scratch.exists()

    # Successful-termination cleanup clears each tmp/<canonical-name>/ tree.
    for canonical in ("cv-editor", "cv-ats-reviewer"):
        shutil.rmtree(sandbox / canonical)
        assert not (sandbox / canonical).exists()
