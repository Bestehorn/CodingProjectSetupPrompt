# Bringing the Advanced Claude Code Workflow Back to Kiro

> ## ⚠️ SCOPE CORRECTION (2026-06-15, added after clarification)
>
> The user clarified that **"Kiro" means the Kiro IDE**, not the Kiro CLI. Most of the
> "ports natively" verdicts in §0–§2 below rest on **Kiro CLI**-only features (headless
> `kiro-cli chat --no-interactive --agent`, the CLI `subagent` built-in tool with
> `availableAgents`/`trustedAgents`, `--resume-id`, and — critically — the CLI `stop`-hook
> `decision:block` force-continue). **Those do not all hold for the IDE.** Read
> **§6 "IDE-specific correction"** at the bottom first; it is the authoritative answer to
> the clarified question. The original §0–§5 are retained as the **CLI-surface** analysis
> (still accurate for the CLI, and relevant because the IDE shares repo `.kiro/` config).
>
> **One-line bottom line:** Kiro is really **three** surfaces — IDE, CLI, and **Web**.
> The IDE has custom sub-agents and within-one-spec autonomy but **no unattended
> backlog loop, no headless launch, and no stop-hook force-continue**. The autonomous
> backlog-orchestrator pattern is **not achievable in the IDE alone**; it lives on the
> **CLI** (scriptable, your own specialists) or partially in **Kiro Web** (single-issue
> autonomous flow, built-in specialists, human merge). See §6.

**Date:** 2026-06-15
**Scope:** The Claude Code setup prompt + agent fleet have advanced well beyond
`KiroProjectSetupPrompt.v2.txt` (autonomous issue-work orchestrator, spec/TDD engine,
enforced gates, merge agent, shared rules). This report determines which of those
advances can be implemented in **Kiro** so the two tools are interchangeable, and which
hit **hard limits**. **NOTE:** §0–§5 were written treating "Kiro" broadly and lean on
**Kiro CLI** features; §6 corrects this for the **Kiro IDE** specifically.

All Kiro facts below were researched against the official docs at `kiro.dev/docs/`
(CLI custom agents, subagents, hooks, headless, specs, steering, MCP, permissions,
built-in tools) in June 2026. Source URLs are listed at the end. Where the docs are
silent, it is flagged as *uncertain* rather than asserted.

---

## 0. Executive summary

**The good news is bigger than expected: ~90% of the advanced Claude Code workflow ports
to the Kiro CLI, and several pieces are native there.** When I first ported Kiro → Claude
Code (see `ClaudeCodePortingAnalysis.md`), I assumed the orchestration features were a
Claude Code strength. Researching the current Kiro docs reverses that on the key axes:

- **Kiro CLI has a first-class `subagent` tool** with the exact `availableAgents` /
  `trustedAgents` settings — native orchestrator→specialist delegation, no flattening
  tricks needed. (Claude Code can only delegate from the main session.)
- **Kiro CLI runs headless**: `kiro-cli chat --no-interactive --agent <name> "<prompt>"`
  — the direct analog of `claude -p --agent`, with `--resume-id` for resumption.
- **Kiro CLI hooks can BLOCK and FORCE-CONTINUE**: a `preToolUse` hook exit code 2
  blocks a tool; a `stop` hook returning `{"decision":"block","reason":"..."}` prevents
  the agent from stopping and feeds the reason back as a new turn. Both of my
  machine-enforced gates (the TDD commit gate and the "keep working the backlog" loop
  gate) replicate directly.
- **Kiro enforces per-agent command/path allow-deny at runtime** (`toolsSettings.shell.
  allowedCommands`/`deniedCommands`/`denyByDefault`, `write.allowedPaths`/`deniedPaths`)
  — *stronger* than Claude Code, where path/command scoping is global, not per-agent.
- **Per-tool MCP `autoApprove`** — which Claude Code does **not** have. A Kiro advantage.

So the autonomous issue-work-orchestrator, the spec/TDD specialist fleet, the shared
rules, and the enforced gates are all reproducible on the Kiro CLI. The catch is almost
entirely about **where** the work runs: the powerful, enforceable, scriptable surface is
the **Kiro CLI**, while Kiro's *native* spec mode (and its nicest task-runner UX) lives
in the **IDE** and is **not driveable headlessly**. The handful of genuine hard limits
are listed in §3.

