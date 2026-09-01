# Auto-Work — autonomous open-issue backlog run (Kiro)

Kiro counterpart of the Claude Code `/auto-work` command
(`claude-commands/auto-work.md`). Installed to `.kiro/prompts/auto-work.md` and invoked in
Kiro CLI as **`@auto-work`** (Kiro's file-based prompts are invoked with `@name`, not
`/name`, and take no arguments). The Kiro IDE reaches the same body through the
`auto-work.kiro.hook` `userTriggered` hook, which tells the agent to read this file.

Run it while the `issue-work-orchestrator` agent is active (`/agents` picker in
`kiro-cli`, or `kiro-cli chat --agent issue-work-orchestrator`).

---

Work this project's open-issue backlog AUTONOMOUSLY, end to end, following
`.kiro/agents/issue-work-orchestrator.md` exactly. You play the orchestrator in this
session; you never spawn a nested orchestrator. Respect the four-subagent cap — run the
six-reviewer design panel in waves of at most four.

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
   whole backlog by invoking this prompt. (A NEW instruction the user actually types
   mid-run still takes precedence; a genuine escalation and a branch-protection approval
   wait are the only self-initiated pauses, and both are recorded, not conversational.)
3. **CLAIM EVERY ISSUE THE MOMENT YOU PICK IT**, before you fetch, branch, or write
   anything: take the local `.locks/issue-<N>.lock` (atomic `mkdir`), then claim on the
   tracker with the fail-closed `issue start <N>` (GitHub wrapper: `start-issue <N>`),
   which adds the in-progress label ADDITIVELY, assigns the working identity, re-reads to
   verify, and exits non-zero if the claim did not land. Other agents are working this
   same backlog in parallel — an unclaimed issue is duplicated work. Never hand-roll the
   claim via `update-issue --labels` (whole-set replace; it silently drops other labels).
   If the claim fails, release the lock and select the next candidate. The
   `kiro-claim-before-worktree.sh` `preToolUse` hook blocks worktree creation for an
   unclaimed issue, so a skipped claim is caught mechanically.
4. **ALWAYS WORK ON THE LATEST CODE.** Other agents are merging while you work. Fetch and
   integrate at all six Remote Sync points: Discovery, before each SELECT, after creating
   the worktree, periodically during long fixes, before opening the PR, and after each
   merge. `git fetch origin --prune --no-auto-gc`, rebase YOUR branch onto
   `origin/<main>`, and delegate ANY conflict to `code-merge-reviewer` — never resolve one
   yourself, never `-X ours/theirs`, never `checkout --ours/--theirs`. Re-run the AFFECTED
   tests after every integration (the whole-suite check is the CI run after the push —
   steering `ci-owns-the-test-suite.md`). Re-retrieve the issue list FRESH every iteration; never reuse
   a previous snapshot (issues get closed or claimed while you work).
5. **ONE GIT WORKTREE PER ISSUE, AND LEAVE GIT CLEAN.** Work in
   `.kiro/worktrees/issue-<N>/` cut off freshly-fetched `origin/<main>` with an explicit
   descriptive branch (`-b issue-<N>-<slug>`). Stay MAIN-CHECKOUT-FREE: never
   `git checkout main`, never fast-forward the shared local `main` — sibling runs and the
   developer depend on it. Per the `keep-git-clean` steering file, commit
   source/config/docs/tests, never generated or temp files, and tear the worktree + branch
   + lock down after every merge so nothing stale survives.

# Setup, then the loop

Run Discovery D0–D5 from the agent definition: establish identity from
`.kiro/agent-state/issue-work-orchestrator/registry.json` (the `kiro-session-register.sh`
hook keys it by session); resume THIS run's `runs/<run-id>/resume_state.md` if it shows
`Status: IN_PROGRESS`; detect the venv, the test command
(`python scripts/run_tests.py` — bounded workers, no fail-fast; never `pytest -n auto`)
and the local full-check command (`python scripts/run_checks.py`, the same one CI runs);
apply the one-time concurrency-safe git config (`gc.auto 0`, `maintenance.auto false`,
`gc.autoDetach false`); detect `ISSUE_MECHANISM` (the wrapper script — its absence is
fatal, report and stop); record the in-progress convention and merge authority; then
`git fetch origin --prune --no-auto-gc`.

