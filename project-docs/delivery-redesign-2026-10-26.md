# Delivery redesign — hand-off at the queue, a merge steward, latest-green deploys — 2026-10-26

The operator's brief: implement, across the whole framework, the five wait-time changes of
`wait-time-analysis-2026-10-25.md` and the merge steward of `merge-velocity-chess-2026-10-25.md`, so
projects stop waiting serially and stop cancelling each other's deploys — **without giving up any
quality or functionality**. This document is the specification the implementation follows and the
record of why each piece has the shape it has.

## The quality invariants (every change below preserves all of them)

| # | Invariant | Before | After |
|---|---|---|---|
| Q1 | Nothing reaches the trunk untested | PR CI tested each PR against a base that went stale as soon as another PR merged; concurrent merges were never tested together; trunk runs were cancelled by the next merge | The steward lands only a commit whose exact tree passed the full CI (`main` + the PRs ahead of it + this PR). Stronger than before |
| Q2 | An issue closes only when its change is merged, deployed, verified end to end, and its checklist is complete (counted) | The session waited for its own SHA's deploy, which supersession often never produced | The verdict watcher closes it after the first green post-deploy check on a SHA that CONTAINS the landing (`git merge-base --is-ancestor`), and only when the counted checklist is complete; otherwise it labels the issue for a session to finish |
| Q3 | A red result never passes silently | A cancelled trunk run left no verdict at all | A red train drops exactly the culprit PR (label + comment + failing jobs); a red deploy marks every issue landed since the last green deploy `verification-failed`, keeps them open and returns them to the pool |
| Q4 | TDD evidence is unchanged | red/green per wave, RED-for-the-right-reason, adversarial verifier, PROOF_GATE | identical; PROOF_GATE cites the PR CI run on the PR head; the train run is the merged-state verdict |
| Q5 | Automation never loses work | — | auto-resume only re-enters the recorded phase under every gate; auto close-out removes only what close-out removed before and asserts nothing is unpushed; the remote branch lives until the steward lands it; nothing takes over a live session's issue |
| Q6 | People still decide product questions | five-line question, Proven Exceptions | unchanged; only the TIMING moves (asked early, independent work continues meanwhile) |
| Q7 | Adoption is safe | — | `config/delivery.json` selects the modes; a project without it keeps today's direct-merge, session-verified path unchanged |

## Delivery modes (`config/delivery.json`, tracked)

```json
{
  "merge": "steward",
  "verification": "watcher",
  "trunk": "main",
  "host": "github"
}
```

| Field | Values | Meaning |
|---|---|---|
| `merge` | `steward` / `direct` | `steward`: workers ENQUEUE (`enqueue-pr`); only the steward writes the trunk, and the `merge-steward` gate refuses `merge-pr`, `gh pr merge` and pushes to the trunk. `direct`: today's `approve-pr` + `merge-pr` |
| `verification` | `watcher` / `session` / `none` | `watcher`: the verdict job at the end of the deploy pipeline verifies and closes; the worker hands off. `session`: today's post-merge wait in the session. `none`: no deploy; the landing (steward) or the merge (direct) is the final verdict |

Absent file = `{"merge": "direct", "verification": "session"}` = today's behaviour. The setup prompt
installs `steward` + `watcher` for a project that deploys and `steward` + `none` for one that does not.
The steward's own settings (labels, batch size) live in the same file under `"steward"`.

## The worker's lifecycle (the five wait-time changes)

```
claim → worktree → classify (+ ALL foreseeable decision questions, non-blocking) → spec → waves
(independent verification runs concurrently; next wave's TEST authors start while this wave's green run
is in flight) → evidence REPORT, issue note, ledger rows, post-deploy checklist items marked — all
BEFORE the push → push once → PR CI (bounded foreground wait; a red run fixed in one pass) →
HAND-OFF → automatic close-out → archive
```

**HAND-OFF** (`merge: steward`): `enqueue-pr <PR>` (refuses unless PR CI is green on the head), the
hand-off note on the issue (PR, evidence path, claim start time, the post-deploy checks that must pass,
and the line `merge-steward: queued PR #<n>`), then `Phase: HANDED_OFF`. With `merge: direct` +
`verification: watcher` the worker merges and posts `merge-steward: landed <sha> (PR #<n>, direct)`
instead. With `verification: session` nothing changes from today.

