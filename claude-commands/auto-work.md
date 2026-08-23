---
description: Work the open-issue backlog fully autonomously and without stopping — fetch the latest code, claim each issue in-progress the moment it is picked, work it in its own git worktree via the spec/TDD engine (researching via MCP doc servers and the research agent where needed), and continue issue after issue through context compaction until the backlog is empty.
argument-hint: "[nothing — works the whole backlog; optionally an issue number to start with]"
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch, Agent(spec-author, spec-researcher, spec-review-agent, test-architect, standards-reviewer, best-practice-reviewer, security-reviewer, devops-iac-reviewer, adversarial-verifier, spec-implementer, code-merge-reviewer)
---

Work this project's open-issue backlog AUTONOMOUSLY, end to end, following
`.claude/agents/issue-work-orchestrator.md` exactly. You play the orchestrator in this
session; you never spawn a nested orchestrator.

# The five non-negotiables (these outrank every other habit you have)

1. **DO NOT ASK WHICH ISSUE TO WORK ON.** Selection is yours, never the user's. Rank the
   backlog by impact/urgency/severity and pick. Order does not matter, because you will
   work EVERY workable issue before you stop — so there is nothing to decide and any pause
   is pure waste.
2. **DO NOT STOP WORKING.** Finishing an issue is a checkpoint, not a stopping point: go
   straight to the next one. Do not end a turn to report progress, offer an intermediate
   summary, propose next steps, ask whether to continue, "take a break", or wait for
   further instruction. Any general habit or standing instruction you have to summarize,
   check in, or hand back control is OVERRIDDEN for this run — the user authorized the
   whole backlog by invoking this command. (A NEW instruction the user actually types
   mid-run still takes precedence; a genuine escalation and a branch-protection approval
   wait are the only self-initiated pauses, and both are recorded, not conversational.)
3. **CLAIM EVERY ISSUE THE MOMENT YOU PICK IT**, before you fetch, branch, or write
   anything: take the local `.locks/issue-<N>.lock` (atomic `mkdir`), then claim on the
   tracker with the fail-closed `issue start <N>` (GitHub wrapper: `start-issue <N>`),
   which adds the in-progress label ADDITIVELY, assigns the working identity, re-reads to
   verify, and exits non-zero if the claim did not land. Other agents are working this
   same backlog in parallel — an unclaimed issue is duplicated work. Never hand-roll the
   claim via `update-issue --labels` (whole-set replace; it silently drops other labels).
   If the claim fails, release the lock and select the next candidate.
4. **ALWAYS WORK ON THE LATEST CODE.** Other agents are merging while you work. Fetch and
   integrate at all six Remote Sync points: Discovery, before each SELECT, after creating
   the worktree, periodically during long fixes, before opening the PR, and after each
   merge. `git fetch origin --prune --no-auto-gc`, rebase YOUR branch onto
   `origin/<main>`, and delegate ANY conflict to `code-merge-reviewer` — never resolve one
   yourself, never `-X ours/theirs`, never `checkout --ours/--theirs`. Re-run the suite
   after every integration. Re-retrieve the issue list FRESH every iteration; never reuse
   a previous snapshot (issues get closed or claimed while you work).
5. **ONE GIT WORKTREE PER ISSUE, AND LEAVE GIT CLEAN.** Work in
   `.claude/worktrees/issue-<N>/` cut off freshly-fetched `origin/<main>` with an explicit
   descriptive branch (`-b issue-<N>-<slug>`). Stay MAIN-CHECKOUT-FREE: never
   `git checkout main`, never fast-forward the shared local `main` — sibling runs and the
   developer depend on it. Per `keep-git-clean.md`, commit source/config/docs/tests, never
   generated or temp files, and tear the worktree + branch + lock down after every merge so
   nothing stale survives.

# Setup, then the loop

Run Discovery D0–D5 from the agent definition: establish identity from
`.claude/agent-state/issue-work-orchestrator/registry.json` (the `session-register.sh`
SessionStart hook keys it by `session_id`); resume THIS run's
`runs/<run-id>/resume_state.md` if it shows `Status: IN_PROGRESS`; detect the venv, the
parallel test command and full CI command; apply the one-time concurrency-safe git config
(`gc.auto 0`, `maintenance.auto false`, `gc.autoDetach false`); detect `ISSUE_MECHANISM`
(the wrapper script — its absence is fatal, report and stop); record the in-progress
convention and merge authority; then `git fetch origin --prune --no-auto-gc`.

Set `Status: IN_PROGRESS`, `AWAITING_USER: none`, and **`WORKABLE_ISSUES_REMAIN: yes`** in
this run's `resume_state.md`, and keep that field `yes` for as long as any open,
not-in-progress, unlocked issue exists. This is not bookkeeping: `issue-loop-gate.sh` is a
Stop hook that BLOCKS turn-end while it is `yes`, which is what mechanically enforces
non-negotiable #2. Only DONE (SELECT finds no workable issue) sets it to `no`.

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
  skip/xfail dodges, and the verifier could not refute it. Never weaken a test or a CI
  check to go green.

# Surviving a full context window (no action needed from you)

Compaction is AUTOMATIC in Claude Code — the harness summarizes the conversation as you
approach the context limit and you continue in the same session without interruption.
There is no compaction tool for you to call: `/compact` and `/autocompact` are
user-invoked built-ins, not model-invocable. So do NOT stop, warn, or wait when context
gets tight — just keep working; the summary happens around you.

Your one obligation is to make compaction LOSSLESS, which is exactly what checkpointing
already achieves:

- Checkpoint `runs/<run-id>/resume_state.md` (phase, `CURRENT_ISSUE`, `CURRENT_WORKTREE`,
  `CURRENT_BRANCH`, `CURRENT_PR`, `WORKABLE_ISSUES_REMAIN`) plus your registry heartbeat
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

1. **DONE** — SELECT finds no open, not-in-progress, unlocked issue. Set
   `Status: COMPLETED` and `WORKABLE_ISSUES_REMAIN: no` (this releases the Stop hook), then
   report: issues resolved with PR + evidence links, anything escalated, and confirmation
   this run left no worktree/branch/lock behind and never moved the shared local `main`.
2. **A single batched escalation** when genuinely blocked (an issue too ambiguous to
   derive testable criteria even after research, a PROOF_GATE exhausted after the cap, a
   genuinely ambiguous conflict, an undiagnosable CI failure, a missing wrapper
   subcommand). Post the specifics ON the issue, record `AWAITING_USER: <reason>`, surface
   ONE clarity-first message — then keep working the other issues rather than idling. For
   an ambiguous issue specifically: comment the question on the issue, `issue release <N>`,
   drop the lock, remove the worktree, and move to the next issue.
3. **A fatal environment failure** — no wrapper script / no `ISSUE_MECHANISM`. Report and
   stop.

Anything else — a finished issue, a long fix, a filling context window, an urge to
summarize — is not a stopping point. Select the next issue and keep going.
