# Implementation Plan

**Subject:** CV Customizer Agent Suite

## Overview

This plan builds the suite bottom-up: the deterministic Python core first (it carries the testable logic), then the JSON schemas, then each agent's configuration and prompt, then the orchestrator that ties them together, and finally end-to-end validation. Tests are written alongside each script and must pass before moving on (per the workspace `tests-must-not-fail` steering rule — no skips, no xfail).

Paths are relative to the repository root. All new agent assets live under `cli-agents/cv/`.

## Tasks

- [x] 1. Scaffold the distribution layout and test fixtures
  - Create `cli-agents/cv/` with the seven agent subdirectories, `shared/scripts/`, `shared/schemas/`, `shared/install/`, `shared/README.md`, and `tests/fixtures/` per design "Distribution layout".
  - Each agent subdirectory gets placeholders for its JSON config, `prompt.md`, and a `CLIAgent-<Name>Discussion.txt` notes file (`.txt` extension to match the existing repo convention).
  - Create a `pytest` configuration (or reuse the repo's if present) rooted at `cli-agents/cv/tests/`.
  - Add small fixture documents under `cli-agents/cv/tests/fixtures/` (a versioned location, not the gitignored `tmp/`): calibrated 1-page, 2-page, and 3-page `.docx` files; a `.docx` containing a text box, a 2-column section, header content, and a layout table; a small sample CV `.docx`; a sample JD as `.html` and `.txt`; a sample database as `.md`.
  - Ensure the following install-output / runtime paths are gitignored (add to `.gitignore` if absent): `.kiro/agent-state/` (per-run runtime state), `.kiro/agents/cv-*.json` (generated discovery configs with machine-specific absolute paths), and `.kiro/cv-suite/` (the installed tree). Only the `cli-agents/cv/` authoring tree is version-controlled; the installer outputs are regenerated per machine (C2).
  - _Requirements: 16.1, 16.2, 16.5_

- [x] 2. Implement `docx_normalize.py` with stable anchors
  - Extract paragraph text to a normalized Markdown representation and emit a companion `*.anchors.json` mapping stable paragraph keys → live indices, per design "anchor model".
  - Stable key = nearest preceding heading + content hash + occurrence ordinal.
  - [x] 2.1 Write unit tests: keys are stable after inserting/deleting earlier paragraphs; duplicate paragraphs get distinct ordinals; every key resolves to exactly one paragraph; round-trip of anchors against the live doc.
  - _Requirements: 1.10, 3.5, 9.1 (anchor field), 10.3 (oscillation matching basis)_

- [x] 3. Implement `input_normalize.py` (multi-format → Normalized_Text)
  - Dispatch by extension: `.docx` (python-docx), `.pdf` (pdfminer.six), `.html` (BeautifulSoup, collapse whitespace), `.md`/`.txt` (passthrough + whitespace normalization).
  - On missing library, exit non-zero naming the package (no install attempts).
  - [x] 3.1 Write unit tests for each format → expected text; messy-HTML whitespace collapse; missing-library path exits non-zero with a clear message (monkeypatch import).
  - _Requirements: 1.2, 1.4, 1.10, 15.5_

- [x] 4. Implement `page_count.py` (render-based, reliable)
  - Primary: Microsoft Word automation (`win32com`), open the document, call `Document.Repaginate()` and let background pagination settle, then read `ComputeStatistics(wdStatisticPages)`, and close without saving — Word is authoritative because the candidate edits in Word downstream, and repagination prevents a stale count on a hard gate.
  - Fallback: `soffice --headless --convert-to pdf` then count pages with `pypdf`.
  - If no renderer available, exit non-zero with a clear message (page count must never be guessed for the hard gate).
  - Output a JSON line and write `page_counts.json`.
  - [x] 4.1 Write unit tests for control flow only: renderer-absent path exits non-zero (monkeypatch COM dispatch / PATH); JSON output shape is correct. These do NOT validate the real page number — that is covered by the calibrated-fixture check in task 17 on a host with Word installed.
  - _Requirements: 11.1, 11.2, 11.4, 11.6, 11.7_

- [x] 5. Implement `docx_edit.py` (the edit engine)
  - Implement the closed operation set: `replace_run_text`, `replace_paragraph_text`, `insert_paragraph_after/before`, `delete_paragraph`, `set_paragraph_style`, `replace_bullet_list`.
  - Preserve run formatting on intra-run replacement; flatten with `formatting_normalized: true` note when a match spans runs.
  - Re-resolve anchors against the live doc at run start; idempotency check (`already_satisfied`); post-apply verification producing `result.json` entries (`verified | failed_to_apply | already_satisfied | formatting_normalized`).
  - [x] 5.1 Write unit tests: each operation on fixtures; formatting preserved on intra-run edit; idempotent re-run; `failed_to_apply` when anchor unresolved (and asserts no other paragraph changed); verification output correctness.
  - _Requirements: 3.2, 3.3, 3.5, 3.6_

- [x] 6. Implement `ats_structural.py` (deterministic ATS hazards)
  - Detect via python-docx XML inspection: text boxes (`w:txbxContent`), images/drawings with text, multi-column sections (`w:cols w:num>1`), header/footer content, layout tables, non-standard heading styles, parser-hostile Unicode.
  - Emit candidate Findings as JSON (the ATS agent adopts them).
  - [x] 6.1 Write unit tests: each hazard fixture produces the expected Finding category/anchor; a clean doc produces none.
  - _Requirements: 7.1, 7.3, 7.4_

- [x] 7. Author JSON schemas in `shared/schemas/`
  - `finding.schema.json`, `change_list.schema.json`, `resume_state.schema.json` matching the design data models (field domains for `target_document`, `category`, `severity`, `status`, etc.).
  - [x] 7.1 Write tests validating the fixture Findings/Change_Lists against the schemas (Properties 3, 4).
  - _Requirements: 9.1, 9.2, 9.3, 14.2_

- [x] 8. CV Editor Agent (config + prompt) — canonical name `cv-editor`
  - `KiroCLIAgent-CVEditor.json`: set `"name": "cv-editor"` explicitly; `tools` = read/write/shell; `toolsSettings.write.allowedPaths` = `tmp/cv-editor/**`, `Workflow_State_Directory/**`, `working/**`; `shell.allowedCommands` = the `apply_changes.py` pattern only; global denied commands; no `subagent`.
  - `prompt.md`: contract to consume a Change_List, write a thin wrapper that invokes `docx_edit.py`, run it, archive script+logs to state, emit `result.json`, never spawn agents, report `failed_to_apply` honestly. Include resume-state protocol.
  - `CLIAgent-CVEditorDiscussion.txt`: role notes.
  - _Requirements: 3.1–3.9, 14.1–14.4, 15.3, 15.4, 16.3, 16.4, 16.5_

- [x] 9. Spell and Formatting Reviewer Agent (config + prompt) — canonical name `cv-spell-format-reviewer`
  - Config: set `"name": "cv-spell-format-reviewer"`; `tools` = read/write; write scope limited to `findings/cv-spell-format-reviewer/**` + own state dir; no shell; LLM-only analysis.
  - Prompt: category set (spelling/grammar/punctuation/caps/tense/date/number/formatting), CV + letter, no JD; emit schema-valid Findings tagged per `target_document`; gate = zero open findings; resume-state protocol.
  - `CLIAgent-SpellFormatReviewerDiscussion.txt`: role notes.
  - _Requirements: 4.1–4.6, 14, 15.3, 16.3, 16.4, 16.5_

- [x] 10. Language and Content Reviewer Agent (config + prompt) — canonical name `cv-language-content-reviewer`
  - Config: set `"name": "cv-language-content-reviewer"`; as the spell/format reviewer but its own `findings/cv-language-content-reviewer/**` dir.
  - Prompt: prose-critique category set + cover-letter structure; no JD; also handle a length-reduction directive (`category: length`) when the orchestrator requests it, preserving content that resolves higher-priority findings.
  - `CLIAgent-LanguageContentReviewerDiscussion.txt`: role notes.
  - _Requirements: 5.1–5.6, 11.5, 14, 15.3, 16.3, 16.4, 16.5_

- [x] 11. JD Alignment Reviewer Agent (two-phase, config + prompt) — canonical name `cv-jd-alignment-reviewer`
  - Config: set `"name": "cv-jd-alignment-reviewer"`; `tools` = read/write; write scope = `findings/cv-jd-alignment-reviewer/**`, `jd_alignment/**`, `accepted_gaps.md`, `database_sidecar.md`, and user DB iff `.md`/`.txt`; no shell; no subagent; non-interactive.
  - Prompt Phase 1: gap analysis, DB-sourced fill-ins, emit `pending_questions.json`; return pending count; never prompt the user.
  - Prompt Phase 2: integrate `answered_questions.json` → fill-in Findings; record declines as `accepted_gap` with verbatim response; DB/sidecar writeback with provenance; may append new questions to repeat the cycle.
  - `CLIAgent-JDAlignmentReviewerDiscussion.txt`: role notes.
  - _Requirements: 6.1–6.11, 12.2, 13.1–13.6, 14, 15.3, 16.3, 16.4, 16.5_

- [x] 12. ATS Reviewer Agent (config + prompt) — canonical name `cv-ats-reviewer`
  - Config: set `"name": "cv-ats-reviewer"`; `tools` = read/write/shell; write scope = `findings/cv-ats-reviewer/**` + `tmp/cv-ats-reviewer/**`; `shell.allowedCommands` = `ats_checks.py` pattern only.
  - Prompt: run `ats_structural.py` via tmp-script for structural hazards; LLM keyword-matching against the JD; defer true skill gaps to JD Alignment; emit schema-valid Findings; gate = zero open findings.
  - `CLIAgent-ATSReviewerDiscussion.txt`: role notes.
  - _Requirements: 7.1–7.7, 14, 15.3, 15.4, 16.3, 16.4, 16.5_

- [x] 13. Hiring Manager Reviewer Agent (config + prompt) — canonical name `cv-hiring-manager-reviewer`
  - Config: set `"name": "cv-hiring-manager-reviewer"`; `tools` = read/write; write scope = `findings/cv-hiring-manager-reviewer/**` + own state; no shell; no user questions.
  - Prompt: whole-package review (CV + letter coherence) against the JD; strengths with citations; concern Findings; `INVITE`/`DO_NOT_INVITE`; consume `accepted_gaps.md` as context; gate = INVITE + no open concerns, but not sufficient for convergence alone.
  - `CLIAgent-HiringManagerReviewerDiscussion.txt`: role notes.
  - _Requirements: 8.1–8.7, 12.4, 14, 15.3, 16.3, 16.4, 16.5_

- [x] 14. CV Orchestrator Agent (config + prompt)
  - [x] 14.1 Config: set `"name": "cv-orchestrator"`; `tools` = read/write/shell/subagent; `toolsSettings.subagent.availableAgents` and `trustedAgents` = the six canonical delegate names (`cv-editor`, `cv-spell-format-reviewer`, `cv-language-content-reviewer`, `cv-jd-alignment-reviewer`, `cv-ats-reviewer`, `cv-hiring-manager-reviewer`); write scope = `Workflow_State_Directory/**`, own state, `working/**`, `backups/**`; `shell.allowedCommands` = the normalization + page-count script patterns; global denied commands.
  - [x] 14.2 Prompt — setup: parse first-message inputs into `run_manifest.json` (workspace-relative, no env vars), validate mandatory inputs (fail fast), record input hashes and page-limit overrides, init `Workflow_State_Directory`, run normalization + anchors, snapshot working copies.
  - [x] 14.3 Prompt — loop: REVIEW (spawn the five reviewers in order, JD-alignment as Phase 1), QA (relay pending questions one at a time, record answers, spawn Phase 2, repeat as needed), EDIT (dedup + conflict-priority → Change_List, snapshot backups, spawn editor, collect result), EVALUATE (page_count per doc, derive length findings if over, recompute gates), convergence check.
  - [x] 14.4 Prompt — conflict, oscillation, convergence, termination: implement conflict priority order, oscillation→alternate→`wont_fix` (3x) rule, and the single success-termination path — success (`COMPLETED`) is declared ONLY in the EDIT phase's empty-change_list branch (a fresh REVIEW produced zero new open findings AND all pages within limits AND hiring manager = INVITE). The EVALUATE phase never declares success; after applying edits it always advances to the next iteration's REVIEW so the edited state is re-reviewed (Property 6). Implement the 10-iteration cap and `termination_report.md` (success or DID_NOT_CONVERGE; surface accepted gaps, DB writeback, sidecar location, page counts).
  - [x] 14.5 Prompt — resumability: read `workflow_state.md` on launch; resume by phase/reviewer-queue/outstanding-questions when input hash matches; archive and restart otherwise.
  - Discussion notes file.
  - _Requirements: 2.1–2.13, 9.3, 9.4, 10.1–10.7, 11.3–11.6, 12.3, 12.5, 13.5, 14.5, 15.1, 15.2_

- [x] 15. Implement `install_agents.py` (discovery installation) — finding A1/A2/B1
  - Copy the `cli-agents/cv/` tree to a fixed installed root: `.kiro/cv-suite/` (workspace install) or `~/.kiro/cv-suite/` (global install), preserving prompts, `shared/scripts/`, and `shared/schemas/` together.
  - For each agent, generate a discovery config at `.kiro/agents/<canonical-name>.json` (or `~/.kiro/agents/<canonical-name>.json`) with: `name` = canonical name; `prompt` = an absolute `file://` URI to the installed prompt; every shared-script reference in `allowedCommands` and the prompt rewritten to the absolute installed script path under `<install-root>/cv-suite/shared/scripts/`.
  - Emit Windows-correct path strings on the Windows-first target: absolute `file://` URIs as `file:///D:/.../prompt.md` and `shell.allowedCommands` patterns with backslash paths correctly regex-escaped. Derive the correct form from the host at install time (remain cross-platform) (D1).
  - Resolve all paths to absolute form at install time. No environment variables, no reliance on cwd.
  - Verify post-install: each `.kiro/agents/<canonical-name>.json` `name` matches the orchestrator's `availableAgents`/`trustedAgents` entries byte-for-byte; each referenced prompt and script exists at its resolved path.
  - [x] 15.1 Write tests: install into a temp directory; assert seven discovery configs exist with correct `name` fields; assert `prompt`/script paths resolve to existing files; assert orchestrator delegate names == generated config basenames.
  - _Requirements: 16.6, 16.7, 16.8, 16.9, 16.10, 15.1_

- [x] 16. Suite README and install/usage docs
  - `cli-agents/cv/shared/README.md`: required Python packages (python-docx, pdfminer.six, beautifulsoup4, pypdf, pywin32 for Word automation; LibreOffice as a fallback renderer), one-time environment-setup instructions the user runs (not the agents), how to run `install_agents.py` (workspace vs global), how to start the workflow (`kiro-cli --agent cv-orchestrator`) and the first-message input format, and the self-contained copy-then-install instructions.
  - _Requirements: 1.5, 11.7, 15.5, 16.8, 16.9_

- [x] 17. Orchestrator-logic harness tests (stubbed subagents)
  - Drive the convergence/dedup/conflict/oscillation/one-question-at-a-time logic over recorded fixture findings without spawning real subagents.
  - Assert Properties 5, 6, 8, 9 and the conflict-priority/oscillation rules from design.
  - _Requirements: 6.6, 9.4, 10.1–10.5, 11.6, 12.3_

- [x] 18. End-to-end smoke test inside Kiro CLI
  - Run `install_agents.py` into the workspace; confirm the orchestrator is discoverable and spawns each delegate by canonical name as a trusted subagent; non-interactive reviewers never attempt to prompt.
  - Use the versioned fixture CV `.docx` + fixture JD under `cli-agents/cv/tests/fixtures/` (not the gitignored `tmp/` sample); run the orchestrator; verify: tailored CV produced within page limit, accepted-gaps honored, DB writeback/sidecar behaves per format, originals unchanged (Property 1), single-writer holds (Property 2).
  - Run the calibrated page-count check on the target Windows host (Word installed): the 1/2/3-page fixtures report 1/2/3 through the real `page_count.py` path (Property 7 — the hard gate's only true correctness check).
  - Clean up `tmp/<canonical-name>/` scratch on success per design.
  - _Requirements: 1.7, 1.8, 1.9, 1.11, 2.1, 3.1, 11.2, 13.1–13.3_

- [x] 19. Final checkpoint
  - Verify every requirement is covered by an agent/config/script/test; reconcile against `requirements.md` and the design's correctness properties; confirm the resolved design decisions (D-1 through D-13) are reflected in the implementation.
  - _Requirements: all_

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": [1],
      "description": "Scaffold distribution layout, test fixtures, gitignore"
    },
    {
      "wave": 2,
      "tasks": [2, 3, 4, 5, 6],
      "description": "Deterministic Python core scripts; each depends only on task 1; mutually independent and parallelizable"
    },
    {
      "wave": 3,
      "tasks": [7],
      "description": "JSON schemas, once data shapes from wave 2 are settled"
    },
    {
      "wave": 4,
      "tasks": [8, 9, 10, 11, 12, 13],
      "description": "Agent configs + prompts; 8 depends on 5, 12 depends on 6, all depend on 7"
    },
    {
      "wave": 5,
      "tasks": [14],
      "description": "Orchestrator (subtasks 14.1-14.5); depends on all delegate agents and all scripts"
    },
    {
      "wave": 6,
      "tasks": [15, 17],
      "description": "Installer (install_agents.py, depends on all seven agent configs) and orchestrator-logic harness tests (depend on task 14)"
    },
    {
      "wave": 7,
      "tasks": [16, 18],
      "description": "Suite README/install docs (depends on installer) and end-to-end smoke test inside Kiro CLI (depends on installer + harness)"
    },
    {
      "wave": 8,
      "tasks": [19],
      "description": "Final checkpoint"
    }
  ]
}
```

```
1 (scaffold + fixtures)
├─ 2 docx_normalize ─┐
├─ 3 input_normalize │
├─ 4 page_count      ├─→ 7 schemas ─┐
├─ 5 docx_edit ──────┤              │
└─ 6 ats_structural ─┘              │
                                    ▼
   8 editor ───────────────────────┤
   9 spell/format reviewer ────────┤
  10 language/content reviewer ────┤
  11 jd-alignment reviewer ────────┤
  12 ats reviewer ─────────────────┤
  13 hiring-manager reviewer ──────┤
                                    ▼
                          14 orchestrator (14.1→14.5)
                                    │
                  ┌─────────────────┼──────────────────┐
                  ▼                                     ▼
        15 install_agents.py                 17 orchestrator-logic harness tests
                  │                                     │
        16 README/install docs                          │
                  └──────────────────┬──────────────────┘
                                     ▼
                          18 end-to-end smoke test (+ calibrated page-count check)
                                     │
                          19 final checkpoint
