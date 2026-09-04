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
report when the backlog is clear. In particular, the agent **never pauses between issues
to ask which one to tackle next or whether to continue** — it selects the next issue by
its own ranking and keeps going. Order does not matter because every workable issue gets
fixed before it stops, so there is nothing to decide; pausing would just waste time the
agent could spend fixing the next issue.

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
| `issue-intake` | Turn ONE observation into AT MOST ONE well-formed issue; it is also the filing GATE | files the issue when the gate passes | a new issue — or NOT_FILED with the direct fix to make |
| `issue-housekeeping` | Batch-triage ALL issues; local Type1 quick-fixes; draft specs for Type2 | **no push** (local ephemeral branch) | issues closed / triaged in place; never new issues |
| **`issue-work-orchestrator`** | **Deliver issues** one at a time, full lifecycle | **pushes, PRs, merges, monitors CI** | merged + closed issues with proof |

Use `issue-intake` to capture work, `issue-housekeeping` to triage and clear easy debt,
and `issue-work-orchestrator` to actually deliver fixes to `main` autonomously. A common
flow: housekeeping classifies the backlog → the orchestrator delivers the real fixes.

**Filing discipline (standing discipline C).** Defects the orchestrator finds while
working an issue are FIXED, not filed: blocking ones are absorbed into the current change,
small and clear ones are fixed in the same worktree and noted in the commit/PR, and only a
finding that needs extensive research, an evaluation of design options, or work outside
the issue's scope goes to `issue-intake` as ONE gated issue (`Origin: spawned-discovery`,
`Spawned-from: #X`). Everything else becomes a row in `docs/findings-ledger.md`. A run
that resolves issues and files none is the expected shape of a good run — see
[`../spec-workflow/rules/issue-filing-discipline.md`](../spec-workflow/rules/issue-filing-discipline.md),
mechanically backed by `hooks/issue-filing-gate.sh`.

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
cp claude-commands/work-issue.md                                     .claude/commands/
cp claude-commands/auto-work.md                                      .claude/commands/
cp claude-commands/continue-work.md                                  .claude/commands/
cp claude-commands/close-session.md                                  .claude/commands/
```

All five commands drive this same agent, and the last three are not optional extras — they are
the entry points the continuous-work contract is written around:

| Command | Why it is installed |
|---|---|
| `/issues-work` | start or resume the whole-backlog run |
| `/work-issue <X>` | the SAME lifecycle for exactly one named issue, then stop |
| `/auto-work` | the never-stop, unattended whole-backlog run — nobody is watching, so nothing it could ask is worth the wait |
| `/continue-work` | the manual restart after a run stopped early. Needing it means the contract was not honored, so part of its job is to record WHY |
| `/close-session` | the end-of-session close-out: assess the tree, remediate THIS run's own artifacts, record a terminal `Phase`, report whether the session is safe to close |

All five carry `disable-model-invocation: true`, so an autonomous merge-and-close run can never
begin because a prompt merely mentioned an issue. `/close-session` is also what puts a run into a
state the Stop gates release: it records the terminal `Phase` the gate reads.

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
/work-issue 42                              # work ONLY issue #42, then stop
```

`/work-issue <X>` runs this same lifecycle for exactly one named issue: it claims X
in-progress on the tracker (fail-closed `issue start <X>`) before it fetches or creates
anything, works X in its own `.claude/worktrees/issue-<X>/` so it runs in parallel with
sibling sessions, commits the reviewed spec artifacts as their own commit BEFORE
implementation, and stops after X is merged and closed instead of continuing into the
backlog. It also records `MODE: SINGLE_ISSUE`, which is what makes the run GATED — see below.
If X turns out to be closed or claimed elsewhere, it reports and stops rather than substituting
a different issue, recording a terminal `Phase` with the reason, since the gate judges the state
file rather than the report.

### What actually holds and releases the `issue-loop-gate.sh` Stop hook

The gate BLOCKS a turn-end while **both** halves hold: this run has CLAIMED tracked work, **and**
it has not AFFIRMATIVELY released. Getting either half wrong is how a run ends up ungated, so
both are worth stating precisely.

**Claimed work** is any one of: a non-placeholder `CURRENT_ISSUE`; a `CURRENT_SPEC`; or a `MODE`
beginning `ISSUE_LOOP`, `SINGLE_ISSUE`, `SPEC`, `BACKLOG` or `AUTO` (hyphens normalised to
underscores, so `single-issue` matches as well). "Non-placeholder" is strict: an empty value, any
angle-bracketed token such as the literal `<N>`, and `none`/`unset`/`unknown`/`tbd`/`n/a` and
their neighbours all claim NOTHING. This half exists because every session is now seeded and
`OWNED`, so without it an ordinary chat session that happened to record a `Status` was refused and
told to finish "issue none".

**An affirmative release** is one of exactly four things:

- an idle `Status` — and only from the explicit vocabulary
  (`NOT_STARTED`/`NOT_YET_STARTED`/`UNSTARTED`/`NOT_IN_PROGRESS`/`NOT_WORKING`/`IDLE`/`PENDING`/
  `NEW`/`NONE`/`UNSET`);
