# Porting the Kiro Setup Prompt and CLI Agents to Claude Code

**Date:** 2026-06-08
**Scope:** Evaluate `KiroProjectSetupPrompt.v2.txt` and the custom agents under `cli-agents/`, and determine how each can be replicated in Claude Code.

All Claude Code facts below were verified against the official docs at `code.claude.com/docs` (subagents, hooks, memory, skills, plugins, MCP, settings, permissions, CLI reference, output styles, Agent SDK).

---

## 0. Executive summary

**Almost everything ports, but the shape changes.** Kiro packs configuration *and* agents into a single per-agent JSON file with a runtime that hard-enforces tool/path/command allowlists. Claude Code spreads the same concerns across several plain-text files in `.claude/`, and the cleanest way to ship the whole thing is a **plugin** instead of a paste-in prompt.

| Kiro concept | Closest Claude Code equivalent | Fidelity |
|---|---|---|
| Paste-in setup prompt | A `/setup` **skill** (or slash command) that writes config files | High |
| `.kiro/steering/*.md` (`inclusion: always`) | `CLAUDE.md` + `.claude/rules/*.md` (no frontmatter) | High |
| Steering `inclusion: fileMatch` | `.claude/rules/*.md` with `paths:` frontmatter | High (reactive, not proactive) |
| Steering `inclusion: manual` | A user-invocable **skill** / slash command | High |
| `.kiro/hooks/*.kiro.hook` (`userTriggered` + `askAgent`) | A **slash command / skill** (not a settings hook) | High |
| `.kiro/hooks` (`fileEdited`/`preToolUse`/…) | `settings.json` `hooks` (`PreToolUse`/`PostToolUse`/…) | High (richer in CC) |
| `.kiro/settings/mcp.json` | `.mcp.json` | High (no per-tool `autoApprove`) |
| Per-agent JSON custom agents | `.claude/agents/*.md` subagents | High, **except nesting** |
| `subagent.availableAgents` orchestration (CV suite) | Main session + `.claude/agents/` | **Partial** — subagents can't spawn subagents |
| `toolsSettings.shell.allowed/deniedCommands` (regex, enforced) | `permissions.allow/deny` rules in `settings.json` | Medium — global, not per-agent; glob not regex |
| `toolsSettings.fs_write.allowedPaths` | `permissions.deny: ["Edit(...)"]` / `Write(...)` rules | Medium — global; per-agent is advisory |
| `install_agents.py` (copies tree, rewrites paths) | Not needed — files are discovered in place / via plugin | N/A (simpler) |
| Autonomous long-running agents | `claude -p` headless + Agent SDK | High |

**The single biggest semantic difference:** Kiro's `toolsSettings` and steering files are *enforced by the runtime* (a denied command simply cannot run). Claude Code splits this into two layers — **permissions** (`settings.json` allow/deny, genuinely enforced for tools) and **instructions** (`CLAUDE.md`/rules/skills, which guide but do not bind the model). Where Kiro uses one mechanism for both "what the agent is told" and "what the agent is allowed", Claude Code separates them. For hard guarantees you use permissions + hooks; for behavioural guidance you use memory + skills.

**The second biggest:** Kiro lets an orchestrator agent spawn named delegate agents (the `cv/` suite). Claude Code subagents **cannot spawn other subagents** — only the main session delegates. The CV orchestrator pattern needs restructuring (see §3.3).

---

## 1. Claude Code building blocks (the target surface)

A quick reference for the file types you'll be writing. All are plain text, discovered automatically at session start, and checked into git (except `*.local.*`).

| File / dir | Purpose | Format |
|---|---|---|
| `CLAUDE.md` (root) and `~/.claude/CLAUDE.md` | Always-on project / user memory | Markdown; supports `@path` imports |
| `.claude/rules/*.md` | Scoped rules; load when Claude touches matching files | Markdown + optional `paths:` frontmatter |
| `.claude/agents/*.md` | Custom subagents | Markdown + YAML frontmatter |
| `.claude/commands/*.md` | Slash commands (legacy; skills preferred) | Markdown + frontmatter |
| `.claude/skills/<name>/SKILL.md` | Skills (auto- or user-invoked, can bundle files) | Markdown + frontmatter + supporting files |
| `.claude/settings.json` | Permissions, hooks, env, model | JSON |
| `.claude/settings.local.json` | Personal overrides (gitignored) | JSON |
| `.mcp.json` (root) | MCP servers (project scope) | JSON |
| `.claude-plugin/plugin.json` | Plugin manifest (bundles all of the above) | JSON |

