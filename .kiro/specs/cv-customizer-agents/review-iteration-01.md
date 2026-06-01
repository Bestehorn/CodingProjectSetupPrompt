# Spec Review Iteration 01

**Spec directory:** .kiro/specs/cv-customizer-agents/
**Reviewed files:** requirements.md, design.md, tasks.md, Discussion.md (context)
**Iteration:** 01
**Verdict:** NOT-READY
**consecutive_clean_AB:** 0

## Verdict Rationale

The spec is detailed, internally cross-referenced, and the major external-technology
decisions hold up against first-party documentation: the Kiro subagent mechanism
(subagent tool, availableAgents/trustedAgents, max-4-concurrent, summary tool,
non-interactive fail-fast, review-loop cap of 10) is verified at
https://kiro.dev/docs/cli/chat/subagents/, and the primary page-count API
(`ComputeStatistics(wdStatisticPages)`, enum value 2) is verified at
https://learn.microsoft.com/en-us/office/vba/api/word.wdstatistic. The
orchestrator-driven loop (rather than the native review-loop construct) is the
correct choice given those docs.

However, two execution blockers prevent the suite from running as written. Both
concern the single mechanism the entire design depends on: the orchestrator
spawning six delegates **by name**. The configs are stored only in `cli-agents/cv/`,
which Kiro CLI does not scan for agents (it scans `.kiro/agents/` and
`~/.kiro/agents/` only), and no task installs them there; and the spawn names
(`cv-editor-agent`, ...) do not match the config filenames (`KiroCLIAgent-CVEditor.json`),
with no `name` field specified to bridge the gap. Per the Kiro config reference,
absent a `name` field the agent name is derived from the filename, so
`availableAgents`/`trustedAgents` would resolve to nothing. Because A_count > 0,
`consecutive_clean_AB` resets to 0 and the verdict is NOT-READY.

## A — Execution Blockers

### A1 — Agent configs are never installed into a Kiro-discoverable location
**Evidence:**
- design.md "Distribution layout" stores all seven configs under
  `cli-agents/cv/<agent>/KiroCLIAgent-*.json`.
- Kiro config reference (https://kiro.dev/docs/cli/custom-agents/configuration-reference/,
  "File locations"): custom agents are discovered **only** in `.kiro/agents/`
  (local) or `~/.kiro/agents/` (global). No other path is scanned.
- R2.2/R2.3/R15.2 and design "Orchestrator subagent configuration" require the
  orchestrator to spawn the six delegates **by name** via
  `toolsSettings.subagent.availableAgents`/`trustedAgents`; name resolution
  requires the configs to be discoverable.
- tasks.md contains no task that installs configs into `.kiro/agents/`. Task 15
  (README) only mentions "self-contained copy instructions" for copying
  `cli-agents/cv/` into another workspace. A grep for `.kiro/agents` across
  requirements/design/tasks returns zero hits (it appears only in Discussion.md).

As written, the orchestrator cannot locate or spawn any delegate, so the workflow
cannot start. The spec needs an explicit installation step (and a task) that places
the seven configs in `.kiro/agents/` (or `~/.kiro/agents/`), and R16.5's "install
the agents" must be defined in terms of that location rather than copying into
`cli-agents/cv/`.

### A2 — Spawn names do not match config filenames, and `name` fields are unspecified
**Evidence:**
- design distribution layout names the files `KiroCLIAgent-CVOrchestrator.json`,
  `KiroCLIAgent-CVEditor.json`, `KiroCLIAgent-SpellFormatReviewer.json`, etc.
- Kiro config reference: "The filename (without `.json`) becomes the agent's name";
  `name` is "optional, derived from filename if not specified."
- The orchestrator's `availableAgents`/`trustedAgents` (design) lists
  `cv-editor-agent`, `spell-format-reviewer`, `language-content-reviewer`,
  `jd-alignment-reviewer`, `ats-reviewer`, `hiring-manager-reviewer`.
- Neither requirements (R16.2/R16.3 specify directory and filename only), design,
  nor tasks specify a `name` field value for any of the seven agents.

If `name` is omitted, the agent names become `KiroCLIAgent-CVEditor` (etc.), which
do not match the `availableAgents`/`trustedAgents` entries, so every spawn fails.
The spec must specify each agent's exact `name` field and make it identical to the
string used in `availableAgents`/`trustedAgents`, the per-agent state directory
(R14.1 `<agent-name>`), and the findings directory. (Existing repo agents already
set an explicit `name`, e.g. `cli-agents/issue-intake/KiroCLIAgent-IssueIntake.json`
→ `"name": "issue-intake-agent"`; the CV suite omits this.)

