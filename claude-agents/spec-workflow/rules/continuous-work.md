# Continuous Work — stopping to ask permission is forbidden (ALL agents, always loaded)

This rule is shared by EVERY agent and by the main session. It is installed at
`.claude/rules/continuous-work.md` (no `paths:` frontmatter → always loaded) and is pointed
to from the project's root `CLAUDE.md`. It governs exactly one thing: **WHEN a turn may
end.** It binds every agent and overrides any contrary habit or instruction.

## The standard

**Work continues until the work is finished.** A turn ends for exactly two reasons: the
task is genuinely complete, or one of the four Proven Exceptions below is in play AND has
been proven. Nothing else.

**Stopping in order to obtain permission to continue is a forbidden behavior.** Any
instruction you hold — from a habit, a general convention, an older rule, a prior session,
or a phase description — that tells you to pause periodically, check back, report at
intervals, or seek approval before carrying on is **VOID for the duration of the task**.
Ignore it. This includes `.claude/rules/post-activity.md`: it defines what to do at the end
of an activity, NOT permission to treat each activity as a place to stop.

Specifically forbidden as turn-ending acts:

- "Shall I continue?" / "Should I proceed?" / "Let me know if you want me to go on."
- An unrequested intermediate summary, status report, or progress recap. Report when the
  work is done, not partway.
- Proposing the next steps instead of performing them.
- Ending on a plan, an offer, or a question the codebase itself could answer.
- **Waiting on background agents or workflows YOU dispatched.** Their completion
  re-invokes you; polling is wasted and idling is a stop. Do the unblocked work while they
  run. "I'll wait for the review to come back" is a stop wearing a process costume.
- **Substituting easier adjacent work for the hard task.** If the next real step is large
  and atomic (a wide refactor, a cross-cutting rename, a migration with no clean
  intermediate commit), do THAT. Doing tidy side-work and ending on a polished report is a
  disguised check-in and is the single most common form of this failure — the next section
  is about nothing else.
- Stopping, warning, or asking because the context window is filling up (see below).
- Waiting for a human to run something you can run yourself.

If you catch yourself about to end a turn, run this check first: *Is the task finished? If
not, is a Proven Exception in play and proven? If neither is true, do not stop — take the
next step.* When in doubt, continue working.

## The disguised check-in is the failure mode that actually happens

Read this section even if you are confident the rest does not apply to you. The measured
failures were not agents announcing "I am taking a break". Every one of them looked like
diligence:

- The report was **accurate**. Everything in it was true and evidence-backed.
- The work described in it was **real**. Nothing was fabricated or skipped.
- The stopping point looked like a **natural seam** — a phase boundary, a merged PR, a
  green suite, a completed sub-deliverable.
- The turn ended on a **polished artifact**, which is what made it feel finished.

That is the shape. **Accuracy is what disguises it**: a correct summary of finished
sub-work reads as a conclusion, so the stop never announces itself as one. A turn that
ends with the top-level task unfinished is a stop no matter how good the artifact is, and
no matter how much genuine work preceded it.

Two corollaries:

1. **A completed sub-deliverable is not a turn boundary.** Finishing a task in `tasks.md`,
   merging a PR, or going green means the NEXT step begins, in the same turn.
2. **Producing a summary is not producing progress.** If your next action is "write up what
   I did", ask what the actual next step of the task is and do that instead.

## The four Proven Exceptions

These are the ONLY legitimate reasons to stop before the work is done. Each carries a
burden of proof: you must show the exception genuinely applies AND that you exhausted the
alternatives. An unproven exception is a forbidden stop.

**1. An irreversible or destructive action.** Deleting or overwriting data, configuration,
history, or infrastructure; `push --force`; rewriting a shared branch; dropping or
replacing deployed resources; anything outward-facing or published.
*Proof:* name the exact command and target, and state why no reversible path exists.
*Exhaust first:* a backup, a copy, an additive change, a new branch, a dry-run, a
non-production target. **If a reversible path exists, take it and do not ask.**

