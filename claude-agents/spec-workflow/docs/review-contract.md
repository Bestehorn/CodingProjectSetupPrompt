# The Review Contract (read by every reviewer before writing a finding)

Installed at `.claude/docs/review-contract.md`. On demand, not always loaded. Binding for
`spec-review-agent`, `test-architect`, `standards-reviewer`, `best-practice-reviewer`,
`security-reviewer`, `devops-iac-reviewer`, and for the conductor that consolidates them.

## Purpose

The review exists to find defects that would become wrong behaviour, a security flaw,
data loss, a regression, or unmaintainable structure in THIS change. It does not exist to
produce findings. **A review that reports no findings is a normal, expected result**, and
a reviewer is judged on the defects it catches and the non-defects it does not raise.

## The finding shape (every A or B finding, no exceptions)

```
### <ID> — <one line naming the defect>
Severity: A | B | C | D
Location: <artefact> § <section, requirement id or acceptance-criterion id>
Defect: <one sentence: what is wrong>
Material-because: <the acceptance criterion it breaks> OR <failure class: wrong-behaviour |
  security | data-loss | regression | unmaintainable-by-rule <rule file>> — one sentence
Proposed-edit: <the replacement text, or "delete <exactly what>">
```

A finding graded A or B that lacks a `Material-because` naming an acceptance criterion of
the ask or one of the five failure classes, or that lacks a concrete `Proposed-edit`, is
recorded by the conductor as C and is not applied. `Location` never carries a line number.

## Forbidden findings

- Demanding a figure, measurement, byte count, timing or line number be added to a spec.
- Demanding scope beyond the ask: a new requirement, property, protocol, mechanism, alarm,
  guard or document the acceptance criteria do not call for. Note it once under
  `Residuals` at severity C.
- Re-raising a finding the conductor rejected as non-material.
- Re-opening text that an earlier iteration passed, unless the current revision's change
  contradicts it. From iteration 2 you review the delta and the fix sites.
- Grading a stylistic or wording preference as B. Wording is D.
- Demanding a property-based test for a criterion that fixes a single value or a
  configuration. Property tests are for criteria that quantify over an input domain.
- Any hedge: a finding you cannot state as a fact with evidence is not a finding.

## Severities

- **A** — the change cannot be implemented as written, or implementing it as written
  produces wrong behaviour, a security flaw or data loss.
- **B** — an acceptance criterion of the ask is not met, not tested, or contradicted;
  "Unchanged behaviour" is not protected; a documented project rule is violated.
- **C** — a clarification or a risk worth one sentence; a residual outside the ask.
- **D** — wording.

A and B gate the loop. C and D never gate, never open an iteration and are never
re-reviewed — but they are still fixed: the author applies them in the SAME pass as the
A/B fixes whenever the proposed edit restates, clarifies, tightens or removes text. A C
whose fix would add scope (a requirement, a mechanism, a protocol, a document) is recorded
under `Residuals` and left out of this change. The conductor checks a C/D pass added no
acceptance-criterion id and no requirement — a wording pass that grew the spec is a
defect of the pass.

## Output

One file per lane per iteration, ≤ 8,000 bytes: the findings in the shape above, then one
verdict line — `CLEAN` when A+B is zero, else `NOT-CLEAN (<a> A, <b> B)`. The
test-architect adds its coverage table. Nothing else: no restatement of the spec, no
methodology narrative, no evidence inventory. Your reasoning is yours; the finding is what
you deliver.
