# Spec Review Iteration 02

**Spec directory:** .kiro/specs/cv-customizer-agents/
**Reviewed files:** requirements.md, design.md, tasks.md, Discussion.md (context), review-iteration-01.md (recurrence basis)
**Iteration:** 02
**Verdict:** NOT-READY
**consecutive_clean_AB:** 1

## Verdict Rationale

The revision resolves every finding from iteration 01. All 11 prior items (A1, A2,
B1, B2, C1–C4, D1–D3) are addressed at the source, verified below against the
updated files and the Kiro documentation:

- A1/A2/B1/B2 (the install/discovery and canonical-naming blockers) are resolved by
  the new Requirement 16 (criteria 16.3–16.10), decisions D-12/D-13, the design
  "Installation and discovery" section, and the new `install_agents.py` task (task
  15). The orchestrator now spawns delegates by canonical name (`cv-editor`,
  `cv-spell-format-reviewer`, `cv-language-content-reviewer`,
  `cv-jd-alignment-reviewer`, `cv-ats-reviewer`, `cv-hiring-manager-reviewer`),
  each config sets `name` explicitly, and the installer places configs in
  `.kiro/agents/` with absolute `file://` prompt and shared-script paths. This
  matches the Kiro discovery model (config reference: agents are found only in
  `.kiro/agents/` or `~/.kiro/agents/`; explicit `name` overrides filename-derived
  naming). A grep across the spec confirms the old names (`cv-editor-agent`,
  `ats-reviewer-agent`) survive only in the historical Discussion.md and the
  iteration-01 review file, never in the current spec.
- B2 naming is now byte-consistent: state dir, findings dir, tmp dir, `name`, and
  `availableAgents`/`trustedAgents` all use the canonical name (R14.1 references
  R16.3; design state layout uses `cv-ats-reviewer/`, `tmp/cv-ats-reviewer/**`).
- C1 (R9.2 vs R15.3 contradiction) is resolved: R15.3 now grants the three pure
  reviewers a narrow findings-directory write, matching R9.2 and design Resolved
  Decision 1.
- C2 is resolved: `page_count.py` now calls `Document.Repaginate()` and lets
  pagination settle before reading `ComputeStatistics(wdStatisticPages)` (design
  page-count layer, Resolved Decision 3, task 4).
- C3 is resolved: R10.2 and the design execution-model section now state the
  10-cap is enforced by the orchestrator itself, not the platform.
- C4 is resolved: the testing strategy and task 18 add a calibrated page-count
  check on a Word-equipped host; task 4.1 is scoped to control flow only.
- D1 (`pdfmin.six`) is fixed to `pdfminer.six`. D2 (discussion-file extension) is
  fixed to `.txt` (R16.5, design layout, tasks). D3 (gitignored fixture) is fixed:
  fixtures now live in versioned `cli-agents/cv/tests/fixtures/`.

Because no A or B findings remain, `consecutive_clean_AB` increments from 0 to 1.
The verdict is NOT-READY only because two clarifications (C) and one nit (D) remain
and `consecutive_clean_AB` has not yet reached the 5-iteration threshold required
for READY. The spec is in strong shape; the remaining items are minor.

## A — Execution Blockers

None.

## B — User-Intent Deviations

None.

## C — Clarifications / Risks

### C1 — Two success-termination conditions conflict; EVALUATE can terminate on un-re-reviewed edits
**Evidence:**
- design "Per-iteration control flow" pseudocode, EDIT phase: "if change_list empty
  AND all gates already PASS AND pages OK -> go to TERMINATING(success)".
- Same pseudocode, EVALUATE phase (reached only when the change_list was non-empty
  and edits were applied): "recompute each reviewer gate status from latest findings
  + result.json + accepted_gaps. if all gates PASS AND all pages within limits AND
  cv-hiring-manager-reviewer=INVITE -> TERMINATING(success)".
- Property 6: the run "terminates with `COMPLETED` only when, **in a REVIEW phase**,
  all reviewer gates are PASS ...".
- Design prose (immediately after the pseudocode): "convergence is detected when an
  iteration's REVIEW phase yields zero new open findings ... This guarantees the
  final state was actually re-reviewed, not merely edited."

In the EVALUATE phase, gates are recomputed from the iteration's pre-edit findings
(now marked `applied`), and the hiring-manager `INVITE` is the pre-edit
recommendation. If those findings were all applied, the EVALUATE check can fire
`TERMINATING(success)` on a document that was edited but never re-reviewed —
contradicting both Property 6 ("in a REVIEW phase") and the design's own re-review
guarantee. The correct convergence path is the EDIT-phase empty-change_list branch
(a fresh REVIEW found nothing). Reconcile the two: remove or gate the EVALUATE
success-termination so that success is only declared on a zero-new-findings REVIEW
pass, and have EVALUATE otherwise fall through to the next iteration.

