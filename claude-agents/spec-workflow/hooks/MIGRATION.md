# Reaching a LIVE session: how an already-running agent picks up new rules

**The question this answers.** You deploy a change to a project's `.claude/` setup — new rules,
new gate logic, a new contract. The project has several worktrees with agents already working in
them. Those sessions started *before* the change. **How do they pick it up, without being
restarted and without losing their place?**

This matters because of what the change usually IS. The gates exist to stop an agent ending a
turn on unfinished work. A migration mechanism that only reaches *new* sessions leaves exactly
the long-running sessions — the ones most likely to stop, because they have been going longest
and have been compacted most — running the old, broken behaviour until they finish or die. The
population you cannot reach is the population you needed.

Every documentation quote below is from the Claude Code hooks reference
(`https://code.claude.com/docs/en/hooks`) and hooks guide
(`https://code.claude.com/docs/en/hooks-guide`), checked 2026-08-30. Where something is
**observed** rather than documented, it says so.

---

## 1. What a live session CAN and CANNOT pick up

| Change | Reaches a LIVE session? | Basis |
|---|---|---|
| **Editing an already-registered hook SCRIPT** | **YES — at its next invocation, guaranteed** | The registration names the interpreter and the script PATH, never the script's contents, so each invocation spawns a fresh interpreter that reads the file from disk. Observed, not documented — see §5. |
| **Editing a file a registered hook READS** (`CONTRACT_VERSION`, `hook-state-lib.sh`, state files) | **YES** | Same reason, one level down: the hook reads it at invocation time. |
| **Registering a NEW hook in `settings.json`** | **USUALLY, but on the new hook's own event cadence** | "Direct edits to hooks in settings files are normally picked up automatically by the file watcher." So the registration itself lands mid-session. **When it then FIRES depends on the event** — see the two rows below. |
| → a new **`Stop`** hook | **YES, at the next turn-end attempt** | `Stop` fires on every attempt to end a turn, so a reloaded registration is exercised almost immediately. |
| → a new **`SessionStart`** hook | **Only at the next SessionStart EVENT** | It will not fire in the middle of a turn. With `matcher: "compact|resume|startup"` it does fire again on a compaction — **observed**: this project's `continuous-work-reinject.sh` fired as `SessionStart:compact` in a long-running session. But the timing is not yours to choose. |
| **Adding a file under `.claude/rules/`** | **NO, not by itself** | Rules enter context by being loaded. A live session's context already exists; a new file on disk does not walk into it. |
| **Editing an always-loaded rule the session already loaded** | **PARTIALLY** | Root `CLAUDE.md` and always-loaded rules are re-injected on compaction/resume, so an edit lands at the *next* compaction — unpredictable timing, not a mechanism. |
| **Adding a slash command** | **NO** | Requires the user to invoke it, which is not "the session picks it up". |
| **Changing an agent definition** | **NO** | The system prompt is fixed at spawn. |

**The load-bearing consequence:** put every change that must reach a live session inside an
**already-registered `Stop` hook**. Not because a new registration cannot arrive — it normally
can — but because that is the only channel whose **timing is guaranteed and self-scheduling**: it
fires precisely when the agent attempts the act you are trying to change, in every session,
without waiting for a compaction that may never come.

That is why this design has one library (`hook-state-lib.sh`) sourced by all five hooks, and why
the contract text is compiled into `issue-loop-gate.sh`'s refusal message rather than being read
out of the rules directory. A rules file is a *hope* that the agent loaded it. A gate's stderr is
a *fact* about what is in its context.

The watcher carries the docs' own hedge, "**normally** picked up", with no enumerated failure
conditions. The documented remedy: "If they haven't appeared after a few seconds, the file
watcher may have missed the change: restart your session to force a reload."

---

## 2. The one channel into a running agent's context

