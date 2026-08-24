---
description: Restart a stalled run — give a short status update, then resume the work and carry it to completion without stopping again. Voids any instruction to pause, check in, or produce intermediate summaries.
argument-hint: "[optional: what to work on, if the session's state is unclear]"
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch, Agent(spec-author, spec-researcher, spec-review-agent, test-architect, standards-reviewer, best-practice-reviewer, security-reviewer, devops-iac-reviewer, adversarial-verifier, spec-implementer, code-merge-reviewer)
disallowed-tools: AskUserQuestion
---

You stopped before the work was finished. Resume it now and carry it to completion.

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

**Re-establish your place from disk, not from memory.** Your conversational context may have
been compacted since you started, so do not trust recall:

1. Read this run's state: `.claude/agent-state/issue-work-orchestrator/registry.json` →
   your `runs/<run-id>/resume_state.md` (phase, `CURRENT_ISSUE`, `CURRENT_WORKTREE`,
   `CURRENT_BRANCH`, `CURRENT_PR`), plus `workflow_state.md` and the active spec's
   `decisions/decision-log.md` if a spec is in flight.
2. Verify that recorded state against reality — `git -C <worktree> status`,
   `git worktree list`, the issue via the wrapper, the PR's CI state. **Reality wins**;
   reconcile the state file to it rather than the reverse.
3. If no state file exists, work out the current task from the git branch, the working tree,
   the open PR, and the in-progress issue, and create the state file so the next resume is
   cheap. Use `$ARGUMENTS` if it names the work; otherwise infer it — do not ask.

**Then continue the recorded phase to a terminal state.** Never restart completed work and
never redo a step the evidence shows is done. If an issue is in flight, drive it to merged
and closed (claim still held, spec artifacts committed, tests green with captured evidence,
CI green, worktree and branch torn down, issue closed). Honor the standing rules throughout:
complete command output (`no-output-shortening.md`), evidence for every claim
(`no-guessing.md`), wrapper-only remote operations, clean git (`keep-git-clean.md`), the
issue as the live record (`issue-tracking.md`), no AI attribution.

**Context pressure is not a reason to stop.** Compaction is automatic and you cannot invoke
it. Do not announce it, do not ask about it — checkpoint your state after every step so a
compaction costs you nothing, re-read that state afterwards, and keep going.

**The only legitimate stops** are the four Proven Exceptions in
`.claude/rules/continuous-work.md`: a genuinely irreversible action, sensitive information,
a real design fork the project cannot settle, or a hard blocker such as missing
authentication material. Each requires proof that it applies and that you exhausted the
alternatives. If one genuinely applies, state it in two sentences WITH your recommendation,
then keep working on everything that does not depend on the answer.

Otherwise: the work is not finished, so do not stop. Take the next step.

**If you are forced to stop anyway and hand control back**, close with one line telling the
user the strongest available fix: set a completion condition with `/goal`, e.g.
`/goal issue 77 is merged and closed with green CI`. `/goal` keeps Claude working across
turns until an independent evaluator confirms the condition holds, so completion stops being
your judgement call. Say it once, in one line, and only when you are genuinely ending the
turn — never as a substitute for continuing.
