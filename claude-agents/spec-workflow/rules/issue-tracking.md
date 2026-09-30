# Issue Tracking: Checklists, Metadata, and Live Updates (ALL agents, always loaded)

Governs an issue that EXISTS; whether one should exist at all is
`issue-filing-discipline.md` (observed defects only, fix-first, zero filings valid) —
read that before creating anything. All tracker operations go through the project's git
wrapper script (`use-git-wrapper-scripts`).

The goal: **the issue is the durable, shared record of the work.** At any moment, any
other agent or human must be able to pick it up and continue — progress, decisions,
questions, answers, and remaining work are kept ON THE ISSUE, updated continuously.
Trackers differ (GitHub, GitLab): use what the wrapper/host supports, skip a missing
optional field cleanly and note it — never treat one as a blocker.

## Checklists

- When filing decomposable work, include a task-list checklist (`- [ ]` items), one per
  concrete step a later session would take.
- During implementation, USE it: tick items (`- [x]`) via the wrapper as each is genuinely
  completed (with evidence), and add newly-discovered items. The checklist must always
  reflect reality — it is a living progress record, not decoration. (Historically agents
  ignored these lists entirely; that is the gap this rule closes.)
- A tick is a claim like any other (`no-guessing.md`): write it when the item is DONE, never
  ahead of the work — the list is what a later session reads to know where things stand, so
  a tick that runs ahead of reality is worse than no checklist at all.

## Live updates (resume-anywhere, at phase transitions)

The issue carries enough to resume from, not a step-by-step diary. Post ONE short note at
each phase transition — claimed (branch, worktree, tier); spec approved (spec path);
implementation pushed (PR link, evidence path); merged and closed (time spent, evidence)
— plus the checklist ticks as items genuinely complete. Step-level progress lives in the
run's `resume_state.md`, not on the issue. A typical issue carries four to six notes from
an agent; twenty is a defect. **Every question put to the user, and the answer, goes on
the issue as a comment, verbatim** — a Q&A decision must never live only in transient
chat.

## Metadata (set what the host supports)

- **Claiming (DETERMINISTIC, fail-closed):** claim with the wrapper's single verified
  command — GitLab `issue start <iid>` / GitHub `start-issue <n>`. It is idempotent and
  fail-closed: adds the in-progress label ADDITIVELY, assigns, re-reads and verifies
  both, exits non-zero otherwise. **NEVER set labels via a whole-set
  `issue update --labels` replace** — it silently drops other labels and has repeatedly
  caused claims to vanish and duplicate work. Use the additive `issue label-add` /
  `issue label-remove` primitives for every label change. If claim verification fails or
  someone else holds the issue: do not start work; release your local lock and pick
  another. Release an unactionable claim with `issue release <iid>`.
- **Start date**: record when work started (field, else a dated comment).
- **Time tracking**: record time spent on completion (e.g. GitLab `/spend`, else in the
  closing comment).
- **Parent/epic/links**: set them so the hierarchy stays intact.
- **State/labels**: move through the host's states via the additive primitives only.

## Closing

**Every task item done is a PRECONDITION for closing, not a nicety.** Re-read the issue and
count its task list before you close: an unticked item means the issue is not closeable. The
one exception is an item whose deferral is recorded ON THE ISSUE with its reason and its
routing — and recorded when the decision was taken, not invented at the moment of closing,
which is just closing over unfinished work with extra words. The same applies to a parent
whose work is tracked as CHILD ISSUES: every child closed, or the parent is not closeable.

Close with a final comment linking the merged PR and the evidence, the checklist fully
ticked, and the time spent. A deferred item is NOT an automatic follow-up issue — route it
through `issue-filing-discipline.md` (fix now if small and clear; ONE gated issue if it needs
research/design/out-of-scope work; else the findings ledger), and let the deferral reason
name which happened.

**An issue closed with items still unticked is corrected, not explained: REOPEN it**
(`reopen-issue <n>` / `issue reopen <iid>`), re-claim it, comment every outstanding item onto
it, finish them all, then close it again with the checklist complete. Reopening is
reversible, so it needs no permission (`continuous-work.md` Exception 1) and is never a
question for the user. `/close-session` audits this at the end of a session and will reopen
what you left — do not make it the place this gets caught.

All of the above governs closing an issue as DONE. An ADMINISTRATIVE close — duplicate,
obsolete, already resolved elsewhere, won't-do — is a different act: it closes on that
reason with its evidence, and unticked items are expected there because they were never
going to be done. Name which kind of close it is in the closing comment; the
every-item-ticked precondition binds the first kind only.
