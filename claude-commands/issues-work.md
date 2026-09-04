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

**Read `.claude/docs/run-identity.md` BEFORE this run's first state write.** It is the
binding contract for run identity, the seeded fields, the release vocabulary, and the gate
verdicts — state written to a path or spelling of your own devising is read by NOTHING
(MEASURED: Incident `invented-run-label`, `.claude/hooks/MIGRATION.md`).

## Resume check

Read `<state_dir>/resume_state.md`. If it shows `Status: IN_PROGRESS`, CONTINUE the recorded
outer phase for the recorded current issue (re-attach to any in-flight worktree / branch / PR)
— do not restart the backlog. If it shows `Status: COMPLETED`, archive it and start fresh. If
it holds only the seeded `Status: NOT_STARTED`, start fresh by appending to that same file.

## Scope, and what does NOT let you stop

If $ARGUMENTS names a specific issue number, prioritize that issue first; otherwise work the
whole backlog by impact/urgency/severity. Either way, `issue-loop-gate.sh` blocks turn-end
while this run has CLAIMED tracked work and has not AFFIRMATIVELY released. Record
`MODE: ISSUE_LOOP` alongside `Status` at the start of the run, so the claim holds across the
window between two issues as well as during one.

The releases the gate recognises are the vocabulary in `.claude/docs/run-identity.md` §5 — a
terminal value must be the WHOLE value of its field (`Phase: DONE` releases;
`Status: COMPLETED (was IN_PROGRESS)` does not), `WORKABLE_ISSUES_REMAIN` gates NOTHING,
and the no-claim release is never a way out of an issue you have already claimed
(blanking `CURRENT_ISSUE`/`MODE` mid-issue is a false record, §5).

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
