# Spec-Driven + Test-Driven Development for Claude Code

This is the automated spec+test workflow — the Claude Code replacement for the manual
Kiro CLI ↔ Kiro IDE loop (prompt-author → generate spec → review → resolve → repeat →
implement). It runs end to end in **one Claude Code session**, driven by a
main-session conductor that delegates to a panel of specialist subagents, converges
the spec to zero blocking defects, then implements test-first and **proves every claim
with captured command/test evidence**.

It generalizes the proven `cv-orchestrator` pattern (main session owns the loop,
delegates to flat subagents via the `Agent` tool, aggregates on-disk findings,
enforces a convergence predicate + iteration cap, never does the protected work
itself). Subagents cannot nest, so **every delegation originates from the conductor**.

## The pipeline

```
claude --agent spec-conductor
  SETUP → PROMPT_AUTHORING (interview)
        → REQUIREMENTS (EARS) → DESIGN (Correctness Properties, Testing Strategy,
                                        threat model, DevOps, AC→validation map)
        → DESIGN_REVIEW_LOOP  (6-reviewer panel ↔ author; exit: 0 A+B + full coverage)
        → TASKS (test-first)  → TASKS_REVIEW_LOOP (light panel; exit: 0 A+B)
        → IMPLEMENT_LOOP (per task: RED → GREEN → commit, paired tests only, conductor
                           captures evidence; no-regress = ONE CI run after the batch's
                           single push)
        → VERIFY (adversarial-verifier verifies & refutes — whole-suite verdict from the
                   CI run; panel re-checks the diff)
        → EVIDENCE_REPORT (property → test → quoted output)
```

You stay out of the loop except: the interview (one question at a time), a single
batched escalation if a review loop hits its cap/oscillates, and the final report.

### The readiness gate (maximally autonomous)
A spec is ready to implement when **both** hold, after ≥1 review cycle:
- **Negative:** combined **A+B findings == 0** across the whole panel, computed
  against the *current* artifact (stale verdicts are rejected). A = execution
  blockers, B = intent deviations/gaps. C (clarifications) and D (nits) never block.
- **Positive:** `test-architect` confirms ≥1 Correctness Property per requirement and
  100% of acceptance criteria map to a test.

This is your "zero defects after at least one adversarial cycle" rule, hardened with a
positive proof-coverage gate so silence ≠ approval.

### Proof with evidence (hard requirement)
The `spec-implementer` writes tests and code but **never certifies its own work**. The
conductor runs the tests and captures complete output to `evidence/`. The
`adversarial-verifier` obtains an independent whole-suite result — normally the CI run
for the pushed SHA, a local run only when none exists — and tries to *refute* every
"it works" claim (kill-the-mutant: revert/stub the impl and require the test to fail;
vacuity/skip/xfail scan; property stress; coverage; red-for-the-right-reason audit).
The final `evidence/REPORT.md` quotes real command output for every passing claim.

## The agents (in `claude-agents/spec-workflow/`)

| Agent | Role | Gate phase |
|---|---|---|
| `spec-conductor` | Main-session orchestrator; owns the loop, delegation, gates, state. | all |
| `spec-author` | Writes/edits requirements, design, tasks. Never grades itself. | gen + revise |
| `spec-researcher` | Read-only codebase/MCP research bursts for the interview. | prompt |
| `test-architect` ★ | Properties + coverage map + AC→test mapping (positive gate). | design, tasks, verify |
| `adversarial-verifier` ★ | Verifies & refutes every claim with evidence (whole-suite verdict from CI). | verify |
| `standards-reviewer` | Conformance to project/coding standards + `.claude/rules/`. | design, verify |
| `best-practice-reviewer` | Alignment with external best practices (MCP/web). | design, verify |
| `security-reviewer` | Threat model + vuln/secret/least-privilege review. | design, verify |
| `devops-iac-reviewer` | CI/CD, IaC least-privilege, observability, rollback. | design, verify |
| `spec-implementer` | Writes tests then code per task, test-first. Never certifies. | implement |

★ = core. Reused from `claude-agents/spec-review/`: `spec-review-agent` (the A/B/C/D
adversarial reviewer; runs in report-only mode under the conductor) and
`spec-prompt-author-agent` (the interview protocol; also backs `/spec-new`).

