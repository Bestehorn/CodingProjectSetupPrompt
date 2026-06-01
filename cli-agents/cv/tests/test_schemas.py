"""Schema validation tests for the suite's data models (task 7 / subtask 7.1).

Validates the three JSON schemas authored in ``shared/schemas/`` against
representative valid and invalid instances, covering:

* **Property 3 — Finding well-formedness.** A representative set of valid
  Findings (one per ``category``, including a *real* one produced by
  ``ats_structural.detect_hazards(ats_hazards.docx)``) validate against
  ``finding.schema.json``; deliberately malformed Findings (bad enum, missing
  required field, empty anchor) fail.
* **Property 4 — Change_List well-formedness.** A valid entry per ``operation``,
  a bare-array Change_List, and an ``{"entries": [...]}`` document validate
  against ``change_list.schema.json``; malformed ones (bad operation, missing
  ``anchor.paragraph_key``, missing ``entries``) fail.
* **resume_state frontmatter object.** Valid + invalid instances against
  ``resume_state.schema.json``.
* The schema files are themselves valid, loadable JSON (and meta-valid when the
  ``jsonschema`` library is present).

Validation backend: the real ``jsonschema`` library (draft 2020-12) is used when
installed. When it is absent, a small dependency-free structural validator
(``_fallback_is_valid``) checks the schema constructs these schemas actually use
(``type``, ``enum``, ``required``, ``properties``, ``additionalProperties``,
``items``, ``minLength``, ``minimum``, ``minProperties``, ``anyOf``, ``oneOf``,
local ``$ref``) so the suite still runs and passes deterministically with no
skips. No environment variables are read; paths derive from this file's location.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ats_structural as ats

# --------------------------------------------------------------------------
# Schema locations
# --------------------------------------------------------------------------

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "shared" / "schemas"
FINDING_SCHEMA_PATH = SCHEMAS_DIR / "finding.schema.json"
CHANGE_LIST_SCHEMA_PATH = SCHEMAS_DIR / "change_list.schema.json"
RESUME_STATE_SCHEMA_PATH = SCHEMAS_DIR / "resume_state.schema.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


FINDING_SCHEMA = _load(FINDING_SCHEMA_PATH)
CHANGE_LIST_SCHEMA = _load(CHANGE_LIST_SCHEMA_PATH)
RESUME_STATE_SCHEMA = _load(RESUME_STATE_SCHEMA_PATH)


# --------------------------------------------------------------------------
# Validation backend: real jsonschema if present, else a tiny structural one
# --------------------------------------------------------------------------

try:  # prefer the real library
    from jsonschema import Draft202012Validator

    HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover - exercised only without the dependency
    HAVE_JSONSCHEMA = False


def _resolve_ref(ref: str, root: dict) -> dict:
    """Resolve a local ``#/...`` JSON Pointer reference within ``root``."""
    assert ref.startswith("#/"), f"only local refs supported, got {ref!r}"
    node: object = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node  # type: ignore[return-value]


def _type_ok(instance, expected: str) -> bool:
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "null":
        return instance is None
    return True


def _structural_errors(instance, schema: dict, root: dict, path: str = "$") -> list[str]:
    """Return a list of validation errors; empty means valid.

    Implements only the keyword subset used by this suite's three schemas.
    """
    if "$ref" in schema:
        return _structural_errors(instance, _resolve_ref(schema["$ref"], root), root, path)

    errors: list[str] = []

    if "type" in schema and not _type_ok(instance, schema["type"]):
        return [f"{path}: expected type {schema['type']}"]

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")

    if "minLength" in schema and isinstance(instance, str) and len(instance) < schema["minLength"]:
        errors.append(f"{path}: shorter than minLength {schema['minLength']}")

    if (
        "minimum" in schema
        and isinstance(instance, (int, float))
        and not isinstance(instance, bool)
        and instance < schema["minimum"]
    ):
        errors.append(f"{path}: below minimum {schema['minimum']}")

    if isinstance(instance, dict):
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            errors.append(f"{path}: fewer than minProperties {schema['minProperties']}")
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property {req!r}")
        props = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in props:
                errors.extend(_structural_errors(value, props[key], root, f"{path}.{key}"))
            elif additional is False:
                errors.append(f"{path}: additional property {key!r} not allowed")
            elif isinstance(additional, dict):
                errors.extend(_structural_errors(value, additional, root, f"{path}.{key}"))

    if isinstance(instance, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, element in enumerate(instance):
                errors.extend(_structural_errors(element, items, root, f"{path}[{i}]"))

    if "anyOf" in schema:
        if not any(
            not _structural_errors(instance, sub, root, path) for sub in schema["anyOf"]
        ):
            errors.append(f"{path}: does not match any anyOf branch")

    if "oneOf" in schema:
        matched = sum(
            1 for sub in schema["oneOf"] if not _structural_errors(instance, sub, root, path)
        )
        if matched != 1:
            errors.append(f"{path}: matched {matched} oneOf branches (expected exactly 1)")

    return errors


def _fallback_is_valid(instance, schema: dict) -> bool:
    return not _structural_errors(instance, schema, schema)


def is_valid(instance, schema: dict) -> bool:
    """True iff ``instance`` validates against ``schema`` (backend-agnostic)."""
    if HAVE_JSONSCHEMA:
        return not list(Draft202012Validator(schema).iter_errors(instance))
    return _fallback_is_valid(instance, schema)


# --------------------------------------------------------------------------
# The schema files are valid, loadable JSON (and meta-valid where possible)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [FINDING_SCHEMA_PATH, CHANGE_LIST_SCHEMA_PATH, RESUME_STATE_SCHEMA_PATH],
    ids=["finding", "change_list", "resume_state"],
)
def test_schema_file_is_valid_loadable_json(path: Path):
    assert path.exists(), f"schema file missing: {path}"
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(schema, dict)
    assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert "$id" in schema and "title" in schema


