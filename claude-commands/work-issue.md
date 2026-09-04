---
description: Work ONE specific issue end to end — claim it in-progress on the tracker FIRST, sync from remote, develop the fix in its own git worktree via the spec/TDD engine (spec artifacts committed before implementation), open a PR, drive CI green, merge, clean up, and close. Single issue only; never continues into the backlog.
argument-hint: "[issue number or ID, e.g. 77 or PROJ-123]"
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch, Agent(spec-author, spec-researcher, spec-review-agent, test-architect, standards-reviewer, best-practice-reviewer, security-reviewer, devops-iac-reviewer, adversarial-verifier, spec-implementer, code-merge-reviewer)
---

Take issue **$ARGUMENTS** (call it issue X) from open to **merged and closed**, scoped to
THIS ONE ISSUE. Steps 1–8 below ARE the single-issue lifecycle; consult the matching phase
section of `.claude/agents/issue-work-orchestrator.md` only if a detail here leaves a
question open — never read the whole file up front. You play the orchestrator role in this
session; you do not launch a nested orchestrator, and you do NOT continue into the rest of
the backlog when X is done.

If `$ARGUMENTS` is empty, STOP and ask which issue to work — never guess an issue number.
Accept `77`, `#77`, or a host-native ID (`PROJ-123`); normalize it and use the wrapper's
own identifier form from then on.

Honor the always-loaded rules throughout: read COMPLETE command output
(`no-output-shortening.md`), cite evidence for every claim (`no-guessing.md`), all remote
operations through the wrapper script (`use-git-wrapper-scripts.md`), venv discipline
(`use-venv.md`), commit only what belongs and leave no stale worktree/branch
(`keep-git-clean.md`), keep the issue as the live record (`issue-tracking.md`), never put
Claude/AI/bot into a branch, commit, PR, or issue and never add a `Co-Authored-By` or
`🤖 Generated with Claude Code` trailer (`no-ai-attribution.md`), CI must be green
(`remote-ci-must-pass.md`), tests run in CI and not on every commit
(`ci-owns-the-test-suite.md`), and log every material decision as `DL-NNN`
(`agent-state-convention.md`). Never touch `.kiro/`.

**Step 0: Single-issue mode (state + autonomy)**
   - **Read `.claude/docs/run-identity.md` BEFORE this run's first state write.** It is the
     binding contract for run identity, the seeded fields, the release vocabulary, and the
     gate verdicts — state written to a path or spelling of your own devising is read by
     NOTHING (MEASURED: Incident `invented-run-label`, `.claude/hooks/MIGRATION.md`).
   - If this run's `resume_state.md` already shows `Status: IN_PROGRESS` for a
     DIFFERENT `CURRENT_ISSUE`, do not abandon it: report the in-flight issue and ask
     whether to finish that one first or run X in a separate session. If it shows
     `Status: IN_PROGRESS` for issue X, RESUME at the recorded phase (re-attach to the
     existing worktree / branch / PR) instead of restarting.
   - Record `MODE: SINGLE_ISSUE` (that exact spelling — it is what the loop gate's MODE
     claim matches), `CURRENT_ISSUE: X`, `Status: IN_PROGRESS`, `AWAITING_USER: none`, and
     `WORKABLE_ISSUES_REMAIN: no`.
   - **`WORKABLE_ISSUES_REMAIN: no` gates NOTHING** (`run-identity.md` §5): it only chooses
     the WORDING of an `issue-loop-gate.sh` refusal. What lets this command finish after ONE
     issue is reaching a terminal `Phase` on X and not selecting another, not this field.
   - Autonomy still applies WITHIN the issue: do not stop mid-lifecycle to report progress
     or ask whether to continue. The only permitted pauses are a genuine escalation, a
     branch-protection approval wait, and the "already claimed by someone else" decision in
     Step 2 — and each is recorded MECHANICALLY as `AWAITING_USER: <the actual reason>`, not
     merely described in chat; the field is checked for SUBSTANCE, not presence
     (`run-identity.md` §5), and an escalation the gate cannot see is indistinguishable from
     abandoning the work — the turn-end will be REFUSED. Checkpoint
     `resume_state.md` + your registry heartbeat after every step.
   - **EVERY exit from this command needs a RECORDED release, including the early ones.** The
     "X is already closed" stop in Step 1, the "claimed by someone else" stop in Step 2, the
     ambiguous-issue path, and normal completion are all turn-ends, and the Stop gate judges
     the FILE, not the report. So before ending any of them, APPEND at the END of
     `resume_state.md` either a terminal `Phase`/`Status` (`DONE` when X is genuinely
     finished, `ABANDONED` when you are standing down, `ESCALATED` when handing back) or a
     substantive `AWAITING_USER` — with the human-readable reason in prose beside it. Writing
     the reason only in chat is what makes a legitimate stop look like an abandoned one.
   - Complete Discovery D1–D2 if `environment.md` is not already recorded: source/test
     layout, venv, the test command (`python scripts/run_tests.py` — bounded workers, no
     fail-fast; never `pytest -n auto`) and the local full-check command
     (`python scripts/run_checks.py`, the same one CI runs), the one-time
     concurrency-safe git config (`gc.auto 0`, `maintenance.auto false`,
     `gc.autoDetach false`), and `ISSUE_MECHANISM` (the wrapper script — its absence is
     fatal, report and stop). Record the in-progress convention and the merge authority.

