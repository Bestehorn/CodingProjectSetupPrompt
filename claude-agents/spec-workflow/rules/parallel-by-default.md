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
- **Independent issues.** Separate issues run in separate worktrees and sessions.

## What waits, and how

Never `sleep`-poll in a tool call. A CI run, a deploy or a merge is waited on with the
wrapper's blocking `wait` subcommand run as a BACKGROUND task; its completion re-invokes
you. Anything else that must be waited for — a local process, a file that must appear —
is awaited by running THAT command with `run_in_background: true`, never by a foreground
sleep. The `no-foreground-sleep` gate refuses a foreground wait of 10 s or more and any
sleep inside a loop. Meanwhile do every piece of work that does not depend on the verdict.
Idling on a pipeline is a stop in disguise (`continuous-work.md`); every shell call is the
expensive tool (`native-tools-over-shell.md`).

## Self-check before any dispatch

Could this call run alongside the previous one? If yes, they belong in the same message.
Is the next step blocked on a run? Start the wait in the background and pick up the next
unblocked step.
