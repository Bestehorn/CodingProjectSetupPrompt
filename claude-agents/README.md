# Claude Code Agents

This directory is the Claude Code counterpart of [`cli-agents/`](../cli-agents/).
It mirrors that directory's structure and contains a **translation** of each
Kiro CLI custom agent into a Claude Code **subagent** (a Markdown file with YAML
frontmatter).

The agent *behaviour* is unchanged — each subagent body is the original Kiro
prompt, preserved. Only the envelope changed: Kiro's per-agent JSON
(`tools` + `toolsSettings` + `subagent.availableAgents`) became Claude Code
subagent frontmatter (`name`, `description`, `tools`, `Agent(...)`), and every
`.kiro/agent-state/<agent>/` path was rewritten to `.claude/agent-state/<agent>/`
so the agents keep their checkpoint/resume state under the Claude tree.

> The Kiro originals in `cli-agents/` are untouched. A project can carry both:
> Kiro reads `.kiro/agents/`, Claude Code reads `.claude/agents/`.

## Directory map (Kiro → Claude Code)

| Kiro source | Claude Code subagent file | Subagent name |
|---|---|---|
| `cli-agents/dead-code/KiroCLIAgent-DeadCodeAgent.json` | `dead-code/dead-code-removal-agent.md` | `dead-code-removal-agent` |
| `cli-agents/doc-review/KiroCLIAgent-DocReviewer.json` | `doc-review/doc-reviewer-agent.md` | `doc-reviewer-agent` |
| `cli-agents/ci-worker/CLIAgents-CIWorkflowAgent.txt` | `ci-worker/ci-workflow-agent.md` | `ci-workflow-agent` |
| `cli-agents/issue-housekeeping/KiroCLIAgent-IssueHousekeeping.json` | `issue-housekeeping/issue-housekeeping-agent.md` | `issue-housekeeping-agent` |
| `cli-agents/issue-intake/KiroCLIAgent-IssueIntake.json` | `issue-intake/issue-intake-agent.md` | `issue-intake-agent` |
| `cli-agents/product-management/KiroCLIAgent-ProductManagement.json` | `product-management/product-management-agent.md` | `product-management-agent` |
| `cli-agents/spec-review/KiroCLIAgent-SpecReviewer.json` | `spec-review/spec-review-agent.md` | `spec-review-agent` |
| `cli-agents/spec-review/KiroCLIAgent-SpecPromptAuthor.json` | `spec-review/spec-prompt-author-agent.md` | `spec-prompt-author-agent` |
| `cli-agents/cv/orchestrator/` | `cv/cv-orchestrator.md` | `cv-orchestrator` |
| `cli-agents/cv/editor/` | `cv/cv-editor.md` | `cv-editor` |
| `cli-agents/cv/spell-format-reviewer/` | `cv/cv-spell-format-reviewer.md` | `cv-spell-format-reviewer` |
| `cli-agents/cv/language-content-reviewer/` | `cv/cv-language-content-reviewer.md` | `cv-language-content-reviewer` |
| `cli-agents/cv/jd-alignment-reviewer/` | `cv/cv-jd-alignment-reviewer.md` | `cv-jd-alignment-reviewer` |
| `cli-agents/cv/ats-reviewer/` | `cv/cv-ats-reviewer.md` | `cv-ats-reviewer` |
| `cli-agents/cv/hiring-manager-reviewer/` | `cv/cv-hiring-manager-reviewer.md` | `cv-hiring-manager-reviewer` |

The CV suite has its own run instructions in [`cv/README.md`](cv/README.md)
(it is the one suite that needs special handling — see *The CV suite* below).

## Spec-driven + test-driven workflow (`spec-workflow/`)

In addition to the translated Kiro agents above, this directory contains a
**native, automated spec-driven + test-driven development workflow** for Claude
Code — the hands-off replacement for the manual Kiro CLI ↔ IDE loop. It is NOT a
translation of a single Kiro agent; it generalizes the `cv-orchestrator` pattern
into a `spec-conductor` that drives a feature/bugfix from a one-line idea to
evidence-proven code in one session.

