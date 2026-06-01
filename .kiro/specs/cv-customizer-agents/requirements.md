# Requirements Document

**Subject:** CV Customizer Agent Suite

## Introduction

This spec defines a suite of Kiro CLI custom agents that, working together, transform a candidate's existing CV (a Word document) and an optional motivational letter (also a Word document) into a polished application package optimized for a specific job description, with the goal of maximizing the likelihood that the candidate is invited to an interview. The suite mirrors and extends the workflow currently embodied by `tmp/CV Customizer.ipynb`, replacing manual cell-by-cell execution with an orchestrated, loop-driven workflow that runs entirely inside a single Kiro CLI chat session.

The suite uses Kiro CLI's native subagent mechanism for delegation (see [Subagents](https://kiro.dev/docs/cli/chat/subagents/)). The orchestrator stays in the main session; reviewer and editor agents run as subagents, return results to the orchestrator automatically, and never interact with the user directly. The orchestrator is the only agent that interacts with the candidate, including for the JD alignment agent's clarification questions, which are surfaced through the orchestrator one at a time.

The suite consists of seven custom agents:

1. **CV Orchestrator Agent** — entry point; coordinates all delegate agents via Kiro's subagent mechanism; runs the iterative loop until quality gates pass or the iteration cap is reached; mediates user clarification questions on behalf of the JD Alignment Reviewer.
2. **CV Editor Agent** — the only agent with write authority over the CV and motivational letter Working Copies; applies a structured Change_List by writing and executing a small Python script in a workspace tmp directory.
3. **Spell and Formatting Reviewer Agent** — flags spelling, punctuation, capitalization, and formatting issues without considering the job description.
4. **Language and Content Reviewer Agent** — flags areas of the CV and motivational letter that read poorly or could be tightened, again without considering the job description.
5. **JD Alignment Reviewer Agent** — compares the application package against the job description, identifies gaps and alignment opportunities, may consult the bullet point database, and operates in a two-phase repeatable pattern: non-interactive analysis, followed by orchestrator-mediated user Q&A, followed by non-interactive integration.
6. **ATS Reviewer Agent** — flags content that automated applicant tracking systems would reject, mis-parse, or fail to read. May invoke deterministic Python tooling in addition to LLM analysis.
7. **Hiring Manager Reviewer Agent** — performs a critical end-to-end review of the application package against the job description and emits a hiring recommendation (`INVITE` or `DO_NOT_INVITE`) along with findings.

All agents follow the existing `cli-agents/` conventions in this repository: a `prompt` field stored as a multi-line string in a JSON configuration file (or referenced via a `file://` URI to a separate prompt file), a per-agent state directory under `.kiro/agent-state/<agent-name>/` for evidence and resumability, and structured artifacts on disk as the primary handoff mechanism between agents.

The agent suite is INVESTIGATIVE-AND-EDIT in scope for the Working Copies; it does not modify the candidate's original input files (CV, motivational letter, job description), with one explicit exception: the user-provided Bullet Point Database is updated in place when the JD Alignment Reviewer elicits new content from the candidate, because the candidate uses git to version that file and wants improvements to accumulate over time. The suite does not touch source code, infrastructure, or other project assets outside the workspace state and tmp directories.

## Glossary

- **CV_Document** — The candidate's CV in Microsoft Word `.docx` format. Provided as input to the workflow.
- **CV_Working_Copy** — A workspace-managed working `.docx` derived from the CV_Document. All CV edits are applied to the CV_Working_Copy. The original CV_Document is never modified.
- **Job_Description** — The target job description, provided in any of: HTML, plain text, PDF, Microsoft Word `.docx`, or Markdown.
- **Motivational_Letter** — An optional cover letter in Microsoft Word `.docx` format. Provided as input alongside the CV_Document when applicable.
- **Letter_Working_Copy** — A workspace-managed working `.docx` derived from the Motivational_Letter. All letter edits are applied to the Letter_Working_Copy. The original Motivational_Letter is never modified.
- **Application_Package** — The combined output artifact set: the final CV_Working_Copy plus, if a Motivational_Letter was provided, the final Letter_Working_Copy. The Application_Package is the deliverable of the workflow.
- **Bullet_Point_Database** — An optional, candidate-supplied document containing skills, experiences, achievements, and other content that may not currently appear on the CV. Accepted in any of: Microsoft Word `.docx`, Markdown, plain text, or PDF. Sometimes called the "Extensive CV". The user-provided Bullet_Point_Database file is updated in place when the JD Alignment Reviewer elicits new content from the candidate (see Requirement 13).
- **Database_Sidecar** — A workspace-managed file at `Workflow_State_Directory/database_sidecar.md` that captures elicited content when no Bullet_Point_Database was provided as input, or when the provided database is in a format that does not permit safe in-place editing.
- **Normalized_Text** — A canonical text representation of a binary input (CV_Document, Job_Description, Motivational_Letter, Bullet_Point_Database) used by reviewer agents that reason in plain text.
- **Finding** — A single structured observation produced by a reviewer agent. Each Finding includes an identifier, category, severity, anchor (where in the document it applies), proposed change, rationale, source agent, and target document.
- **Change_List** — A structured collection of Findings translated by the orchestrator into edit instructions for the CV Editor Agent. Each entry identifies its target document (CV_Working_Copy or Letter_Working_Copy).
- **Quality_Gate** — A pass/fail check performed by a reviewer agent. The workflow converges when all reviewer gates pass independently, all open Findings are resolved or marked as Accepted_Gap, and the Page_Constraint holds for both documents.
- **Accepted_Gap** — A Finding (typically from JD alignment) that has been explicitly acknowledged as unresolvable because the candidate does not possess the corresponding skill or experience. Accepted_Gaps are excluded from further quality-gate checks and recorded permanently for the duration of the workflow run.
- **Iteration** — One pass through the orchestrator's loop: reviewers run as subagents, Findings are gathered, the orchestrator decides actions, the editor (also a subagent) applies changes, and quality gates are re-evaluated.
- **Iteration_Cap** — The maximum number of Iterations permitted in a single workflow run. Set to 10, matching Kiro CLI's native review-loop cap.
- **Page_Constraint** — A constraint on the rendered length of each Working Copy. Default: at most 2 pages for the CV_Working_Copy and at most 1 page for the Letter_Working_Copy. The candidate may override the CV page limit at workflow invocation; the letter page limit is always 1 unless explicitly overridden.
- **Workflow_State_Directory** — The shared directory `.kiro/agent-state/cv-workflow/` containing artifacts shared across agents in a single run (current Findings, Change_List, Accepted_Gaps register, iteration log, normalized inputs, etc.).
- **Per_Agent_State_Directory** — The directory `.kiro/agent-state/<agent-name>/` per agent, used for that agent's private evidence, resume state, and intermediate artifacts.
- **Cli_Agents_Cv_Directory** — The directory `cli-agents/cv/` in this repository where the seven agents' JSON configuration files and prompt files are stored for distribution.
- **Subagent_Mechanism** — Kiro CLI's native delegation feature, by which a custom orchestrator agent that includes `subagent` in its `tools` array can spawn other custom agents that run with their own context and permissions and return summaries to the orchestrator. Reference: [Subagents](https://kiro.dev/docs/cli/chat/subagents/). Content was rephrased for compliance with licensing restrictions.

