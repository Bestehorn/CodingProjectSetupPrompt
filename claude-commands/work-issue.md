---
description: Work ONE specific issue end to end — claim it in-progress on the tracker FIRST, sync from remote, develop the fix in its own git worktree via the spec/TDD engine (spec artifacts committed before implementation), open a PR and drive its CI green, then hand it to the merge steward (or merge it and verify it, per config/delivery.json), close out the session, and stop. Single issue only; never continues into the backlog.
argument-hint: "[issue number or ID, e.g. 77 or PROJ-123]"
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch, AskUserQuestion, CronCreate, CronDelete, mcp__ccd_session_mgmt__archive_session, Agent(spec-author, spec-researcher, spec-review-agent, test-architect, standards-reviewer, best-practice-reviewer, security-reviewer, devops-iac-reviewer, adversarial-verifier, spec-implementer, code-merge-reviewer)
---

Take issue **$ARGUMENTS** (call it issue X) from open to **merged and verified** — or, where the merge
steward lands the trunk, to **queued and handed off** (`.claude/docs/delivery.md`) — scoped to
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
   - **Arm the run watchdog** once in this process, exactly as the session-start context prints it
     (`CronCreate`, session-only, recurring, the `[run-watchdog]` prompt — `continuous-work.md`). It fires only
     while the session is idle, so a turn an API error kills is resumed without a person; it costs nothing
     while you work.
   - **`WORKABLE_ISSUES_REMAIN: no` gates NOTHING** (`run-identity.md` §5): it only chooses
     the WORDING of an `issue-loop-gate` refusal. What lets this command finish after ONE
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
     fatal: stop with the Completion Block, verdict FAILED). Record the in-progress
     convention and the merge authority.

**Step 1: Read issue X fresh from the remote**
   - `git fetch origin --prune --no-auto-gc`. Do NOT check out or fast-forward the shared
     local `main` — you stay MAIN-CHECKOUT-FREE and branch off `origin/<main>`.
   - Fetch X fresh via the wrapper (`get-issue`, `get-issue-comments`) — never work from a
     cached or previously-listed snapshot. Quote its state, labels, assignee, and body.
   - If X is already CLOSED, stop with the Completion Block — X as a `skipped` row quoting
     the state (do not reopen).
   - If X does not exist, stop with the Completion Block — X as a `skipped` row quoting the
     wrapper's exact error.

**Step 2: Claim X as in-progress BEFORE any work (the anti-duplicate-work gate)**
   - Acquire the local cross-run lock FIRST: atomically `mkdir`
     `.claude/agent-state/issue-work-orchestrator/.locks/issue-<X>.lock` (atomic
     create-or-fail on NTFS too — never rename-over-existing) and write your `run_id` +
     timestamp inside. If it exists and its owner is a LIVE run (in `registry.json` with a
     fresh heartbeat), a sibling session in this clone already has X: stop with the
     Completion Block (X as a `skipped` row naming that run).
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
     (`no-ai-attribution.md`). The `claim-before-worktree` PreToolUse gate independently
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
   - **Ask every open product question NOW, in one batch** (`continuous-work.md`, "How to ask"): list
     each decision the ask leaves open that no spec, code, doc or decision log settles; post them on the issue
     and in ONE five-line message; then keep working on everything that does not depend on the answers. Ask
     with `AskUserQuestion` — which blocks the session — only when the next step depends on an answer and
     nothing independent remains. A decision asked at the start is answered while you build; one asked at the
     end costs the operator's whole reply time.
   - CLASSIFY the tier from the ASK (`proportionality.md`): **S** for a value, default,
     config, message or doc change or a bounded local fix — however many files, snapshots
     or infrastructure constants it touches; **M** for a feature or fix across components
     with a design choice; **L** for a subsystem. When in doubt choose the smaller tier;
     re-tier UP only with a recorded reason naming what the ask contains. Record
     `Tier:` in `prompt.md` and one `DL-NNN`. The tier fixes the byte caps, the panel, the
     iteration cap and the time tripwire (S 3 h, M 24 h, L 72 h).
   - Synthesize `<worktree>/.claude/specs/<slug>/prompt.md` from the issue: goal, FEATURE
     vs BUGFIX, tier, the ASK's scope (the issue's risk sections, open questions and
     measurements feed residuals, not scope), integration points by symbol and path, and
     the tests that pin each criterion plus — where runtime behaviour changes — the
     automated end-to-end check the pipeline runs after deploy. Note in `qa_log.md` that
     the interview was skipped.
   - **Tier M/L → the proportional spec process:** `spec-phase-design.md` (REQUIREMENTS →
     DESIGN under the caps) → `spec-phase-review.md` (the panel dispatched in ONE message;
     materiality gate; delta review from iteration 2; scope frozen; exit at A+B == 0 with
     full coverage; C/D applied in one pass without a round; cap 4 for M, 6 for L, then the
     five-line question recommending "approve as reviewed, record residuals") →
     `spec-phase-tasks.md` (waves with `Files:` ownership) → light TASKS_REVIEW_LOOP.
   - **Tier S → `change.md` (≤ 8,000 bytes) and one combined `spec-review-agent` pass**
     (all lenses, security included when auth, IAM, secrets or input handling is touched;
     max 2 iterations). No design.md, no panel.
   - Every delegate prompt MUST state the ABSOLUTE worktree path and that spec artifacts
     go under `<worktree>/.claude/specs/<slug>/`, code under `<worktree>/src/`, tests under
     `<worktree>/test/` — delegates inherit the SESSION cwd, not the worktree. After each
     delegate returns, verify the files actually landed via `git -C <worktree> status`.

