# Run Identity, State Fields, and Gate Release — the binding contract for registered runs

Installed at `.claude/docs/run-identity.md`. NOT auto-loaded: read this file BEFORE the
first state write of any registered run (an orchestrator run, a spec workflow, issue
work). `.claude/rules/agent-state-convention.md` binds you to it; this file is the
AUTHORITATIVE copy of the run-identity contract, the seeded field set, the release
vocabulary, and the gate verdicts. Full accounts of every MEASURED incident cited here:
`.claude/hooks/MIGRATION.md` §Incident record.

## 1. Per-run namespacing when multiple runs share one clone

A single-run agent uses the flat `.claude/agent-state/<agent-name>/` layout. An agent of
which multiple instances may run concurrently in one clone (notably
`issue-work-orchestrator`) MUST namespace state per run:

```
.claude/agent-state/<agent-name>/
  registry.json                 # session_id -> { session_id, run_id, cwd, state_dir,
                                #                 status, started_at, last_heartbeat }
  .locks/<resource>.lock        # per-resource mkdir locks (atomic create-or-fail; NTFS-safe)
  .stop-gate-counters/          # <gate>-<first-8-of-session-id>.count, .capped, .fingerprint (§6)
  .hook-decisions/<date>.log    # one line per hook invocation: allow / block / why (§6)
  runs/<run-id>/                # ONE run's private state subtree
    resume_state.md             # SEEDED by session-register.sh — see §3
    workflow_state.md           # SEEDED by session-register.sh — see §3
    contract-ack-<version>      # existence = this run has ingested that contract version
    environment.md  issue_queue.md  iteration_log.md
```

Run identity is established by the SessionStart hook `session-register.sh`, which writes
`registry.json` keyed by the harness `session_id` and derives `run_id` from it. Agent and
gate hooks both resolve "which run owns this session" via that registry — no environment
variable carries identity. A LIVE run = an active `status` plus a fresh `last_heartbeat`;
stale entries/locks are reclaimed only when the heartbeat is past its bound AND the
worktree pointer no longer resolves AND the run's status is terminal (archive, never
delete). The seven keys above are the WHOLE registry entry — there is no `current_issue`
key; which issue a run claimed lives ONLY in `runs/<run-id>/resume_state.md` as
`CURRENT_ISSUE`. `state_dir` is written WITH a trailing slash and the resolver strips it;
do not "correct" it. `status` and `last_heartbeat` are stamped at SessionStart and are the
AGENT's to maintain after that.

All five hooks resolve a session's run through the shared `hooks/hook-state-lib.sh`,
every rung of which is keyed on the session id; none has a most-recently-modified rung.
The resolver is a shared LIBRARY because the mtime defect was found independently in
THREE hand-rolled copies (MEASURED — Incident `mtime-borrow`). Add no fourth copy: a new
hook sources the library.

## 2. The run id is REGISTRY-DERIVED. An agent-authored label is a DEFECT.

`session-register.sh` computes `run_id` from the `session_id` and writes the resulting
`state_dir` into `registry.json`. **Use that value verbatim.** Do not derive your own, do
not make it "readable", do not append an issue number or timestamp. MEASURED (Incident
`invented-run-label`): an agent wrote its state under a tidy self-chosen label
(`run-issue574-…`), the gates resolved the registry path, found nothing, and exited 0 —
every Stop gate was inert from turn one, and across 189 registered sessions in that clone
neither gate had EVER blocked a turn-end. Nothing about the label looked wrong from the
inside; a well-formed state file in a nicely named directory is what this failure looks
like while it is happening. If a hook says your run state is missing, create the path IT
names, verbatim — never reconcile in the other direction.

## 3. `session-register.sh` SEEDS the state, so the gates are reachable from turn one

The hook creates `runs/<run-id>/` and writes both state files if absent (never
overwrites), so every field a gate branches on holds a real value before your first
action. The seeded field set — all plain `Name: value` lines:

| File | Seeded fields |
|---|---|
| `resume_state.md` | `SESSION_ID`, `RUN_ID`, `STATE_DIR`, `MODE`, `Status`, `Phase`, `CURRENT_ISSUE`, `BRANCH`, `WORKTREE`, `PR`, `WORKABLE_ISSUES_REMAIN`, `AWAITING_USER` |
| `workflow_state.md` | `SESSION_ID`, `RUN_ID`, `CURRENT_SPEC`, `Phase`, `Status`, `CURRENT_TASK` |