| Channel | Fires when | Usable for migration? |
|---|---|---|
| `SessionStart` hook stdout (exit 0) | session start / resume / compaction | **Partly.** "Claude Code adds stdout it treats as plain text to Claude's context" — `SessionStart` is one of four events where that happens. But it only fires on those moments. |
| **`Stop` hook stderr on exit 2** | **the agent attempts to end a turn** | **YES — this is the mechanism.** "A hook that blocks by exiting 2 routes the same way as `reason`: Claude receives the stderr message as the explanation for why it should continue." |
| `PreToolUse` stderr on exit 2 | a matching tool call | Possible, but it would have to block real work to speak. Wrong trade. |

`Stop`-hook-stderr is right for a further reason: **the moment of delivery is the moment of
relevance.** You are not informing the agent about a policy it might need later; you are refusing
the specific act the new policy forbids, while it is being attempted, and saying why.

### DECISION: exit 2 with stderr, NOT the JSON `decision` form — and the reason is fail-direction

A tidier-looking alternative exists: `{"decision":"block","reason":"..."}`, or
`hookSpecificOutput.additionalContext`. **Do not migrate to it.** The docs give the asymmetry
plainly:

- "A hook that exits 2 while printing JSON that fails JSON output schema validation **still
  blocks**: Claude Code uses stderr as the blocking reason."
- A JSON-only decision whose object fails schema validation is "**a non-blocking error: the
  action proceeds**."

So exit 2 **fails closed** and JSON-only **fails open** on the same malformed input — a stray
line on stdout from a shell profile, an unescaped quote in an interpolated issue title. Swapping
one for the other is a change that reads like a cleanup and reintroduces the original defect.

Two constraints that follow from the same section:

- **Exit-0 stderr is invisible to the agent.** "Stderr from a hook that exits 0 goes to the debug
  log only, never the transcript, and Claude never sees it." The message rides on the block, and
  only on the block. A gate that "warns" without blocking communicates with nobody.
- **The harness itself stops after 8 consecutive blocks:** "Claude Code overrides the hook and
  ends the turn after 8 consecutive blocks." That is the vendor-side twin of `HOOK_BLOCK_CAP`,
  whose default of 8 matches it deliberately rather than by coincidence — so a gate that tried to
  block indefinitely would be overridden anyway, and the counter exists to make the give-up
  *say so* rather than to invent a limit.

