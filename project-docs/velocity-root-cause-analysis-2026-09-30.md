# Development velocity: root-cause analysis (2026-09-30)

Scope: AWSBedrockGateway (BG), Insights Analyzer (IA) and chess, all running the CodingProjectSetupPrompt framework. Evidence: the Claude Code session transcripts of the three projects (17 GB, 226 sessions, 1.53 million model calls, 629 billion tokens, June to September 2026), the `.claude/specs/` trees, the agent-state directories, the GitLab and GitHub trackers via the project wrappers, git history, and the framework sources under `claude-agents/`, `claude-commands/` and the setup prompt. Raw analysis output is in `tmp/velocity-analysis/` (`analyze_transcripts.py`, `parallel_and_subagents.py`, `bg.json`, `chess.json`, `ia.json`, `par_*.txt`).

## 1. Headline measurements

| Measure | BG | IA | chess |
|---|---|---|---|
| Sessions analysed | 83 | 84 | 59 |
| Model calls | 494,656 | 489,171 | 546,435 |
| Total tokens | 200 B | 201 B | 227 B |
| of which cache reads | 175 B (87%) | 187 B (93%) | 216 B (95%) |
| of which output | 0.41 B (0.2%) | 0.49 B (0.2%) | 0.59 B (0.3%) |
| Average context per model call | 404k tokens | 410k tokens | 415k tokens |
| Peak week (W39, Sep 21-27) | 62 B | 83 B | 107 B |
| Longest single `/work-issue` session | 171 h (issues 710, 711, 712, still open) | 140 h (509) | 145 h (506) |
| Subagent dispatches | 1,073 | 1,322 | 2,604 |
| Dispatched in parallel with another | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| Agent time spent in `sleep` polling | 913 h | 670 h | 264 h |
| Assistant messages mentioning `mwinit` | 219 | 194 | 2 |
| Always-on instruction footprint (CLAUDE.md + unscoped rules) | 428 KB (~107k tokens) | 89 KB (~22k) | 123 KB (~31k) |
| Mandatory pre-work reading (`forLLMConsumption.md` + `lessons-learned.md` + `ProjectDesign.md`) | 1.27 MB (~320k tokens) | 1.78 MB (~445k tokens) | 346 KB (~86k) |
| `docs/findings-ledger.md` | 886 KB (from 2 KB on Aug 24) | 939 KB | 98 KB |
| `docs/lessons-learned.md` | 639 KB (from 328 B on Jun 10) | 961 KB | 227 KB |
| Specs whose `design.md` exceeds 200 KB | 56 of 228 | 97 of 332 | 4 of 80 |
| Specs needing more than 8 review iterations | 10 | 8 | 1 |
| BG specs about process machinery (gates, hooks, wrappers, citations, worktrees) | 89 of 278 (32%) | — | — |

Token volume rose roughly tenfold between August and late September in all three projects while the commit stream became dominated by bookkeeping: of the last 3,000 BG commits, 878 mention evidence, record, ledger, citation, re-pin, bank or census; 491 are `feat` or `fix`.

## 2. Case study: issue 714 (change the default Opus pin from Opus 5 to Opus 5.5)

The ask is one constant in `cdk/app.py`, plus the snapshot and price rows that name the family.