**Subagent frontmatter** (the fields that matter for this port): `name`, `description` (drives auto-delegation), `tools` (allowlist), `disallowedTools` (denylist), `model` (`opus`/`sonnet`/`haiku`/`inherit`), `permissionMode`, `skills` (preload), `mcpServers`, `hooks`, `memory` (`user`/`project`/`local`), `maxTurns`, `effort`, `isolation: worktree`, `color`.

**Permission rule syntax** (in `settings.json`): `Bash(npm run test:*)`, `Read(src/**)`, `Edit(/docs/**)`, `WebFetch(domain:github.com)`, `mcp__server__tool`, `Agent(Explore)`. Evaluation: **deny → ask → allow**, deny always wins. Glob-style, not regex.

---

## 2. Part-by-part mapping of `KiroProjectSetupPrompt.v2.txt`

The prompt is fundamentally **an executable runbook** — "detect, merge, create these files, verify". That model translates directly: in Claude Code it becomes a **skill** (e.g. `/project-setup`) whose body is essentially the same runbook, plus a set of **committed config files** that the skill writes. The migration-aware merge logic (Rule 1) stays as prose instructions to the agent either way.

### Global execution rules
| Rule | Port |
|---|---|
| **Rule 1 — migration-aware merge** | Stays as prose in the setup skill. Claude Code does *not* auto-merge config; the skill reads existing files and merges, exactly as today. |
| **Rule 2 — no shell env vars** | Becomes a line in `CLAUDE.md` (always-on) **and** can be hard-enforced with a `PreToolUse` hook on `Bash` that rejects `export`/`setx`/`$env:`. This is *stronger* than Kiro, which relies on steering text alone. |
| **Rule 3 — read complete output** | `CLAUDE.md` rule + the `no-output-shortening` rule file. Advisory (same status as Kiro steering). |
| **Rule 4 — paths / pathlib** | `CLAUDE.md` / coding-standards rule. |
| **Rule 5 — no ad-hoc temp vars** | `CLAUDE.md` / rule. **Note:** the *reason* this rule exists in Kiro — that its command-approval system pattern-matches literal command text and re-prompts on every new variable name — does **not** apply to Claude Code, which matches on permission rules, not literal recall. The rule still has style value but its original motivation is Kiro-specific. |

### Part 0 — MCP servers (configure + verify)
- **Configure:** the five AWS/Strands MCP servers move verbatim into `.mcp.json` (project scope) under a top-level `mcpServers` key. Same `command`/`args`/`env`. Drop the Kiro-only keys: `disabled` → omit or use server enable/disable; `timeout` is supported (milliseconds in CC vs seconds in Kiro — **convert**, e.g. `60` → `60000`); `type: stdio` is supported.
- **`autoApprove` has no per-tool equivalent.** Replace each server's `autoApprove: [...]` list with `permissions.allow` entries in `settings.json`: e.g. `"mcp__awslabs.aws-documentation-mcp-server__search_documentation"`, or blanket `"mcp__awslabs.aws-documentation-mcp-server__*"`.
- **Verify:** Part 0.2's "call one documented tool against each server" becomes a step in the setup skill, or run `/mcp` interactively to see connection status. `claude mcp list` also reports reachability.

### Part 1 — directory structure
Unchanged — it's just `mkdir`. The only Kiro-specific dirs (`.kiro/steering`, `.kiro/hooks`, `.kiro/settings`, `.kiro/specs`) become `.claude/rules`, `.claude/skills` + `settings.json` `hooks`, `.mcp.json` + `settings.json`, and a docs/specs convention of your choosing.

### Part 2 — venv + pre-commit hook
Fully portable; nothing Kiro-specific. The git pre-commit hook is a real git hook, independent of the assistant. Optionally also add a Claude Code `PreToolUse`/`Stop` hook to run ruff, but the git hook remains the source of truth.

### Part 3 — `.gitignore`; Part 4 — pyproject/ruff/mypy/bandit; Part 5 — AWS config; Part 7 — CI/CD
All assistant-agnostic. They produce ordinary project files; the setup skill writes them exactly as the Kiro prompt does. Add `.claude/settings.local.json` and (if desired) `.claude/cv-suite`-style generated dirs to `.gitignore`.