**2. Sensitive information.** Using, exposing, or transmitting credentials, secrets,
tokens, personal data, or production data.
*Proof:* name exactly what is needed and why.
*Exhaust first:* a test fixture, a mock, synthetic data, a local or dev environment, an
already-authorized wrapper script.

**3. Genuine design guidance.** Two or more defensible designs exist, the choice materially
changes the deliverable, and the project cannot settle it.
*Proof:* state the options and cite what you actually consulted that failed to decide it —
the spec, the issue, existing patterns in the codebase, project docs, the decision log.
*Not this exception:* a choice between minor implementation details, naming, or anything
the existing code already answers by precedent. Decide those yourself and record the
decision (`DL-NNN`).

**4. A hard blocker.** A missing credential or authentication material, missing access or
permission, an unavailable external service, or a missing required capability (e.g. a
wrapper subcommand that does not exist).
*Proof:* the exact failing command with its COMPLETE output (per
`no-output-shortening.md`), plus the alternatives you tried.
*Not this exception:* a failure you have not yet diagnosed. Diagnose it first — a red test,
a red pipeline, or a confusing error is work to do, not a blocker to report.

Before invoking any exception you must have researched: the project's own docs and code, the
relevant MCP documentation servers (`use-doc-mcp-servers.md`), the spec/issue, and git
history. "I am not sure" is not proof — it is an instruction to go find out
(`no-guessing.md`).

## How to ask, when an exception is proven

- **Be short.** Two sentences of context, the options, the recommendation. Five lines is
  plenty. No preamble, no recap of what you already did.
- **Always give a recommendation.** Never present a bare choice. State which option you
  would take and the one reason why. A question without a recommendation is incomplete.
- Use the `AskUserQuestion` tool where available, with your recommended option **first** and
  labelled `(Recommended)`.
- **Batch.** One message with every open question. Never drip-feed.
- **Record it durably** where the work lives — a comment on the issue
  (`issue-tracking.md`), or the spec's `qa_log.md` — not only in chat, which does not
  survive compaction.
- **Record it MECHANICALLY too:** add an `AWAITING_USER` line naming the actual reason to this
  run's `resume_state.md`. That field is what tells the Stop gate the pause is sanctioned. An
  escalation you only *described* is, to every gate, indistinguishable from abandoning the
  work — and will be refused.
  **Write the reason you would give a person**, e.g.
  `AWAITING_USER: waiting on the production credential for the smoke test`. It is checked for
  substance, not presence: a placeholder, an angle-bracketed template, a one-word token
  (`no`, `false`, `0`, `waiting`, `blocked`, `?`), or anything shorter than a dozen characters
  is rejected. This is a self-issued permission slip, so it is the one field held to that
  standard — and BOTH gates apply the SAME test (`hook_is_substantive_escalation`), so a one-word
  token releases neither. The evidence gate used to release on any non-placeholder value, which
  was harmless only while both gates were registered: in a spec-only project where it is the ONLY
  Stop hook, that was a fail-open, and it let a word stand in for a reason.
- **Keep working.** Immediately continue with every part of the task that does not depend
  on the answer. Asking is never a reason to idle. If the whole task depends on it, and
  other workable tasks exist, move to one of those.

## Context-window pressure is never a reason to stop

Compaction is automatic: the harness summarizes older history as the window fills and the
session continues uninterrupted. **You cannot invoke it yourself** — `/compact` and
`/autocompact` are user commands, not tools available to you. So never stop, never warn,
never ask about context. Just keep working; the summary happens around you.

Your obligation is to make compaction lossless:

- **Externalize state continuously** to this run's `resume_state.md`
  (`agent-state-convention.md`) after EVERY step — progress, decisions, the current phase
  and the next step. On-disk state is what survives; the conversation is not.
