# Delivery — how a change lands, deploys and is verified (the contract after "PR CI is green")

Installed at `.claude/docs/delivery.md`. NOT auto-loaded: `/work-issue`, the issue-work orchestrator and
`/close-session` read it at their PR step. Mechanism: `scripts/merge_steward.py` (header docstring), the CI
templates under the framework's `templates/ci/`, the `merge-steward`, `session-verdict`, `archive-after-verdict`
and `stop-failure-recorder` gates. Why it
has this shape: `project-docs/delivery-redesign-2026-10-26.md` in the framework repository.

## 1. The modes (`config/delivery.json`)

| `merge` | `verification` | After PR CI is green the worker… | Who merges | Who verifies after the deploy |
|---|---|---|---|---|
| `steward` | `watcher` | **enqueues, waits until it LANDS, hands off the post-deploy check** | the merge steward | the verdict watcher (deploy pipeline's last job) |
| `steward` | `none` | **enqueues and waits until it lands** (the landing verifies and closes) | the merge steward | nobody: the landing is the final verdict |
| `direct` | `watcher` | merges, records the landing, **hands off the post-deploy check** | the worker | the verdict watcher |
| `direct` | `session` | merges, waits for the trunk pipeline and its post-deploy check, closes | the worker | the worker (the pre-2026-10-26 lifecycle) |

No `config/delivery.json` = `direct` + `session`. Read the file at the PR step; never guess the mode.
"PR" means a GitLab merge request on GitLab, and `#n` its `!iid` (the steward's machine lines keep the literal `PR #<n>` form on both hosts).

## 2. What the worker does before the push (everything the PR must carry)

- The evidence (`evidence/REPORT.md`, the wave captures), the ledger rows (`memory_compile.py ledger add`), the
  docs, the issue checklist ticked for every item that is DONE — all committed BEFORE the single push. Nothing
  is pushed to the trunk after the landing: no evidence PR, no ledger PR (measured: 40 % of one project's PRs
  were such follow-ups, each cancelling a real change's trunk run).
- Checklist items that only a deploy can prove get the literal suffix `(post-deploy)` — e.g.
  `- [ ] the dev smoke check passes (post-deploy)`. The watcher ticks exactly those after a green post-deploy
  check; every other item must be ticked by the worker, or the issue is not closed (§5).
- The PR body names its issue(s) with `Refs #N` (a list: `Refs #12, #13`; a project may name other words in
  `steward.reference_keywords`) — the ONLY form the steward reads as a reference; anything else is a mention,
  and a mentioned issue is never landed, verified or returned. NEVER a closing keyword (`Closes`/`Fixes`/`Resolves`/`Implements #N`, in the PR description or in
  any commit message on the branch) under `watcher` verification: the host would close the issue at landing,
  before the deploy check, and the steward refuses the PR. `Depends-on: #<PR>` lines order dependent PRs.
- An issue delivered by several PRs carries one `merge-steward: queued PR #<n>` line per PR; the watcher
  verifies it only when every one of them has landed.

## 3. Queue, landing, hand-off (`merge: steward`) — the session owns its PR until it LANDS

1. PR CI green on the PR head (a red run is fixed in one pass, `ci-owns-the-test-suite.md`).
2. `python scripts/<wrapper>.py enqueue-pr <n>` — it refuses (exit 4, reason printed) unless the queue would
   accept the PR now; fix the reason, do not work around it.
3. Post the queued note on the issue with these two machine-read lines verbatim, and APPEND `Phase: QUEUED`
   (`Status: IN_PROGRESS` stays) — QUEUED is not a release:
   ```
   merge-steward: queued PR #<n>
   merge-steward: claim-started <the ISO-8601 time the claim was taken>
   ```
4. Wait for the landing: `python scripts/<wrapper>.py wait-landed <n> --timeout-seconds 540` in the
   FOREGROUND (Bash `timeout` 600000), re-issued while it exits 11 (still queued; it prints the queue state).
   It nudges at most one due steward tick per call; the session never dispatches the steward or a deploy.
   - exit 0 `landed <sha>` → step 5.
   - exit 10 — returned, the reason printed (`queue-failed`, `queue-conflict`, dequeued, closed): the steward
     released the claim, so re-claim the issue (`start-issue` / `issue start`), fix every cause in ONE pass (a conflict goes to
     `code-merge-reviewer`), push once, PR CI green, enqueue again, wait again.
   - After 3 returns, or 3 hours of waiting: APPEND `AWAITING_USER: PR #<n> has not landed after 3 h — <queue
     state>` (or the return reason) and end with `SESSION: NEEDS YOU` (§7).
5. Landed. `verification: none`: the landing verified and closed the issue → `Phase: DONE`.
   `verification: watcher`: run `python scripts/<wrapper>.py check-handoff <issue>` — exit 0 only when every
   PR the issue queued has landed and every OPEN checklist item carries `(post-deploy)`; exit 4 prints what is
   still open, and that work is finished now, never handed off. Then post the hand-off note (the landing, the
   evidence path, what the post-deploy check must show) and APPEND `Phase: HANDED_OFF`; append `Phase: DONE` +
   `Status: COMPLETED` to `workflow_state.md`. The tracker claim (in-progress label, assignee) STAYS until the
   watcher verifies the issue. The issue-loop brake releases HANDED_OFF only when `check-handoff` exits 0.
6. Close out at once — a single-issue run runs the close-out checks as its last step, a loop run its HAND_OFF
   clean-up: worktree, local branch, per-worktree venv, local lock and temp residue go; the PR landed, so its
   remote branch goes too (the host's delete-on-merge setting, or `delete-remote-branch`). `CronDelete` the run
   watchdog (a loop: at DONE). Then the SESSION verdict (§7) with the issue as a `landed — deploy check
   pending` row.

`HANDED_OFF` releases a single-issue run (`MODE: SINGLE_ISSUE`) and NOTHING else. A loop (`/issues-work`,
`/auto-work`) does not wait at step 4: it APPENDS `QUEUED_PRS: #<a> #<b>` (the whole list; the last value
wins), cleans up the worktree (the PR branch stays on the remote; a return is fixed in a fresh worktree of
it), records `Phase: LOAD_ISSUES` and works the next issue; before DONE it runs step 4 for every queued PR,
then step 5 for each landed issue — the brake refuses a loop's DONE while `python scripts/<wrapper>.py
check-landed <QUEUED_PRS…>` (exit 0 all landed, 4 not: one line per PR) reports one that has not landed.

`merge: direct` + `verification: watcher`: merge per the recorded merge authority, then
`python scripts/merge_steward.py record-landing <n>` (it posts the landing line and the
`awaiting-verification` label), then steps 5–6.

Never keep a session alive to watch another issue or a deploy (a cron, a loop, a "check back later"): post
`reverify` or a note on the issue and end.

## 4. After the landing (the verdict watcher's, not the session's)

| Event | Who | Effect on the issue |
|---|---|---|
| PR lands (train green) | steward | comment `merge-steward: landed <sha> (PR #n, …)`, label `awaiting-verification` |
| PR's train red, a conflict, PR CI red, a closing keyword, a draft, a dependency closed unlanded | steward | the PR leaves the queue (`queue-failed` / `queue-conflict`, one automatic retry for a first red train); issue `needs-rework`, claim released — the waiting session's `wait-landed` exits 10 |
| PR's train could not run CI to a result (no run, cancelled, timed out) | steward | the green trains ahead land; the PR stays queued for ONE retry, then `queue-failed` |
| PR's head moved, it was dequeued or put on hold while its train ran | steward | not landed (its new commits were never tested); it stays as it is, the trains behind it are rebuilt |
| Green post-deploy check on a commit that CONTAINS the landing | watcher | `(post-deploy)` items ticked, `verified`; checklist complete → closed with time spent and the run; else `needs-closeout`, claim released; the environment's red streak ends |
| Red post-deploy check, the environment green before it | watcher | a red streak starts at that commit; the issues landed since the last green deploy and contained in it: `verification-failed` + `needs-rework`, claim released |
| Red post-deploy check during a red streak, on an issue that landed AFTER the streak began | watcher | stays `awaiting-verification` with ONE comment naming the streak — it landed into an environment that was already red, so it is not a suspect; the first green deploy containing it verifies it |

Verification is by ANCESTRY (`git merge-base --is-ancestor <landing> <deployed>`): a deploy superseded by a
newer one loses no verdict, and no one waits for a deploy of their own commit. The steward keeps ONE open
issue labelled `delivery-status` whose body holds, per environment, the machine lines
`merge-steward: <env> last-green <sha> <ISO>` and `merge-steward: <env> red-since <sha> <ISO>` — the record
the red-streak rule reads. Nothing ever closes without a green deploy that contains the landing.

## 5. Picking work back up

`/issues-work` and `/auto-work` take issues labelled `needs-rework` or `needs-closeout` FIRST (they are open and
unclaimed again). A `needs-rework` issue starts from the comment that returned it: read every failing job, fix
in a fresh worktree off `origin/<trunk>`, push once, PR CI green, enqueue. A `needs-closeout` issue only needs
its open checklist items finished and the issue closed (RESOLVE). If a red deploy is not caused by your change,
say so on the issue with the evidence, append the `reverify` label, and leave the deploy to the steward —
sessions never re-run, cancel or dispatch trunk, steward or deploy runs (one owner for trunk health).
`/close-session` treats an issue whose PR LANDED and whose open items are `(post-deploy)` only as the session's
work done; a queued, unlanded PR is not done.

The queue lives on ONE host, `config/delivery.json` `host`. A second host kept as a read-only archive or
mirror has no queue: its wrapper's delivery verbs refuse (exit 2), and a PR is opened and enqueued on the
primary host only.

## 6. Labels (created once per repository; names configurable under `steward` in `config/delivery.json`)

`queue`, `queue-failed`, `queue-conflict`, `queue-retried`, `do-not-merge`, `awaiting-verification`,
`verified`, `verification-failed`, `needs-rework`, `needs-closeout`, `reverify`, `delivery-status`.

## 7. How a session ends — the SESSION verdict

The last message of every registered work run is the SESSION verdict — the issue-work orchestrator's "The
SESSION verdict" section is the binding form; `/close-session` uses the same head over its nine-row table:

```
SESSION: CAN CLOSE — 1/1 issues delivered · tasks 9/10 (1 post-deploy) · 0 filed

| Issue | Now | Tasks | PR | Next |
|---|---|---|---|---|
| #1445 | landed — deploy check pending | 9/10 | #1532 landed | watcher |
```

`CAN CLOSE` iff every row is `closed`, `landed — deploy check pending` or `filed`, nothing waits for the
operator, and the close-out is done; `NEEDS YOU — <the one decision or action>` iff a substantive
`AWAITING_USER` is recorded; `NOT DONE — <what is left and who has it>` otherwise. Nothing after the table.
The `session-verdict` Stop gate refuses a released run's turn-end without it; in the Claude desktop app the
`wrap_up` recap repeats the SESSION line verbatim and the closing message IS the block.
