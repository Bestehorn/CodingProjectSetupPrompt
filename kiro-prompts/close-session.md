# Close-Session — end-of-session close-out (Kiro)

Kiro counterpart of the Claude Code `/close-session` command
(`claude-commands/close-session.md`). Installed to `.kiro/prompts/close-session.md` and
invoked in Kiro CLI as **`@close-session`** (Kiro's file-based prompts are invoked with
`@name`, not `/name`, and take no arguments).

Run it while the agent that did the work is active — normally `issue-work-orchestrator`, so
it can resolve its own run state. It degrades cleanly in any other session: with no run
state, its scope is the current working tree.

Two differences from the Claude Code twin, both in the ending. Kiro has no session-archive
tool, so the report leaves ending the session to the user (`/quit` in the CLI) instead of
offering to archive itself. And Kiro has no structured question tool, so a blocker that
genuinely needs a decision is asked in TEXT, in one batched block under the table, in the
shape "Output" prescribes — the Claude twin routes the same thing through `AskUserQuestion`.
The verdict table itself is identical on both sides, deliberately.

---

Answer **"can we close this session?"** — by finishing anything unfinished, not by describing
it. Steps 1–3 and the remediation in steps 5–7 and 9 may CHANGE things (that is the point);
everything else is read-only assessment. The line between the two is the project's own:
remediating THIS run's own, reversible artifacts is MANDATORY, not a request (the
`keep-git-clean` steering rule makes the clean end-state per run; `continuous-work`
Exception 1 says take a reversible path rather than ask for one) — ANYTHING ELSE is
recommend-and-wait: never another run's artifacts, never the shared local `main`, never an
untracked file whose fate is the user's call.

**Running this prompt is not permission to stop.** If any work remains unfinished, close-out
is not what comes next — the work is. Per the `continuous-work` steering rule, an accurate
close-out report over unfinished work is a disguised check-in, and the `issue-loop-gate` gate will
refuse the turn-end anyway.

**Scope: THIS session only.** Consider only your own worktree, branch, lock, claim markers,
files and temp residue. Do not inspect, enumerate, or mention other sessions' worktrees,
branches, locks or issues — they are not your business and reporting them is noise. Resolve
your own scope from `.kiro/agent-state/issue-work-orchestrator/registry.json` → your entry's
`state_dir` → `resume_state.md` and its `CURRENT_ISSUE` / `CURRENT_WORKTREE` /
`CURRENT_BRANCH` / `CURRENT_PR` fields. The `session-register` gate (run by `kiro_hooks.py`
at agentSpawn) seeds `resume_state.md` and `workflow_state.md` at the path the registry names;
if that file is nevertheless missing, create it at exactly that path, never under a readable
label of your own devising (a state file under an invented name is found only through its
`SESSION_ID:` line, and a run the registry declares but cannot read is refused by the stop
gates until it is repaired). With no registry entry at all, your scope is the current working
tree.

**The reply is a FIXED FORM, not a write-up.** Everything you find lands in one cell of the
nine-row table in "Output" — one row per step below, in that order, with a ✅/❌ and at most
60 characters of detail. There is no preamble, no narration of what you are about to check,
no paragraph under the table, and no prose restatement of a failure. `no-guessing` still
binds and `no-output-shortening` still governs what you READ (read complete output; report
the deciding number).

