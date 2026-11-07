# Claude Code Agents

This directory is the Claude Code counterpart of [`clients/kiro/`](../kiro/). It is laid
out like a project's `.claude/` (`agents/`, `commands/`, `rules/`, `docs/`) and contains a
**translation** of each
Kiro CLI custom agent into a Claude Code **subagent** (a Markdown file with YAML
frontmatter).

The agent *behaviour* is unchanged — each subagent body is the original Kiro
prompt, preserved. Only the envelope changed: Kiro's per-agent JSON
(`tools` + `toolsSettings` + `subagent.availableAgents`) became Claude Code
subagent frontmatter (`name`, `description`, `tools`, `Agent(...)`), and every
`.kiro/agent-state/<agent>/` path was rewritten to `.claude/agent-state/<agent>/`
so the agents keep their checkpoint/resume state under the Claude tree. (One
later, behaviour-neutral restructuring: four agents' drafting templates were
extracted into sibling files read on demand from `.claude/docs/` — see below.)

> The Kiro originals in `clients/kiro/agents/` are untouched. A project can carry both:
> Kiro reads `.kiro/agents/`, Claude Code reads `.claude/agents/`.

## Directory map (Kiro → Claude Code)

| Kiro source | Claude Code subagent file | Subagent name |
|---|---|---|
| `clients/kiro/agents/dead-code-removal-agent.json` | `agents/dead-code-removal-agent.md` | `dead-code-removal-agent` |
| `clients/kiro/agents/doc-reviewer-agent.json` | `agents/doc-reviewer-agent.md` | `doc-reviewer-agent` |
| `clients/kiro/agents/ci-workflow-agent.json` | `agents/ci-workflow-agent.md` | `ci-workflow-agent` |
| `clients/kiro/agents/issue-housekeeping-agent.json` | `agents/issue-housekeeping-agent.md` | `issue-housekeeping-agent` |
| `clients/kiro/agents/issue-intake-agent.json` | `agents/issue-intake-agent.md` | `issue-intake-agent` |
| `clients/kiro/agents/product-management-agent.json` | `agents/product-management-agent.md` | `product-management-agent` |
| `clients/kiro/agents/spec-review-agent.json` | `agents/spec-review-agent.md` | `spec-review-agent` |
| `clients/kiro/agents/spec-prompt-author-agent.json` | `agents/spec-prompt-author-agent.md` | `spec-prompt-author-agent` |

The agents' design notes (the Kiro `*Discussion.txt` files and prompt drafts) are in
[`docs/design/agents/`](../../docs/design/agents/).

Four agents keep their drafting/reference material in a SIBLING file rather than
in the agent definition: `docs/issue-draft-template.md`,
`docs/pm-proposal-template.md`, `docs/housekeeping-templates.md`, and
`docs/dead-code-language-matrix.md`. Each installs to the project's
`.claude/docs/` and is read by its agent at the moment it is needed — drafting an
issue, writing a proposal, triaging, language setup — instead of loading with the
agent definition every session. Install the template with its agent: the agent
bodies point at those exact `.claude/docs/` paths.

## Spec-driven + test-driven workflow

In addition to the translated Kiro agents above, this directory contains a
**native, automated spec-driven + test-driven development workflow** for Claude
Code — the hands-off replacement for the manual Kiro CLI ↔ IDE loop. It is NOT a
translation of a single Kiro agent; a main-session `spec-conductor` owns the loop
and drives a feature/bugfix from a one-line idea to
evidence-proven code in one session.

