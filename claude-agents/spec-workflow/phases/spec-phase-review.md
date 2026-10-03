# Phase Fragment: REVIEW LOOPS (design + tasks)

Followed by `spec-conductor` (DESIGN_REVIEW_LOOP and TASKS_REVIEW_LOOP), by the
`issue-work-orchestrator` in its FIX phase, and by the `/spec-review` command (one pass).
Installed at `.claude/specs/_workflow/phases/spec-phase-review.md`.

The loop converges to **zero material defects** — A+B == 0 — and it converges
structurally, not hopefully: the artefacts are size-capped so every lane reads them whole,
findings must be material to the ask and carry their own fix, fixes may not add scope, and
from the second iteration only the delta is reviewed. Every reviewer and the conductor
read `.claude/docs/review-contract.md` first; it is the binding finding shape.

## Panel by tier (`proportionality.md`)

| Tier | Design review | Tasks review | Iteration caps |
|---|---|---|---|
| S | `spec-review-agent` alone, in COMBINED mode (all six lenses in one pass; the security lens is mandatory when auth, IAM, secrets or input handling is touched) | none — `change.md` carries the task list | 2 |
| M | full panel: `spec-review-agent` (report-only), `test-architect`, `standards-reviewer`, `best-practice-reviewer`, `security-reviewer`, `devops-iac-reviewer` | `spec-review-agent` + `test-architect` | 4 design, 2 tasks |
| L | full panel | `spec-review-agent` + `test-architect` | 6 design, 3 tasks |

**Every lane of a panel is dispatched in ONE message** (`parallel-by-default.md`). Each
lane writes only `review/<lane>/iteration-NN.md` (≤ 8,000 bytes) and never the decision
log; the conductor is the Authoritative Writer (`agent-state-convention.md` §1c).

## Before dispatching: the cap check

Measure the artefacts. Over the tier's byte cap → do not dispatch; return the artefact to
`spec-author` with "cut, do not add" and the cap. Re-tier UP only with a recorded reason
that names what in the ASK the tier missed — never because the analysis grew.

## Iteration 1 — whole-artefact review

Each lane reads the whole `requirements.md` (or `change.md`) and `design.md`, applies its
lens, and writes findings in the contract's shape.

## Iteration N ≥ 2 — delta review

The conductor hands every lane: (a) the diff between the revision it last reviewed and the
current one, (b) the list of findings that were applied, rejected or downgraded, with the
reason. Lanes review the changed regions and the fix sites. Text that passed in an earlier
iteration stays passed unless the current change contradicts it. A finding on unchanged
text must say which change contradicted it, or it is downgraded to C.

## Aggregation (the conductor, after every panel)

1. Read every lane file. Apply the **materiality gate**: an A or B that lacks a
   `Material-because` naming an acceptance criterion of the ask or one of the five failure
   classes, or that lacks a concrete `Proposed-edit`, or that demands a figure, a line
   number, or scope beyond the ask, is recorded as C with the reason. A finding rejected
   this way may not be re-raised, and the lane is told so in the next brief.
2. Dedupe across lanes (one defect, one entry; keep the stricter grade when lanes agree it
   is material and disagree on grade).
3. Write `review/review-latest.md`: the surviving A/B list, the C/D list, the rejections
   with reasons, the combined A+B, and the coverage table from `test-architect`. One
   `DL-NNN` entry only when a finding was rejected or downgraded (a decision), not for the
   round itself.

## Readiness gate (both must hold)

- **Negative:** combined A+B == 0, computed against the CURRENT artefacts (a lane's verdict
  on a stale revision is re-run, not trusted).
- **Positive:** `test-architect` reports every acceptance criterion mapped to at least one
  test task and every "Unchanged behaviour" clause covered, with zero GAP rows — verdict
  `TEST-READY`. Property-based tests are required only where a criterion quantifies over an
  input domain.

When both hold and C/D findings remain: `spec-author` applies them in ONE pass (restate,
clarify, tighten, delete — never add), the conductor verifies the pass added no
requirement, criterion or mechanism, and the phase is approved WITHOUT another panel
round. When both hold and nothing remains: approved.

## Otherwise — revise and loop

Invoke `spec-author` with the aggregated A/B findings AND the C/D findings, the scope
freeze (`proportionality.md`: restate or remove, never add; anything outside the ask goes
to `## Residuals`), and the byte cap. Increment NN and re-dispatch the panel in delta mode.

## Cap — and what happens at it

When the tier's cap is reached with A+B > 0, or A+B has not decreased across two
consecutive iterations, the loop stops. The conductor puts ONE question in the five-line
shape of `continuous-work.md`, recommended option first:

1. **(Recommended)** Approve the reviewed spec as it stands; record the open A/B findings
   under `## Residuals` with their proposed edits; any residual that is a genuine new ask
   becomes its own issue via intake.
2. One more full round (name what changed that makes convergence likely).
3. Narrow the ask (name the criterion to drop).

Record the answer as `DL-NNN` and continue. The old default of "keep running full rounds
until the gate passes" is not offered: it is the measured cause of a sixteen-round review
of a one-constant change.

## `/spec-review` standalone

Perform ONE panel iteration over the current spec (whole-artefact if no earlier iteration
exists, else delta), write the lane files and `review/review-latest.md`, print the combined
A+B and the coverage table, and stop.