Phase procedures are authored once in `phases/spec-phase-*.md` and followed by both
the conductor and the slash commands (single source of truth). The shared decision-log
convention is `rules/agent-state-convention.md`. The gates are in `hooks/`.

**Where tests run.** Per task the conductor runs only the PAIRED tests and commits;
commits are cheap (the pre-commit hook is lint + security) and are meant to be frequent.
The whole-suite regression verdict comes from ONE CI run over the finished batch after a
single push. `spec-tdd-gate.sh` therefore gates the PUSH, not the commit — the evidence
requirement used to sit on `git commit`, which made every task cost a full suite run and
drove agents to one giant commit per feature. `rules/ci-owns-the-test-suite.md` is the
rule; the exception is a declared CI outage, where the `pre-push` hook runs the suite
locally with bounded workers.

## The hooks (in `claude-agents/spec-workflow/hooks/`)

| File | Event | Does |
|---|---|---|
| `hook-state-lib.sh` | — (sourced) | The ONE identity/state library. Resolves "which run owns this session" through three rungs, all keyed on the session id: the registry's `state_dir`, `runs/<first-8-of-session-id>/`, then a scan of `runs/*/resume_state.md` for a matching `SESSION_ID:`. **No most-recently-modified rung, ever.** Exposes the `OWNED`/`UNREGISTERED`/`BROKEN` verdicts, plain-`Name: value` field reads (last occurrence wins), bounded block counters, the decision log, and the contract handshake. |
| `CONTRACT_VERSION` | — (data) | One line naming the deployed continuous-work contract. A run acknowledges it by creating `contract-ack-<version>` in its run dir; that is how a LIVE session picks up a newly deployed contract without restarting. |
| `session-register.sh` | SessionStart | Upserts `registry.json` **and SEEDS** `runs/<run-id>/resume_state.md` + `workflow_state.md`, so the gates are reachable from turn one. Pre-acknowledges the current contract. Has a python rung for the registry write because `jq` is absent on some hosts and the previous jq-only upsert wrote no entry at all there. Non-blocking. |
| `continuous-work-reinject.sh` | SessionStart (`compact\|resume\|startup`) | Re-injects the continuous-work contract plus THIS session's recorded place (phase, issue, branch, worktree, PR). When identity is unresolvable it SAYS SO rather than guessing — the predecessor borrowed the most recently touched run directory and handed one session another run's issue number. |
| `issue-loop-gate.sh` | Stop | The PRIMARY brake. Blocks while the run has CLAIMED tracked work (`CURRENT_ISSUE`/`CURRENT_SPEC`/an orchestrator `MODE`) and has NOT affirmatively said it is idle, finished, or escalated. Polarity is inverted on purpose: an UNRECOGNISED `Status` means work in flight, because arming on the single literal `IN_PROGRESS` let `WORKING`, `ACTIVE`, `in progress` and four other plausible words each disable it. `WORKABLE_ISSUES_REMAIN` gates NOTHING: it chooses the refusal's wording and feeds the progress fingerprint. `AWAITING_USER` is checked for SUBSTANCE, not presence — a placeholder, an angle-bracketed token, or a one-word answer is rejected. Fails CLOSED on a `BROKEN` identity, an unrecognised verdict, and a missing or partially-sourced library. |
| `spec-stop-gate.sh` | Stop | The evidence gate. Blocks on a `[x]` task with no capture, a capture that shows no PASSING result (existence was being read as proof — two zero-byte files were accepted as evidence), a failing latest capture, a real skip/xfail counter, an unparseable checked task line, and an ABSENT `tasks.md` **or** `CURRENT_SPEC` at phase IMPLEMENT/VERIFY — both are the mandatory-artifact case the gate exists for. Honours `AWAITING_USER`, resolves a spec inside a per-issue WORKTREE, and matches runner counters rather than bare words so a test NAME containing "skipped" cannot force the agent to edit its own evidence. |
| `spec-tdd-gate.sh` | PreToolUse(Bash) | Bans `git commit --no-verify`/`-n` and `git push --no-verify` outright, and blocks a PUSH during IMPLEMENT/VERIFY when a checked task has no evidence capture, the newest green capture is red or skip-ridden, or CI-OUTAGE MODE is declared with no green full-suite capture. Commits carry no evidence requirement — commit early, commit often (`rules/ci-owns-the-test-suite.md`). Resolves identity through `hook-state-lib.sh`. Its internal ORDER is load-bearing: the bypass bans and the non-push exit run ABOVE any library code and the fail-closed trap is installed only after them, so a broken library can refuse a PUSH but never a commit or an ordinary Bash command. Its failure predicate matches a NON-ZERO count (`[1-9][0-9]* failed`); an earlier escape clause was satisfied by any passing count, so `3 failed, 5 passed` was allowed. |
| `red-for-right-reason.sh` | — | Helper for the RED-phase audit (a test must fail for the reason the task predicts). |
| `MIGRATION.md` | — (docs) | How to deploy all of this to a project whose agents are ALREADY RUNNING: what a live session can and cannot pick up, why the delivery channel is a blocking Stop hook's stderr rather than the tidier JSON `decision` form, and which live sessions the contract handshake does NOT reach. |
| `tests/` | — (suites) | SEVEN self-contained suites, driven against synthetic payloads in a throwaway tree. Most assert EXIT CODES; `test_reinject.sh` asserts on emitted TEXT, because that hook's contract is what it says. `test_gate_overblock.sh` is the counterpart of `test_stop_gates.sh`: it asks whether the gates refuse a turn they should allow, because an over-blocking gate gets DELETED — which removes the fail-open protection too. `test_unpinned_fixes.sh` covers the three fixes a mutation pass found real in the code and guarded by nothing. |

