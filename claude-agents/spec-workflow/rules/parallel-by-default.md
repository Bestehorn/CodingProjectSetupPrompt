# Parallel by Default (ALL agents, always loaded)

Independent work runs concurrently. The operator's time is the scarce resource; tokens
are not. A sequential dispatch of independent work is a defect, not a style choice.

## What must run in parallel

- **Review lanes.** Every reviewer of a panel is dispatched in ONE message. Each lane
  writes only its own file; the conductor consolidates afterwards (the Authoritative
  Writer rule in `agent-state-convention.md` §1c is what makes this safe).
- **Research bursts.** Independent questions to `spec-researcher` go out together.
- **Implementation waves.** `tasks.md` groups tasks into waves; tasks in a wave own
  disjoint files and depend only on earlier waves. All TEST tasks of a wave are dispatched
  together, the wave's tests are run once (red), then all IMPL tasks are dispatched
  together and the wave's tests are run once (green). One commit per wave. The next wave's
  TEST authors start while this wave's green run is in flight; its red capture waits for
  this wave's commit.
- **Independent suites** of one capture start together, each through `scripts/run_tests.py`
  or `scripts/suite_semaphore.py run`. Captures overlap; they are never skipped or merged.
- **Independent issues.** Separate issues run in separate worktrees and sessions.

## What waits, and how

Never `sleep`-poll in a tool call, and NEVER END A TURN TO WAIT: a background task dies
with the session's process and never wakes it. Do every unblocked piece of work first, then
wait in the FOREGROUND, bounded (Bash `timeout` 600000), re-issued while it exits 11: a run
with the wrapper's `wait-run <id> --timeout-seconds 540` (GitLab: `pipeline wait`); a local
process started as `<command> > <log> 2>&1; echo "exit=$?" >> <log>` with
`python .claude/hooks/wait_for.py --file <log> --line '^exit=' --timeout-seconds 540`. A
background task is for output you read LATER while you keep working. The
`no-foreground-sleep` and `no-idle-wait` gates enforce this.

Under the merge steward (`config/delivery.json`) a PR whose own CI is green is enqueued and
handed off: its merge, the trunk run and the deploy are not yours to wait for
(`.claude/docs/delivery.md`).

## Self-check before any dispatch

Could this call run alongside the previous one? If yes, they belong in the same message.
Is the next step blocked on a run? Pick up every unblocked step first; then wait for the
run in the foreground, bounded, and continue in the same turn.
