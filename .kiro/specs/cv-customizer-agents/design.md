# Design Document

**Subject:** CV Customizer Agent Suite

## Overview

This design specifies how the seven-agent CV Customizer suite is built on top of Kiro CLI's native subagent mechanism. It is organized layer-by-layer: cross-cutting concerns first (orchestration model, state and filesystem layout, data schemas, normalization, page counting, edit application, conflict and convergence handling, tooling, permissions), then a per-agent specification that draws on those layers.

The suite runs inside a single Kiro CLI chat session. The candidate talks only to the CV Orchestrator Agent. The orchestrator spawns the other six agents as subagents, each running with its own context and its own tool permissions, and aggregates their results from disk. All durable state lives under `.kiro/agent-state/`, mirroring the conventions already used by the agents in `cli-agents/` (issue-intake, dead-code, doc-review, etc.).

The deliverable is an `Application_Package`: a tailored two-page CV and, when provided, a one-page motivational letter, both edited to maximize the candidate's likelihood of being invited to an interview while passing every reviewer's independent quality gate.

This design satisfies the requirements in `requirements.md`. Requirement references appear as `[Rn.m]`.

## Architecture

### High-level topology

```
                         ┌───────────────────────────────────────┐
                         │      Candidate (main chat session)      │
                         └───────────────────┬─────────────────────┘
                                             │  (only this agent talks to the user)
                         ┌───────────────────▼─────────────────────┐
                         │         CV Orchestrator Agent            │
                         │  - owns the iteration loop               │
                         │  - owns Workflow_State_Directory         │
                         │  - asks JD questions one at a time       │
                         │  - tool: subagent                        │
                         └───┬───────┬───────┬───────┬───────┬──────┘
            spawns as subagents (toolsSettings.subagent.availableAgents / trustedAgents)
        ┌───────────┬────────┴───┬────────┬─┴──────────┬───────────────┬─────────────┐
        ▼           ▼            ▼        ▼             ▼               ▼             ▼
 ┌────────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐ ┌────────────┐ ┌────────────┐ (editor)
 │ Spell &    │ │ Language │ │  JD    │ │   ATS    │ │  Hiring    │ │ CV Editor  │
 │ Formatting │ │ &Content │ │ Align  │ │ Reviewer │ │  Manager   │ │ (writes)   │
 │ Reviewer   │ │ Reviewer │ │ (2-ph) │ │          │ │  Reviewer  │ │            │
 └─────┬──────┘ └────┬─────┘ └───┬────┘ └────┬─────┘ └─────┬──────┘ └─────┬──────┘
       │  read-only  │           │ r/o + sidecar         r/o            write docx
       └─────────────┴───────────┴───────────┴─────────────┘            via python
                          all communicate through                       script in tmp
                          Workflow_State_Directory (on disk)
```

### Why this topology

- **Single session, native delegation [R2.1, R2.2, D-1].** Kiro CLI's subagent feature lets the orchestrator hand a focused task to another custom agent that runs in its own isolated context and returns a `summary`. The orchestrator does not shell out to a second `kiro-cli` process and does not require the user to `/agent swap`. This matches the candidate's mental model of one coordinator distributing work.
- **Disk as the handoff bus.** A subagent's `summary` returns a short natural-language report to the orchestrator, but the substantive artifacts (Findings, Change_List, normalized inputs) are written to `Workflow_State_Directory`. This keeps the orchestrator's context lean, makes every handoff auditable, and makes the workflow resumable after interruption [R14].
- **Exactly one writer [R3.1].** Only the CV Editor Agent mutates the Working Copies. Reviewers are read-only (with narrow exceptions for the JD Alignment Reviewer's database/sidecar writes and the ATS Reviewer's tmp scripts). This eliminates write races between parallel subagents and gives a single, well-tested edit path.
- **Human-in-the-loop is confined to the orchestrator [R2.13, R6.6].** Subagents launched non-interactively cannot prompt the user; if they need approval they fail fast. We therefore never ask the user anything from inside a subagent. The JD Alignment Reviewer emits questions to disk; the orchestrator (which is interactive) relays them one at a time.

### Execution model: orchestrator-driven loop, not native review-loop

Kiro CLI offers a native review-loop construct (target/trigger/`max_iterations`, capped at 10). It is well-suited to a single implementer↔reviewer pair. Our convergence condition is global: *every* reviewer gate must pass simultaneously, *and* a page constraint must hold across one or two documents. That is a whole-workflow predicate, not a single stage's output check.

**Decision:** the orchestrator implements the loop itself, evaluating on-disk state after each pass, and enforces its own cap of 10 iterations [R10.2, D-10]. This cap is self-imposed in the orchestrator's loop logic; the platform does not enforce any iteration limit on an orchestrator-driven loop. The value 10 is chosen only to align with the maximum of Kiro CLI's native review-loop construct — that native construct is *not* used for the top-level loop. (A future optimization could use a native loop for a tight editor↔spell/format sub-cycle, but that is explicitly out of scope for v1 to avoid two competing loop authorities.)

## State and Filesystem Layout

All paths are workspace-relative. No environment variables are read at any point [R15.1].

### Distribution layout (version-controlled) [R16]

Authoring tree under `cli-agents/cv/`. Each config's `name` field is set to the agent's canonical name (shown in the comment beside each JSON file); the filename is for human navigation only and is not what Kiro resolves on.

```
cli-agents/cv/
  orchestrator/
    KiroCLIAgent-CVOrchestrator.json          # "name": "cv-orchestrator"
    prompt.md
    CLIAgent-CVOrchestratorDiscussion.txt
  editor/
    KiroCLIAgent-CVEditor.json                # "name": "cv-editor"
    prompt.md
    CLIAgent-CVEditorDiscussion.txt
  spell-format-reviewer/
    KiroCLIAgent-SpellFormatReviewer.json     # "name": "cv-spell-format-reviewer"
    prompt.md
    CLIAgent-SpellFormatReviewerDiscussion.txt
  language-content-reviewer/
    KiroCLIAgent-LanguageContentReviewer.json # "name": "cv-language-content-reviewer"
    prompt.md
    CLIAgent-LanguageContentReviewerDiscussion.txt
  jd-alignment-reviewer/
    KiroCLIAgent-JDAlignmentReviewer.json     # "name": "cv-jd-alignment-reviewer"
    prompt.md
    CLIAgent-JDAlignmentReviewerDiscussion.txt
  ats-reviewer/
    KiroCLIAgent-ATSReviewer.json             # "name": "cv-ats-reviewer"
    prompt.md
    CLIAgent-ATSReviewerDiscussion.txt
  hiring-manager-reviewer/
    KiroCLIAgent-HiringManagerReviewer.json   # "name": "cv-hiring-manager-reviewer"
    prompt.md
    CLIAgent-HiringManagerReviewerDiscussion.txt
  shared/
    scripts/
      docx_edit.py                    # editor's reusable edit engine
      docx_normalize.py               # extracts Normalized_Text from .docx
      input_normalize.py              # extracts Normalized_Text from pdf/html/txt/md
      page_count.py                   # renders via Word/LibreOffice, counts pages
      ats_structural.py               # deterministic ATS structural checks
    schemas/
      finding.schema.json
      change_list.schema.json
      resume_state.schema.json
    install/
      install_agents.py               # copies tree to fixed location, generates .kiro/agents/*.json
    README.md                         # install/usage for the whole suite
  tests/
    fixtures/                         # versioned sample CV/JD/DB + hazard docx fixtures
    test_*.py
```

