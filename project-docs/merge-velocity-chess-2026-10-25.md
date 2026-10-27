# Merge velocity in chess: why deploys get cancelled and workers collide — 2026-10-25

Question asked by the operator: the many parallel workers produce so many PRs and merges that deploys
get cancelled and the workers step on each other's toes. How do high-velocity repositories handle ten or
more PRs that are pending against `main` at any time? Nothing was changed; this records the diagnosis
and the proposed direction, to be decided together with the five changes kept from
`wait-time-analysis-2026-10-25.md`.

## What happens today (measured)

Sources: `git log --first-parent origin/main` since 2026-10-11; the chess workflow files on `origin/main`;
read-only `list-runs`/`get-run` through the project wrapper (the last 100 runs each of CI and Deploy dev);
the transcripts of the 31 finished chess sessions (`tmp/wait-analysis-2026-10-25/`).

**Arrival rate.** 342 commits reached `main` in 15 days, 24 a day on average (38 on 10-13, 37 today). The
median gap between two merges is 39 min, a quarter are less than 16 min apart, and 63% arrive less
than 55 min after the previous one, which is a trunk CI run's current duration.

**Trunk CI cancels itself.** `ci.yml` has `concurrency: group: ci-${{ github.ref }}` with
`cancel-in-progress: true`. On `main` the ref is always `refs/heads/main`, so every merge cancels the trunk
run of the merge before it. Today, 29 of 34 trunk CI runs were cancelled, 3 failed and 2 succeeded.

**Deploys starve, then queue.** `Deploy dev` starts only from a successful trunk run whose SHA is still
`main`'s tip (`head_sha == github.sha`). Of the last 100 Deploy dev runs (since 10-21 23:56 UTC), 71 were
skipped by that guard, 15 failed and 13 succeeded: about three successful dev deploys a day for 24 merges
a day. The deploy group is `cancel-in-progress: false` with `queue: max`, so the runs that are admitted
queue behind each other: creation-to-completion has a median of 4.7 h (max 9.5 h) for a deploy job of
~94 min plus harnesses. At the peak, 19 merges landed inside one such 4.7 h window.

**Each session insists on its own SHA.** The framework makes the E2E evidence "the verdict on the merged
SHA" (`work-issue.md` Step 8, orchestrator MERGE step 4), so most sessions wait for a deploy that never
comes for their SHA. In the transcripts: 60 of 334 waited-on runs ended `cancelled`, 46 wrapper re-run or
dispatch calls, and "this may take more than one round" waits for a quiet window on trunk.

**The workers amplify the load.** 32 of the 80 PRs these sessions opened were evidence, ledger or follow-up
PRs created after the feature merged, and 80 of the 342 trunk commits touch only `.claude/`, specs, the
findings ledger or its archive. Each of them is a merge that cancels the trunk CI of a real change.

**Branches drift and collide.** The 31 sessions re-synced their branch with trunk 99 times and dispatched
`code-merge-reviewer` 98 times; 9 `merge-pr` calls failed with "Pull Request has merge conflicts". The
conflicts concentrate on shared append and registry files: `docs/findings-ledger.md` conflicted in 18 of
the 31 sessions (87 times), followed by the SSM parameter tree and its tests
(`src/ssm_config.py`, `test/test_ssm_parameter_tree.py`, `test/cdk/test_parameter_tree_synth.py`), the
doc-pinning tests (`test/ci/test_doc_dev_deploy_surfaces.py`, `docs/dev-deploy.md`) and the test and
module registries.

## How high-velocity repositories handle it

1. **A merge queue (GitHub merge queue, GitLab merge trains, or Bors/Mergify/Aviator).** A PR that is
   reviewed and green is enqueued instead of merged. The queue builds the exact future state (`main` +
   the PRs ahead of it + this PR), runs the required checks on that, and merges in order when green.
   Branches never have to be "updated with main", nobody races for the merge button, and `main` only
   ever receives tested states. With a 55-min CI and 24 merges a day, one-at-a-time queueing is already
   at capacity (~26 a day), so the queue must **batch** (test 3–5 PRs together, bisect a red batch) and
   build several groups concurrently.
2. **Trunk CI is never cancelled; superseded PR runs are.** `cancel-in-progress` applies to PR refs
   only. With a merge queue, the merged commit is the commit the queue tested, so the post-merge run is
   cheap or skipped.
