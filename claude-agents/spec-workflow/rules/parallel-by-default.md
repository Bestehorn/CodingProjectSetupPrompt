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
  together and the wave's tests are run once (green). One commit per wave.
- **Independent verification.** The suites of one capture that do not depend on each other (a Python
  suite, a UI suite, a type check) start together as background tasks, each through `scripts/run_tests.py`
  or `scripts/suite_semaphore.py run` (the host-wide slots still bound the machine), and are collected with
  bounded foreground waits. The next wave's TEST authors start while this wave's green run is in flight;
  that wave's red capture waits for this wave's green capture to pass and be committed. Captures are never
  skipped or merged to save time — they stop waiting for each other.
- **Independent issues.** Separate issues run in separate worktrees and sessions.

## What waits, and how

Never `sleep`-poll in a tool call, and NEVER END A TURN TO WAIT. First do every piece of
work that does not depend on the verdict. When nothing unblocked remains, wait in the
FOREGROUND with a bounded timeout: the wrapper's blocking `wait-run <id> --timeout-seconds
540` (GitLab: `pipeline wait <id> --timeout-seconds 540`) under the Bash tool's 10-minute
ceiling (`timeout` 600000), re-issued while it exits 11, then act on the verdict (0 success,
10 not success). A local process or a file that must appear is awaited the same way: a
bounded foreground command, re-issued: start it as `<command> > <log> 2>&1; echo "exit=$?" >> <log>` and
collect it with `python .claude/hooks/wait_for.py --file <log> --line '^exit=' --timeout-seconds 540` (exit 0
found, 11 timeout — re-issue; `--pid` takes an OS process id, which Git Bash's `$!` on Windows is not).
The `no-foreground-sleep` gate refuses a foreground `sleep` of 10 s or more and any sleep inside a loop; a
wrapper wait and `wait_for.py` are not sleeps.

What you never wait for: where `config/delivery.json` says `merge: steward`, a PR whose own CI is green is
ENQUEUED (`enqueue-pr`) and handed off — the merge steward tests the exact merged state and lands it, the
deploy's verdict job verifies the issue by ancestry and closes it, and anything that comes back arrives on
the issue as `needs-rework` (`.claude/docs/delivery.md`). A session that waits for its PR to merge, for the
trunk pipeline or for a deploy is idling on work that is no longer its own.

Why not a background task: it dies with the session's process, and a task the harness
reports as `stopped` never wakes the model (measured 2026-10-10 over 30 days: 82 of 82); a
turn that ended "waiting on it in the background — its exit line will notify me" then idles
until the operator types `/continue-work`. The `no-idle-wait` Stop gate refuses such a turn
end. A background task is for output you will read LATER while you keep working in the same
turn (a long reaper run, a harness whose log you collect at the end), never for a wait you
need before continuing. Idling on a pipeline is a stop in disguise (`continuous-work.md`);
every shell call is the expensive tool (`native-tools-over-shell.md`).

## Self-check before any dispatch

Could this call run alongside the previous one? If yes, they belong in the same message.
Is the next step blocked on a run? Pick up every unblocked step first; then wait for the
run in the foreground, bounded, and continue in the same turn.