**Step 1 — Is the work actually DONE? (gate: nothing else runs until this passes)**
   For every issue this session was working, check against the project's standards, not your
   memory: implemented, tested (a test that reproduces the original symptom now passes, and
   the full suite is green for the merged SHA — cited from the CI run, not a local full-suite
   run: `ci-owns-the-test-suite` — with no skip/xfail dodges), and documented (issue updated,
   spec artifacts committed, docs touched where the change requires it — the issue's own task
   items are Step 2's subject and are checked there, mechanically). Read the issue and this
   run's `resume_state.md` rather than trusting recall.
   - **If anything is missing, FINISH IT NOW** — `@continue-work` semantics: resume the
     recorded phase and drive it to a terminal state. Do not report a gap and stop; do not
     ask whether to finish it. The answer is always yes, and `continuous-work` governs.
     Then re-enter Step 1.
   - Only when it genuinely passes, continue. If it CANNOT pass (a Proven Exception from
     `continuous-work` — irreversible action, sensitive information, a real design fork, a
     hard blocker), the row is ❌ naming that exception, it becomes one question in the single
     batched Questions block (see "Asking"), and it is recorded as an `AWAITING_USER` line
     naming the ACTUAL reason.

**Step 2 — Is EVERY task item on the issue done? (gate: the other half of Step 1)**
   It precedes the CI check deliberately: finishing a missed item produces commits that CI
   must then see, so checking CI first would only mean checking it twice.
   An issue is not finished because its code merged; it is finished when every item on its
   checklist is genuinely done. **Reporting an issue as closed while task items remain
   unfinished is a MEASURED habit and the reason this step exists** — so it is checked
   MECHANICALLY, per issue, never from recall.
   - Re-read each issue this session worked through the wrapper (`issue show <iid>` /
     `get-issue <N>`; plus the notes/comments for items added after filing) and COUNT the
     task-list lines in the description: `- [ ]` vs `- [x]`. The arithmetic
     (`#<N>: 7/9 ticked`) is what row 2 of the report carries, and any unticked item is named
     to YOURSELF here as the worklist — it reaches the reply only if it legitimately survives,
     on that issue's Issues-block line. A tick you believe you wrote but cannot see in the
     description is NOT ticked.
   - If the issue tracks its work as CHILD issues rather than checkboxes (an epic, or linked
     child issues), the same rule applies to them: every child closed, or the parent is not
     closeable. Count and name them the same way.
   - An unticked item is UNFINISHED WORK unless one of two things is evidenced FROM THE ISSUE
     ITSELF: (a) a deferral recorded on the issue BEFORE this close-out, naming its reason
     and its routing per `issue-filing-discipline` (fixed here / a findings-ledger row / ONE
     gated issue); or (b) a Proven Exception from `continuous-work`, stated with its proof.
     **A deferral written DURING close-out to make this gate pass is not a deferral — it is
     unfinished work renaming itself. Finish the item instead.**
   - One carve-out: an issue this session closed ADMINISTRATIVELY (duplicate, obsolete,
     already resolved elsewhere, won't-do) is outside this gate — its unticked items were
     never going to be done. The closing comment must NAME that reason; with no such reason
     on the issue it was a DONE close and the gate applies.
   - **Issue still OPEN with unfinished items → exactly Step 1's remedy: FINISH IT NOW**,
     ticking each item through the wrapper's checklist toggle as it genuinely completes, then
     re-enter Step 1. Do not ask; do not report the gap and stop.
   - **Issue already CLOSED with unfinished items → REOPEN it, before anything else in this
     close-out.** It is stated, not glossed: the issue was closed while `<n>` task item(s)
     were unfinished, and that closure was WRONG. That sentence goes on the ISSUE (sub-step 3)
     and, compressed, on the issue's line in the report's Issues block — not into a paragraph
     of the reply. Then, in order:
     1. Reopen it via the wrapper (`issue reopen <iid>` / `reopen-issue <N>`) and re-claim it
        (`issue start <iid>` / `start-issue <N>`) — an issue you are working is an issue you
        hold. Re-acquire its local lock if you released one.
     2. **Re-arm the brake in the same breath:** APPEND to this run's `resume_state.md`
        `Status: IN_PROGRESS`, `WORKABLE_ISSUES_REMAIN: yes`, `AWAITING_USER: none`, plus
        `CURRENT_ISSUE: <N>` and the `Phase` you are resuming. The `issue-loop-gate` (the
        `stop` hook `kiro_hooks.py` runs) holds the turn while the run has CLAIMED tracked
        work — a non-placeholder `CURRENT_ISSUE` is the claim — and records no release: an
        idle `Status`, a terminal `Phase`, or a SUBSTANTIVE `AWAITING_USER`. Every field read
        takes the LAST occurrence — so a `Status: COMPLETED` or `Phase: DONE` recorded earlier
        in this session is exactly what would let the turn end over the work you just
        reopened. This is what makes finishing mandatory rather than merely intended.
     3. Post a comment naming every item that was outstanding at the moment of closure and
        stating that they are now being finished. That comment is the durable record; chat is
        not (`issue-tracking`).
     4. Finish every one of them, ticking as you go, with the same evidence standard as
        Step 1 (a test that fails for the right reason first, green suite from CI).
     5. Only THEN close it again, through Step 7, with the checklist visibly complete.
     Reopening is reversible, so `continuous-work` Exception 1 makes it the REQUIRED path,
     not something to ask for: do not request permission, and do not report the premature
     closure as a finding and stop.
   - If the wrapper has no reopen subcommand, implement it from the spec in the wrapper's own
     docstring (one call: GitLab `PUT /issues/{iid}` `{"state_event":"reopen"}`, GitHub
     `PATCH /issues/{n}` `{"state":"open"}`) rather than leaving the tracker's record wrong.
     Only a tracker that REFUSES the reopen is a hard blocker (Exception 4), and then the
     evidence is the failing call with its complete output.

**Step 3 — Is CI still running? (wait for it; it is part of the work)**
   Pending CI means the work is not finished, so this precedes every cleanliness check.
   - Determine your own run: the MR/PR and branch from your run state, via the wrapper script
     (`use-git-wrapper-scripts`) — never `glab`/`gh`/`curl`.
   - If a pipeline is non-terminal, WAIT and monitor to a terminal state: repeated
     `pipeline status` / `get-run <id>` captures on a stated interval, reporting only the
     latest status plus elapsed. Never a blocking watch command with no clock and no timeout.
   - Red CI is the debugging loop, not a close-out: enumerate EVERY failing job and every
     failure inside it, group by root cause, fix them ALL, and push once
     (`remote-ci-must-pass`, `ci-owns-the-test-suite`). If CI cannot run at all, that rule's
     capacity ladder applies — relocate if the fallback exists, else file/comment then
     declare CI-OUTAGE MODE (`python scripts/ci_outage_mode.py declare`) and run the pipeline
     locally via `python scripts/run_checks.py`.
   - If CI-OUTAGE MODE is still declared (`python scripts/ci_outage_mode.py status`) but a
     real pipeline has since gone green, CLEAR it — until it is cleared, every push in every
     worktree of this clone pays for a full local suite.
   - Carry forward one obligation only: if this session merged with the pipeline unrun or with
     any job that did not execute, row 3 is ✅ with its Detail saying so (`merged
     pipeline-unrun — later run must confirm`). It lives on the repo, not the tree, does not
     block closing, and gets no extra line in the reply.

**Step 4 — Your working tree is clean**
   `git status --porcelain` in your own tree (`git -C <your worktree>` if you have one), then
   `--untracked-files=all` to surface what the short form hides. Classify each untracked file
   per `keep-git-clean`: anything that BELONGS gets committed (or `.gitignore`d) before you
   can close; anything generated or temporary is deleted in Step 5. Never `git add -A`
   blindly.

**Step 5 — Delete your own leftovers**
   Delete what THIS session created. Never delete a file you did not create, and never touch
   another session's scratch — if ownership is unclear, leave it and say so in row 5's Detail.
   1. `tmp/` (per `file-organization`, empty at end of task) and any scratch files this
      session wrote elsewhere in the tree. Untracked + self-created + generated = delete, no
      confirmation needed. Tracked, or possibly someone else's = leave.
   2. **OS temp residue — this is the big one.** Agent tooling leaks unbounded scratch OUTSIDE
      the project: every `cdk` invocation orphans a `jsii-kernel-*` directory that is never
      removed, and randomized `cdk.out<hash>` assemblies accumulate in the OS temp dir (one
      report reached 170 GB in two days). An aborted bundling also leaves `bundling-temp-*` /
      empty `asset.<hash>` that makes the NEXT deploy fail, so this is correctness, not just
      disk. Run the reaper — its default 28-minute budget fits a 30-minute tool cap; pass a
      lower `--budget-minutes` to fit a shorter one:
      ```bash
      python scripts/reap_agent_temp.py --scoped-temp tmp/os-temp --apply
      ```
      It removes your session-scoped temp contents wholesale (provably yours) and, in the
      shared OS temp dir, only known residue patterns untouched for 30+ minutes whose rename
      succeeds — a sibling's in-flight `cdk synth` holds files open and refuses the rename,
      so it is never harmed. Each candidate is moved into `.reap-quarantine/` before
      deletion, so even a killed run has removed the poison directories from where tooling
      looks. Exit 0 is done; exit 1 names an entry that would not delete; exit 3 means the
      budget ran out with the rest quarantined — run the same command again until it exits
      0 or 1 (each run is bounded and visibly further along; a quarantine is deleted first
      by the next run, whichever session's). Its reclaimed total, summed over the runs, is
      row 5's Detail; anything it reports as in use, skipped or failed is named in that same
      cell, never expanded.
   3. If `tmp/os-temp` is not this tree's `TMPDIR`/`TEMP`/`TMP`, row 5's Detail says
      `unscoped temp` — the reaper then falls back to pattern matching in the shared temp dir,
      which is best-effort. The scoped form (a settings-file `env` block or a per-command
      prefix) is the one temp variable `no-environment-vars` permits; the global form stays
      forbidden.

**Step 6 — Your worktree, branch, lock AND claim markers are gone**
   Confirm the worktree and branch this session created were removed after merge. Tear down a
   per-worktree venv FIRST if one exists (locked DLLs otherwise block removal on Windows);
   `git worktree remove` plain, `--force` only after confirming no uncommitted work would be
   lost; then delete the branch and verify with `git worktree list` and that
   `.kiro/worktrees/issue-<N>/` is gone.
   Derive your claim set mechanically from evidence this run wrote — its
   `.locks/issue-<N>.lock` owner records, its registry entry, its `issue_queue.md` — **never
   from topical adjacency** (an issue split out of yours, or one whose title resembles yours,
   is not yours to unclaim). For each issue in that set, remove the claim per the convention
   in this run's `environment.md`, through the ADDITIVE primitives only — `issue label-remove`
   and `issue assign --unassign`, never a whole-set `labels` write — and remove the marker
   BEFORE removing that issue's local lock — the lock is the ownership evidence the removal
   guard reads. Then release your lock under
   `.kiro/agent-state/issue-work-orchestrator/.locks/` and update the registry entry.
   Report only your own; say nothing about anyone else's.

**Step 7 — Issues updated and closed with evidence**
   For each issue this run finished: a final comment linking the merged MR/PR and the
   evidence, the checklist fully ticked — the count re-read after whatever Step 2 made you
   finish, not the count you started with — time spent recorded, and the issue closed via the
   wrapper. **An issue may not be closed while any task item is unticked** unless that item
   carries the pre-existing, evidenced deferral Step 2 defines; closing over unfinished items
   is exactly the closure this prompt reopens, so do not manufacture one here. An issue
   reopened in Step 2 is re-closed HERE, and its final comment says it was reopened, which
   items were outstanding, and that every one of them is now done. For an issue this run did
   NOT finish (Proven Exception only, per Step 1 or Step 2): leave it OPEN with a status
   comment carrying the branch, worktree, MR/PR and evidence location, so any agent can
   resume from the issue alone — and do not remove its claim if the work is still in flight
   elsewhere.

**Step 8 — The shared local `main` was not moved**
   `git rev-parse main` vs `origin/main`. Local `main` being behind is the DESIGNED state on a
   shared clone (`keep-git-clean`) — row 8 is ✅ reading `<n> behind origin (designed)`, never
   "drift" and never a ❌. Do not move it.

**Step 9 — A terminal state recorded**
   APPEND a block at the END of this run's `resume_state.md` carrying `Status: COMPLETED`,
   a terminal `Phase: DONE`, and `WORKABLE_ISSUES_REMAIN: no`. On this host the stop gate
   blocks while `Status` matches `IN_PROGRESS` AND `WORKABLE_ISSUES_REMAIN` is `yes` AND no
   `AWAITING_USER` reason is recorded — it does not read `Phase` at all — so what actually
   releases it is a `Status` that is no longer `IN_PROGRESS`, and `WORKABLE_ISSUES_REMAIN: no`
   may be written HERE and at the orchestrator's DONE only — the orchestrator's "only at DONE"
   rule means only at a TERMINAL point, and a close-out whose Steps 1–2 genuinely passed is
   one. Append; never edit an earlier block (every field read
   takes the LAST occurrence). Do NOT record a terminal state to end a turn on work that is
   not finished: that is the failure the gate exists to catch, and the state file is the
   record someone will trust later. Set your registry entry's `status` to done.

## Output — this form, every time, and nothing else

Reply with exactly three things in this order: the verdict line, the nine-row table, the
Issues block. A clean single-issue session is 16 lines; the ONLY things that may grow the
reply are one more line per additional issue and — when something is genuinely blocked — the
Questions block below. If it is not in this template, it does not go in the reply.

```
CLOSE: YES

| # | Check | ✓ | Detail |
|---|---|---|---|
| 1 | Work complete | ✅ | impl+tests+docs, MR !77 merged |
| 2 | Task items | ✅ | #412: 9/9 ticked |
| 3 | CI | ✅ | pipeline 8821 green on 4f2a1c9 |
| 4 | Tree clean | ✅ | nothing untracked |
| 5 | Leftovers | ✅ | 1.4 GB reclaimed; tmp/ empty |
| 6 | Worktree/branch/lock/claims | ✅ | all four released |
| 7 | Issues closed | ✅ | #412 closed with evidence |
| 8 | Local main | ✅ | 3 behind origin (designed) |
| 9 | Terminal state | ✅ | Status COMPLETED / Phase DONE |

Issues
- #412 worked → closed — MR !77; evidence in specs/fix-timeout/evidence/
- #418 filed — flaky teardown in pipeline 8814; needs design, gated
```

That block is a SPECIMEN with real-shaped values, not a description of one. Copy its skeleton
verbatim and swap the values. It is identical to the Claude Code twin's, deliberately: the
same nine rows mean a close-out reads the same whichever assistant produced it.

**The nine rows are fixed.** Those labels, that order, all nine present every time — one per
step above. Never add a row, drop a row, reorder, rename, merge two, or append a "notes" row.
A step with nothing to report still gets its row.

**The `✓` column is exactly one character, one of three:**

| Mark | Means | Use it when |
|---|---|---|
| ✅ | checked, and it passes | you looked and it is good |
| ❌ | checked and FAILING, **or not checked at all** | anything else — an unperformed check is a ❌, never a ➖ |
| ➖ | the step has no subject in this session | no pipeline exists on this host; no worktree was created; no issue was worked. NOT "I skipped it", NOT "unclear" |

There is no fourth symbol. A caveat is not a ⚠️: it is either a ✅ whose Detail names the
caveat, or a ❌. Guessing between them is what the three definitions above remove.

**The Detail cell is ≤60 characters, telegraphic, and carries the deciding number** — a
pipeline id, a SHA prefix, `m/n`, a byte total, a count. No sentences, no trailing period, no
hedging ("appears to", "should be", "looks clean"), no quoted command output, no path longer
than its basename. If the finding will not fit in 60 characters, you have not finished
deciding what it is.

**The verdict line is arithmetic, not judgement:** `CLOSE: YES` if and only if zero rows are
❌; otherwise `CLOSE: NO — <n> blocker(s)` where `<n>` is the exact count of ❌ rows. Nothing
else ever appears on that line.

**The Issues block** is the literal header `Issues`, then one line per issue this session
worked or filed, ascending by number, `- none` if there were none:

```
- #<n> <worked → closed | worked → left open | filed> — <≤70 chars: MR, evidence, or why>
```

One line each, no sub-bullets, no grouping headers. An unticked task item that legitimately
survives (a pre-existing deferral or a Proven Exception, per Step 2) is named HERE, on its
issue's line — never in the table. If Step 2 reopened an issue, its line says so:
`#412 worked → closed — REOPENED: 2 items unfinished at first close, now done`.

**Asking — for a decision, not for permission**

A ❌ that genuinely needs the USER is not explained in prose. Kiro has no structured question
tool, so it goes in ONE batched block after the Issues block, and that block is the whole of
what you add:

```
Questions
1. <question> — <≤2 sentences of context>. Recommend: <option> because <one reason>.
2. <question> — …
```

At most four, one to two lines each, every one carrying a recommendation — never a bare
yes/no, never drip-fed across turns. Record the same question on the issue and as an
`AWAITING_USER` line naming the actual reason (`continuous-work`): a question asked only in
chat does not survive compaction and releases no stop gate.

What it is NOT for: permission to do the mandatory remediation. Finishing the work, reopening
an issue closed over unfinished items, deleting your own leftovers, tearing down your own
worktree — those are obligations, not questions, and Steps 1–2 have already settled them.
"Shall I continue?" stays forbidden. If nothing is blocked, there is no Questions block.

**When `CLOSE: YES`** there is nothing further to say and nothing to invoke: Kiro has no
session-archive tool, so the table IS the go-ahead and `/quit` is the user's to type. Do not
add a sentence telling them so.

No AI attribution in any comment, commit or issue text (`no-ai-attribution`). Never modify
anything under `.claude/`.