Neither Stop gate reads the harness's `stop_hook_active` field any more: honouring it made a
POLICY gate block at most ONCE per continuation chain, so the agent was nudged once and then
free to stop on unfinished work. Loop safety is each gate's own consecutive-block counter —
`HOOK_BLOCK_CAP`, default 8 to match the ceiling the harness itself enforces, overridable per
project with `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` and validated into `[1, 64]` by
`hook_resolve_block_cap`, so a typo like `abc` or a `0` cannot silently disable the brake.

Reaching the cap allows the stop while stating that the work is not done — and writes a
DURABLE `.capped` marker beside the counter, so it is a one-way stand-down rather than a duty
cycle. That distinction is measured: the cap used to RESET the counter, which produced 8
refusals, one release, then 8 more, forever, while printing a message claiming the session
could not wedge. Two things clear the marker, both through `hook_counter_reset`: a genuine
release (an idle `Status`, a terminal value, a substantive `AWAITING_USER`, or — for the loop
gate — no claimed work), and a change in the gate's own progress FINGERPRINT. The loop gate
fingerprints the state fields it reads; the evidence gate fingerprints the phase, the spec,
and the name and size of every capture under it. So a run that advances every turn never
reaches the cap, and the stand-down message's claim that nothing changed is something the gate
actually measured rather than assumed.

`hooks/tests/test_stop_gates.sh` is the suite that proves this: **24 cases, each asserting an
EXIT CODE** (0 = allow the turn to end, 2 = block), driven against synthetic payloads in a
throwaway project tree. Exit codes are the whole contract, so the assertions are the point —
a gate that "looks right" but returns 0 where it must return 2 is exactly the defect class
these gates were found to have. It covers the identity verdicts (including state written
under an agent-invented directory name, recovered via `SESSION_ID`), the block cap, the
evidence and vacuous-green rules, the absent-`tasks.md` block, and fail-closed behaviour for
both gates against a missing and a partially-sourced library. What it CANNOT prove on its own is
which gate fired: several of its cases seed a state the primary brake also blocks, so an observed
exit 2 is consistent with more than one cause. That gap is what `test_unpinned_fixes.sh` closes
below, by asserting on the refusal TEXT.

`hooks/tests/test_hook_state_lib.sh` (**64 cases**) tests the library by calling its functions
DIRECTLY, and it is separate from the gate suite for a reason worth internalising: an end-to-end
suite can pass over a broken unit. `hook_resolve_run_dir` contained
`local base="$1" … orch="$base/…"`, and bash expands every assignment word in one `local` BEFORE
creating the locals — so `$base` resolved to the CALLER's global of that name. Both gates hold a
global called `base`, so all 24 gate assertions passed while the function, called from anywhere
else, aborted; and inside a `$(…)` that abort yields an empty verdict, which the gates read as
"nothing to guard". **A test that reaches the unit only through one caller measures the pair, not
the unit.** This suite therefore defines no global named `base`, `session`, `orch`, `declared` or
`run_dir`. It also pins the registered-but-unresolvable cases to `BROKEN` rather than
`UNREGISTERED` (an entry with an absent, empty, absolute or path-traversing `state_dir`, and a
malformed registry), the counter's clamping and base-10 handling, and the field-parsing contract.

