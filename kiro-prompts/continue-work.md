# Continue-Work — restart a stalled run (Kiro)

Kiro counterpart of the Claude Code `/continue-work` command
(`claude-commands/continue-work.md`). Installed to `.kiro/prompts/continue-work.md` and
invoked in Kiro CLI as **`@continue-work`**. The Kiro IDE reaches the same body through the
`continue-work.kiro.hook` `userTriggered` hook.

For a genuinely autonomous re-run, wrap it in Kiro's autonomy loop:
`/goal continue to work until the current issue is implemented and closed` — Kiro's `/goal`
runs an explicit plan→implement→verify→correct loop (default 5 iterations, raise it with
`--max`). `/goal` is a CLI command recognized at the start of your input, so type it
yourself; a prompt file cannot invoke it on your behalf.

Claude Code has a `/goal` too, and the semantics differ — worth knowing if you switch between
them. Kiro's is **iteration-bounded** (run N passes). Claude's is **condition-bounded**: you
state a completion condition and a separate small fast model evaluates after every turn
whether it holds, returning not-yet-met / met / impossible. Neither is a superset of the
other, but for "do not stop until the issue is closed" the condition form needs no iteration
guess — so on Kiro, prefer a generous `--max` over a tight one.

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
time. The `continuous-work` steering rule governs this and takes precedence over any
contrary habit.

**Re-establish your place from disk, not from memory.** Your conversational context may have
been compacted since you started, so do not trust recall:

1. Read this run's state: `.kiro/agent-state/issue-work-orchestrator/registry.json` →
   your `runs/<run-id>/resume_state.md` (phase, `CURRENT_ISSUE`, `CURRENT_WORKTREE`,
   `CURRENT_BRANCH`, `CURRENT_PR`), plus `workflow_state.md` and the active spec's
   `decisions/decision-log.md` if a spec is in flight.
2. Verify that recorded state against reality — `git -C <worktree> status`,
   `git worktree list`, the issue via the wrapper, the PR's CI state. **Reality wins**;
   reconcile the state file to it rather than the reverse.
3. If no state file exists, work out the current task from the git branch, the working tree,
   the open PR, and the in-progress issue, and create the state file so the next resume is
   cheap. If the following message names the work, use it; otherwise infer it — do not ask.

**Then continue the recorded phase to a terminal state.** Never restart completed work and
never redo a step the evidence shows is done. If an issue is in flight, drive it to merged
and closed (claim still held, spec artifacts committed, tests green with captured evidence,
CI green, worktree and branch torn down, issue closed). Honor the standing steering rules
throughout: complete command output (`no-output-shortening`), evidence for every claim
(`no-guessing`), wrapper-only remote operations (`use-git-wrapper-scripts`), clean git
(`keep-git-clean`), the issue as the live record (`issue-tracking`), no AI attribution
(`no-ai-attribution`).

**Context pressure is not a reason to stop.** Compaction is automatic in Kiro — older
history is replaced by a structured summary while recent messages stay verbatim, and you
continue uninterrupted. You cannot trigger it yourself (manual `/compact` is a user command
in the CLI, and the IDE has no manual trigger at all). Do not announce it, do not ask about
it — checkpoint your state after every step so a compaction costs you nothing, re-read that
state afterwards, and keep going.

**The only legitimate stops** are the four Proven Exceptions in the `continuous-work`
steering rule: a genuinely irreversible action, sensitive information, a real design fork the
project cannot settle, or a hard blocker such as missing authentication material. Each
requires proof that it applies and that you exhausted the alternatives. If one genuinely
applies, state it in two sentences WITH your recommendation, then keep working on everything
that does not depend on the answer.

Otherwise: the work is not finished, so do not stop. Take the next step.