### Part 6 — git wrapper scripts
Fully portable (plain Python using stdlib). **However**, Claude Code ships a first-class `gh` integration and the steering rule "never use `gh`" was a *Kiro-environment* workaround (token stores / SSO cookies). On Claude Code you may prefer to allow `gh` via `permissions.allow: ["Bash(gh *)"]` unless the same corporate-network constraints apply. Keep the wrappers if the constraints are real; otherwise this is a place to simplify.

### Part 8 — steering files → `CLAUDE.md` + `.claude/rules/`
This is the richest mapping. Kiro's `inclusion` field has three values; here's the Claude Code equivalent for each:

| Kiro `inclusion` | Claude Code mechanism |
|---|---|
| `always` | Put the content in `CLAUDE.md`, or in `.claude/rules/<name>.md` **with no `paths:` frontmatter** (loads every session). |
| `fileMatch` + `fileMatchPattern` | `.claude/rules/<name>.md` with `paths: [globs]` frontmatter. **Caveat:** Claude Code loads the rule *when it reads a matching file* (reactive), whereas Kiro can load it proactively. For rules that must always be present regardless, keep them in `CLAUDE.md`. |
| `manual` (referenced via `#[[file:...]]`) | A user-invocable **skill** or slash command; invoke with `/<name>`. |

Concrete per-file plan:

| Kiro steering file | Claude Code home |
|---|---|
| `tech-stack.md`, `pre-work.md`, `coding-standards.md`, `design-principles.md`, `file-organization.md`, `post-activity.md`, `aws-config.md`, `no-environment-vars.md`, `no-output-shortening.md`, `no-cli-temp-variables.md`, `use-lessons-learned.md`, `use-doc-mcp-servers.md`, `document-user-prompts.md`, `no-guessing.md`, `always-test-e2e.md`, `tests-must-not-fail.md`, `use-git-wrapper-scripts.md`, `remote-ci-must-pass.md` | `CLAUDE.md` (the short, universal ones) or `.claude/rules/*.md` with no `paths:` (the long ones, to keep `CLAUDE.md` lean) |
| `testing.md` (fileMatch `test/**/*.py`) | `.claude/rules/testing.md` with `paths: ["test/**/*.py"]` |
| `dependencies.md` (fileMatch `**/*.py`) | `.claude/rules/dependencies.md` with `paths: ["**/*.py"]` |
| `cdk-rules.md`, `cdk-deployment-only.md` (fileMatch `cdk/**/*.py`) | `.claude/rules/cdk-rules.md` with `paths: ["cdk/**/*.py"]` |
| `lambda-rules.md` (fileMatch `src/lambda_handlers/**/*.py`) | `.claude/rules/lambda-rules.md` with `paths: ["src/lambda_handlers/**/*.py"]` |
| `git-workflow-shared.md` (`inclusion: manual`, referenced by hooks) | A shared markdown file referenced from the git skills via `@path`, or a skill the git skills delegate to |
| Part 8.26 conformance check | Becomes a verification step in the setup skill: validate `.claude/rules/*.md` frontmatter keys (only `paths:` is meaningful) and that `CLAUDE.md` parses |

The hard-enforcement rules (`no-environment-vars`, `tests-must-not-fail`, `cdk-deployment-only`, `use-git-wrapper-scripts`) should be **doubled up**: keep the rule text *and* add a `PreToolUse` Bash hook + `permissions.deny` entries so the prohibition is actually enforced, not merely requested. Examples:
- `cdk-deployment-only` → `permissions.deny: ["Bash(aws cloudformation create-stack*)", "Bash(aws s3api create-bucket*)", ...]`
- `use-git-wrapper-scripts` → `permissions.deny: ["Bash(gh *)", "Bash(glab *)"]`
- `no-environment-vars` → `PreToolUse` hook on `Bash` returning `permissionDecision: deny` when the command matches `export `/`setx `/`$env:`.

### Part 9 — hooks
Kiro mixes two unrelated things under "hooks": **user-invoked workflow prompts** (`userTriggered` + `askAgent`) and **event-driven automation**. They split cleanly in Claude Code:

