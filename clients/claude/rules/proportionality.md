# Proportionality — size the work to the ask (ALL agents, always loaded)

Governs how much specification, review and ceremony a change receives. The ask decides,
never the analysis: a one-constant change stays a one-constant change however many files,
guards or risks the investigation turns up. Discoveries that are not the ask become
residuals, ledger rows, or their own issue.

## Tiers (decided from the ASK, at classification, recorded once)

| Tier | The ask is | Artefacts and hard byte caps | Review | Implementation |
|---|---|---|---|---|
| **S** | a value, default, config, message or doc change; a bounded local fix; one component; no new interface | `change.md` ≤ 8,000 B (ask, acceptance criteria in EARS, unchanged behaviour, files, tests incl. the E2E check) | ONE combined pass (`spec-review-agent`, all lenses; security lens mandatory when auth, IAM, secrets or input handling is touched); max 2 iterations | one wave |
| **M** | a feature or fix across several components with a design choice | `requirements.md` ≤ 20,000 B, `design.md` ≤ 60,000 B, `tasks.md` ≤ 15,000 B | full panel, dispatched in parallel; max 4 design iterations, 2 tasks iterations | waves |
| **L** | a new subsystem or a cross-cutting change | double the M caps | full panel; max 6 design iterations, 3 tasks iterations | waves |

Anything larger than L is split into issues before any spec is written. An infrastructure
file in the diff, a snapshot that must be regenerated, a docs edit, or a count of touched
files does NOT raise the tier; only a bigger ASK does. When in doubt, choose the smaller
tier and re-tier UP later with a recorded reason that names what in the ask was missed.

## The caps are hard

The conductor measures every artefact before dispatching a review or an implementation
wave. Over cap → back to the author with "cut, do not add": remove repetition, move
rationale to the decision log, move measurements to evidence. An artefact cannot be
brought under cap only when the ask itself is bigger than the tier — then re-tier with a
recorded reason. Every review file is ≤ 8,000 B; an issue body filed by intake is ≤ 4,000 B.

## Scope freeze

Once the design review opens, the acceptance criteria are frozen. A finding is fixed by
restating or removing text, never by adding a requirement, a property, a mechanism or a
protocol. Something the review finds that the ask does not cover is recorded in
`## Residuals` (≤ 10 lines), routed per `issue-filing-discipline.md`, and left out of this
change. The ask changes only when the person who asked changes it.

## Specs state behaviour, not measurements

A spec cites symbols, paths and acceptance-criteria ids. It never carries line numbers,
byte counts, durations, record counts, or any figure that a later commit invalidates.
Measurements are evidence: they live under `evidence/` or in test assertions. A reviewer
may not demand a figure be added to a spec, and a spec edit is never required to keep
line numbers stable.

## Time tripwires

S: 3 hours. M: 24 hours. L: 72 hours of run time from claim to merge. Crossing one is not
a stop and not a question: record it, re-tier or split (both reversible), and continue.

## Evidence is test output

`evidence/` holds captured test runs (red, green, CI verdict, verifier report) — nothing
else. Probes, measurement scripts and exploratory notebooks are either tests (committed
under `test/`) or discarded.
