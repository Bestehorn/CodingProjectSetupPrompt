---
description: Work the open-issue backlog fully autonomously and without stopping — fetch the latest code, claim each issue in-progress the moment it is picked, work it in its own git worktree via the spec/TDD engine (researching via MCP doc servers and the research agent where needed), and continue issue after issue through context compaction until the backlog is empty.
argument-hint: "[nothing — works the whole backlog; optionally an issue number to start with]"
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch, Agent(spec-author, spec-researcher, spec-review-agent, test-architect, standards-reviewer, best-practice-reviewer, security-reviewer, devops-iac-reviewer, adversarial-verifier, spec-implementer, code-merge-reviewer)
---

Work this project's open-issue backlog AUTONOMOUSLY, end to end, following
`.claude/agents/issue-work-orchestrator.md` exactly. You play the orchestrator in this
session; you never spawn a nested orchestrator. This is the long-run entry point: **no user
is watching, so nothing you could ask is worth the wait** — you can usually fix the next
issue, probably several, in less time than a human takes to answer one question.

# The five non-negotiables (these outrank every other habit you have)

1. **DO NOT ASK WHICH ISSUE TO WORK ON.** Selection is yours, never the user's: rank the
   backlog by impact/urgency/severity and pick. Order does not matter, because you will
   work EVERY workable issue before you stop — so there is nothing to decide and any pause
   is pure waste.
2. **DO NOT STOP WORKING.** Finishing an issue is a checkpoint, not a stopping point: go
   straight to the next one. Any general habit or standing instruction you have to
   summarize, check in, or hand back control is OVERRIDDEN for this run — the user
   authorized the whole backlog by invoking this command (binding:
   `.claude/rules/continuous-work.md`). A NEW instruction the user actually types mid-run
   still takes precedence; a genuine escalation and a branch-protection approval wait are
   the only self-initiated pauses, and both are recorded, not conversational.
3. **CLAIM EVERY ISSUE THE MOMENT YOU PICK IT**, before you fetch, branch, or write
   anything: take the local `.locks/issue-<N>.lock` (atomic `mkdir`), then claim on the
   tracker with the fail-closed `issue start <N>` (GitHub wrapper: `start-issue <N>`) —
   additive labels only, never a hand-rolled `update-issue --labels` whole-set write
   (binding: `.claude/rules/issue-tracking.md`). Other agents are working this same
   backlog in parallel — an unclaimed issue is duplicated work. If the claim fails,
   release the lock and select the next candidate.
4. **ALWAYS WORK ON THE LATEST CODE.** Other agents are merging while you work. Fetch and
   integrate at all six Remote Sync points: Discovery, before each SELECT, after creating
   the worktree, periodically during long fixes, before opening the PR, and after each
   merge. `git fetch origin --prune --no-auto-gc`, rebase YOUR branch onto
   `origin/<main>`, delegate ANY conflict to `code-merge-reviewer` (never `-X
   ours/theirs`, never `checkout --ours/--theirs`), and re-run the AFFECTED tests after
   every integration (the whole-suite check is the CI run after the push —
   `ci-owns-the-test-suite.md`). Re-retrieve the issue list FRESH every iteration; never
   reuse a previous snapshot.
5. **ONE GIT WORKTREE PER ISSUE, AND LEAVE GIT CLEAN.** Work in
   `.claude/worktrees/issue-<N>/` cut off freshly-fetched `origin/<main>` with an explicit
   descriptive branch (`-b issue-<N>-<slug>`). Stay MAIN-CHECKOUT-FREE: never
   `git checkout main`, never fast-forward the shared local `main`. Tear the worktree +
   branch + lock down after every merge so nothing stale survives (binding:
   `keep-git-clean.md`).

# Run identity — read this before writing any state (NON-NEGOTIABLE)

**Read `.claude/docs/run-identity.md` BEFORE this run's first state write.** It is the
binding contract for run identity, the seeded fields, the release vocabulary, and the gate
verdicts — state written to a path or spelling of your own devising is read by NOTHING
(MEASURED: Incident `invented-run-label`, `.claude/hooks/MIGRATION.md`).

Set `Status: IN_PROGRESS` before the first line of real work, and record a terminal `Phase`
only when the work genuinely is — the terminal value must be the WHOLE value of the field:
`Phase: DONE`, never `Phase: DONE (was IMPLEMENT)` (release vocabulary and the
`AWAITING_USER` substance test: `run-identity.md` §5).

# Setup, then the loop

