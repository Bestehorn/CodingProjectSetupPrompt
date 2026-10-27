# Delivery — how a change lands, deploys and is verified (the contract after "PR CI is green")

Installed at `.claude/docs/delivery.md`. NOT auto-loaded: `/work-issue`, the issue-work orchestrator and
`/close-session` read it at their PR step. Mechanism: `scripts/merge_steward.py` (header docstring), the CI
templates under the framework's `templates/ci/`, the `merge-steward` and `stop-failure-recorder` gates. Why it
has this shape: `project-docs/delivery-redesign-2026-10-26.md` in the framework repository.

## 1. The modes (`config/delivery.json`)

| `merge` | `verification` | After PR CI is green the worker… | Who merges | Who verifies after the deploy |
|---|---|---|---|---|
| `steward` | `watcher` | **enqueues and hands off** | the merge steward | the verdict watcher (deploy pipeline's last job) |
| `steward` | `none` | **enqueues and hands off** | the merge steward | nobody: the landing is the final verdict |
| `direct` | `watcher` | merges, records the landing, **hands off** | the worker | the verdict watcher |
| `direct` | `session` | merges, waits for the trunk pipeline and its post-deploy check, closes | the worker | the worker (the pre-2026-10-26 lifecycle) |

No `config/delivery.json` = `direct` + `session`. Read the file at the PR step; never guess the mode.

## 2. What the worker does before the push (everything the PR must carry)

- The evidence (`evidence/REPORT.md`, the wave captures), the ledger rows (`memory_compile.py ledger add`), the
  docs, the issue checklist ticked for every item that is DONE — all committed BEFORE the single push. Nothing
  is pushed to the trunk after the landing: no evidence PR, no ledger PR (measured: 40 % of one project's PRs
  were such follow-ups, each cancelling a real change's trunk run).
- Checklist items that only a deploy can prove get the literal suffix `(post-deploy)` — e.g.
  `- [ ] the dev smoke check passes (post-deploy)`. The watcher ticks exactly those after a green post-deploy
  check; every other item must be ticked by the worker, or the issue is not closed (§5).
- The PR body names its issue(s) with `Refs #N` (a list: `Refs #12, #13`) — the ONLY form the steward reads
  as a reference; "part of" or "related to" is a mention, and a mentioned issue is never landed, verified or
  returned. NEVER a closing keyword (`Closes`/`Fixes`/`Resolves`/`Implements #N`, in the PR description or in
  any commit message on the branch) under `watcher` verification: the host would close the issue at landing,
  before the deploy check, and the steward refuses the PR. `Depends-on: #<PR>` lines order dependent PRs.
- An issue delivered by several PRs carries one `merge-steward: queued PR #<n>` line per PR; the watcher
  verifies it only when every one of them has landed.

## 3. Hand-off (`merge: steward`)

1. PR CI green on the PR head (a red run is fixed in one pass, `ci-owns-the-test-suite.md`).
2. `python scripts/<wrapper>.py enqueue-pr <n>` — it refuses (exit 4, reason printed) unless the queue would
   accept the PR now; fix the reason, do not work around it.
3. Post the hand-off note on the issue — at most ten lines: the PR, the evidence path, what the post-deploy
   check must show, and these two machine-read lines verbatim:
   ```
   merge-steward: queued PR #<n>
   merge-steward: claim-started <the ISO-8601 time the claim was taken>
   ```
4. Append `Phase: HANDED_OFF` (and `Status: IN_PROGRESS` stays) at the END of `resume_state.md`; append
   `Phase: DONE` + `Status: COMPLETED` to `workflow_state.md` (the spec workflow is complete). The tracker claim
   (in-progress label, assignee) STAYS: the issue is still in flight until it is verified.
5. Close out at once — a single-issue run runs the close-out checks as its last step, a loop run its HAND_OFF
   clean-up: worktree, local branch, per-worktree venv, local lock and temp residue go; the REMOTE branch stays
   until the steward lands it. Then the Completion Block with the issue as a `handed off` row.

`HANDED_OFF` releases a single-issue run (`MODE: SINGLE_ISSUE`) and NOTHING else: in `/issues-work` and
`/auto-work` handing one issue off is a checkpoint — record `Phase: LOAD_ISSUES` and select the next issue.

`merge: direct` + `verification: watcher`: merge per the recorded merge authority, then
`python scripts/merge_steward.py record-landing <n>` (it posts the landing line and the
`awaiting-verification` label), then steps 3–5 above (the note's first line is the landing line it posted).

## 4. What happens after the hand-off (not the worker's to wait for)

| Event | Who | Effect on the issue |
|---|---|---|
| PR lands (train green) | steward | comment `merge-steward: landed <sha> (PR #n, …)`, label `awaiting-verification` |
| PR's train red | steward | culprit only: PR `queue-failed`; issue `needs-rework`, claim released (one automatic retry first when it never failed a train before) |
| PR conflicts with the trunk or the PRs ahead | steward | PR `queue-conflict`; issue `needs-rework`, claim released |
| PR CI red, a closing keyword, a draft, a dependency closed unlanded | steward | PR `queue-failed` with the reason; issue `needs-rework`, claim released |
| PR's train could not run CI to a result (no run, cancelled, timed out) | steward | the green trains ahead land; the PR stays queued for ONE retry, then `queue-failed` |
| PR's head moved, it was dequeued or put on hold while its train ran | steward | not landed (its new commits were never tested); it stays as it is, the trains behind it are rebuilt |
| Green post-deploy check on a commit that CONTAINS the landing | watcher | `(post-deploy)` items ticked, `verified`; checklist complete → closed with time spent and the run; else `needs-closeout`, claim released |
| Red post-deploy check on such a commit | watcher | `verification-failed` + `needs-rework`, claim released; the next green deploy containing it verifies it |

Verification is by ANCESTRY (`git merge-base --is-ancestor <landing> <deployed>`): a deploy superseded by a
newer one loses no verdict, and no one waits for a deploy of their own commit.

## 5. Picking work back up

`/issues-work` and `/auto-work` take issues labelled `needs-rework` or `needs-closeout` FIRST (they are open and
unclaimed again). A `needs-rework` issue starts from the comment that returned it: read every failing job, fix
in a fresh worktree off `origin/<trunk>`, push once, PR CI green, enqueue. A `needs-closeout` issue only needs
its open checklist items finished and the issue closed (RESOLVE). A red deploy suspects every issue landed since
the last green one; if the failure is not yours, say so on the issue with the evidence, append the
`reverify` label, and leave the deploy to the steward — sessions never re-run, cancel or dispatch trunk or
deploy runs (one owner for trunk health). `/close-session` treats a handed-off issue as the session's work done.

## 6. Labels (created once per repository; names configurable under `steward` in `config/delivery.json`)

`queue`, `queue-failed`, `queue-conflict`, `queue-retried`, `do-not-merge`, `awaiting-verification`,
`verified`, `verification-failed`, `needs-rework`, `needs-closeout`, `reverify`.