`HANDED_OFF` is a terminal value for a SINGLE-ISSUE run only (`MODE: SINGLE_ISSUE`). In a loop mode
(`ISSUE_LOOP`, `AUTO`, `BACKLOG`) the issue-loop brake treats it as unfinished and the refusal says
"select the next issue" — handing one issue off is a checkpoint there, never a stop.

The tracker claim (in-progress label + assignee) STAYS on a handed-off issue: it is still in flight. The
steward or the watcher RELEASES it (removes label and assignee) and adds `needs-rework` when the work
comes back (conflict, red train, red deploy, open checklist items); `/issues-work` and `/auto-work` take
`needs-rework` issues first. The local lock, the worktree, the local branch and the per-worktree venv are
released at close-out (nothing unpushed — asserted).

**Automatic close-out** runs the `/close-session` checks as the last step of `/work-issue`; on
`CLOSE: YES` it archives the session without asking (the 2026-10-25 analysis measured 71 h of sessions
waiting on "Archive this session?" and 210 h waiting for `/close-session`). `CLOSE: NO` still asks.

**Questions** (`continuous-work.md`): every product decision the ask leaves open is identified at
CLASSIFY and asked then, in ONE batch; the session keeps working on everything independent of the
answers; `AskUserQuestion` (which blocks the session) is used only when the next step depends on the
answer and nothing independent remains. In a loop mode an issue blocked on a question is set aside and
the run continues with the next issue (as for an ambiguous issue today).

**Local verification**: suites of one verification that do not depend on each other (the Python suite,
the UI suite, a type check) start together as background tasks, each holding its own host-wide suite
slot, and are collected with bounded foreground waits (`.claude/hooks/wait_for.py`, exit 0/10/11 like
the wrapper waits). The rule "never two worktrees running suites at the same time" is replaced by the
semaphore, which already bounds the host. Captures, RED-for-the-right-reason and the verifier are
unchanged; wave N+1's red capture is taken only after wave N's green capture passed and was committed.

**Waiting**: one rule everywhere — do the unblocked work, then wait in the FOREGROUND with a bounded
timeout (`wait-run`/`pipeline wait` `--timeout-seconds 540`, re-issued on exit 11). Every leftover
"await it as a BACKGROUND task" text (the CI rule, the sleep gate's message, the two contract texts, the
orchestrator, the wrapper docstring, the setup prompts) is corrected. After the hand-off a worker waits
for NOTHING: the queue, the train, the deploy and the post-deploy check belong to the steward and the
watcher.

## The merge steward (`scripts/merge_steward.py`, `templates/merge_steward.py.template`)

Host-neutral Python (standard library; GitHub and GitLab adapters; git via subprocess with hooks
disabled). Run by the host's CI — never by an agent session — on EVENTS: an explicit trigger from
`enqueue-pr`, and the end of a train's CI run (GitHub `workflow_run` filtered to the train branches;
GitLab a `.post` bridge job in the train pipeline that cannot fail the train), with a 30-minute schedule
only as the safety net — a `*/10` schedule alone bills about 4,300 hosted-runner minutes a month, more
than a GitHub Free organisation's private-repo quota. Under `merge: direct` a tick runs only `reverify`
and exits 0, so the workflow installed by the bootstrap PR is green before the switch. STATELESS: every tick reconstructs the state from git (train branches and their
commit trailers) and the tracker (labels), so a lost runner or a cancelled tick loses nothing.

One tick:

1. **Finish the trains in flight.** For each train branch `steward/train-<batch>-<k>` read its CI
   verdict. Any still running → exit (the next tick continues). All terminal → step 2.
2. **Land.** `L` = the largest `k` such that trains `1..k` are all green. If the trunk still equals the
   batch's base (only the steward writes it), fast-forward it to train `L`'s head (`git push origin
   <sha>:refs/heads/<trunk>`, never a force). A moved trunk (someone pushed past the gate) lands
   nothing: the PRs stay queued and the next tick rebuilds on the new trunk. For each landed PR: comment
   `merge-steward: landed <sha> (PR #<n>, train run <url>)` on the PR AND on each issue it names
   (`Closes`/`Fixes`/`Refs #N`), remove the `queue` label, add `awaiting-verification` to the issue
   (`verification: watcher`) or run the verdict for it at once (`verification: none`). The PR at
   `L + 1` is the culprit: `queue-failed` label, `queue` removed, a comment with the failing train run,
   and its issue gets `needs-rework` with the claim released. PRs after it stay queued. Delete the
   train branches. Trigger the deploy workflow (`workflow_dispatch` with the landed SHA on GitHub; the
   trunk push itself triggers the pipeline on GitLab).
