# Issue Filing Discipline: fix it, or file it — never file by default (ALL agents, always loaded)

Governs ONE decision: what happens to something you noticed that is not the task you were
given. Companion of `issue-tracking.md`, which governs an issue that DOES exist.

Why: an autonomous issue-driven workflow spawns its own backlog — MEASURED, 60% of all
issues (78% in the last measured month) were created by working other issues, weekly
creation went 11 → 52, and the subject mix drifted from product to process. No single
filing was wrong; the DEFAULT was. So: filing is not the cheap, diligent option — it is a
commitment of a future work cycle, and it needs a reason.

## The standard

**Only an OBSERVED defect can be filed** — one you observed with quotable evidence:
failing command output, a wrong value, an exception, a demonstrated misbehaving code
path. NOT defects: "this could go wrong" / "not hardened against X" / "a guard is
missing"; suspicious-looking patterns; theoretical races, hypothetical inputs,
unexercised edge cases; stylistic preferences. "It could theoretically go wrong"
describes all software.

**Zero filed issues is a valid and expected outcome.** Never file to demonstrate
diligence or leave a trace. **No quotas, ever** — no per-run filing targets; a sweep that
produces nothing filable correctly reports "nothing filable" plus its ledger entries.

## The fix-first evaluation (MANDATORY before any filing)

Run in order, stop at the first branch that applies, record which branch you took:

1. **Blocking the current task?** → Fix it inside the current change.
2. **Small and clear?** → **FIX IT NOW. Do not file.** (ALL of: localized; a few lines;
   no design choice; no new dependency; no public-API/schema change; provable with
   existing tests plus at most one added test. Typos, off-by-ones, wrong constants,
   missing `None` checks, stale docstrings — fixed, mentioned in commit and report, never
   tracker entries.)
3. **Needs one of these?** → File it and NAME which in the issue: `RESEARCH` (extensive
   investigation), `DESIGN-OPTIONS` (alternatives to evaluate / spec cycle),
   `OUT-OF-SCOPE` (fixing here would materially enlarge the change). A human asking is
   its own rationale: `HUMAN-REQUEST`.
4. **None of the above?** → One line in the findings ledger; nothing dropped, nothing
   filed.

Additional bars: **process machinery needs a named incident** — a gap in a hook, gate,
rule, or CI script is filable only after MEASURED damage (lost work, false merge/block,
corrupted state, wedged session); absent an incident it goes to the ledger. **Already
resolved is never filed.** **Check duplicates and neighbors first** — extend an existing
issue instead of opening a sibling. **One observation → at most one issue** (three-plus
findings sharing a root cause = ONE issue that removes the cause).

## Filing mechanics

Delegate the filing to the **issue-intake agent** (it investigates, dedupes, and writes
the structured body); call the wrapper's `create-issue` yourself only when intake is
unavailable — producing the same body. Every filed body carries these lines near the top
(the `PreToolUse` gate `.claude/hooks/issue-filing-gate.sh` blocks a create call missing
them):

```
Origin: human-request | spawned-discovery | spawned-residual | agent-sweep
Subject: product | process
Spawned-from: #<N>          (required when Origin is spawned-*)
Filing-rationale: RESEARCH | DESIGN-OPTIONS | OUT-OF-SCOPE | HUMAN-REQUEST — <one line>
```

`Origin` values: `human-request` — a person asked, or reported the symptom;
`spawned-discovery` — found while working another issue; `spawned-residual` — scope split
out of another issue; `agent-sweep` — an autonomous audit not anchored to one issue.
`Subject` is `product` if the change can alter behavior a user of the delivered system
experiences (the tie-break for deploy/build tooling), else `process`.

## The findings ledger

`docs/findings-ledger.md` is the durable, append-only home for everything the evaluation
did NOT file — sub-threshold findings, theoretical gaps, deferred checklist items. Same
evidence standard as an issue, NO obligation of work: this is what makes "nothing may be
dropped" compatible with "do not file it". Create on first use with a `# Findings Ledger`
header and this table; append one row per finding:

```
| Date | Subject | Finding | Evidence | Why not filed | Status |
```

`Status` is `open`, `promoted #N`, or `stale` (a row untouched for six weeks may be
marked stale — retained, never deleted; promote a row when it recurs or causes measured
damage).

Anti-patterns: filing what you could fix in the time the body took; filing "for the
record"; hardening ideas for machinery that never failed; splitting one root cause into
point-fix issues; reports ending in follow-up issues that never cleared the evaluation;
skipping the ledger because "it was only a small thing" — the ledger is what makes not
filing honest.
