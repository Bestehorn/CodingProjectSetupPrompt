# shared/schemas

JSON Schemas for the suite's data models (task 7, Requirement 9). Dialect:
**JSON Schema draft 2020-12** (`$schema: https://json-schema.org/draft/2020-12/schema`).
Validated with the `jsonschema` library when present; `tests/test_schemas.py`
also carries a dependency-free structural fallback so the schema tests run and
pass deterministically even without the library installed.

## Files

- `finding.schema.json` — the unified **Finding** (Requirement 9.1, design
  "Data Models / Finding"). Required: `id`, `source_agent`, `iteration`,
  `target_document`, `category`, `severity`, `anchor`, `rationale`, `status`.
  `current` and `proposed` are **optional** (not every Finding carries text to
  change — e.g. a structural ATS hazard or a hiring-manager concern). Field
  domains:
  - `target_document` ∈ {`CV_Working_Copy`, `Letter_Working_Copy`, `package_coherence`}
  - `category` ∈ {`spelling`, `formatting`, `language`, `jd_gap`, `ats`, `hiring_manager_concern`, `length`}
  - `severity` ∈ {`low`, `medium`, `high`, `blocking`}
  - `status` ∈ {`open`, `applied`, `verification_failed`, `accepted_gap`, `wont_fix`}

  **The `anchor` is intentionally permissive.** It must be a non-empty object
  carrying at least one location-identifying key, and it accommodates BOTH:
  - the design's example anchor — `{ section, paragraph_key, match_text }`; and
  - the object anchors emitted by `ats_structural.py` — `{ type, hazard, … }`
    where the tail keys vary by hazard (`paragraph_key`, `section_index`,
    `columns`, `table_index`, `part`, `text`).

  This is expressed as `anchor.anyOf` requiring one of
  `paragraph_key` / `section` / `section_index` / `table_index` / `type`, with
  `additionalProperties: true` so future anchor shapes (e.g. `package_coherence`
  anchors spanning both documents) keep validating. `tests/test_schemas.py`
  validates real `ats_structural.detect_hazards(...)` output against this schema
  to guarantee the two shapes never drift apart.

- `change_list.schema.json` — a **Change_List** as consumed by `docx_edit.py`.
  The top level is `oneOf`: a bare JSON array of entries, OR an object with an
  `entries` array and optional `iteration` (the two shapes `docx_edit.py`
  accepts). Each entry requires `id`, `operation`, `anchor`, with
  `anchor.paragraph_key` required (`match_text` optional). `operation` ∈ the
  closed engine vocabulary {`replace_run_text`, `replace_paragraph_text`,
  `insert_paragraph_after`, `insert_paragraph_before`, `delete_paragraph`,
  `set_paragraph_style`, `replace_bullet_list`}. `implements_findings`,
  `new_text`, `style`, `new_items`, `notes`, `iteration`, `target_document` are
  optional / used where the operation needs them.

- `resume_state.schema.json` — the per-agent **resume_state** model
  (Requirement 14.2, design "Data Models / resume_state.md"). `resume_state.md`
  is authored on disk as **Markdown with YAML frontmatter**; this schema
  describes the **structured frontmatter object** after a validator parses it
  (the free-form notes body below the frontmatter is out of scope and not
  validated). Required: `status`, `agent`, `timestamp`, `input_hash`,
  `current_step`, `iteration`; `status` ∈ {`IN_PROGRESS`, `COMPLETED`,
  `BLOCKED_ON_CLARIFICATION`, `FATAL`}. Extra frontmatter keys are allowed
  (`additionalProperties: true`).
