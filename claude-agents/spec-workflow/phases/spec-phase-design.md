# Phase Fragment: REQUIREMENTS + DESIGN (by tier)

Followed by `spec-conductor` and by the orchestrator's FIX phase. Generates the artefacts
by delegating to `spec-author`. Installed at
`.claude/specs/_workflow/phases/spec-phase-design.md`.

The tier (`proportionality.md`) is fixed before this phase starts and is written to
`prompt.md` as `Tier: S|M|L` with one line of reason. The conductor passes the tier and
its byte caps in every delegate brief.

## Tier S — one artefact: `change.md` (≤ 8,000 bytes)

Invoke `spec-author` to write `change.md`:

- **Ask** — one paragraph, the operator's words where available.
- **Acceptance criteria** — numbered `AC-n`, EARS form, at most eight, each testable.
- **Unchanged behaviour** — numbered `UB-n` SHALL CONTINUE TO clauses; these drive the
  regression tests.
- **Files** — the files to be changed, by path, with one line each.
- **Tests** — one line per AC and UB naming the test (kind: example, property-based only
  where the AC quantifies over an input domain, integration) and, where runtime behaviour
  changes, the automated end-to-end check: the script under `test/e2e/` and the CI job
  that runs it after deploy (`always-test-e2e.md`).
- **Tasks** — one wave: the TEST tasks, then the IMPL tasks, each with its `Files:`.
- **Residuals** (optional, ≤ 10 lines) — what the investigation found that the ask does
  not cover, and where each was routed.

No design.md, no threat model, no operability section. If writing `change.md` shows the
ask needs a design choice between alternatives, re-tier to M with a recorded reason.

## Tier M and L — `requirements.md` then `design.md`

### REQUIREMENTS (≤ 20,000 bytes M / ≤ 40,000 bytes L)

FEATURE → `requirements.md`: a short overview, a glossary only for terms the criteria use,
numbered requirements each with a user story and EARS acceptance criteria (`AC-n.m`), an
`## Unchanged behaviour` section, and `## Residuals`. BUGFIX → `bugfix.md` with
`### Current Behavior (Defect)`, `### Expected Behavior (Correct)`, `### Unchanged
Behavior (Regression Prevention)`, all EARS, defect and regression clauses citing the code
by symbol. Criteria are concrete and testable, carry no measurements, and are FROZEN once
the design review opens.

### DESIGN (≤ 60,000 bytes M / ≤ 120,000 bytes L)

Mandatory sections; each section is as short as the ask allows, and a section that does
not apply says `Not applicable — <one line>` rather than inventing content:

- **Overview** and **Design** — components, data flow, the existing patterns followed
  (cited by symbol or path; deviations flagged).
- **## Testing Strategy** — the layers that apply and where each lives; the automated
  end-to-end check (script + CI job) where runtime behaviour changes; `Not applicable` for
  a change that alters no runtime behaviour.
- **## Correctness Properties** — one entry per acceptance criterion and per unchanged
  behaviour clause: the test kind and its oracle in one or two sentences. A Hypothesis
  sketch only where the criterion quantifies over an input domain.
- **## Security Considerations** — only where a trust boundary, credential, IAM grant or
  external input is touched; else `Not applicable`.
- **## Operability** — only where deployment or runtime behaviour changes: how it deploys,
  what it logs, how it is rolled back; else `Not applicable`.
- **## Acceptance Criteria Mapping** — the table: criterion → component → test.
- **## Residuals**.

After each artefact returns, the conductor measures it against the cap (over → "cut, do
not add") and transitions: REQUIREMENTS → DESIGN → DESIGN_REVIEW_LOOP
(`spec-phase-review.md`). No `DL-NNN` entry is owed for these transitions.

## Notes

- The conductor never writes these files itself; `spec-author` does.
- Codebase claims are cited by symbol and path, never by line number; external-technology
  choices cite MCP or web sources. Figures belong in evidence.
