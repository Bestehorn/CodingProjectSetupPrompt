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

## Live updates (resume-anywhere)

Post progress to the issue continuously, not only at the end: a short status comment at
each meaningful step (done / next / links to branch, PR, evidence), checklist updates,
and the current branch/worktree/PR and spec/evidence locations. Bias toward
over-documenting: if the session dies, the issue alone must carry enough context to
continue. **Every question put to the user, and the answer, goes on the issue as a
comment, verbatim** — a Q&A decision must never live only in transient chat.

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

Close with a final comment linking the merged PR and the evidence, the checklist fully
ticked (or remaining items explicitly deferred with a reason), and the time spent. A
deferred item is NOT an automatic follow-up issue — route it through
`issue-filing-discipline.md` (fix now if small and clear; ONE gated issue if it needs
research/design/out-of-scope work; else the findings ledger), and let the deferral reason
name which happened.
