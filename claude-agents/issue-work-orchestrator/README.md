# Issue Work Orchestrator

An autonomous, main-session Claude Code agent that works a project's **entire open-issue
backlog end to end**. It is the top layer above the spec-driven + test-driven engine in
[`../spec-workflow/`](../spec-workflow/README.md): for each open issue it selects the
highest-priority one, develops and **proves** a fix through the spec/TDD cycle, opens a
PR, drives CI green, merges, cleans up, closes the issue, and moves on — checkpointing
every step so it is fully resumable.

## The lifecycle

```
claude --agent issue-work-orchestrator      (or  /issues-work)

LOAD_ISSUES  – sync local main with the remote, then re-retrieve ALL open issues FRESH
               via the wrapper (every iteration — never reuse a stale list); drop any
               issue closed/claimed upstream since last time
SELECT       – discard in-progress issues; pick the highest impact/urgency/severity
               (issue X); CLAIM IT NOW — mark issue X in progress on the tracker
               immediately, before any work (re-checking for a race). No workable
               issue left → DONE.
PREPARE      – Remote Sync main; git worktree add .claude/worktrees/issue-<X> -b <branch>
               origin/main (the issue is already claimed in SELECT)
CLASSIFY     – Type1 (quick fix) vs Type2 (full spec) — issue-housekeeping's criteria
FIX          – the embedded spec/TDD engine, run IN the worktree:
                 Type2: REQUIREMENTS → DESIGN → 6-reviewer design loop → TASKS →
                        tasks loop → IMPLEMENT (TDD) → VERIFY (adversarial)
                 Type1: bugfix.md → failing reproduction test → fix → regress →
                        adversarial verify
               (the interactive interview is skipped; the prompt is derived from the issue)
PROOF_GATE   – the orchestrator accepts the proof only if a test reproducing the issue's
               symptom now passes AND the adversarial-verifier could not refute it;
               insufficient → reopen the fix
DOCUMENT     – post a comprehensive fix writeup + evidence on the issue
PR           – rebase on origin/main with line-by-line conflict resolution, stage all
               non-gitignored changes, push, open the PR, self-approve + merge if branch
               protection allows (else poll for approval), monitor CI, fix failures
MERGE_CLEANUP– after merge + remote-branch delete: checkout main, remove the worktree and
               local branch (no leftovers), monitor post-merge CI on main, rework to green
RESOLVE      – close the issue with links to the merged PR + evidence
→ refresh → LOAD_ISSUES
```

You stay out of the loop entirely except for a **single batched escalation** if the agent
is genuinely blocked (an ambiguous issue, an unsatisfiable proof, a genuinely ambiguous
merge conflict, an undiagnosable CI failure, or a missing wrapper subcommand), and a final
report when the backlog is clear.

### Two standing disciplines that keep parallel work safe

- **Fresh issue data every iteration.** LOAD_ISSUES re-retrieves the whole open-issue
  list from the remote at the start of each loop and never reuses a stale snapshot —
  if an issue was closed or claimed by someone else while the agent worked the previous
  one, it is dropped, so the agent never duplicates work that was fixed in parallel.
- **Claim-on-select.** The moment an issue is chosen, the agent marks it in progress on
  the tracker (assignee and/or in-progress label) — before any code is written — so
  other workers and future iterations skip it.
- **Remote Sync.** Local code is re-synced with the remote (fetch + fast-forward/rebase
  with line-by-line conflict resolution) before any work begins, at the start of each
  iteration, right after the worktree is created, after the fix completes (before the
  PR), and after each merge — so the agent never builds on a stale base or overwrites
  others' changes.

## How it relates to the other issue agents

| Agent | Scope | Remote? | Output |
|---|---|---|---|
| `issue-intake` | Turn ONE informal observation into a well-formed filed issue | files the issue | a new issue |
| `issue-housekeeping` | Batch-triage ALL issues; local Type1 quick-fixes; draft specs for Type2 | **no push** (local ephemeral branch) | issues closed / triaged in place |
| **`issue-work-orchestrator`** | **Deliver issues** one at a time, full lifecycle | **pushes, PRs, merges, monitors CI** | merged + closed issues with proof |

Use `issue-intake` to capture work, `issue-housekeeping` to triage and clear easy debt,
and `issue-work-orchestrator` to actually deliver fixes to `main` autonomously. A common
flow: housekeeping classifies the backlog → the orchestrator delivers the real fixes.

## Why it embeds the spec engine (and does not call `spec-conductor`)