One more reason the contract travels this way: contract text is **imperative** by nature ("a turn
ends when the WORK IS FINISHED"). The docs warn that for `additionalContext` you should "write the
text as factual statements rather than imperative system instructions", because "text framed as
out-of-band system commands can trigger Claude's prompt-injection defenses, which causes Claude to
surface the text to you instead of treating it as context." A `Stop` blocking reason has no such
caveat — imperative text is its documented purpose ("Tells Claude why it should continue"). Keep
imperative content in the gate refusal, and keep the SessionStart injection's *state* half phrased
as facts (`Phase: IMPLEMENT`, `Issue: 574`).

---

## 3. The mechanism: a versioned contract handshake

`CONTRACT_VERSION` holds one line, e.g. `2026.08.30-continuous-work-1`.

On every `Stop` event, `issue-loop-gate.sh` checks for
`runs/<run-id>/contract-ack-<version>`:

- **Present** → the run has ingested this contract. Proceed to the normal gate logic.
- **Absent** → **block once (exit 2)**, print the full contract to stderr, and instruct the agent
  to create the ack file and continue. The block is counted against `HOOK_BLOCK_CAP`, so a run
  that cannot write the file is never wedged.

Three properties make this safe to deploy under running load:

1. **Idempotent and self-clearing.** Once acked, silence. The agent pays one blocked turn-end,
   ever, per contract version.
2. **Fresh sessions never see it.** `session-register.sh` pre-writes the ack when it seeds the
   run, so only pre-deployment sessions are interrupted. Deployment cost scales with the number of
   *stale* sessions, not with traffic.
3. **Bumping the version re-migrates everyone.** To push a revised contract to every live run,
   edit `CONTRACT_VERSION`. Every run's ack filename stops matching, so each gets the new text
   once. **That is the whole deployment procedure.**

A blocked turn-end costs one turn; an allowed turn-end on unfinished work costs the work. So an
unacked contract blocks rather than warns — and the message is written to be actionable inside the
same turn (create one file, carry on), never to send the agent looking for documentation.

---

## 4. Deploying to a project with live workers

```
1. Copy the hooks into <project>/.claude/hooks/:
       hook-state-lib.sh   CONTRACT_VERSION   MIGRATION.md
       session-register.sh issue-loop-gate.sh
       spec-stop-gate.sh   spec-tdd-gate.sh   continuous-work-reinject.sh
       tests/
2. Copy rules/continuous-work.md into <project>/.claude/rules/ and reference it from CLAUDE.md.
3. Register the hooks in <project>/.claude/settings.json (see ClaudeCodeSetupPrompt.txt).
4. Run the seven suites in tests/ (§7). Do NOTHING to the running sessions.
```

**Steps 1–3 are safe to perform while agents are working.** Every file is read at invocation time,
and a partially-copied library **fails closed**: the gates verify `hook_task_selftest`
(deliberately the last definition in the library) and refuse the stop if it is missing. The failure
mode of a mid-copy Stop event is one spurious refusal, not a silent hole.

### Which live sessions actually acquire a working brake

**Loading the new code is not the same as engaging.** A pre-change session's fate is decided by
what the OLD `session-register.sh` left on disk, because that is what the identity verdict reads:

| What the old registrar left | Verdict | What happens at the next Stop |
|---|---|---|
| A `registry.json` entry for this session (the old jq-only upsert **ran**) | `BROKEN` | The gate **fails closed and refuses**, and the refusal is a repair instruction. Note this is the BROKEN path, not the contract handshake — the run acquires a brake either way. |
| **No** entry (the old upsert was jq-only and `jq` was **absent**) | `UNREGISTERED` | The gate loads the new code and **exits 0 silently**. This session is **NOT migrated.** |
| Started after step 3 | `OWNED`, pre-acked | Seeded and never interrupted. |

That second row is not hypothetical — it is the state of the host where this incident was measured
(`jq` is not installed there, so the old registrar wrote nothing). And `UNREGISTERED` must stay
benign, because that is exactly what an ordinary chat session looks like; making it block would
refuse every non-orchestrator session in the project.

**Tell which case you are in, per live session:**

```bash
# List the sessions the registry knows about. A live session absent from here is row 2.
python - <<'PY'
import json, pathlib
p = pathlib.Path(".claude/agent-state/issue-work-orchestrator/registry.json")
d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
print(f"{len(d)} registered sessions")
for sid, e in d.items():
    sd = e.get("state_dir", "(none)")
    seeded = (pathlib.Path(".claude/agent-state/issue-work-orchestrator") / str(sd).rstrip("/") / "resume_state.md").exists()
    print(f"  {sid[:8]}  state_dir={sd:24s} seeded={seeded}")
PY
```

**Recovering a row-2 session without restarting it.** Seed the file the gate looks for, by hand,
using the session's own id (the `session_id` in that session's transcript filename):

```bash
mkdir -p .claude/agent-state/issue-work-orchestrator/runs/<first-8-of-session-id>
cat > .claude/agent-state/issue-work-orchestrator/runs/<first-8-of-session-id>/resume_state.md <<'EOF'
SESSION_ID: <full-session-id>
MODE: SINGLE_ISSUE
Status: IN_PROGRESS
Phase: FIX
CURRENT_ISSUE: <N>
AWAITING_USER: none
WORKABLE_ISSUES_REMAIN: no
EOF
```

**What each line is doing, because a seed that resolves `OWNED` can still leave the gate
releasing every turn.** The gate holds a turn only while the run has CLAIMED tracked work AND has
not affirmatively released, so a seed has to satisfy both halves:

- `SESSION_ID:` — the third resolution rung. It is what lets a hook find this state even if the
  directory name does not match, so do not omit it.
- `MODE: SINGLE_ISSUE` — **this is the line that CLAIMS the work**, and it is deliberately a
  literal rather than a template. The claim predicate accepts a non-placeholder `CURRENT_ISSUE`,
  a `CURRENT_SPEC`, or a `MODE` beginning `ISSUE_LOOP`/`SINGLE_ISSUE`/`SPEC`/`BACKLOG`/`AUTO`
  (hyphens normalised to underscores, so `single-issue` matches too).