## Requirements

### Requirement 1: Workflow Inputs and Application Package Scope

**User Story:** As a candidate, I want to provide my CV, a target job description, and optionally a motivational letter and a bullet point database, so that the agent suite has all the material it needs to tailor a complete application package.

#### Acceptance Criteria

1. THE workflow SHALL accept a `CV_Document` as a Microsoft Word `.docx` file. This input is mandatory.
2. THE workflow SHALL accept a `Job_Description` in any of: HTML, plain text, PDF, Microsoft Word `.docx`, or Markdown. This input is mandatory.
3. THE workflow SHALL accept an optional `Motivational_Letter` as a Microsoft Word `.docx` file.
4. THE workflow SHALL accept an optional `Bullet_Point_Database` in any of: Microsoft Word `.docx`, Markdown, plain text, or PDF.
5. THE workflow SHALL receive all input file paths as explicit arguments at workflow invocation. The workflow SHALL NOT consult environment variables to locate any input file.
6. WHEN any mandatory input is missing or its file does not exist THEN the orchestrator SHALL terminate with a clear error stating which input was missing.
7. WHEN the optional `Motivational_Letter` is provided THEN it SHALL be subject to the same review and edit passes as the CV (spell and formatting, language and content, JD alignment, ATS, hiring manager). The deliverable in this case is an `Application_Package` containing both the final CV_Working_Copy and the final Letter_Working_Copy. The two documents must form a coherent package that aligns with each other and with the Job_Description.
8. WHEN the optional `Motivational_Letter` is not provided THEN the workflow SHALL proceed with all CV-related capabilities active and SHALL skip letter-related review and edit work entirely.
9. WHEN the optional `Bullet_Point_Database` is not provided THEN the workflow SHALL proceed with the JD Alignment Reviewer Agent's database-driven gap-filling capability disabled. Elicited content from the candidate SHALL be recorded in the `Database_Sidecar` (see Requirement 13).
10. THE workflow SHALL produce a `Normalized_Text` representation of every input it accepts, stored under the `Workflow_State_Directory`, before any reviewer agent runs.
11. THE workflow SHALL NOT modify any input file at the path the user provided, except for the `Bullet_Point_Database`, which is updated in place per Requirement 13.

### Requirement 2: CV Orchestrator Agent

**User Story:** As a candidate, I want a single entry-point agent that drives the entire CV tailoring workflow within one Kiro CLI session, so that I can run the full process without manually invoking each reviewer or editor agent.

#### Acceptance Criteria

1. THE CV Orchestrator Agent SHALL be the entry point of the workflow. The candidate interacts only with the orchestrator. All other agents in the suite run as subagents and never communicate directly with the candidate.
2. THE orchestrator's configuration SHALL include `subagent` in its `tools` array so that it can spawn the other six agents as subagents.
3. THE orchestrator's configuration SHALL declare the six delegate agents in `toolsSettings.subagent.availableAgents` and SHALL declare the non-interactive ones (every delegate other than itself) in `toolsSettings.subagent.trustedAgents` so that subagent invocations do not require user approval at each call.
4. THE orchestrator SHALL initialize the `Workflow_State_Directory` on first invocation, including writing initial copies of normalized inputs, an empty Change_List, an empty Findings register, an empty `Accepted_Gaps` register, and an iteration log starting at iteration 0.
5. THE orchestrator SHALL invoke reviewer agents as subagents in a defined order per iteration. The default order is: (1) Spell and Formatting Reviewer, (2) Language and Content Reviewer, (3) JD Alignment Reviewer, (4) ATS Reviewer, (5) Hiring Manager Reviewer.
6. THE orchestrator SHALL collect all Findings produced in an iteration, deduplicate them, and translate them into a Change_List for the CV Editor Agent.
7. THE orchestrator SHALL invoke the CV Editor Agent as a subagent with the Change_List to apply edits to the CV_Working_Copy and (if applicable) the Letter_Working_Copy.
8. THE orchestrator SHALL evaluate the Page_Constraint for each Working Copy after each edit pass.
9. THE orchestrator SHALL terminate successfully when all of the following hold simultaneously: every reviewer agent's Quality_Gate passes (no open Findings remain other than `Accepted_Gap` items), the Page_Constraint holds for every Working Copy in the Application_Package, and the Hiring Manager Reviewer Agent emits an `INVITE` recommendation.
10. THE orchestrator SHALL terminate with a `did_not_converge` outcome if the `Iteration_Cap` of 10 is reached without simultaneous Quality_Gate satisfaction.
11. THE orchestrator SHALL NOT have direct write access to either Working Copy. All modifications to Working Copies SHALL be performed by the CV Editor Agent.
12. THE orchestrator SHALL preserve a complete audit trail of every iteration, including which reviewers ran, what Findings they produced, what the editor applied, what the resulting page count was per Working Copy, and the per-reviewer Quality_Gate status, in `Workflow_State_Directory/iteration_log.md`.
13. THE orchestrator SHALL be the sole agent that surfaces clarification questions to the candidate (on behalf of the JD Alignment Reviewer; see Requirement 6). The orchestrator SHALL ask such questions one at a time, recording the question and the candidate's response in the workflow state before proceeding.

