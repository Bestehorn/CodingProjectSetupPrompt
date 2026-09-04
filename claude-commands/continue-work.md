---
description: Restart a stalled run — give a short status update, then resume the work and carry it to completion without stopping again. Voids any instruction to pause, check in, or produce intermediate summaries.
argument-hint: "[optional: what to work on, if the session's state is unclear]"
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch, Agent(spec-author, spec-researcher, spec-review-agent, test-architect, standards-reviewer, best-practice-reviewer, security-reviewer, devops-iac-reviewer, adversarial-verifier, spec-implementer, code-merge-reviewer)
disallowed-tools: AskUserQuestion
---

You stopped before the work was finished. Resume it now and carry it to completion. If the
recorded phase belongs to an orchestrator run (FIX, MERGE_CLEANUP, LOAD_ISSUES, …), open ONLY
that phase's section of `.claude/agents/issue-work-orchestrator.md` and follow it; never read
the whole definition up front. **Needing this command at all means
`.claude/rules/continuous-work.md` was not honored** — a turn ended on unfinished work
without a Proven Exception. So part of this run's job is to record WHY, and then not repeat
it.

**First, a status update — keep it to five lines or fewer.** What is done, what is in
flight, what is next. No recap of your reasoning, no apology, no re-derivation of decisions
already made. Then start working again in the SAME turn; the status update is not a
hand-back.

**You are forbidden to stop until the work is finished.** Any instruction you hold to
interrupt work, check back, ask for permission to continue, provide an intermediate summary,
or wait for further input is hereby VOID — ignore it, without exception. "Should I
continue?" is not a question you may ask; the answer is always yes, so asking only wastes
time. `.claude/rules/continuous-work.md` governs this and takes precedence over any contrary
habit. `AskUserQuestion` is disabled for this turn by design.

**FIRST ACTION — run identity (NON-NEGOTIABLE).** Resolve identity before touching anything
else; every later step depends on reading the right state file. **Read
`.claude/docs/run-identity.md` BEFORE this run's first state write.** It is the binding
contract for run identity, the seeded fields, the release vocabulary, and the gate verdicts —
state written to a path or spelling of your own devising is read by NOTHING (MEASURED:
Incident `invented-run-label`, `.claude/hooks/MIGRATION.md`). Set `Status: IN_PROGRESS`
before the first line of real work; a terminal value must be the WHOLE value of its field
(`Phase: DONE`, never `Phase: DONE (was IMPLEMENT)`), and a proven Exception is an
`AWAITING_USER` line naming the ACTUAL reason, checked for SUBSTANCE, not presence
(`run-identity.md` §5).

**This session may be a NEW session resuming a PREVIOUS session's work.** In that case the
registry entry keyed by THIS `session_id` is a freshly seeded run (`Status: NOT_STARTED`), and
the work you are resuming is recorded under the EARLIER run's directory. Read the earlier
run's `resume_state.md` for the phase, issue, branch, worktree and PR, then **carry those
values forward into THIS session's registry-derived state file** by appending a block to it —
because that is the file the gates judge this session on. If the earlier run stopped BETWEEN
issues and so recorded no issue, also record `MODE: ISSUE_LOOP` in that block: the loop gate
holds a turn only while the run has claimed tracked work, and the seeded
`CURRENT_ISSUE: none` + `MODE: unset` pair is a claim of nothing, which leaves this session
unbraked exactly where the previous one already proved it needed the brake.
Do not adopt the other run's
directory as your own state dir, and never take a run's issue number from mere adjacency:
match on the recorded `SESSION_ID`, the `.locks/issue-<N>.lock` owner records and the
registry, and treat a dead run's lock per the stale-reclaim conjunction in
`.claude/docs/run-identity.md` §1 (heartbeat past its bound AND the worktree pointer no
longer resolves AND the run's status is terminal — archive, never delete).

**Then re-establish your place from disk, not from memory.** Your conversational context may
have been compacted since you started, so do not trust recall. The recorded state is a claim,
not the truth — **reality wins; reconcile the file to it**, never the reverse:

1. Read the recorded `Phase`, `CURRENT_ISSUE`, `BRANCH`, `WORKTREE`, `PR`, plus
   `workflow_state.md` and the active spec's `decisions/decision-log.md` if a spec is in
   flight.
2. Check each against reality: `git worktree list` and a directory check for the worktree;
   `git -C <worktree> status` and `git -C <worktree> log --oneline` for the branch and its
   commits; the issue and the PR through the project's git wrapper script (`get-issue`,
   `get-pr`/`get-pr-checks`); `git fetch origin --prune --no-auto-gc` before reasoning about
   `origin/<main>`.