3. **Plan the next batch.** Queued PRs in enqueue order, each ELIGIBLE: open, not draft, base = trunk,
   no `do-not-merge`, PR CI green on its current head, approvals per `require_approval`, every
   `Depends-on: #N` landed or earlier in this batch. A PR whose head CI is red leaves the queue
   (`queue-failed`); one still running waits. Up to `batch_size` (default 4), preferring PRs whose
   changed files are disjoint from the batch so far (an overlapping PR waits for the next batch unless
   it is the oldest). Build train `k` = train `k-1` + `git merge --no-ff <PR head>` with trailers
   `Steward-PR`, `Steward-Issues`, `Steward-Batch`; a merge conflict drops that PR (`queue-conflict`,
   the conflicted paths in the comment, `needs-rework` on its issue) and the batch continues without
   it. Push every train branch and start its CI (GitHub: `workflow_dispatch` of the CI workflow on the
   train branch — a `GITHUB_TOKEN` push starts no workflow, a dispatch does; GitLab: the push with the
   steward's project token starts the branch pipeline).

All prefixes run in parallel (`parallel_trains: true`, the default for elastic runners such as
CodeBuild-hosted ones): one round lands the longest green prefix and names the culprit at once. With
`parallel_trains: false` the steward tests ONE PR per round (batch size 1) — the fewest runner minutes,
one landing per CI duration; it does not bisect a larger batch.

Capacity: CI duration D, batch B, one round per D: about B × 24 h ÷ D landings a day (55-min CI, B = 4:
about 100 a day).

Security: the tick checks out and runs the DEFAULT BRANCH's copy of the steward (a PR cannot alter the
steward that merges it — the workflow triggers on `workflow_dispatch`/`workflow_run`/`schedule`,
never `pull_request`, `pull_request_target` or `push`); it merges PR content as data and executes none of it (git with `core.hooksPath`
emptied); CI on the train branches keeps its read-only token; the token reaches the script on stdin,
never through a shell variable (`no-environment-vars`).

## Deploys: latest green, superseded, attributed by ancestry

The deploy workflow takes a SHA (GitHub `workflow_dispatch` input; GitLab: the trunk pipeline), uses ONE
concurrency group per environment that never cancels a running deploy, and lets a newer pending deploy
supersede an older pending one (GitHub's default group behaviour; drop `queue: max`; GitLab:
`resource_group` + "prevent outdated deployment jobs"). A superseded deploy is not a lost verdict any
more, because verification is by ANCESTRY: a green post-deploy check on SHA N verifies every landing that
is an ancestor of N. The trunk CI run on a steward landing is unnecessary — the train ran on exactly that
commit — and a workflow that still runs on `push` to the trunk must not cancel it
(`cancel-in-progress: ${{ github.event_name == 'pull_request' }}`).

## The verdict watcher (`merge_steward.py verdict`)

The last job of the deploy pipeline, `if: ${{ !cancelled() && needs.guard.result == 'success' }}` (a
superseded deploy renders no verdict, and neither does a dispatch the trunk-ancestry guard refused — that
is not a failed deploy): `verdict --sha <deployed> --conclusion <success|failure> --run-url <url>`.

- Collects the open issues labelled `awaiting-verification` or `verification-failed`, each with its
  landing SHA from the `merge-steward: landed <sha>` line; COVERED = landing is an ancestor of the
  deployed SHA.
- **success**: per covered issue, one comment (deploy run, SHA, environment; marker
  `<!-- merge-steward-verdict:<sha> -->` keeps it idempotent), tick the checklist items marked
  `(post-deploy)`, remove `awaiting-verification`/`verification-failed`, add `verified`; then COUNT the
  checklist: complete → close with the closing comment (PR, evidence, time spent from the hand-off note's
  claim start) and release the claim; items still open → `needs-closeout`, claim released, left open for
  a session to finish (a RESOLVE judgement the watcher does not make).