| File (under `spec-workflow/`) | Subagent / role |
|---|---|
| `spec-conductor.md` | Main-session orchestrator (`claude --agent spec-conductor`) |
| `spec-author.md` | Writes requirements / design / tasks |
| `spec-researcher.md` | Read-only research bursts |
| `test-architect.md` | Correctness Properties + coverage gate (core) |
| `adversarial-verifier.md` | Re-runs & refutes every claim (core) |
| `standards-reviewer.md` | Project/coding-standards conformance |
| `best-practice-reviewer.md` | External best-practice alignment (MCP/web) |
| `security-reviewer.md` | Threat model + vulnerability review |
| `devops-iac-reviewer.md` | CI/CD, IaC least-privilege, observability |
| `spec-implementer.md` | Test-first implementer (never certifies itself) |
| `phases/spec-phase-*.md` | Phase procedures (shared by conductor + commands) |
| `rules/agent-state-convention.md` | Cross-agent decision-log convention (all agents) |
| `rules/no-ai-attribution.md` | Descriptive names; no Claude/AI attribution in commits/PRs/issues/branches (all agents) |
| `rules/issue-filing-discipline.md` | WHEN an issue may be filed at all: observed defects only, fix-first, zero-is-valid, provenance, findings ledger (all agents) |
| `hooks/*.sh` | TDD/evidence gates (commit gate, stop gate, red-for-right-reason) + the issue-filing gate |

It reuses the two `spec-review/` agents (the adversarial `spec-review-agent` and the
`spec-prompt-author-agent`). The four `/spec-*` slash commands live in
[`../claude-commands/`](../claude-commands/). Full documentation — pipeline, the
autonomous readiness gate, the evidence/proof model, install, and durable state —
is in [`spec-workflow/README.md`](spec-workflow/README.md). `ClaudeCodeSetupPrompt.txt`
Part 12 installs and wires it into a project.

## Autonomous issue resolution (`issue-work-orchestrator/`)

The top layer above the spec workflow: a main-session agent that works the project's
ENTIRE open-issue backlog end to end. Per issue it selects the highest-priority
not-in-progress issue, creates a git worktree + branch, develops and PROVES a fix
through the spec/TDD engine (embedding the same phase fragments and leaf agents — it
does NOT nest the conductor), reviews the proof, documents it on the issue, opens a PR,
drives CI green, self-approves + merges where allowed, cleans up, closes the issue, and
repeats — fully resumable via `.claude/agent-state/issue-work-orchestrator/`.