- `CURRENT_ISSUE: <N>` — substitute the real issue number. **Until you do, this line claims
  nothing**: `hook_field_is_placeholder` rejects any angle-bracketed value, along with `none`,
  `unset`, `unknown`, `tbd`, `n/a` and the rest of that vocabulary. That is exactly why the `MODE`
  line above is literal — pasted as written, the seed still arms.
- `Status: IN_PROGRESS` — any value OUTSIDE the idle vocabulary
  (`NOT_STARTED`/`NOT_YET_STARTED`/`UNSTARTED`/`NOT_IN_PROGRESS`/`NOT_WORKING`/`IDLE`/`PENDING`/
  `NEW`/`NONE`/`UNSET`) and outside the terminal vocabulary will hold, because the polarity is
  inverted: an UNRECOGNISED `Status` means work in flight. `IN_PROGRESS` is not magic; it is
  simply not idle. Seeding `NOT_STARTED` here releases the gate on the spot.
- `Phase: FIX` — must not be a terminal value. `DONE`, `COMPLETE`, `COMPLETED`, `FINISHED`,
  `CLOSED`, `ABANDONED`, `ESCALATED`, `CANCELLED` and `CANCELED` release, matched WHOLE-VALUE and
  case-insensitively.
- `AWAITING_USER: none` — a placeholder, so no escalation is recorded. A SUBSTANTIVE reason here
  releases the gate; `none`, `<reason>`, `no`, `false`, `0` and anything shorter than
  `HOOK_MIN_ESCALATION_REASON` do not.
- `WORKABLE_ISSUES_REMAIN: no` — records that this is a single-issue recovery. It gates NOTHING:
  it selects the refusal's wording and feeds the progress fingerprint.

**Which placeholders bite silently, and which do not.** The two `<…>` tokens in the PATHS are
self-announcing: pasted verbatim, bash parses `<first-8-of-session-id>` as a redirection and dies
with `syntax error near unexpected token`, so nothing is created and you know at once. The FIELD
values are the quiet ones, and they are why this recipe previously seeded an UNARMED run. MEASURED
by driving `issue-loop-gate.sh` against the seed: with no `MODE` line and `CURRENT_ISSUE` left as
the literal `<N>`, the run resolved `OWNED` and the gate exited **0** on every turn-end, acked or
not — a well-formed state file that looked exactly like a working brake with nothing to hold. With
the `MODE` line above, the same paste exits **2**. Leaving `<full-session-id>` verbatim is milder
but not free: the run still resolves from its directory name, but the third rung can no longer
recover it if the state ever moves.

**Then it takes effect at the NEXT turn-end attempt, in two steps.** The first attempt resolves
`OWNED`, finds no contract ack, and BLOCKS to deliver the contract — that block is the delivery,
and it names the ack file to create. Once the agent has written the ack, subsequent attempts are
judged by the brake proper against the fields above. Nothing happens mid-turn; if the session
never attempts to end a turn, it is never spoken to.

If you cannot determine the session id, the session must be restarted — there is no way for a hook
to attribute a run it has no evidence for, and guessing is the defect this whole change removes.

Do not create the ack files yourself to "spare" the running agents the interruption. The
interruption *is* the delivery.

---

## 5. What is documented, what is observed, and what is neither

This project's signature defect is prose that is true of a mechanism's intent and false of its
reach. So the evidence class of each load-bearing claim is stated explicitly.

- **DOCUMENTED — settings edits reach a live session.** "Direct edits to hooks in settings files
  are normally picked up automatically by the file watcher." Corroborating: the `ConfigChange`
  event "Runs when a configuration file changes during a session", and its decision control says
  "When blocked, the new settings are not applied to the running session" — the negative entails
  that unblocked changes *are* applied. The `/hooks` menu also lists a `Session Hooks` source,
  "registered in memory for the current session".
  > **A previous revision of this file asserted the opposite** — that "hook configuration is
  > snapshotted at session start". That was wrong, and nothing in either page supports it: a
  > case-insensitive search for `snapshot`/`at startup` across the complete 316KB reference returns
  > zero matches. It is recorded here rather than quietly deleted, because the design decision in
  > §1 survives the correction while its original justification does not — and a reader who
  > remembers the old claim needs to know which part changed.