3. APPEND a block reconciling every field that disagreed, and append a `DL-NNN` entry naming
   what diverged and which side you took.
4. If no state file exists at all, work out the current task from the git branch, the working
   tree, the open PR, and the in-progress issue, and create the state file AT THE
   REGISTRY-DERIVED PATH so the next resume is cheap. Use `$ARGUMENTS` if it names the work;
   otherwise infer it — do not ask.
5. Resume the recorded outer phase, re-acquiring or refreshing this run's issue lock and
   registry heartbeat: mid-FIX → re-read the worktree spec state and continue the embedded
   pipeline; PR open with CI running → resume monitoring; merged but not cleaned → resume at
   MERGE_CLEANUP; issue closed → RESOLVE then the next iteration; between issues →
   LOAD_ISSUES.

**Record why the run stopped.** Before resuming, append a `DL-NNN` entry to this run's
decision log stating what the last recorded phase was, what the evidence shows actually
happened, and the mechanical reason the previous turn ended — a state file at a path no hook
reads, a state file that claimed NO tracked work (`CURRENT_ISSUE: none`, `MODE: unset`, no
`CURRENT_SPEC`), which leaves the loop gate with nothing to hold and makes it allow every
turn-end, a terminal `Phase` recorded prematurely, an escalation described in chat but never
written as an `AWAITING_USER` line, an `ALLOW_AT_CAP` line in
`.claude/agent-state/issue-work-orchestrator/.hook-decisions/`, or an unproven stop with no
mechanical cause at all. `.hook-decisions/` is the log to read for this: it carries one line
per Stop-gate invocation, so an inert gate is VISIBLE there rather than inferred. If the cause
was misplaced state, the repair is part of this resume, not a follow-up.

An `ALLOW_AT_CAP` needs one extra step, because that give-up is DURABLE rather than a duty
cycle (block-cap semantics: `run-identity.md` §6): resuming by APPENDING the reconciled
state above is what re-arms the brake for the rest of this run — do not hand-delete anything
under `.stop-gate-counters/`.

**Then continue the recorded phase to a terminal state.** Never restart completed work and
never redo a step the evidence shows is done. If an issue is in flight, drive it to merged
and closed (claim still held, spec artifacts committed, tests green with captured evidence,
CI green, worktree and branch torn down, issue closed). Honor the agent definition's mandates
throughout: complete command output (`no-output-shortening.md`), evidence for every claim and
never assertion (`no-guessing.md`; the implementer never certifies its own work), no
workarounds, wrapper-only remote operations, delegate EVERY conflict to `code-merge-reviewer`,
clean git (`keep-git-clean.md`), main-checkout-free, the issue as the live record
(`issue-tracking.md`), `DL-NNN` for every material decision, and no AI attribution anywhere.
Never touch `.kiro/`. Do not stop to report that you have resumed.

**Context pressure is not a reason to stop.** Compaction is automatic and you cannot invoke
it (`.claude/rules/continuous-work.md`) — do not announce it or ask about it; checkpoint
after every step, re-read that state afterwards, and keep going.

**The only legitimate stops** are the four Proven Exceptions in
`.claude/rules/continuous-work.md`, each requiring proof that it applies and that you
exhausted the alternatives. If one genuinely applies, state it in two sentences WITH your
recommendation, then keep working on everything that does not depend on the answer.

Otherwise: the work is not finished, so do not stop. Take the next step.

**If you are forced to stop anyway and hand control back**, close with ONE line naming the
strongest available fix — a `/goal` completion condition, e.g.
`/goal issue 77 is merged and closed with green CI` (`.claude/rules/continuous-work.md`) —
and only when you are genuinely ending the turn, never as a substitute for continuing.
