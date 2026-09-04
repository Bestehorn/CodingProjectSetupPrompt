# Agent State & Decision-Log Convention (ALL agents)

Shared by EVERY custom agent in this project. It codifies (1) where agent state lives,
(2) how state fields are written so the hooks can read them, and (3) an append-only,
cross-agent **decision log**.

## 1. State directory

Every agent keeps its resume/log artifacts under:

```
.claude/agent-state/<agent-name>/
```

`<agent-name>` is the agent's canonical `name:` frontmatter (e.g. `spec-conductor`,
`dead-code-removal-agent`). Typical artifacts: `resume_state.md` (Status + phase +
counters + git HEAD + source mtimes), `iteration_log.md`, `evidence_ledger.md`. Create
the directory on first use. Archive a completed/stale artifact by suffixing an ISO
timestamp; never delete history. `.claude/agent-state/` is gitignored. The spec-workflow
master state lives at `.claude/agent-state/spec-conductor/workflow_state.md`.

## 1a. Registered runs — read the run-identity contract BEFORE the first state write

Any workflow that runs as a REGISTERED run — the issue-work-orchestrator entry points,
the spec workflow, single-issue work — is bound by the run-identity contract in
**`.claude/docs/run-identity.md`**. Read that file before writing any state in such a
run. It is the AUTHORITATIVE copy of: per-run namespacing (`runs/<run-id>/`,
`registry.json`, locks), the seeded field set and values, the gate-release vocabulary,
and the `OWNED`/`UNREGISTERED`/`BROKEN` verdicts. Its two headline obligations, binding
even before you read it:

- **The run id is REGISTRY-DERIVED — never invent or "improve" a run-id label.** Use the
  `state_dir` that `registry.json` records for THIS `session_id`, verbatim. (MEASURED: a
  self-chosen readable label left every Stop gate inert for 189 sessions — Incident
  `invented-run-label` in `.claude/hooks/MIGRATION.md`.)
- **Keep the seeded `SESSION_ID:` line intact** — it is the rung by which a hook recovers
  a misplaced run.

## 1b. Field semantics (how EVERY state field is written)

Hooks read **the LAST occurrence of a plain `Name: value` line**. Therefore:

1. Correct a value by **APPENDING a new block at the END of the file** — never edit an
   earlier block, never prepend.
2. **A bold spelling (`**Name:** value`) is read by NO hook.** Write fields plain.
3. A human-facing summary must be PROSE with no `Name: value` lines of its own.
4. A `Name: value` line inside a fenced code block is IGNORED.
5. Terminal/idle values are matched WHOLE-VALUE (`Phase: DONE`, never
   `Phase: DONE (was IMPLEMENT)`); the accepted vocabulary is
   `.claude/docs/run-identity.md` §5.

## 2. The decision log (mandatory for all agents)

Whenever an agent makes a **non-trivial decision** — a design choice, a classification,
a fix approach, a candidate selection, a convergence/exit call, an escalation — it
appends one entry to a decision log. This is the durable record other agents and later
sessions read to understand *why* the project is the way it is. Not optional, and not
only for the spec agents.

### Where to write

- In a **spec context** (a `.claude/specs/<feature>/` directory is the subject):
  `.claude/specs/<feature>/decisions/decision-log.md`.
- Otherwise: `.claude/agent-state/<agent-name>/decision-log.md`.

Create the file with an `# Decision Log` header on first use.

### Entry schema (fixed, append-only)

```markdown
## DL-<nnn> — <ISO-timestamp> — <agent-name> — phase:<PHASE-or-"n/a">

**Decision:** <one sentence: what was decided>
**Driver:** <what forced it — requirement IDs, finding IDs (A2/B1), user answer Q###, a failing test, an MCP source>
**Alternatives considered:** <one line each, or "none">
**Evidence:** <path:line | command output ref (evidence/...) | review/<r>/iteration-NN.md#A2 | MCP/web citation>
**Supersedes:** <DL-mmm, or "none">
**Artifacts touched:** <files written/edited>
```

### Rules

1. **Append-only.** Never edit or delete a prior entry; supersede it with a new one.
2. **Monotonic IDs.** Next number is `max(existing DL-NNN) + 1` — the file is
   authoritative; never restart at 001 on resume. **Under concurrency**, give each run
   its OWN `runs/<run-id>/decision-log.md` (preferred) or serialize appends behind the
   registry lock; spec-context decisions still go to the spec's log.
3. **Evidence required.** Every entry cites concrete evidence (`no-guessing.md`). A
   decision with no citable driver is itself a defect.
4. **Granularity.** Record decisions, not narration. The conductor writes an entry per
   phase transition and applied finding-batch; a reviewer per material classification
   call; an implementer per task.

The ported agents (dead-code, doc-review, ci-worker, issue-housekeeping, issue-intake,
product-management, cv/*) inherit all of this without body edits — the rule is
always-loaded and referenced from `CLAUDE.md`.