**Step 5: Commit the spec artifacts BEFORE any implementation (hard gate)**
   - Once the spec has passed review and BEFORE the first line of implementation, commit
     the spec artifacts on the issue branch:
     `git -C <worktree> add .claude/specs/<slug>` then
     `git -C <worktree> commit` with a descriptive message referencing issue X as `Refs #X` (no AI
     attribution, no closing keyword). This is a distinct commit, not folded into the implementation commit,
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
   - `spec-phase-implement.md`, per WAVE: dispatch all the wave's TEST tasks in ONE
     message → run the wave's tests once → `evidence/red/wave-N.txt` with a `# tasks:`
     header, confirmed RED-FOR-THE-RIGHT-REASON via `python .claude/hooks/red_for_right_reason.py`
     → dispatch all the wave's IMPL tasks in ONE message → run once →
     `evidence/green/wave-N.txt` → ONE commit per wave. Tier S is a single wave. Then run
     `adversarial-verifier` once and produce `evidence/REPORT.md` (≤ 8,000 bytes).
   - **Overlap the verification, never thin it.** The suites of one capture that do not depend on each other
     (a Python suite, a UI suite, a type check) start TOGETHER as background tasks, each through
     `scripts/run_tests.py` / `scripts/suite_semaphore.py run` so the host-wide slots still bound the machine,
     and are collected with bounded foreground waits (`python .claude/hooks/wait_for.py --file <capture>
     --line <summary regex> --timeout-seconds 540`, re-issued on exit 11). While a wave's green run is in
     flight, dispatch the NEXT wave's TEST authors (their files are disjoint by construction); that wave's red
     capture is taken only after this wave's green capture passed and is committed. Draft the issue note and
     `evidence/REPORT.md` while the verifier re-runs. Nothing is skipped: every capture, the RED audit and the
     verifier happen exactly as before — they just stop waiting for each other.
   - **No per-task full-suite run.** Commit per task instead — the pre-commit hook is lint
     + security, about a second. The regression verdict for the whole batch is the CI run
     after Step 7's single push (`ci-owns-the-test-suite.md`). Run the affected module
     locally when a change plainly reaches past its paired tests; never `pytest -n auto`,
     and never a suite outside the host-wide semaphore.
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
     for the PR's head SHA (run id + SHA), or the `pre-push` hook's local run while CI-OUTAGE
     MODE is declared — `adversarial-verifier` returned VERIFIED, coverage of changed code
     meets the project threshold, and — for a bugfix — regressions cover the Unchanged
     Behavior clauses. On insufficient proof, record why as `DL-NNN` and reject back to
     implement (cap 3 cycles, then escalate once — the orchestrator's PROOF_GATE).
   - DEFECTS YOU DISCOVER ALONG THE WAY (`issue-filing-discipline.md`): blocking → absorb
     into this change; small and clear (a few lines, no design choice) → **fix it now** in
     this worktree and mention it in the commit/PR, do NOT file it; needs extensive
     research, design options, or work outside this issue → delegate to
     `issue-intake-agent` for ONE gated issue (`Origin: spawned-discovery`,
     `Spawned-from: #X`, plus `Subject:`/`Filing-rationale:`); anything else → a row via
     `python scripts/memory_compile.py ledger add`, committed IN THIS PR. Finishing with zero new issues filed
     is the expected result.
   - DOCUMENT, before the push and in this PR (nothing goes to the trunk after the landing — no evidence PR,
     no ledger PR, `.claude/docs/delivery.md` §2): the full writeup on issue X via `comment-issue` (root cause
     with citation, approach, spec/design summary, tests added, link to `evidence/REPORT.md`); every checklist
     item that is DONE ticked; every item only a deploy can prove carries the suffix `(post-deploy)`; then
     commit the code, tests, evidence and ledger rows with an evidence-based message referencing issue X
     as `Refs #X` (never a closing keyword in a commit: the host would close X at landing, before the deploy
     check, and the steward refuses the PR).

**Step 7: PR → its CI green (ONE push, ONE run per fix batch)**
   - Read `config/delivery.json` (absent = `merge: direct`, `verification: session`) and
     `.claude/docs/delivery.md`; the mode decides Step 8.
   - Remote Sync the worktree once more, rebase on the latest `origin/<main>`, delegate any
     conflict to `code-merge-reviewer`, and re-run the AFFECTED tests after integrating.
   - Ensure everything that belongs is committed (`git -C <worktree> status`). Optionally
     run `python scripts/run_checks.py --group lint --group types` for the fast groups —
     they cost seconds and catch the embarrassing failures before the run. Do NOT run the
     full CI command locally to pre-check the pipeline: that is the hour-long duplicate of
     what CI is about to do anyway (`ci-owns-the-test-suite.md`).
   - **Push ONCE.** The push triggers the pre-push hook (mypy, plus the full suite if
     CI-OUTAGE MODE is declared) and then the CI run that is the authoritative verdict.
   - Open the PR via `create-pr` (base `main`, head `<branch>`, body linking issue X with
     `Refs #X` — never a closing keyword when `verification` is `watcher` — and the evidence). Title and body
     describe the change only — strip any AI-attribution line the tool adds. Record `PR` (that field name).
   - Wait for the PR's CI WITHOUT ending the turn: the issue note and the docs are already written, so run
     the wrapper's blocking wait in the FOREGROUND with a bounded timeout (`pipeline wait <id>
     --timeout-seconds 540` / `wait-run <id> --timeout-seconds 540`, Bash timeout 600000), re-issuing it while
     it exits 11 — never `sleep` in a tool call, never a background task you then wait for (it dies with the
     session's process and never wakes you). Then read the verdict via `get-pr-checks` / `get-logs`.
     **On failure, fix the whole run in one pass:** retrieve the COMPLETE logs of EVERY
     non-successful job (the pipeline does not fail fast, so a red run is the complete
     list), enumerate every failing test and check, group them by root cause and record
     `N failures across M jobs → K root causes` as `DL-NNN`, fix them ALL at root cause in
     the worktree committing as you go, then push ONCE and re-monitor. Fixing one failure
     and re-pushing to discover the next is forbidden. Never abandon a red pipeline.

**Step 8: Land, verify or hand off — then close out and STOP**
   - **`merge: steward` (any verification) — HAND OFF.** `python scripts/<wrapper>.py enqueue-pr <PR>`
     (exit 4 prints why the queue refuses it: fix that, never work around it; the `merge-steward` gate refuses
     `merge-pr` and any push to the trunk). Post the hand-off note on X (`.claude/docs/delivery.md` §3: PR,
     evidence path, what the post-deploy check must show, and the two `merge-steward:` lines verbatim, the
     claim time from Step 2). APPEND `Phase: HANDED_OFF` to `resume_state.md` and `Phase: DONE` +
     `Status: COMPLETED` to `workflow_state.md`. The steward lands it; the verdict watcher (or, under
     `verification: none`, the landing itself) verifies and closes X. A conflict, a red train or a red deploy
     comes back to X as `needs-rework` with the claim released — a later run picks it up. Keep the tracker
     claim; release the local lock in the close-out below.
   - **`merge: direct` + `verification: watcher` — MERGE, RECORD, HAND OFF.** Approve + merge per the
     recorded authority (`approve-pr`, `merge-pr`; if branch protection forbids self-approval, set
     `AWAITING_USER: waiting for external approval of PR #<n>`, poll `get-pr` on an interval with
     checkpoints, merge once approved and CI is green, then clear `AWAITING_USER` to `none`); confirm the
     merge landed (`git fetch origin --prune --no-auto-gc`, `git merge-base --is-ancestor <merge-sha>
     origin/<main>`); `python scripts/merge_steward.py record-landing <PR>`; then the hand-off note and
     `Phase: HANDED_OFF` exactly as above.
   - **`merge: direct` + `verification: session` — today's lifecycle.** Merge as just described, then wait for
     the post-merge trunk pipeline in the FOREGROUND, bounded and re-issued — its deploy and post-deploy stage
     run the committed end-to-end check, and that verdict on a commit containing the merge is the E2E
     evidence (`always-test-e2e.md`); you never deploy a branch to the shared environment or ask the operator
     to check anything by hand. If it fails, the fix is not done — rework in a FRESH worktree cut from
     `origin/<main>` until it is green. Then RESOLVE per `issue-tracking.md`: final comment linking the merged
     PR and the evidence, checklist fully ticked — re-read X and COUNT its `- [ ]` / `- [x]` lines, then
     finish any item still open rather than closing over it (only an item whose deferral was already
     recorded on the issue may stay unticked, routed per `issue-filing-discipline.md`) — time spent recorded
     (elapsed from the Step 2 start time), then close X via `update-issue`, and append `Status: COMPLETED`
     and `Phase: DONE`. **The terminal or hand-off value is what releases the Stop gate** — it must be the
     WHOLE value of the field (`Phase: DONE`, never `Phase: DONE (was IMPLEMENT)`).
   - **Close out — every mode, at once, without asking.** Run the `/close-session` checks
     (`.claude/commands/close-session.md`) as this command's last step: tree clean; nothing unpushed
     (`git -C <worktree> status --porcelain` empty AND `git -C <worktree> log origin/<branch>..HEAD` empty —
     otherwise push, never discard); tear down the worktree venv FIRST if one was provisioned (locked DLLs
     otherwise block removal on Windows), `git worktree remove .claude/worktrees/issue-<X>`, `git branch -D
     issue-<X>-<slug>` (the REMOTE branch stays while the steward still needs it: `delete-remote-branch` only
     after a direct merge if the host did not auto-delete), verify with `git worktree list`; the reaper; under
     `verification: session` remove the tracker's in-progress marker BEFORE releasing the local lock (`rmdir
     .locks/issue-<X>.lock`); under hand-off keep the tracker claim and release only the lock; `CronDelete`
     the run watchdog. On `CLOSE: YES` archive the session (`archive_session` with `session_id: "self"`)
     WITHOUT asking — the measured "Archive this session?" wait was 71 h in two weeks; on `CLOSE: NO` the
     close-out's own question rules apply.
   - **Then STOP, and reply with the agent definition's Completion Block** — the fixed
     verdict line, the per-issue table (X as its `closed` row, or its `handed off` row with the queued or
     landed PR; `Tasks` from a fresh re-read; the CI-run count in `Detail`; plus a `filed` row for anything
     routed through intake), and the three trailer lines — and nothing else. Do NOT select another
     issue — that is what `/issues-work` (or `/auto-work`, for an unattended whole-backlog
     run) is for. The block's `Backlog` line is where "other workable issues remain" is
     said; the user decides from there.

**Escalation and the ambiguous-issue path**
   - If X is too ambiguous to derive testable acceptance criteria even after research, post
     the clarifying question(s) ON issue X via `comment-issue` (questions live on the
     issue, not in transient chat), then release the claim with `issue release <X>` and the
     local lock, tear down the worktree venv and remove the worktree so nothing stale is
     left, record the state, and stop with the Completion Block (X as a `blocked` row,
     `Detail` = released; question on issue). Do not guess, and do not silently substitute
     a different issue.
   - Otherwise escalate ONCE, batched, only when genuinely blocked (proof gate exhausted, a
     genuinely ambiguous conflict, an undiagnosable CI failure, a missing wrapper
     subcommand): post the specifics to the issue, record the blocked state with
     an `AWAITING_USER` line in `resume_state.md` naming the ACTUAL reason (the literal `<reason>` is
     rejected as a placeholder), and surface one clarity-first message.