Seeded VALUES matter as much as names: `Status`/`Phase` are `NOT_STARTED` in both files;
`MODE` is `unset`; `CURRENT_ISSUE`, `BRANCH`, `WORKTREE`, `PR`, `AWAITING_USER`,
`CURRENT_TASK` are `none`; `WORKABLE_ISSUES_REMAIN` is `unknown`; `CURRENT_SPEC` is
seeded EMPTY. Every one of those is in §5's placeholder vocabulary, so a freshly seeded
run is ungated twice over: affirmatively idle AND no tracked work claimed. The hook also
pre-writes `contract-ack-<version>`.

## 4. Field semantics: LAST occurrence wins, plain spelling only

Every hook reads **the LAST occurrence of a plain `Name: value` line**. Four load-bearing
consequences:

1. **Correct a value by APPENDING a new block at the END of the file.** Never edit an
   earlier block, never prepend — the top of the file is what a human reads and what NO
   hook reads.
2. **A bold field spelling (`**Name:** value`) is read by NO hook** — invisible, not
   out-competed. The file documents the right value and every gate reads an empty string.
   Write fields plain; bold belongs in prose only.
3. **A human-facing summary must be PROSE with no `Name: value` lines**: a recap
   containing `Status: blocked on review` becomes the authoritative last occurrence.
4. **A `Name: value` line inside a fenced code block is IGNORED** — an example or pasted
   transcript is not a field. (Before fence tracking it WAS one — Incident
   `fenced-status`.)

## 5. THE FIELD VOCABULARY — the values a gate actually recognises (AUTHORITATIVE)

This section exists because its absence was a measured defect: the primary brake armed
only on the literal `IN_PROGRESS`, and `WORKING`, `ACTIVE`, `in progress` and four more
plausible words each disabled it (Incident `seven-synonyms`). The polarity is now
INVERTED, so guessing wrong is safe: **an unrecognised `Status` means work is in
flight.** Only an affirmative statement releases the brake.

| Field | Values that RELEASE a Stop gate | Everything else means |
|---|---|---|
| `Status` | `NOT_STARTED`, `NOT_YET_STARTED`, `UNSTARTED`, `NOT_IN_PROGRESS`, `NOT_WORKING`, `IDLE`, `PENDING`, `NEW`, `NONE`, `UNSET` (whole value, any case) | work in flight |
| `Phase` or `Status` | `DONE`, `COMPLETE`, `COMPLETED`, `FINISHED`, `CLOSED`, `ABANDONED`, `ESCALATED`, `CANCELLED`, `CANCELED` (whole value, any case) | not finished |
| `AWAITING_USER` | a SUBSTANTIVE reason — see below | no escalation recorded |
| `CURRENT_ISSUE`, `CURRENT_SPEC`, `BRANCH`, `WORKTREE`, `PR`, `MODE` | EMPTY, anything from `<` to `>`, or `none`, `-`, `--`, `n/a`, `na`, `unset`, `unknown`, `empty`, `null`, `nil`, `tbd`, `todo`, `pending`, `placeholder`, `xxx` (whole value, any case) = NOTHING RECORDED | a real recorded value |

Five consequences worth internalising:

- **A terminal value must be the WHOLE value.** `Phase: DONE` releases;
  `Phase: waiting to be DONE` and `Status: COMPLETED (was IN_PROGRESS)` do not — that is
  why the synonym list is generous. This rule is where two adversarial reviews of the
  gates DISAGREED in opposite directions (one measured the narrative form refused and
  called it an over-block; the other measured `IN_PROGRESS - tasks 1-3 completed…`
  DISARMING a gate through a substring match). Only one rule can hold, and fail direction
  decides: a whole-value match costs a spurious refusal that names its own escape, while
  a substring match lets a progress note end a turn. Do NOT "fix" this to a substring
  match — Incident `whole-value-vs-substring` records both measured failures. **Write the
  status as a bare token and put the narrative in prose.**
- **`AWAITING_USER` must name a real reason.** It is a self-issued permission slip, so it
  is checked for SUBSTANCE (`hook_is_substantive_escalation`, the SAME test in both
  gates): a placeholder, a one-word token (`no`, `false`, `0`, `waiting`, `blocked`,
  `?`), or anything shorter than a dozen characters is REJECTED. Measured releases
  included the literal `<reason>` — the gate's own former example string. Write the
  reason you would give a person:
  `AWAITING_USER: waiting on the production credential for the smoke test`.
- **The placeholder list above is CLOSED and exact.** Two tests, in this order: by SHAPE
  (any value from `<` to `>` is a placeholder), then by WORD (whole-value,
  case-insensitive, exactly the fifteen tokens — so `unclaimed`, `nothing`, `0` are REAL
  values). Whitespace is stripped before either test, deliberately in both directions
  (Incident `untrimmed-whitespace`: an untrimmed `none ` read as a recorded escalation
  and disabled the brake, while an untrimmed `x ` built an unopenable path and refused
  every turn-end with no escape).
