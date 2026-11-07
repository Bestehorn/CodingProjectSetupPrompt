# Wait time in finished Chess and AWSBedrockGateway sessions — analysis, 2026-10-25

Question asked by the operator: of the whole build time of the recently finished sessions, how much is
spent waiting on something instead of actively working (the **wait-time**, and its share of the session,
the **wait-time-portion**)? Which part of it is (a) waiting for other parts of the build process (CI
pipeline, tests, …), and how much time is lost there because nothing ran in parallel? The answer feeds a
decision on whether to adapt the framework. Nothing in the framework or the projects was changed.

## Method

- **Sessions.** Every archived (finished) Claude desktop session whose working directory is `chess` or
  `AWSBedrockGateway` and that was active on or after 2026-10-11: 39 `/work-issue` sessions (31 chess,
  8 gateway). Five of them started 10-07 to 10-10 and finished inside the window; they are counted whole.
  Excluded: two conversational sessions ("User Admin usage statistics", "Game history and rating not
  syncing") and the seven sessions that are still open.
- **Data.** Session metadata from `%LOCALAPPDATA%\Claude-3p\claude-code-sessions` (title, cwd, CLI session
  id, archived flag); the transcripts in `~\.claude\projects\<project>\<cli-id>.jsonl` plus every
  `subagents\agent-*.jsonl` (2,612 subagent transcripts); the background-task output files in
  `%TEMP%\claude\<project>\<cli-id>\tasks\` (their last-write time dates the 24 background tasks that never
  delivered a completion notification).
- **One timeline per session.** Every second between the session's first and last record gets ONE label:
  the highest-priority state of any agent at that moment (main thread, any subagent, any background task).
  Priority: model generating > quick tool work (Read/Edit/Grep, short git/shell) > a build step running in
  the foreground > a build step running in the background while nothing else happens > infrastructure
  (API retries, compaction) > waiting for a human > stalled. So a CI run that overlaps real work counts
  as work, and only the time in which **nothing else happened** is wait-time.
- **Build span** = first to last record, minus the post-completion idle (the issue was done and the
  session waited for `/close-session` or for the "Archive this session?" answer: 281 h, reported
  separately, not counted as build time).
- Bash commands are classified by pattern (CI wait, local tests, suite lock, git, setup/cleanup, …); hand-
  rolled waits (`wait_for_line.py`, `tail -f | grep -m1`, `until …; sleep`) are attributed to what they
  wait on. Scripts and raw output: `tmp/wait-analysis-2026-10-25/` (not tracked).

## Headline numbers

| | Hours | Share of build span |
|---|---:|---:|
| Build span, 39 sessions (median 22.7 h per issue, IQR 10.5–38.8 h) | 1,318 | 100% |
| **Active** (model generating 392 h, quick tools 49 h) | 441 | 33.5% |
| **Wait-time** | **877** | **66.5%** |
| — (a) build-process steps with nothing else running | 616 | 46.7% |
| — (b) waiting for a human (decisions, credentials) | 131 | 9.9% |
| — (c) stalled until `/continue-work` | 110 | 8.4% |
| — overhead (Stop-hook churn 8 h, API retries 2 h, compaction 0.5 h) and untracked idle | 20 | 1.5% |
| *Post-completion idle, excluded from the span* | *281* | — |

Per session the wait-time-portion has a median of 65% (IQR 56–71%); chess 66%, gateway 68%. The build-
process share alone has a median of 50%. When the sessions do work, they already work in parallel: in 48%
of the active time two or more agents were busy at once. The waits are the problem, not the work.

## (a) Waiting for the build process

### What the 616 hours are

| Build step (exposed = nothing else happening) | Running h | Exposed h | Exposed share |
|---|---:|---:|---:|
| CI pipeline (PR/MR CI, trunk CI, deploy dev, E2E harness) | 367 | 285 | 78% |
| Local tests and TDD evidence captures | 333 | 171 | 51% |
| Local full-CI run (CI-outage mode, issue 553) | 50 | 40 | 79% |
| Worktree/venv setup and cleanup (incl. reaper) | 53 | 35 | 66% |
| Other sessions: one-suite-per-host marker, their commits | 43 | 24 | 54% |
| Git push/fetch/commit incl. pre-push/pre-commit hooks | 33 | 23 | 71% |
| Sleep and waits whose target could not be resolved | 57 | 23 | 40% |
| Everything else (checks/build, tracker API, scripts, deploy) | 67 | 16 | 24% |
| **All build steps (union)** | **839** | **616** | **73%** |

Only 27% of the time a build step was running overlapped with any other work. During 446 of the 616
exposed hours exactly one build step was running and nothing else happened at all.

### The post-merge phase is half of every session

Split at each session's first real merge (`merge-pr` / `mr merge`):

| | Before the merge | After the merge |
|---|---:|---:|
| Build span | 673 h | 645 h (49%) |
| Active | 328 h | 114 h |
| CI pipeline waits | 62 h | 223 h |
| Local full-CI run | 0 h | 39 h |
| Local tests | 118 h | 53 h |
| Setup/cleanup | 2 h | 33 h |
| Stalled | 28 h | 83 h |
| Human | 71 h | 60 h |

Median post-merge phase: 7.4 h per issue (41% of the session); 557, 544, 798 and 553 spent 60–102 h after
their first merge. The CI wait is dominated by what happens AFTER the PR is merged — trunk CI, the dev
deploy and the post-deploy E2E harness, which `work-issue.md` Step 8 and the orchestrator's MERGE step 4
make the issue's E2E evidence — not by the PR pipeline (62 h). The pipelines are long and serial: chess
`Deploy dev` runs one deploy at a time with `cancel-in-progress: false`, its `deploy` job has a median of
94 min (n = 20) followed by the harnesses (9–21 min), and every merged SHA waits for its own deploy behind
the other sessions' merges. Chess PR CI: `quality` (5 min) → `tests` (31 min, `needs: quality`) beside
`ui` (34 min). Gateway, in the sessions measured: `check` (frontend 16 min) → a single `test` job (median
93 min, n = 14) → `deploy-dev` (21 min) → `smoke-test` (8 min); trunk has since made `test` `needs: []`
with `parallel: 2`. (Job durations are what the sessions themselves printed, so the samples are small.)

### How much of it is lost to missing parallelization

The projects ran framework 510b377, whose `parallel-by-default.md` said "start the wait in the background
and pick up the next step" — but in single-issue mode there is no next step, so the session idles: 230 h
of the CI wait is a background wait with an idle session, 55 h a foreground wait. Both are the same
exposure. Estimates, with the assumption each rests on:

| Lever | Exposed h | Recoverable h | Assumption |
|---|---:|---:|---|
| Session no longer blocks on the post-merge pipeline (trunk CI → deploy → E2E), local full-CI and close-out cleanup | 262 + 33 | ~290 | The verdict is still awaited, but by a watcher, not by the session; a red verdict reopens the work. The issue's time-to-verified does not shrink, the session's (and the operator's) does. |
| Deploy queue: E2E evidence from the first green deploy whose SHA contains the merge, so deploys may supersede each other | part of the 223 | not measurable here | Needs each run's queue time, which the transcripts do not hold. |
| PR/MR CI wait | 62 | 0–60 | Only recoverable by overlapping the next issue; the docs/PR text is already written before the wait. |
| Independent local verification runs executed one after another (no edit in between) | 72 | ≤ 32 | Upper bound: each chain's runs run concurrently. |
| Suites queued behind other sessions (chess one-suite-per-host marker 24 h, `suite_semaphore` "all slots busy" ≥ 17 h inside test commands) | ~41 | capacity, not framework | 2 semaphore slots on 8 vCPU shared by ~5 sessions. |
| Remaining wave red/green runs | ~120 | partial | Pipelining waves (author wave N+1 tests while wave N's green suite runs) is possible where files are disjoint. |

Conservatively ~320 h (24% of the build span) of the 616 h is time lost to waiting serially that the
framework could overlap; ~380 h (29%) if the session also works the next issue during PR CI. The ~41 h of
queueing behind other sessions' suites needs host or runner capacity rather than a framework change.

## (b) and (c): the waits that are not build steps

- **Stalls, 110 h.** 95 h are 17 turns killed by an API error — `401 Unauthorized`, `403 Forbidden`
  ("Failed to authenticate"), and three Bedrock `400 … each thinking block must contain thinking` on
  2026-10-22 — after which nothing ran until the operator typed `/continue-work` (median 7.5 h per episode;
  six started between 22:00 and 07:00). 9 h are foreground tools whose process died, 6 h turns that ended
  without an error (4.5 h of them "waiting on …"). The 2026-10-10 stop measures (`no-idle-wait`, foreground bounded waits) are only in this
  repo's uncommitted working tree and address the last group, not the API-error group.
- **Human, 131 h.** 20 `AskUserQuestion` decisions (median 2 h, 71.5 h; nine asked between 22:00 and
  07:00), 16 questions asked as text (median 40 min, 55.6 h), operator `mwinit` 3.9 h. `AskUserQuestion`
  blocks the whole session, including work that does not depend on the answer.
- **Post-completion, 281 h (excluded).** 210 h between "done" and `/close-session`, 71 h with "Archive this
  session?" unanswered. Not build time, but the sessions keep their worktrees and keep being polled by the
  desktop app (the 2026-10-01 load investigation measured ~255 `git status` polls per session per hour).

## What this suggests for the framework (for discussion)

Ranked by the hours they address:

1. **Stop holding the session for post-merge verification (~290 h).** Merge → record the trunk run to watch
   → close the session; a watcher (scheduled task, or the desktop app's CI monitor) reads the deploy/E2E
   verdict, closes the issue on green, and starts a fresh fix session on red. In `/issues-work` mode the
   alternative is to start the next issue while the previous one's post-merge pipeline runs.
2. **Auto-resume API-killed turns (~95 h).** A watchdog that finds a session whose last assistant message is
   an API error while its `resume_state.md` says `IN_PROGRESS`, and sends it `/continue-work`.
3. **Overlap local verification (≤ 32 h direct, more with wave pipelining).** Run independent suites of one
   verification concurrently; let the next wave's TEST authors start while the current wave's green run is
   in flight; move wide suites to CI runners instead of queueing behind the host's two semaphore slots.
4. **Make decision questions non-blocking and earlier (part of 131 h).** Batch the questions at CLASSIFY;
   ask without `AskUserQuestion` when independent work remains, and keep working.
5. **Auto close-out at `Phase: DONE` (281 h of idle sessions, not build time).**
6. **Pipeline shape (project work, not framework):** chess `Deploy dev` single concurrency with ~94-min
   deploys; chess `tests` waits for `quality`; gateway's `test` stage (already sharded on trunk).

## Limits

The `merge` boundary is the first wrapper merge, which can be a dependency or evidence PR; CI run ids
include runs a session only inspected; command classification is pattern-based (about 4% of build-step
time is "unresolved"); five-plus sessions shared an 8-vCPU host, which lengthens both work and waits; the
harness's own `cost-state` counters are written per process lifetime and too sparse to cross-check against.