3. **Continuous deployment deploys the latest green commit and attributes it.** Skipping intermediate
   SHAs is the intended batching: a deploy of SHA N verifies every merge that is an ancestor of N
   (`git merge-base --is-ancestor`). Pending deploys are superseded by the newest one instead of queued.
   A red batch is attributed by one owner (bisect, or revert the culprit), not by every PR in it.
4. **One owner for trunk health.** A single watcher or "build cop" owns trunk and environment verdicts,
   re-runs, and reverts, and notifies or reopens the responsible issue. Workers do not each watch and
   react to the shared environment.
5. **Fewer merges, fewer hot files.** Results and bookkeeping that do not change the product do not go
   to `main` as separate PRs. Append-only shared files become one fragment file per entry (the
   "changelog.d" or news-fragment pattern) or carry `merge=union`. Central registries are generated or
   split per module, so two features stop editing the same lines.
6. **Lean required checks, fast CI.** Only what must gate the merge is required. Slow or advisory legs
   run after the merge or nightly. The queue's capacity is roughly (concurrent groups × batch size ×
   24 h ÷ CI duration).
7. **Schedule around collisions.** A dispatcher does not run two issues at once that touch the same hot
   files, or it orders them as a stack.

## Mapping to chess and the framework

| # | Change | Where | Addresses |
|---|---|---|---|
| A | Merge through a queue: GitHub merge queue (workflows add `merge_group:`) or, if the plan lacks it, a framework "merge steward" (one serial/batching merger) | chess repository settings + `ci.yml`; `work-issue.md` Step 7 and the wrapper's `merge-pr` become "enqueue" | merge races, 405 conflicts, branch re-sync churn |
| B | `cancel-in-progress: ${{ github.event_name == 'pull_request' }}` in `ci.yml` | chess | 29 of 34 trunk runs cancelled |
| C | Deploy dev: newest pending supersedes (drop `queue: max`) and deploys the latest green SHA; the evidence rule becomes "the first green post-deploy E2E on a SHA that contains the merge" | chess deploy workflows; framework Step 8, orchestrator MERGE step 4, the E2E rule | 4.7 h deploy turnaround; sessions waiting for their own SHA |
| D | One trunk-health watcher owns deploy verdicts, re-runs and reverts | framework, together with kept change #1 (post-merge hand-off) | sessions stepping on each other in the shared dev environment |
| E | No post-merge evidence or ledger PRs: post-merge verdicts go to the issue (comment / check summary); the ledger becomes per-entry fragment files compiled by `memory_compile` | framework (`issue-filing-discipline.md`, `compile-memory`, `templates/memory_compile.py.template`) and chess | 23% of trunk commits; the top conflict file |
| F | Split the SSM parameter tree, doc-pinning tests and registries into per-module fragments | chess | the next conflict hot spots |
| G | `/issues-work` / `/auto-work` selection avoids concurrently running issues with overlapping file footprints | framework | collisions before they happen |

## GitHub plan (checked 2026-10-26)

The chess organisation is on GitHub Free. Settings → Rulesets reports "Your rulesets won't be enforced on
this private repository until you move to GitHub Team organization account", so nothing on GitHub enforces
anything on `main` today: no required checks, no required reviews, no merge queue. "CI green before
merge" holds only because the framework's rules and wrapper make the agents check it. As far as I know,
GitHub Team makes rulesets and branch protection enforceable, but the native merge queue on a private
repository needs GitHub Enterprise Cloud; on a public organisation repository it is available on Free.

So change A has three routes:

1. **A framework merge steward on GitHub Actions** (works on Free, independent of the host, so it suits
   development spread over several machines). Workers stop calling `merge-pr` and enqueue instead (a
   label). One workflow with a single, never-cancelled concurrency group builds `main` + the queued PRs
   on a train branch, runs CI on it, fast-forwards `main` on green, and drops and comments on the culprit
   on red (the bors model). Two GitHub details shape it: a push made with `GITHUB_TOKEN` does not trigger
   other workflows, so the steward calls CI as a reusable workflow (`workflow_call`) and starts the
   deploy itself; and with no enforcement on Free, "only the steward merges" is a framework rule backed by
   the wrapper and a gate, not a GitHub setting.
2. **A third-party merge-queue app** (Mergify, Aviator, Trunk and similar), which works through the API on
   any plan but is paid for private repositories.
3. **Making the repository public** (native merge queue and free Actions minutes), which is a security and
   ownership decision.

Changes B to G need no plan change and are independent of the route.

