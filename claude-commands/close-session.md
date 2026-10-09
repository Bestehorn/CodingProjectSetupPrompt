---
description: End-of-session close-out — confirm the assigned work is actually complete INCLUDING every task item on its issue (reopening an issue closed over unfinished items), wait out any running CI, clean up this session's own files, temp residue, worktree/branch/lock and claim markers, record a terminal Phase, then report one fixed nine-row verdict table.
argument-hint: "[nothing]"
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch, AskUserQuestion, mcp__ccd_session_mgmt__archive_session, Agent(spec-author, spec-researcher, spec-review-agent, test-architect, standards-reviewer, best-practice-reviewer, security-reviewer, devops-iac-reviewer, adversarial-verifier, spec-implementer, code-merge-reviewer)
---

<!-- archive_session is allowlisted because the final step invokes it after an explicit go-ahead.
     It is an MCP tool and may be absent (plain CLI): then RECOMMEND archiving rather than reporting a failure.
     AskUserQuestion is allowlisted for ONE purpose — a blocker that genuinely needs a user decision, and
     the archive offer — never to ask permission to do the mandatory remediation. See "Asking" below. -->

Answer **"can we close this session?"** — by finishing anything unfinished, not by describing
it. Steps 1–3 and the remediation in steps 5–7 and 9 may CHANGE things (that is the point);
everything else is read-only assessment. The line between the two is the project's own:
remediating THIS run's own, reversible artifacts is MANDATORY, not a request
(`keep-git-clean.md` makes the clean end-state per run; `continuous-work.md` Exception 1 says
take a reversible path rather than ask for one) — ANYTHING ELSE is recommend-and-wait: never
another run's artifacts, never the shared local `main`, never an untracked file whose fate is
the user's call.

**Running this command is not permission to stop.** If any work remains unfinished, close-out
is not what comes next — the work is. Per `.claude/rules/continuous-work.md`, an accurate
close-out report over unfinished work is a disguised check-in, and the `issue-loop-gate` gate will
refuse the turn-end anyway.

**Scope: THIS session only.** Consider only your own worktree, branch, lock, claim markers,
files and temp residue. Do not inspect, enumerate, or mention other sessions' worktrees,
branches, locks or issues — they are not your business and reporting them is noise. Resolve
your own scope from `.claude/agent-state/issue-work-orchestrator/registry.json` → your
`runs/<run-id>/` → the seeded `CURRENT_ISSUE` / `WORKTREE` / `BRANCH` / `PR` fields. With no
run state, your scope is the current working tree.

**Read `.claude/docs/run-identity.md` BEFORE this run's first state write.** It is the
binding contract for run identity, the seeded fields, the release vocabulary, and the gate
verdicts — state written to a path or spelling of your own devising is read by NOTHING
(MEASURED: Incident `invented-run-label`, `.claude/hooks/MIGRATION.md`). The seeded field
NAMES are `BRANCH`/`WORKTREE`/`PR` — never `CURRENT_BRANCH`-style.

**The reply is a FIXED FORM, not a write-up.** Everything you find lands in one cell of the
nine-row table in "Output" — one row per step below, in that order, with a ✅/❌ and at most
60 characters of detail. There is no preamble, no narration of what you are about to check,
no paragraph under the table, and no prose restatement of a failure. A question for the user
goes through `AskUserQuestion`, not through sentences. `no-guessing.md` still binds and
`no-output-shortening.md` still governs what you READ (read complete output; report the
deciding number).