| File (under `clients/claude/` unless a full path is given) | Subagent / role |
|---|---|
| `agents/spec-conductor.md` | Main-session orchestrator (`claude --agent spec-conductor`) |
| `agents/spec-author.md` | Writes requirements / design / tasks |
| `agents/spec-researcher.md` | Read-only research bursts |
| `agents/test-architect.md` | Correctness Properties + coverage gate (core) |
| `agents/adversarial-verifier.md` | Re-runs & refutes every claim (core) |
| `agents/standards-reviewer.md` | Project/coding-standards conformance |
| `agents/best-practice-reviewer.md` | External best-practice alignment (MCP/web) |
| `agents/security-reviewer.md` | Threat model + vulnerability review |
| `agents/devops-iac-reviewer.md` | CI/CD, IaC least-privilege, observability |
| `agents/spec-implementer.md` | Test-first implementer (never certifies itself) |
| `clients/common/phases/spec-phase-*.md` | Phase procedures (shared by conductor + commands, and by Kiro) |
| `rules/agent-state-convention.md` | State layout + plain `Name: value` field semantics + the cross-agent decision log; its §1a binds every REGISTERED run to the run-identity contract (all agents) |
| `docs/run-identity.md` | The AUTHORITATIVE run-identity/gate-release contract (registry-derived run id, seeded fields, release vocabulary, `OWNED`/`UNREGISTERED`/`BROKEN` verdicts). Installs to `.claude/docs/` — deliberately NOT a rule, so it is read on demand by registered runs instead of loading into every session |
| `rules/no-ai-attribution.md` | Descriptive names; no Claude/AI attribution in commits/PRs/issues/branches (all agents) |
| `rules/issue-filing-discipline.md` | WHEN an issue may be filed at all: observed defects only, fix-first, zero-is-valid, provenance, findings ledger (all agents) |
| `rules/continuous-work.md` | WHEN a turn may end: never stop for permission; four proven exceptions only; a question is five lines with the recommended option first; reversible decisions are decided, not asked (all agents + main session) |
| `rules/proportionality.md` | HOW MUCH spec a change gets: tiers S/M/L from the ASK, hard byte caps, scope frozen once review opens, no measurements in specs (all agents) |
| `rules/parallel-by-default.md` | Independent work runs concurrently — panels, research, implementation waves and independent suites run together; a wait you need runs in the foreground, bounded, after the unblocked work; a green PR is handed to the merge steward, never waited on (all agents) |
| `rules/native-tools-over-shell.md` | A Bash call is the expensive tool: files through Read/Grep/Glob/Write/Edit, never `cat`/`grep`/`ls`/heredocs; one shell call per step; no foreground sleep (the `no-foreground-sleep` gate); suites through the runner's host-wide slot (all agents) |
| `clients/common/docs/review-contract.md` | The finding shape every reviewer uses and the forbidden findings; installs to `.claude/docs/`, read on demand |
| `clients/common/docs/delivery.md` | HOW a green PR lands, deploys and is verified, by the mode `config/delivery.json` selects: hand-off to the merge steward, the verdict watcher, the `(post-deploy)` items, the `needs-rework` return path; installs to `.claude/docs/`, read at the PR phase |
| `rules/ci-owns-the-test-suite.md` | WHERE tests run: affected tests locally, full suite in CI, never as a commit precondition; commit often and push once; bounded local workers (never `-n auto`); fix EVERY failure a CI run reports in one pass (all agents + main session) |
| `src/hooks/hooks.py`, `src/hooks/gate_*.py` | The Python hook dispatcher and its discovered gates: the PUSH gate and stop gate (both accept per-task and wave captures), the issue-loop brake (which also releases a single-issue `HANDED_OFF` run), no-env-vars, no-foreground-sleep, no-idle-wait, claim-before-worktree, merge-steward (only the steward writes the trunk), the issue-filing gate, the stop-failure recorder; `red_for_right_reason.py` is the RED-audit helper, `wait_for.py` the bounded wait for a background task's output, `supervisor.py` the `/supervise` backstop |

It reuses the two spec-review agents (the adversarial `spec-review-agent` and the
`spec-prompt-author-agent`). The four `/spec-*` slash commands live in
[`commands/`](commands/). Full documentation — pipeline, the
autonomous readiness gate, the evidence/proof model, install, and durable state —
is in [`docs/design/agents/spec-workflow.md`](../../docs/design/agents/spec-workflow.md). `prompts/setup-claude.txt`
Part 12 installs and wires it into a project.

## Autonomous issue resolution (`issue-work-orchestrator`)

The top layer above the spec workflow: a main-session agent that works the project's
ENTIRE open-issue backlog end to end. Per issue it selects the highest-priority
not-in-progress issue, creates a git worktree + branch, develops and PROVES a fix
through the spec/TDD engine (embedding the same phase fragments and leaf agents — it
does NOT nest the conductor), reviews the proof, documents it on the issue, opens a PR,
drives its CI green, hands it to the merge steward (or self-approves + merges where the project
merges directly), cleans up, closes or hands off the issue, and repeats — fully resumable via
`.claude/agent-state/issue-work-orchestrator/`.