- **failure**: per covered issue not yet verified, add `verification-failed` + `needs-rework`, release
  the claim, comment with the run and the suspect range (last green SHA..this SHA). A red deploy says
  the cumulative state is broken, not that each issue is: the next green deploy containing them all
  verifies them all, and the rework session finds the culprit.

## Auto-resume after an API error (StopFailure + the host supervisor)

Measured: 17 turns killed by API errors (401/403/a Bedrock 400) idled a median 7.5 h each, 95 h in total,
until a person typed `/continue-work`. Documented harness facts the design rests on: `StopFailure` fires
instead of `Stop` when a turn ends on an API error, with `error`, `error_details`,
`last_assistant_message`, `session_id`, `transcript_path`, and has NO decision control; Desktop sessions
can reach each other with `ListAgents`/`SendMessage`, and a message to an idle session starts a turn; a
session in bypass mode holds messages from a non-bypassing sender unless the USER settings say
`crossSessionInbound: accept` (a project value can only tighten it). The raw inbox-socket format is not
documented and is not used.

1. `gate_stop_failure.py` (the dispatcher's new `stop-failure` event): records the failure in the run
   directory (`stop_failure.json`: error, details, time, streak) and writes a resume request for a run
   that has claimed unfinished work; logs the decision. Never blocks (it cannot).
2. `.claude/hooks/supervisor.py scan`: lists this clone's stalled runs — a resume request newer than the
   session's last transcript activity, or claimed `IN_PROGRESS` work idle past the bound — with the
   session id, issue, error and attempt count; `note <session> resumed|unreachable` records an attempt.
   Backoff 15 min doubling, at most 6 attempts per failure streak; a run that resumes and works again
   clears its streak.
3. `/supervise` (a Desktop scheduled task in bypass mode, every 15 minutes, one per project): runs the
   scan, finds each stalled session with `ListAgents`, sends the resume text with `SendMessage` (plain
   text: "the previous turn ended on an API error — follow `.claude/commands/continue-work.md`"), records
   the attempt, and reports in five lines. Never starts work of its own; `needs-rework` issues are
   reported, not taken.
No harness retry setting is relied on: none was verified to exist, and an authentication failure is not a
transient error a retry would fix — which is why the recorder, the watchdog and the supervisor exist.

## Fewer collisions

- `docs/findings-ledger.md`, `docs/lessons-learned.md` and `docs/archive/*.md` carry `merge=union` in
  `.gitattributes`: they are append-only tables, the top conflict file of the measured project (18 of
  31 sessions). The steward and every worker merge with git, which honours the attribute;
  `memory_compile.py reconcile` drops exact duplicate rows a union merge can produce.
- No post-merge evidence or ledger PRs: everything the PR should carry goes in before the push; what
  happens after the landing is recorded ON THE ISSUE by the steward and the watcher (40 % of the measured
  sessions' PRs were such follow-ups, 23 % of trunk commits).
- Batches prefer disjoint footprints; SELECT prefers an issue whose obvious footprint does not overlap a
  queued PR.
- One owner for trunk health: sessions never re-run, cancel or dispatch trunk or deploy runs; the
  steward and the watcher do.

## What a project gets (install map)

| Asset | Target |
|---|---|
| `templates/merge_steward.py.template` | `scripts/merge_steward.py` |
| `templates/test_merge_steward.py.template` | `test/test_merge_steward.py` |
| `templates/delivery.json.template` | `config/delivery.json` |
| `templates/ci/github-merge-steward.yml.template` | `.github/workflows/merge-steward.yml` |
| `templates/ci/github-deploy.yml.template` | the deploy workflow's trigger, concurrency and verdict job |
| `templates/ci/gitlab-delivery.gitlab-ci.yml.template` | the steward job, train rules, verdict job |
| `hooks/gate_merge_steward.py`, `hooks/gate_stop_failure.py`, `hooks/supervisor.py`, `hooks/wait_for.py` | `.claude/hooks/` (with the rest of the hooks) |
| `claude-commands/supervise.md` | `.claude/commands/supervise.md` |
| `claude-agents/spec-workflow/docs/delivery.md` | `.claude/docs/delivery.md` (on demand) |