### C2 — Installer outputs carry machine-specific absolute paths but are not addressed by the gitignore/versioning guidance
**Evidence:**
- design install model (D-12, R16.10): the installer writes `.kiro/agents/
  <canonical-name>.json` with **absolute** `file://` prompt URIs and **absolute**
  shared-script paths, and copies the tree to `.kiro/cv-suite/` (or `~/.kiro/`).
- tasks task 1 gitignores only `.kiro/agent-state/`; design state section: git
  versioning "applies to inputs and to the `cli-agents/cv/` tree, not to
  agent-state." Neither `.kiro/agents/` nor `.kiro/cv-suite/` is mentioned.
- R16.9 requires the suite to be "self-contained": copy the authoring tree + run
  install → working suite.

The generated discovery configs and the installed `.kiro/cv-suite/` tree contain
absolute, host-specific paths and are install outputs, not source. The spec does
not say they should be excluded from version control. If a user commits
`.kiro/agents/cv-*.json` (absolute paths from one machine), a teammate who pulls
the repo gets a broken suite, undercutting the R16.9 portability intent. Specify
that the installer outputs (`.kiro/agents/cv-*.json`, `.kiro/cv-suite/`) are
gitignored / regenerated per machine, and that only the `cli-agents/cv/` authoring
tree is version-controlled.

## D — Minor Nits

### D1 — Install path/URI examples are POSIX-style on an explicitly Windows-only target
**Evidence:**
- System context: Windows. The page-count engine is Microsoft Word automation
  (`win32com`, `pywin32`) — the suite targets Windows as primary.
- design install examples use POSIX-style placeholders: `prompt` =
  `file://<abs>/.kiro/cv-suite/editor/prompt.md`; allowedCommands =
  `python <install>/shared/scripts/page_count.py ...`.

On Windows, absolute `file://` URIs are `file:///D:/.../prompt.md` and shell
`allowedCommands` patterns contain backslash paths (`python D:\...\page_count.py`)
that must be regex-escaped. The design leaves path formatting to the installer,
but the POSIX-style examples could mislead the implementer on a Windows-first
target. Add a note that `install_agents.py` emits Windows-correct `file://` URIs
and backslash-escaped `allowedCommands` patterns (while remaining cross-platform).

## Open Product Decisions

None. Both remaining items are technical specification fixes resolvable by Kiro in
spec mode without business/user input.

## Evidence Summary

- MCP lookups: 0 (no MCP servers exposed; external-technology facts were verified
  against first-party docs in iteration 01 and the revisions align with them).
- Web sources: 2 re-confirmed (Kiro subagents doc, Kiro config reference) for the
  install/discovery and canonical-name resolution; Word COM repagination recipe
  already verified in iteration 01.
- Codebase references: 6 (spec-wide grep confirming canonical-name consistency and
  no `pdfmin`/`.md`-discussion/old-tmp stragglers; design pseudocode vs Property 6;
  tasks gitignore scope; design install model; tasks installer; cli-agents `.txt`
  convention).
- Pattern-mining hits: 2 (installer-output portability vs the `cli-agents/`
  distribution-vs-runtime split; Windows path formatting vs POSIX examples).

## Handoff Instructions

For Kiro IDE spec mode — two clarifications and one nit; the spec is otherwise
implementation-ready:

1. (C1) In design's "Per-iteration control flow", reconcile the two
   success-termination conditions so that `COMPLETED` is declared only on a
   zero-new-findings REVIEW pass (the EDIT-phase empty-change_list branch). The
   EVALUATE phase should not terminate-success after applying edits; it should fall
   through to the next iteration's REVIEW. Align the pseudocode with Property 6 and
   the re-review guarantee.
2. (C2) State that the installer outputs — `.kiro/agents/cv-*.json` and
   `.kiro/cv-suite/` — are gitignored and regenerated per machine (only the
   `cli-agents/cv/` authoring tree is version-controlled). Add `.kiro/agents/` and
   `.kiro/cv-suite/` (or the specific generated files) to the task-1 gitignore step.
3. (D1) Add a one-line note that `install_agents.py` produces Windows-correct
   absolute `file://` URIs and backslash-escaped `shell.allowedCommands` patterns,
   since the target environment is Windows-first.