**Step 1: Read issue X fresh from the remote**
   - `git fetch origin --prune --no-auto-gc`. Do NOT check out or fast-forward the shared
     local `main` — you stay MAIN-CHECKOUT-FREE and branch off `origin/<main>`.
   - Fetch X fresh via the wrapper (`get-issue`, `get-issue-comments`) — never work from a
     cached or previously-listed snapshot. Quote its state, labels, assignee, and body.
   - If X is already CLOSED, report that with the quoted state and stop (do not reopen).
   - If X does not exist, report the wrapper's exact error and stop.

**Step 2: Claim X as in-progress BEFORE any work (the anti-duplicate-work gate)**
   - Acquire the local cross-run lock FIRST: atomically `mkdir`
     `.claude/agent-state/issue-work-orchestrator/.locks/issue-<X>.lock` (atomic
     create-or-fail on NTFS too — never rename-over-existing) and write your `run_id` +
     timestamp inside. If it exists and its owner is a LIVE run (in `registry.json` with a
     fresh heartbeat), a sibling session in this clone already has X: report that and stop.
     Reclaim only a provably stale lock (owner heartbeat past the bound AND its worktree's
     `.git` pointer no longer resolves AND its `resume_state` is terminal), archiving the
     stale contents first.
   - Then claim on the tracker with the ONE deterministic, fail-closed command:
     `issue start <X>` (GitHub wrapper: `start-issue <X>`). It is idempotent and
     self-verifying — it re-fetches X, aborts if X is not open or is assigned to someone
     else, adds the in-progress label ADDITIVELY, assigns the working identity, then
     re-reads to confirm both landed, exiting non-zero if the claim did not take.
   - NEVER hand-roll the claim with `update-issue --labels` — that field is a whole-set
     replace and silently drops other labels (see `issue-tracking.md`). Use only the
     additive `issue label-add` / `label-remove` / `assign` primitives if you need more.
   - **If `issue start` exits non-zero** (X was closed or claimed in this window, or the
     verification failed): release your local lock (`rmdir`) and STOP with the quoted
     output. Unlike `/issues-work`, do NOT silently move to a different issue — the user
     named this one. If X is in progress under someone else, say who holds it and ask
     whether to take it over; take over only on an explicit go-ahead.
   - On success: note the wall-clock start time for time-spent at closure, set the
     parent/epic link if X has one, append a `DL-NNN` entry, and checkpoint. This verified
     claim is what stops other workers from duplicating the work.