| Kiro hook | Claude Code |
|---|---|
| `run-ci-workflow`, `test-coverage`, `sync-documentation`, `git-commit`, `git-rebase`, `git-push` (all `userTriggered` + `askAgent`) | **Skills / slash commands** — `/run-ci`, `/test-coverage`, `/sync-docs`, `/git-commit`, `/git-rebase`, `/git-push`. The hook's `then.prompt` becomes the skill body verbatim. This is the natural, idiomatic home for them. |
| `fileEdited` trigger | `settings.json` `hooks.PostToolUse` with `matcher: "Write\|Edit"` |
| `agentStop` | `hooks.Stop` |
| `preToolUse` / `postToolUse` | `hooks.PreToolUse` / `hooks.PostToolUse` (with tool matchers) |
| `promptSubmit` | `hooks.UserPromptSubmit` |
| `preTaskExecution` / `postTaskExecution` | **No direct equivalent** — Claude Code has no built-in spec-task concept. Closest: `PostToolBatch` (TS SDK) or fold the logic into a skill. |

Claude Code hooks are strictly richer: ~20 events, matchers, `command`/`http`/`mcp_tool`/`prompt`/`agent` action types, and the ability to **block or rewrite** a tool call (`permissionDecision`, `updatedInput`) — Kiro hooks can only `runCommand` or `askAgent`. The one thing Kiro has that CC lacks is a first-class "user presses a button → inject this prompt mid-session" action, but that is exactly what a **slash command** is, so nothing is lost.

### Part 10 — spec templates; Part 12 — docs
Plain files; portable as-is. Keep them under `docs/` and/or `.claude/skills/<name>/templates/`. Claude Code's own `/init` can bootstrap `CLAUDE.md` from the codebase as a starting point before your setup skill layers the standards on top.