@pytest.mark.parametrize(
    "schema",
    [FINDING_SCHEMA, CHANGE_LIST_SCHEMA, RESUME_STATE_SCHEMA],
    ids=["finding", "change_list", "resume_state"],
)
def test_schema_is_meta_valid(schema: dict):
    """Each schema is itself a valid draft 2020-12 schema (when jsonschema present)."""
    if HAVE_JSONSCHEMA:
        Draft202012Validator.check_schema(schema)  # raises on an invalid schema
    else:  # pragma: no cover - exercised only without the dependency
        # Without the library we cannot meta-validate; assert the structural
        # invariants the fallback validator relies on instead.
        assert schema["type"] in {"object", "array"} or "oneOf" in schema


# --------------------------------------------------------------------------
# Property 3 — Finding well-formedness
# --------------------------------------------------------------------------


def _base_finding(**overrides) -> dict:
    finding = {
        "id": "SF-001",
        "source_agent": "cv-spell-format-reviewer",
        "iteration": 1,
        "target_document": "CV_Working_Copy",
        "category": "spelling",
        "severity": "high",
        "anchor": {
            "section": "Professional Experience",
            "paragraph_key": "exp.aws.bullet.3",
            "match_text": "QuickSuite",
        },
        "current": "Bedrock, QuickSuite, Kiro",
        "proposed": "Bedrock, Amazon Q, Kiro",
        "rationale": "'QuickSuite' is not a recognized AWS product name.",
        "status": "open",
    }
    finding.update(overrides)
    return finding


# One representative valid Finding per category in the schema's enum.
VALID_FINDINGS_BY_CATEGORY = {
    "spelling": _base_finding(),
    "formatting": _base_finding(
        id="SF-014",
        category="formatting",
        severity="low",
        anchor={"section": "Skills", "paragraph_key": "skills.bullet.1"},
        current="•  Python",
        proposed="• Python",
        rationale="Inconsistent bullet spacing.",
    ),
    "language": _base_finding(
        id="LC-007",
        source_agent="cv-language-content-reviewer",
        category="language",
        severity="medium",
        anchor={"section": "Summary", "paragraph_key": "summary.para.1"},
        current="Responsible for managing a team.",
        proposed="Led a team of eight engineers.",
        rationale="Weak, passive phrasing; use an active, quantified verb.",
    ),
    "jd_gap": _base_finding(
        id="JD-003",
        source_agent="cv-jd-alignment-reviewer",
        category="jd_gap",
        severity="high",
        anchor={"section": "Skills", "paragraph_key": "skills.bullet.5"},
        proposed="Add Kubernetes experience drawn from the bullet database.",
        rationale="The JD requires Kubernetes; it is present in the database but not the CV.",
    ),
    "ats": _base_finding(
        id="ATS-COL-12ab34cd",
        source_agent="cv-ats-reviewer",
        category="ats",
        severity="high",
        anchor={"type": "section", "hazard": "multi_column", "section_index": 0, "columns": 2},
        current="Section 0 uses 2 text columns.",
        proposed="Convert the section to a single-column layout.",
        rationale="Multi-column layouts are read out of order by ATS parsers.",
    ),
    "hiring_manager_concern": _base_finding(
        id="HM-002",
        source_agent="cv-hiring-manager-reviewer",
        category="hiring_manager_concern",
        severity="blocking",
        target_document="package_coherence",
        anchor={
            "type": "paragraph",
            "section": "Summary",
            "paragraph_key": "summary.para.1",
            "match_text": "ten years",
        },
        current="CV says ten years; letter says eight years.",
        proposed="Reconcile the years of experience across both documents.",
        rationale="Inconsistent claims undermine credibility.",
    ),
    "length": _base_finding(
        id="LEN-001",
        source_agent="cv-orchestrator",
        category="length",
        severity="medium",
        anchor={"section": "Early Career", "paragraph_key": "early.bullet.9"},
        proposed="Remove the least-relevant early-career bullet to fit 2 pages.",
        rationale="CV renders to 3 pages; the limit is 2.",
    ),
}