**Step 3: Worktree off freshly-fetched `origin/<main>`**
   - `git fetch origin --prune --no-auto-gc` again so the base is current at branch time.
   - `git worktree add .claude/worktrees/issue-<X> -b issue-<X>-<slug> origin/<main>`
     with an EXPLICIT descriptive `<slug>` (e.g. `issue-77-invoke-grant`). Never accept an
     auto-generated `claude/<name>` branch; never put claude/ai/bot in the name
     (`no-ai-attribution.md`). The `claim-before-worktree.sh` PreToolUse hook independently
     blocks this call until X's claim is visible on the remote — if it blocks, your Step 2
     claim did not land: fix the claim, do not work around the hook.
   - Record the ABSOLUTE worktree path as `WORKTREE` and the branch as
     `BRANCH` (also in your registry entry) — those exact field names, because they are the
     ones the hooks read. This per-issue worktree is what lets
     this session work in parallel with other workers on the same machine — every command
     from here runs as `git -C <worktree> …` or `cd <worktree> && <venv> …`, never against
     the main checkout.
   - If this project executes code/CDK from worktrees, provision the worktree's OWN venv
     now per `per-worktree-venv.md` — do not reuse or repoint the shared venv.
   - Mirror `CURRENT_SPEC=<worktree>/.claude/specs/<slug>` and `Phase=FIX` into
     `runs/<run-id>/workflow_state.md` so the TDD/evidence hooks fire for this run.

**Step 4: Classify, then run the spec process (spec-author / spec-review-agent)**
   - CLASSIFY Type1 vs Type2 by the orchestrator's criteria (Type1 only if ALL hold: ≤3
     non-test files, no new architectural pattern, no public-API change with downstream
     consumers, no new dependency, no IaC change, existing test patterns suffice, root
     cause identifiable with high confidence). When ambiguous, choose Type2. Record the
     call + rationale as `DL-NNN`.
   - Synthesize `<worktree>/.claude/specs/<slug>/prompt.md` from the issue (goal, FEATURE
     vs BUGFIX, scope/out-of-scope, integration points) with the explicit requirement that
     the spec include an end-to-end test reproducing the reported symptom plus regression
     coverage. Note in `qa_log.md` that the interview was skipped and the prompt derives
     from issue X.
   - **Type2 → the full spec process:** `spec-phase-design.md` (REQUIREMENTS → DESIGN with
     Correctness Properties, Testing Strategy, threat model, DevOps, AC→test mapping) →
     `spec-phase-review.md` DESIGN_REVIEW_LOOP with the full six-reviewer panel, exiting
     only when combined A+B == 0 after ≥1 cycle against the CURRENT design and
     `test-architect` confirms a property per requirement with full AC→test coverage (cap
     8 cycles, then escalate) → `spec-phase-tasks.md` TASKS (test-first) → light
     TASKS_REVIEW_LOOP.
   - **Type1 → lightweight test-first:** `spec-author` writes `bugfix.md`
     (Current/Expected/Unchanged behavior in EARS) from the issue; run
     `spec-review-agent` over it for a single review pass; add `security-reviewer` if the
     issue touches security-sensitive code. Skip the heavy design panel.
   - Every delegate prompt MUST state the ABSOLUTE worktree path and that spec artifacts
     go under `<worktree>/.claude/specs/<slug>/`, code under `<worktree>/src/`, tests under
     `<worktree>/test/` — delegates inherit the SESSION cwd, not the worktree. After each
     delegate returns, verify the files actually landed via `git -C <worktree> status`.

**Step 5: Commit the spec artifacts BEFORE any implementation (hard gate)**
   - Once the spec has passed review and BEFORE the first line of implementation, commit
     the spec artifacts on the issue branch:
     `git -C <worktree> add .claude/specs/<slug>` then
     `git -C <worktree> commit` with a descriptive message referencing issue X (no AI
     attribution). This is a distinct commit, not folded into the implementation commit,
     so the reviewed spec is in the repo's history independent of the code.
   - **Do NOT push it on its own.** The commit is the gate; a separate push is not. A push
     triggers a CI run over a branch with no code change in it, which is a pipeline run
     spent on nothing (`ci-owns-the-test-suite.md`: push once, when the batch is
     complete). The branch gets pushed in Step 7, and the spec commit rides along with its
     own history intact. If this project specifically requires the spec to be visible on
     the remote before implementation, push here and note in `DL-NNN` that the extra run
     was a deliberate cost.
   - Confirm the gate with quoted evidence: `git -C <worktree> log --stat -1` showing the
     spec files, and `git -C <worktree> status --porcelain` clean of spec artifacts. Post a
     short progress comment on issue X with the branch and spec location, and append a
     `DL-NNN` entry. Do NOT start implementation until this commit exists.