The discussion-notes files use the `.txt` extension to match the existing repository convention (`cli-agents/issue-intake/CLIAgent-IssueIntakeDiscussion.txt`, `cli-agents/dead-code/CLIAgent-DeadCodeDiscussion.txt`) [R16.5].

### Installation and discovery [R16.8, R16.9, R16.10, D-12]

Kiro CLI discovers custom agents **only** in `.kiro/agents/` (workspace) or `~/.kiro/agents/` (global); it does not scan `cli-agents/cv/`. The orchestrator spawns delegates **by canonical name** via `availableAgents`/`trustedAgents`, so the configs must (a) live in a discovery directory and (b) carry an explicit `name` field equal to the canonical name — Kiro's filename-derived naming would otherwise produce `KiroCLIAgent-CVEditor`, which would not match `cv-editor`.

**Install model — fixed-location tree + generated discovery configs.** The suite is installed to a single fixed location and the discovery directory holds thin configs that point at it. Concretely, `install_agents.py`:

1. Copies the entire `cli-agents/cv/` tree to a fixed installed root: `<install-root>/cv-suite/`, where `<install-root>` is `.kiro/` for a workspace install (giving `.kiro/cv-suite/`) or `~/.kiro/` for a global install. This carries prompts, shared scripts, and schemas together so their relative layout is preserved.
2. For each agent, writes a config into the discovery directory (`.kiro/agents/<canonical-name>.json` or `~/.kiro/agents/<canonical-name>.json`) with:
   - `name` set to the canonical name (e.g., `cv-editor`);
   - `prompt` set to an **absolute** `file://` URI pointing at the installed prompt (e.g., `file://<abs>/.kiro/cv-suite/editor/prompt.md`), so resolution does not depend on the config's own directory;
   - every shared-script reference in `allowedCommands` and in the prompt rewritten to the **absolute** installed script path under `<install-root>/cv-suite/shared/scripts/` (e.g., `python <abs>/.kiro/cv-suite/shared/scripts/page_count.py ...`).
3. Resolves all paths to absolute form at install time (no environment variables, no reliance on the current working directory) [R15.1, R16.7].

This satisfies "copy the tree and run install → working suite" [R16.9]: the authoring tree is portable, and the installer is the single place that knows the discovery-directory and fixed-location conventions. The orchestrator's `availableAgents`/`trustedAgents` list the canonical names, which now match the generated `.kiro/agents/*.json` `name` fields exactly [A1, A2, B1].

Shared scripts are therefore referenced by their absolute installed path (resolved by the installer), not "relative to the agent config directory" — this removes the earlier ambiguity about how `shared/scripts/` stays resolvable once configs live in `.kiro/agents/` [B1].

**Windows path formatting [D1].** The target environment is Windows-first (the page-count engine is Word automation via `win32com`). `install_agents.py` therefore emits Windows-correct absolute `file://` URIs (e.g., `file:///D:/.../.kiro/cv-suite/editor/prompt.md`, with the drive letter and forward slashes per the file-URI convention) and `shell.allowedCommands` patterns that contain backslash paths correctly regex-escaped (e.g., `python D:\\\\...\\\\cv-suite\\\\shared\\\\scripts\\\\page_count\\.py .*`). The installer is responsible for producing valid host-specific path strings; the POSIX-style placeholders shown elsewhere in this design are illustrative only. The installer remains cross-platform (it derives the correct form from the host at install time).

### Runtime state layout (not version-controlled; gitignored)

```
.kiro/agent-state/
  cv-workflow/                         # Workflow_State_Directory (shared)
    workflow_state.md                  # orchestrator resume marker [R14.5]
    iteration_log.md                   # human-readable audit trail [R10.6]
    run_manifest.json                  # input paths, hashes, page-limit overrides
    inputs/
      cv.normalized.md
      jd.normalized.md
      letter.normalized.md             # only if letter provided
      database.normalized.md           # only if database provided
    working/
      cv.working.docx                  # CV_Working_Copy
      letter.working.docx              # Letter_Working_Copy (if applicable)
    backups/
      cv.working.<iso>.bak.docx        # per-edit-pass backups [R3.4]
      letter.working.<iso>.bak.docx
    findings/
      cv-spell-format-reviewer/iteration-<n>.json
      cv-language-content-reviewer/iteration-<n>.json
      cv-jd-alignment-reviewer/iteration-<n>.json
      cv-ats-reviewer/iteration-<n>.json
      cv-hiring-manager-reviewer/iteration-<n>.json
    change_list/
      iteration-<n>.json
      iteration-<n>.result.json        # editor verification results
    jd_alignment/
      pending_questions.json           # Phase 1 output [R6.4]
      answered_questions.json          # orchestrator-collected answers
    accepted_gaps.md                   # Accepted_Gaps register [R12]
    database_sidecar.md                # when DB binary or absent [R13.2,R13.3]
    page_counts.json                   # latest measured counts per document
    termination_report.md              # final user-facing report

  cv-orchestrator/                     # Per_Agent_State_Directory (one per agent, by canonical name)
    resume_state.md
  cv-editor/
    resume_state.md
    scripts/<iso>/apply_changes.py     # archived editor scripts + logs [R3.9]
  cv-spell-format-reviewer/
    resume_state.md
  cv-language-content-reviewer/
    resume_state.md
  cv-jd-alignment-reviewer/
    resume_state.md
  cv-hiring-manager-reviewer/
    resume_state.md
  cv-ats-reviewer/
    resume_state.md
    scripts/<iso>/ats_checks.py
```