**Step 1 — Is the work actually DONE? (gate: nothing else runs until this passes)**
   For every issue this session was working, check against the project's standards, not your
   memory: implemented, tested (a test that reproduces the original symptom now passes, and
   the full suite is green for the merged SHA — cited from the CI run, not a local
   full-suite run: `ci-owns-the-test-suite.md` — with no skip/xfail dodges), and documented
   (issue updated, spec artifacts committed, docs touched where the change requires it —
   the issue's own task items are Step 2's subject and are checked there, mechanically).
   Read the issue and `runs/<run-id>/resume_state.md` rather than trusting recall.
   - **If anything is missing, FINISH IT NOW** — `continue-work` semantics: resume the
     recorded phase and drive it to a terminal state. Do not report a gap and stop; do not
     ask whether to finish it. The answer is always yes, and `continuous-work.md` governs.
     Then re-enter Step 1.
   - Only when it genuinely passes, continue. If it CANNOT pass (a Proven Exception from
     `continuous-work.md` — irreversible action, sensitive information, a real design fork,
     a hard blocker), the row is ❌ naming that exception, it becomes one question in the
     single `AskUserQuestion` call (see "Asking"), and it is recorded as an `AWAITING_USER`
     line naming the ACTUAL reason (checked for SUBSTANCE — `run-identity.md` §5).

