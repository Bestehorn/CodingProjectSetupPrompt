# Issue Work Orchestrator (Kiro CLI port)

The Kiro CLI twin of the Claude Code
[`issue-work-orchestrator`](../../claude-agents/issue-work-orchestrator/README.md): an
autonomous, main-session agent that works a project's entire open-issue backlog end to
end — select, claim, fix through the embedded spec/TDD engine, prove, PR, drive CI green,
merge, clean up, close, repeat. The agent definition is
[`issue-work-orchestrator.md`](issue-work-orchestrator.md); the Kiro agent config is
[`KiroCLIAgent-IssueWorkOrchestrator.json`](KiroCLIAgent-IssueWorkOrchestrator.json).
The lifecycle, the standing disciplines, the escalation contract, and the fixed Completion
Block that ends every run (identical on both hosts) are documented in the Claude twin's
README — this port differs in host paths (`.kiro/…`), a four-subagent concurrency cap, and
the gate semantics below.

## Maintainer notes (hook internals and Claude-gate comparison)

These details were moved out of the agent definition to keep its always-loaded footprint
small. They are load-bearing for MAINTAINING the hooks, not for running the agent — the
definition states the behavioral consequences and points here.

### The gates are the Claude Code gates

Since the 2026-10-01 rewrite the Kiro hooks are Python and SHARED with Claude Code:
`kiro_hooks.py` runs `hooklib.py` and the `gate_*.py` modules from
`claude-agents/spec-workflow/hooks/` with the Kiro host (`.kiro/agent-state/`,
`.kiro/steering/`, `.kiro/hooks-bin/`). Everything the previous section of this file
recorded as "not ported" is therefore in force on Kiro too, and the bash-era citations are
gone with the scripts:

- State fields are the LAST plain `Name: value` line outside a fenced block, trimmed,
  case-insensitive; a bold `**Name:** value` spelling matches nothing (`hooklib.parse_state`).
- The `issue-loop-gate` holds the turn while the run has CLAIMED tracked work — a
  non-placeholder `CURRENT_ISSUE`, a non-placeholder `CURRENT_SPEC`, or a `MODE` naming an
  orchestrator mode — and releases only on an explicitly idle `Status`, a terminal `Phase`
  **or** `Status` (whole-value), or a substantive `AWAITING_USER`. Its polarity is inverted:
  an unrecognised `Status` is work in flight. `WORKABLE_ISSUES_REMAIN` selects the refusal's
  wording and gates nothing.
- Identity resolves through three session-keyed rungs (the registry's `state_dir`,
  `runs/<first-8-of-session_id>/`, a `runs/*/resume_state.md` recording this `SESSION_ID`).
  A registered session with no state file is `BROKEN` and the Stop gates fail CLOSED on it;
  an unregistered session is a deliberate no-op. There is no `ls -t` fallback anywhere.
- The `session-register` gate SEEDS `runs/<run-id>/resume_state.md` + `workflow_state.md`
  before writing the registry entry, and the registry is read and written as JSON by the
  interpreter — nothing depends on `jq`.
- Each Stop gate keeps a per-run consecutive-block counter (default 8,
  `KIRO_STOP_BLOCK_CAP`) that resets on progress and writes a durable give-up marker at the
  cap; a Kiro block is `{"decision":"block","reason":"..."}` on stdout with exit 0.

The behaviour is pinned by the shared pytest modules under
`claude-agents/spec-workflow/hooks/tests/` (installed to `.kiro/hooks-bin/tests/`).

The measured incident behind the never-invent-a-run-label rule happened on the Claude
Code sibling: an agent told to "derive RUN_ID" wrote its state under a tidy self-chosen
label (`run-issue574-…`); both Stop hooks were silent no-ops for the entire session —
neither had ever blocked a turn-end in that clone across 189 registered sessions — and
that run ended FOUR turns while under an explicit standing instruction never to stop
without a proven reason. Full account: Incident `invented-run-label` in
[`../../claude-agents/spec-workflow/hooks/MIGRATION.md`](../../claude-agents/spec-workflow/hooks/MIGRATION.md)
§Incident record.

## Procedure changelog (maintainers)

- **SELECT's tracker claim was once a hand-rolled sequence** (re-fetch → additive-label →
  assign → re-read-verify) whose verification was the agent's to remember. It was
  superseded by the wrapper's single fail-closed `issue start <X>` (GitHub
  `start-issue`), which performs the same sequence and exits non-zero if the claim did
  not land; the definition now states only the current command. The live trap that stays
  documented inline is the whole-set `issue update --labels` replace, which silently
  drops other labels.