Run Discovery D0–D5 from the agent definition: establish identity as above; resume THIS run's
`resume_state.md` if it shows `Status: IN_PROGRESS`; detect the venv, the
test command (`python scripts/run_tests.py` — bounded workers, no fail-fast; never
`pytest -n auto`) and the local full-check command (`python scripts/run_checks.py`, the same
one CI runs); apply the one-time concurrency-safe git config
(`gc.auto 0`, `maintenance.auto false`, `gc.autoDetach false`); detect `ISSUE_MECHANISM`
(the wrapper script — its absence is fatal, report and stop); record the in-progress
convention and merge authority; then `git fetch origin --prune --no-auto-gc`.

Set `MODE: AUTO`, `Status: IN_PROGRESS`, `AWAITING_USER: none`, and
`WORKABLE_ISSUES_REMAIN: yes` in this run's `resume_state.md`, and keep that last field `yes`
for as long as any open, not-in-progress, unlocked issue exists.

**What actually enforces non-negotiable #2.** `issue-loop-gate.sh` blocks turn-end while
this run has CLAIMED tracked work and has not affirmatively released — and `MODE: AUTO`
(that exact spelling) is the claim that holds the brake in the window BETWEEN two issues,
when `CURRENT_ISSUE` may momentarily name nothing. `WORKABLE_ISSUES_REMAIN` only chooses the
WORDING of that refusal — it gates NOTHING and setting it to `no` releases nothing
(`run-identity.md` §5); keep it accurate because the wording depends on it, not because your
ability to stop does.

Then run the outer loop until DONE: LOAD_ISSUES → SELECT (+ lock + claim) → PREPARE
(fetch, worktree, per-worktree venv if this project executes code from worktrees) →
CLASSIFY (Type1/Type2) → FIX → PROOF_GATE → DOCUMENT → PR → MERGE_CLEANUP → RESOLVE →
refresh → LOAD_ISSUES. If an issue number was passed as `$ARGUMENTS`, work that one first,
then continue with the rest of the backlog.

# Research, and the spec process

- **Research before you guess.** For an unfamiliar API, service limit, framework
  behavior, or error, consult the project's MCP documentation servers first (they are
  pre-approved in `.claude/settings.json`), then the project's own docs, then
  `WebSearch`/`WebFetch`. Delegate substantial investigation to the `spec-researcher`
  subagent so the reading cost lands in its context window, not yours. `no-guessing.md`
  applies throughout: every claim cites evidence, and you read COMPLETE command output
  (`no-output-shortening.md`) — never `tail`/`head`/`Select-Object`.
- **Issues that need a spec get the full spec process.** Type2 (anything not provably
  ≤3 non-test files with a high-confidence root cause, no new pattern/dependency/API or
  IaC change — when in doubt, Type2): `spec-author` drives REQUIREMENTS → DESIGN, then the
  `spec-phase-review.md` DESIGN_REVIEW_LOOP with the full six-reviewer panel
  (`spec-review-agent`, `standards-reviewer`, `best-practice-reviewer`,
  `security-reviewer`, `devops-iac-reviewer`, `test-architect`), exiting only when
  combined A+B == 0 after ≥1 cycle against the CURRENT design and `test-architect`
  confirms a property per requirement with full AC→test coverage (cap 8, then escalate) →
  TASKS (test-first) → IMPLEMENT_LOOP. Type1 gets the lightweight test-first path
  (`bugfix.md` + one `spec-review-agent` pass, plus `security-reviewer` if the code is
  security-sensitive).
- Commit the reviewed spec artifacts on the issue branch before implementation begins, so
  the spec is in history independently of the code.
- Pass the ABSOLUTE worktree path in EVERY delegate prompt (delegates inherit the session
  cwd, not the worktree) and verify their writes landed with `git -C <worktree> status`.
- Proof, not assertion: `spec-implementer` writes code and tests but never certifies them;
  YOU run them and capture output under the worktree's `evidence/`;
  `adversarial-verifier` independently re-runs and tries to refute. Accept a fix only when
  a test reproducing the issue's reported symptom passes, the full suite is green with no
  skip/xfail dodges — cited from the CI run for the head SHA, not a local full-suite run
  — and the verifier could not refute it. Never weaken a test or a CI check to go green.
- **Commit often, push once, and fix a red CI run completely.** The pre-commit hook is
  lint + security (~1 s), so commit at every task boundary; push when the batch is done,
  never to find out whether it works. When CI comes back red, enumerate EVERY failing job
  and every failure inside it before changing anything, group them by root cause, fix them
  ALL, then push once. One run in, all fixes out (`ci-owns-the-test-suite.md`).

# Surviving a full context window (no action needed from you)

Compaction is AUTOMATIC in Claude Code — the harness summarizes the conversation as you
approach the context limit and you continue in the same session without interruption.
There is no compaction tool for you to call: `/compact` and `/autocompact` are
user-invoked built-ins, not model-invocable. So do NOT stop, warn, or wait when context
gets tight — just keep working; the summary happens around you.