`hooks/tests/test_tdd_gate.sh` (**42 cases**) covers the push gate in BOTH directions, which are
asymmetric: it must never refuse a non-push command — commits included, which carry no evidence
requirement — even when its own library is broken, and it must always refuse a push it cannot
justify. It pins the measured fail-open where a capture reading `3 failed, 5 passed` was ALLOWED
because the old escape clause matched "5 passed", while `0 failed, 5 passed` must still pass, plus
the CI-outage rung (a push with no CI run behind it owes a green full-suite capture).

`hooks/tests/test_reinject.sh` covers the SessionStart re-injector with 23 substring
assertions over its emitted text, because that hook's contract is what it SAYS rather than an
exit code: that the continuous-work contract is always injected; that an `OWNED` session is
told its OWN issue and branch; that a `BROKEN` one is named the exact path to create, warned
the next gate will refuse, and told not to invent a label; that an unresolvable identity says
so plainly instead of guessing; and that a missing library still exits 0 so startup is never
broken. Seven of them are NEGATIVE assertions against a planted, more-recently-touched
sibling run — that the output leaks none of its issue, branch or run dir, on every path
including recovery and the no-session-id path — because leaking exactly that was the original
defect, and only a negative assertion can prove a fallback is gone rather than merely unused.

`hooks/tests/test_unpinned_fixes.sh` (**32 cases**) exists because a mutation pass over the
shipped hooks found three fixes that were REAL IN THE CODE and guarded by nothing — every other
suite stayed green while each was reverted — and an unpinned fix is one that regresses silently,
which is precisely how the original incident happened. It pins those three, plus the cross-gate
terminal-value agreement this project had to adjudicate twice:

- **The contract handshake's BLOCK direction**, identified by the refusal TEXT rather than the
  exit code. Replacing the handshake's condition with `if false` left the gate suite reporting
  24 passed, because the state that case seeds is one the primary brake blocks as well — so exit
  2 proved nothing about the handshake. These cases assert that the refusal names the contract,
  the deployed version and the ack file to create, and is NOT the brake's message; then they ack
  and assert the SAME state still blocks, now with the brake's wording. That pair is what makes
  the two refusals distinguishable at all.
- **Defect class 10 — a capture must SHOW a pass, not merely exist.** A zero-byte capture and a
  prose-only one must block; a real `5 passed` capture must allow.
- **Per-task failure scanning, proven MTIME-INDEPENDENT.** An older task's capture reading
  `3 failed, 5 passed` must block even when a newer task's capture is clean, and `touch`ing the
  older file — same bytes — must not change the verdict. The mirror skip counter, a
  both-captures-clean non-vacuity control, and a `#`-comment mentioning failures are all covered.
- **Cross-gate agreement on terminal values.** `Status: COMPLETED (was IN_PROGRESS)` must NOT
  release and a bare `COMPLETED` must, asserted on BOTH gates for the same two strings — the
  evidence gate used a prefix-matching raw grep and released on the narrative form while the loop
  gate refused it.

```bash
bash claude-agents/spec-workflow/hooks/tests/test_crlf_hygiene.sh    # 11 passed, 0 failed
bash claude-agents/spec-workflow/hooks/tests/test_hook_state_lib.sh  # 64 passed, 0 failed
bash claude-agents/spec-workflow/hooks/tests/test_tdd_gate.sh        # 42 passed, 0 failed
bash claude-agents/spec-workflow/hooks/tests/test_reinject.sh        # 23 passed, 0 failed
bash claude-agents/spec-workflow/hooks/tests/test_stop_gates.sh      # 24 passed, 0 failed
bash claude-agents/spec-workflow/hooks/tests/test_gate_overblock.sh  # 50 passed, 0 failed
bash claude-agents/spec-workflow/hooks/tests/test_unpinned_fixes.sh  # 32 passed, 0 failed
```

