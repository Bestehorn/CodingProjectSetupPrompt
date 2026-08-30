# Agent State & Decision-Log Convention (ALL agents)

This rule is shared by EVERY custom agent in this project — the spec-workflow
agents AND the ported agents (dead-code, doc-review, ci-worker, issue-housekeeping,
issue-intake, product-management, the cv/* suite). It is installed at
`.claude/rules/agent-state-convention.md` (no `paths:` frontmatter → always loaded)
and is pointed to from the project's root `CLAUDE.md`, so every agent observes it
without its own body being edited.

It codifies two things that the agents already do informally, and makes them
uniform and mandatory: (1) where agent state lives, and (2) an append-only,
cross-agent **decision log** so decisions and the discussion behind them are
preserved for later agents and future sessions.

## 1. State directory

Every agent keeps its resume/log artifacts under:

```
.claude/agent-state/<agent-name>/
```

`<agent-name>` is the agent's canonical name (its `name:` frontmatter, e.g.
`spec-conductor`, `dead-code-removal-agent`, `cv-editor`). Typical artifacts:
`resume_state.md` (Status + phase + counters + git HEAD + source mtimes),
`iteration_log.md`, `evidence_ledger.md`, and any agent-specific logs. Create the
directory (and missing parents) on first use. Archive a completed/stale artifact by
suffixing an ISO timestamp (e.g. `resume_state.2026-06-09T14-02-11Z.md`); never
delete history. `.claude/agent-state/` is gitignored (per-run runtime state).

The spec-workflow master state lives at
`.claude/agent-state/spec-conductor/workflow_state.md`.

### 1a. Per-run namespacing when multiple runs share one clone

A single-run agent uses the flat layout above. But an agent of which **multiple
instances may run concurrently in one clone** (notably `issue-work-orchestrator`) MUST
namespace its state per run so runs never share a `resume_state.md`/`workflow_state.md`
slot:

```
.claude/agent-state/<agent-name>/
  registry.json                 # session_id -> { session_id, run_id, cwd, state_dir,
                                #                 status, started_at, last_heartbeat }
  .locks/<resource>.lock        # per-resource mkdir locks (atomic create-or-fail; NTFS-safe)
  .stop-gate-counters/          # <gate>-<first-8-of-session-id>.count, plus the durable
                                # .capped marker and the .fingerprint beside it (see 1f)
  .hook-decisions/<date>.log    # one line per hook invocation: allow / block / why (see 1f)
  runs/<run-id>/                # ONE run's private state subtree
    resume_state.md             # SEEDED by session-register.sh — see 1c
    workflow_state.md           # SEEDED by session-register.sh — see 1c
    contract-ack-<version>      # existence = this run has ingested that contract version
    environment.md  issue_queue.md  iteration_log.md
```

Run identity is established by the **SessionStart hook `session-register.sh`**, which
writes `registry.json` keyed by the harness `session_id` (stable per run) and derives
`run_id` from it. The agent and the gate hooks both resolve "which run owns this session"
via that registry — no environment variable carries identity (consistent with
`no-environment-vars`). A LIVE run = an entry with active `status` and a fresh
`last_heartbeat`; stale entries/locks are reclaimed only when the heartbeat is past its
declared bound AND the worktree pointer no longer resolves AND the run's status is terminal
(archive, never delete).

Those seven keys are the WHOLE of what the hook writes, and the entry carries **no
`current_issue`** — an earlier version of this section listed one. Which issue a run has
claimed lives in `runs/<run-id>/resume_state.md` as `CURRENT_ISSUE`, which is where every gate
reads it and the only place it is authoritative; a reader that wants it must open that file.
`state_dir` is written WITH a trailing slash (`runs/<run-id>/`) and the resolver strips it, so
do not "correct" it. `status` (seeded `starting`) and `last_heartbeat` are stamped at each
SessionStart and are the AGENT's to maintain after that — no hook refreshes them mid-run, so
the liveness test above is only as current as the run's own bookkeeping.

**All five hooks** — `session-register.sh`, `continuous-work-reinject.sh`, `issue-loop-gate.sh`,
`spec-stop-gate.sh` and `spec-tdd-gate.sh` — resolve THIS session's run through the shared
`hooks/hook-state-lib.sh`, every rung of which is keyed on the session id and which has no
most-recently-modified rung at all.

That the resolver is a shared LIBRARY rather than a convention each hook follows is itself a
consequence of measurement: the "resolve by most recently touched" defect was found
INDEPENDENTLY in THREE separate hooks. Each had hand-rolled its own registry read, with its own
`command -v jq` guard and its own `ls -t … | head -1` fallback — and because `jq` was absent on
the host, all three took the fallback every time. Three copies of a resolver meant three chances
to get it wrong, and all three took it. Add no fourth copy: if a new hook needs to know which run
it belongs to, source the library.

### 1b. The run id is REGISTRY-DERIVED. An agent-authored label is a DEFECT.

`session-register.sh` computes `run_id` from the harness `session_id` and writes the
resulting `state_dir` into `registry.json`. **The agent uses that value verbatim.** It does
not derive its own, does not translate it into something more readable, and does not append
an issue number or a timestamp to it.

That is a mechanical requirement, not a style preference, because the alternative was
MEASURED and it silently disabled every Stop gate in a clone:

- the hook wrote `state_dir: "runs/<first-8-of-session-id>/"` and **created nothing** — no
  directory, no state file;
- the agent, following its own instruction to "derive `RUN_ID`", produced a readable label
  (`run-issue574-20260828T194800Z`) and wrote its state there instead;
- both Stop gates resolve state from the registry and then `exit 0` when it is absent, so the
  two namespaces never met. Every gate was inert from turn one. Across **189 registered
  sessions in that clone, neither Stop gate had EVER blocked a turn-end**, and a run holding
  an explicit instruction never to stop without a proven reason ended four turns unopposed.

Nothing about the invented label looked like a fault from the inside: the state file was
well-formed, complete, current, and sitting in a directory whose name read *better* than the
one the hooks key on. That is precisely why the rule is "verbatim" rather than "meaningful" —
a tidy, readable run label is what this failure looks like while it is happening.

If a hook ever tells you your run state is missing, the repair is to create the path IT
names, verbatim. Do not reconcile the difference in the other direction.

### 1c. `session-register.sh` SEEDS the state, so the gates are reachable from turn one

The hook no longer merely describes where state ought to go. It creates `runs/<run-id>/` and
writes both state files if they are absent (it never overwrites an existing one), so every
field a gate branches on holds a real value before the agent's first action. A gate then
evaluates state instead of exiting on a missing file.

The seeded field set — all plain `Name: value` lines:

| File | Seeded fields |
|---|---|
| `resume_state.md` | `SESSION_ID`, `RUN_ID`, `STATE_DIR`, `MODE`, `Status`, `Phase`, `CURRENT_ISSUE`, `BRANCH`, `WORKTREE`, `PR`, `WORKABLE_ISSUES_REMAIN`, `AWAITING_USER` |
| `workflow_state.md` | `SESSION_ID`, `RUN_ID`, `CURRENT_SPEC`, `Phase`, `Status`, `CURRENT_TASK` |

The seeded VALUES, which matter as much as the names: `Status` and `Phase` are `NOT_STARTED` in
both files; `MODE` is `unset`; `CURRENT_ISSUE`, `BRANCH`, `WORKTREE`, `PR`, `AWAITING_USER` and
`CURRENT_TASK` are `none`; `WORKABLE_ISSUES_REMAIN` is `unknown`; and `CURRENT_SPEC` is seeded
EMPTY rather than `none`. Every one of those — `unset`, `none`, `unknown`, empty — is in the
placeholder vocabulary of §1d-bis, which is what makes a freshly seeded run ungated twice over:
its `Status` is affirmatively idle, AND it has claimed no tracked work. The hook also pre-writes
`contract-ack-<version>`: a session seeded by this hook is running under the contract shipped
beside it, so blocking it once to deliver a contract it already has would be a gratuitous
interruption.

### 1d. Field semantics: LAST occurrence wins, plain spelling only

Every hook that reads a field takes **the LAST occurrence of a plain `Name: value` line** in
the file. Four consequences, all load-bearing:

1. **Correct a value by APPENDING a new block at the END of the file.** Never edit an earlier
   block, and never prepend. A block at the top of the file is what a human reads and what NO
   hook reads.
2. **A bold field spelling is read by NO hook** — that is, `Name:` wrapped as a bold run with
   a leading and trailing pair of asterisks. The matcher permits a single leading `*` or `-`
   before the name, so a bold field is *invisible* rather than merely out-competed by a later
   one. This is the failure mode that looks most like success: the file documents the right
   value and every gate reads an empty string. Write fields plain; use bold in prose only.
3. **A human-facing summary must be PROSE, with no `Name: value` lines at all.** A narrative
   recap that happens to contain `Status: blocked on review` becomes the authoritative last
   occurrence of `Status` and silently overrides the real record.
4. **A `Name: value` line inside a fenced code block is IGNORED.** An example, a quoted
   instruction, or a pasted transcript is not a field. (Before fence tracking it WAS: a fenced
   `Status: inside a fenced code block` was returned as the run's Status, and last-occurrence-wins
   made a late example beat the real record.)

### 1d-bis. THE FIELD VOCABULARY — the values a gate actually recognises

This section exists because its absence was a measured defect. The primary brake used to arm only
on the exact token `IN_PROGRESS`; every other value was read as "nothing to hold", and **nothing
anywhere told an agent that.** MEASURED on a correctly seeded, registered, contract-acked run
recording `Phase: IMPLEMENT` and `CURRENT_ISSUE: 574`, all of these let the turn end: `in progress`,
`In Progress`, `in-progress`, `WORKING`, `ACTIVE`, `RUNNING`, `IMPLEMENTING`. The gate depended on
the agent guessing one magic string.

The polarity is now INVERTED, so guessing wrong is safe: **an unrecognised `Status` means work is in
flight.** Only an affirmative statement releases the brake.

| Field | Values that RELEASE a Stop gate | Everything else means |
|---|---|---|
| `Status` | `NOT_STARTED`, `NOT_YET_STARTED`, `UNSTARTED`, `NOT_IN_PROGRESS`, `NOT_WORKING`, `IDLE`, `PENDING`, `NEW`, `NONE`, `UNSET` (whole value, any case) | work in flight |
| `Phase` or `Status` | `DONE`, `COMPLETE`, `COMPLETED`, `FINISHED`, `CLOSED`, `ABANDONED`, `ESCALATED`, `CANCELLED`, `CANCELED` (whole value, any case) | not finished |
| `AWAITING_USER` | a SUBSTANTIVE reason — see below | no escalation recorded |
| `CURRENT_ISSUE`, `CURRENT_SPEC`, `BRANCH`, `WORKTREE`, `PR`, `MODE` | EMPTY, anything from `<` to `>`, or `none`, `-`, `--`, `n/a`, `na`, `unset`, `unknown`, `empty`, `null`, `nil`, `tbd`, `todo`, `pending`, `placeholder`, `xxx` (whole value, any case) = NOTHING RECORDED | a real recorded value |

Five consequences worth internalising:

- **A terminal value must be the WHOLE value.** `Phase: DONE` releases; `Phase: waiting to be DONE`
  does not, and neither does `Status: COMPLETED (was IN_PROGRESS)`. That is why the synonym list is
  generous — a whole-value test against a narrow vocabulary would refuse an agent for its choice of
  word.
  This rule is where two adversarial reviews of the gates disagreed, so the reasoning is recorded
  rather than left implicit. One measured the narrative `COMPLETED (was IN_PROGRESS)` being refused
  and called it an over-block. The other measured `IN_PROGRESS - tasks 1-3 completed, 4 remaining`
  DISARMING the evidence gate through a substring match, noting that the phrasing "is not
  adversarial; it is how a progress note is naturally written". Both describe the same value shape,
  so only one rule can hold, and fail direction decides: a whole-value match costs a spurious refusal
  that names its own escape, while a substring match lets an agent end a turn by writing a progress
  note. **Write the status as a bare token and put the narrative in prose.**
- **`AWAITING_USER` must name a real reason.** It is a self-issued permission slip, so it is checked
  for substance, not mere presence: a placeholder, a one-word token (`no`, `false`, `0`, `waiting`,
  `blocked`, `?`), or anything shorter than a dozen characters is REJECTED. Measured releases
  included `<reason>` — the literal placeholder the gate itself used to print, so an agent copying
  the instruction verbatim disarmed the brake with the gate's own string. Write the reason you would
  give a person: `AWAITING_USER: waiting on the production credential for the smoke test`.
  BOTH gates apply the SAME substance test (`hook_is_substantive_escalation`), so a one-word token
  releases neither. The evidence gate previously released on any NON-PLACEHOLDER value — a
  fail-open wherever it is the only Stop hook registered. Both gates DO honour the field, which
  they did not always: measured, after an agent recorded a genuine escalation exactly as
  instructed, the loop gate allowed while the evidence gate — which then read the field not at all
  — still refused and told it to "continue". A mechanism must not contradict the contract it
  delivers.
- **The placeholder list above is CLOSED and exact — it is the authoritative copy of what the
  code recognises, so read it as a list and not as a flavour.** Two tests, in this order. First
  by SHAPE: any value that BEGINS with `<` and ENDS with `>` is a placeholder whatever sits
  between them, which is what rejects the gate's own former `AWAITING_USER: <reason>` line, and
  equally `<N>`, `<your-run-id>` or `<path to the spec>`. Then by WORD, whole-value and
  case-insensitively, against exactly the fifteen tokens listed — no others, so `unclaimed`,
  `nothing` or `0` are REAL values. Leading and trailing whitespace is stripped before either
  test, which is deliberate in both directions: measured, an untrimmed `AWAITING_USER: none `
  compared unequal to `none` and so read as a recorded escalation, DISABLING the primary brake,
  while an untrimmed `CURRENT_SPEC: x ` produced the unopenable path `x /tasks.md` and refused
  every turn-end with no escape an agent could find.
- **`Status: IN_PROGRESS` alone does NOT hold a turn.** `session-register.sh` registers and seeds
  EVERY session, including ordinary chat sessions, so the loop gate's brake additionally requires
  evidence that TRACKED WORK was claimed: a real `CURRENT_ISSUE`, a `CURRENT_SPEC`, or a `MODE`
  naming an orchestrator mode (`ISSUE_LOOP`, `SINGLE_ISSUE`, `SPEC`, `BACKLOG`, `AUTO`). Without
  that, an ordinary session that recorded a Status was refused and told to "FINISH issue none end to
  end". Every orchestrator entry point records at least one of them, so the brake keeps its full
  reach over the runs it exists for. (The evidence gate has no claim test; what scopes it is the
  spec workflow's own phase — it acts only at `IMPLEMENT`/`VERIFY`, matched as a WORD and in
  uppercase, so `NOT_IMPLEMENTED` and `PRE_IMPLEMENT_REVIEW` are outside it and `Phase: implement`
  is inside it.)
  The `MODE` test is a PREFIX match, case-insensitive, with hyphens normalised to underscores, so
  `single-issue` and `SINGLE_ISSUE_574` both count. That normalisation is not cosmetic: `/work-issue`
  instructed `MODE: single-issue`, the earlier predicate did not match it, and an unmatched `MODE`
  means LESS blocking — a fail-open produced by a document and a regex drifting apart.
- **`WORKABLE_ISSUES_REMAIN` gates NOTHING.** It once WAS the block condition, and that is how
  `/work-issue` runs — which set it to `no` deliberately — came to be ungated by the one hook most
  likely to be needed there. Today it selects the refusal's WORDING and feeds the loop gate's
  progress fingerprint. It can neither hold a turn nor release one, so do not write it expecting
  either, and read any claim that it is the gate condition as describing the version that had that
  hole.

### 1e. `SESSION_ID:` is load-bearing

`SESSION_ID` is not documentation. It is the third resolution rung: when no registry
`state_dir` and no `runs/<first-8-of-session-id>/` resolves, the library scans
`runs/*/resume_state.md` for a recorded `SESSION_ID` matching this session. That is what
recovers a run whose state was written under a differently-named directory — the 1b failure —
and it is still session-derived, so it can only ever return state belonging to this session.

Never remove or rewrite it. **And note what it is not:** it is a repair rung for a naming
deviation, not a licence to choose your own directory name because the rung will find it. It
also only works for a run that got `SESSION_ID` written down, so it cannot rescue a run that
skipped it.

The scan is STRICTER than an ordinary field read, and the difference is worth knowing before you
rely on it. It matches a line that is ONLY `SESSION_ID: <this session>` — no list marker,
nothing after the value — so a `- SESSION_ID: …` bullet or a trailing comment is read by the
ordinary field reader and yet invisible to this rung (a bold spelling is invisible to both, per
1d). It is also the one read in the family with no fence tracking, so never paste another
session's id into your state file, not even inside a code fence: it is matched wherever it
appears, and this rung's whole value is that it can only ever return state belonging to the
session asking.

### 1f. The three identity verdicts, and why `BROKEN` must fail CLOSED

Resolution yields one of exactly three verdicts, and a gate must branch on the verdict —
never on "is the file there":

| Verdict | Means | Gate behaviour |
|---|---|---|
| `OWNED` | a session-keyed run directory resolved and has a `resume_state.md` | judge the run on its own recorded state |
| `UNREGISTERED` | the registry knows nothing about this session and no rung found state | **no-op.** A plain chat session looks exactly like this and must never be blocked |
| `BROKEN` | the registry DECLARES a run for this session, but no rung found a state file | **fail CLOSED — block the turn-end** |

`BROKEN` is the whole point of the split. "No state" and "nothing to guard" are different
facts, and collapsing them into a single `exit 0` *is* the defect this convention exists to
prevent: a run that never established its state has violated the contract, and the gate that
cannot judge it must refuse the stop rather than wave it through. A gate that goes quiet
exactly when its own inputs are missing is not a lenient gate; it is an absent one, and its
absence is invisible. A verdict a gate does not RECOGNISE is normalised to `BROKEN` for the same
reason: measured with a single `set -u` slip in the resolver, the substitution's subshell
aborted, the verdict was EMPTY, it matched no guard, and the gate fell through to its field
reads and ALLOWED — while logging a line that read like a decision.

Two bounds keep that refusal from wedging a session, and neither weakens the verdict:

- Each gate keeps its **own consecutive-block counter** (`HOOK_BLOCK_CAP`, default 8, validated
  into [1, 64] so that a typo like `abc` or a `0` cannot silently disable the brake). At the cap
  the gate allows the stop *while saying explicitly that the work is not done*, so a bounded
  give-up can never be misread as completion — and it records that give-up in a **durable
  `.capped` marker** beside the counter, so the stand-down persists rather than expiring. That
  marker is the whole point: while the cap path merely reset the counter, MEASURED over eleven
  consecutive Stop events, attempts 1-8 were refused, attempt 9 was released, and attempts 10-11
  began refusing again — a duty cycle, and a session wedged at 8-of-9 while being told it was
  not. **What clears the count and the marker is a genuine release** — a pass on the merits
  (`hook_counter_reset`), not a stand-down: neither reaching the cap nor standing down on an
  unwritable counter clears anything. The LOOP gate has one further reset: it fingerprints the
  fields it reads (`Status`, `Phase`, `CURRENT_ISSUE`, `AWAITING_USER`, `BRANCH`,
  `WORKABLE_ISSUES_REMAIN`) and clears count and marker whenever that fingerprint CHANGES, so a
  run that is genuinely advancing never reaches the cap and the "no change in the recorded
  state" wording is true when it is printed. The evidence gate does the same over its OWN subject —
  the phase, the spec, and the name and size of every capture under it — so new evidence clears its
  count too.
  The library reads `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` for that default if it is already set in
  the harness's own environment; that is a description of the code, not licence for an agent to
  set it — `no-environment-vars` still applies.
- The gates no longer read the harness's `stop_hook_active` field. Honouring it made a POLICY
  gate block at most ONCE per continuation chain — nudge once, then free to stop on unfinished
  work — which is not a loop guard but an expiry date.

Every invocation appends one line to `.hook-decisions/<date>.log` (allow or block, and why).
Stderr behaviour is unchanged, so the "an ungated exit produces no message" property still
holds; the log is what makes a permanently inert gate *visible* instead of indistinguishable
from a satisfied one. If you want to know whether these gates are working in a given clone,
read that log — the 189-session failure above was diagnosable from the absence of a directory
that only the blocking path creates.

## 2. The decision log (mandatory for all agents)

Whenever an agent makes a **non-trivial decision** — a design choice, a
classification, a fix approach, a candidate selection, a convergence/exit call, an
escalation — it appends one entry to a decision log. This is the durable record
other agents and later sessions read to understand *why* the project is the way it
is. It is NOT optional and it is NOT only for the spec agents.

### Where to write

- If the agent is operating in a **spec context** (a `.claude/specs/<feature>/`
  directory is the subject of the work), append to:
  `.claude/specs/<feature>/decisions/decision-log.md`.
- Otherwise (an agent with no spec context, e.g. dead-code or doc-review on a
  general run), append to:
  `.claude/agent-state/<agent-name>/decision-log.md`.

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

1. **Append-only.** Never edit or delete a prior entry. To change a past decision,
   write a NEW entry whose `Supersedes:` points at the old `DL-mmm`.
2. **Monotonic IDs.** `DL-001`, `DL-002`, … never reused, never rewound. The next
   number is `max(existing DL-NNN) + 1` — scan the file to determine it (the file is
   authoritative; do not restart at 001 on a resumed session). **Under concurrency:**
   when multiple runs could append to the SAME decision log, two runs computing
   `max+1` independently produce duplicate IDs. Either serialize appends to the shared
   log behind the registry lock, OR (simpler and preferred) give each run its OWN
   `runs/<run-id>/decision-log.md` and reserve the agent-root `decision-log.md` for
   cross-run notes. Spec-context decisions still go to the spec's
   `decisions/decision-log.md`.
3. **Evidence required.** Every entry cites concrete evidence (this reuses the
   project's No-Guessing rule). A decision with no citable driver/evidence is itself
   a defect — gather the evidence or do not record the decision as made.
4. **Granularity.** Record decisions, not narration. One entry per decision; do not
   log every file read. The conductor writes an entry at each phase transition and
   after each applied finding-batch; a reviewer writes an entry for each material
   classification call it could not derive mechanically; an implementer writes an
   entry per task for the approach taken (citing the design section it implements).

### For the ported agents (no body rewrite)

The ported agents already maintain `.claude/agent-state/<agent>/` state. This rule
ADDS the decision-log requirement to them uniformly: when any of them makes a
decision of the kind listed above, it appends a `DL-NNN` entry per the schema, to
the spec `decisions/decision-log.md` if a spec context exists, else to its own
state dir. No change to their prompt bodies is needed — they inherit this because
the rule is always-loaded and referenced from `CLAUDE.md`.