**Step 6: Implement, prove, document**
   - Type2: `spec-phase-implement.md` IMPLEMENT_LOOP per task — RED (a failing test that
     reproduces the reported symptom; confirm RED-FOR-THE-RIGHT-REASON via
     `.claude/hooks/red-for-right-reason.sh` — assertion failure, not an import/collection
     error) → GREEN (minimal fix, paired tests only via
     `python scripts/run_tests.py <paths>`) → COMMIT, YOU capturing every run into
     `<worktree>/.claude/specs/<slug>/evidence/`. Type1: the same RED → GREEN → commit
     cycle without the design panel. Then run `adversarial-verifier` and produce
     `evidence/REPORT.md`.
   - **No per-task full-suite run.** Commit per task instead — the pre-commit hook is lint
     + security, about a second. The regression verdict for the whole batch is the CI run
     after Step 7's single push (`ci-owns-the-test-suite.md`). Run the affected module
     locally when a change plainly reaches past its paired tests; never `pytest -n auto`,
     and never two worktrees running suites at the same time.
   - Evidence, not assertion: `spec-implementer` writes code and tests but never certifies
     them; YOU run the tests and capture the output; `adversarial-verifier` independently
     re-runs and tries to refute.
   - No shortcuts: never skip, xfail, weaken, or delete a test or CI check to go green; fix
     root causes.
   - Run **Remote Sync** on the worktree between major sub-phases of a long fix
     (`git -C <worktree> fetch origin --prune --no-auto-gc` then
     `git -C <worktree> rebase origin/<main>`), delegating ANY conflict to
     `code-merge-reviewer` — never resolve one yourself, never `-X ours/theirs`, never
     `checkout --ours/--theirs`. Re-run the AFFECTED tests after an integration; the
     whole-suite check is the CI run in Step 7.
   - PROOF_GATE: accept only when a test reproducing the issue's REPORTED SYMPTOM now
     passes (cite it), the full suite is green with no skip/xfail dodges — cite the CI run
     for the head SHA (run id + SHA), or the `pre-push` hook's local run while CI-OUTAGE
     MODE is declared — `adversarial-verifier` returned VERIFIED, coverage of changed code
     meets the project threshold, and — for a bugfix — regressions cover the Unchanged
     Behavior clauses. On insufficient proof, record why as `DL-NNN` and reject back to
     implement (cap ~5 cycles, then escalate once).
   - DEFECTS YOU DISCOVER ALONG THE WAY (`issue-filing-discipline.md`): blocking → absorb
     into this change; small and clear (a few lines, no design choice) → **fix it now** in
     this worktree and mention it in the commit/PR, do NOT file it; needs extensive
     research, design options, or work outside this issue → delegate to
     `issue-intake-agent` for ONE gated issue (`Origin: spawned-discovery`,
     `Spawned-from: #X`, plus `Subject:`/`Filing-rationale:`); anything else → a row in
     `docs/findings-ledger.md`. Finishing with zero new issues filed is the expected result.
   - DOCUMENT: post the full writeup on issue X via `comment-issue` (root cause with
     citation, approach, spec/design summary, tests added, quoted proof / link to
     `evidence/REPORT.md`), then commit the code, tests, and evidence with an
     evidence-based message referencing issue X.