- **OBSERVED, not documented — a hook SCRIPT is re-read at every invocation.** The docs say
  nothing in either direction. It follows from process-spawn semantics, and it is checkable in five
  seconds: hold one invocation constant, edit the script between two calls, and the second call
  reflects the edit. Treat it as demonstrable rather than as guaranteed.
- **OBSERVED — a `SessionStart` hook fires mid-session on compaction.** With
  `matcher: "compact|resume|startup"`, this project's `continuous-work-reinject.sh` fired as
  `SessionStart:compact` in a long-running session. The reference describes `SessionStart` as
  running "when a session begins or resumes"; the compaction case is what makes a
  newly-registered SessionStart hook eventually reachable, at timing you do not control.
- **NOT DOCUMENTED — whether the 10,000-character output cap covers stderr.** The sentence names
  `additionalContext`, `systemMessage` and plain stdout only. Moot at current sizes (the gates'
  largest refusal is ~3KB), so no claim is made.
- **VERSION-DEPENDENT.** Several documented behaviours carry client-version floors. Check the
  reference for the release you are on rather than trusting this file.

### Three invariants of `continuous-work-reinject.sh`, so a future edit cannot break them silently

1. **It must `exit 0`.** For `SessionStart`, exit 2 "Shows stderr to user only" and "Claude doesn't
   see it". A SessionStart hook that signalled by stderr and a non-zero exit would deliver nothing
   to the agent.
2. **Its stdout must not both start with `{` and end with `}`** unless it is deliberately valid
   hook JSON: stdout of that shape is parsed as JSON, and on a parse failure "Claude Code doesn't
   add the text" — silent, with no error the agent can see. The first line is currently
   `## Continuous work is in force …`, i.e. plain text.