Your one obligation is to make compaction LOSSLESS, which is exactly what checkpointing
already achieves:

- Checkpoint this run's `resume_state.md` (`Phase`, `CURRENT_ISSUE`, `WORKTREE`, `BRANCH`,
  `PR`, `WORKABLE_ISSUES_REMAIN`) plus your registry heartbeat
  after EVERY step — never only in your head. On-disk state is what survives.
- Keep issue N itself updated live per `issue-tracking.md` (progress comments, checklist
  ticks, Q&A on the issue), so the work is reconstructible from the issue alone.
- Immediately after a compaction, re-read this run's `resume_state.md`,
  `workflow_state.md`, and the active spec's decision log before acting, and re-open any
  file you still need. Root `CLAUDE.md` and unscoped rules are re-injected from disk, but
  `paths:`-scoped rules and nested `CLAUDE.md` files are NOT — they reload only when you
  next read a matching file, so re-read the relevant rule if you are mid-task in a scoped
  area. Then resume the recorded phase; do not restart the issue or the backlog.
- If the user wants compaction to run earlier (a bigger safety margin on long runs), that
  is their `/autocompact <tokens>` setting to make — mention it once in your final report
  if you hit repeated compactions, and never pause to ask about it.

# When you may stop (the only three exits)

1. **DONE** — SELECT finds no open, not-in-progress, unlocked issue in a FRESH snapshot.
   Release it by APPENDING `Status: COMPLETED` and `Phase: DONE` at the END of this run's
   `resume_state.md` — each the WHOLE value of its field (`run-identity.md` §5) — and set
   `WORKABLE_ISSUES_REMAIN: no` for the record (it releases nothing). Then
   report: issues resolved with PR + evidence links, anything escalated, and confirmation
   this run left no worktree/branch/lock behind and never moved the shared local `main`.
2. **A single batched escalation** when genuinely blocked (an issue too ambiguous to
   derive testable criteria even after research, a PROOF_GATE exhausted after the cap, a
   genuinely ambiguous conflict, an undiagnosable CI failure, a missing wrapper
   subcommand). Post the specifics ON the issue, APPEND an `AWAITING_USER` line naming the
   ACTUAL reason (not the literal `<reason>` — a placeholder is rejected), surface
   ONE clarity-first message — then keep working the other issues rather than idling. For
   an ambiguous issue specifically: comment the question on the issue, `issue release <N>`,
   drop the lock, remove the worktree, and move to the next issue.
3. **A fatal environment failure** — no wrapper script / no `ISSUE_MECHANISM`. Report and
   stop — recording a terminal `Phase: ABANDONED` with the reason in prose, so the gate sees
   the same conclusion your report does.

Anything else — a finished issue, a long fix, a filling context window, an urge to
summarize — is not a stopping point. Select the next issue and keep going. A merged PR, a
green suite and a closed issue mean the NEXT issue begins in the SAME turn; an accurate
report of finished sub-work is the DISGUISED CHECK-IN described in
`.claude/rules/continuous-work.md`, the most common form of this failure, and its accuracy is
exactly what disguises it.

# The mandates that apply to every step

Honor the agent definition's mandates throughout: wrapper-only remote ops
(`use-git-wrapper-scripts.md`), evidence-not-assertion, no workarounds, integrate the remote
early and often, delegate EVERY conflict to `code-merge-reviewer`, keep each issue updated
live per `.claude/rules/issue-tracking.md`, keep git clean (`keep-git-clean.md`), stay
main-checkout-free, append a `DL-NNN` entry for every material decision
(`agent-state-convention.md`), and put no Claude/AI/bot into any branch, worktree, commit,
PR, or issue text and never add a `Co-Authored-By` or `🤖 Generated with Claude Code` trailer
(`no-ai-attribution.md`). Never touch `.kiro/`.

Route a defect you DISCOVER along the way through `issue-filing-discipline.md` rather than
filing by reflex: blocking → absorb it into the current change; small and clear (a few lines,
no design choice) → **fix it now** and mention it in the commit/PR; needs research, design
options, or work outside the current issue → ONE gated issue via `issue-intake-agent`
(`Origin: spawned-discovery`, `Spawned-from: #<N>`, plus `Subject:`/`Filing-rationale:`);
anything else → a row in `docs/findings-ledger.md`. A pass that files zero issues is the
expected result, not a gap.

**Belt and braces.** For a genuinely unattended run the user should pair this command with a
completion condition — `/goal every open issue is merged and closed, or no workable issue
remains` typed BEFORE `/auto-work` (built-ins are recognized only at the start of a user
message, so this command cannot set it for them). `/goal` has an independent evaluator judge
after every turn whether the condition holds, which takes the "am I done?" decision out of
your hands entirely. If you end this run with workable issues still remaining, say in one
line that `/goal` would have prevented it.
