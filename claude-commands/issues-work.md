---
description: Autonomously work the open-issue backlog end to end — select the highest-priority not-in-progress issue, fix it via the spec/TDD cycle with proof, open a PR, drive CI green, merge, clean up, close, and repeat. Resumable.
argument-hint: "[optional: a specific issue number to start with, or blank to work the whole backlog]"
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch, Agent(spec-author, spec-researcher, spec-review-agent, test-architect, standards-reviewer, best-practice-reviewer, security-reviewer, devops-iac-reviewer, adversarial-verifier, spec-implementer)
---

Run the autonomous issue-work lifecycle for this project, following the agent
definition in `.claude/agents/issue-work-orchestrator.md` exactly. (This command runs
the orchestrator's logic in the current session; for a dedicated long run you may
instead launch `claude --agent issue-work-orchestrator`.)

**User-invocable only, exactly like the four narrower entry points beside it.** This
command carries `disable-model-invocation: true` for the same reason `/work-issue`,
`/auto-work`, `/continue-work` and `/close-session` do: it pushes, merges and closes
issues autonomously, so it must never begin because a prompt merely mentioned an issue
number. Nothing here needs model invocation — the orchestrator is launched as an agent or
typed by the user — and this is the WIDEST of the five (the whole backlog, with no named
issue to bound the blast radius), so the reason applies to it most, not least. Keep the key.

## Run identity — read this before writing any state (NON-NEGOTIABLE)

`session-register.sh` (SessionStart) has ALREADY created this session's `runs/<run-id>/`
directory and seeded `resume_state.md` and `workflow_state.md` in it. **Your job is to UPDATE
those files. You do not choose where they live.**

- **Find the path:** read `.claude/agent-state/issue-work-orchestrator/registry.json`, find
  the entry whose KEY is THIS session's `session_id`, and use that entry's `state_dir` value
  VERBATIM (it is relative to `.claude/agent-state/issue-work-orchestrator/`). If the entry
  carries no `state_dir`, the path is `runs/<run_id>/` from the same entry. The `State file:`
  line in the `## Your recorded place in the work` block that `continuous-work-reinject.sh`
  prints at session start / resume / compaction is the same path character for character — use
  it if you have it. If the directory is missing, create the registry-derived path and nothing
  else — never a second run directory beside it.
- **NEVER invent a readable run-id label** such as `run-issue<N>-<timestamp>`. Every Stop gate
  resolves this session's state from the registry-derived path; state written anywhere else is
  read by NOTHING, which silently disables every gate for the entire session. MEASURED: an
  agent told to "derive RUN_ID" wrote its state under a label of its own, both Stop hooks were
  consequently silent no-ops for the whole session — neither had ever blocked a turn-end in
  that clone across 189 registered sessions — and the run ended FOUR spurious turns under a
  standing instruction never to stop without a proven reason.
- **State fields are plain `Name: value` lines**, and hooks read the **LAST** occurrence of
  each. **Correct a value by APPENDING a new block at the END of the file** — never edit an
  earlier line, never prepend. A bold `**Name:** value` spelling is read by NO hook. Prose you
  add for a human reader must contain no `Name: value` lines.
- **Keep `SESSION_ID:` intact.** It is the rung by which a hook recovers this run if state
  ever lands under a differently-named directory.

## Resume check

Read `<state_dir>/resume_state.md`. If it shows `Status: IN_PROGRESS`, CONTINUE the recorded
outer phase for the recorded current issue (re-attach to any in-flight worktree / branch / PR)
— do not restart the backlog. If it shows `Status: COMPLETED`, archive it and start fresh. If
it holds only the seeded `Status: NOT_STARTED`, start fresh by appending to that same file.

## Scope, and what does NOT let you stop

If $ARGUMENTS names a specific issue number, prioritize that issue first; otherwise work the
whole backlog by impact/urgency/severity. Either way, `issue-loop-gate.sh` blocks turn-end
while this run has CLAIMED tracked work and has not AFFIRMATIVELY released. A claim is a
non-placeholder `CURRENT_ISSUE`, or a non-placeholder `CURRENT_SPEC`, or a `MODE` naming an
orchestrator mode (`ISSUE_LOOP`, `SINGLE_ISSUE`, `SPEC`, `BACKLOG`, `AUTO`; a hyphen reads as
an underscore). Record `MODE: ISSUE_LOOP` alongside `Status` at the start of the run, so the
claim holds across the window between two issues as well as during one.

**`Status: IN_PROGRESS` is not what arms the gate, and no single status word is.** The polarity
is INVERTED: any `Status` the gate does not recognise as explicitly idle counts as work in
flight, so guessing a status word wrong HOLDS the turn instead of quietly freeing it. There are
exactly four releases:

  * an explicitly idle `Status` — `NOT_STARTED`, `NOT_YET_STARTED`, `UNSTARTED`,
    `NOT_IN_PROGRESS`, `NOT_WORKING`, `IDLE`, `PENDING`, `NEW`, `NONE`, `UNSET`;
  * a terminal `Phase` **or** a terminal `Status` — `DONE`/`COMPLETE`/`COMPLETED`/`FINISHED`/
    `CLOSED`/`ABANDONED`/`ESCALATED`/`CANCELLED`/`CANCELED` — matched as the WHOLE value of the
    field, so
    `Phase: DONE` releases and `Status: COMPLETED (was IN_PROGRESS)` does not;
  * a substantive `AWAITING_USER` line naming the actual reason (the literal `<reason>`, any
    other angle-bracketed template are rejected as placeholders, and a one-word token such as
    `no`/`false`/`0`/`waiting` is rejected by the substance test's own deny-list — the effect is
    the same, the mechanism differs);
  * no tracked work claimed at all — which is how an ordinary chat session stays unblocked, and
    never a way out of an issue you have already claimed.

`WORKABLE_ISSUES_REMAIN` only selects the WORDING of that refusal (finish the
issue in flight vs. select the next one); **it does NOT decide whether the gate blocks.** It
used to BE the block condition, so a single-issue run that set it to `no` switched the gate off
for itself — that is fixed, and the belief that `no` releases you is precisely what the old
gate rewarded.

## The lifecycle to run

Run the lifecycle from `issue-work-orchestrator.md`: Discovery (venv, ISSUE_MECHANISM
via the wrapper script, in-progress convention, merge authority, clean tree) → the outer
loop LOAD_ISSUES → SELECT → PREPARE (worktree + branch) → CLASSIFY (Type1/Type2) → FIX
(embedded spec/TDD core, proof with evidence) → PROOF_GATE → DOCUMENT → PR (rebase,
line-by-line conflict resolution, push, open, self-approve+merge if allowed, monitor CI)
→ MERGE_CLEANUP → RESOLVE → refresh, until no not-in-progress open issue remains.

Honor all the mandates in the agent definition: wrapper-only remote ops, evidence-not-
assertion (the implementer never certifies its own work; the adversarial-verifier
refutes), no workarounds, never overwrite others' changes, checkpoint after every step into
the registry-derived state files (appending, never editing in place), escalate only once when
genuinely blocked, and never touch `.kiro/`.