Run: `claude --agent issue-work-orchestrator` (or `/issues-work`, or "continue the work
on the existing issues of this project"). For a single named issue, `/work-issue <X>` runs
the same lifecycle claim-first in its own worktree and stops after that issue. Full docs:
[`docs/design/agents/issue-work-orchestrator.md`](../../docs/design/agents/issue-work-orchestrator.md).
`prompts/setup-claude.txt` Part 13 installs it (depends on Part 12).

**Which issue agent to use:** `issue-intake` turns one observation into AT MOST ONE
well-formed issue — and is the fleet's filing gate, reporting NOT_FILED with a
recommended direct fix when the defect is small and clear, already resolved, or a
duplicate; `issue-housekeeping` batch-triages all issues with local quick-fixes (never
pushes, never creates issues); `issue-work-orchestrator` delivers issues one at a time
through the full remote PR/CI/merge lifecycle with proof.

**Filing discipline (read this before adding any filing mechanism).** Five agents can
create tracker issues: `issue-intake`, `product-management`, `doc-review`, `dead-code`,
and (via intake) `issue-work-orchestrator`. All of them are bound by
[`rules/issue-filing-discipline.md`](rules/issue-filing-discipline.md):
an issue may be filed only for an OBSERVED defect, only after the mandatory fix-first
evaluation (a few lines with no design choice gets FIXED, not filed), only when it needs
extensive research / an evaluation of design options / work outside the current task, and
only with `Origin:`/`Subject:`/`Spawned-from:`/`Filing-rationale:` lines — which
[`issue-filing-gate`](../../src/hooks/gate_filing.py)
enforces as a `PreToolUse` gate. No agent has a filing quota, and **zero filed issues is
a valid and expected outcome of a run**. Everything not filed goes to
`docs/findings-ledger.md`. This exists because the fleet was measured spawning most of
its own backlog: 60% of issues (78% in the last measured month) came from working other
issues, and the subject mix drifted from the product to the workflow machinery.

## Mandatory merge agent (`code-merge-reviewer`)

Whenever local code must be integrated with the remote and a conflict arises, the work
is delegated to `code-merge-reviewer` — a dedicated subagent that reviews the merge
holistically, resolves every conflict **line by line** preserving both sides' intent,
forbids blind "take theirs/ours", and re-runs the affected tests to prove no regression
before declaring the merge done (the whole-suite check is the CI run after the push —
`rules/ci-owns-the-test-suite.md`). The `issue-work-orchestrator` delegates all conflict
resolution to it (in Remote Sync and the PR rebase); any agent doing merges should too.
Full docs: [`docs/design/agents/code-merge-reviewer.md`](../../docs/design/agents/code-merge-reviewer.md).

## How Claude Code discovers subagents

Claude Code reads subagent definitions from two locations:

- **Project scope:** `.claude/agents/` in the project root (checked into git,
  shared with the team).
- **User scope:** `~/.claude/agents/` (available in all your projects).

It does **not** scan this `clients/claude/` authoring directory. To use an
agent, copy (or symlink) its `.md` file into one of those locations. Unlike
Kiro, there is **no installer and no path rewriting** — the files are used
as-is.

### Install (project scope)

```bash
# from the project root, install every agent for this project:
mkdir -p .claude/agents .claude/docs
cp clients/claude/agents/dead-code-removal-agent.md   .claude/agents/
cp clients/claude/agents/doc-reviewer-agent.md        .claude/agents/
cp clients/claude/agents/ci-workflow-agent.md         .claude/agents/
cp clients/claude/agents/issue-housekeeping-agent.md  .claude/agents/
cp clients/claude/agents/issue-intake-agent.md        .claude/agents/
cp clients/claude/agents/product-management-agent.md  .claude/agents/
cp clients/claude/agents/spec-review-agent.md         .claude/agents/
cp clients/claude/agents/spec-prompt-author-agent.md  .claude/agents/

# agent-sibling templates → .claude/docs/ (read by their agents at drafting
# time; on demand, deliberately NOT rules/, which would always-load them):
cp clients/claude/docs/issue-draft-template.md      .claude/docs/
cp clients/claude/docs/pm-proposal-template.md      .claude/docs/
cp clients/claude/docs/housekeeping-templates.md    .claude/docs/
cp clients/claude/docs/dead-code-language-matrix.md .claude/docs/
```

`.claude/agents/` may be flat — the subagent's `name:` (not its path) is the
identifier. New or changed files are picked up on the next session start (or
immediately when created via the `/agents` command).

### Install (user scope, available everywhere)

```bash
cp clients/claude/agents/*.md ~/.claude/agents/   # one-time, all projects
# agents/ holds agent definitions only, so nothing else is swept in.
```

(The `.claude/docs/` sibling templates cannot be installed user-scope — agents
read them from the PROJECT's `.claude/docs/`, so copy them per project as above.)

> The `prompts/setup-claude.txt` setup prompt installs these for you when you
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
| `subagent` | `Agent(<name>, …)` on a main-session agent |

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
| any agent that can create issues (`issue-intake`, `product-management`, `doc-review`, `dead-code`, `issue-housekeeping`) | Install `rules/issue-filing-discipline.md` into `.claude/rules/` AND wire `src/hooks/hooks.py` (installed as `.claude/hooks/hooks.py`) as a `PreToolUse` hook (`python .claude/hooks/hooks.py pre-tool-use`) — its `issue-filing-gate` gate blocks an issue-create call whose body carries no filing rationale. |

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
`prompts/setup-claude.txt`, Part 0). Auto-approve their read-only tools with
`permissions.allow: ["mcp__<server>__*"]` so the agents are not interrupted by
approval prompts mid-run.

## Relationship to the Kiro originals

- The Kiro agent files under `clients/kiro/agents/` (design notes in `docs/design/agents/`)
  remain the authoring source of record and are unchanged.
- These `.md` files are derived from them. If you change an agent's behaviour,
  decide which is canonical and regenerate the other (the standalone agents
  were generated by `tmp/translate_agents.py`, kept for reference).
- A project may use both assistants at once: Kiro from `.kiro/agents/`, Claude
  Code from `.claude/agents/`.