## B — User-Intent Deviations

### B1 — `file://` prompt and shared-script paths break under the (undefined) install model
**Evidence:**
- design references prompts via `file://./prompt.md`; Kiro config reference: a
  `file://` relative path "resolves relative to the agent configuration file's
  directory."
- design "Distribution layout" note: agents "locate `shared/scripts/` relative to
  the agent config directory," and the orchestrator's `shell.allowedCommands` use
  `python <shared>/page_count.py ...`.
- A1 establishes the configs must move to `.kiro/agents/` to be discoverable.

If installation copies only the JSON files into `.kiro/agents/`, then
`file://./prompt.md` points at a non-existent `.kiro/agents/prompt.md`, and the
`shared/scripts/` directory is no longer "next to" the config. The deliverable
the user asked for — a self-contained, copy-to-install suite (R16.5) — requires the
spec to define exactly how the prompt files and `shared/scripts/` remain resolvable
once the configs live in the discovery directory (e.g., absolute `file://` paths,
or a documented directory layout under `.kiro/agents/`, or workspace-relative
script paths anchored to a fixed location). This is currently unspecified, so the
intent "copy and it works" is not met.

### B2 — Agent-name string is inconsistent across the spec (`ats-reviewer` vs `ats-reviewer-agent`)
**Evidence:**
- design subagent config / availableAgents uses `ats-reviewer` and `cv-editor-agent`.
- design runtime state layout uses per-agent directories `ats-reviewer-agent/` and
  `cv-editor-agent/`; the ATS shell pattern uses `tmp/ats-reviewer-agent/...`; the
  findings directory uses `findings/ats-reviewer/...`.
- R14.1 fixes the per-agent state directory as `.kiro/agent-state/<agent-name>/`.

For ATS, the name (`ats-reviewer`), the state directory (`ats-reviewer-agent`), and
the tmp directory (`ats-reviewer-agent`) disagree, which violates the R14.1
`<agent-name>` contract and (combined with A2) makes name-based spawning and
state-dir resolution ambiguous. Pick one canonical name per agent and use it
verbatim everywhere (name field, availableAgents, trustedAgents, state dir, tmp dir,
findings dir, and the `kiro-cli --agent <name>` invocation).

## C — Clarifications / Risks