| Fact | Value |
|---|---|
| Filed | 2026-09-23 10:07 (by the issue-intake agent, on the operator's request) |
| Issue body | Already a mini-spec: blast radius, four risk sections, eleven open questions, CloudWatch Logs Insights measurements |
| Spec branch | `gitlab/wip/issue-714-opus-5-5-default`, 310 files, 9.56 MB |
| `design.md` | 1,479,119 bytes, 13,402 lines, 284 headings, 35 Correctness Properties |
| `requirements.md` | 448,651 bytes, 14 requirements, 268 SHALL clauses, 138 acceptance criteria |
| `tasks.md` | 421,584 bytes |
| Decision log | 150 DL entries |
| Design review iterations | 16 (cap is 8); tasks review iterations 6 |
| Combined A+B per iteration | 20, 13, 14, 12, 8, 6, 1, 3, 1, 1, 2, 0, 2, 3, 2, 1 |
| Review files | 96 lane files of 30 to 74 KB each, plus 22 aggregates |
| Wall clock per review-and-revise cycle | 8 to 10 hours (from commit timestamps) |
| Status on 2026-09-30 | No production code written; the spec is still in design review |

What the requirements grew into: R5 to R9 add a request-shape reconciliation subsystem for two shapes Opus 5.5 rejects, R9 adds CloudWatch telemetry for it, R13 adds a post-merge live rollout protocol with a "Run Record", "Pin Write Landing Bound", a "Deployed-Code Check", a write-back recovery route (E-R), deploy locks and merge freezes. Iteration 16's single blocking finding is about precedence between three waiting rules in that rollout protocol. None of the last eight iterations' findings concern the default value.

The cap of 8 was reached at iteration 8; the conductor escalated, and the operator's recorded answer (`open-questions.md` Q-CAP-1, DL-030, DL-038) was to run full rounds until the gate passes. The design gate then reached zero at iteration 12 but the tasks review had 2 findings; revising for those reopened the design at 2, 3, 2, 1.

Issue 708 shows the same shape on an even smaller ask (a `.cmd` wrapper losing its exit code through a bare `exit /b`): 100 KB requirements, 202 KB design, 39 tasks, 165 evidence files, 31 hours from filing to merge. Issue 711 (gating one beta header) has a 1.66 MB, 20,886-line design, 84 review files, 276 evidence files, and after 171 hours of session time is still open. Issue 712 (cross-platform helper sign-in) has a 489 KB design and a 318 KB `tasks.md` with 96 tasks, 55 of them done after 171 hours, each task a separate sequential implementer call. Issue 724 has a 206 KB requirements document and a 345 KB design before a single task exists.

## 3. Root causes, ranked by contribution

### RC1. The review gate is unbounded and rewards scope growth

Mechanism. `spec-phase-review.md` exits only when six adversarial reviewers report combined A+B == 0 against the current artefacts and the test-architect reports 100% acceptance-criteria coverage with at least one Hypothesis property per requirement. A "B" finding is defined as any "intent deviation / gap". Every gap is closed by adding requirements, properties, mapping rows and mechanism, which enlarges the surface the next iteration reviews. The document grows until no reviewer can read it in one pass (12,655 lines against a 2,000-line Read window), so each lane samples a different part and finds a different gap. The A+B sequence for 714 (20, 13, 14, 12, 8, 6, 1, 3, 1, 1, 2, 0, 2, 3, 2, 1) is the signature of a loop whose findings are generated by its own revisions.

Aggravators in the framework text: `spec-author.md` makes Security Considerations, DevOps & Operability, a threat model and a Hypothesis sketch per property mandatory for every design regardless of change size; `test-architect.md` treats a requirement without a property as an A blocker; reviewers are told to be adversarial and are never told what the ask was worth. The cap-8 escalation offers "continue or narrow", never "ship the reviewed subset". Across BG, 10 specs exceeded the cap; IA has one spec at 27 iterations.

Framework files: `claude-agents/spec-workflow/phases/spec-phase-review.md`, `spec-author.md`, `test-architect.md`, `spec-review-agent.md`.

### RC2. Every change is classified as a full-spec change

Mechanism. `issue-work-orchestrator.md` CLASSIFY makes Type1 (lightweight) require all of: at most 3 non-test files, no IaC change to deployed resources, no new dependency, no public interface change, and "when ambiguous, default to Type2". A default value in `cdk/app.py` is an IaC change and touches a constant, a snapshot JSON, a price JSON, docs and pinned tests, so it is Type2 by construction. Type2 means the full six-reviewer pipeline, tasks review, per-task TDD with captured evidence, adversarial verification, and a deployed E2E.

The issue-intake agent compounds this: it is instructed to research blast radius and risks before filing, so the issue for a constant change arrives with four risk sections and eleven open questions, and `spec-author` faithfully turns every "TO VERIFY" into a requirement.

Framework files: `issue-work-orchestrator.md` (CLASSIFY), `claude-commands/work-issue.md` step 4, `issue-intake-agent.md`.

### RC3. Execution is strictly sequential

Mechanism. Measured over 4,999 subagent dispatches in the three projects, zero were issued alongside another. The framework says the conductor "invokes one call at a time" and only "MAY" parallelise the panel; the 2026-08-29 decision-log collision (a parallel test-architect destroyed seven DL entries) led to the "One Authoritative Writer" rule and an explicit warning against parallel panels, after which parallel dispatch never happened. Implementation is defined as "per task, in tasks.md order", one `spec-implementer` call per task, with the conductor running tests and committing between tasks.

Cost. Per subagent run (BG averages): reviewers 55 to 66 minutes each, spec-author 98 minutes, spec-implementer 63 minutes, adversarial-verifier 116 minutes. IA reviewers average 150 to 170 minutes each. One design-review cycle is therefore about 7.5 hours in BG and about 17 hours in IA before a single line of code; a 39-task implementation is 39 sequential implementer calls plus 39 test-and-commit rounds. CLAUDE.md additionally forbids two worktrees running suites at once, so parallel runs on one host serialise on the test suite too.

Framework files: `spec-conductor.md`, `spec-phase-implement.md`, `spec-implementer.md`, `rules/agent-state-convention.md` §2a, `rules/ci-owns-the-test-suite.md`.

### RC4. Context bloat: 400k tokens per call, most of it re-read process text

Mechanism. Three layers stack on every call:

- Always-on instructions. BG's CLAUDE.md is 21 KB of incident narrative and its unscoped rules total 407 KB (no-guessing.md 85 KB with an embedded violation log, remote-ci-must-pass.md 80 KB, use-git-wrapper-scripts.md 46 KB, no-silent-resource-removal.md 31 KB, agent-state-convention.md 29 KB). The framework's canonical versions of the same rules total about 130 KB; the projects tripled them by appending every incident.
- Mandatory pre-work reading. `pre-work.md` and `use-lessons-learned.md` require reading `forLLMConsumption.md`, `ProjectDesign.md` and `lessons-learned.md` before any task. In BG that is 1.27 MB (about 320k tokens); in IA 1.78 MB (about 445k tokens), more than a context window. Both files are append-only by rule, updated by `post-activity.md` step 3 on every change, and have no pruning mechanism. `findings-ledger.md` (886 KB in BG, 939 KB in IA) is the routing target for everything not filed as an issue and is likewise append-only.
- The spec artefacts themselves. `design.md` is the single most-read file in every project (11.5k to 12.7k Read calls each), and 56 of BG's 228 designs and 97 of IA's 332 exceed 200 KB.

Effect. 97% of all tokens are cache reads of context; output is 0.2%. A 400k-token context also degrades attention, which is why reviewers cite line numbers that a later edit invalidates, which is why BG grew a 72 KB `check_spec_citations.py`, a rule that spec edits be line-count-neutral, and 146 commits whose subject is re-pinning citations.

Framework files: `rules/pre-work.md`, `rules/use-lessons-learned.md`, `rules/post-activity.md`, `rules/no-guessing.md` (violation log inside the rule), `rules/issue-filing-discipline.md` (ledger routing), setup prompt Part 9.

### RC5. The continuous-work mandate and Stop gates remove every natural stopping point

Mechanism. `continuous-work.md` (framework commit d5c595c, 2026-08-24) forbids ending a turn unless the task is finished or a Proven Exception applies, declares any summary a "disguised check-in", and is enforced by `issue-loop-gate.sh` and `spec-stop-gate.sh` (framework commit ec1604a, 2026-08-30), each of which refuses turn-end up to 8 consecutive times. All three projects installed this on 2026-09-06 to 09-08 (chess PR 324, IA branch wire-stop-gates-20260906, BG worktree framework-update-20260907). Token consumption per week rose from 3 to 7 B (BG W36-W37) to 24 and 62 B (W38-W39); chess from 5 B (W36) to 107 B (W39); IA from 9 B (W37) to 83 B (W39).

In the 711 session the Stop hook fired 103 times; in 693, 46 times. When an agent that believes it is done is refused, it does not find missing product work; it finds more spec, evidence, ledger and citation work, because that is what the rules define as unfinished. Combined with the `/work-issue` goal hook ("implement and close issue N with green CI and all tasks completed"), a run cannot end until a 33-task list is fully green, so a stuck E2E keeps the session alive for a week.

Framework files: `rules/continuous-work.md`, `hooks/spec-stop-gate.sh`, `hooks/issue-loop-gate.sh`, `hooks/continuous-work-reinject.sh`, `claude-commands/work-issue.md`.

### RC6. Wall-clock is lost to polling, credential expiry and shared-environment locks

Mechanism.

- CI. The BG pipeline's test job alone takes 46 to 48 minutes; a full pipeline with deploy-dev and smoke is about an hour. IA runs 22 jobs of 5 to 20 minutes. The workflow requires one push per batch, then a post-merge trunk pipeline, then a deploy, then a smoke gate. Agents wait with `sleep` in a tool call: 7,785 sleep calls totalling 913 hours in BG, 6,076 totalling 670 hours in IA, 3,315 totalling 264 hours in chess. Every wake-up is a full 400k-token model call.
- Credentials. The Midway SSH certificate is valid for 12 hours. Any push after expiry fails, the run records `AWAITING_USER: ... please run mwinit` and stops; the dominant escalation reason in BG and IA agent-state is exactly this. A 170-hour run crosses about 14 expiries. This is the "login loop" the operator experiences.
- Shared dev. A run performing its live E2E takes a deploy lock and posts a merge freeze on `main`; other runs then record "implementation is blocked because MR !118 cannot be merged ... waiting on the operator to supply the T41 admin-auth-options response body". One manual E2E step serialises every concurrent run, and the lock is advisory, so a sibling deploy invalidated the E2E and forced a re-capture.

Framework and project files: `rules/ci-owns-the-test-suite.md`, `rules/remote-ci-must-pass.md`, `rules/always-test-e2e.md`, `rules/deploy-latest-code-only.md`, `scripts/gitlab_wrapper.py`.

### RC7. The mandatory deployed E2E manufactures manual testing

Mechanism. `always-test-e2e.md` requires every spec or bugfix to end with a deploy-and-verify of the running system, and the evidence mandate forbids claiming success without captured output. For any change that touches sign-in, a browser session or a desktop client, the only capture the agent can obtain is the operator's: issue 719 asks the operator to open the console, sign in as admin, copy a JSON response from the network pane and save it to a path (T41), then perform a fresh Claude Desktop sign-in (T43), then re-capture after a wrong diagnosis. The agent recommends "I sign in by hand (Recommended)" because the rule leaves no automatable alternative and the design offers none. Issue 714's R13 alone mentions the operator 156 times.

Framework files: `rules/always-test-e2e.md`, `spec-phase-implement.md` (Evidence Mandate), `rules/no-guessing.md`.

### RC8. Process machinery grows itself and competes with product work

Mechanism. 89 of BG's 278 specs (32%) are about gates, hooks, wrappers, citations, worktrees, locks or CI machinery. The machinery files are now the largest code in the repository: `github_wrapper.py` 244 KB, `gitlab_wrapper.py` 206 KB, `claim_ownership.py` 200 KB, `check_spec_citations.py` 72 KB, `git_repo_invariants.py` 69 KB, `hook-state-lib.sh` 54 KB. Every incident adds a rule paragraph, a guard, a test of the guard and a ledger row. The BG team diagnosed this itself on 2026-08-17 (`docs/backlog-self-amplification.md`: five loops L1 to L5, product converges but machinery does not) and applied containment C2 and C3 (thresholds instead of quotas; a findings ledger). The containment redirected the output stream into the 886 KB ledger and the rule files rather than reducing the loop's gain, because L1 (verification as a defect-discovery engine), L4 (monotonic machinery growth) and L5 (no stopping conditions) were left intact and L5 was then strengthened by RC5.

Also measured: `rules/issue-tracking.md` requires live progress notes on the issue at every step, which in IA produced 1,202 `issue note` calls and 8,097 wrapper calls in total; `agent-state-convention.md` requires a DL entry at every phase transition and applied finding batch (150 entries for 714).

## 4. Things checked that are not the cause

- Model or tooling regressions. The same models and harness served the fast July work and the slow September work; the change is in the instruction corpus and the loops.
- Human unavailability. Real human messages per long session are few (the 711 session has about 36 user-authored turns, of which 5 are `mwinit` confirmations); most user-role messages in the transcripts are Stop-hook feedback, goal check-ins and compaction summaries.
- The iteration cap not being enforced. It fired; the escalation's options were "continue or narrow" and continuation was chosen.
- CI duration alone. Fifty minutes per run is long but would cost two to three hours per issue if a run were needed only two or three times; the loss comes from the number of pushes, deploys and polls the workflow requires and from polling with sleeps.

## 5. Where the 24-hour budget goes (BG, a typical Type2 issue)

| Stage | Sequential cost as measured | Notes |
|---|---|---|
| Pre-work reading and run setup | 1 to 2 h | 1.27 MB mandatory reading plus identity, registry, claim, worktree, venv |
| Requirements + design authoring | 2 to 3 h | spec-author averages 98 min per invocation |
| Design review, one iteration | 6 reviewers × ~1 h + author 1.6 h ≈ 7.5 h | zero parallelism |
| Design review, median spec (2 to 3 iterations) | 15 to 23 h | 714 took 16 iterations, about 5 days |
| Tasks + tasks review | 3 to 6 h | |
| Implementation, 30 to 40 tasks | 30 to 40 h | implementer ~63 min per task plus conductor test and commit |
| Push, CI, merge, trunk CI, deploy, smoke | 3 to 5 h wall clock | polled by sleep |
| Adversarial verification + panel re-review | 4 to 8 h | verifier ~116 min plus six lanes |
| Live E2E | hours to days | gated on operator sign-in and on shared-dev locks |

A change of the 714 kind should be about 30 minutes of authoring, one review pass, one implementer call, one CI run and one deploy: 2 to 3 hours. The framework as installed makes the minimum path for it roughly 60 to 90 sequential hours.

## 6. Direction for fixing (to be worked out at framework and project level)

1. Proportionality. Replace the Type1/Type2 binary with size tiers driven by the ask, with hard byte budgets for `requirements.md`, `design.md` and `tasks.md` per tier, and a rule that a reviewer finding must name the acceptance criterion of the original ask it protects or be recorded as C.
2. Bounded review. One combined review pass for small tiers; at most two iterations for medium; the cap-8 escalation must offer "approve the reviewed subset and ship" as the recommended option; the exit predicate becomes "no A findings" rather than "no A and no B".
3. Parallel by default. Panels dispatched in one message; independent tasks in `tasks.md` grouped into waves and implemented concurrently in one worktree; the Authoritative-Writer rule already makes this safe because lanes write only their own files.
4. Context diet. Cap always-on instructions (the framework's own 2026-09-04 kernel commit set the target at about 21k tokens; BG is at 107k); move incident narratives and violation logs out of rules; replace mandatory reading of `forLLMConsumption.md` and `lessons-learned.md` with an indexed, size-capped summary; give ledgers and lessons a retention policy.
5. Definition of done tied to the ask. Retire "work continues until finished" as a Stop-gate criterion in favour of "the acceptance criteria of the ask are green in CI"; let a session end when that holds even if the tasks list has residuals.
6. E2E only where automatable and where runtime behaviour changed; record a manual check as a residual, never as a gate; never ask the operator to sign in as a test step.
7. Waiting without polling: CI completion via the app's PR monitor or a single long wait, not 5-minute sleeps; a credential-expiry handling step that queues the push instead of stopping the run.
8. Machinery budget: a process-subject issue needs a named incident and a measured cost, and a rule paragraph added for an incident must displace one of equal size.