```

- Tasks 2–6 are independent of each other and can be built in parallel; each depends only on task 1.
- Task 7 (schemas) depends on the data shapes exercised by 2–6 being settled.
- Tasks 8–13 (agents) depend on the scripts they invoke (8→5, 12→6) and on schemas (7); reviewers 9, 10, 13 depend only on 7 and 1.
- Task 14 (orchestrator) depends on all delegate agents (8–13) and all scripts (2–6).
- Task 15 (installer) depends on all seven agent configs (8–14). Task 16 (README) depends on 15. Task 17 (harness) depends on 14.
- Task 18 (smoke) depends on 15 and 17; task 19 is last.

## Notes

- Test framework is `pytest`. Any failing test is fixed at the source per the `tests-must-not-fail` steering rule — never skipped, removed, or marked xfail.
- Agents must never run package installers or `git`; the README (task 16) documents the one-time environment setup the user performs, and `install_agents.py` (task 15) is run by the user, not by an agent.
- Agents are authored under `cli-agents/cv/` but must be installed into `.kiro/agents/` (or `~/.kiro/agents/`) to be discoverable; `install_agents.py` copies the tree to `.kiro/cv-suite/` and generates discovery configs with absolute `file://` prompt and script paths. Each config's `name` field equals its canonical name byte-for-byte (D-13).
- Discussion-notes files use the `.txt` extension to match the existing repo convention (`cli-agents/issue-intake/`, `cli-agents/dead-code/`).
- Page counting is render-based by design; Microsoft Word automation is the primary engine with `Repaginate()` before `ComputeStatistics` (the candidate edits in Word downstream, so the gate matches what they see), with LibreOffice as fallback. If neither is available the workflow fails fast rather than guessing. The real page count is validated only by the calibrated check on a Word-equipped host (task 18), not by monkeypatched unit tests.
- All design decisions D-1 through D-13 are resolved; see design's "Resolved Design Decisions".
- `.kiro/agent-state/` is runtime state and is gitignored; the candidate's git versioning covers inputs and the `cli-agents/cv/` tree. Test fixtures live in the versioned `cli-agents/cv/tests/fixtures/`, not in gitignored `tmp/`. The installer outputs — `.kiro/agents/cv-*.json` and `.kiro/cv-suite/` — are also gitignored and regenerated per machine (they carry machine-specific absolute paths); only `cli-agents/cv/` is version-controlled (C2).
- Success (`COMPLETED`) is declared at exactly one point: the EDIT phase's empty-change_list branch, i.e. a fresh REVIEW found nothing to change and pages + hiring-manager gate hold. The EVALUATE phase never terminates-success; it advances to the next REVIEW so edits are always re-reviewed (Property 6, C1).