3. **It must stay under 10,000 characters** ("Hook output strings, including `additionalContext`,
   `systemMessage`, and plain stdout, are capped at 10,000 characters"); past the cap the text is
   replaced by a file path and a preview, which reads as delivered but is not. Currently ~2KB.

---

## 6. What this mechanism does NOT solve

- **A session that runs no gate cannot be reached.** Nothing in a hooks-based design migrates a
  session whose settings register no hooks at all and whose watcher never reloads.
- **A row-2 session (no registry entry) is not migrated** by any hook. §4 gives the manual seed;
  otherwise restart it.
- **A session that never attempts to end a turn is never spoken to.** That is fine — the contract
  only constrains turn-end.
- **`AWAITING_USER` is self-reported.** The gate cannot distinguish a genuine Proven Exception from
  a fabricated one. It enforces that an escalation was *recorded*, which is a real constraint (an
  undeclared stop is refused) but not a judgement of the reason's quality.
- **A determined agent can delete a hook.** Both gates are file-editable. Defence in depth, not a
  boundary.
- **The cap is a real exit.** After `HOOK_BLOCK_CAP` consecutive blocks the gate allows the stop,
  saying the work is not done — and the harness ends the turn after 8 consecutive blocks in any
  case. The gates bound spurious stops; they do not eliminate them.

---

## 7. Verifying a deployment

```bash
# 1. Both Stop gates load their library and reach a decision.
printf '{"session_id":"probe","cwd":"%s","hook_event_name":"Stop"}' "$PWD" \
  | bash .claude/hooks/issue-loop-gate.sh; echo "exit $?"      # expect 0 (unregistered probe)

# 2. The library fails CLOSED, not open. Expect exit 2 — never 0, never 1.
mkdir -p /tmp/gp/hooks && cp .claude/hooks/issue-loop-gate.sh /tmp/gp/hooks/
( cd /tmp/gp && printf '{"session_id":"x","cwd":"."}' | bash hooks/issue-loop-gate.sh ); echo "exit $?"

# 3. The seven suites. A registered run with NO state file must BLOCK; if it exits 0 the
#    deployment is inert. All seven must be green. Read each suite's own TOTAL line rather
#    than trusting the counts below.
bash .claude/hooks/tests/test_crlf_hygiene.sh     # 11 — a CR smuggled through a line protocol
bash .claude/hooks/tests/test_hook_state_lib.sh   # 64 — identity, parsing, counters, cap validation
bash .claude/hooks/tests/test_stop_gates.sh       # 24 — Stop gate exit codes
bash .claude/hooks/tests/test_tdd_gate.sh         # 42 — push gate, both directions
bash .claude/hooks/tests/test_reinject.sh         # 23 — no cross-run adoption + delivery invariants
bash .claude/hooks/tests/test_gate_overblock.sh   # 50 — the OVER-block direction: turns that must be ALLOWED
bash .claude/hooks/tests/test_unpinned_fixes.sh   # 32 — handshake BLOCK by text, evidence, mtime, cross-gate

# 4. Confirm the gates have actually fired in this clone. This directory is created ONLY on a
#    blocking path, so its absence across many sessions means never-blocked.
ls -la .claude/agent-state/issue-work-orchestrator/.stop-gate-counters/ 2>/dev/null \
  || echo "no counters yet — no gate has ever blocked in this clone"

# 5. Read the decision log. Every invocation appends one line, so permanent inertness is now
#    visible instead of looking identical to compliance.
tail -40 .claude/agent-state/issue-work-orchestrator/.hook-decisions/*.log
```

Step 4 is the one that matters most. It is how the original defect was *proved* rather than
suspected: the counter directory did not exist in a clone with 189 registered sessions, which is
only possible if neither gate had ever blocked a turn-end.

### Why the library has a suite of its own, and not just the gate suite

`test_hook_state_lib.sh` exists because an end-to-end suite can pass over a broken library.
`hook_resolve_run_dir` contained

```bash
local base="$1" ... orch="$base/$HOOK_ORCHESTRATOR_DIRNAME"
```

and bash expands every assignment word in a single `local` **before** creating any of the locals,
so `$base` there resolved to the **caller's global** of that name. Both gates hold a global called
`base`, so all 24 gate assertions passed while the function was, called from anywhere else,
aborting. Inside a `$(…)` that abort produces an empty verdict, which the gates read as "nothing to
guard": a silent fail-open, reachable by nothing more than renaming a variable in a caller.

The general lesson, worth applying beyond this file: **a test that reaches the unit only through
one caller measures the pair, not the unit.** The library suite therefore defines no global named
`base`, `session`, `orch`, `declared` or `run_dir`, so a reintroduced same-statement self-reference
reds a case here instead of waiting for an unrelated refactor to expose it.

---

# Incident record

The measured incidents the loaded rules cite by slug. Each entry is the authoritative
account; the loaded rules and `.claude/docs/run-identity.md` carry only one-line pointers,
so this section is what stops a future editor "simplifying" a constraint whose reason they
cannot see. Append new incidents here; never delete one.

## Incident `invented-run-label` (the 189-session inert-gate failure)
`session-register.sh` wrote `state_dir: "runs/<sid8>/"` into `registry.json` but created
nothing on disk. The agent, told by its command to "derive `RUN_ID`", invented a readable
label (`run-issue574-20260828T194800Z`) and wrote well-formed state there. Both Stop gates
resolved state from the registry, found nothing, and exited 0 — inert from turn one.
Across 189 registered sessions in that clone, neither Stop gate had EVER blocked a
turn-end (provable from the absence of `.stop-gate-counters/`, which only the blocking
path creates), and a run holding an explicit instruction never to stop without a proven
reason ended four turns unopposed. Fixes: the hook now SEEDS `runs/<run-id>/`, and a
registered-but-stateless session resolves `BROKEN` and fails CLOSED.

## Incident `mtime-borrow` (three hand-rolled resolvers, one shared defect)
Three hooks each hand-rolled a registry read guarded by `command -v jq` with an
`ls -t … | head -1` fallback. jq was absent on the development host, so all three resolved
"the most recently touched run" — which handed one session a sibling's issue number,
branch, and worktree as its own (reproduced live), and gated one session's push on a
stranger's task ids. Fix: `hook-state-lib.sh` is the ONE resolver, every rung
session-keyed, no mtime rung. Add no fourth copy.

## Incident `seven-synonyms` (the brake armed on one magic string)
The loop gate armed only on the literal `IN_PROGRESS`. MEASURED on a correctly seeded,
registered, contract-acked run recording `Phase: IMPLEMENT` and `CURRENT_ISSUE: 574`, all
of these let the turn end: `in progress`, `In Progress`, `in-progress`, `WORKING`,
`ACTIVE`, `RUNNING`, `IMPLEMENTING`. Fix: inverted polarity — an unrecognised `Status`
means work in flight; only an affirmative idle/terminal value releases.

## Incident `whole-value-vs-substring` (two adversarial reviews, opposite failures)
One review measured the narrative `Status: COMPLETED (was IN_PROGRESS)` being REFUSED and
called it an over-block. The other measured `IN_PROGRESS - tasks 1-3 completed, 4
remaining` DISARMING the evidence gate through a prefix/substring match — phrasing that
"is not adversarial; it is how a progress note is naturally written". Both describe the
same value shape, so only one rule can hold, and fail direction decides: a whole-value
match costs a spurious refusal that names its own escape; a substring match lets a
progress note end a turn. WHOLE-VALUE won. Do not "fix" it back in either direction.

## Incident `untrimmed-whitespace` (one stray space, both fail directions)
An untrimmed `AWAITING_USER: none ` compared unequal to the placeholder `none` and so
read as a recorded escalation — DISABLING the primary brake. An untrimmed
`CURRENT_SPEC: x ` produced the unopenable path `x /tasks.md` and REFUSED every turn-end
with no escape an agent could find. Fix: values are whitespace-trimmed before both the
shape test and the word test.

## Incident `placeholder-release` (the gate's own example string released it)
The substance test on `AWAITING_USER` exists because measured releases included the
literal `<reason>` — the placeholder the gate itself used to print, so an agent copying
the instruction verbatim disarmed the brake with the gate's own string. Both gates now
apply the same `hook_is_substantive_escalation` test; the evidence gate previously
released on any non-placeholder value, a fail-open wherever it was the only Stop hook.

## Incident `duty-cycle` (the block cap reset itself into a cycle)
While reaching `HOOK_BLOCK_CAP` merely reset the counter, MEASURED over eleven
consecutive Stop events: attempts 1-8 refused, attempt 9 released and reset, attempts
10-11 refusing again — eight forced continuations, one exit, eight more, forever. Fix:
reaching the cap writes a durable `.capped` marker; only a genuine release on the merits
(or, for the loop gate, a CHANGE in the field fingerprint; for the evidence gate, new
evidence) clears count and marker.

## Incident `empty-verdict` (a `set -u` slip fell through to ALLOW)
A single `set -u` abort inside the resolver's subshell produced an EMPTY verdict that
matched no guard; the gate fell through to its field reads and ALLOWED — while logging a
line that read like a decision. Fix: an unrecognised verdict is normalised to `BROKEN`.

## Incident `fenced-status` (an example beat the record)
Before fence tracking, a `Status:` line inside a fenced code block was read as the run's
Status, and last-occurrence-wins made a late example beat the real record. Fix: fields
inside fences are ignored.

## Incidents `hour-long-commits`, `pytest-n-auto-host-death`, `fail-fast-cycles`
The three measured failures of the per-commit-test-suite arrangement, recorded in full in
the `scripts/run_tests.py` header (WHY THIS EXISTS) and `ci-owns-the-test-suite.md`'s
history: a 60-minute suite made every commit an hour, so agents batched whole features
into single unreviewable commits; several worktrees each running `pytest -n auto` (one
worker per vCPU) made the host unusable and got the agent killed mid-run; fail-fast CI
reported one failure per run, so a ten-failure branch cost ten pipeline runs. Fixes:
pre-commit = lint+security only, the evidence gate moved to the PUSH, `run_tests.py`
bounds local workers and refuses `-x`/`--maxfail`, CI runs everything with no fail-fast.
