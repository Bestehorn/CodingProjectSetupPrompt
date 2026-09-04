# Issue Work Orchestrator (Kiro CLI port)

The Kiro CLI twin of the Claude Code
[`issue-work-orchestrator`](../../claude-agents/issue-work-orchestrator/README.md): an
autonomous, main-session agent that works a project's entire open-issue backlog end to
end — select, claim, fix through the embedded spec/TDD engine, prove, PR, drive CI green,
merge, clean up, close, repeat. The agent definition is
[`issue-work-orchestrator.md`](issue-work-orchestrator.md); the Kiro agent config is
[`KiroCLIAgent-IssueWorkOrchestrator.json`](KiroCLIAgent-IssueWorkOrchestrator.json).
The lifecycle, the standing disciplines, and the escalation contract are documented in
the Claude twin's README — this port differs in host paths (`.kiro/…`), a four-subagent
concurrency cap, and the gate semantics below.

## Maintainer notes (hook internals and Claude-gate comparison)

These details were moved out of the agent definition to keep its always-loaded footprint
small. They are load-bearing for MAINTAINING the hooks, not for running the agent — the
definition states the behavioral consequences and points here.

### Script line citations (as shipped)

- `kiro-loop-gate.sh` reads each state field with
  `grep -iE "^[*-]?[[:space:]]*<Name>:" | tail -1`
  (`cli-agents/spec-workflow/hooks/kiro-loop-gate.sh:75`) — hence LAST occurrence wins
  and a bold `**Name:** value` spelling matches nothing.
- Its block condition (`kiro-loop-gate.sh:78-96`): block only while `Status` matches
  `IN_PROGRESS` AND `AWAITING_USER` is `none`/`-`/empty AND `WORKABLE_ISSUES_REMAIN`
  matches `^(yes|true)$`. It does not read `Phase`.
- It resolves state from the registry's `state_dir`, else
  `runs/<first-8-of-session_id>/` (`kiro-loop-gate.sh:62-67`), and at line 73 it
  **exits 0 — a silent no-op — when that `resume_state.md` is absent**.
- `kiro-session-register.sh` derives identity mechanically from the stdin `session_id`
  (`run_id = ${session_id:0:8}` at `kiro-session-register.sh:43`,
  `state_dir = "runs/$run_id/"` at `:54`), and performs its entire registry upsert
  inside `if command -v jq >/dev/null 2>&1` with no fallback (lines 49-62) — on a host
  without `jq` it creates `registry.json` as `{}` and records no entry. It never creates
  `runs/<run-id>/` and never writes a state file (unlike the Claude Code
  `session-register.sh`, which seeds both state files).
- `kiro-stop-gate.sh` falls back to `ls -t` over every `workflow_state.md` in the clone
  (`kiro-stop-gate.sh:65`), so with concurrent runs it can judge a run against a
  SIBLING's state instead of going quiet.

### How the corrected Claude Code loop gate differs (NOT ported here)

The Claude Code sibling gate (`issue-loop-gate.sh`) was corrected after measured
incidents, and now works differently in three ways rather than one:

1. `WORKABLE_ISSUES_REMAIN` selects only the refusal's WORDING — it gates nothing.
2. The block turns on whether the run has CLAIMED tracked work — a non-placeholder
   `CURRENT_ISSUE`, a non-placeholder `CURRENT_SPEC`, or a `MODE` naming an orchestrator
   mode — and is released only by an explicitly idle `Status`, a terminal `Phase` **or**
   `Status` (whole-value), or a substantive `AWAITING_USER`.
3. Its polarity is INVERTED: a `Status` it does not recognise as idle counts as work in
   flight, not as nothing to hold.

NONE of that is ported to the Kiro gate: it still tests the literal `IN_PROGRESS`, still
tests `WORKABLE_ISSUES_REMAIN`, and still ignores `Phase` entirely. The agent definition
states the Kiro behavior and this difference rather than assuming the port. On the Claude
Code gate `Phase` is one of the two fields whose terminal value releases the brake, and
the seeded `SESSION_ID:` line is used as a recovery rung — two more reasons the
definition tells runs to record `Phase` and keep `SESSION_ID` intact even though the
local gate reads neither.

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