**Step 2 — Is EVERY task item on the issue done? (gate: the other half of Step 1)**
   It precedes the CI check deliberately: finishing a missed item produces commits that CI
   must then see, so checking CI first would only mean checking it twice.
   An issue is not finished because its code merged; it is finished when every item on its
   checklist is genuinely done. **Reporting an issue as closed while task items remain
   unfinished is a MEASURED habit and the reason this step exists** — so it is checked
   MECHANICALLY, per issue, never from recall.
   - Re-read each issue this session worked through the wrapper (`get-issue <N>`; plus
     `get-issue-comments` for items added after filing) and COUNT the task-list lines in
     the body: `- [ ]` vs `- [x]`. The arithmetic (`#<N>: 7/9 ticked`) is what row 2 of the
     report carries, and any unticked item is named to YOURSELF here as the worklist — it
     reaches the reply only if it legitimately survives, on that issue's Issues-block line.
     A tick you believe you wrote but cannot see in the body is NOT ticked.
   - If the issue tracks its work as CHILD issues rather than checkboxes (a parent/epic
     with sub-issues), the same rule applies to them: every child closed, or the parent is
     not closeable. Count and name them the same way.
   - An unticked item is UNFINISHED WORK unless one of two things is evidenced FROM THE
     ISSUE ITSELF: (a) a deferral recorded on the issue BEFORE this close-out, naming its
     reason and its routing per `issue-filing-discipline.md` (fixed here / a findings-ledger
     row / ONE gated issue); or (b) a Proven Exception from `continuous-work.md`, stated
     with its proof. **A deferral written DURING close-out to make this gate pass is not a
     deferral — it is unfinished work renaming itself. Finish the item instead.**
   - One carve-out: an issue this session closed ADMINISTRATIVELY (duplicate, obsolete,
     already resolved elsewhere, won't-do) is outside this gate — its unticked items were
     never going to be done. The closing comment must NAME that reason; with no such reason
     on the issue it was a DONE close and the gate applies.
   - **Issue still OPEN with unfinished items → exactly Step 1's remedy: FINISH IT NOW**,
     ticking each item through the wrapper's checklist toggle as it genuinely completes,
     then re-enter Step 1. Do not ask; do not report the gap and stop.
   - **Issue already CLOSED with unfinished items → REOPEN it, before anything else in this
     close-out.** It is stated, not glossed: the issue was closed while `<n>` task item(s)
     were unfinished, and that closure was WRONG. That sentence goes on the ISSUE (sub-step
     3) and, compressed, on the issue's line in the report's Issues block — not into a
     paragraph of the reply. Then, in order:
     1. Reopen it via the wrapper (`reopen-issue <N>` / `issue reopen <iid>`) and re-claim
        it (`start-issue` / `issue start`) — an issue you are working is an issue you hold.
        Re-acquire its local lock if you released one.
     2. **Re-arm the brake in the same breath:** APPEND to this run's `resume_state.md`
        `Status: IN_PROGRESS`, the `Phase` you are resuming, and `CURRENT_ISSUE: <N>`.
        Every gate reads the LAST occurrence of a field, so a terminal `Phase` recorded
        earlier in this session is exactly what would let the turn end over the work you
        just reopened (`run-identity.md` §4, §5). This is what makes finishing mandatory
        rather than merely intended.
     3. Post a comment naming every item that was outstanding at the moment of closure and
        stating that they are now being finished. That comment is the durable record; chat
        is not (`issue-tracking.md`).
     4. Finish every one of them, ticking as you go, with the same evidence standard as
        Step 1 (test that fails for the right reason first, green suite from CI).
     5. Only THEN close it again, through Step 7, with the checklist visibly complete.
     Reopening is reversible, so `continuous-work.md` Exception 1 makes it the REQUIRED
     path, not something to ask for: do not request permission, and do not report the
     premature closure as a finding and stop.
   - If the wrapper has no reopen subcommand, implement it from the spec in the wrapper's
     own docstring (one call: GitHub `PATCH /issues/{n}` `{"state":"open"}`, GitLab
     `PUT /issues/{iid}` `{"state_event":"reopen"}`) rather than leaving the tracker's
     record wrong. Only a tracker that REFUSES the reopen is a hard blocker (Exception 4),
     and then the evidence is the failing call with its complete output.

**Step 3 — Is CI still running? (wait for it; it is part of the work)**
   Pending CI means the work is not finished, so this precedes every cleanliness check.
   - Determine your own run: the PR/branch from your run state, via the wrapper script
     (`use-git-wrapper-scripts.md`) — never `gh`/`glab`/`curl`.
   - If a run is non-terminal, WAIT and monitor to a terminal state. Do NOT use `watch-run`
     (no clock, no timeout — it cannot evidence elapsed time and will hold the terminal).
     Take repeated `get-run <id>` captures on a stated interval, and report only the latest
     status plus elapsed.
   - Red CI is the debugging loop, not a close-out: enumerate EVERY failing job and every
     failure inside it, group by root cause, fix them ALL, and push once
     (`remote-ci-must-pass.md`, `ci-owns-the-test-suite.md`). If CI cannot run at all, that
     rule's capacity ladder applies — relocate if the fallback exists, else file/comment then
     declare CI-OUTAGE MODE (`scripts/ci_outage_mode.py declare`) and run the pipeline
     locally via `scripts/run_checks.py`.
   - If CI-OUTAGE MODE is still declared (`python scripts/ci_outage_mode.py status`) but a
     real CI run has since gone green, CLEAR it — until it is cleared, every push in every
     worktree of this clone pays for a full local suite.
   - Carry forward one obligation only: if this session merged with the pipeline unrun
     (Rung 3) or with any job that did not execute, row 3 is ✅ with its Detail saying so
     (`merged pipeline-unrun — later run must confirm`). It lives on the repo, not the tree,
     does not block closing, and gets no extra line in the reply.

**Step 4 — Your working tree is clean**
   `git status --porcelain` in your own tree (`git -C <your worktree>` if you have one), then
   `--untracked-files=all` to surface what the short form hides. Classify each untracked file
   per `keep-git-clean.md`: anything that BELONGS gets committed (or `.gitignore`d) before you
   can close; anything generated or temporary is deleted in Step 5. Never `git add -A`
   blindly.

**Step 5 — Delete your own leftovers**
   Delete what THIS session created. Never delete a file you did not create, and never touch
   another session's scratch — if ownership is unclear, leave it and say so in row 5's Detail.
   1. `tmp/` (per `file-organization.md`, empty at end of task) and any scratch files this
      session wrote elsewhere in the tree. Untracked + self-created + generated = delete, no
      confirmation needed. Tracked, or possibly someone else's = leave.
   2. **OS temp residue — this is the big one.** Agent tooling leaks unbounded scratch OUTSIDE
      the project: every `cdk` invocation orphans a `jsii-kernel-*` directory that is never
      removed, and randomized `cdk.out<hash>` assemblies accumulate in the OS temp dir (one
      report reached 170 GB in two days). An aborted bundling also leaves `bundling-temp-*` /
      empty `asset.<hash>` that makes the NEXT deploy fail, so this is correctness, not just
      disk. Run the reaper with `run_in_background: true` — its default 28-minute budget
      fits the background form's 30-minute cap; a foreground call must pass
      `--budget-minutes 9` and the maximum timeout:
      ```bash
      python scripts/reap_agent_temp.py --scoped-temp tmp/os-temp --apply
      ```
      It removes your session-scoped temp contents wholesale (provably yours) and, in the
      shared OS temp dir, only known residue patterns untouched for 30+ minutes whose rename
      succeeds — a sibling's in-flight `cdk synth` holds files open and refuses the rename,
      so it is never harmed. The residue that poisons the next deploy goes first; each
      candidate is moved into `.reap-quarantine/` just before its deletion; and the budget
      is checked before every file, so the run returns on time even on a host whose
      security agent scans each delete. Exit 0 is done; exit 1 names an entry that would
      not delete; exit 3 means the budget ran out with the rest quarantined or not yet
      reached — run the same command again until it exits 0 or 1 (each run is bounded and
      visibly further along; a quarantine is deleted first by the next run, whichever
      session's). Its reclaimed total, summed over the runs, is row 5's Detail; anything it
      reports as in use, skipped or failed is named in that same cell, never expanded, and
      a `SLOW HOST` line is quoted there as the reason the backlog outlives the session.
   3. If `tmp/os-temp` is not configured as this tree's `TMPDIR`/`TEMP`/`TMP`, row 5's Detail
      says `unscoped temp` — the reaper then falls back to pattern matching in the shared temp
      dir, which is best-effort. The `scoped-temp-init` gate self-writes the env block at session
      start (effective the NEXT session), so persistent absence means the hook is not wired or
      the settings file does not parse — name which in that same cell.

**Step 6 — Your worktree, branch, lock AND claim markers are gone**
   Confirm the worktree and branch this session created were removed after merge. Tear down a
   per-worktree venv FIRST if one exists (locked DLLs otherwise block removal on Windows);
   `git worktree remove` plain, `--force` only after confirming no uncommitted work would be
   lost; then delete the branch and verify with `git worktree list`.
   Derive your claim set mechanically from evidence this run wrote — its
   `.locks/issue-<N>.lock` owner records, its registry entry, its `issue_queue.md` — **never
   from topical adjacency** (an issue split out of yours, or one whose title resembles yours,
   is not yours to unclaim). For each issue in that set, remove the claim per the convention
   in `environment.md` (unassign and/or remove the in-progress label through the ADDITIVE
   `remove-label` primitive with this run's `--run-id`, never a whole-set `labels` write),
   and remove the marker BEFORE removing that issue's local lock — the lock is the ownership
   evidence the removal guard reads. Then release your lock under
   `.claude/agent-state/issue-work-orchestrator/.locks/` and update the registry entry.
   Report only your own; say nothing about anyone else's.

**Step 7 — Issues updated and closed with evidence**
   For each issue this run finished: a final comment linking the merged PR and the evidence,
   the checklist fully ticked — the count re-read after whatever Step 2 made you finish, not
   the count you started with — time spent recorded, and the issue closed via the wrapper.
   **An issue may not be closed while any task item is unticked** unless that item carries
   the pre-existing, evidenced deferral Step 2 defines; closing over unfinished items is
   exactly the closure this command reopens, so do not manufacture one here. An issue
   reopened in Step 2 is re-closed HERE, and its final comment says it was reopened, which
   items were outstanding, and that every one of them is now done. For an issue this run did
   NOT finish (Proven Exception only, per Step 1 or Step 2): leave it OPEN with a status
   comment carrying the branch, worktree, PR and evidence location, so any agent can resume
   from the issue alone — and do not remove its claim if the work is still in flight
   elsewhere.

**Step 8 — The shared local `main` was not moved**
   `git rev-parse main` vs `origin/main`. Local `main` being behind is the DESIGNED state on a
   shared clone (`keep-git-clean.md`) — row 8 is ✅ reading `<n> behind origin (designed)`,
   never "drift" and never a ❌. Do not move it.

**Step 9 — A terminal `Phase` recorded**
   APPEND a block at the END of this run's `resume_state.md` carrying `Status: COMPLETED` and
   a terminal `Phase` (`DONE`/`COMPLETED`/`ABANDONED`/`ESCALATED`) — **that terminal value is
   what releases the `issue-loop-gate` gate**, and it must be the WHOLE value of the field
   (`Phase: DONE`, never `Phase: DONE (was IMPLEMENT)`; vocabulary: `run-identity.md` §5). Do
   NOT record a terminal `Phase` to end a turn on work that is not finished: that is the
   failure the gate exists to catch, and the state file is the record someone will trust
   later.

## Output — this form, every time, and nothing else

Reply with exactly three things in this order: the verdict line, the nine-row table, the
Issues block. A clean single-issue session is 16 lines; the ONLY thing that may grow the
reply is one more line per additional issue. If it is not in this template, it does not go
in the reply.

```
CLOSE: YES

| # | Check | ✓ | Detail |
|---|---|---|---|
| 1 | Work complete | ✅ | impl+tests+docs, PR #77 merged |
| 2 | Task items | ✅ | #412: 9/9 ticked |
| 3 | CI | ✅ | run 8821 green on 4f2a1c9 |
| 4 | Tree clean | ✅ | nothing untracked |
| 5 | Leftovers | ✅ | 1.4 GB reclaimed; tmp/ empty |
| 6 | Worktree/branch/lock/claims | ✅ | all four released |
| 7 | Issues closed | ✅ | #412 closed with evidence |
| 8 | Local main | ✅ | 3 behind origin (designed) |
| 9 | Terminal state | ✅ | Status COMPLETED / Phase DONE |

Issues
- #412 worked → closed — PR #77; evidence in specs/fix-timeout/evidence/
- #418 filed — flaky teardown in run 8814; needs design, gated
```

That block is a SPECIMEN with real-shaped values, not a description of one. Copy its
skeleton verbatim and swap the values.

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

**The Detail cell is ≤60 characters, telegraphic, and carries the deciding number** — a run
id, a SHA prefix, `m/n`, a byte total, a count. No sentences, no trailing period, no hedging
("appears to", "should be", "looks clean"), no quoted command output, no path longer than its
basename. If the finding will not fit in 60 characters, you have not finished deciding what
it is.

**The verdict line is arithmetic, not judgement:** `CLOSE: YES` if and only if zero rows are
❌; otherwise `CLOSE: NO — <n> blocker(s)` where `<n>` is the exact count of ❌ rows. Nothing
else ever appears on that line.

**The Issues block** is the literal header `Issues`, then one line per issue this session
worked or filed, ascending by number, `- none` if there were none:

```
- #<n> <worked → closed | worked → left open | filed> — <≤70 chars: PR, evidence, or why>
```

One line each, no sub-bullets, no grouping headers. An unticked task item that legitimately
survives (a pre-existing deferral or a Proven Exception, per Step 2) is named HERE, on its
issue's line — never in the table. If Step 2 reopened an issue, its line says so:
`#412 worked → closed — REOPENED: 2 items unfinished at first close, now done`.

**Asking — for a decision, not for permission**

A ❌ that genuinely needs YOU is not explained in prose. Emit the table FIRST so the answer
is on screen, then make exactly ONE `AskUserQuestion` call carrying EVERY open question:
batched, never drip-fed, at most four, each with ≤2 sentences of context and concrete action
options — recommended option FIRST and labelled `(Recommended)`, never a bare yes/no. Record
the same question on the issue and as an `AWAITING_USER` line naming the actual reason
(`continuous-work.md`): a question asked only in chat does not survive compaction and
releases no gate.

What it is NOT for: permission to do the mandatory remediation. Finishing the work, reopening
an issue closed over unfinished items, deleting your own leftovers, tearing down your own
worktree — those are obligations, not questions, and Steps 1–2 have already settled them.
"Shall I continue?" stays forbidden. If nothing is blocked, make no call.

**When `CLOSE: YES`**, offer archiving through the same mechanism — one `AskUserQuestion`
("Archive this session now?" → `Archive` `(Recommended)` / `Keep open`) — and call
`archive_session` with `session_id: "self"` only on an explicit Archive. If that MCP tool is
absent (a plain CLI session has no session-management server), append exactly this one line
instead of asking: `Archive: recommended — no session tool in this session.` That line is the
only permitted addition to the template.

No AI attribution in any comment, commit or issue text (`no-ai-attribution.md`). Never touch
`.kiro/`.