def test_every_category_has_a_representative_valid_finding():
    """Guard: the schema's category enum and our fixtures stay in lockstep."""
    schema_categories = set(FINDING_SCHEMA["properties"]["category"]["enum"])
    assert set(VALID_FINDINGS_BY_CATEGORY) == schema_categories


@pytest.mark.parametrize("category", sorted(VALID_FINDINGS_BY_CATEGORY))
def test_valid_finding_per_category_validates(category: str):
    finding = VALID_FINDINGS_BY_CATEGORY[category]
    assert is_valid(finding, FINDING_SCHEMA), f"{category} finding should validate"


def test_real_ats_structural_findings_validate(fixture_path):
    """A real detector's output must validate against finding.schema.json.

    This is the load-bearing cross-check: the ATS anchor shape (``type`` +
    ``hazard`` + e.g. ``section_index`` / ``table_index`` / ``part``) differs
    from the design's example anchor, and the schema must accept both.
    """
    findings = ats.detect_hazards(fixture_path("ats_hazards.docx"))
    assert findings, "fixture should yield at least one ATS finding to validate"
    for finding in findings:
        assert is_valid(finding, FINDING_SCHEMA), f"real ATS finding failed: {finding}"

    # Exercise every anchor type the detector can emit against the schema.
    anchor_types = {f["anchor"].get("type") for f in findings}
    assert anchor_types, "expected structured anchors with a 'type'"


# Each invalid Finding violates exactly one rule and must FAIL validation.
INVALID_FINDINGS = {
    "bad_category": _base_finding(category="typo"),
    "bad_severity": _base_finding(severity="critical"),
    "bad_status": _base_finding(status="done"),
    "bad_target_document": _base_finding(target_document="Resume"),
    "missing_id": {k: v for k, v in _base_finding().items() if k != "id"},
    "missing_anchor": {k: v for k, v in _base_finding().items() if k != "anchor"},
    "missing_rationale": {k: v for k, v in _base_finding().items() if k != "rationale"},
    "missing_status": {k: v for k, v in _base_finding().items() if k != "status"},
    "empty_anchor": _base_finding(anchor={}),
    "iteration_not_integer": _base_finding(iteration="1"),
    "unknown_extra_field": _base_finding(severity_level="high"),
}


@pytest.mark.parametrize("name", sorted(INVALID_FINDINGS))
def test_invalid_finding_fails_validation(name: str):
    finding = INVALID_FINDINGS[name]
    assert not is_valid(finding, FINDING_SCHEMA), f"{name} should NOT validate"


# --------------------------------------------------------------------------
# Property 4 — Change_List well-formedness
# --------------------------------------------------------------------------


def _entry(operation: str, **overrides) -> dict:
    entry = {
        "id": "CL-1-001",
        "iteration": 1,
        "target_document": "CV_Working_Copy",
        "implements_findings": ["SF-001"],
        "operation": operation,
        "anchor": {"paragraph_key": "exp.aws.bullet.3"},
    }
    entry.update(overrides)
    return entry


# A valid entry for every operation in the closed vocabulary.
VALID_ENTRIES_BY_OPERATION = {
    "replace_run_text": _entry(
        "replace_run_text",
        anchor={"paragraph_key": "exp.aws.bullet.3", "match_text": "QuickSuite"},
        new_text="Amazon Q",
        notes="Merged spelling + ATS keyword finding.",
    ),
    "replace_paragraph_text": _entry(
        "replace_paragraph_text",
        new_text="Led a team of eight engineers delivering a payments platform.",
    ),
    "insert_paragraph_after": _entry(
        "insert_paragraph_after",
        new_text="Certifications: AWS Solutions Architect.",
        style="Normal",
    ),
    "insert_paragraph_before": _entry(
        "insert_paragraph_before",
        new_text="Professional Summary",
        style="Heading 1",
    ),
    "delete_paragraph": _entry("delete_paragraph"),
    "set_paragraph_style": _entry("set_paragraph_style", style="Heading 2"),
    "replace_bullet_list": _entry(
        "replace_bullet_list",
        new_items=["Python, Go, TypeScript", "AWS, Kubernetes", "CI/CD, Terraform"],
    ),
}


