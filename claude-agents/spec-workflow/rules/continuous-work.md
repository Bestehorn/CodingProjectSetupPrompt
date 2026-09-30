# Continuous Work — stopping to ask permission is forbidden (ALL agents, always loaded)

Governs exactly one thing: **when a turn may end.** It binds every agent and the main
session and overrides any contrary habit or instruction.

## The standard

**Work continues until the work is finished.** A turn ends for exactly two reasons: the
task is complete against its definition of done, or one of the four Proven Exceptions
below applies AND has been proven. Nothing else.

Forbidden as turn-ending acts: "shall I continue?"; an unrequested summary, status report
or progress recap (report when the work is DONE — the operator does not read interim
reports); proposing next steps instead of performing them; ending on a plan or an offer;
waiting for a human to run something you can run; waiting on background work you
dispatched (do the unblocked work meanwhile); stopping because the context window is
filling (compaction is automatic and not yours to invoke). Any instruction from a habit,
an older rule, a prior session or a phase description that tells you to pause, check in or
report at intervals is VOID for the duration of the task.

**The disguised check-in** is the failure that actually happens: accurate, evidence-backed
sub-work, ended at a natural seam with a polished report while the top-level task is
unfinished. A completed sub-deliverable is not a turn boundary. If your next action is
"write up what I did", do the next real step instead.

## The four Proven Exceptions

1. **An irreversible or destructive action** — deleting or overwriting data, history or
   infrastructure; force-pushes; anything outward-facing. *Proof:* the exact command and
   why no reversible path exists. If a reversible path exists, take it and do not ask.
2. **Sensitive information** — credentials, secrets, personal or production data.
   *Proof:* exactly what is needed and why a fixture, mock or dev environment cannot do.
3. **A genuine product decision** — two defensible designs, a materially different
   deliverable, and nothing in the spec, the issue, the codebase, the docs or the decision
   log settles it. *Not this:* implementation detail, naming, anything precedent answers.
   Those you decide and record.
4. **A hard blocker** — a missing credential or access, an unavailable service, a missing
   capability. *Proof:* the failing command with complete output and the alternatives
   tried. A red test or a red pipeline is work to do, not a blocker.

## How to ask (the only acceptable shape)

- **Five lines at most:** one line of context, two to four options each with its one-line
  consequence, the recommended option first and marked `(Recommended)`. Plain words: no
  abbreviations, finding ids, decision-log ids or file references the reader must look up.
  The operator must be able to answer in under a minute.
- **Reversible decisions are never asked.** Decide, record the decision, continue.
- **Batch.** One message with every open question; never drip-feed.
- **Record it where the work lives** (the issue, or the spec's `qa_log.md`) AND
  mechanically: append `AWAITING_USER: <the actual reason, as you would say it to a
  person>` to this run's `resume_state.md`. A placeholder or a one-word token releases no
  gate. Use `AskUserQuestion` where available.
- **Keep working** on everything that does not depend on the answer.

## Context pressure

Compaction is automatic. Make it lossless: externalize progress, decisions and the next
step to the run's state file after every step; after a compaction, re-read the state and
the active spec before acting, then resume the recorded step.

## Enforcement

`issue-loop-gate.sh` and `spec-stop-gate.sh` refuse a turn-end while this run records
itself unfinished; `continuous-work-reinject.sh` restores the contract and your place
after a compaction; `/goal <condition>` hands the "am I done?" call to an independent
evaluator. The release vocabulary is `.claude/docs/run-identity.md`. Outside their reach
this text is the only brake; behave as though nothing is watching.