### Requirement 3: CV Editor Agent (Exclusive Write Authority)

**User Story:** As a workflow operator, I want all Working Copy edits performed by exactly one agent that operates from a structured change list, so that edits are auditable, reversible, and never made by reviewer agents directly.

#### Acceptance Criteria

1. THE CV Editor Agent SHALL be the sole agent in the suite with write authority over the CV_Working_Copy and the Letter_Working_Copy.
2. THE CV Editor Agent SHALL accept a Change_List as input and SHALL apply each Change_List entry to the entry's specified target document (CV_Working_Copy or Letter_Working_Copy).
3. THE CV Editor Agent SHALL apply changes by writing a Python script to a workspace-scoped temp directory (`tmp/cv-editor/<iso-timestamp>/`) and executing it via the `shell` tool. The script SHALL use the `python-docx` library (or an equivalent maintained library; final choice in design) to perform structural edits.
4. THE CV Editor Agent SHALL produce a timestamped backup of each Working Copy before any edit pass: `<working-copy-name>.<iso-timestamp>.bak.docx` stored under the `Workflow_State_Directory`. (Note: this backup is for in-run rollback; the candidate's git workflow handles cross-run history.)
5. THE CV Editor Agent SHALL verify each applied change after script execution by re-reading the resulting `.docx` and comparing the affected paragraphs/runs against the requested change. The verification result for each Change_List entry SHALL be recorded.
6. WHEN the verification of a Change_List entry fails THEN the CV Editor Agent SHALL mark the entry as `failed_to_apply` in its output and SHALL NOT silently skip it. The orchestrator SHALL surface failed-to-apply entries in the iteration log.
7. THE CV Editor Agent SHALL NOT modify any file outside `tmp/cv-editor/**`, `Workflow_State_Directory/**`, the CV_Working_Copy path, and the Letter_Working_Copy path.
8. THE CV Editor Agent SHALL NOT invoke any reviewer agent. The CV Editor Agent's role is strictly to apply a Change_List.
9. THE CV Editor Agent SHALL persist every script it generates and every script's stdout/stderr under its `Per_Agent_State_Directory` so that a workflow run can be reconstructed after termination.

### Requirement 4: Spell and Formatting Reviewer Agent

**User Story:** As a candidate, I want a reviewer that catches spelling, punctuation, capitalization, and formatting issues across my CV and motivational letter, so that cosmetic errors do not disqualify me before my content is even considered.

#### Acceptance Criteria

1. THE Spell and Formatting Reviewer Agent SHALL operate on the CV_Working_Copy and (when present) the Letter_Working_Copy, using their `Normalized_Text` representations or the `.docx` directly per the agent's design choice. The agent SHALL NOT consult the Job_Description.
2. THE agent SHALL produce Findings for: spelling errors, grammatical errors, punctuation errors, capitalization inconsistencies, tense inconsistencies, date-format inconsistencies, number-format inconsistencies, and visible formatting defects (e.g., orphaned single-line trailing pages, inconsistent bullet styles).
3. THE agent SHALL produce Findings using the unified Finding schema defined in Requirement 9, with each Finding tagged with its target document (CV_Working_Copy or Letter_Working_Copy).
4. THE agent SHALL rely on its underlying LLM to perform spell and formatting analysis. THE agent SHALL NOT require external spell-checking libraries. (This matches the notebook's working approach.)
5. THE agent SHALL NOT modify any Working Copy. The agent's output is read-only Findings only.
6. THE agent's Quality_Gate SHALL pass when no open Findings remain in its category set after the editor's most recent edit pass, evaluated independently for each Working Copy.

### Requirement 5: Language and Content Reviewer Agent

**User Story:** As a candidate, I want a reviewer that critically reviews the prose of my CV and motivational letter in isolation from the job description, so that areas of weak phrasing, vague claims, or weak action verbs are surfaced and improved before any job-specific tailoring happens.

#### Acceptance Criteria

1. THE Language and Content Reviewer Agent SHALL operate on the CV_Working_Copy and (when present) the Letter_Working_Copy. The agent SHALL NOT consult the Job_Description.
2. THE agent SHALL produce Findings for: weak action verbs, vague or unquantified claims, redundant phrasing, passive voice where active is more appropriate, missing professional summary content, parallelism issues across bullets, structural issues in cover-letter prose (paragraph balance, opening hook, closing call-to-action), and other prose-level improvements.
3. THE agent SHALL produce Findings using the unified Finding schema defined in Requirement 9, with each Finding tagged with its target document.
4. THE agent SHALL rely on its underlying LLM for language and content analysis.
5. THE agent SHALL NOT modify any Working Copy.
6. THE agent's Quality_Gate SHALL pass when no open Findings remain in its category set after the editor's most recent edit pass, evaluated independently for each Working Copy.

### Requirement 6: JD Alignment Reviewer Agent (Two-Phase, Repeatable)

**User Story:** As a candidate, I want a reviewer that compares my application package to the target job description, identifies skill and experience gaps, draws on my bullet point database to fill those gaps where possible, and asks me clarifying questions only when neither the database nor the existing application package provides the missing information, so that I do not waste effort on alignment improvements I could have surfaced from existing material.

#### Acceptance Criteria

1. THE JD Alignment Reviewer Agent SHALL consume the CV_Working_Copy, the Job_Description, the Letter_Working_Copy (when present), and the Bullet_Point_Database (when present, including any in-place additions from prior iterations).
2. THE agent SHALL produce Findings for: explicit skill or experience requirements in the Job_Description that are not reflected in the application package, terminology in the Job_Description that could replace less-aligned terminology in the application package, and emphasis re-balancing where existing content matches the Job_Description but is buried.
3. WHEN a gap is identified AND the gap is addressable from the Bullet_Point_Database or the Database_Sidecar THEN the agent SHALL produce a Finding whose proposed change pulls content from that source.
4. THE agent SHALL operate in a two-phase pattern when clarification is needed:
   - **Phase 1 (Analysis)**: a non-interactive subagent invocation that consumes inputs, identifies gaps, and emits any clarification needs to a structured artifact (`Workflow_State_Directory/jd_alignment/pending_questions.json`) along with all Findings that can already be produced without user input. The agent terminates Phase 1 with a `summary` indicating whether questions are pending.
   - **Phase 2 (Integration)**: a separate non-interactive subagent invocation, triggered by the orchestrator after the candidate has answered, that consumes the answered questions and emits the final Findings (filling-in Findings derived from candidate input, plus `Accepted_Gap` markers for declined gaps).
5. THE two-phase pattern SHALL be repeatable within the same iteration. Phase 1 may emit new questions in response to information gathered during a previous Phase 2; the orchestrator SHALL re-enter the user Q&A flow as many times as needed within the iteration, subject to the global `Iteration_Cap` for the workflow as a whole.
6. THE orchestrator SHALL surface clarification questions to the candidate one at a time, not as a batched list. WHEN multiple questions are pending THEN the orchestrator SHALL present the first question, wait for the answer, record it in workflow state, and only then present the next question.
7. WHEN the candidate responds with information that fills a gap THEN the JD Alignment Reviewer Agent (in its next Phase 2 invocation) SHALL produce a Finding incorporating the candidate's information AND SHALL append the new content to the Bullet_Point_Database (in place, when a database file was provided in a writable text-based format) or to the Database_Sidecar (when no database was provided or the provided format does not support safe in-place writeback). See Requirement 13 for writeback details.
8. WHEN the candidate responds that they do not have the requested skill or experience THEN the agent SHALL record the corresponding Finding as an `Accepted_Gap` in the `Accepted_Gaps` register. Accepted_Gaps SHALL NOT be reopened in subsequent iterations.
9. THE JD Alignment Reviewer Agent SHALL be the only agent in the suite whose workflow contributes clarification questions to the candidate. All other agents operate without surfacing user-facing questions.
10. THE agent SHALL NOT modify any Working Copy. The agent's only file-write authority is to its `Per_Agent_State_Directory`, the `Workflow_State_Directory/jd_alignment/` subtree, the Bullet_Point_Database (in-place writeback per Requirement 13), and the Database_Sidecar.
11. THE agent's Quality_Gate SHALL pass when every gap Finding is either resolved (proposed change applied and verified) or recorded in the `Accepted_Gaps` register.

### Requirement 7: ATS Reviewer Agent

**User Story:** As a candidate, I want a reviewer that simulates how automated applicant tracking systems will parse and score my application package, so that quirks of those systems do not silently disqualify me before a human reviewer ever sees the documents.

#### Acceptance Criteria

1. THE ATS Reviewer Agent SHALL operate on the CV_Working_Copy and (when present) the Letter_Working_Copy and produce Findings for ATS-incompatibility issues including: content inside text boxes, content inside images, multi-column layouts that ATS parsers misread, header/footer content that ATS parsers ignore, non-standard section headings, special characters that fail to round-trip through ATS parsers, and missing keywords from the Job_Description that ATS keyword-matching commonly looks for.
2. THE agent MAY consult the Job_Description for keyword-matching purposes.
3. THE agent SHALL prefer deterministic Python tooling for the structural and parser-quirk subset of its checks (e.g., `python-docx` to inspect document structure, and existing ATS-evaluation libraries where appropriate). The specific library choices SHALL be settled in `design.md`. THE agent MAY use its underlying LLM for the keyword-matching subset of its checks.
4. WHEN the agent uses Python tooling THEN it SHALL invoke that tooling by writing a script to `tmp/cv-ats-reviewer/<iso-timestamp>/` and executing it via the `shell` tool, in the same pattern used by the CV Editor Agent. The agent's `toolsSettings.shell.allowedCommands` SHALL be scoped to permit only this pattern.
5. THE agent SHALL produce Findings using the unified Finding schema defined in Requirement 9, with each Finding tagged with its target document.
6. THE agent SHALL NOT modify any Working Copy.
7. THE agent's Quality_Gate SHALL pass when no open Findings remain in its category set after the editor's most recent edit pass, evaluated independently for each Working Copy.

### Requirement 8: Hiring Manager Reviewer Agent

**User Story:** As a candidate, I want a final critical review that simulates a hiring manager reading my application package with the job description in hand, so that I have a clear go/no-go signal on whether the package is interview-worthy before I submit it.

#### Acceptance Criteria

1. THE Hiring Manager Reviewer Agent SHALL consume the CV_Working_Copy, the Job_Description, and the Letter_Working_Copy when present. THE agent SHALL evaluate the package as a whole: the CV alone is insufficient when a motivational letter is present; the agent SHALL verify the two documents are coherent with each other and with the Job_Description.
2. THE agent SHALL produce a structured review including: a list of strengths (with citations to specific content in the package), a list of concerns (as Findings), and a final binary recommendation: `INVITE` or `DO_NOT_INVITE`.
3. THE agent SHALL produce concern Findings using the unified Finding schema defined in Requirement 9, with each Finding tagged with its target document (CV_Working_Copy, Letter_Working_Copy, or `package_coherence` when the issue is a cross-document inconsistency).
4. THE agent SHALL NOT modify any Working Copy.
5. THE agent's Quality_Gate SHALL pass when ALL of the following hold: the recommendation is `INVITE` AND no open concern Findings from this agent remain other than `Accepted_Gap` items.
6. THE Hiring Manager Quality_Gate SHALL be evaluated independently of the other reviewer gates. An `INVITE` recommendation does NOT unblock convergence if any other reviewer's gate is still failing. Convergence requires every reviewer's gate to pass independently (see Requirement 10).
7. THE agent SHALL NOT contribute clarification questions to the candidate. Concerns that would benefit from clarification SHALL be emitted as Findings for the orchestrator and other agents to address.

### Requirement 9: Unified Findings and Change List Schema

**User Story:** As a workflow operator, I want every reviewer agent to produce Findings in the same structured schema, and I want the orchestrator to translate Findings into a consistent Change_List for the editor, so that handoffs between agents are reliable, deduplicable, and auditable.

#### Acceptance Criteria

1. EVERY Finding produced by any reviewer agent SHALL include the following fields:
   - `id`: a stable identifier unique within the workflow run
   - `source_agent`: the name of the agent that produced the Finding
   - `iteration`: the iteration number in which the Finding was produced
   - `target_document`: one of `CV_Working_Copy`, `Letter_Working_Copy`, or `package_coherence`
   - `category`: the kind of issue (e.g., `spelling`, `formatting`, `language`, `jd_gap`, `ats`, `hiring_manager_concern`)
   - `severity`: one of `low`, `medium`, `high`, `blocking`
   - `anchor`: a stable reference into the target document identifying where the Finding applies (e.g., heading text, paragraph index plus stable identifier, or section name); for `package_coherence` Findings, the anchor identifies one or more locations across both documents
   - `current`: the current text or formatting state at the anchor (where applicable)
   - `proposed`: the proposed text or formatting change (where applicable)
   - `rationale`: why the change is recommended, with citations where appropriate
   - `status`: one of `open`, `applied`, `verification_failed`, `accepted_gap`, `wont_fix`
2. Findings SHALL be persisted under `Workflow_State_Directory/findings/<source_agent>/iteration-<n>.json` (or `.md` with frontmatter, per design choice).
3. THE orchestrator SHALL translate Findings into Change_List entries that the CV Editor Agent can apply mechanically. Each Change_List entry SHALL preserve a backreference to the Finding ID(s) it implements and SHALL specify its target document.
4. WHEN two Findings from different agents conflict (e.g., ATS proposes removing a special character that the language reviewer wants to keep) THEN the orchestrator SHALL record the conflict, choose a resolution rule (default: ATS-blocking severity wins over language preferences), and document the resolution in the iteration log.

### Requirement 10: Iteration Loop, Quality Gates, and Convergence

**User Story:** As a candidate, I want the workflow to iterate automatically until every reviewer agent's quality gate passes or it becomes clear the workflow cannot converge, so that I receive either a polished application package or a clear explanation of why one could not be produced.

#### Acceptance Criteria

1. THE orchestrator SHALL run iterations until ALL of the following hold simultaneously: every reviewer's Quality_Gate passes independently, the Page_Constraint holds for every Working Copy, and the Hiring Manager Reviewer recommends `INVITE`.
2. THE orchestrator SHALL terminate with a `did_not_converge` outcome when the `Iteration_Cap` of 10 iterations is reached without simultaneous Quality_Gate satisfaction. The orchestrator enforces this cap itself within its own loop logic; it is not enforced by any platform mechanism. The value 10 is chosen to align with the maximum of Kiro CLI's native review-loop construct, even though that native construct is not used for the top-level loop (see `design.md`).
3. WHEN the same Finding (matched by `target_document` + `anchor` + `category` + substantive `proposed` content) reappears across two consecutive iterations after being marked `applied` THEN the orchestrator SHALL classify it as oscillation. The orchestrator SHALL escalate oscillating Findings into the iteration log and SHALL NOT silently re-apply the same change indefinitely.
4. WHEN oscillation is detected THEN the orchestrator SHALL attempt one alternate resolution (e.g., reverse-prioritize the conflicting agents per Requirement 9.4 conflict rules). If oscillation persists for a third consecutive iteration on the same Finding THEN the orchestrator SHALL mark it `wont_fix` with documented rationale and continue.
5. `Accepted_Gap` Findings SHALL be excluded from Quality_Gate evaluation in subsequent iterations.
6. THE iteration log under `Workflow_State_Directory/iteration_log.md` SHALL contain, per iteration: the iteration number, the timestamp, the list of reviewers run, the count of Findings per category and target document, the Change_List applied, the verification results, the resulting page count per Working Copy, and the per-reviewer Quality_Gate status.
7. THE choice between using Kiro CLI's native review-loop construct (target / trigger / max_iterations) for individual reviewer-editor stages and using an orchestrator-level loop driven by on-disk Findings state SHALL be settled in `design.md`. Either choice is consistent with the 10-iteration cap.

### Requirement 11: Page Constraint

**User Story:** As a candidate, I want the produced CV to default to two pages (and the motivational letter to one page), with the option to override the CV page limit when I have a defensible reason to, since these are the conventional length expectations in many hiring processes.

#### Acceptance Criteria

1. THE workflow SHALL enforce a Page_Constraint per Working Copy.
2. THE default maximum length SHALL be 2 pages for the CV_Working_Copy and 1 page for the Letter_Working_Copy.
3. THE candidate MAY override the CV_Working_Copy page limit at workflow invocation by passing an explicit page-limit argument. WHEN the candidate provides such an override THEN the orchestrator SHALL use the overridden value and SHALL record the override (with its value and the timestamp at which it was applied) in the iteration log. THE candidate MAY similarly override the Letter_Working_Copy page limit, but the default of 1 page SHALL apply when no override is provided.
4. THE orchestrator SHALL measure the page count of each Working Copy after each editor pass.
5. WHEN a Working Copy's page count exceeds its Page_Constraint THEN the orchestrator SHALL produce Change_List entries (sourced from the Language and Content Reviewer's existing Findings or by re-invoking that reviewer with explicit instructions to suggest reductions) that reduce length while preserving the highest-impact content.
6. THE workflow SHALL NOT terminate successfully while any Working Copy's page count exceeds its Page_Constraint, regardless of all other Quality_Gate states.
7. THE specific page-counting mechanism SHALL be defined in `design.md`. The mechanism SHALL be reliable and SHALL operate on the `.docx` directly (or via a deterministic conversion to a paginated format such as PDF). Acceptable mechanisms include conversion to PDF via a headless renderer (LibreOffice or Word automation), inspection of `.docx` page-break and section metadata, or a calibrated character-and-line heuristic validated against known-good documents. Design MAY also choose to factor page-counting into a dedicated subagent if isolation is beneficial.

### Requirement 12: Accepted Gaps Register

**User Story:** As a candidate, I want gaps I cannot fill (skills I do not possess, experience I lack) to be recorded once and then excluded from the iterative loop, so that the workflow does not repeatedly re-prompt me for information I have already declined to provide.

#### Acceptance Criteria

1. THE `Accepted_Gaps` register SHALL be persisted at `Workflow_State_Directory/accepted_gaps.md` (or equivalent JSON/markdown form per design).
2. EVERY entry in the register SHALL include: the originating Finding ID, the originating agent (typically JD Alignment), the iteration in which the gap was accepted, the candidate's verbatim response declining the gap, and a one-line summary of the missing skill or experience.
3. THE orchestrator SHALL exclude `Accepted_Gap` Findings from Quality_Gate evaluation.
4. THE Hiring Manager Reviewer Agent SHALL include the `Accepted_Gaps` register summary as supporting context in its review and MAY downgrade its recommendation if the cumulative accepted gaps materially weaken the candidate's fit.
5. THE register SHALL persist for the lifetime of the workflow run and SHALL be surfaced in the orchestrator's termination report.

### Requirement 13: Bullet Point Database Handling and Writeback

**User Story:** As a candidate, I want new content I provide during the workflow to be written back into my bullet point database when possible, so that my source-of-truth document accumulates improvements over time across multiple workflow runs. I version this file with git, so I do not need a separate backup mechanism inside the workflow.

#### Acceptance Criteria

1. WHEN a Bullet_Point_Database is provided AND its file format supports safe in-place text editing (Markdown or plain text) THEN the JD Alignment Reviewer Agent SHALL append elicited content to the user-provided Bullet_Point_Database file in place. The agent SHALL preserve the existing file structure and conventions to the maximum extent possible (e.g., appending under an appropriate heading, using a consistent bullet style).
2. WHEN a Bullet_Point_Database is provided in a binary format (Microsoft Word `.docx` or PDF) THEN the JD Alignment Reviewer Agent SHALL NOT modify that file in place. Instead, it SHALL append elicited content to the `Database_Sidecar` at `Workflow_State_Directory/database_sidecar.md` and SHALL surface, in the orchestrator's termination report, an instruction to the candidate to merge the sidecar contents into the source-of-truth database manually.
3. WHEN no Bullet_Point_Database is provided THEN the JD Alignment Reviewer Agent SHALL append elicited content to the `Database_Sidecar` and SHALL surface its location in the termination report.
4. EVERY entry written to the Bullet_Point_Database (in place) or the Database_Sidecar SHALL preserve provenance: the iteration in which the entry was elicited, the Finding ID it relates to, the verbatim question asked, and the candidate's verbatim response. Provenance SHALL be stored as metadata that does not disrupt the readability of the file (e.g., as comment-style annotations in Markdown, or as inline italicized footnotes).
5. THE orchestrator's termination report SHALL surface the in-place writeback (when applicable) and the existence of the Database_Sidecar (when applicable) so that the candidate is aware of every modification or elicited content the workflow produced.
6. THE workflow SHALL NOT create its own backup copies of the Bullet_Point_Database. Versioning is the candidate's responsibility via git.

### Requirement 14: Per-Agent State and Resumability

**User Story:** As a candidate, I want every agent in the suite to write durable state so that an interrupted workflow can resume cleanly, mirroring the resumability pattern used by the existing `cli-agents/` agents in this repository.

#### Acceptance Criteria

1. EVERY agent in the suite SHALL maintain a `Per_Agent_State_Directory` at `.kiro/agent-state/<canonical-name>/`, where `<canonical-name>` is the agent's canonical name as fixed in Requirement 16.3 (e.g., `.kiro/agent-state/cv-ats-reviewer/`).
2. EVERY agent SHALL write a `resume_state.md` (or equivalent) at the top of its state directory with at minimum: a `Status` field (`IN_PROGRESS`, `COMPLETED`, `BLOCKED_ON_CLARIFICATION`, `FATAL`), a timestamp, and an input hash that uniquely identifies the inputs for the current invocation.
3. WHEN an agent is invoked AND a prior `resume_state.md` exists with `Status: IN_PROGRESS` AND its input hash matches the current invocation's inputs THEN the agent SHALL resume from the recorded step rather than starting fresh.
4. WHEN a prior `resume_state.md` exists with `Status: COMPLETED` or `Status: FATAL` THEN the agent SHALL archive it with an ISO timestamp suffix and proceed with a fresh run.
5. THE `Workflow_State_Directory` SHALL similarly maintain a workflow-level resume marker that captures the orchestrator's current iteration, in-flight reviewer queue, pending JD-alignment questions and their answered/unanswered state, and pending Change_List.
6. THE state-directory layout and resume protocol SHALL be consistent with the conventions established by the existing agents under `cli-agents/` in this repository (see for example `cli-agents/issue-intake/` and `cli-agents/dead-code/`).

### Requirement 15: Tool Permissions, Subagent Configuration, and No-Environment-Variables

**User Story:** As a workspace owner, I want each agent's tool permissions scoped to exactly what it needs, the orchestrator configured to delegate via Kiro's native subagent mechanism, and the workflow operating without depending on any environment variable, so that the suite cannot accidentally affect unrelated projects on the system.

#### Acceptance Criteria

1. NO agent in the suite SHALL read or rely on environment variables for any input path, configuration, or credential. All such values SHALL be passed as explicit arguments or read from workspace-relative files.
2. THE CV Orchestrator Agent's configuration SHALL include `subagent` in its `tools` array, SHALL declare the six delegate agents by their canonical names in `toolsSettings.subagent.availableAgents`, and SHALL declare the same six in `toolsSettings.subagent.trustedAgents` so that the orchestrator can delegate to them without per-call user approval prompts. The canonical names are `cv-editor`, `cv-spell-format-reviewer`, `cv-language-content-reviewer`, `cv-jd-alignment-reviewer`, `cv-ats-reviewer`, and `cv-hiring-manager-reviewer`. The orchestrator's own canonical name is `cv-orchestrator`. (See Requirement 16 for how each canonical name is bound to a config file via its `name` field, and how the configs are installed into a Kiro-discoverable location.)
3. EVERY delegate agent's `allowedTools` SHALL be the minimum needed for its role. No delegate has `write` access to any Working Copy or to another agent's state. Specifically:
   - The Spell and Formatting Reviewer, Language and Content Reviewer, and Hiring Manager Reviewer SHALL be read-only with respect to documents and shared state, with one tightly scoped `write` exception: each MAY write only to its own `Per_Agent_State_Directory` and its own `Workflow_State_Directory/findings/<agent-name>/` subtree, so that Findings persist for audit and resumability (per Requirement 9.2). None of these three has `shell`.
   - The JD Alignment Reviewer SHALL additionally be permitted to write to its `Per_Agent_State_Directory`, its own `findings/<agent-name>/` subtree, the `Workflow_State_Directory/jd_alignment/` subtree, the `Accepted_Gaps` register, the `Database_Sidecar`, and the user-provided Bullet_Point_Database when in a writable text-based format (per Requirement 13). It has no `shell`.
   - The ATS Reviewer SHALL be permitted to write to its `Per_Agent_State_Directory`, its own `findings/<agent-name>/` subtree, and `tmp/cv-ats-reviewer/**`, and to execute its structural-check script there via `shell` (per Requirement 7).
   - The CV Editor Agent SHALL be permitted to write to `tmp/cv-editor/**`, `Workflow_State_Directory/**`, and the Working Copy paths, and to execute its edit script via `shell`.
   - The orchestrator SHALL be permitted to write to `Workflow_State_Directory/**` and its own `Per_Agent_State_Directory`, and to execute the normalization and page-count scripts via `shell`.
4. EVERY agent that uses the `shell` tool SHALL have `toolsSettings.shell.allowedCommands` and `deniedCommands` configured to permit only the commands necessary for that agent's role.
5. NO agent SHALL invoke `pip install`, `npm install`, package managers, or any command that mutates the host system outside of the workspace.
6. NO agent SHALL invoke `git` commands. Version control of the agents' configurations and the workflow outputs is performed by the user, not by the agents.
7. WHEN any agent encounters a path outside the permitted scope THEN it SHALL terminate with a clear error rather than attempting the operation.

### Requirement 16: File and Directory Layout

**User Story:** As a workspace owner, I want the seven agents authored under `cli-agents/cv/` and installed into a Kiro-discoverable agent location with consistent canonical names, so that the orchestrator can spawn each delegate by name and the suite is easy to find, distribute, install, and version-control alongside the other agents in this repository.

#### Acceptance Criteria

1. ALL seven agents' configuration files, prompt files, discussion notes, and shared scripts/schemas SHALL be authored and version-controlled under `cli-agents/cv/` (the distribution tree).
2. EACH agent SHALL have its own subdirectory under `cli-agents/cv/`, named after the agent's canonical name without the `cv-` prefix where that reads naturally (e.g., `cli-agents/cv/orchestrator/`, `cli-agents/cv/editor/`, `cli-agents/cv/spell-format-reviewer/`, `cli-agents/cv/language-content-reviewer/`, `cli-agents/cv/jd-alignment-reviewer/`, `cli-agents/cv/ats-reviewer/`, `cli-agents/cv/hiring-manager-reviewer/`).
3. EACH agent SHALL have a canonical name that is used byte-identically in ALL of the following places: the JSON `name` field, the orchestrator's `availableAgents`/`trustedAgents` entries, the `Per_Agent_State_Directory` path (`.kiro/agent-state/<canonical-name>/`), the agent's findings directory (`Workflow_State_Directory/findings/<canonical-name>/`), the agent's tmp directory when it has one (`tmp/<canonical-name>/`), and the `kiro-cli --agent <canonical-name>` invocation. The canonical names are: `cv-orchestrator`, `cv-editor`, `cv-spell-format-reviewer`, `cv-language-content-reviewer`, `cv-jd-alignment-reviewer`, `cv-ats-reviewer`, `cv-hiring-manager-reviewer`.
4. EACH agent's JSON configuration SHALL set the `name` field explicitly to the agent's canonical name. The configuration SHALL NOT rely on filename-derived naming, because the orchestrator resolves delegates by canonical name and the filename does not match that name.
5. EACH agent's directory SHALL contain at minimum: a Kiro CLI agent JSON file, a prompt file, and a discussion/notes file. The discussion/notes file SHALL use the `.txt` extension to match the existing repository convention (e.g., `cli-agents/issue-intake/CLIAgent-IssueIntakeDiscussion.txt`, `cli-agents/dead-code/CLIAgent-DeadCodeDiscussion.txt`).
6. EACH agent's prompt SHALL be stored in a separate prompt file referenced from the JSON `prompt` field via a `file://` URI. To remain resolvable after installation (see 16.8), the `prompt` field SHALL reference the prompt file using a path that resolves correctly from the installed config location — either an absolute `file://` path produced by the installer, or a `file://` path relative to the installed config's directory with the prompt file installed alongside it.
7. EACH agent's configuration and prompt SHALL reference the shared scripts (`page_count.py`, `docx_normalize.py`, `input_normalize.py`, `docx_edit.py`, `ats_structural.py`) and shared schemas by a path that is resolvable at runtime independent of the current working directory and independent of the `cli-agents/cv/` authoring location. The exact resolution mechanism (absolute path written by the installer, or a fixed installed location) SHALL be defined in `design.md`.
8. THE suite SHALL be installable into a Kiro-discoverable agent location. Kiro CLI discovers custom agents only in `.kiro/agents/` (workspace) or `~/.kiro/agents/` (global); the `cli-agents/cv/` authoring tree is NOT scanned. Therefore an explicit installation step SHALL copy or generate each agent's JSON config into `.kiro/agents/` (workspace install) or `~/.kiro/agents/` (global install), with the canonical name as the file basename (e.g., `.kiro/agents/cv-orchestrator.json`), and SHALL ensure each config's `prompt` `file://` reference and shared-script references resolve from that installed location.
9. THE installation step SHALL be documented and SHALL be self-contained: a user who copies the `cli-agents/cv/` tree into another workspace and runs the documented install SHALL obtain a working suite with no other files from this repository.
10. WHEN the installation places only the JSON configs into `.kiro/agents/` THEN the installer SHALL also ensure the referenced prompt files and shared scripts are present at the resolved paths (e.g., by installing prompt files alongside the configs and rewriting `file://` references to absolute paths, or by installing the whole tree to a fixed location and pointing `.kiro/agents/` configs at it). The chosen approach SHALL be specified in `design.md`.

## Decisions Recorded

The following decisions were made during requirements review and are now baked into the requirements above. They are listed here for traceability.

- **D-1: Orchestration mechanism** — In-session subagent delegation via Kiro CLI's native subagent feature. The orchestrator stays in the main session; reviewers and the editor run as subagents. (Closes prior OQ-1.)
- **D-2: Database write-back policy** — In-place writeback to the user-provided Bullet_Point_Database when its format supports safe text editing (Markdown or plain text); otherwise to a `Database_Sidecar`. The candidate uses git for versioning; no workflow-internal backup is required. (Closes prior OQ-2.)
- **D-3: Motivational letter scope** — Fully in scope. Same review and edit passes apply. The deliverable is an `Application_Package` containing both the CV and the letter when a letter was provided. (Closes prior OQ-3.)
- **D-4: Page-count mechanism** — Reliable mechanism required, settled in design. May be a deterministic library, a headless conversion, or a dedicated subagent. (Closes prior OQ-4 at the requirements level.)
- **D-5: Spell-and-formatting tooling** — LLM-only (matching the notebook's working approach); no separate spell-checking library required. (Closes prior OQ-5.)
- **D-6: ATS detection technique** — Hybrid: deterministic Python tooling for structural and parser-quirk checks, LLM for keyword matching. Specific libraries settled in design. (Closes prior OQ-6.)
- **D-7: Page-constraint behavior** — Default 2 pages for CV, default 1 page for letter; user may override the CV (and, if needed, the letter) at workflow invocation; constraint is a hard convergence requirement when in effect. (Closes prior OQ-7.)
- **D-8: Hiring Manager gate composition** — Every reviewer's gate must pass independently. An `INVITE` recommendation alone does not unblock convergence. (Closes prior OQ-8.)
- **D-9: JD Alignment two-phase pattern, repeatable** — Analysis (Phase 1) → orchestrator-mediated user Q&A → integration (Phase 2). The pattern is repeatable within a single iteration when integration surfaces new questions. The orchestrator asks questions one at a time, never as a batched list.
- **D-10: Iteration cap** — 10 iterations, matching Kiro CLI's native review-loop maximum.
- **D-11: Page-count renderer** — Microsoft Word automation is the primary page-count engine (the candidate uses Word for downstream manual edits, so the gate matches the candidate's own view of pagination); LibreOffice headless conversion is the fallback; the workflow fails fast if neither is available. (Settled during design review.)
- **D-12: Agent installation and discovery** — Agents are authored under `cli-agents/cv/` but installed into `.kiro/agents/` (workspace) or `~/.kiro/agents/` (global), because Kiro CLI scans only those locations. Each config's `name` field is set explicitly to the agent's canonical name; filename-derived naming is not relied upon. The installer ensures `file://` prompt references and shared-script references resolve from the installed location. (Settled in spec review iteration 01, findings A1/A2/B1.)
- **D-13: Canonical agent names** — Each agent has a single canonical name used byte-identically across the `name` field, `availableAgents`/`trustedAgents`, state dir, findings dir, tmp dir, and `--agent` invocation: `cv-orchestrator`, `cv-editor`, `cv-spell-format-reviewer`, `cv-language-content-reviewer`, `cv-jd-alignment-reviewer`, `cv-ats-reviewer`, `cv-hiring-manager-reviewer`. (Settled in spec review iteration 01, findings A2/B2.)

## Open Questions

No requirement-level open questions remain. The following items are intentionally deferred to `design.md`:

- Specific Python libraries for the CV Editor Agent (`python-docx` is the working assumption; alternatives may be considered).
- Specific Python libraries for the ATS Reviewer Agent's deterministic checks.
- Specific page-counting mechanism implementation, including whether to introduce a dedicated subagent for `.docx` metadata access.
- Whether to use Kiro CLI's native review-loop construct for individual reviewer-editor stages or implement an orchestrator-level loop driven by on-disk Findings state, or a hybrid (note: 10-iteration cap applies in either case).
- Specific format of the Findings persistence (JSON vs. Markdown-with-frontmatter).
- Conflict-resolution defaults beyond the "ATS-blocking severity wins over language preferences" baseline stated in Requirement 9.4.