246 assertions in total. Take each number from the `TOTAL:` line the suite itself prints rather
than from this file — a count quoted in prose and never re-measured is how the library suite came
to be described as "30 cases" in one paragraph while the runnable block above said 64.

All seven are read-only with respect to the repository — all state lives in a temp tree they
create and destroy — so they are safe to run in any clone. Run them after any edit to a hook or
to `hook-state-lib.sh`: a gate regression is otherwise SILENT, which is the property that let the
original defect persist for 189 sessions. They install alongside the hooks, but only because the
recipe below copies `tests/` explicitly — the `hooks/*.sh` glob does not descend into it.

## Slash commands (in `claude-commands/`)

For running one phase on demand instead of the whole pipeline:

| Command | Does |
|---|---|
| `/spec-new "<idea>"` | Interview + author `prompt.md` for a new feature/bugfix. |
| `/spec-review [slug]` | One review-panel pass; reports combined A+B + coverage. |
| `/spec-tasks [slug]` | Generate/regenerate `tasks.md` (test-first) + light review. |
| `/spec-implement [slug]` | TDD implement + adversarial verify + evidence report. |

## Install (per project)

```bash
mkdir -p .claude/agents .claude/commands .claude/rules \
         .claude/hooks .claude/specs/_workflow/phases

# agents
cp claude-agents/spec-workflow/spec-conductor.md          .claude/agents/
cp claude-agents/spec-workflow/spec-author.md             .claude/agents/
cp claude-agents/spec-workflow/spec-researcher.md         .claude/agents/
cp claude-agents/spec-workflow/test-architect.md          .claude/agents/
cp claude-agents/spec-workflow/adversarial-verifier.md    .claude/agents/
cp claude-agents/spec-workflow/standards-reviewer.md      .claude/agents/
cp claude-agents/spec-workflow/best-practice-reviewer.md  .claude/agents/
cp claude-agents/spec-workflow/security-reviewer.md       .claude/agents/
cp claude-agents/spec-workflow/devops-iac-reviewer.md     .claude/agents/
cp claude-agents/spec-workflow/spec-implementer.md        .claude/agents/
cp claude-agents/spec-review/spec-review-agent.md         .claude/agents/
cp claude-agents/spec-review/spec-prompt-author-agent.md  .claude/agents/

# commands, phase fragments, shared rule, hooks
cp claude-commands/spec-*.md                              .claude/commands/
cp claude-agents/spec-workflow/phases/*.md                .claude/specs/_workflow/phases/
cp claude-agents/spec-workflow/rules/*.md                 .claude/rules/   # agent-state-convention,
                                                                         # no-ai-attribution, keep-git-clean,
                                                                         # issue-tracking, per-worktree-venv,
                                                                         # issue-filing-discipline,
                                                                         # continuous-work,
                                                                         # ci-owns-the-test-suite
cp claude-agents/spec-workflow/hooks/*.sh                 .claude/hooks/ && chmod +x .claude/hooks/*.sh
cp claude-agents/spec-workflow/hooks/CONTRACT_VERSION     .claude/hooks/
cp claude-agents/spec-workflow/hooks/MIGRATION.md         .claude/hooks/
mkdir -p .claude/hooks/tests
cp claude-agents/spec-workflow/hooks/tests/*.sh           .claude/hooks/tests/ \
  && chmod +x .claude/hooks/tests/*.sh
```

Three of those lines exist because the `hooks/*.sh` glob does not reach what they copy, and each
omission is silent:

- **`CONTRACT_VERSION`** is data, not a script, and `hook-state-lib.sh` reads it from
  `.claude/hooks/CONTRACT_VERSION` by that exact path. Omit it and the version resolves to
  `unversioned` — the handshake still functions, but it can no longer distinguish one deployed
  contract from the next.
- **`tests/`** is a subdirectory, so the glob does not descend into it. Omit it and step 3 of
  `MIGRATION.md` §7 has nothing to run, which is the step that tells you whether the deployment
  is armed or inert.
- **`MIGRATION.md`** is what a later session reads to find out what a LIVE agent can and cannot
  pick up, and how to recover a session the old registrar never registered. It is documentation
  the deployed tree needs, not a source-repo artifact.

Then register the hooks in `.claude/settings.json`:

