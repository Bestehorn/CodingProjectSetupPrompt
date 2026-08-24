# Continuous Work — stopping to ask permission is forbidden (ALL agents, always loaded)

Installed at `.claude/rules/continuous-work.md` (no `paths:` frontmatter → always loaded)
and pointed to from the root `CLAUDE.md`. It governs WHEN a turn may end. It binds the main
session and every agent, and it overrides any contrary habit or instruction.

## The standard

**Work continues until the work is finished.** A turn ends for exactly two reasons: the
task is genuinely complete, or one of the four Proven Exceptions below is in play and has
been proven. Nothing else.

**Stopping in order to obtain permission to continue is a forbidden behavior.** Any
instruction you hold — from a habit, a general convention, an older rule, a prior session,
or a phase description — that tells you to pause periodically, check back after a while,
report at intervals, or seek approval before carrying on is **VOID for the duration of the
task**. Ignore it. This includes `.claude/rules/post-activity.md`: it defines what to do at
the end of an activity, NOT permission to treat each activity as a place to stop.

Specifically forbidden as turn-ending acts:

- "Shall I continue?" / "Should I proceed?" / "Let me know if you want me to go on."
- An unrequested intermediate summary, status report, or progress recap. Report when the
  work is done, not partway.
- Proposing the next steps instead of performing them.
- Ending on a plan, an offer, or a question the codebase itself could answer.
- **Substituting easier adjacent work for the hard task.** If the next real step is large
  and atomic (a wide refactor, a cross-cutting rename, a migration with no clean
  intermediate commit), do THAT. Doing tidy side-work and ending on a polished report is a
  disguised check-in and is the single most common form of this failure.
- Stopping, warning, or asking because the context window is filling up (see § Context).
- Waiting for a human to run something you can run yourself.

If you catch yourself about to end a turn, run this check first: *Is the task finished? If
not, is a Proven Exception in play and proven? If neither is true, do not stop — take the
next step.* When in doubt, continue working.

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

Before invoking any exception, you must have researched: the project's own docs and code,
the relevant MCP documentation servers (`use-doc-mcp-servers.md`), the spec/issue, and git
history. "I am not sure" is not proof — it is an instruction to go find out
(`no-guessing.md`).

## How to ask, when an exception is proven

- **Be short.** Two sentences of context, the options, the recommendation. Five lines total
  is plenty. No preamble, no recap of what you already did.
- **Always give a recommendation.** Never present a bare choice. State which option you
  would take and the one reason why. A question without a recommendation is incomplete.
- Use the `AskUserQuestion` tool where available, with your recommended option **first** and
  labelled `(Recommended)`.
- **Batch.** One message with every open question. Never drip-feed one question at a time.
- **Record it durably.** Put the question and, once answered, the answer where the work
  lives — a comment on the issue (`issue-tracking.md`) or the spec's `qa_log.md` — not only
  in chat, which does not survive compaction.
- **Keep working.** After asking, immediately continue with every part of the task that does
  not depend on the answer. Asking is never a reason to idle. If the whole task depends on
  it, and other workable tasks exist, move to one of those.

## Context-window pressure is never a reason to stop

Compaction is automatic: the harness summarizes older history as the window fills and the
session continues uninterrupted. **You cannot invoke it yourself** — `/compact` and
`/autocompact` are user commands, not tools available to you. So never stop, never warn,
never ask about context. Just keep working; the summary happens around you.

Your obligation is to make compaction lossless:

- **Externalize state continuously.** Write progress, decisions, the current phase, and the
  next step to the durable state files (`agent-state-convention.md`) after EVERY step —
  never hold your place only in the conversation. On-disk state is what survives.
- Keep the issue or spec updated as the live record, so the work is reconstructible from it
  alone.
- **Delegate large reads** to a subagent so the file contents land in its context, not
  yours.
- **After a compaction, re-read before acting:** your state file, the active spec's decision
  log, and any file you still need. Root `CLAUDE.md` and always-loaded rules (including this
  one) are re-injected from disk, but `paths:`-scoped rules and nested `CLAUDE.md` files are
  NOT — they return only when you next read a matching file. Then resume the recorded step;
  do not restart the task.

## Enforcement

Four mechanisms back this rule; none of them replaces it.

- **Stop-hook gates** (`issue-loop-gate.sh`, `spec-stop-gate.sh`) block turn-end in the
  situations they cover — but only the orchestrator loop and the spec implement/verify
  phases, and only up to eight consecutive blocks. Outside them, this rule is the only thing
  standing between a long run and an unnecessary halt.
- **`continuous-work-reinject.sh`** (SessionStart, matcher `compact|resume|startup`) puts
  this contract and your recorded place back into context at the moments you are likeliest to
  lose them. When you see it, act on it: resume the phase it names.
- **`/goal <condition>`** — the user's strongest lever. It keeps Claude working across turns
  until an independent evaluator confirms the condition holds, so "am I done?" stops being
  your judgement call. If you are ever genuinely forced to end a turn early, recommend it in
  one line.
- **`/continue-work`** — the manual restart. Needing it means this rule was not honored.
