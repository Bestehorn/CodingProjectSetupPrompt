# Issue Filing Discipline: fix it, or file it — never file by default (ALL agents, always loaded)

This rule is shared by EVERY agent and the main session. It is installed at
`.claude/rules/issue-filing-discipline.md` (no `paths:` frontmatter → always loaded) and
is pointed to from the project's root `CLAUDE.md`. It governs ONE decision: what happens
to something you noticed that is not the task you were given. It is the companion of
`issue-tracking.md`, which governs how an issue that DOES exist is kept up to date.

## Why this rule exists

An autonomous issue-driven workflow spawns its own backlog. Verification finds defects,
evidence culture forbids dropping them, so every finding becomes a tracker entry, every
entry gets worked, and working it runs the discovery engine again. Measured on a project
built with this setup: 60% of all issues (78% in the last measured month) were created by
working other issues, weekly creation went 11 → 52, and the subject mix moved from the
product to the workflow machinery. No single filing was wrong; the DEFAULT was.

So the default changes. Filing an issue is not the cheap, safe, diligent option — it is a
commitment of a future work cycle, and it needs a reason.

## The standard

**Only an OBSERVED defect can be filed.** A filable defect is one you observed with
evidence you can quote: failing command output, a wrong value, an exception, a cited code
path whose misbehavior you demonstrated. These are NOT defects:

- "This could go wrong" / "this is not hardened against X" / "a guard is missing here".
- "This pattern is suspicious", "this looks fragile", name-based inference.
- A theoretical race, a hypothetical input, an unexercised edge case nobody hit.
- An improvement you would prefer stylistically.

That sentence — "it could theoretically go wrong" — describes all software. It does not
clear the bar.

**Zero filed issues is a valid and expected outcome.** No activity is required to end
with a filed issue. Do not file to demonstrate diligence, to prove you looked carefully,
or to leave a trace of the work. A run that fixed its issue, proved it, and filed nothing
is a complete, successful run — say so plainly in the report.

**No quotas, ever.** No agent has a per-run filing target ("file N proposals", "one issue
per finding"). If a sweep, review, or audit run produces nothing filable, its correct
output is "nothing filable" plus its ledger entries.

## The fix-first evaluation (MANDATORY before any filing)

Run this in order and stop at the first branch that applies. Record which branch you took.

1. **Blocking the current task?** → Fix it inside the current change. It is part of the
   work you were given, not a new issue.

2. **Small and clear?** → **FIX IT NOW. Do not file.** Small and clear means ALL of:
   localized to one file or a small cluster; on the order of a few lines; no design
   choice to make; no new dependency; no public-API or schema change; and provable with
   the existing tests plus at most one added test. A typo in a message, an off-by-one, a
   wrong constant, a missing `None` check, a stale docstring, a wrong path — these get
   fixed, mentioned in the commit message and the final report, and never become tracker
   entries.

3. **Does it need one of these three?** → File it, and NAME which one in the issue:
   - `RESEARCH` — finding a solution needs extensive investigation (unknown root cause,
     external behavior to establish, a spike).
   - `DESIGN-OPTIONS` — design alternatives have to be evaluated, or it needs a spec
     cycle / architectural decision.
   - `OUT-OF-SCOPE` — fixing it here would materially enlarge the current change or
     reach into unrelated subsystems; the current task's isolation is worth more than
     the fix's convenience.
   (A human asking you to file an issue is its own rationale: `HUMAN-REQUEST`.)

4. **None of the above?** → One line in the findings ledger, then move on. Nothing is
   dropped and nothing is filed.

**Process machinery needs a named incident.** A gap in a hook, gate, rule, lock protocol,
CI script, or agent prompt is filable only after it caused MEASURED damage: lost work, a
false merge, a false block, corrupted state, a wedged session. Name that incident in the
issue. Absent an incident, the gap goes to the ledger and waits for one. Guards ship at
"good enough"; adversarial completeness is reserved for the product.

**Already resolved is never filed.** If investigation proves the observation is already
fixed (the behavior cannot be reproduced, `git log` shows the fix), report that with the
citation. Do not create a tracker record of a non-defect so that someone can close it.

**Check for duplicates and neighbors first.** Before filing, search open AND recently
closed issues for the same defect or an adjacent one. Extend the existing issue (a
comment, a checklist item) instead of opening a sibling.

**One observation → at most one issue.** Never split a single finding into a family of
issues, and never file "companion" issues for candidates you discarded.

## Route every filing through the intake agent

When the evaluation says FILE, delegate the filing to the **issue-intake agent** rather
than calling the tracker yourself: it does the code investigation, the duplicate check,
and produces the structured body. Call the project's git wrapper `create-issue` directly
only when the intake agent is unavailable to you — and then produce the same body.

## Mandatory provenance fields in every filed body

Every issue this project files carries these four lines near the top. They cost nothing
at filing time and are the only way to see the loop later.

```
Origin: human-request | spawned-discovery | spawned-residual | agent-sweep
Subject: product | process
Spawned-from: #<N>          (required when Origin is spawned-*; omit otherwise)
Filing-rationale: RESEARCH | DESIGN-OPTIONS | OUT-OF-SCOPE | HUMAN-REQUEST — <one line>
```

- `Origin` — `human-request`: a person asked, or reported the symptom.
  `spawned-discovery`: found while working another issue. `spawned-residual`: scope split
  out of another issue. `agent-sweep`: produced by an autonomous audit not anchored to
  one issue.
- `Subject` — `product` if the change can alter behavior a user of the delivered system
  experiences (this is the tie-break for deploy scripts and build tooling), else
  `process`.
- The `PreToolUse` gate `.claude/hooks/issue-filing-gate.sh` blocks a create call whose
  body is missing these lines, so a filing that skipped the evaluation is stopped at the
  moment it is attempted.

## The findings ledger

`docs/findings-ledger.md` is the durable home for everything the evaluation did NOT file:
sub-threshold findings, theoretical hardening gaps, adjacent observations, deferred
checklist items. It is append-only, cheap to write, carries the same evidence standard as
an issue, and carries NO obligation of work. This is what makes "nothing may be dropped"
compatible with "do not file it": the finding is on durable record without buying a full
closure pipeline.

Create it with this header if it does not exist, and append one row per finding:

```markdown
# Findings Ledger

Findings recorded but deliberately NOT filed as issues, per
`.claude/rules/issue-filing-discipline.md`. Append-only: never delete a row; mark it
`stale` instead. Promote a row to an issue when it recurs or causes measured damage, and
record the issue number here.

| Date | Subject | Finding | Evidence | Why not filed | Status |
|---|---|---|---|---|---|
| 2026-08-21 | process | Example: gate X has no test for the empty-payload path | `.claude/hooks/x.sh:42` | theoretical; no incident | open |
```

`Status` is `open`, `promoted #N`, or `stale`. A row untouched for six weeks may be
marked `stale` — retained and re-openable, never deleted.

## Anti-patterns

- Filing an issue for something you could have fixed in the time it took to write the
  issue body.
- Filing "for the record" — to document that you noticed, that you checked, or that a
  thing is already fine.
- Filing a hardening idea for machinery that has never failed.
- Turning one root cause into three point-fix issues instead of one issue that removes
  the cause (when three or more findings share a root cause, file ONE issue to eliminate
  the cause and link the others to it).
- Ending a report with a list of "follow-up issues I opened" when none of them cleared
  the evaluation.
- Leaving the ledger unwritten because "it was only a small thing" — the ledger is the
  reason not filing is honest.