**Step 7: PR → CI green → merge (ONE push, ONE run per fix batch)**
   - Remote Sync the worktree once more, rebase on the latest `origin/<main>`, delegate any
     conflict to `code-merge-reviewer`, and re-run the AFFECTED tests after integrating.
   - Ensure everything that belongs is committed (`git -C <worktree> status`). Optionally
     run `python scripts/run_checks.py --group lint --group types` for the fast groups —
     they cost seconds and catch the embarrassing failures before the run. Do NOT run the
     full CI command locally to pre-check the pipeline: that is the hour-long duplicate of
     what CI is about to do anyway (`ci-owns-the-test-suite.md`).
   - **Push ONCE.** The push triggers the pre-push hook (mypy, plus the full suite if
     CI-OUTAGE MODE is declared) and then the CI run that is the authoritative verdict.
   - Open the PR via `create-pr` (base `main`, head `<branch>`, body linking issue X and
     the evidence). Title and body describe the change only — strip any AI-attribution
     line the tool adds. Record `PR` (that field name).
   - Approve + merge per the recorded authority: `approve-pr` then `merge-pr`. If branch
     protection forbids self-approval, set `AWAITING_USER: waiting for external approval
     of PR #<n>`, poll `get-pr` on an interval, checkpoint between polls, and merge once
     approved and CI is green; clear `AWAITING_USER` back to `none` after merging.
   - Monitor CI to a terminal state via `get-pr-checks` / `list-runs` + `get-logs`.
     **On failure, fix the whole run in one pass:** retrieve the COMPLETE logs of EVERY
     non-successful job (the pipeline does not fail fast, so a red run is the complete
     list), enumerate every failing test and check, group them by root cause and record
     `N failures across M jobs → K root causes` as `DL-NNN`, fix them ALL at root cause in
     the worktree committing as you go, then push ONCE and re-monitor. Fixing one failure
     and re-pushing to discover the next is forbidden. Never abandon a red pipeline.

**Step 8: Clean up, close, and STOP**
   - Confirm the merge landed on the trunk WITHOUT touching local `main`:
     `git fetch origin --prune --no-auto-gc` then
     `git merge-base --is-ancestor <merge-sha> origin/<main>`.
   - `delete-remote-branch` if the host did not auto-delete. Tear down the worktree venv
     FIRST if one was provisioned (locked DLLs otherwise block removal on Windows), then
     `git worktree remove .claude/worktrees/issue-<X>` and
     `git branch -D issue-<X>-<slug>`. Verify with `git worktree list` and that the
     directory is gone (`keep-git-clean.md`).
   - Monitor the post-merge trunk pipeline if one exists; if it fails, the fix is not done
     — rework in a FRESH worktree cut from `origin/<main>` until it is green.
   - RESOLVE per `issue-tracking.md`: final comment linking the merged PR and the evidence,
     checklist fully ticked (or remaining items explicitly deferred with a reason — routed
     per `issue-filing-discipline.md`, never as an automatic follow-up issue), time
     spent recorded (elapsed from the Step 2 start time), then close X via `update-issue`.
   - Release the local lock (`rmdir .locks/issue-<X>.lock`) — and remove the tracker's
     in-progress marker BEFORE releasing that lock, since the lock is the ownership evidence
     the removal guard reads. Then, by APPENDING at the END of `resume_state.md`, record
     `Status: COMPLETED` and a terminal `Phase: DONE`, plus `WORKABLE_ISSUES_REMAIN: no`, and
     update your registry entry. **The terminal value is what actually releases the Stop gate**
     — it must be the WHOLE value of the field (`Phase: DONE`, never
     `Phase: DONE (was IMPLEMENT)`), and an unrecorded belief that you are finished releases
     nothing.
   - **Then STOP.** Report: issue X, the PR link, the spec-artifact commit, the proof
     summary, how many CI runs the fix took and what each surfaced, and confirmation that
     no worktree, branch, or lock of this run survives and the shared local `main` was
     never moved. Do NOT select another issue — that is what `/issues-work` (or
     `/auto-work`, for an unattended whole-backlog run) is for. Use those when you want
     the next workable issue picked for you. If other workable issues remain, say so and
     let the user decide.

**Escalation and the ambiguous-issue path**
   - If X is too ambiguous to derive testable acceptance criteria even after research, post
     the clarifying question(s) ON issue X via `comment-issue` (questions live on the
     issue, not in transient chat), then release the claim with `issue release <X>` and the
     local lock, tear down the worktree venv and remove the worktree so nothing stale is
     left, record the state, and stop with a report. Do not guess, and do not silently
     substitute a different issue.
   - Otherwise escalate ONCE, batched, only when genuinely blocked (proof gate exhausted, a
     genuinely ambiguous conflict, an undiagnosable CI failure, a missing wrapper
     subcommand): post the specifics to the issue, record the blocked state with
     an `AWAITING_USER` line in `resume_state.md` naming the ACTUAL reason (the literal `<reason>` is
     rejected as a placeholder), and surface one clarity-first message.