Open point: whether the E2E rule may accept a batch deploy as evidence. The gateway's equivalent of the
merge queue is GitLab merge trains, which need GitLab Premium.

## Update 2026-10-26: what chess already changed

Issue #1266 landed overnight (`775fffc7e` "Finish main's CI runs and deploy dev from the newest green
one", `f8a6c90fb`). `ci.yml` now sets `cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}`, so trunk
runs are no longer cancelled (change B). `deploy-dev.yml` has an Admission Job: when a queued run leaves
the `deploy-dev` queue, it is admitted only if its trigger is still the newest green push run on `main`,
and otherwise it cancels itself as Superseded. That is the pipeline half of change C. What is still
missing from C is the evidence half: the framework still asks for the verdict on each session's own merged
SHA, and under supersession most SHAs are never deployed.

## Decision 2026-10-26: route 1, a framework merge steward, on CodeBuild

**It runs on CodeBuild, the same way chess CI already does.** `CI_RUNNER_MODE` has been `codebuild` since
2026-08-25: every CI job and every deploy job runs on a CodeBuild-hosted, ephemeral GitHub Actions runner
(`chess-ci-runner-dev`, `chess-deploy-runner-dev`). GitHub Actions provides the orchestration: the
triggers, the concurrency group that serialises the queue, the checks UI and the job token. CodeBuild
provides all the compute. The steward's jobs use the same `runs-on: codebuild-<project>-<run_id>-<attempt>`
labels, so no GitHub-hosted minutes are used and the Free quota does not matter. Because AWS bills
CodeBuild per minute and scales it, the steward can also test several train prefixes at once (see below).
A steward built entirely in AWS (EventBridge, Step Functions and CodeBuild behind a GitHub App) would
also work, but it needs a stored GitHub App key and a webhook receiver, which goes against chess's "no
stored credential" posture (`deploy-dev.yml` header). Recommended: orchestrate in GitHub Actions, compute
on CodeBuild.

**Shape of `merge-steward.yml`:**

- **Triggers:** `workflow_dispatch` (fired by the wrapper's new `enqueue-pr`, after it adds the `queue`
  label) plus a `schedule` every few minutes as a safety net. Both run the default-branch copy of the
  workflow, so a PR cannot change the steward that merges it. `pull_request` events are not used for this
  reason. Concurrency: `group: merge-steward`, `cancel-in-progress: false`. Each run reads the whole queue,
  so one pending run is enough.
- **plan** (contents: read): list open PRs labelled `queue`, oldest first. Each must have green PR CI on
  its head SHA, satisfy the recorded merge authority, and carry no `do-not-merge` label. Take a batch of
  up to N (start with 4), preferring PRs with disjoint file footprints (change G). PRs whose dependencies
  are not landed yet stay in the queue.
- **stage** (contents: write; runs only git, never repository code): build `steward/train-<run>` = `main`
  plus a `--no-ff` merge of each PR head, plus one cumulative branch per prefix (A, A+B, A+B+C, …). A
  textual conflict drops the PR: label `queue-conflict` and comment. Push the train branches.
- **verify** (contents: read): `uses: ./.github/workflows/ci.yml` with the train ref as input (`ci.yml`
  gains a `workflow_call` trigger). The jobs keep their CodeBuild `runs-on`. All prefixes run as a matrix
  in parallel on CodeBuild, so a red batch still lands its longest green prefix in the same round, which
  is GitHub's own merge-queue strategy. Running them serially would cost one CI duration per failing PR
  of bisection.
- **land** (contents: write; runs only git): check that `main` is still an ancestor of the longest green
  prefix (if someone pushed to `main`, rebuild in the next round), then `git push origin <prefix>:main`, a
  fast-forward. GitHub marks the PRs merged because their heads are now reachable from `main`. Remove the
  `queue` label, comment "landed in `<sha>` by steward run `<id>`", and delete the PR branches. The first
  PR after the green prefix is the culprit: label `queue-failed`, comment with the failing jobs and their
  logs. The others stay queued.
- **Deploy trigger:** a `GITHUB_TOKEN` push starts no `push` workflows, so trunk CI does not re-run for
  the landed SHA. It does not need to: the steward tested exactly that commit. `deploy-dev.yml` is
  triggered by `workflow_run: workflows: [Merge steward]` instead of by CI, and #1266's Admission Job
  checks "newest landed steward SHA" instead of "newest green push run". The chain steward → Deploy dev
  → Deploy stage stays within GitHub's limit of three `workflow_run` levels.