### C1 — requirements.md contradicts itself on reviewer write access (R9.2 vs R15.3)
**Evidence:**
- R9.2: "Findings SHALL be persisted under `Workflow_State_Directory/findings/
  <source_agent>/iteration-<n>.json`" — requires a write for every reviewer.
- R15.3: "reviewer agents SHALL be read-only (no `write`, no `shell`) except for the
  JD Alignment Reviewer ... and the ATS Reviewer" — i.e., spell/format,
  language/content, and hiring-manager reviewers have no write tool.
- design "Resolved Design Decisions" #1 (and the Discussion, user reply "1. Ok")
  resolve this by granting those three a narrow `write` scoped to their findings dir.

The design resolved it, but requirements.md was never reconciled, so the requirements
read as self-contradictory (a reviewer cannot satisfy R9.2 with no write tool).
Update R15.3 to state the narrow findings-directory write exception explicitly, so
requirements and design agree.

### C2 — Page count via `ComputeStatistics(wdStatisticPages)` may need repagination
**Evidence:**
- Microsoft Learn confirms `wdStatisticPages = 2` and that `ComputeStatistics`
  returns the page count (verified).
- The canonical win32com recipe (StackOverflow 12964580) calls `word.Repaginate()`
  before reading the count; design's page_count.py step says only "open the
  document, read `ComputeStatistics(wdStatisticPages)`, then close without saving"
  with no repagination/background-pagination step.

Because the page count is a hard convergence gate (R11.6, Property 7), an
unrepaginated or background-paginating read risks an inaccurate count. Add a
repagination/wait step (or document why it is unnecessary) to the page_count.py
design so the hard gate cannot read a stale value.

### C3 — The 10-iteration cap is self-imposed in the orchestrator loop, not platform-enforced
**Evidence:**
- Glossary/R10.2: the cap is 10 "matching Kiro CLI's native review-loop cap."
- Kiro subagent docs: the 10 cap applies to the **native review-loop** construct
  (`max_iterations` "capped at 10").
- design "Execution model" explicitly does NOT use the native review loop for the
  top-level loop ("Native review loops are not used for the top-level loop") and
  states the orchestrator "caps itself at 10."

The design is correct (self-imposed cap), but the requirement phrasing implies the
platform enforces 10 on the orchestrator loop, which it does not. Clarify in R10.2
that the orchestrator enforces the cap itself; the platform's 10 only bounds the
unused native construct.

### C4 — page_count.py correctness is environment-bound and unverifiable in headless CI
**Evidence:**
- design page-count layer: Word COM (`win32com`) primary, requiring `pywin32` + a
  Word install; LibreOffice+pypdf fallback.
- tasks 4.1 tests the "renderer-absent path" by monkeypatching; task 17 (manual,
  inside Kiro CLI) is the only place the real render-based count is exercised.
- Discussion (final assistant turn) acknowledges "Tests for `page_count.py` will
  need that environment, or the COM path gets monkeypatched."

The hard page gate's real correctness is only ever validated manually. Note this
explicitly in the testing strategy (e.g., a calibrated-fixture check on the target
Windows host) so the gate is not assumed-correct from monkeypatched tests alone.

## D — Minor Nits

### D1 — `pdfmin.six` typo names a nonexistent package
**Evidence:** design.md line 276: "`.pdf` → `pdfmin.six` text extraction". tasks.md
(task 3) and task 15's README list correctly use `pdfminer.six`. Fix the design
typo so a literal reading does not install the wrong package.

### D2 — Discussion-file extension claim does not match the cited convention
**Evidence:** R16.3 and design's distribution layout use `.md` discussion files
(`CLIAgent-CVOrchestratorDiscussion.md`) and claim to mirror
`cli-agents/issue-intake/` and `cli-agents/dead-code/`. Those agents actually use
`.txt` (`CLIAgent-IssueIntakeDiscussion.txt`, `CLIAgent-DeadCodeDiscussion.txt`).
Either switch to `.txt` to match, or drop the "mirrors the convention" claim.

### D3 — Task 17 builds its smoke test from a gitignored sample
**Evidence:** task 17 derives the E2E fixture from `tmp/CV Customizer.ipynb`;
`.gitignore` is `tmp/*`, so the notebook (and any sample under `tmp/`) is not a
versioned artifact and will not travel with the suite. Move the derived fixture CV
and JD text into a versioned `cli-agents/cv/shared/tests/fixtures/` location (task 1
already creates that directory) and reference those instead.

## Open Product Decisions

None. Every finding is a technical specification fix resolvable by Kiro in spec
mode without business/user input. (The earlier product decisions OQ-1..OQ-8 are
recorded as D-1..D-11 and remain settled.)

## Evidence Summary

- MCP lookups: 0 (no MCP servers exposed in this environment; substituted
  first-party docs).
- Web sources: 4 (Kiro subagents doc, Kiro config reference, MS Learn WdStatistic,
  StackOverflow win32com page count).
- Codebase references: 7 (cli-agents JSON conventions ×3, .gitignore, notebook,
  design L276, spec-wide greps).
- Pattern-mining hits: 6 (distribution-vs-runtime location, agent naming, prompt
  storage, discussion extension, reviewer write isolation, novel subagent use).

## Handoff Instructions

For Kiro IDE spec mode — make these changes, highest-impact first:

1. (A1) Add an installation section to design.md and an install task to tasks.md
   placing all seven configs in `.kiro/agents/` (or `~/.kiro/agents/`). Redefine
   R16.5 "install" in terms of that location, not a copy into `cli-agents/cv/`.
2. (A2) Specify the exact `name` field for each of the seven agents and make it
   byte-identical to the `availableAgents`/`trustedAgents` entries. Reconcile the
   `KiroCLIAgent-*.json` filenames with the chosen names (set `name` explicitly, as
   the existing repo agents do).
3. (B1) Define how `file://` prompt files and `shared/scripts/` remain resolvable
   once configs live in `.kiro/agents/` (absolute file:// paths, a replicated
   directory layout, or fixed workspace-relative script anchors).
4. (B2) Choose one canonical name per agent and use it verbatim in the name field,
   availableAgents, trustedAgents, state dir (R14.1), tmp dir, and findings dir.
   Fix `ats-reviewer` vs `ats-reviewer-agent`.
5. (C1) Amend R15.3 to state the narrow findings-directory write exception for the
   spell/format, language/content, and hiring-manager reviewers, matching design.
6. (C2) Add a repagination/wait step to the page_count.py design (Word COM path).
7. (C3) Clarify R10.2 that the orchestrator enforces the 10-iteration cap itself.
8. (C4) Note in the testing strategy that the render-based page count is validated
   on the target Windows host, not only via monkeypatched tests.
9. (D1) Fix `pdfmin.six` → `pdfminer.six` in design.md.
10. (D2) Align the discussion-file extension with the cited convention (or drop the
    claim). (D3) Move the task-17 fixture out of gitignored `tmp/` into the
    versioned fixtures directory.