### Part 11 — editor settings (`.vscode` + `.kiro/settings.json`)
`.vscode/settings.json` is unchanged (it's VS Code, not the assistant). Drop the `.kiro/settings.json` half. Claude Code's editor/terminal integration doesn't need a parallel file; per-project env for the integrated terminal stays in `.vscode/settings.json`.

### Part 13 — verification + migration report
Becomes the closing steps of the setup skill. The report format is unchanged; just retarget the checklist items (MCP via `/mcp` or `claude mcp list`; steering → `.claude/rules` presence + frontmatter validity; hooks → `settings.json` validity; subagents → `.claude/agents` presence).

---

## 3. The custom CLI agents

### 3.1 What they have in common (the patterns that must survive)
Every Kiro agent (read from the JSON definitions) shares:
1. **Per-agent state directory** `.kiro/agent-state/<agent>/` with `resume_state.md` and append-only logs → checkpoint/resume across runtime termination.
2. **Mandates** baked into the prompt: non-interruption, no-shortcuts, no-guessing (no hedge words), evidence-over-inference.
3. **Tool gating**: `tools`/`allowedTools` + `toolsSettings` restricting writable paths and shell commands.
4. **Long-running autonomy** with a single terminal report.

All four survive the port:
1. State dir → keep the exact same convention; just rename to `.claude/agent-state/<agent>/` (or keep `.kiro/agent-state/` — it's an arbitrary path). **Plus** Claude Code subagents have an optional `memory:` field (`project`/`user`/`local`) for built-in persistence, complementing the file-based ledger.
2. Mandates → move verbatim into the subagent's system prompt (the Markdown body). Identical mechanism.
3. Tool gating → `tools:`/`disallowedTools:` in frontmatter for the tool *set*; path/command restriction via `settings.json` `permissions` (global) — see §3.4 for the fidelity gap.
4. Autonomy → run the subagent foreground, `background: true`, or headless via `claude -p --agent <name>`.

### 3.2 Per-agent mapping (the standalone agents)
These are all single-purpose autonomous agents — they map **one-to-one** to `.claude/agents/<name>.md`. The entire `prompt`/`prompt.md` body transfers unchanged; only the JSON envelope (`tools`, `toolsSettings`, `resources`, `welcomeMessage`, `model`) becomes YAML frontmatter + a couple of `settings.json` permission rules.

| Kiro agent | Claude Code subagent | Tool frontmatter | Notes |
|---|---|---|---|
| `dead-code-removal-agent` | `dead-code-removal.md` | `tools: Read, Write, Grep, Glob, Bash, WebSearch, WebFetch` | `fs_write.allowedPaths` (`src/**`, `test/**`, manifests, state dir) → `permissions.deny` for everything else, or rely on prompt + review. Git-branch protocol unchanged. |
| `doc-reviewer-agent` | `doc-reviewer.md` | `tools: Read, Grep, Glob, Bash, WebSearch, WebFetch, Write` | Write scope was `docs/**`, `*.md`, state — enforce via `permissions.deny: ["Edit(src/**)", "Edit(cdk/**)", ...]`. `resources` (`file://docs/**`) → drop; CC reads on demand. |
| `spec-review-agent` (`SpecReviewer`) | `spec-reviewer.md` | `tools: Read, Grep, Glob, Bash, WebSearch, WebFetch, Write` | Write only to spec + state dirs. Read-only review semantics. |
| `SpecPromptAuthor` | `spec-prompt-author.md` | similar | Pairs with the reviewer. |
| `ci-worker` (`.txt`) | `ci-worker.md` | `tools: Bash, Read, Grep, Glob, WebFetch` | Already a `.txt` prompt; wrap in frontmatter. |
| `issue-housekeeping` | `issue-housekeeping.md` | `tools: Bash, Read, Grep, Glob` | Uses git-host wrappers / `gh`. |
| `issue-intake` | `issue-intake.md` | similar | |
| `product-management` | `product-management.md` | similar | |

`welcomeMessage` has no exact equivalent; fold it into the `description` or the first lines of the body. `model: null` → omit (inherits session model) or set `model: inherit`.

### 3.3 The CV suite — the one structural problem
The CV suite is an **orchestrator + 6 delegates**, wired with Kiro's `toolsSettings.subagent.availableAgents`/`trustedAgents`. The orchestrator drives an iteration loop and *spawns the delegates by name*.

**Claude Code subagents cannot spawn subagents (no nesting).** So a literal port — `cv-orchestrator.md` spawning `cv-editor.md` etc. — will not work. Three options, best first:

1. **Promote the orchestrator to the main session (recommended).** Implement `cv-orchestrator` as a **skill** (`/cv-customize`) or as the top-level agent (`claude --agent cv-orchestrator`). The main session *can* delegate to the six delegate subagents in `.claude/agents/`. The orchestrator's loop logic, convergence predicate, dedup/conflict resolution, and on-disk Change_List all stay the same; only "I am a subagent spawning subagents" becomes "I am the main loop delegating to subagents". The six delegates become ordinary `.claude/agents/*.md` files. This preserves the architecture almost exactly.
2. **Flatten to a workflow** (Agent SDK / a Claude Code Workflow script): a deterministic JS/Python driver runs the loop and invokes each reviewer as an `agent()` call. Strongest control, but it's code, not a paste-in agent.
3. **Single mega-agent** with the six reviewer "lenses" as sequential phases in one prompt. Simplest, loses the isolation/parallelism the suite was designed for. Not recommended.

The deterministic helper scripts (`docx_normalize.py`, `page_count.py`, etc.) port unchanged; reference them via `permissions.allow: ["Bash(python .../docx_normalize.py*)"]`.

### 3.4 The tool-gating fidelity gap (read this before relying on it)
Kiro enforces, **per agent**, regex `shell.allowedCommands`/`deniedCommands` and glob `fs_write.allowedPaths` — the runtime physically blocks anything off-list.

Claude Code's enforcement is **global to the session**, not per-subagent: `permissions.allow/deny` in `settings.json` apply to the whole session and all subagents. A subagent's `tools:`/`disallowedTools:` restrict the tool *types* it can use, but you cannot give `cv-editor` a different writable-path allowlist than `cv-ats-reviewer` through settings alone. To approximate per-agent path/command restriction you must use **`PreToolUse` hooks** that inspect `tool_input` (e.g. the file path or command) and return `permissionDecision: deny` — that's where the real per-call gating lives. Patterns also differ: Kiro uses **regex**; Claude Code uses **glob** (`Bash(python script.py*)`, `Edit(src/**)`).

Net: tool *type* restriction and global path/command allow-deny are easy and enforced. Truly *per-agent* path scoping requires hooks, or you accept it as advisory (prompt-level) — which for read-only reviewer agents is usually fine.

---

## 4. How to package and ship it

Two viable models. They're not exclusive — start with (A), graduate to (B).

### A. Committed `.claude/` files + a setup skill (closest to current workflow)
Mirror today's "paste the prompt" flow:
1. Ship a `/project-setup` **skill** whose body is the v2 runbook (Parts 0–13), referencing template files bundled beside `SKILL.md`.
2. The skill writes `CLAUDE.md`, `.claude/rules/*.md`, `.claude/agents/*.md`, `.claude/settings.json` (permissions + hooks), and `.mcp.json` into the target project — applying Rule 1 merge logic exactly as now.
3. The user runs `/project-setup` once per project (the analogue of pasting the prompt).

This is the **lowest-friction port**: one skill replaces the paste, and the agents come along as committed files.

### B. A Claude Code plugin + marketplace (best long-term)
Bundle everything into one installable, versioned, team-shareable unit:
```
kiro-standard-plugin/
├── .claude-plugin/plugin.json
├── skills/
│   ├── project-setup/SKILL.md          # the v2 runbook
│   │   └── templates/                  # pyproject, ruff, gitignore, wrappers, …
│   ├── git-commit/SKILL.md             # ex-userTriggered hooks
│   ├── git-push/SKILL.md
│   ├── run-ci/SKILL.md
│   ├── test-coverage/SKILL.md
│   └── sync-docs/SKILL.md
├── agents/                             # the custom agents
│   ├── dead-code-removal.md
│   ├── doc-reviewer.md
│   ├── spec-reviewer.md
│   ├── ci-worker.md
│   ├── issue-housekeeping.md
│   └── cv-*.md                         # orchestrator-as-skill + 6 delegates
├── rules/                              # steering files
│   ├── coding-standards.md
│   ├── tests-must-not-fail.md
│   └── … (paths: frontmatter where fileMatch)
├── hooks/hooks.json                    # enforced PreToolUse / Stop hooks
├── .mcp.json                           # the 5 AWS/Strands servers
└── settings.json                       # default permissions (allow mcp__*, deny gh/cfn-mutate, …)
```
Install once (`/plugin marketplace add <org>/<repo>` → `/plugin install kiro-standard@<org>`); thereafter every project gets the agents, rules, hooks, MCP servers, and the `/project-setup` skill, with versioning and `/plugin marketplace update` for upgrades. **No `install_agents.py` equivalent is needed** — Claude Code discovers `.claude/agents/*.md` in place and plugins handle distribution, so the whole path-rewriting installer disappears.

### Headless / autonomous runs
For the long-running autonomous agents (dead-code, doc-reviewer, spec-reviewer), Claude Code supports `claude -p "..." --agent dead-code-removal --output-format json` for non-interactive/CI execution, and the **Claude Agent SDK** (Python/TypeScript) gives the same tools programmatically — a natural fit for the resume_state checkpoint pattern these agents already implement.

---

## 5. What you lose, what you gain

**Lose (vs Kiro):**
- **Subagent nesting** — orchestrator→delegate chains must move to the main session or a workflow (§3.3).
- **Per-agent enforced command/path allowlists** — becomes global permissions + hooks (§3.4).
- **Per-tool `autoApprove`** — becomes `permissions.allow` rules (§Part 0).
- **Proactive `fileMatch`** — `paths:` rules load reactively (when a matching file is read), not at session start (§Part 8).
- **`preTaskExecution`/`postTaskExecution`** hooks — no spec-task concept in CC.

**Gain (vs Kiro):**
- **Real enforcement layer** — permissions + `PreToolUse` hooks can *block/rewrite* tool calls; Kiro steering is text-only.
- **Far richer hooks** — ~20 events, 5 action types, mid-call blocking.
- **Plugin distribution + marketplace** — versioned, one-command install, team-shareable; replaces the bespoke installer and the paste-in workflow.
- **Skills with progressive disclosure** — the 2000-line prompt can be split so only descriptions sit in context until invoked.
- **First-class headless mode + Agent SDK** for the autonomous agents.

---

## 6. Recommended next steps

1. **Prototype the steering layer first** — it's the highest-value, lowest-risk piece. Convert the 25 steering files to `CLAUDE.md` + `.claude/rules/*.md` and add the enforcing `settings.json` permissions/hooks for the four "hard" rules.
2. **Port one standalone agent end-to-end** (suggest `doc-reviewer` — read-mostly, clean write-scope) to validate the `.claude/agents/*.md` + permissions pattern, including resume_state behaviour under `claude -p`.
3. **Decide the CV orchestrator shape** (§3.3 option 1 vs 2) before porting the suite — it determines whether the orchestrator is a skill, the main agent, or a workflow.
4. **Rewrite the setup prompt as a `/project-setup` skill** (model A), targeting `.claude/` outputs.
5. **Wrap it all in a plugin** (model B) once the pieces are proven.

> One open decision worth surfacing: how much of the original "hard enforcement" you actually want re-created with hooks/permissions versus left as advisory `CLAUDE.md` guidance. Hooks cost setup effort and can interrupt flow; for a single-user, trusted setup, advisory rules + a few permission `deny`s may be enough, reserving `PreToolUse` hooks for the genuinely dangerous prohibitions (env vars, infra mutation).