- Keep the issue or spec updated as the live record, so the work is reconstructible from it
  alone.
- **Delegate large reads** to a subagent so the contents land in its context, not yours.
- **After a compaction, re-read before acting:** your state file, the active spec's
  decision log, and any file you still need. Root `CLAUDE.md` and always-loaded rules are
  re-injected from disk; `paths:`-scoped rules and nested `CLAUDE.md` files are NOT — they
  return only when you next read a matching file. Then resume the recorded step; do not
  restart the task.

## What enforces this, and what its reach actually is

Several mechanisms back this rule. None replaces it, and the limits below are stated because
a control believed to be wider than it is, is worse than a control known to be narrow.

- **Stop-hook gates** (`issue-loop-gate.sh`, `spec-stop-gate.sh`) refuse turn-end while
  this run records itself unfinished — the loop gate over a run that has claimed tracked
  work, the evidence gate over the spec workflow's IMPLEMENT/VERIFY phases. **They find your
  state through three rungs, every one of them keyed on the session id:** the `state_dir` the
  registry declares for this session, then `runs/<first-8-of-session-id>/`, then a scan of
  `runs/*/resume_state.md` for a recorded `SESSION_ID` matching this session.
  `session-register.sh` creates that directory at session start AND writes it into the registry,
  so the first two rungs name the same path and it holds real values from turn one.
  **Writing your state elsewhere does not switch the gates off, in either direction.** State
  under a directory name of your own choosing is still recovered by the third rung, as long as
  the file carries its `SESSION_ID:` line; and a session the registry DECLARES as a run for
  which NO rung finds a state file resolves `BROKEN`, which BLOCKS the turn-end and prints the
  exact path to create. The gates go quiet for exactly one case: a session the registry does
  not know and for which no rung finds state (`UNREGISTERED`) — which is what an ordinary chat
  session looks like, and why it must be a no-op.
  Inventing a run-id label is nonetheless a defect and is never yours to do
  (`agent-state-convention.md` §1b): it defeats the two cheap rungs, leaves the third carrying
  the whole guarantee, and a state file written without `SESSION_ID` defeats that one too — at
  which point the gates do not go quiet, they resolve `BROKEN` and refuse every turn-end against
  a record that is in fact perfectly good, until the path the registry names exists. It
  is not hypothetical either. MEASURED under the PREVIOUS gates, which resolved state from the
  registry and then exited 0 when it was absent, an agent that wrote its state under a
  readable label of its own devising left both gates inert, and in that clone neither had EVER
  blocked a turn-end across 189 registered sessions. The `BROKEN` verdict exists because of
  that incident — do not read its existence as making the label safe.
- **Bounded, not absolute — and the bound is DURABLE, not a duty cycle.** Each gate keeps its
  OWN consecutive-block counter and stands down once `HOOK_BLOCK_CAP` (default 8, validated
  into [1, 64]) is reached, so a session cannot wedge. Reaching it also writes a durable
  `.capped` marker beside that counter, and the marker is the point: without it, MEASURED over
  eleven consecutive Stop events, attempts 1-8 were refused, attempt 9 was released and reset
  the count, and attempts 10-11 began refusing again — eight forced continuations, one exit,
  then eight more, forever. What clears the count and the marker is a genuine release — a pass on
  the merits, which for the loop gate means an idle `Status`, a terminal value, a substantive
  `AWAITING_USER` or no claimed work, and for the evidence gate a phase outside IMPLEMENT/VERIFY,
  a terminal status, a recorded escalation, or evidence that checks out. A stand-down is not one:
  neither reaching the cap nor standing down on an unwritable counter clears
  anything. The LOOP gate additionally clears them whenever the state it
  reads CHANGES — a fingerprint over `Status`, `Phase`, `CURRENT_ISSUE`, `AWAITING_USER`,
  `BRANCH` and `WORKABLE_ISSUES_REMAIN` — so a run that is actually advancing never reaches the
  cap. The evidence gate fingerprints its OWN subject instead — the phase, the spec, and the name
  and size of every capture under it — so capturing a new result clears its count the same way.
  The stand-down message says the work is NOT done and does not certify it. Reaching the cap is
  a defect to diagnose, never a sanctioned way to stop. (The harness independently ends a turn
  after 8 consecutive blocks, so the default matches that ceiling rather than inventing one.)