- a terminal `Phase` **or** `Status` (`DONE`/`COMPLETE`/`COMPLETED`/`FINISHED`/`CLOSED`/
  `ABANDONED`/`ESCALATED`/`CANCELLED`/`CANCELED`), matched WHOLE-VALUE and case-insensitively —
  so `Phase: DONE` releases and `Status: COMPLETED (was IN_PROGRESS)` does not;
- a SUBSTANTIVE `AWAITING_USER` reason. Presence is not enough: `<reason>`, `none`, `no`, `false`,
  `0`, `waiting`, `blocked` and anything too short to be a reason are all rejected;
- no claimed work, per the paragraph above.

**`Status: IN_PROGRESS` is not what holds the turn, and the polarity is INVERTED.** An
UNRECOGNISED `Status` means work IN FLIGHT; only an explicit idle or terminal value releases. So
`WORKING`, `ACTIVE`, `RUNNING`, `IMPLEMENTING`, `in progress` and `in-progress` all hold — they
used to each disable the brake, because it armed on the single literal `IN_PROGRESS` and nothing
told the agent the vocabulary. The failure direction is deliberate: a novel status word now costs
a visible, recoverable refusal that names its own escape, rather than the whole guarantee.

**`WORKABLE_ISSUES_REMAIN` gates NOTHING.** It selects the refusal's WORDING — whole-backlog
"select the next issue yourself" versus single-issue "finish issue X end to end" — and it feeds
the progress fingerprint that resets the block counter. It used to BE the block condition, which
is why `/work-issue`'s deliberate `no` meant this command's runs were never gated at all. Setting
it is still correct for the record; it releases nothing.

Loop safety is the gate's own consecutive-block counter (`HOOK_BLOCK_CAP`, default 8): at the cap
it stands down, says the work is NOT done, and writes a durable marker so the cap is a one-way
stand-down rather than a duty cycle. Recorded progress clears it. Reaching the cap is not a
completion signal — `/continue-work` is.

To resume after any interruption, just relaunch the same way (or say "continue the work
on the existing issues of this project") — the agent reads THIS run's
`.claude/agent-state/issue-work-orchestrator/<state_dir>/resume_state.md`, where `<state_dir>`
is the value `registry.json` already holds for the session (normally `runs/<run-id>/`), and
continues mid-lifecycle (including re-attaching to an open PR mid-CI or a half-built worktree).

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

- Orchestrator coordination state (spans issues, survives worktree deletion), PER RUN under
  `.claude/agent-state/issue-work-orchestrator/runs/<run-id>/` — `resume_state.md` (master
  state machine), `workflow_state.md` (mirrors the active FIX phase so the TDD hooks fire),
  `issue_queue.md`, `iteration_log.md`, `environment.md`, `decision-log.md`. `<run-id>` is
  computed by the `session-register.sh` SessionStart hook and published as `state_dir` in
  `registry.json`; the agent reads that value verbatim and never invents a label of its own.
  An invented label is what caused the original incident: the gates looked for the registry's
  path, the agent had written its state under a readable name of its own, the two namespaces
  never met, and every gate was silently inert from turn one. The library does carry a
  last-resort third rung that scans `runs/*/resume_state.md` for a matching `SESSION_ID:`, and it
  exists to REPAIR exactly that divergence — never as licence to create it, since it only works
  while the `SESSION_ID` line survives. Keep the registry's path. The agent root itself holds
  only the cross-run artifacts: `registry.json`, `.locks/`, and the cross-run `decision-log.md`.
- Per-issue work (committed and merged with the fix): `<worktree>/.claude/specs/<slug>/`
  with the spec, `decisions/decision-log.md` (DL-NNN), and `evidence/` (the proof chain).
- Everything follows `.claude/rules/agent-state-convention.md`. `.claude/agent-state/`
  and `.claude/worktrees/` are gitignored. `.kiro/` is never touched.

## Procedure changelog (maintainers)

Historical notes moved out of the agent definition; current behavior is fully stated
there, and the full incident accounts live in
[`../spec-workflow/hooks/MIGRATION.md`](../spec-workflow/hooks/MIGRATION.md) §Incident
record (installed as `.claude/hooks/MIGRATION.md`).

- **SELECT's tracker claim was once a hand-rolled sequence.** The step originally
  described a re-fetch → additive-label → assign → re-read-verify sequence the agent had
  to execute and remember to verify. It was superseded by the wrapper's single
  fail-closed `issue start <X>` (GitHub `start-issue`), which performs the same sequence
  and exits non-zero if the claim did not land; the definition now states only the
  current command. The live trap that remains documented inline is the whole-set
  `issue update --labels` replace, which drops other labels.
- **`WORKABLE_ISSUES_REMAIN` used to BE the loop gate's block condition** (which is how
  single-issue runs that set it to `no` were never gated); the loop gate armed only on
  the literal `Status: IN_PROGRESS` (Incident `seven-synonyms`); and the evidence gate
  once released on a PREFIX match of a terminal value the loop gate refused (Incident
  `whole-value-vs-substring`). All three were corrected — the semantics the definition
  now points to are the authoritative contract in `.claude/docs/run-identity.md` §5, and
  the "What actually holds and releases" section above describes the corrected gate.
- **The definition's identity section once retold the `invented-run-label` incident and
  the `SESSION_ID` third-rung re-derivation in full**; both are now one-line pointers.
  The authoritative telling is `run-identity.md` §2/§6 and MIGRATION.md.