A `.gitignore` entry for `.kiro/agent-state/` is assumed (runtime state is per-run, not source). Two further paths are also install outputs and MUST be gitignored, not committed: `.kiro/agents/cv-*.json` (the generated discovery configs) and `.kiro/cv-suite/` (the installed tree). These contain machine-specific absolute paths produced by `install_agents.py` and are regenerated per machine; committing them would give a teammate who pulls the repo a broken suite (absolute paths from another machine), undercutting the R16.9 portability intent. The only version-controlled artifact is the `cli-agents/cv/` authoring tree (plus the candidate's own inputs). The candidate's git versioning applies to inputs and to the `cli-agents/cv/` tree, not to agent-state, the generated discovery configs, or the installed suite [D-2, C2].

Note: every per-agent directory, findings directory, and tmp directory uses the agent's canonical name verbatim (`cv-editor`, `cv-ats-reviewer`, etc.) per R16.3 [B2].

## Data Models

### Finding [R9.1]

Findings are JSON (chosen over Markdown-with-frontmatter for deterministic machine parsing by the orchestrator).

```json
{
  "id": "SF-003",
  "source_agent": "cv-spell-format-reviewer",
  "iteration": 1,
  "target_document": "CV_Working_Copy",
  "category": "spelling",
  "severity": "high",
  "anchor": {
    "section": "Professional Experience",
    "paragraph_key": "exp.aws.bullet.3",
    "match_text": "QuickSuite"
  },
  "current": "AWS Generative AI platform & services (e.g., Bedrock, QuickSuite, Kiro)",
  "proposed": "AWS Generative AI platform & services (e.g., Bedrock, Amazon Q, Kiro)",
  "rationale": "‘QuickSuite’ is not a recognized AWS product name; using an incorrect product name on a CV is a credibility risk.",
  "status": "open"
}
```

Field domains:

- `target_document`: `CV_Working_Copy` | `Letter_Working_Copy` | `package_coherence`.
- `category`: `spelling` | `formatting` | `language` | `jd_gap` | `ats` | `hiring_manager_concern` | `length` (used by the page-constraint reducer).
- `severity`: `low` | `medium` | `high` | `blocking`.
- `status`: `open` | `applied` | `verification_failed` | `accepted_gap` | `wont_fix`.

#### The anchor model (critical for stable, idempotent edits)

`python-docx` addresses paragraphs by index, which is unstable across edits (inserting one paragraph shifts every later index). To make Findings and edits robust [R3.5, R10.3 oscillation detection], the normalization step assigns each paragraph a **stable paragraph key** and records it so both reviewers and the editor speak the same coordinate system.

Implementation: `docx_normalize.py` walks the document body and computes, per paragraph, a stable key derived from (a) the nearest preceding heading text, plus (b) a content hash of the paragraph's runs, plus (c) an occurrence ordinal to disambiguate duplicates. The mapping `paragraph_key → current paragraph index` is persisted in `inputs/cv.normalized.md` sidecar metadata (a companion `cv.anchors.json`). The editor re-derives the mapping at edit time against the live document, so an anchor resolves correctly even after earlier edits in the same pass. When an anchor cannot be resolved (content changed underneath it), the editor reports `verification_failed` for that entry rather than editing the wrong paragraph [R3.6].

### Change_List entry [R9.3]

```json
{
  "id": "CL-1-007",
  "iteration": 1,
  "target_document": "CV_Working_Copy",
  "implements_findings": ["SF-003", "ATS-011"],
  "operation": "replace_run_text",
  "anchor": { "paragraph_key": "exp.aws.bullet.3", "match_text": "QuickSuite" },
  "new_text": "Amazon Q",
  "notes": "Merged spelling + ATS keyword finding into one edit."
}
```

`operation` is a small closed vocabulary the editor engine implements:

- `replace_run_text` — replace a substring within a paragraph's runs, preserving run formatting.
- `replace_paragraph_text` — replace an entire paragraph's text.
- `insert_paragraph_after` / `insert_paragraph_before` — add a paragraph relative to an anchor, copying style from the anchor.
- `delete_paragraph` — remove a paragraph (used by length reduction).
- `set_paragraph_style` — change the named style (e.g., fix an orphaned heading).
- `replace_bullet_list` — replace a contiguous run of list items under an anchor.

Keeping the operation set small and explicit makes the editor script deterministic and testable, and keeps the LLM's job at edit time to "fill in parameters", not "invent docx manipulation". Anything a reviewer wants that does not map to an operation is expressed as `replace_paragraph_text` with the full new text.

### resume_state.md (per agent) [R14.2]

```
---
status: IN_PROGRESS            # IN_PROGRESS | COMPLETED | BLOCKED_ON_CLARIFICATION | FATAL
agent: cv-editor
timestamp: 2026-05-29T10:14:02Z
input_hash: 7f3a9c2e1b04        # stable hash of this invocation's inputs
current_step: apply_change_list # agent-specific step marker
iteration: 1
---
# free-form notes / progress log
```

### workflow_state.md (orchestrator) [R14.5]

```
---
status: IN_PROGRESS
timestamp: 2026-05-29T10:13:55Z
run_id: 2026-05-29T10-13-55Z
iteration: 1
phase: REVIEW                   # NORMALIZE | REVIEW | QA | EDIT | EVALUATE | TERMINATING
reviewer_queue: [cv-ats-reviewer, cv-hiring-manager-reviewer]   # remaining this iteration
pending_change_list: change_list/iteration-1.json
jd_questions_outstanding: 2
page_limits: { cv: 2, letter: 1 }
gate_status:
  cv-spell-format-reviewer: PASS
  cv-language-content-reviewer: PASS
  cv-jd-alignment-reviewer: PENDING
  cv-ats-reviewer: PENDING
  cv-hiring-manager-reviewer: PENDING
---
```

## Input Normalization Layer

Every input is converted to `Normalized_Text` before reviewers run [R1.10]. This gives reviewers a uniform plain-text surface and decouples them from binary parsing.

| Input | Source formats | Tool | Output |
|-------|----------------|------|--------|
| CV | `.docx` | `docx_normalize.py` (python-docx) | `cv.normalized.md` + `cv.anchors.json` |
| Letter | `.docx` | `docx_normalize.py` | `letter.normalized.md` + `letter.anchors.json` |
| Job description | html, txt, pdf, docx, md | `input_normalize.py` | `jd.normalized.md` |
| Database | docx, md, txt, pdf | `input_normalize.py` | `database.normalized.md` |

`input_normalize.py` dispatches by extension:

- `.docx` → python-docx text extraction.
- `.pdf` → `pdfminer.six` text extraction (already a common, maintained dependency; chosen over heavier OCR stacks because job descriptions and databases are digital text, not scans).
- `.html` → strip tags via `BeautifulSoup` (`bs4`), collapse whitespace (the notebook explicitly tolerates messy whitespace).
- `.md` / `.txt` → passthrough with light whitespace normalization.

Normalization is deterministic and runs via the same script-in-tmp + shell pattern used by the editor, executed by the orchestrator during the `NORMALIZE` phase. The orchestrator owns normalization (rather than a dedicated agent) because it is a precondition for all reviewers and has no reasoning component.

Dependency policy: scripts assume their libraries are already installed in the Python environment. Agents must not run `pip install` [R15.5]. If a required library is missing, the script exits non-zero with a clear message naming the missing package; the orchestrator surfaces this as a FATAL setup error telling the user which packages to install. This keeps host-mutation out of the agents while still giving the user an actionable message.

## Page-Counting Layer [R11, D-4]

### Why not python-docx

Research finding: a `.docx` does not store soft (rendered) page breaks. Word computes them at layout time based on fonts, margins, and the rendering engine; `python-docx` has no rendering function and cannot report page count reliably ([python-docx pagebreak module notes](https://python-docx.readthedocs.io/en/stable/_modules/docx/text/pagebreak.html); [StackOverflow: soft page breaks are not reliably determinable](https://stackoverflow.com/questions/23980268/find-a-new-page-in-a-word-document)). Content was rephrased for compliance with licensing restrictions. Counting hard page breaks only would massively undercount and is unacceptable for a hard convergence gate.

### Mechanism: render then count

`page_count.py`:

1. Convert the Working Copy `.docx` to PDF (or compute statistics directly) using Microsoft Word automation, the primary engine on the target Windows environment: `win32com.client.Dispatch("Word.Application")`, open the document, **call `Document.Repaginate()` and allow background pagination to settle** before reading `ComputeStatistics(wdStatisticPages)` (`wdStatisticPages = 2`), then close without saving. The repagination step is required because Word can otherwise return a stale or background-computed page count; since the count is a hard convergence gate [R11.6, Property 7], the script forces a fresh pagination and reads the value only after it stabilizes. Word is the authoritative renderer here because the candidate uses Word for downstream manual edits, so the page count the workflow gates on matches exactly what the candidate will see when they open the document [D-11]. (Reference recipe: the canonical win32com page-count approach calls `Repaginate()` before `ComputeStatistics`.)
2. Print a JSON line `{"document": "...", "pages": N, "method": "word-com"}` and write it to `page_counts.json`.

Fallbacks and robustness:

- If Word automation is unavailable, the script falls back to a headless LibreOffice conversion: `soffice --headless --convert-to pdf --outdir <tmp> <docx>`, then counts PDF pages with `pypdf`. This path reports `"method": "libreoffice+pypdf"`.
- If neither renderer is available, `page_count.py` exits non-zero with a clear message. The orchestrator treats "cannot measure pages" as a FATAL setup error rather than guessing, because the page constraint is a hard gate [R11.6] and a wrong guess could silently pass an over-length CV.

A calibrated character/line heuristic was considered and rejected for the gate: it is not reliable enough to hard-fail on. It may be referenced in the termination report as a sanity hint only.

### Page-counting ownership

Page counting is invoked by the orchestrator after each editor pass [R11.4]. It is a deterministic script, not a reasoning task, so it does not warrant its own agent. (Requirement R11.7 permits a dedicated subagent; we choose not to, to minimize agent count and subagent-spawn overhead. This is recorded as a design decision, reversible later.)

## Edit-Application Layer [R3]

### The editor engine: `docx_edit.py`

A single reusable script consumes a Change_List JSON and a target `.docx`, applies operations, and writes the result in place (after the orchestrator has already snapshotted a backup). Design choices:

- **Run-formatting preservation.** `replace_run_text` locates the run(s) spanning the matched substring and edits text while leaving run properties (bold, hyperlink, font) intact wherever the match lies fully within a single run. When a match spans multiple runs with differing formatting, the engine replaces the affected runs with a single run that inherits the formatting of the first matched run and records a `formatting_normalized: true` note in the result so the language reviewer can catch any unwanted flattening next pass.
- **Idempotency.** Before applying `replace_run_text`, the engine checks whether `new_text` is already present and `match_text` absent; if so it marks the entry `already_satisfied` (counts as applied) instead of re-editing. This is the first line of defense against oscillation [R10.3].
- **Anchor re-resolution.** The engine recomputes paragraph keys against the live document at the start of each run (see anchor model), so multiple operations in one Change_List remain correct as the document changes.
- **Verification.** After applying all entries, the engine re-reads the document, recomputes the text at each anchor, and emits `iteration-<n>.result.json` with per-entry `verified | failed_to_apply | already_satisfied | formatting_normalized` [R3.5, R3.6].

The editor agent writes a thin wrapper script under `tmp/cv-editor/<iso>/apply_changes.py` that imports/embeds the engine and points it at the right paths, then runs it via `shell`. The wrapper and the engine's stdout/stderr are archived to the editor's `Per_Agent_State_Directory` [R3.9].

### Backups [R3.4, D-2]

The orchestrator (not the editor) copies each Working Copy to `backups/<name>.<iso>.bak.docx` immediately before invoking the editor. Rationale: the orchestrator owns the iteration boundary, so it is the natural place to snapshot. These backups are for in-run rollback if an edit pass corrupts the document; cross-run history is the candidate's git responsibility. No backups of the Bullet_Point_Database are made [R13.6].

## Reviewer Findings, Conflicts, and Convergence Layer

### Per-iteration control flow (orchestrator)

```
NORMALIZE (iteration 0 only): build Normalized_Text + anchors; snapshot working copies
loop iteration n = 1..10:
  phase REVIEW:
    for reviewer in [cv-spell-format-reviewer, cv-language-content-reviewer,
                     cv-jd-alignment-reviewer(Phase1), cv-ats-reviewer, cv-hiring-manager-reviewer]:
       spawn reviewer subagent (by canonical name); it writes findings/<canonical-name>/iteration-n.json; returns summary
  phase QA (only if cv-jd-alignment-reviewer Phase1 emitted pending_questions):
    while pending_questions remain:
       orchestrator asks ONE question to the user; records answer
    spawn cv-jd-alignment-reviewer(Phase2) subagent; it finalizes findings + writes accepted_gaps + DB/sidecar
    (Phase1/Phase2 may repeat if Phase2 surfaces new questions) [R6.5]
  phase EDIT:
    orchestrator builds change_list/iteration-n.json from all open findings (dedup + conflict rules)
    if change_list empty:
        # a fresh REVIEW found nothing to change. Confirm the global predicate:
        if all gates PASS AND all pages within limits AND cv-hiring-manager-reviewer=INVITE:
            -> TERMINATING(success)   # success is declared ONLY here, on a zero-new-findings REVIEW
        else:
            -> advance to next iteration's REVIEW   # e.g. pages still over, or a gate still failing
    snapshot backups; spawn cv-editor subagent with change_list; collect result.json
  phase EVALUATE:
    run page_count.py for each working copy
    if any document over its page limit:
        derive length-reduction findings (category=length) -> they feed next iteration's change_list
    record applied/failed results and current page counts in iteration_log.md
    # EVALUATE never declares success: edits made this iteration have not been re-reviewed yet.
    # Always advance to the next iteration's REVIEW so the edited state is re-reviewed.
    -> advance to next iteration's REVIEW
  detect oscillation; if a finding oscillates 3x -> mark wont_fix with rationale
TERMINATING:
  write termination_report.md; set workflow_state COMPLETED or DID_NOT_CONVERGE
```

Note on gate re-evaluation: a reviewer's gate for iteration `n` is computed from the findings it produced in iteration `n` *after* the editor pass of iteration `n`. Because reviewers run at the *start* of an iteration and the editor runs in the *middle*, a gate truly "passes" only when a subsequent iteration's reviewer pass produces no open findings. There is exactly one success-termination path: the EDIT phase's empty-change_list branch, which is reached only when the iteration's REVIEW produced zero new open findings across all reviewers AND the page constraints hold AND the hiring manager (from that same fresh REVIEW) recommends INVITE. The EVALUATE phase never declares success — it has just applied edits that have not yet been re-reviewed, so it always advances to the next iteration's REVIEW. This guarantees the final, COMPLETED state was actually re-reviewed, not merely edited, consistent with Property 6.

### Deduplication

Within an iteration, Findings are deduplicated by the tuple `(target_document, anchor.paragraph_key, category, normalized(proposed))`. Identical proposals from two agents collapse into one Change_List entry whose `implements_findings` lists both IDs (e.g., a spelling fix that is also an ATS keyword fix).

### Conflict resolution [R9.4]

When two Findings target the same anchor with incompatible `proposed` values:

Default priority order (highest wins):
1. `ats` with `severity: blocking` (an ATS-unreadable document fails before humans read it).
2. `hiring_manager_concern` with `severity: blocking | high`.
3. `jd_gap` (alignment to the target role).
4. `spelling` / `formatting` (correctness).
5. `language` (stylistic preference).
6. `length` (reduction) — applied last, and never deletes content that resolves a higher-priority finding.

The orchestrator records each conflict and its resolution in `iteration_log.md`. If the loser is `severity: blocking`, the orchestrator does not silently drop it; it records an explicit note and, where possible, seeks a synthesis edit (e.g., reword to satisfy both) by emitting a `replace_paragraph_text` operation that the next reviewer pass will validate.

### Oscillation handling [R10.3, R10.4]

A Finding is "the same" across iterations when `(target_document, anchor.paragraph_key, category, normalized(proposed))` repeats after having been marked `applied`. On the 2nd consecutive recurrence the orchestrator applies the alternate conflict resolution (reverse the two contending agents' priority for that anchor only). On the 3rd consecutive recurrence it marks the Finding `wont_fix` with a logged rationale and excludes it from gate evaluation, allowing the loop to progress. This bounds the loop independently of the iteration cap.

### Convergence and termination [R10.1, R10.2]

Success requires, simultaneously: every reviewer gate PASS (no open non-accepted-gap, non-wont_fix findings), every Working Copy within its page limit, and hiring manager = INVITE. Reaching iteration 10 without this yields `DID_NOT_CONVERGE`, and the termination report lists the still-open findings, the accepted gaps, and the current page counts so the candidate can finish manually.

## JD Alignment Two-Phase Q&A Layer [R6, D-9]

### Phase 1 (Analysis) — non-interactive subagent

Input: CV/letter working copies, normalized JD, normalized database (+ any prior in-place DB additions). Output:

- `findings/cv-jd-alignment-reviewer/iteration-n.json` with all Findings that need no user input (including database-sourced fill-ins).
- `jd_alignment/pending_questions.json`: an ordered list of questions for gaps that are neither in the CV nor the database.

```json
{
  "iteration": 1,
  "questions": [
    {
      "qid": "Q1",
      "missing_skill": "Kubernetes security at scale",
      "jd_evidence": "‘securing complex cloud environments (Kubernetes, AWS/GCP)’",
      "question": "The current material doesn't show Kubernetes security experience. Do you have an example (a project, incident, or responsibility) that demonstrates it?",
      "status": "unanswered"
    }
  ]
}
```

Phase 1 returns a `summary` to the orchestrator stating how many questions are pending. The subagent never prompts the user itself (it is non-interactive) [R6.4].

### Orchestrator-mediated Q&A — one question at a time [R2.13, R6.6]

The orchestrator reads `pending_questions.json` and, for each `unanswered` question in order: presents exactly one question to the candidate, waits, writes the verbatim answer into `jd_alignment/answered_questions.json` (marking that question `answered`), and only then moves to the next. This serialization is also what makes the QA phase resumable: on restart the orchestrator replays from the first still-`unanswered` question.

### Phase 2 (Integration) — non-interactive subagent

Input: the answered questions plus all prior context. Behavior:

- For answers that supply evidence: produce fill-in Findings (`category: jd_gap`) whose `proposed` content integrates the candidate's evidence into the CV/letter, and append the new material to the database (in place if text-based, else sidecar) with provenance [R6.7, R13].
- For answers that decline ("I don't have that"): record the Finding as `accepted_gap` in `accepted_gaps.md` with the verbatim response [R6.8, R12.2].

Repeatability [R6.5]: if integrating an answer reveals a follow-up gap (e.g., the candidate's answer implies a related skill worth surfacing), Phase 2 may write new entries back into `pending_questions.json` with `status: unanswered`. The orchestrator detects outstanding questions and re-enters the Q&A loop, then re-runs Phase 2. This Phase1→QA→Phase2 cycle repeats within the iteration until no questions remain, bounded overall by the 10-iteration workflow cap.

### Database writeback rules [R13]

```
provided database format:
  .md or .txt   -> append in place to the user's file, preserving structure;
                   provenance as HTML-style comments (md) or bracketed notes (txt)
  .docx or .pdf -> do NOT modify; append to database_sidecar.md instead
no database     -> create/append database_sidecar.md
```

Provenance block appended with each entry:

```markdown
<!-- cv-customizer: iteration=1 finding=JD-014 qid=Q1
     question="...verbatim..." answered="2026-05-29T10:31Z" -->
- Led Kubernetes security hardening for a 200-node EKS fleet: ...
```

The termination report lists every in-place DB modification and the sidecar location [R13.5].

## ATS Layer [R7, D-6]

Hybrid: deterministic structural checks via Python, keyword matching via the LLM.

- **Structural checks — `ats_structural.py`** (run via tmp-script + shell, like the editor [R7.4]). Uses `python-docx` to inspect the `.docx` and flag ATS hazards that are objectively detectable from the document XML: text boxes (`w:txbxContent`), images/drawings carrying text, multi-column section properties (`w:cols w:num>1`), content in headers/footers, tables used for layout, unusual section heading styles, and non-standard Unicode that commonly breaks naive parsers. Emits candidate Findings as JSON the agent then adopts.
- **Keyword matching — LLM.** The agent compares the JD's required terms against the CV/letter text (from Normalized_Text) and flags missing high-value keywords as `category: ats` Findings, deferring to the JD Alignment Reviewer when a gap is substantive (a true missing skill) rather than merely a missing keyword for an existing skill.

Library choice: `python-docx` is the only hard dependency for structural checks (already needed by the editor). General-purpose third-party "ATS scorers" on PyPI (e.g., `ats-resume-scorer`, `simple-ats`) were evaluated and not adopted as dependencies: their scoring heuristics are opaque and would add maintenance surface and supply-chain risk for marginal benefit over targeted python-docx checks plus LLM keyword analysis. They may be revisited if structural coverage proves insufficient.

## Tooling and Permissions Layer [R15]

### Per-agent tool matrix

| Agent (canonical name) | tools | write scope | shell allowed | subagent |
|-------|-------|-------------|---------------|----------|
| `cv-orchestrator` | `read`, `write`, `shell`, `subagent` | `Workflow_State_Directory/**`, own state dir, `working/**`, `backups/**` (snapshots only) | `python <install>/shared/scripts/page_count.py ...` (drives Word COM, or `soffice` fallback), `python <install>/shared/scripts/input_normalize.py ...`, `python <install>/shared/scripts/docx_normalize.py ...` | yes |
| `cv-editor` | `read`, `write`, `shell` | `tmp/cv-editor/**`, `Workflow_State_Directory/**`, `working/**` | `python tmp/cv-editor/.*/apply_changes\.py .*` | no |
| `cv-spell-format-reviewer` | `read`, `write` | own state dir + `findings/cv-spell-format-reviewer/**` | (none) | no |
| `cv-language-content-reviewer` | `read`, `write` | own state dir + `findings/cv-language-content-reviewer/**` | (none) | no |
| `cv-jd-alignment-reviewer` | `read`, `write` | own state dir, `findings/cv-jd-alignment-reviewer/**`, `jd_alignment/**`, `accepted_gaps.md`, `database_sidecar.md`, user DB iff `.md`/`.txt` | (none) | no |
| `cv-ats-reviewer` | `read`, `write`, `shell` | own state dir, `findings/cv-ats-reviewer/**`, `tmp/cv-ats-reviewer/**` | `python tmp/cv-ats-reviewer/.*/ats_checks\.py .*` | no |
| `cv-hiring-manager-reviewer` | `read`, `write` | own state dir + `findings/cv-hiring-manager-reviewer/**` | (none) | no |

Notes:

- The three pure reviewers (`cv-spell-format-reviewer`, `cv-language-content-reviewer`, `cv-hiring-manager-reviewer`) have `write` *only* to enable persisting Findings; `toolsSettings.write.allowedPaths` restricts each to its own `findings/<canonical-name>/` subtree and its own state dir [R15.3]. This is read-only with respect to documents and shared state, with a tightly scoped exception for the agent's own findings file (audit/resumability, R9.2, R14). Confirmed in "Resolved Design Decisions" #1.
- `<install>` denotes the fixed installed root (`.kiro/cv-suite/` for workspace install, `~/.kiro/cv-suite/` for global). The installer rewrites these to absolute paths in each agent's `allowedCommands` [R16.7, R16.10, D-12].
- Every `write`-capable agent sets `toolsSettings.write.allowedPaths` to its scope; every `shell`-capable agent sets `allowedCommands`/`deniedCommands` [R15.3, R15.4].
- Global denied commands for all shell-capable agents: `pip install .*`, `npm .*`, `git .*`, `rm .*`/`del .*`/`rmdir .*` outside the agent's tmp dir, `curl .*`, `wget .*` [R15.5, R15.6].
- No agent reads environment variables; all paths arrive as script arguments or are read from `run_manifest.json` [R15.1].

### Orchestrator subagent configuration [R2.2, R2.3, R15.2]

```json
{
  "name": "cv-orchestrator",
  "tools": ["read", "write", "shell", "subagent"],
  "toolsSettings": {
    "subagent": {
      "availableAgents": [
        "cv-editor",
        "cv-spell-format-reviewer",
        "cv-language-content-reviewer",
        "cv-jd-alignment-reviewer",
        "cv-ats-reviewer",
        "cv-hiring-manager-reviewer"
      ],
      "trustedAgents": [
        "cv-editor",
        "cv-spell-format-reviewer",
        "cv-language-content-reviewer",
        "cv-jd-alignment-reviewer",
        "cv-ats-reviewer",
        "cv-hiring-manager-reviewer"
      ]
    }
  }
}
```

The `name` field is set explicitly (not derived from the filename) so the orchestrator and the installed `.kiro/agents/cv-orchestrator.json` agree. Each `availableAgents`/`trustedAgents` entry is byte-identical to the corresponding delegate's `name` field and its installed `.kiro/agents/<canonical-name>.json` basename [A2, B2].

`trustedAgents` ensures the orchestrator can spawn each delegate without per-call approval prompts, which is required because the orchestrator is the only interactive surface and we do not want spawn-time prompts interrupting the loop. The delegates' own `allowedTools` still govern what each can do once running.

## Invocation and Run Manifest

The candidate starts the workflow by selecting the orchestrator agent (`kiro-cli --agent cv-orchestrator`) and providing inputs in the first message, e.g.:

```
Tailor my CV for this job.
CV: ./inputs/MyCV.docx
JD: ./inputs/job.html
Letter: ./inputs/cover.docx          (optional)
Database: ./inputs/extensive_cv.md   (optional)
CV page limit: 2                     (optional override)
```

The orchestrator parses these into `run_manifest.json` (absolute-resolved, workspace-relative paths; never from env vars [R15.1]) and validates existence of mandatory inputs, failing fast with a precise message if any is missing [R1.6]. The manifest records input hashes for resumability [R14.2] and any page-limit overrides [R11.3].

## Components and Interfaces

This section specifies each of the seven agents as a component: its responsibility, its inputs and outputs (the interface, expressed as files it reads and writes plus the `summary` it returns to its caller), and the behavioral contract it must uphold. All components share the data models, state layout, and layers defined above.

### Component 1: CV Orchestrator Agent

**Responsibility:** Own the workflow — parse inputs, normalize, run the iteration loop, spawn delegates, mediate JD questions one at a time, evaluate convergence, write the termination report. [R2]

**Interface:**
- Reads: the user's first message; `run_manifest.json`; all `findings/**`; `change_list/**/*.result.json`; `jd_alignment/pending_questions.json`; `page_counts.json`; `workflow_state.md`.
- Writes: `run_manifest.json`, `workflow_state.md`, `iteration_log.md`, `inputs/**` (via normalization scripts), `working/**` and `backups/**` (snapshots only), `change_list/iteration-<n>.json`, `answered_questions.json`, `termination_report.md`, own `resume_state.md`.
- Spawns (subagent): all six delegates, per `availableAgents`/`trustedAgents`.
- Returns to user: progress narration and, during QA, exactly one question at a time.

**Contract:** never writes the Working Copies' content (only byte-copies them to `backups/`); is the only interactive surface; enforces the convergence predicate (Property 6) and the one-question-at-a-time rule (Property 8); caps at 10 iterations.

### Component 2: CV Editor Agent

**Responsibility:** Apply a Change_List to the targeted Working Copy via a generated Python script, then verify. Sole writer of document content. [R3]

**Interface:**
- Reads: `change_list/iteration-<n>.json`; `working/<doc>.docx`; `inputs/<doc>.anchors.json`.
- Writes: `working/<doc>.docx` (in place); `change_list/iteration-<n>.result.json`; archived scripts + stdout/stderr under its state dir; own `resume_state.md`.
- Shell: `python tmp/cv-editor/<iso>/apply_changes.py ...` only.
- Returns: a summary of applied/failed/already-satisfied counts.

**Contract:** writes only within `working/**`, `Workflow_State_Directory/**`, `tmp/cv-editor/**`; preserves run formatting; idempotent; reports `failed_to_apply` rather than mis-editing (Property 9); spawns no agents.

### Component 3: Spell and Formatting Reviewer Agent

**Responsibility:** Flag spelling, grammar, punctuation, capitalization, tense/date/number consistency, and visible formatting defects across CV and letter, without the JD. LLM-only analysis. [R4]

**Interface:**
- Reads: `inputs/cv.normalized.md` (+ letter), and/or the `.docx` directly; `inputs/*.anchors.json`.
- Writes: `findings/cv-spell-format-reviewer/iteration-<n>.json`; own `resume_state.md`.
- Returns: a summary with per-document open-finding counts (the gate signal).

**Contract:** no document writes; write scope limited to its findings dir + state dir; Findings conform to schema (Property 3); gate passes when it emits zero open findings.

### Component 4: Language and Content Reviewer Agent

**Responsibility:** Critique prose in isolation from the JD — weak verbs, vague/unquantified claims, redundancy, passive voice, parallelism, summary quality, and cover-letter structure. Also services length-reduction requests (`category: length`) when the orchestrator asks during the EVALUATE phase. LLM-only. [R5, R11.5]

**Interface:**
- Reads: `inputs/cv.normalized.md` (+ letter); optionally a length-reduction directive from the orchestrator (passed in the spawn task and via `workflow_state.md`).
- Writes: `findings/cv-language-content-reviewer/iteration-<n>.json`; own `resume_state.md`.
- Returns: per-document open-finding counts.

**Contract:** as Component 3; additionally, length-reduction findings must preserve content that resolves higher-priority findings (conflict priority places `length` last).

### Component 5: JD Alignment Reviewer Agent (two-phase)

**Responsibility:** Compare the package to the JD; fill gaps from the database; emit clarifying questions for true gaps; integrate answers; record accepted gaps; write DB/sidecar. [R6, R13]

**Interface (Phase 1 / Analysis):**
- Reads: `inputs/cv.normalized.md` (+ letter), `inputs/jd.normalized.md`, `inputs/database.normalized.md` and any prior in-place DB additions.
- Writes: `findings/cv-jd-alignment-reviewer/iteration-<n>.json` (input-free findings); `jd_alignment/pending_questions.json`.
- Returns: count of pending questions.

**Interface (Phase 2 / Integration):**
- Reads: `jd_alignment/answered_questions.json` + all Phase 1 context.
- Writes: fill-in findings; `accepted_gaps.md`; in-place DB append (`.md`/`.txt`) or `database_sidecar.md`; may append new `pending_questions.json` entries to repeat the cycle.
- Returns: counts of fill-ins, accepted gaps, and any new pending questions.

**Contract:** never writes Working Copies; never prompts the user directly (non-interactive); writes only to its findings dir, `jd_alignment/**`, `accepted_gaps.md`, `database_sidecar.md`, and the user DB iff `.md`/`.txt`; preserves provenance (Property 5, R13.4).

### Component 6: ATS Reviewer Agent

**Responsibility:** Flag ATS-incompatibility (structural hazards via deterministic Python; missing keywords via LLM). [R7]

**Interface:**
- Reads: `working/<doc>.docx` (structural), `inputs/*.normalized.md` + `inputs/jd.normalized.md` (keywords).
- Writes: `findings/cv-ats-reviewer/iteration-<n>.json`; archived `ats_checks.py` + logs under its state dir; own `resume_state.md`.
- Shell: `python tmp/cv-ats-reviewer/<iso>/ats_checks.py ...` only.
- Returns: per-document open-finding counts.

**Contract:** no document writes; structural checks come from `ats_structural.py` (python-docx); defers true skill gaps to JD Alignment; gate passes at zero open findings.

### Component 7: Hiring Manager Reviewer Agent

**Responsibility:** Critically review the whole package against the JD; emit strengths, concern Findings, and an `INVITE`/`DO_NOT_INVITE` recommendation; assess CV↔letter coherence. [R8]

**Interface:**
- Reads: `inputs/cv.normalized.md` (+ letter), `inputs/jd.normalized.md`, `accepted_gaps.md`.
- Writes: `findings/cv-hiring-manager-reviewer/iteration-<n>.json` (concerns + a recommendation record); own `resume_state.md`.
- Returns: the recommendation and open-concern counts.

**Contract:** no document writes; no user questions; its gate (INVITE + no open concerns) is necessary but not sufficient for convergence — every other gate must independently pass (Property 6, R8.6).

### Shared Python utilities (not agents)

`docx_normalize.py`, `input_normalize.py`, `page_count.py`, `docx_edit.py`, `ats_structural.py` under `cli-agents/cv/shared/scripts/`. These are deterministic libraries invoked via the script-in-tmp + shell pattern. They carry the testable core of the system (see Testing Strategy) and are owned by no single agent: the orchestrator invokes the normalization and page-count scripts; the editor invokes the edit engine; the ATS reviewer invokes the structural checker.

## Correctness Properties

*A property is a characteristic that should hold across all valid executions. Properties bridge the human-readable requirements and verifiable checks.*

### Reflection on redundant and non-testable criteria

The acceptance criteria contain expected redundancy (e.g., each reviewer restates "shall not modify any Working Copy" and "gate passes when no open findings remain"). These collapse into a few cross-cutting properties about write-isolation and gate semantics. Criteria that are environmental (subagent platform behavior) or subjective (quality of LLM language suggestions) are not property-tested; they are covered by manual/integration testing.

### Property 1: Original inputs are immutable (except DB writeback)

For any execution, the byte contents of the CV_Document, Motivational_Letter, and Job_Description files at their user-provided paths are identical before and after the run. The Bullet_Point_Database may change only when its extension is `.md`/`.txt`, and only by append.
**Validates: Requirements 1.11, 3.1, 3.7, 13.1, 13.2, 13.6**

### Property 2: Single writer of Working Copies

For any execution, every modification to `working/cv.working.docx` or `working/letter.working.docx` is performed by the CV Editor Agent's script. No reviewer or orchestrator step writes those files (the orchestrator only copies them to `backups/`).
**Validates: Requirements 2.11, 3.1, 4.5, 5.5, 6.10, 7.6, 8.4**

### Property 3: Finding schema validity

For any Finding written by any reviewer, the JSON validates against `finding.schema.json`: all required fields present, each enum field within its domain, `target_document` consistent with whether a letter exists.
**Validates: Requirements 9.1, 4.3, 5.3, 6.2, 7.5, 8.3**

### Property 4: Change_List traceability

For any Change_List entry, `implements_findings` is non-empty and every referenced Finding ID exists in that iteration's findings; `target_document` matches the referenced Findings' target.
**Validates: Requirements 9.3**

### Property 5: Accepted-gap exclusion and persistence

For any Finding with `status: accepted_gap`, it appears in `accepted_gaps.md` with a verbatim candidate response, and it is excluded from every subsequent gate evaluation and never re-emitted as an open question.
**Validates: Requirements 6.8, 10.5, 12.1, 12.2, 12.3**

### Property 6: Convergence predicate

The run terminates with `COMPLETED` only when, in a REVIEW phase, all reviewer gates are PASS, all Working Copies are within their page limits, and the hiring manager recommendation is INVITE; otherwise it terminates `DID_NOT_CONVERGE` at iteration 10.
**Validates: Requirements 2.9, 2.10, 8.6, 10.1, 10.2, 11.6**

### Property 7: Page limit is a hard gate

For any execution that terminates `COMPLETED`, the last measured page count of each Working Copy is ≤ its (possibly overridden) limit, and that count was produced by the render-based `page_count.py`, not a heuristic.
**Validates: Requirements 11.2, 11.3, 11.4, 11.6**

### Property 8: One question at a time

During the QA phase, the orchestrator never presents question `k+1` before an answer to question `k` has been recorded in `answered_questions.json`.
**Validates: Requirements 2.13, 6.6**

### Property 9: Anchor-safe editing

For any Change_List entry the editor reports `verified`, the post-edit text at the resolved anchor equals the entry's intended result; for any entry whose anchor cannot be resolved, the editor reports `failed_to_apply` and does not modify a different paragraph.
**Validates: Requirements 3.5, 3.6**

### Property 10: Permission containment

For any agent, every file it writes lies within that agent's declared `allowedPaths`, and every shell command it runs matches its `allowedCommands` and none of `deniedCommands`; no agent reads environment variables.
**Validates: Requirements 15.1, 15.3, 15.4, 15.5, 15.6, 15.7**

## Error Handling

- **Missing mandatory input** → orchestrator emits a FATAL termination report naming the input; no state mutated beyond the report [R1.6].
- **Missing Python library / renderer** → the failing script exits non-zero with the package name; orchestrator reports FATAL setup error with remediation (install X), without attempting installation [R15.5].
- **Editor `failed_to_apply`** → recorded in `result.json` and `iteration_log.md`; the originating Finding stays `open`; if it fails to apply across iterations it falls into the oscillation/`wont_fix` path rather than blocking forever [R3.6, R10.4].
- **Subagent returns without writing its findings file** → orchestrator treats the reviewer as FAILED for that iteration, logs it, and retries once; a second failure marks the run `DID_NOT_CONVERGE` with the reason, so a silently broken reviewer cannot be mistaken for a passing gate.
- **Page measurement fails mid-run** → FATAL (cannot honor a hard gate without a trustworthy count) [R11.6].
- **Interruption** → on next launch the orchestrator reads `workflow_state.md`; if `IN_PROGRESS` with a matching input hash it resumes at the recorded `phase`/`reviewer_queue`/`jd_questions_outstanding`; otherwise it archives and restarts [R14.3–R14.5].

## Testing Strategy

### Unit tests (the shared Python scripts)

These scripts are deterministic and are the highest-value test target.

- `docx_normalize.py`: stable paragraph keys are stable across edits; duplicate paragraphs get distinct ordinals; anchors round-trip.
- `docx_edit.py`: each operation type on fixture docs; run-formatting preserved on intra-run replacement; `already_satisfied` idempotency; `failed_to_apply` on unresolved anchors; verification output correctness.
- `input_normalize.py`: docx/pdf/html/md/txt each normalize to expected text; messy HTML whitespace collapses.
- `page_count.py`: a known 2-page fixture reports 2; a 3-page fixture reports 3; renderer-absent path exits non-zero with a clear message (test via monkeypatched COM dispatch / PATH). NOTE: the monkeypatched tests validate the script's control flow and error handling only — they do NOT validate the real page count, because that depends on Word (or LibreOffice) actually rendering. The render-based count's correctness is therefore validated separately by a **calibrated-fixture check that must be run on the target Windows host with Word installed** (see Integration / manual tests). The hard page gate is never assumed correct from monkeypatched tests alone [C4].
- `ats_structural.py`: fixtures containing a text box, a 2-column section, header content, and a layout table each produce the expected Findings.

Test framework: `pytest`. Per the workspace steering rule (`tests-must-not-fail`), any failing test is fixed at the source, never skipped or xfail'd.

### Schema/property tests

- Validate every emitted Finding and Change_List against the JSON schemas (Properties 3, 4).
- A harness that runs the orchestrator logic over recorded fixture findings to assert the convergence predicate, dedup, conflict priority, oscillation→wont_fix, and one-question-at-a-time ordering (Properties 5, 6, 8, 9). These exercise orchestrator *logic* with stubbed subagents, since spawning real subagents is not unit-testable.

### Integration / manual tests

- **Calibrated page-count check (target Windows host, Word installed).** Render `cli-agents/cv/tests/fixtures/` documents of known length (1-, 2-, and 3-page calibrated fixtures) through the real `page_count.py` Word path and assert the reported counts match. This is the only check that validates the hard page gate's true correctness; it must run on a host with Word (or, for the fallback path, LibreOffice) actually installed [C4].
- End-to-end smoke run on a **versioned** fixture pair under `cli-agents/cv/tests/fixtures/` (a small fixture CV `.docx` plus a fixture JD `.txt`), asserting: a tailored two-page CV is produced, the accepted-gaps register is honored, and the database sidecar/writeback behaves per format. The fixtures are committed to the repository, not derived from the gitignored `tmp/` sample [D3].
- Manual verification inside Kiro CLI that the installed orchestrator (`.kiro/agents/cv-orchestrator.json`) can actually spawn each delegate by canonical name as a trusted subagent and that non-interactive reviewers do not attempt to prompt.

### Cleanup

Temporary files under `tmp/<agent>/<iso>/` are archived to per-agent state for audit, then the `tmp/<agent>/` working scratch is cleared at successful termination. Backups under `Workflow_State_Directory/backups/` are retained for the run and removed only when the user discards the run state.

## Resolved Design Decisions

The following decisions were confirmed during design review and are now binding.

1. **Reviewer write-scope nuance (Property 2 / R15.3) — CONFIRMED.** Requirement 15.3's "reviewer agents shall be read-only" is implemented as read-only *with respect to documents and shared state*, with a tightly scoped exception: the `cv-spell-format-reviewer`, `cv-language-content-reviewer`, and `cv-hiring-manager-reviewer` receive a narrow `write` limited to their own `findings/<canonical-name>/` directory (and their own state dir), so Findings persist for audit and resumability [R9.2, R14]. They never write Working Copies or any other agent's state.
2. **No dedicated page-count agent (R11.7) — CONFIRMED.** Page counting is an orchestrator-invoked deterministic script (`page_count.py`), not a subagent. This keeps the agent count at seven and avoids subagent-spawn overhead for a non-reasoning task.
3. **Renderer choice — CONFIRMED: Microsoft Word primary, LibreOffice fallback [D-11].** Word automation (`win32com`, `Repaginate()` then `ComputeStatistics(wdStatisticPages)`) is the primary page-count engine because the candidate uses Word for downstream manual edits; gating on Word's own pagination guarantees the measured page count matches what the candidate sees. LibreOffice headless conversion + `pypdf` is the fallback. If neither is available, the workflow fails fast (page count is a hard gate and must never be guessed).
4. **Agent installation and discovery [D-12] — RESOLVED (review iteration 01, A1/B1).** Agents are authored under `cli-agents/cv/` and installed by `install_agents.py` to a fixed root (`.kiro/cv-suite/` workspace, `~/.kiro/cv-suite/` global), with generated discovery configs in `.kiro/agents/<canonical-name>.json` whose `prompt` and shared-script references are rewritten to absolute installed paths. Kiro scans only `.kiro/agents/` and `~/.kiro/agents/`, so this is what makes name-based spawning work.
5. **Canonical agent names [D-13] — RESOLVED (review iteration 01, A2/B2).** Each agent has one canonical name (`cv-orchestrator`, `cv-editor`, `cv-spell-format-reviewer`, `cv-language-content-reviewer`, `cv-jd-alignment-reviewer`, `cv-ats-reviewer`, `cv-hiring-manager-reviewer`) used byte-identically in the `name` field, `availableAgents`/`trustedAgents`, state dir, findings dir, tmp dir, and `--agent` invocation. The `name` field is always set explicitly; filename-derived naming is never relied upon.