Run: `claude --agent issue-work-orchestrator` (or `/issues-work`, or "continue the work
on the existing issues of this project"). For a single named issue, `/work-issue <X>` runs
the same lifecycle claim-first in its own worktree and stops after that issue. Full docs:
[`issue-work-orchestrator/README.md`](issue-work-orchestrator/README.md).
`ClaudeCodeSetupPrompt.txt` Part 13 installs it (depends on Part 12).

**Which issue agent to use:** `issue-intake` turns one observation into AT MOST ONE
well-formed issue — and is the fleet's filing gate, reporting NOT_FILED with a
recommended direct fix when the defect is small and clear, already resolved, or a
duplicate; `issue-housekeeping` batch-triages all issues with local quick-fixes (never
pushes, never creates issues); `issue-work-orchestrator` delivers issues one at a time
through the full remote PR/CI/merge lifecycle with proof.

**Filing discipline (read this before adding any filing mechanism).** Five agents can
create tracker issues: `issue-intake`, `product-management`, `doc-review`, `dead-code`,
and (via intake) `issue-work-orchestrator`. All of them are bound by
[`spec-workflow/rules/issue-filing-discipline.md`](spec-workflow/rules/issue-filing-discipline.md):
an issue may be filed only for an OBSERVED defect, only after the mandatory fix-first
evaluation (a few lines with no design choice gets FIXED, not filed), only when it needs
extensive research / an evaluation of design options / work outside the current task, and
only with `Origin:`/`Subject:`/`Spawned-from:`/`Filing-rationale:` lines — which
[`spec-workflow/hooks/issue-filing-gate.sh`](spec-workflow/hooks/issue-filing-gate.sh)
enforces as a `PreToolUse` gate. No agent has a filing quota, and **zero filed issues is
a valid and expected outcome of a run**. Everything not filed goes to
`docs/findings-ledger.md`. This exists because the fleet was measured spawning most of
its own backlog: 60% of issues (78% in the last measured month) came from working other
issues, and the subject mix drifted from the product to the workflow machinery.

## Mandatory merge agent (`code-merge-reviewer/`)

Whenever local code must be integrated with the remote and a conflict arises, the work
is delegated to `code-merge-reviewer` — a dedicated subagent that reviews the merge
holistically, resolves every conflict **line by line** preserving both sides' intent,
forbids blind "take theirs/ours", and re-runs the test suite to prove no regression
before declaring the merge done. The `issue-work-orchestrator` delegates all conflict
resolution to it (in Remote Sync and the PR rebase); any agent doing merges should too.
Full docs: [`code-merge-reviewer/README.md`](code-merge-reviewer/README.md).

## How Claude Code discovers subagents

Claude Code reads subagent definitions from two locations:

- **Project scope:** `.claude/agents/` in the project root (checked into git,
  shared with the team).
- **User scope:** `~/.claude/agents/` (available in all your projects).

It does **not** scan this `claude-agents/` authoring directory. To use an
agent, copy (or symlink) its `.md` file into one of those locations. Unlike
Kiro, there is **no installer and no path rewriting** — the files are used
as-is.

### Install (project scope)

```bash
# from the project root, install every agent for this project:
mkdir -p .claude/agents
cp claude-agents/dead-code/dead-code-removal-agent.md        .claude/agents/
cp claude-agents/doc-review/doc-reviewer-agent.md            .claude/agents/
cp claude-agents/ci-worker/ci-workflow-agent.md              .claude/agents/
cp claude-agents/issue-housekeeping/issue-housekeeping-agent.md .claude/agents/
cp claude-agents/issue-intake/issue-intake-agent.md          .claude/agents/
cp claude-agents/product-management/product-management-agent.md .claude/agents/
cp claude-agents/spec-review/spec-review-agent.md            .claude/agents/
cp claude-agents/spec-review/spec-prompt-author-agent.md     .claude/agents/
cp claude-agents/cv/cv-*.md                                  .claude/agents/
```

`.claude/agents/` may be flat — the subagent's `name:` (not its path) is the
identifier. New or changed files are picked up on the next session start (or
immediately when created via the `/agents` command).

### Install (user scope, available everywhere)

```bash
cp claude-agents/**/*.md ~/.claude/agents/   # one-time, all projects
```

> The `ClaudeCodeSetupPrompt.txt` setup prompt installs these for you when you
> ask it to (Part 8 of that prompt). This README is for installing them
> manually or understanding what got installed.

## How to invoke an agent

Three ways, all standard Claude Code:

1. **Auto-delegation.** Describe the task; Claude reads each subagent's
   `description` and delegates when it matches. Example: "remove dead code from
   `src/`" will tend to route to `dead-code-removal-agent`.
2. **Explicit @-mention** (guarantees the agent runs):
   `@agent-dead-code-removal-agent clean up src/`.
3. **Whole session as the agent** (best for the long-running autonomous ones):
   ```bash
   claude --agent dead-code-removal-agent
   ```
   or, non-interactively / in CI:
   ```bash
   claude -p "Run the dead-code removal loop on this repo." --agent dead-code-removal-agent
   ```

The long-running agents (`dead-code-removal-agent`, `doc-reviewer-agent`,
`ci-workflow-agent`, `issue-housekeeping-agent`, `product-management-agent`)
checkpoint to `.claude/agent-state/<agent>/resume_state.md`. If a run is
interrupted, start the same agent again — its Discovery Step 0 reads that state
and resumes.

## Tool mapping (Kiro → Claude Code)

Each Kiro tool maps to Claude Code's built-in tools in the `tools:` frontmatter:

| Kiro tool | Claude Code tool(s) |
|---|---|
| `fs_read`, `read`, `code` | `Read` (+ `Grep`, `Glob` for `code`) |
| `fs_write`, `write` | `Write`, `Edit` |
| `grep` | `Grep` |
| `glob` | `Glob` |
| `executePwsh`, `execute_bash`, `shell` | `Bash` |
| `web_search` | `WebSearch` |
| `web_fetch` | `WebFetch` |
| `subagent` | `Agent(<name>, …)` — only on `cv-orchestrator` |

## The big difference from Kiro: write-scope and command allow/deny lists

Kiro enforced **per-agent** restrictions inside each agent's JSON:
`toolsSettings.fs_write.allowedPaths` (which paths the agent may write) and
`toolsSettings.shell.allowedCommands` / `deniedCommands` (which shell commands
it may run). Claude Code subagent frontmatter has **no per-agent equivalent**;
the `tools:` field restricts the *tool set*, but path/command scoping is a
**session-wide** concern handled by the permission system in
`.claude/settings.json` (`permissions.allow` / `permissions.deny`, glob-based,
deny wins) and, for true per-call enforcement, `PreToolUse` hooks.

What this means in practice, per original Kiro restriction:

| Original Kiro restriction | Claude Code equivalent |
|---|---|
| `doc-reviewer` writes only `docs/**`, `*.md`, state dir | Prompt body already forbids editing code. To **enforce** it, add `permissions.deny` rules: `"Edit(src/**)"`, `"Edit(cdk/**)"`, `"Edit(test/**)"`, `"Edit(scripts/**)"`. |
| `dead-code` writes only `src/**`, `test/**`, manifests, state | Prompt body restricts this. Optionally enforce with a `PreToolUse` hook that denies `Edit`/`Write` outside those globs. |
| `spec-review`, `spec-prompt-author` write only spec + state dirs | Same: enforce with `permissions.deny` on code dirs if you want a hard guarantee. |
| `issue-intake`, `product-management`: never modify code, never `git commit` | Add `permissions.deny: ["Bash(git commit:*)", "Bash(git push:*)", "Edit(src/**)", ...]`. |
| `cv-editor` shell allowlist `python tmp/cv-editor/.../apply_changes.py` and deny `git`/`pip`/`rm`/`curl`/... | Optionally add the deny rules to `.claude/settings.json`; the body already constrains behaviour. |
| any agent that can create issues (`issue-intake`, `product-management`, `doc-review`, `dead-code`, `issue-housekeeping`) | Install `rules/issue-filing-discipline.md` into `.claude/rules/` AND wire `hooks/issue-filing-gate.sh` as a `PreToolUse` Bash hook — it blocks an issue-create call whose body carries no filing rationale. |

For a single trusted user, the prompt-level restrictions in each body are
usually sufficient. Add the `permissions.deny` rules (or a `PreToolUse` hook)
when you want the restriction to be *enforced* rather than *instructed*. Each
agent file notes its original write-scope at the top of its body.

A ready-to-paste starting `permissions` block for the read-only / scoped
agents:

```json
{
  "permissions": {
    "deny": [
      "Bash(git push:*)",
      "Edit(.git/**)"
    ]
  }
}
```

…then tighten per agent as the table above describes. (Because permissions are
session-wide, the strictest practical pattern is to run one restricted agent
per session via `claude --agent <name>` with a matching
`.claude/settings.local.json`.)

## MCP servers

Several agents consult MCP documentation servers ("consult the relevant MCP
documentation server…"). Configure those in the project's `.mcp.json` (see
`ClaudeCodeSetupPrompt.txt`, Part 0). Auto-approve their read-only tools with
`permissions.allow: ["mcp__<server>__*"]` so the agents are not interrupted by
approval prompts mid-run.

## Relationship to the Kiro originals

- The Kiro JSON/`prompt.md`/`*Discussion.txt` files under `cli-agents/` remain
  the authoring source of record and are unchanged.
- These `.md` files are derived from them. If you change an agent's behaviour,
  decide which is canonical and regenerate the other (the standalone agents
  were generated by `tmp/translate_agents.py`, kept for reference).
- A project may use both assistants at once: Kiro from `.kiro/agents/`, Claude
  Code from `.claude/agents/`.