- **Security:** only `stage` and `land` hold `contents: write`, and they never execute repository code;
  CI keeps `contents: read`. Free has no enforcement, so "only the steward writes `main`" is a framework
  rule: the wrapper's `merge-pr` refuses, and a new PreToolUse gate refuses `merge-pr`, `gh pr merge` and
  `git push … main` for agents. The operator also merges through the queue.
- **Capacity:** with 55-min CI and batches of 4, one round per hour lands ~4 PRs, about 100 a day, against
  24 a day today.

## Integration with the five wait-time changes and B–G

Target lifecycle. Each piece lives where its state lives: everything that touches `main` or a shared
environment runs in the cloud, once; everything that touches a Claude session runs per host.

| Actor | Responsibilities | Absorbs |
|---|---|---|
| **Worker session** (per issue, any host) | spec → implement → verify only what the change affects, with independent runs concurrent and the next wave's TEST authors started while the current wave's green run is in flight → ask all decision questions together at CLASSIFY, without blocking independent work → push once → PR CI (cancellable) → `enqueue-pr` → hand-off note on the issue (what the post-deploy check must show) → `Phase: QUEUED` is a terminal release → automatic close-out (worktree, venv, reaper, archive) | wait-time #3, #4, #5; E (ledger rows as per-entry fragment files inside the PR, evidence `REPORT.md` inside the PR, nothing pushed to `main` after enqueue) |
| **Merge steward** (GitHub Actions on CodeBuild) | queue → train → CI → land → trigger Deploy dev | A; B becomes moot (no trunk push runs); G (footprint-aware batching) |
| **Verdict watcher** (GitHub Actions on CodeBuild, `workflow_run` on Deploy dev and its harness jobs) | For every landed, unresolved issue whose merge is an ancestor of the deployed SHA: on green, post the evidence (run ids, SHA), tick the checklist, close the issue (RESOLVE moves here). On red, attribute it to the issues landed since the last green deploy: if one, that one; if several, revert-and-redeploy bisection or `needs-rework` on each with the logs | wait-time #1 (the session never waits for merge, trunk, deploy or E2E); C's evidence half (first green post-deploy E2E on a SHA that contains the merge); D (one owner for trunk health) |
| **Host supervisor** (desktop scheduled task on each machine) | Resume sessions whose last turn died on an API error while `resume_state.md` says `IN_PROGRESS` (`/continue-work`). Start sessions for `needs-rework` and ready issues, claiming them through `start-issue` so hosts never collide, and never two in-flight issues with overlapping footprints | wait-time #2; G; rework pickup |

What changes in the framework, for the implementation step:

- `work-issue.md` Steps 7 and 8, the orchestrator's MERGE and RESOLVE sections, `run-identity.md` (new
  terminal phase `QUEUED`; the issue carries `awaiting-verification` until the watcher closes it), the
  Stop gates (accept `QUEUED`), `close-session.md` (runs automatically).
- The E2E rule (`always-test-e2e.md`) and `continuous-work.md` / `parallel-by-default.md`: the
  post-merge verdict belongs to the watcher; workers never wait for it.
- Wrapper templates: `enqueue-pr` and `queue-status`; `merge-pr` refuses. A new hook,
  `gate_merge_steward.py`.
- New templates: `merge-steward.yml`, `post-deploy-verdict.yml`, plus `workflow_call` guidance for the
  project's CI.
- `issue-filing-discipline.md`, `compile-memory`, `templates/memory_compile.py.template`: the findings
  ledger becomes per-entry fragments.
- `/issues-work` and `/auto-work` selection and the host-supervisor prompt: footprint awareness.
- `CONTRACT_VERSION` bump, `REVISION_NOTICE.md`, `FrameworkUpdatePrompt.txt`.

Order: (1) independent quick wins: the watchdog (#2), ledger fragments, and no post-merge evidence PRs (E).
(2) One release for A + the verdict watcher + hand-off at enqueue + automatic close-out (#1, #5, D, C's
evidence half), because the hand-off is only safe once the watcher exists. (3) #3, #4, F, G.

Decisions this needs from the operator: the batch deploy counts as E2E evidence (ancestry); the watcher
closes issues; on red, the host supervisor starts the fix session itself (or labels the issue and waits
for the operator); the merge authority the steward checks, since Free enforces no review.