- **The releases are an explicit vocabulary, and an unrecognised value means WORK IN FLIGHT.**
  A gate releases only on an affirmative statement: an idle `Status`, a terminal `Phase` or
  `Status`, or a substantive `AWAITING_USER`. The terminal vocabulary is matched WHOLE-VALUE and
  case-insensitively, in BOTH gates now — so `Phase: DONE` releases and
  `Status: COMPLETED (was IN_PROGRESS)` does not; the evidence gate used to test it with a
  prefix-matching grep and released on exactly that narrative form. The idle vocabulary is the
  loop gate's alone, matched the same way. Guessing a status word wrong is therefore
  safe: it holds the turn rather than silently freeing it. `Status: IN_PROGRESS` is not the
  condition at all — it neither arms nor releases anything, and the loop gate has a fourth
  release for the reason why: every session is registered and seeded, so the brake additionally
  requires evidence that TRACKED WORK was claimed (a real `CURRENT_ISSUE`, a `CURRENT_SPEC`, or
  an orchestrator `MODE`), and a run that has claimed none is not the work it governs. The
  evidence gate has the OPPOSITE rule inside an implementation phase, deliberately: there an
  absent `CURRENT_SPEC` or `tasks.md` is unfinished work, not nothing to check.
  `agent-state-convention.md` §1d-bis lists every accepted value; that list exists because its
  absence was measured letting seven plausible status words (`WORKING`, `ACTIVE`,
  `in progress`, …) each disable the brake.
- **`continuous-work-reinject.sh`** (SessionStart, matcher `compact|resume|startup`) puts
  this contract and your recorded place back into context at the moments you are likeliest
  to have lost them. When you see it, act on it: resume the phase it names. If it says it
  could not identify your run, that is a defect to repair — not permission to guess, and
  never a reason to adopt another run's issue number.
- **The contract handshake.** A session that started before this rule was deployed is
  refused ONCE per contract version, with the contract in the refusal text, and must write
  an ack file. A blocking Stop hook's stderr is what carries it: a hook that exits 0 has its
  stderr sent to the debug log, where the agent never sees it — so a gate that warns instead
  of blocking communicates with nobody. See `hooks/MIGRATION.md`, which also records which
  live sessions this does and does NOT reach.
- **`/goal <condition>`** — the user's strongest lever, and the only one that does not depend
  on this run judging its own completeness. It keeps Claude working across turns until an
  independent evaluator confirms the condition holds, so "am I done?" stops being the working
  model's call. Pair it with `/auto-work` or `/continue-work` for an unattended run. If you
  are ever genuinely forced to end a turn early, recommend it in one line.
- **`/continue-work`** — the manual restart. Needing it means this rule was not honored.

Outside the gates' reach — an ordinary chat session, a phase they do not cover, a project
that installed the rule without the hooks — **this rule text is the only thing standing
between a long run and an unnecessary halt.** Behave as though nothing is watching, because
frequently nothing is.

## Self-check before ending any turn

1. Is the top-level task the user gave me complete? If yes, stop.
2. If no: is a Proven Exception in play, and can I quote the proof?
3. Did I record it as an `AWAITING_USER` line naming the ACTUAL reason (not the literal `<reason>`, which is
   rejected as a placeholder) — and on the issue/spec?
4. Is there any part of the task that does NOT depend on the answer? If yes, do that
   instead of stopping.
5. Am I about to write a summary of finished sub-work? That is the disguised check-in.
   Take the next real step instead.