def test_every_operation_has_a_representative_valid_entry():
    """Guard: the schema's operation enum and our fixtures stay in lockstep."""
    schema_ops = set(CHANGE_LIST_SCHEMA["$defs"]["entry"]["properties"]["operation"]["enum"])
    assert set(VALID_ENTRIES_BY_OPERATION) == schema_ops


@pytest.mark.parametrize("operation", sorted(VALID_ENTRIES_BY_OPERATION))
def test_valid_change_list_entry_per_operation_as_bare_array(operation: str):
    """docx_edit.py accepts a bare list of entries; that shape must validate."""
    change_list = [VALID_ENTRIES_BY_OPERATION[operation]]
    assert is_valid(change_list, CHANGE_LIST_SCHEMA), f"{operation} entry should validate"


def test_valid_change_list_document_with_entries_validates():
    """The ``{"iteration": n, "entries": [...]}`` document shape must validate."""
    document = {
        "iteration": 1,
        "entries": list(VALID_ENTRIES_BY_OPERATION.values()),
    }
    assert is_valid(document, CHANGE_LIST_SCHEMA)


def test_valid_change_list_document_without_iteration_validates():
    document = {"entries": [VALID_ENTRIES_BY_OPERATION["delete_paragraph"]]}
    assert is_valid(document, CHANGE_LIST_SCHEMA)


def test_empty_bare_array_is_a_valid_change_list():
    assert is_valid([], CHANGE_LIST_SCHEMA)


# Invalid Change_Lists — each must FAIL validation.
INVALID_CHANGE_LISTS = {
    "bad_operation": [_entry("rewrite_everything")],
    "missing_anchor_paragraph_key": [
        _entry("replace_paragraph_text", anchor={"match_text": "x"}, new_text="y")
    ],
    "missing_id": [{k: v for k, v in _entry("delete_paragraph").items() if k != "id"}],
    "missing_operation": [
        {k: v for k, v in _entry("delete_paragraph").items() if k != "operation"}
    ],
    "missing_anchor": [
        {k: v for k, v in _entry("delete_paragraph").items() if k != "anchor"}
    ],
    "entry_unknown_field": [_entry("delete_paragraph", surprise=True)],
    "document_missing_entries": {"iteration": 1},
    "document_unknown_field": {"entries": [], "surprise": True},
    "neither_array_nor_object": "not a change list",
}


@pytest.mark.parametrize("name", sorted(INVALID_CHANGE_LISTS))
def test_invalid_change_list_fails_validation(name: str):
    change_list = INVALID_CHANGE_LISTS[name]
    assert not is_valid(change_list, CHANGE_LIST_SCHEMA), f"{name} should NOT validate"


# --------------------------------------------------------------------------
# resume_state frontmatter object
# --------------------------------------------------------------------------


def _resume_state(**overrides) -> dict:
    state = {
        "status": "IN_PROGRESS",
        "agent": "cv-editor",
        "timestamp": "2026-05-29T10:14:02Z",
        "input_hash": "7f3a9c2e1b04",
        "current_step": "apply_change_list",
        "iteration": 1,
    }
    state.update(overrides)
    return state


@pytest.mark.parametrize(
    "status",
    ["IN_PROGRESS", "COMPLETED", "BLOCKED_ON_CLARIFICATION", "FATAL"],
)
def test_valid_resume_state_validates(status: str):
    assert is_valid(_resume_state(status=status), RESUME_STATE_SCHEMA)


def test_resume_state_allows_extra_frontmatter_keys():
    """resume_state.md frontmatter may carry agent-specific extras (notes, etc.)."""
    assert is_valid(_resume_state(phase="EDIT", run_id="abc"), RESUME_STATE_SCHEMA)


INVALID_RESUME_STATES = {
    "bad_status": _resume_state(status="RUNNING"),
    "missing_agent": {k: v for k, v in _resume_state().items() if k != "agent"},
    "missing_status": {k: v for k, v in _resume_state().items() if k != "status"},
    "missing_iteration": {k: v for k, v in _resume_state().items() if k != "iteration"},
    "iteration_not_integer": _resume_state(iteration="one"),
    "negative_iteration": _resume_state(iteration=-1),
    "empty_agent": _resume_state(agent=""),
}


@pytest.mark.parametrize("name", sorted(INVALID_RESUME_STATES))
def test_invalid_resume_state_fails_validation(name: str):
    state = INVALID_RESUME_STATES[name]
    assert not is_valid(state, RESUME_STATE_SCHEMA), f"{name} should NOT validate"