- **`Status: IN_PROGRESS` alone does NOT hold a turn.** Every session is registered and
  seeded, so the loop gate additionally requires evidence that TRACKED WORK was claimed:
  a real `CURRENT_ISSUE`, a `CURRENT_SPEC`, or a `MODE` naming an orchestrator mode
  (`ISSUE_LOOP`, `SINGLE_ISSUE`, `SPEC`, `BACKLOG`, `AUTO`). The `MODE` test is a PREFIX
  match, case-insensitive, hyphens normalised to underscores, so `single-issue` and
  `SINGLE_ISSUE_574` both count. The no-claim release exists so an ordinary chat session
  stays unblocked — it is NEVER a way out of work you have already claimed: blanking a
  claim mid-issue (appending `CURRENT_ISSUE: none` / `MODE: none` on unfinished,
  still-tracker-claimed work) is a false record and a forbidden stop, worse than a
  refused turn-end because it disarms the brake. (The evidence gate is scoped instead by
  the spec workflow's own phase: it acts only at `IMPLEMENT`/`VERIFY`, matched as an
  uppercase WORD, so `NOT_IMPLEMENTED` is outside it and `Phase: implement` is inside
  it — and inside those phases it has the OPPOSITE rule, deliberately: an absent
  `CURRENT_SPEC` or `tasks.md` is unfinished work to block on, not nothing to check.)
- **`WORKABLE_ISSUES_REMAIN` gates NOTHING.** It once WAS the block condition — which is
  how `/work-issue` runs, which set it to `no`, came to be ungated. Today it selects the
  refusal's wording and feeds the progress fingerprint; it can neither hold a turn nor
  release one.

## 6. `SESSION_ID:` is load-bearing, and the three identity verdicts (AUTHORITATIVE)

`SESSION_ID` is the third resolution rung: when no registry `state_dir` and no
`runs/<first-8-of-session-id>/` resolves, the library scans `runs/*/resume_state.md` for
a recorded `SESSION_ID` matching this session. It recovers a naming deviation (§2) and is
still session-derived, so it can only return state belonging to this session. Never
remove or rewrite it — and it is a repair rung, not a licence to choose your own
directory name. The scan is STRICTER than an ordinary field read: it matches a line that
is ONLY `SESSION_ID: <id>` (no list marker, no trailing comment) and has no fence
tracking — so never paste another session's id into your state file, even in a fence.

Resolution yields exactly three verdicts; a gate branches on the verdict, never on "is
the file there":

| Verdict | Means | Gate behaviour |
|---|---|---|
| `OWNED` | a session-keyed run directory resolved with a `resume_state.md` | judge the run on its own recorded state |
| `UNREGISTERED` | registry knows nothing, no rung found state | **no-op** — a plain chat session looks like this and must never be blocked |
| `BROKEN` | registry DECLARES a run, no rung found a state file | **fail CLOSED — block the turn-end** |

`BROKEN` is the whole point of the split: "no state" and "nothing to guard" are different
facts, and collapsing them into one `exit 0` is the defect this contract exists to
prevent. An unrecognised verdict is normalised to `BROKEN` (Incident `empty-verdict`).
Do not "simplify" a gate to exit 0 on a missing state file.

Two bounds keep refusal from wedging a session, and neither weakens the verdict:

- Each gate keeps its own consecutive-block counter (`HOOK_BLOCK_CAP`, default 8,
  validated into [1, 64]). At the cap it allows the stop WHILE SAYING the work is not
  done, and writes a durable `.capped` marker so the stand-down persists — without the
  marker the cap was a duty cycle (Incident `duty-cycle`: refusals 1-8, release 9,
  refusals 10-11, forever). Only a genuine release on the merits clears count and marker.
  The loop gate also clears them whenever its field fingerprint (`Status`, `Phase`,
  `CURRENT_ISSUE`, `AWAITING_USER`, `BRANCH`, `WORKABLE_ISSUES_REMAIN`) CHANGES; the
  evidence gate fingerprints its own subject (phase, spec, every capture's name and
  size). A run that is genuinely advancing never reaches the cap.
- The gates do not read `stop_hook_active` — honouring it made a policy gate block at
  most once per continuation chain.

Every invocation appends one line to `.hook-decisions/<date>.log` (allow or block, and
why) — the log is what makes an inert gate visible. If you want to know whether the gates
are working in a clone, read it.