| Event | Hook | Note |
|---|---|---|
| SessionStart | `session-register.sh` | must run — it seeds the state the gates read |
| SessionStart | `scoped-temp-init.sh` | creates `tmp/os-temp` so the scoped `TMPDIR` is usable |
| SessionStart (`compact\|resume\|startup`) | `continuous-work-reinject.sh` | |
| Stop | `issue-loop-gate.sh` | the primary brake |
| Stop | `spec-stop-gate.sh` | the evidence gate |
| PreToolUse(Bash) | `spec-tdd-gate.sh` | the push/evidence gate (commits carry no evidence requirement) |
| PreToolUse(Bash) | `claim-before-worktree.sh` | blocks a per-issue worktree until the claim is visible on the remote |
| PreToolUse(Bash) | `issue-filing-gate.sh` | blocks an issue-create call whose body carries no filing rationale |

Registering the Stop gates without `session-register.sh` is the configuration that produced
the measured failure: with nothing seeding `runs/<run-id>/`, both gates resolved no state and
exited 0 on every turn-end for 189 sessions. Add to root `CLAUDE.md`:
"All agents follow `.claude/rules/agent-state-convention.md` for state and decision
logging, `.claude/rules/no-ai-attribution.md` for descriptive names with no
Claude/AI attribution in commits, PRs, issues, branches, or worktrees,
`.claude/rules/issue-filing-discipline.md` for when an issue may be filed at all
(observed defects only, fix-first, zero filings is a valid outcome), and
`.claude/rules/ci-owns-the-test-suite.md` for where tests run (affected tests locally,
full suite in CI; commit often, push once; fix every failure a CI run reports in one
pass)."
`ClaudeCodeSetupPrompt.txt` (Part 12) does all of this for you.

## Durable state (preserved for later agents)

```
.claude/specs/<feature>/
  prompt.md  prompt-discussion.md  qa_log.md
  requirements.md (or bugfix.md)  design.md  tasks.md  open-questions.md
  review/{spec,test,standards,best-practice,security,devops}/iteration-NN.md
  review/review-latest.md          # conductor's aggregated A+B union
  decisions/decision-log.md        # append-only DL-NNN ledger (ALL agents write here)
  evidence/{red,green,regress,verify}/...   # captured command output
  evidence/REPORT.md               # the proof chain
.claude/agent-state/<agent>/       # per-agent resume_state.md + logs (gitignored)
.claude/agent-state/spec-conductor/workflow_state.md   # master phase machine (single-run layout)
.claude/agent-state/issue-work-orchestrator/
  registry.json                    # session_id -> run identity (written by session-register.sh)
  runs/<run-id>/                   # ONE run's state; run-id comes from the registry VERBATIM
    resume_state.md  workflow_state.md  contract-ack-<version>
  .hook-decisions/<date>.log       # every hook decision — read this to see if the gates are live
```

Two properties of that layout are load-bearing rather than cosmetic, and
`rules/agent-state-convention.md` §1b–§1f is the authority on both: the run-id is taken from
the registry **verbatim** (an agent-authored label puts state where no hook reads it), and
hooks read the **LAST** occurrence of a plain `Name: value` line — so a field is corrected by
appending a block at the end of the file, never by editing an earlier one, and a bold-styled
field is read by no hook at all.

The `decisions/decision-log.md` (`DL-NNN` entries: Decision / Driver / Alternatives /
Evidence / Supersedes / Artifacts) is the cross-agent memory: every agent — these new
ones AND the ported ones (dead-code, doc-review, issue-*, product-management, cv/*) —
appends to it, so decisions and the discussion behind them survive across agents and
sessions. See `rules/agent-state-convention.md`.

## Coexistence with Kiro

Specs live under `.claude/specs/` and never touch `.kiro/`. You can keep using Kiro
spec mode on the same project; the two trees are independent. The artifact format
mirrors Kiro's (EARS requirements, design with properties, checkbox tasks) so the
mental model is identical.

## Bugfix vs feature

The conductor detects FEATURE vs BUGFIX from your kickoff. A bugfix produces
`bugfix.md` (Current / Expected / **Unchanged-behavior regression-prevention** in
EARS) instead of `requirements.md`, and the test-architect requires a regression test
for every "SHALL CONTINUE TO" clause — so a fix cannot silently break existing
behavior.
