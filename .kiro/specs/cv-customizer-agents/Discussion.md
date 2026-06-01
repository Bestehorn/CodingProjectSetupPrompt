# I have a notebook for modifying and customizing...

Exported: 5/29/2026, 3:06:56 PM

## Steering Documents

**Workspace:**
- tests-must-not-fail.md

**Global:**
- No%20Environment%20Variables.md

---

**User:**

I have a notebook for modifying and customizing CVs that currently requires manual automation and a lot of manual tweaking and work. I would like to use the Kiro-CLI to improve this and distribute the different custom Kiro CLI agents (use the documentation here: https://kiro.dev/docs/cli/custom-agents/). My first question is if the Kiro CLI would be able to "coordinate" or serve as an execution framework to implement a set of agents that review a given CV along with editing agents that implement changes into a Word document based on a job description and potentially company information that another agent would retrieve. Do not implement anything yet, this is more a general question.

---

**Assistant:**

Short answer: yes, Kiro CLI is a workable execution framework for what you describe, but with a specific shape. It is not a "multi-agent orchestration runtime" in the sense that one agent calls another like a function. It is a per-session agent runtime where each agent has its own prompt, tool set, MCP servers, and permissions, and where coordination between agents happens through shared artifacts on disk plus shell-level invocation. That model maps cleanly onto your existing pattern in `cli-agents/` (state directories, evidence ledgers, structured mission statements).

Here is what the documentation supports and what it does not, framed for your CV use case.

What the framework gives you natively

- Per-agent JSON config in `.kiro/agents/<name>.json` (workspace) or `~/.kiro/agents/` (global) with `prompt`, `tools`, `allowedTools`, `mcpServers`, `resources`, `toolsSettings`, `hooks`, `model`. Reference: [configuration reference](https://kiro.dev/docs/cli/custom-agents/configuration-reference/).
- Tool gating per agent. A "CV reviewer" agent can be read-only on the CV file. A "CV editor" agent can have `write` enabled but with `toolsSettings.write.allowedPaths` narrowed to the document directory and a temp dir.
- MCP servers per agent. You can give the company-research agent a fetch/web MCP and nothing else.
- Resources auto-loaded into context (project README, steering, skills) without each agent needing to re-discover them.
- Hooks at `agentSpawn`, `userPromptSubmit`, `preToolUse`, `postToolUse`, `stop`. These are shell-command hooks, useful for audit, formatting, validation, and limited automation, but they do not return data into the conversation.
- Switching is via `/agent swap` interactively, or `kiro-cli --agent <name>` to start a session against a specific agent.

What the framework does not give you

- No built-in agent-to-agent invocation primitive. There is no `call_agent("cv-editor", ...)` tool in the public CLI surface. Cross-agent workflow has to be expressed either as a human swapping agents, or as a coordinator agent shelling out to `kiro-cli` itself.
- No conversation-level shared memory across sessions. Each agent session is independent. State has to be persisted on disk. Your current pattern (`.kiro/agent-state/<agent-name>/...` with `resume_state.md`, evidence ledgers, draft artifacts) is exactly the right shape for this and would carry over.
- No native Word `.docx` tool. Editing a Word document means an MCP server you build (e.g., a small Python MCP that wraps `python-docx`) or a plain Python script invoked via `shell`. Either is fine, but it is yours to provide.
- Hooks cannot replace orchestration. They run shell commands, not agent turns. They are for guardrails and side effects, not for "now run the editor agent".

Two coordination shapes that fit your existing style

1. Human-driven, artifact-passed (lowest risk, mirrors what your other agents already do)
   - `cv-reviewer-agent` — reads `cv.docx` (via a docx-to-markdown step) and the job description, writes findings to `.kiro/agent-state/cv-reviewer-agent/review.md`.
   - `job-research-agent` — fetches/derives company info, writes `.kiro/agent-state/job-research-agent/company_brief.md` and `jd_analysis.md`.
   - `cv-editor-agent` — read-only on review/brief artifacts, write-allowed only on the working `.docx` (and a `.bak` copy), applies edits via a `docx_edit` MCP tool or a `shell`-invoked Python script.
   - User runs them in sequence with `/agent swap`. Each agent has a clear mission, a state directory, and termination criteria. This is identical in spirit to `issue-intake`/`spec-review`/`dead-code` already in your repo.

2. Coordinator agent that shells out
   - A `cv-pipeline-coordinator` agent whose tools are essentially `read`, `shell`, and a small set of MCPs.
   - Its prompt instructs it to invoke `kiro-cli --agent cv-reviewer-agent` (and the others) as subprocesses, pass inputs via stdin or files, and consume their artifacts from the state directories.
   - Pros: single-command run. Cons: more brittle, harder to debug, depends on each child agent emitting machine-readable artifacts. The non-interactive ergonomics of `kiro-cli` should be verified before committing to this shape (it is not detailed in the public docs page set above).

For your specific CV scenario, the natural agent split is

- cv-input-agent: extracts CV content into a normalized intermediate (markdown or JSON) so downstream agents reason in text, not binary `.docx` bytes.
- jd-analysis-agent: parses the job description into requirements, keywords, seniority, must-haves vs nice-to-haves.
- company-research-agent: web research (MCP fetch), produces a short brief plus citations. Read/web-only, no write tools.
- cv-review-agent: scores/critiques the current CV against jd-analysis + company-brief, produces a change list with rationale. Read-only on docs, write-only on its state dir.
- cv-editor-agent: applies the change list to the `.docx` via a `docx` MCP/script. Write tool restricted to the document path. This is the only agent that touches the binary document.

Things worth deciding before you build

- Where Word editing happens. An MCP server is reusable across agents and across CLI/IDE; a one-off Python script is faster to ship. Given you already have `templates/` and `scripts/`, a small MCP server is probably the better long-term call.
- Whether you want a coordinator agent or keep it human-driven via swap. Your existing agents (issue-intake, dead-code, doc-review) lean human-driven, which is consistent and easier to reason about.
- The handoff format between agents. Markdown with a fixed schema (your current style) is fine; JSON sidecars make programmatic orchestration easier if you go the coordinator route.
- Distribution. Workspace agents live under `.kiro/agents/`; global ones under `~/.kiro/agents/`. For sharing across machines or teammates, workspace agents in version control is the cleanest path, mirroring how `cli-agents/` is organized today.

Net: the Kiro CLI can serve as the execution framework here. The "coordination" layer is light, file-based, and the same pattern you have already proven with your existing agents. The Word editing piece is the one capability that is not in the box and that you will need to provide, most cleanly as a small dedicated MCP server.

---

**User:**

What Kiro usually does when I ask for editing word files is that it writes a small script into a tmp directory that uses a python library to make the corresponding changes. Wouldn't it be possible to have such an agent?

---

**Assistant:**

Yes, absolutely. That is actually the more pragmatic path and fits the Kiro CLI model well. You do not need a custom MCP server for `.docx` editing. You can have a `cv-editor-agent` whose job is, exactly as you describe, to write a short Python script into a tmp directory, run it via `shell`, verify the result, and clean up. The pattern is well-supported by what the configuration reference exposes.

Why this works cleanly

- The agent only needs three capabilities: read the inputs (CV, change list, job analysis), write the script and the modified document, and execute the script. That maps to the built-in `read`, `write`, and `shell` tools.
- `toolsSettings` lets you scope each of those:
  - `write.allowedPaths` restricted to the document directory plus a tmp dir under the workspace.
  - `shell.allowedCommands` / `deniedCommands` restricted to `python` invocations against scripts in the tmp dir, and explicitly denying anything destructive.
- `hooks.preToolUse` and `postToolUse` give you guardrails around shell execution (audit log, refuse if the script targets paths outside the allowed area, run a checksum/size sanity check on the resulting `.docx`).
- The agent's prompt enforces the workflow: always operate on a copy, always produce a diff summary, never overwrite without a backup.

What the agent loop looks like in practice

1. Read inputs: original `.docx`, the change list (from cv-review-agent), optionally jd-analysis and company-brief.
2. Make a working copy (e.g., `cv.working.docx`) plus a timestamped backup.
3. Write a Python script to `tmp/cv-editor-agent/<timestamp>/apply_changes.py` using `python-docx` (or `docx2python` for read-side parsing). The script is idempotent and parameterized: input path, output path, change list path (JSON or markdown).
4. Run it via `shell`: `python tmp/cv-editor-agent/<timestamp>/apply_changes.py --in ... --out ... --changes ...`
5. Verify: re-read the resulting docx, diff it against the original at the text level, confirm the change list was applied, record the verification output.
6. Persist the script and a run log under the agent's state directory so the run is reproducible. Cleanup of the tmp dir is optional and configurable.

Concrete config sketch (illustrative, not yet implemented)

```json
{
  "name": "cv-editor-agent",
  "description": "Applies a structured change list to a CV .docx by writing and running a small python-docx script.",
  "prompt": "file://./cv-editor-prompt.md",
  "tools": ["read", "write", "shell"],
  "allowedTools": ["read"],
  "toolsSettings": {
    "write": {
      "allowedPaths": [
        "tmp/cv-editor-agent/**",
        ".kiro/agent-state/cv-editor-agent/**",
        "cv/working/**"
      ]
    },
    "shell": {
      "allowedCommands": [
        "python tmp/cv-editor-agent/.*/apply_changes\\.py .*",
        "python -m pip show python-docx",
        "python -c \"import docx; print\\(docx\\.__version__\\)\""
      ],
      "deniedCommands": [
        "rm .*", "del .*", "rmdir .*",
        "git .*", "curl .*", "wget .*",
        "pip install .*"
      ]
    }
  },
  "resources": [
    "file://.kiro/steering/**/*.md",
    "file://docs/cv-editor/**/*.md"
  ],
  "hooks": {
    "preToolUse": [
      {
        "matcher": "execute_bash",
        "command": "powershell -NoProfile -Command \"$input | Out-File -Append -FilePath tmp/cv-editor-agent/audit.log\""
      }
    ]
  },
  "model": "claude-sonnet-4"
}
```

A few notes specific to your setup

- The "no environment variables" rule applies here. The script must take all paths and configuration as CLI arguments or read them from a config file the agent writes; it must not rely on env vars to locate the CV, the output, or any credentials.
- `python-docx` does not preserve every styling nuance for complex Word documents (custom XML parts, some advanced field codes, tracked changes). For typical CV layouts (paragraphs, runs, bullet lists, simple tables, basic styles) it is fine. If your CV uses heavy formatting, plan for the editor agent to operate on a structured intermediate (e.g., a paragraph-and-run JSON model) and have a separate "apply" step that does targeted edits rather than a round-trip rewrite.
- Keep edits surgical. The Python script should locate paragraphs/runs by stable anchors (heading text, role/company markers, bullet IDs you assign during ingestion) rather than by index, so re-runs are stable and a partial change list does not reflow the whole document.
- Verification is worth investing in. After the script runs, re-open the docx, extract the changed paragraphs, and compare against the requested change list. Record pass/fail per change in the state directory. This is the equivalent of the "evidence ledger" pattern you already use elsewhere.
- Backups are mandatory. The agent's prompt should make this non-optional: every run produces `cv.<ISO-timestamp>.bak.docx` before any edit. Trivial to enforce in the script itself.

Where this sits relative to the MCP option

A dedicated docx MCP server is the better choice if you expect to do this often, want the same capability across multiple agents, or want stronger isolation than `shell`-with-allowlists. A script-writing agent is the better choice if you want to ship something now, keep the surface area small, and reuse a pattern your team already understands. The two are not mutually exclusive: start with the script-writing agent, and if it gets used heavily, lift the proven script logic into an MCP server later. Same code, just wrapped differently.

So: yes, the agent you described is exactly the right shape for Kiro CLI, and it slots into your existing `cli-agents/` layout the same way the others do.

---

**User:**

Let's start creating a set of these agents and create a directory cli-agents/cv for this where all of the prompts and json files for this are to be stored. I think the notebook provides an adequate overview on what kind of agents we need and what they input looks like: All agents operate on a given Word document (the CV) and a given job description (the HTML, txtx, PDF or other file). Optionally, there should also be a way to provide a motivational letter (Word Document), but this is not required. They use an agent state mechanism like the other agents in cli-agents/ so that they can recover aborted or previous sessions.
Let's look at the agents one by one: I think we need a "CV Orchestrator Agent" that knows about all the other agents and distributes tasks to them so that we implement a workflow similar to what the notebook has. This agent uses the agent you have outlined above (cv-editor-agent) to edit word files and also passes the ability to edit word files to some of the delegate agents "downwards" through this agent. The orchestrator is the entry point to the agentic workflow and this agent has the goal to produce a 2-page CV document that has the highest likelihood of the candidate to be invited for an interview. Additionally, we may provide this agent with a "bullet point database" or "extensive CV" which is a document that contains information about skills, work history or other items that are currently not reflected on the CV. This allows the agent to pull in items from this "database" to align the skills displayed on the CV with those requested/required/desired by the job description. This "database" can be another Word Doc, a Markdown file, a txt file or a PDF.
There is a spell checking and formatting agent that will use the Word document to verify and check for spelling or formatting issues. This agent will just flag the issues and the editor will be used to resolve these one by one until all of the formatting an spelling issues are resolved.
Then there is a language and content reviewer agent that will review the language of the CV critically and suggest edits/changes without looking at the job description. It will just review the CV as it is to determine if there are areas of improvement and flag these similar to what we have in the notebook. Based on these suggested changes, the CV will be edited until all areas of improvement are resolved.
Next, there is an agent that review the CV and the job description and identifies important areas of alignment, but also most criticially reviews if there are gaps. This agent then uses (if available) the aforementioned database to determine approaches how these areas could be addressed and how to improve the CV to improve the alignement with the job description. Thisis the only agent that may ask for feedback from the user by asking questions for additional information. This agent will try to find out if there are potential areas or skills not reflected in the database or the current CV, but requested by the job description, so that the alignment with the job description is higher. for instance, let's say the job description asks for "skill X", but there is no indication that the candidate has skill X. Then this agent is going to ask "The current material does not indicate you have skill X, can you provide me with an indication on or an example of an acitivity that demonstrates skill X?". If the user answers here with a set of points or results, then this agent should use this information to generate a corresponding item or mention this on the CV. Furthermore, if possible, the agent must integrate the answer of the user into the database (if possible). IF the user answers with "Sorry, I do not have skill X" (or something to that point), then this is an accepted gap.
We laos need an ATS agent that performs the role of automated hiring systems and their quirks, to make sure the document aligns with these systems and does not contain content that would be rejected or is unreadable by these systems. Similar to the other agents, this agent flags corresponding items and then uses the editing agent to resolve them.
We also need a hiring manager review agent that does a review of the CV to perform a critical review of the CV against the given job description. This agent will just perform the review and then return the findings along with a decision on whether to invite the canddate or not. The orchestrator will be asked to resolve these items in collaboration with the other agents in a loop.
In general, the orchestrator will use a loop to iteratively modify the CV until it passes the quality gates imposed by the different agents (with the exception of accepted gaps, see above). To avoid endless looping we will impose a max of 40 iterations, but this should never be hit.
DO we need a spec for all of this? 

---

**Assistant:**

Yes. This is exactly the shape of problem a spec earns its keep on, and I would not start writing JSON files without one. Here is why, concretely.

Why a spec is warranted

- Multiple interlocking artifacts. You are describing seven or eight agents whose prompts depend on contracts between them (handoff file formats, state layout, who-applies-edits). Getting any contract wrong rewrites all the others.
- A non-obvious architectural decision up front. Kiro CLI agents do not natively call other agents. Your orchestrator "delegating downward" has to be expressed as one of: a single mega-agent that internally simulates the others by following sub-prompts, an orchestrator that shells out to `kiro-cli --agent <name>` per delegate, or a human-driven swap pattern with the orchestrator producing a plan. Each choice changes every other agent's prompt and tool surface. This is a one-time decision, and it belongs in design, not in prompt copy.
- Convergence semantics for the quality-gate loop. "Iterate until all agents pass, max 40" is well-defined in spirit but not in mechanics. We need rules for oscillation (ATS removes a special character that the language reviewer wanted), accepted-gap tracking, what counts as "pass", and what to do when two agents disagree.
- Multi-format input normalization. JD as PDF/HTML/TXT/DOCX, the database in any of those formats, plus a Word CV. We need one normalization layer specified once, not five times.
- The user-question loop is unique to the alignment agent. That agent's question batching, gap-acceptance handling, and database append-back behavior all need a concrete contract.
- Page-budget enforcement. "Two pages" is a hard physical constraint that has to be measured somehow (rendered docx → page count via a tool) and turned into a feedback signal for the orchestrator. That mechanism needs a design.
- Reproducibility and audit. Your existing agents lean heavily on evidence ledgers and resume-state files. Across seven agents that share artifacts, the directory layout and file schema must be designed together.

Specifically, the questions the spec needs to settle before any prompt is written

1. Orchestration model. Subprocess-based (`kiro-cli --agent ...`), single-agent-with-internal-roles, or human-driven swap with an orchestrator that emits a plan. Pick one and commit.
2. Edit authority. Only `cv-editor-agent` writes to the docx, ever. Reviewers produce structured findings; the orchestrator translates findings into a change list; the editor applies it. (I think this is the only sane model, but the spec should state it explicitly.)
3. Findings schema. A single JSON or markdown-with-frontmatter schema used by every reviewer, with stable fields: `id`, `category`, `severity`, `anchor` (paragraph/run reference), `current`, `proposed`, `rationale`, `source_agent`, `status` (open/applied/accepted-gap/wont-fix).
4. State directory layout. Per-agent state under `.kiro/agent-state/<agent>/` for evidence and resume, plus a shared `cv-workflow/` directory for the rolling artifacts (current docx, normalized JD, normalized database, change-log, accepted-gaps register, iteration log).
5. Input normalization. One ingestion step turns CV/JD/database/cover-letter into a canonical intermediate (paragraph/run JSON for the docx, plain markdown for the others) so reviewers reason in text. PDF and HTML parsers chosen here once.
6. Database append-back policy. When the alignment agent gets new info from the user, where does it go? Default: never write to the user's original database file; write to a workspace-managed `database.augmented.<format>` and surface a clear instruction at the end of the run for the user to merge it back if they choose.
7. Convergence rules. Per-agent pass criteria, the global "two-page hard constraint" check, oscillation detection (same finding appearing in two consecutive iterations after being "fixed"), the 40-iteration cap behavior (terminate with a structured "did not converge" report), and how accepted gaps are excluded from further checks.
8. ATS toolset. Whether ATS checks are pure-rule (regex/heuristics in the agent's prompt operating on extracted text) or use an external tool. Affects what tools the ATS agent gets.
9. Spell/format tooling. Which library (e.g., `python-docx` for structure, an external spell library or LLM-based check for prose), and which language(s) for the spell checker.
10. Page count measurement. `python-docx` cannot render. Options: convert to PDF via LibreOffice/Word headless and count pages, or use a heuristic on character/line counts. Spec the chosen approach.
11. Privacy and tool scoping. Each agent's `allowedTools`, `toolsSettings.write.allowedPaths`, and shell allowlists. The "no environment variables" steering rule applies; everything is paths-as-arguments.

Proposed spec structure (matching what your repo already does for other agents)

- requirements.md — user stories, the eight agents, the loop semantics, accepted-gap behavior, the 2-page hard constraint, max-iteration safeguard, multi-format inputs, reproducibility requirements.
- design.md — orchestration model decision, findings schema, state directory layout, edit authority and change-list flow, input normalization, page-count measurement, ATS approach, spell/format tooling, database append-back policy, error and convergence handling.
- tasks.md — incremental implementation plan: ingestion utilities, shared schemas, editor agent, reviewer agents, alignment agent (with its user-question protocol), hiring-manager and ATS agents, orchestrator, end-to-end smoke test on a sample CV/JD pair.

What I would not put in the spec

- Verbatim prompt text for the agents. Those go into per-agent prompt files under `cli-agents/cv/<agent>/` once design is locked. The spec defines contracts; the prompts implement them.

If you agree, I will start the spec workflow with `requirements.md` first, focused on the eight agents and the loop semantics, and we iterate from there. Before I do, two things worth confirming so the requirements are not built on guesses:

- Orchestration model preference. My recommendation is the subprocess model (orchestrator shells out to `kiro-cli --agent <delegate>` per call) because it keeps each agent's prompt small and focused, and because your existing agents already produce machine-readable artifacts on disk that compose naturally. Alternative is a single orchestrator agent that internally plays all the reviewer roles via sub-prompts; cheaper to run, harder to maintain. Which do you want as the working assumption?
- Database write-back. Are you OK with the rule "never modify the user's original database file; produce a side-car augmentation document and tell the user to merge"? If you want in-place updates, that changes the editor agent's permission scope and the database needs a stable structured format.

---

**User:**

Yes, let's start the spec workflow then to create a requierements.md file.

---

**Assistant:**

Looking at the existing spec convention in this project (from `fix-hook-format/requirements.md`) and the notebook, I'll draft the requirements following the same User Story + Acceptance Criteria style.

A few decisions I had to make to keep the requirements concrete; I've left these explicitly flagged at the end as open questions so you can correct any I got wrong before we move to design:

- The orchestration mechanism (subprocess vs. single-agent vs. swap) is a design concern, not a requirement, so I describe the orchestrator's *behavior* and leave the mechanism for `design.md`.
- Database write-back defaults to "never modify the original; produce a sidecar augmentation file" since you haven't explicitly confirmed yet.
- Motivational letter is accepted as an input but its review/edit workflow is scoped only to spell/format and language passes by default; alignment and hiring-manager passes treat it as supporting context. Flagged for confirmation.
- Spell-and-formatting are combined into a single reviewer agent as you described.

Spec slug: `cv-customizer-agents` (consistent with your existing `fix-hook-*` slugs).

The Kiro Spec Format checker requires the heading to be exactly `# Requirements Document`. Let me fix that.

Diagnostics clean. Drafted `.kiro/specs/cv-customizer-agents/requirements.md` with 16 requirements covering the seven agents, the orchestrator loop, two-page constraint, accepted gaps register, database handling, state/resumability, tool permissions, and the directory layout under `cli-agents/cv/`.

Before we move to design, I need your call on the eight open questions I left at the bottom of the file (OQ-1 through OQ-8). The most consequential ones:

- **OQ-1 (orchestration mechanism)**: my working assumption is subprocess-based delegation (orchestrator shells out to `kiro-cli --agent <delegate>`). This keeps each agent's prompt small. The tradeoff is that we depend on `kiro-cli` having a usable non-interactive invocation mode, which I have not yet verified in your environment. If you want a safer bet, the alternative is a single orchestrator agent that internally plays each reviewer role via sub-prompts, all in one chat session.
- **OQ-2 (database write-back)**: defaulting to "never modify the user's original file; produce a sidecar `augmented_database.md`". Confirm or override.
- **OQ-3 (motivational letter scope)**: requirements currently say only the spell/format reviewer runs against it. The notebook actually runs the same passes against the letter as against the CV. Three options listed.
- **OQ-7 (two-page strict vs. lenient)**: requirements currently make it a hard-fail; alternative is "emit a near-miss report at iteration cap".

The other open questions (page-counting mechanism, spell tooling, ATS technique, hiring-manager gate composition) are more naturally settled in `design.md` — we can defer those.

Once you answer OQ-1 through OQ-3 (and OQ-7 if you want to override the default), I will revise the requirements document and we can move on to `design.md`.

---

**User:**

Let's discuss QQ-1: My assumption was that the Kiro-CLI has the ability to pass tasks between different agents, i.e., the orchaestrator knows that it should pass the CV for review to the hiring manager and that all of this would run within a single Kiro-CLI session. Review the Kiro CLI documentation for custom agents and how they operate / work together.

---

**Assistant:**

Your assumption was right and my earlier answer was outdated. Kiro CLI does have a native subagent mechanism. Let me read the actual docs and confirm the details before updating the spec.

You were right and my earlier answer was wrong. Kiro CLI does have first-class subagent delegation that runs inside a single session. Here are the relevant facts straight from the docs, with the implications for our spec.

What the docs actually say

- A custom agent can spawn other agents as subagents in the same session by including `subagent` in its `tools` array. Without it, the agent cannot delegate. ([subagents reference](https://kiro.dev/docs/cli/chat/subagents/))
- A main agent can spawn up to four subagents at once.
- Each subagent runs in its own isolated context and inherits the tools, `toolsSettings`, and `allowedTools` from whichever target agent's config it uses.
- Subagents return findings via a built-in `summary` tool that is included autom

---

**User:**

Continue!

---

**Assistant:**

Your assumption was correct. I owe you a correction. Kiro CLI does have a native subagent mechanism, and it is exactly the shape you described: one main session, the orchestrator delegates to other agents in-session, results return to the orchestrator automatically.

What the docs actually say (sources: [Subagents](https://kiro.dev/docs/cli/chat/subagents/), [Delegate (deprecated, replaced by Subagents)](https://kiro.dev/docs/cli/experimental/delegate/))

- Subagents run in their own isolated context, spawned by the main agent. The main session stays a single Kiro CLI session; you do not shell out to another `kiro-cli` invocation.
- Up to four subagents can run at once, in parallel or chained as a DAG with dependencies.
- Each subagent inherits the `tools`, `toolsSettings`, and `allowedTools` of whichever custom agent configuration it uses. So per-agent permissions still apply.
- A custom orchestrator agent must include `subagent` in its `tools` array (or `@builtin`). Without it, it cannot delegate.
- Results return to the main agent automatically when the subagent finishes (it calls a built-in `summary` tool).
- There is a built-in review-loop construct: a stage can loop back to an earlier one based on a trigger string in the output (e.g., `NEEDS_CHANGES`), with a `max_iterations` cap that the platform itself enforces (capped at 10 by Kiro, regardless of the value requested). The agent describes the intent in plain language; the platform builds the looping pipeline.
- Permissions for delegation are controlled in the orchestrator's config:
  - `toolsSettings.subagent.availableAgents` — which agents the orchestrator may spawn (glob patterns supported).
  - `toolsSettings.subagent.trustedAgents` — which spawned agents run without per-call approval prompts.
- Non-interactive subagents that hit a tool requiring approval fail fast unless they are in `trustedAgents`. This matters for our reviewers, which should run unattended.

What this changes in our spec

Three concrete updates are warranted:

1. **OQ-1 is now answered.** The orchestration model is "in-session subagent delegation". No subprocess shelling, no manual `/agent swap`, no single mega-agent simulating roles. The CV Orchestrator Agent has `subagent` in its `tools`, lists the six delegate agents in `toolsSettings.subagent.availableAgents`, and adds the non-interactive ones to `trustedAgents`. The JD Alignment Reviewer is the one exception: it must be allowed to ask the user clarifying questions, which means it cannot run as a fully autonomous subagent in the same way as the others — needs design attention (see below).

2. **The iteration loop has a platform-native expression.** Kiro's review-loop construct (target / trigger / max_iterations) maps cleanly onto the "iterate until reviewers pass" requirement. However, the platform caps `max_iterations` at 10. Our requirements currently set the cap at 40. We need to choose between:
   - Adopting the platform cap of 10 and accepting it as the upper bound. Probably fine for this workload — if the CV is not converging in 10 passes, something is structurally wrong.
   - Implementing our own loop on top of subagent delegation (the orchestrator decides when to re-delegate based on Findings on disk), bypassing the native review-loop construct. More flexible, more code, but free of the 10-iteration cap.
   - Combining both: use native review loops for tight per-stage refinement (e.g., editor → spell/format reviewer until the spell/format gate passes), and an orchestrator-level loop on top for the global "all gates pass" condition. This is probably the right answer.

3. **The JD Alignment Reviewer needs a different runtime mode.** A subagent that is `is_interactive=false` (the default for delegated tasks) cannot prompt the user. Two reasonable options:
   - The JD Alignment Reviewer is *not* run as a subagent. The orchestrator surfaces its turn back into the main session (effectively a planned context switch) so the user can answer questions in the main chat. After answers arrive, the orchestrator re-delegates the rest of the iteration.
   - The JD Alignment Reviewer runs as a subagent in two phases: phase 1 is a non-interactive analysis that emits a `NEEDS_USER_INPUT` artifact listing the questions; the orchestrator surfaces the questions to the user; the user answers; the orchestrator delegates phase 2 (also non-interactive) which integrates the answers and emits final Findings. This keeps every reviewer non-interactive at the subagent level and confines user interaction to the main agent.

   I lean toward option 2. It keeps the subagent permission model uniform and the human-in-the-loop control flow explicit at the orchestrator level, instead of having one reviewer with special interactivity.

Concrete changes I'd like to make to `requirements.md`

- Replace OQ-1 with a confirmed decision: in-session subagent delegation.
- Update Requirement 2 (orchestrator) to specify it uses Kiro's native subagent mechanism, including `availableAgents` and `trustedAgents` settings.
- Update Requirement 6 (JD Alignment) to split the agent into the two-phase pattern: non-interactive analysis → orchestrator-mediated user Q&A → non-interactive integration.
- Update Requirement 10 (iteration loop) to allow the design phase to choose between native review loops, an orchestrator-driven loop on disk-based state, or a hybrid. Note the platform's 10-iteration cap on native review loops, and adjust our 40-iteration cap discussion accordingly: keep 40 as the orchestrator-level safeguard if we go hybrid; reduce to 10 if we use native review loops exclusively.
- Update Requirement 15 (tool permissions) to require the orchestrator's config include `subagent` in `tools` and configure `toolsSettings.subagent.availableAgents` / `trustedAgents`.
- Update OQ-1 to closed; OQ-7 (strict vs. lenient on two-page) and OQ-2/OQ-3 still open.

Two questions for you before I edit the requirements

- **Iteration cap with the platform's 10 limit.** Are you OK keeping the 40-iteration safeguard as an orchestrator-level cap (built on top of subagent delegation, not on native review loops)? Or do you prefer to use native review loops and accept the platform's hard cap of 10? My recommendation: keep 40 at the orchestrator level. Reasoning: the platform's review-loop construct is a single-stage refinement, but our convergence condition involves *all* gates simultaneously plus a global page-count constraint, which is the orchestrator's job to evaluate, not a single stage's.
- **JD Alignment two-phase pattern.** Are you OK with splitting JD Alignment into "analysis → user Q&A surfaced through orchestrator → integration"? It is slightly more orchestration logic but keeps every reviewer non-interactive at the subagent level, which is the cleaner permission model.

Once you answer those plus the still-open OQ-2 (database write-back), OQ-3 (motivational letter scope), and OQ-7 (strict two-page), I will revise the requirements in one pass and we move to design.

---

**User:**

I accept the 10 iterations hard limit. That is fine.
I also accept the 2-phase approach but with a caveat: There may be cases where the agent needs to repeat this 2-phase pattern and this should be allowed. Furthermore, the orchestrator should ask the questions one by one and not bombard the user with 10 questions at once. This also makes bookkeeping easier.
QQ-2: The write-back is important to improve over time. As I will use git to version files, we do not necessarily need a separate backup mechanism.
QQ-3: Motivational letter is in scope. We will improve this in a further iteration of this, but in general, it needs to match the CV and the JD and also needs to undergo the same editing and review process. The entire process needs to result in a CV and optionally a motivational letter that server as a package to "sell" the candidate.
QQ-4: We need a reliable mechanism to count the pages. I do not care how this is implemented, but I assume if we can access the word document in docx format that we will be able to derrive the page count from this. If needed, we can make a separate agent for accessing/analyzing word document meta data.
QQ-5: The agents use (powerful) LLMs, so if we ask an agent to find all spelling mistakes or formatting issues in a document, we essentially ask this to the LLM. Hence, we can rely on the LLM that serves the agent we use.
QQ-6: Do some research, if there is a (set of) packages that we can use for this and then run them as a python script or something similar (which is made available to the agent as a tool), then by all means, we should do this.
QQ-7: The default length should be 2 pages. While it can be explicitly overridden by the user, we should keep this as a default to make sure the CV is not longer than needed.
QQ-9: No, every reviewer gate must idenpendently pass. It is not sufficient to have the HM accept.

---

**Assistant:**

Good, all decisions are clear. Let me do the OQ-6 research first, then revise the requirements in one pass.

Research note on OQ-6: there isn't a single authoritative ATS-validation library, but the deterministic checks that matter (text-boxes, headers/footers, multi-column structures, embedded images, special-character round-trip, keyword presence) are cleanly addressable with `python-docx` for structural inspection plus a parser like `pdfminer.six` to verify what an ATS-style text extractor would actually see. That's what I'll require: deterministic library-based checks rather than pure LLM heuristics.

Now revising the requirements with all your decisions baked in.

---

**User:**

Continue working here!

---

**Assistant:**

Research check on OQ-6 packages: there are usable Python options (`python-docx` for structure, `ats-resume-scorer` and similar for ATS heuristics, plus the notebook's existing `python-docx`-based approach). Concrete library choices belong in design, not requirements; the requirements just need to commit to "Python tooling where reliable, LLM otherwise".

Now revising the requirements in one pass to lock in your decisions. Most changes are throughout multiple sections, so rather than chain many small replacements I'm rewriting the file cleanly.

Diagnostics clean. Requirements revised end-to-end.

What changed in this pass

- **Orchestration committed to in-session subagent delegation** (D-1). Requirement 2 now specifies `subagent` in `tools` and the `availableAgents`/`trustedAgents` configuration; Requirement 15 makes those configurations mandatory.
- **Iteration cap reduced to 10** (D-10) to match Kiro CLI's native review-loop maximum. Requirement 10 also explicitly leaves the choice between native review loops and an orchestrator-level loop on disk state for design.
- **JD Alignment Reviewer is now two-phase, repeatable** (Requirement 6, D-9). Phase 1 emits questions to a structured artifact. The orchestrator surfaces questions one at a time. Phase 2 runs after answers are collected. The pattern repeats within a single iteration when Phase 2 surfaces new gaps.
- **Motivational letter is fully in scope** (D-3). New `Letter_Working_Copy` and `Application_Package` glossary entries; Requirements 4–8 all explicitly cover the letter; the Hiring Manager gate now also evaluates package coherence.
- **Page constraint is now per-document with overridable defaults** (Requirement 11, D-7). 2 pages for CV, 1 page for letter, both overridable at invocation.
- **Database writeback is in place when format permits** (Requirement 13, D-2). Markdown and plain text → in-place writeback to user's file with provenance metadata; `.docx` and PDF → sidecar; no workflow-internal backups since git handles versioning.
- **Spell/format reviewer is LLM-only** (Requirement 4.4, D-5). Matches the notebook.
- **ATS reviewer is hybrid** (Requirement 7.3-7.4, D-6). Deterministic Python tooling for structural checks (script-and-shell pattern, same as the editor), LLM for keyword matching. Specific libraries deferred to design.
- **Hiring Manager gate does not unblock convergence** (Requirement 8.6, D-10). Every reviewer's gate must pass independently.
- **Findings schema gained `target_document`** (Requirement 9) so reviewers and the editor can route per-document Findings cleanly.
- **All open questions closed at the requirements level**, with the deferred-to-design items listed explicitly.

Two small things worth flagging before we proceed to design

- The orchestrator's "ask questions one at a time" rule (Requirement 6.6 / 2.13) means a single iteration may include multiple round-trips with the user before the editor runs. That is correct given your bookkeeping preference, but it does mean that a single iteration can take noticeably longer than a fully automated one. I am calling this out so it does not surprise us in design or in operation.
- Requirement 7.4 grants the ATS Reviewer `shell` access scoped to `tmp/ats-reviewer-agent/**`. That means it now has the same script-and-shell pattern as the editor. Per your earlier note, you are comfortable with this approach generally, so I am treating it as decided. If you want ATS to remain LLM-only and defer all deterministic tooling to a separate utility agent, say the word and I will adjust.

Ready to proceed to `design.md` when you are. Before I start, one quick orientation question: do you want design organized agent-by-agent (one section per agent, with its tool config, prompt outline, and state shape) or layer-by-layer (orchestration model, findings schema, page-counting mechanism, then per-agent details)? Both work; layer-by-layer tends to read better when the cross-cutting decisions are the bulk of the design, which is the case here.

---

**User:**

Continue with the design and task docs. I like the layer by layer approach

---

**Assistant:**

Got the existing convention (Property-based correctness section is part of it). One critical research result for design:

- `python-docx` cannot reliably determine page boundaries — that's a function of the rendering engine. Sources: [python-docx pagebreak module note](https://python-docx.readthedocs.io/en/stable/_modules/docx/text/pagebreak.html), Stack Overflow Q&A. So the design must commit to a render-and-count approach (LibreOffice headless or `docx2pdf` on Windows-with-Word).

Now writing `design.md`. This is going to be long — splitting across writes.

---

**User:**

Continue working!

---

**Assistant:**

Research is sufficient to commit design decisions. Key takeaways that drive design:

- **Page count**: `python-docx` cannot reliably determine soft page breaks (confirmed via [python-docx pagebreak module docs](https://python-docx.readthedocs.io/en/stable/_modules/docx/text/pagebreak.html) and [Stack Overflow: docx page detection](https://stackoverflow.com/questions/23980268/find-a-new-page-in-a-word-document)). Reliable path is to convert `.docx` → PDF via a headless renderer, then count PDF pages.
- **ATS deterministic checks**: `python-docx` reads structure (text boxes, images, headers/footers, columns); existing ATS libraries are LLM-wrappers themselves. In-house helper script is the cleaner path.

Writing the design now.

---

**User:**

Continue working here!

---

**Assistant:**

Important design finding from the research: `python-docx` cannot reliably determine page count, because soft page breaks are computed by Word's rendering engine and are not stored in the `.docx` ([StackOverflow](https://stackoverflow.com/questions/23980268/find-a-new-page-in-a-word-document), [python-docx pagebreak docs](https://python-docx.readthedocs.io/en/stable/_modules/docx/text/pagebreak.html)). So page counting must go through a real renderer (LibreOffice headless → PDF, then count PDF pages). That decision is now baked into the design below.

Writing `design.md` layer-by-layer.

The spec format checker needs a `## Components and Interfaces` section and properties as `### Property N: Title` headings. Let me fix both.

Now I need to add a `## Components and Interfaces` section. The per-agent specification is the natural fit. Let me add it after the permissions layer, restructured as a proper Components and Interfaces section.

Two format issues: the "Property reflection" subheading is being parsed as a malformed property, and the validates references need the exact `**Validates: Requirements X.Y**` format. Let me check the exact text and fix.

Design is clean. Now the tasks document. I'll structure it as an incremental implementation plan: shared scripts first (the testable core), then schemas, then agents bottom-up (editor before orchestrator), then the orchestrator, then end-to-end validation.

The tasks format checker wants `## Overview`, `## Tasks`, `## Task Dependency Graph`, and `## Notes` sections. Let me restructure.

The dependency graph section needs a JSON code block with "wave" definitions. Let me add that.

All three spec documents are complete and pass the Kiro spec-format checks. Here's the full spec at `.kiro/specs/cv-customizer-agents/`:

- **requirements.md** — 16 requirements, EARS-style acceptance criteria, all eight original open questions closed and recorded as decisions D-1 through D-10.
- **design.md** — layer-by-layer: orchestration model, state/filesystem layout, data models (Finding/Change_List/resume-state with the stable-anchor scheme), normalization, page counting, edit application, conflict/convergence/oscillation handling, JD two-phase Q&A, ATS, tooling/permissions matrix, a Components and Interfaces section per agent, 10 correctness properties mapped to requirements, error handling, and testing strategy.
- **tasks.md** — 18 tasks bottom-up (scripts → schemas → agents → orchestrator → validation), with a wave-based dependency graph.

Key engineering decisions worth surfacing

- **In-session subagent delegation** (your original assumption), orchestrator-driven loop capped at 10. I deliberately did *not* use Kiro's native review-loop construct for the top level, because convergence is a whole-workflow predicate (all gates + page limits across two docs), not a single stage's output check.
- **Page counting must render.** Research confirmed `python-docx` cannot determine soft page breaks; the design renders to PDF (LibreOffice headless, Word COM fallback on Windows) and fails fast if no renderer exists, rather than guessing on a hard gate.
- **Stable paragraph anchors** instead of `python-docx` indices, so Findings and edits survive document mutation across iterations and oscillation detection works.
- **One writer** (the editor) via a closed operation vocabulary, keeping the LLM's edit-time job to filling parameters rather than inventing docx manipulation.

Three things I need you to confirm before implementation (they're listed at the bottom of design.md as "Design Decisions Requiring Confirmation"):

1. **Reviewer write-scope nuance.** Requirement 15.3 says reviewers are "read-only (no write, no shell)". But they need to persist Findings to disk for audit/resumability. My design grants the pure reviewers a narrowly scoped `write` limited to their own `findings/<agent>/` directory. The alternative is to have them return Findings only through the subagent `summary` channel and let the orchestrator serialize them. I recommend the narrow write scope. Confirm?
2. **No dedicated page-count agent.** I folded page counting into an orchestrator-invoked script rather than a seventh-plus subagent, to keep the agent count down. Acceptable, or do you want a dedicated metrics agent?
3. **Renderer.** Is LibreOffice (`soffice`) reliably installed in your environment, or should the Word COM path be primary? This is Windows, so Word automation is likely available.

Once you confirm those, task 1 (scaffold + fixtures) is ready to start.

---

**User:**

To your points:
1. Ok
2. Yes ok.
3. We should Word / MS Office as this will also be used by users for further edits.

---

**Assistant:**

All three confirmed. Decision 3 flips the renderer priority to Word/MS Office primary. Let me update the design to make Word COM the primary page-count path and LibreOffice the fallback, and resolve the three confirmation items in the design doc.

Now let me update the "Design Decisions Requiring Confirmation" section to reflect that all three are now resolved.

Now let me update the README task and the Notes in tasks.md to reflect Word-primary, and add the D-11 decision reference. Let me also update the tooling layer table note about the renderer command.

Now update task 18 which references "three Design Decisions Requiring Confirmation" (now resolved), and check diagnostics.

Let me also add D-11 to the requirements' Decisions Recorded section so the renderer choice is traceable there too, then verify all diagnostics.

All three documents updated and clean. The spec at `.kiro/specs/cv-customizer-agents/` is now complete with all decisions locked in:

- **Decision 1** → reviewers get narrow `write` scoped to their own findings directory; recorded in design's "Resolved Design Decisions".
- **Decision 2** → page counting stays an orchestrator-invoked script, no dedicated agent.
- **Decision 3 / D-11** → Word automation (`win32com` `ComputeStatistics(wdStatisticPages)`) is now the primary page-count engine, LibreOffice the fallback. This is the right call beyond just availability: gating on Word's own pagination means the two-page count the workflow enforces is exactly what you'll see when you open the document to make further edits. Updated in design's page-counting layer, the tooling table, requirements (D-11), and the tasks (task 4, 15, and Notes).

The spec is ready for implementation. Task 1 (scaffold `cli-agents/cv/` layout + test fixtures + gitignore) is the entry point, and the dependency graph lays out the waves from there.

Two practical notes before you greenlight building:

- The deterministic Python core (tasks 2–6) is where the real testable logic lives, and it depends on `pywin32` plus a working Word install on the machine that runs the workflow. Tests for `page_count.py` will need that environment, or the COM path gets monkeypatched and the real check happens in the task 17 smoke test.
- Whenever you want to start implementing, just say which task (or wave) to pick up and I'll execute it against the plan.

Want me to start on task 1, or would you like to review the spec documents first?

---