Set `Status: IN_PROGRESS`, `AWAITING_USER: none`, and **`WORKABLE_ISSUES_REMAIN: yes`** in
this run's `resume_state.md`, and keep that field `yes` for as long as any open,
not-in-progress, unlocked issue exists. This is not bookkeeping: `kiro-loop-gate.sh` is the
Kiro CLI `stop` hook that BLOCKS turn-end while it is `yes`, which is what mechanically
enforces non-negotiable #2. Only DONE (SELECT finds no workable issue) sets it to `no`.
Note the gate has a deliberate loop-safety cap — after `LOOP_BLOCK_CAP` CONSECUTIVE blocks
it allows the stop so a session cannot wedge, and the run must be re-launched to continue.
Do not treat that cap as a licence to idle: it exists for a wedged agent, and the only way
you should ever reach it is if you keep trying to stop when you should be working.

Then run the outer loop until DONE: LOAD_ISSUES → SELECT (+ lock + claim) → PREPARE
(fetch, worktree, per-worktree venv if this project executes code from worktrees) →
CLASSIFY (Type1/Type2) → FIX → PROOF_GATE → DOCUMENT → PR → MERGE_CLEANUP → RESOLVE →
refresh → LOAD_ISSUES.

# Research, and the spec process

- **Research before you guess.** For an unfamiliar API, service limit, framework
  behavior, or error, consult the project's MCP documentation servers first (they are
  auto-approved per server in `.kiro/settings/mcp.json`), then the project's own docs,
  then web search/fetch. Delegate substantial investigation to the `spec-researcher`
  subagent so the reading cost lands in its context, not yours. The `no-guessing` steering
  rule applies throughout: every claim cites evidence, and you read COMPLETE command
  output (`no-output-shortening`) — never `tail`/`head`/`Select-Object`.
- **Issues that need a spec get the full spec process.** Type2 (anything not provably
  ≤3 non-test files with a high-confidence root cause, no new pattern/dependency/API or
  IaC change — when in doubt, Type2): `spec-author` drives REQUIREMENTS → DESIGN, then the
  DESIGN_REVIEW_LOOP with the full six-reviewer panel (`spec-review-agent`,
  `standards-reviewer`, `best-practice-reviewer`, `security-reviewer`,
  `devops-iac-reviewer`, `test-architect`) **in waves of at most four**, exiting only when
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
  a test reproducing the issue's reported symptom passes, the full suite is green — cited
  from the CI run for the head SHA rather than a local full-suite run — with no
  skip/xfail dodges, and the verifier could not refute it. Never weaken a test or a CI
  check to go green.

# Surviving a full context window (no action needed from you)

Compaction is AUTOMATIC in Kiro — as the session approaches the model's context limit,
older history is replaced by a structured summary (goals, decisions, progress, next steps)
while recent messages stay verbatim, and you continue with no interruption. In the IDE
there is no manual trigger at all; in the CLI `/compact` is a USER command, not something
you invoke. So do NOT stop, warn, or wait when context gets tight — just keep working; the
summary happens around you.

Your one obligation is to make compaction LOSSLESS, which is exactly what checkpointing
already achieves:

- Checkpoint `runs/<run-id>/resume_state.md` (phase, `CURRENT_ISSUE`, `CURRENT_WORKTREE`,
  `CURRENT_BRANCH`, `CURRENT_PR`, `WORKABLE_ISSUES_REMAIN`) plus your registry heartbeat
  after EVERY step — never only in your head. On-disk state is what survives.
- Keep issue N itself updated live per the `issue-tracking` steering rule (progress
  comments, checklist ticks, Q&A on the issue), so the work is reconstructible from the
  issue alone.
- Immediately after a compaction, re-read this run's `resume_state.md`,
  `workflow_state.md`, and the active spec's decision log before acting, and re-open any
  file you still need — tool-call details and earlier snippets are the first things
  compaction compresses away. `inclusion: always` steering files remain in effect;
  `fileMatch` steering reloads when you next touch a matching file. Then resume the
  recorded phase; do not restart the issue or the backlog.
- Compaction history is not recoverable within the session, so anything that must outlive
  it belongs on disk (state files, evidence) or on the issue — not in the conversation.

# When you may stop (the only three exits)

1. **DONE** — SELECT finds no open, not-in-progress, unlocked issue. Set
   `Status: COMPLETED` and `WORKABLE_ISSUES_REMAIN: no` (this releases the stop gate), then
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

Never modify anything under `.claude/`.