Claude Code subagents **cannot spawn other subagents**. `spec-conductor` is itself a
main-session orchestrator that delegates to ~10 leaf subagents — so the orchestrator
cannot invoke it as a subagent. Instead the orchestrator **plays the conductor role
itself** for the FIX phase: it reads the same phase fragments
(`.claude/specs/_workflow/phases/spec-phase-*.md`) and delegates to the same leaf agents
(`spec-author`, the six reviewers, `test-architect`, `adversarial-verifier`,
`spec-implementer`, `spec-researcher`), which are listed in its `Agent(...)` allowlist.
One session, one context, no nested `claude`.

> **Worktree caveat (important).** A delegated subagent inherits the *session's* working
> directory — the **main checkout**, not the worktree. The orchestrator therefore passes
> the **absolute worktree path** to every delegate ("write the spec under
> `<wt>/.claude/specs/<slug>/`, code under `<wt>/src/`, tests under `<wt>/test/`"), runs
> all git/test commands with `git -C <wt>` / `cd <wt> && …`, and verifies each delegate's
> writes landed in the worktree via `git -C <wt> status`. If, in practice, path-passing
> proves fragile, the documented fallback is to drive the FIX phase as a **headless child**
> — `cd <wt> && claude -p --agent spec-conductor "<issue-derived prompt; skip the
> interview>"` — which runs as its own main session inside the worktree and can delegate
> normally. The embedded approach is the default; the headless child is the escape hatch.

## Install

Depends on the spec-workflow being installed first (ClaudeCodeSetupPrompt.txt Part 12 —
the leaf agents, the phase fragments under `.claude/specs/_workflow/phases/`, the
`agent-state-convention` rule, and the TDD/evidence hooks).

```bash
mkdir -p .claude/agents .claude/commands
cp claude-agents/issue-work-orchestrator/issue-work-orchestrator.md  .claude/agents/
cp claude-commands/issues-work.md                                    .claude/commands/
```

Also ensure the git wrapper (`scripts/github_wrapper.py` or `scripts/gitlab_wrapper.py`)
implements the PR/merge/CI subcommands the orchestrator needs (the setup prompt Part 6.2
lists them: `get-pr`, `get-pr-checks`, `approve-pr`, `merge-pr`, `delete-remote-branch`,
and `list-issues` with state/assignee/label filters, plus the existing issue/run
subcommands), and add `.claude/worktrees/` to `.gitignore`. `ClaudeCodeSetupPrompt.txt`
Part 13 does all of this for you.

## Run it

```bash
claude --agent issue-work-orchestrator      # work the whole backlog
# or, in an existing session:
/issues-work                                # start or resume
/issues-work 42                             # prioritize issue #42 first
```

To resume after any interruption, just relaunch the same way (or say "continue the work
on the existing issues of this project") — the agent reads
`.claude/agent-state/issue-work-orchestrator/resume_state.md` and continues mid-lifecycle
(including re-attaching to an open PR mid-CI or a half-built worktree).

## Permission posture (autonomy)

This agent is designed for long autonomous runs and performs real remote operations
(push, PR, merge). Recommended posture:

- `acceptEdits` permission mode plus an `allow` list covering `Bash(git *)`,
  `Bash(git worktree *)`, the venv test/CI commands, and the wrapper subcommands
  (`Bash(python scripts/github_wrapper.py *)` etc.). This auto-approves the routine work
  while still surfacing anything unexpected.
- `bypassPermissions` ONLY in an isolated environment (container/VM/CI runner). It removes
  all prompts; rely on the agent's own gates (PROOF_GATE, adversarial-verifier, the TDD
  hooks) and the wrapper's read-only/scoped operations for safety.
- **Self-merge authority** is honored only where branch protection permits; otherwise the
  agent opens the PR, drives CI green, and polls for an external approval before merging.

## State & resumability

- Orchestrator coordination state (spans issues, survives worktree deletion):
  `.claude/agent-state/issue-work-orchestrator/` — `resume_state.md` (master state
  machine), `workflow_state.md` (mirrors the active FIX phase so the TDD hooks fire),
  `issue_queue.md`, `iteration_log.md`, `environment.md`, `decision-log.md`.
- Per-issue work (committed and merged with the fix): `<worktree>/.claude/specs/<slug>/`
  with the spec, `decisions/decision-log.md` (DL-NNN), and `evidence/` (the proof chain).
- Everything follows `.claude/rules/agent-state-convention.md`. `.claude/agent-state/`
  and `.claude/worktrees/` are gitignored. `.kiro/` is never touched.