| Capability axis | Kiro CLI verdict |
|---|---|
| Custom agents + orchestrator→specialist delegation | **Native** (`subagent` tool) |
| Headless / scripted autonomous run | **Native** (`--no-interactive --agent`) |
| Block a tool / commit (TDD gate) | **Native** (`preToolUse` exit 2) |
| Force the loop to continue (don't stop with work left) | **Native** (`stop` hook `decision:block`) |
| Per-agent command/path enforcement | **Native, stronger than CC** |
| Per-tool MCP auto-approval | **Native, CC has no equivalent** |
| Resumable sessions | **Native** (`--resume-id`) + your own state files |
| Spec/TDD engine (requirements/design/tasks, review-until-clean, evidence) | **Rebuild as CLI agents** (same as you already did for CC) |
| Native spec mode driven from the CLI/headless | **Hard limit** (IDE-only) |
| Adversarial-verify / proof-with-evidence as a built-in | **Not native** (impose via hook+agents) |
| Git worktree-per-issue isolation | **No native support** (orchestrate via shell, outside Kiro) |
| >4 specialists running concurrently | **Hard limit** (max 4 concurrent subagents) |
| Deep recursive nesting (orchestrator→conductor→leaves) | **Unconfirmed** — design flat, as you already do |

---

## 1. What "advanced" means here (the Claude Code feature inventory to port)

The features built across this project that go beyond `KiroProjectSetupPrompt.v2.txt`:

1. **`issue-work-orchestrator`** — a main-session agent that autonomously works the whole
   open-issue backlog: load issues → select highest-priority → claim in-progress →
   worktree+branch → fix via the spec/TDD engine → proof-gate → document on issue → PR →
   CI → merge → cleanup → close → repeat; resumable via `resume_state.md`.
2. **The spec/TDD engine** (`spec-workflow/`): `spec-conductor` + ~10 specialists
   (spec-author, spec-researcher, test-architect, adversarial-verifier, the four
   reviewers, spec-implementer), driven through `phases/spec-phase-*.md`, with an
   adversarial review loop to zero blocking findings and evidence-based proof.
3. **`code-merge-reviewer`** — mandatory line-by-line conflict resolver, regression-gated.
4. **Enforced gates** (`hooks/`): `spec-tdd-gate.sh` (block commit without green
   evidence), `spec-stop-gate.sh` + `issue-loop-gate.sh` (force the agent to keep
   working), `red-for-right-reason.sh`.
5. **Shared always-loaded rules** (`rules/`): `agent-state-convention` (DL-NNN decision
   log), `no-ai-attribution`, `keep-git-clean`, `issue-tracking`.
6. **Slash commands** (`claude-commands/`): `/spec-*`, `/issues-work`.

---

## 2. Feature-by-feature: how each maps onto Kiro

### 2.1 Custom agents + delegation — NATIVE (and the crux is solved)

Kiro CLI custom agents are JSON configs in `.kiro/cli/agents/*.json` (project) or
`~/.kiro/cli/agents/*.json` (global) with the exact fields your design uses: `name`,
`description`, `prompt` (inline or `file://`), `tools`, `allowedTools`, `toolsSettings`,
`mcpServers`, `resources`, `hooks`, `model`. (You already have the *originals* of most of
your agents in this repo's `cli-agents/` — they predate the Claude port.)

The decisive finding: Kiro has a built-in **`subagent` tool** ("Delegate complex tasks to
specialized subagents that run in parallel with isolated context"), configured via
`toolsSettings.subagent.availableAgents` (glob allow-list of spawnable agents) and
`toolsSettings.subagent.trustedAgents` (glob list that runs without approval) — the exact
fields. So the orchestrator delegates to specialists **natively**, no main-session-only
restriction. Kiro additionally documents **task-dependency DAGs** and **review loops**
(`target`/`trigger`/`max_iterations`, hard-capped at 10) — an implement→review→fix
pipeline is a documented native pattern, close to your spec review loop.

> **Architecture note:** keep the design **flat** — orchestrator delegates directly to
> leaf specialists (exactly the "orchestrator embeds the phases" decision you already
> made for Claude Code). Kiro confirms one level of delegation; it does **not** confirm
> recursive nesting (orchestrator→conductor→leaves), and the *default* subagent's
> toolset excludes `subagent`. Flat is the safe, portable choice in both tools.

### 2.2 Autonomous headless run — NATIVE

`kiro-cli chat --no-interactive --agent <orchestrator> --trust-tools=read,grep,write
"<prompt>"` (or `--trust-all-tools`), authenticated by `KIRO_API_KEY`, is the
`claude -p --agent` analog. It accepts piped stdin (`gh issue list | kiro-cli chat
--no-interactive …`). The `/goal` command provides an explicit autonomous
plan→implement→verify→correct loop (default 5 iterations, `--max`). Tool approval is
pre-granted via `allowedTools` + `toolsSettings` + `trustedAgents`, so a fully unattended
run is achievable.

### 2.3 The enforced gates — NATIVE on the CLI (this surprised me most)

Kiro **CLI** hooks (in the agent JSON `hooks` object, keyed by trigger →
`{command, matcher, timeout_ms, cache_ttl_seconds}`) are a true veto/enforcement model,
not just triggers:

- **`preToolUse`** — exit code `2` **blocks** the tool and returns STDERR to the LLM
  ("Can block the tool use"). → your `spec-tdd-gate.sh` (block `git commit` without green
  evidence; block `export` env-var commands) ports directly. Match the shell tool, read
  `tool_input` from the STDIN event JSON, exit 2 to veto.
- **`stop`** — returning `{"decision":"block","reason":"…"}` on STDOUT **prevents the
  agent from stopping** and feeds `reason` back as a new user message, "continuing the
  conversation." → your `issue-loop-gate.sh` / `spec-stop-gate.sh` (keep working while
  the backlog has workable issues, or while tests are red) ports **directly**.
- **`postToolUse`** — runs after a tool (format/lint/audit); cannot undo it (same as CC).
- **`agentSpawn` / `userPromptSubmit`** — inject context (STDOUT added to context).

Plus **runtime command/path enforcement** per agent: `toolsSettings.shell.allowedCommands`
/`deniedCommands` (anchored regex, deny-before-allow, `denyByDefault`) and
`write.allowedPaths`/`deniedPaths`. A denied command genuinely cannot run — this is
*stronger and more granular* than Claude Code, where these are global glob rules.

### 2.4 Spec/TDD engine — REBUILD as CLI agents (exactly what you already did)

This is the nuance worth internalizing. Kiro has an excellent **native** spec workflow —
`requirements.md` (EARS `WHEN … THE SYSTEM SHALL …`), `design.md`, `tasks.md`, an
"Analyze Requirements" pass that catches inconsistencies/gaps, a **"Run all Tasks"**
dependency-wave task runner, and Autopilot autonomous execution — **but it is an IDE
experience and is not documented as driveable from the CLI/headless.** The CLI docs never
mention specs. So your autonomous CLI orchestrator **cannot trigger native spec mode**; it
must reproduce the spec engine as CLI custom agents + steering + prompts — which is
exactly what you already built for Claude Code, so it transfers almost verbatim. Native
TDD/red-green/proof-with-evidence is **not** built in either (the only example is an
opt-in `preToolUse` "test-first" hook in Kiro's own "how TDD should feel" blog), and there
is **no** native adversarial-verify-and-refute loop. So your `test-architect` /
`adversarial-verifier` / `red-for-right-reason` discipline stays imposed by you — same as
in Claude Code.

The upside: when working **interactively in the Kiro IDE**, you get the native spec mode,
dependency-wave task runner, and Analyze Requirements *for free* — nicer than Claude Code
for hands-on spec authoring. The autonomous CLI path and the interactive IDE path are two
different experiences; plan to use both.

### 2.5 Shared rules → steering — NATIVE

`.kiro/steering/*.md` with inclusion modes maps your rules cleanly: `inclusion: always`
≈ always-loaded rules (your `no-ai-attribution`, `keep-git-clean`, `issue-tracking`,
`agent-state-convention` become four `always` steering files); `fileMatch` +
`fileMatchPattern` ≈ path-scoped rules; `manual` (`#name`) ≈ on-demand; **`auto` +
`description`** ≈ description-gated loading (an option Claude Code rules lack). File
references via `#[[file:path]]`. Caveat (same as CC): steering is **advisory**, not
enforcement — the hard guarantees come from the CLI hooks + `toolsSettings`, not steering.

### 2.6 MCP + git wrappers — NATIVE (one Kiro advantage)

MCP in `.kiro/settings/mcp.json` with **per-tool `autoApprove`** (`["tool_a","*"]`) — a
capability Claude Code does **not** have (there you approve via global permission rules).
Git/PR/CI/issue operations are shell commands or MCP servers the agent runs, optionally
constrained by `allowedCommands` — your wrapper-script pattern works identically.

---

## 3. The genuine hard limits

These are the things that do **not** fully port, with the evidence:

1. **Native spec mode is IDE-only — not CLI/headless-driveable.** The CLI docs never
   mention specs, `requirements.md/design.md/tasks.md`, "Analyze Requirements", or "Run
   all Tasks". An autonomous CLI orchestrator cannot invoke native spec creation/execution
   on an issue. *Mitigation:* reproduce the spec engine as CLI agents (already done for
   CC); use native spec mode only in interactive IDE sessions.

2. **Max 4 concurrent subagents.** "Spawn up to 4 subagents simultaneously." Your ~10
   specialists and the 6-reviewer design panel must run in **batches/waves**, not all at
   once. *Mitigation:* the spec pipeline is mostly sequential anyway; batch the reviewer
   panel into two waves of ≤4.

3. **Recursive subagent nesting is unconfirmed.** The default subagent's toolset excludes
   `subagent`; the docs neither confirm nor forbid a custom subagent spawning further
   subagents. *Mitigation:* design flat (orchestrator → leaf specialists), the same
   decision you already made for Claude Code — so this costs nothing.

4. **No git-worktree awareness.** Kiro is cwd-agnostic; sessions persist per-folder, with
   no worktree/branch-isolation concept. Your worktree-per-issue isolation must be
   orchestrated **outside** Kiro: a wrapper script (or the orchestrator's own shell tool)
   does `git worktree add … && cd … && kiro-cli chat --no-interactive --agent … "fix
   issue X"`. *Note:* this is essentially how it works in Claude Code too; Kiro just has
   no worktree helper, so it's pure shell.

5. **Headless forbids mid-session input + is gated to paid tiers.** `--no-interactive`
   means fully fire-and-forget (no interactive pickers), and headless/API-key auth
   requires a paid tier (and possibly admin enablement). *Mitigation:* the orchestrator
   already operates without mid-run questions (it posts clarifications to the issue and
   moves on); ensure the `KIRO_API_KEY` tier is provisioned.

6. **Turn/context limits bound a long run** (unquantified in the docs), and the
   autonomous loop stops on context exhaustion / repeated-failure. *Mitigation:* the same
   chunk-and-resume design you already have — per-issue worktrees + `resume_state.md` +
   `--resume-id` — so an interrupted backlog run continues.

7. **Two hook systems, only the CLI one enforces.** The IDE GUI hooks can block only
   `preToolUse`/`promptSubmit` and have **no** stop-veto/force-continue; only the **CLI**
   hook system has the `stop` `decision:block` loop-continuation. *Mitigation:* put all
   enforced gates in the **CLI agent `hooks`**, not the IDE hook UI.

8. **Forward-compat risk: Kiro CLI 3.0 (Early Access)** mentions a new unified agent
   harness, `permissions.yaml`, Markdown agent configs, and a Spec agent, but does **not**
   mention `subagent`/delegation — so the current `toolsSettings.subagent` schema may
   change. *Mitigation:* build against the documented current CLI schema; revisit when v3
   is GA.

Two items I could **not** verify and would test before relying on them: (a) whether the
IDE and CLI actually share `.kiro/steering` + MCP config (paths overlap but sharing is
unstated), and (b) the exact numeric turn/context caps.

---

## 4. Where Kiro is actually *ahead* of Claude Code

Worth noting for interchangeable use — Kiro natively does several things you had to hand-
build or cannot do in Claude Code:

- **Per-tool MCP `autoApprove`** (CC has no per-tool MCP approval).
- **Native spec mode** with EARS, "Analyze Requirements", and a **dependency-wave "Run
  all Tasks" runner** (you built this by hand for CC).
- **Per-agent runtime command/path enforcement** (CC's permissions are global, not
  per-agent).
- **Native `subagent` delegation with parallel isolated contexts** + documented review
  loops and task DAGs (CC subagents can't nest and you flattened around it).
- **Built-in resumable sessions** (`--resume-id`, `--list-sessions`).

---

## 5. Concrete plan to adapt the Kiro side

The goal: a `KiroProjectSetupPrompt.v3.txt` (or additive v2 update) + a Kiro CLI agent
fleet that mirrors the Claude Code capability, so you can run the same autonomous
issue-resolution workflow in either tool. You already have the *base* Kiro agents in
`cli-agents/`; this adds the advances.

**A. Port the new agents into `cli-agents/` (Kiro JSON form).** Translate each Claude
agent body to a Kiro custom-agent JSON (the inverse of what `claude-agents/` did):
- `issue-work-orchestrator` → JSON with `tools` including `subagent`,
  `toolsSettings.subagent.availableAgents`/`trustedAgents` listing the specialists, and
  `hooks.stop`/`hooks.preToolUse` pointing at the gate scripts.
- The `spec-workflow` fleet (conductor + author + researcher + test-architect +
  adversarial-verifier + 4 reviewers + implementer) → one JSON each. Keep the flat
  delegation model (orchestrator → leaf), and batch the 6-reviewer panel into ≤4-wide
  waves to respect the concurrency cap.
- `code-merge-reviewer` → JSON; the orchestrator lists it in `availableAgents`.
- The shared rules → four `.kiro/steering/*.md` files with `inclusion: always`.

**B. Re-wire the gates as CLI agent hooks.** The three hook scripts
(`spec-tdd-gate.sh`, the loop gate, `red-for-right-reason.sh`) work as-is; reference them
from each agent's `hooks` object: `preToolUse` (matcher on the shell/write tool) for the
commit/TDD gate, `stop` (`decision:block`) for the keep-working gate. Confirm the
STDIN-JSON contract (`tool_name`/`tool_input`/`tool_response`) field names against the CLI
hooks reference and adjust the scripts' parsing (they currently target Claude Code's
hook JSON).

**C. Enforce scope via `toolsSettings`, not just steering.** Move the "commit only
green", "never commit temp files", "no AI attribution in names" guarantees into
`deniedCommands` regex + `write.allowedPaths` where they're expressible, keeping the
steering text for the advisory parts.

**D. Wrapper scripts + worktree orchestration.** Keep the git/PR/CI wrapper scripts
(GitHub/GitLab) — they're shell, tool-agnostic. Add the worktree create/cd/launch
sequence to the orchestrator's prompt (pure shell, since Kiro has no worktree helper) and
expose the wrapper subcommands via `allowedCommands` or an MCP server with per-tool
`autoApprove`.

**E. The setup prompt itself.** Update `KiroProjectSetupPrompt` to install the new
`.kiro/cli/agents/*.json`, the new steering files, the hook scripts, and the wrapper
subcommands — and document the headless launch (`kiro-cli chat --no-interactive --agent
issue-work-orchestrator --trust-tools=… "work the backlog"`) and resume (`--resume-id`).

**F. Decide the interactive-vs-headless split explicitly.** Document that *spec
authoring* can use the native IDE spec mode (richer), while *autonomous backlog work*
uses the CLI agent fleet (the part that ports). They share steering + wrapper scripts.

I'd suggest building this in the same order I built the Claude side: shared steering
first, then the spec specialists, then the orchestrator + gates, then the setup-prompt
wiring — validating each agent JSON against the Kiro configuration-reference schema as I
go. I have not made any changes for this report; say the word and I'll start with (A).

---

## Sources (kiro.dev/docs, June 2026)
- CLI custom agents + configuration reference: `/cli/custom-agents/`,
  `/cli/custom-agents/configuration-reference/`, `/cli/custom-agents/creating/`
- Subagents + built-in tools: `/cli/chat/subagents/`, `/cli/reference/built-in-tools/`
- Autonomy + headless + sessions: `/cli/chat/`, `/cli/chat/goal/`,
  `/cli/chat/permissions/`, `/cli/headless/`, `/cli/reference/cli-commands/`
- CLI hooks (enforcement): `/cli/hooks/`
- IDE hooks: `/hooks/`, `/hooks/types/`, `/hooks/actions/`
- Specs: `/specs/`, `/specs/best-practices/`, `/specs/feature-specs/`; `/chat/autopilot/`
- Steering + MCP: `/steering/`, `/mcp/`, `/mcp/configuration/`
- TDD blog: `/blog/how-tdd-should-feel/`
- Forward-compat: `/cli/experimental/`, `/cli/v3/`

---

## 6. IDE-SPECIFIC CORRECTION (the authoritative answer to the clarified question)

The user works in the **Kiro IDE**. Researching the IDE docs (`/docs/`) separately from
the CLI (`/docs/cli/`) and Web (`/docs/web/`) docs changes the conclusion materially.
**Kiro is three products with separate docs trees and different capabilities.** Here is
what is true for each, mapped to the advanced Claude Code workflow.

### 6.1 What the Kiro IDE *does* have

- **Custom sub-agents — SUPPORTED (this corrects a CLI/IDE conflation).** The IDE has its
  own subagents at `.kiro/agents/*.md` (Markdown + YAML front matter: `name`,
  `description`, `tools`, `model`, `includeMcpJson`, `includePowers`) — a *different*
  format and directory from the CLI's `.kiro/cli/agents/*.json`. The main agent delegates
  to named specialists ("Use the code-reviewer subagent…", or `/code-reviewer`), they run
  in parallel with isolated context, and return results to the main agent. So your
  orchestrator→specialist *roster* is reproducible in the IDE.
  - **IDE caveats with teeth:** IDE subagents **"do not have access to Specs"** and
    **hooks "will not trigger in subagents."** There is **no `availableAgents` /
    `trustedAgents`** allow-list (selection is by `description` or explicit call). So you
    cannot scope/auto-trust delegation the way the CLI (or your Claude design) does.
- **Within-one-unit autonomy — SUPPORTED.** Autopilot mode makes changes across the
  codebase "without asking for approval at each step"; the spec **"Run all Tasks"**
  dependency-wave runner executes a spec's tasks concurrently in waves. **Quick Plan**
  collapses the Requirements→Design→Tasks approval gates.
- **Native spec mode — SUPPORTED and richer than Claude Code** (EARS requirements,
  Analyze Requirements, design/tasks, the wave runner). This is a real IDE advantage for
  *interactive* spec authoring.
- **IDE hooks — block-only, no force-continue.** `Pre Tool Use` (and `Prompt Submit`) can
  **block** via a Shell Command non-zero exit → your TDD/commit gate works. But **`Agent
  Stop` fires only AFTER the turn ends and cannot veto the stop** — there is **no IDE
  equivalent of the CLI `stop`-hook `decision:block`**. Your "keep working the backlog"
  loop gate has **no IDE mechanism.**
- **Shared repo config — SUPPORTED.** `.kiro/steering/` works identically across IDE,
  CLI, and Web, so your four shared rules port as steering regardless of surface.

### 6.2 What the Kiro IDE *cannot* do (the hard limits for your workflow)

1. **No unattended backlog loop.** The IDE's autonomy is scoped to **one human-initiated
   spec/task**. Nothing in the IDE selects the next issue and repeats. Your
   `issue-work-orchestrator`'s defining behavior — loop the whole backlog with no human —
   is **not an IDE capability.**
2. **No headless / scriptable launch.** There is **no flag/API to open the IDE and run a
   spec non-interactively.** A human clicks "Run all Tasks" / initiates the spec. (Headless
   is a **CLI**-only mode.) So you cannot drive the IDE from a wrapper script or cron.
3. **No stop-hook force-continue.** As above — the loop-continuation gate that makes the
   Claude orchestrator keep going does not exist in the IDE hook model.
4. **Subagents can't use Specs and don't fire hooks** — so an IDE "specialist" can't itself
   run the native spec engine or be gated by your TDD hook. The enforcement + spec power
   and the delegation power don't compose in the IDE the way they do in your design.
5. **Resume is backward-only.** IDE **Checkpoints** rewind code+context (a safety net);
   the docs do **not** document forward session-resume of an interrupted run. (Spec
   task-completion state implies you can re-open and continue, but interrupted-run resume
   is not documented.)

### 6.3 The autonomous backlog pattern actually lives on two *other* surfaces

- **Kiro CLI** — the scriptable surface. Headless `kiro-cli chat --no-interactive --agent`,
  the `subagent` tool with `availableAgents`/`trustedAgents`, the `stop`-hook
  force-continue, `--resume-id`. Everything in §0–§5 applies **here**. This is where your
  full autonomous orchestrator-with-your-own-specialists is achievable.
- **Kiro Web** (cloud, paid Pro+, GitHub-app, `us-east-1` preview) — a polished
  **single-issue** autonomous flow: label an issue `kiro` (or `/kiro`), it sandboxes,
  plans, **delegates to built-in specialist sub-agents** (analyze → write → verify), and
  **opens a PR automatically**; **Automations** add cron-scheduled unattended PR-opening
  runs. It honors repo `.kiro/steering/` and has its own Specs + MCP/Powers.
  - **But the backlog-orchestrator gaps remain:** **no backlog loop** (one task per
    session / one prompt per scheduled run; up to 10 parallel tasks but nothing *feeds*
    them); **no autonomous merge** ("nothing reaches your main branch without your
    review"); **CI-fixing is human-feedback-triggered, not self-driven to green**; **no
    enforced TDD/proof-before-PR**; and **sub-agents are built-in, NOT user-definable** (you
    cannot author your specialist roster in Web); **hooks in Web are undocumented**.

### 6.4 Revised recommendation (for an IDE-centric user who wants both tools interchangeable)

The earlier "build the orchestrator as Kiro agents" plan (§5) is **correct only for the
Kiro CLI**, not the IDE. Given the IDE clarification, the realistic split is:

- **Interactive feature/bug work → Kiro IDE.** Use native spec mode (EARS, Analyze
  Requirements, Quick Plan), Autopilot + "Run all Tasks", and IDE subagents
  (`.kiro/agents/*.md`) for delegated review/specialist help. Put the four shared rules in
  `.kiro/steering/` and the TDD/commit gate as an IDE `Pre Tool Use` hook. This gives you
  a strong, mostly-native spec/TDD experience — richer than Claude Code for hands-on work
  — but **human-initiated, one feature at a time.**
- **Unattended backlog automation → Kiro CLI (primary) or Kiro Web (managed).** The
  autonomous `issue-work-orchestrator` (select→fix→PR→CI→merge→next, with your own
  specialists and enforced gates) is achievable **on the Kiro CLI**, scripted, mirroring
  the Claude Code design via §5. **Kiro Web** is the lower-effort managed alternative for
  the *single-issue* slice (label → autonomous PR), but you give up the backlog loop,
  custom specialists, autonomous merge, and enforced TDD.
- **Net:** for the IDE *specifically*, treat the goal as **"interchangeable for
  interactive spec/TDD work" (yes, largely native and even nicer)** but **"interchangeable
  for unattended backlog orchestration" (no — that requires the CLI or Web, not the IDE).**
  If full interchangeability of the *autonomous orchestrator* is the priority, the Kiro
  **CLI** is the surface to target, and a practical hybrid is: **CLI** runs the
  unattended loop, the **IDE** is where you review/iterate, both sharing the same
  `.kiro/steering/` and wrapper scripts in the repo.

### 6.5 Honest uncertainties (verify before relying)
- Whether IDE `.kiro/agents/` subagents and CLI `.kiro/cli/agents/` are ever unified
  (different dirs/formats today).
- IDE interrupted-run **forward**-resume mechanics (only backward Checkpoints documented).
- Kiro Web: any true issue-*opened* event trigger, auto-merge, and whether a cleverly
  written Automation prompt could iterate multiple issues in one run (docs are silent —
  do not assume).
- Whether Kiro CLI 3.0 (Early Access) keeps the current `toolsSettings.subagent` schema.

### 6.6 Added sources (IDE & Web)
- IDE subagents: `/docs/chat/subagents/`; Autopilot: `/docs/chat/autopilot/`;
  Checkpoints: `/docs/chat/checkpoints/`; IDE hooks: `/docs/hooks/`, `/docs/hooks/types/`,
  `/docs/hooks/actions/`; Quick Plan: `/docs/specs/quick-plan/`.
- Kiro Web: `/docs/web/`, `/docs/web/autonomous-mode/`, `/docs/web/automations/`,
  `/docs/web/github/`, `/docs/web/specs/`, `/docs/web/steering/`, `/docs/web/sandbox/`,
  `/docs/web/using-the-agent/creating-tasks/`, `/docs/web/setup/`.

---

## 7. IF YOU SWITCH TO THE KIRO CLI: component-by-component translation

This answers the direct question — *if I use the Kiro CLI instead of the IDE, how much of
the current Claude Code prompt's mechanics translate, and why would the experience be
better?* Short answer: **~85–95% translates, most of it close to 1:1, and a few pieces are
genuinely nicer than Claude Code.** The Kiro CLI is the rebranded Amazon Q Developer CLI
(`kiro-cli`); the features below are from `/docs/cli/*`.

### 7.1 Translation table (every mechanic in the current Claude prompt)

Fidelity legend: **1:1** = direct documented equivalent; **High** = same outcome, minor
reshaping; **Medium** = achievable with real work/constraints; **Gap** = no documented
equivalent, must work around.

| Claude Code mechanic (what you built) | Kiro CLI equivalent | Fidelity |
|---|---|---|
| Custom agents in `.claude/agents/*.md` | Custom agents in `.kiro/cli/agents/*.json` (name, description, prompt/`file://`, tools, allowedTools, toolsSettings, mcpServers, resources, hooks, model) | **1:1** (JSON not MD) |
| Orchestrator delegates to specialists (`Agent(...)`) | Built-in `subagent` tool + `toolsSettings.subagent.availableAgents`/`trustedAgents` | **1:1** (your exact field names) |
| Claude rule: subagents can't nest → you flattened | Kiro: nesting unconfirmed → keep the same flat design | **1:1** (same design choice) |
| `claude -p --agent X "..."` headless run | `kiro-cli chat --no-interactive --agent X "..."` (+ `--trust-tools=`/`--trust-all-tools`, `KIRO_API_KEY`, stdin piping) | **1:1** |
| `spec-tdd-gate.sh` (PreToolUse blocks commit w/o green evidence) | CLI `preToolUse` hook, exit code 2 blocks the tool, STDERR returned to the LLM | **1:1** |
| `issue-loop-gate.sh` / `spec-stop-gate.sh` (Stop hook forces the loop to continue) | CLI `stop` hook returning `{"decision":"block","reason":"…"}` → reason becomes a new user turn, agent keeps going | **1:1** |
| `red-for-right-reason.sh` + PostToolUse side-effects | CLI `postToolUse` hook (runs after; cannot undo — same as Claude) | **1:1** |
| Permission allow/deny (`Bash(...)`, `Edit(...)`, global) | Per-agent `toolsSettings.shell.allowedCommands`/`deniedCommands`/`denyByDefault` + `write.allowedPaths`/`deniedPaths` | **High** (per-agent + regex — *stronger*) |
| Shared always-loaded rules (`.claude/rules/*.md`) | `.kiro/steering/*.md` with `inclusion: always` (+ `fileMatch`/`manual`/`auto`) | **1:1** (+ `auto` is a bonus) |
| `.mcp.json` + per-tool approval (Claude has none) | `.kiro/settings/mcp.json` with per-tool `autoApprove: ["tool","*"]` | **High** (Kiro *adds* per-tool approval) |
| Resumable run (`resume_state.md` + relaunch) | Built-in `--resume`/`--resume-id`/`--list-sessions` PLUS your own file-state (works identically) | **1:1+** |
| Slash commands (`/issues-work`, `/spec-*`) | In-session prompts / a launch script; subagents are also invocable like commands | **High** |
| The whole spec/TDD engine (conductor + ~10 specialists + phases + review-to-zero + evidence) | Re-author the specialists as Kiro agents; drive via prompts + review loops (max_iterations ≤10) | **High** (you already built the logic; it transfers) |
| `code-merge-reviewer` (mandatory line-by-line merge) | A Kiro custom agent in `availableAgents`; gate fs_write/git via `preToolUse` | **High** |
| Per-run state namespacing + registry + locks (your recent concurrency work) | Same file-based scheme; Kiro also records each subagent's parent session ID | **High** |
| Git worktree-per-issue isolation | No Kiro worktree concept → pure shell (`git worktree add … && cd … && kiro-cli …`) | **Medium** (same as Claude — shell) |
| 6-reviewer panel running at once | Max **4** concurrent subagents → run in two waves | **Medium** (batch, don't parallelize all) |
| Native spec mode (EARS, Analyze, wave runner) from the loop | IDE-only; **not** driveable from the CLI | **Gap** (rebuild as agents — already done) |
| Deep recursive orchestrator nesting | Unconfirmed in docs | **Gap/avoid** (stay flat) |

### 7.2 Why the experience is *better* than Claude Code (not just equal)

Five things the Kiro CLI gives you that you had to hand-build or cannot do in Claude Code:

1. **Native delegation with your exact contract.** Claude Code subagents *cannot nest*, so
   your orchestrator had to "embed the phases" and the CV suite had to be flattened. Kiro's
   `subagent` tool with `availableAgents`/`trustedAgents` is the orchestrator→specialist
   pattern *as a first-class feature* — closer to your original intent than Claude allows.
2. **Per-agent, regex, runtime-enforced command/path scoping.** In Claude Code,
   permissions are **global** to the session (you noted this limitation repeatedly); a
   delegated agent can't be given a tighter command allow-list than the parent. Kiro's
   `toolsSettings` is **per-agent** and regex-based — the merge agent, the reviewers, and
   the implementer can each have genuinely different, enforced tool scopes.
3. **Per-tool MCP auto-approval.** Claude Code has no per-tool MCP approval (you approve
   via broad permission rules). Kiro's `autoApprove: ["search_docs", …]` per server is
   exactly the granularity you wanted.
4. **Built-in resumable sessions + a native autonomous loop.** `--resume-id` and the
   `/goal` plan→implement→verify→correct loop give you, natively, machinery you assembled
   from `resume_state.md` + the Stop-hook in Claude.
5. **Native spec mode available when you want it.** Even though the *autonomous loop* can't
   call it, you can drop into interactive spec mode (EARS, Analyze Requirements, the
   dependency-wave task runner) for hands-on work — Claude Code has no equivalent; you
   built yours from scratch.

### 7.3 The honest costs of switching

- **The spec/TDD engine is still yours to carry.** Kiro's *native* spec mode is IDE-only
  and not callable from the CLI loop, and there's **no native test-first / adversarial-
  verify / proof-before-merge enforcement** anywhere. So `test-architect`,
  `adversarial-verifier`, the review-to-zero loop, and the evidence discipline remain
  prompt+hook constructs you author — exactly as in Claude Code. Net effort here is a
  port, not a redesign.
- **4-concurrent-subagent cap** → batch the reviewer panel.
- **Hook STDIN/!output contract differs** from Claude's hook JSON — the three gate scripts
  need their field parsing adjusted (`tool_name`/`tool_input`/`stop_hook_active` etc. per
  the CLI hooks reference). Small, mechanical.
- **Headless needs a paid `KIRO_API_KEY` tier** (Pro+), and possibly admin enablement.
- **No worktree helper** — the worktree create/cd/launch is plain shell in the
  orchestrator prompt (it already is, in Claude).
- **Forward-compat risk:** Kiro CLI **3.0 (Early Access)** hints at a new agent harness +
  `permissions.yaml` + Markdown agent configs and does **not** mention `subagent` — so the
  current `toolsSettings.subagent` schema may change. Build against documented-current,
  revisit at GA.
- **Unverified:** exact turn/context caps; whether the recent concurrency refinements
  (registry/locks/per-run namespacing in your `agent-state-convention`) behave identically
  under Kiro's session model — they *should*, since they're pure file-state, but worth a
  dry-run.

### 7.4 Bottom line

If you adopt the **Kiro CLI**, essentially the entire current Claude Code workflow
translates: the orchestrator, the specialist fleet, the enforced TDD + loop gates, the
shared rules, the wrapper-script + worktree pattern, and the resumable per-run state all
have direct Kiro CLI equivalents — and four of them (native delegation, per-agent
enforcement, per-tool MCP approval, built-in resume/loop) are **better** than what Claude
Code offers. The only true rebuild is the spec/TDD *intelligence* (which you already own as
prompts), and the only true gaps are the 4-subagent cap and calling native spec mode from
the loop. A practical adoption: keep one repo with **shared `.kiro/steering/` + wrapper
scripts**, run the **autonomous backlog loop on the CLI**, and drop into **IDE spec mode**
for interactive authoring — the two Kiro surfaces share the repo config, so they're
genuinely interchangeable for your work.

> This remains a documentation-based assessment (I have not executed `kiro-cli`). The
> §7.3 costs — hook field-parsing, the concurrency refinements under Kiro's session model,
> and CLI 3.0 schema drift — are the things to confirm in a first dry-run before a full
> port. No files were changed for this section beyond this report.

---

## 8. RUNNING N PARALLEL `kiro-cli` INSTANCES (the better isolation model)

The natural way to get the separation you have in Claude Code — and to dodge any
subagent-concurrency cap — is **not** one orchestrator fanning out to subagents, but
**N independent `kiro-cli` processes**, one per issue, each in its own git worktree,
each launched headless. This is architecturally cleaner (OS-process isolation) and is
how you'd run a real parallel backlog. The research verdict: **this works and is the
recommended model — with exactly one shared-state caveat that has a clean mitigation.**

### 8.1 What the docs guarantee
- **Sessions are stored per directory.** "Sessions are stored per directory, so each
  project has its own set of sessions"; `--resume`/`--list-sessions` are scoped to the
  current directory; session IDs are UUIDs. → **N instances in N distinct worktree paths
  get logically separate session namespaces.** (`/docs/cli/reference/cli-commands/`)
- **Configs are plain files re-read per process.** Each process independently reads
  `.kiro/agents/*` (note the real path is `.kiro/agents/`, **not** `.kiro/cli/agents/` —
  correcting §2/§7), `.kiro/settings/mcp.json`, and `.kiro/steering/`. No shared
  daemon is documented; `--require-mcp-startup` (exit 3 if MCP fails) reads as per-process
  MCP startup, i.e. each instance spawns its own MCP servers.
- So the **different-worktree case is documented-safe**: separate session namespace,
  separate configs, no documented global lock serializing them.

### 8.2 The one real caveat — the shared `~/.kiro` root
Session state is keyed per-directory but **physically lives under a single global root
(`~/.kiro`, overridable by `KIRO_HOME`)**, which also holds global agents/skills/steering/
settings. The docs **do not** disclose the on-disk format (file-per-session vs. one
SQLite/JSON DB) or whether the every-turn auto-save is atomic/locked. So while the
*keying* is isolated, *concurrent write-safety to the shared store* is **undocumented** —
the plausible (unconfirmed) risk if it's a single DB and many processes save every turn.

**The mitigation is clean and built-in: give each parallel run its own `KIRO_HOME`.**
`KIRO_HOME` explicitly overrides the directory "used for global agents, prompts, skills,
steering, settings, and **sessions**." So per run:

```
KIRO_HOME=.claude-equiv/kiro-homes/issue-<N>  \
  kiro-cli chat --no-interactive --agent issue-fixer \
  --trust-tools=read,write,grep "fix issue <N>"
```

run from that issue's worktree. That fully isolates Kiro's *own* state store per process,
on top of the per-directory session keying — belt and suspenders. (You'd seed each
`KIRO_HOME` with, or symlink it to, the shared global agents/steering so every run uses
the same fleet.)

### 8.3 How this maps to your existing design
Your recent concurrency work in `agent-state-convention.md` (a `registry.json` keyed by
`session_id`, per-run `runs/<run-id>/` subtrees, `mkdir`-based `.locks/`) and
`keep-git-clean.md` (never move shared local `main`; `gc.auto 0` / `--no-auto-gc`; branch
off `origin/<main>`; per-run clean end-state) were built for exactly the "multiple runs
share one clone" hazard — and they map **directly** onto the N-parallel-`kiro-cli` model:
- **`YOUR` file-state** (registry/locks/per-run dirs) governs the orchestrator's *own*
  artifacts and the shared clone's git object store — and is tool-agnostic, so it works
  identically under Kiro.
- **`KIRO_HOME`-per-run** governs Kiro's *own* session store — the piece your file-state
  can't reach. The two together give complete isolation.
- **Worktree-per-issue** gives each process its own working dir (and thus per-directory
  session keying even without `KIRO_HOME`), and your `gc.auto 0` + branch-off-`origin/main`
  rules already neutralize the one genuine shared-object-store git hazard.

So you don't run one orchestrator with a 4-subagent fan-out; you run **a thin launcher**
(shell or a small "dispatcher" agent) that, per selected issue: makes the worktree, sets a
per-run `KIRO_HOME`, and spawns a headless `kiro-cli` fixer process — up to your chosen
parallelism. The "4 concurrent subagents" limit from §7 **does not even apply here** (and,
note, that number is from upstream Amazon Q, not Kiro's own docs); parallelism is bounded
only by what you launch and your machine/API budget.

### 8.4 Verdict
**Yes — parallel `kiro-cli` instances give you the same (arguably stronger, because
OS-level) separation you have in Claude Code, provided each run uses its own worktree and
its own `KIRO_HOME`.** This is the recommended way to do a parallel backlog on Kiro and it
removes the only Medium-fidelity item (the subagent cap) from §7.

**Must verify empirically (docs silent):** (1) the session store's on-disk format and
whether per-turn writes are atomic/locked — the core reason to use `KIRO_HOME`-per-run
until confirmed; (2) that `KIRO_HOME` per process cleanly isolates the whole global store
(very likely, untested); (3) the MCP process model (own subprocesses per instance vs. any
shared component) and the resulting resource cost of N×servers; (4) any `KIRO_API_KEY`
rate/concurrency cap under several simultaneous headless instances; (5) whether two
instances in the *same* directory collide (avoid this — your worktree-per-run design
already does). Sources: `/docs/cli/reference/cli-commands/`, `/docs/cli/headless/`,
`/docs/cli/mcp/`, `/docs/cli/authentication/`, `/docs/cli/experimental/delegate/`.
