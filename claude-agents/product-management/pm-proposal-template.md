<!-- Installed to .claude/docs/ by the setup prompt (Part 12/13); the agent reads it at drafting time. -->

# Drafting Templates (product-management-agent)

Three templates: the candidate-pool entry block (PHASE_CANDIDATE_GENERATION),
the proposal document (PHASE_DRAFTING), and the class-A update-comment
payload (PHASE_ACTING).

## Candidate-Pool Entry Block

Each candidate entry in `candidate_pool.md` uses this block format:

```
---

## C<nnn> — Class <A|B|C>

**Title:** <concise imperative title>

**Source:**
- Class A: `issue_inventory.md` entry `<issue-id>`
- Class B: `code_review_notes.md` observations `O<nnn>`, `O<mmm>`
- Class C: `research_log.md` entries + any supporting observations

**One-paragraph description (pre-evaluation):**
<short paragraph grounded in at least one citation>

**Primary citations:**
- <citation 1>
- <citation 2>

**Preliminary impact notes:**
<one or two sentences — do not score here>
```

## Proposal Document Template

Every proposal in `proposals/proposal-<NN>-<slug>.md` follows this template
exactly.

```
# Proposal <NN>: <Title>

**Class:** A (existing issue) | B (code review) | C (new feature)
**Candidate ID:** C<nnn>
**Composite Score:** <score> / 25
**Existing Issue:** <identifier + URL> (class A only)

## Executive Summary

<3–5 sentences: what the proposal is, why it matters, and what
concrete outcome the work produces. No hedge words.>

## Background and Evidence

### Codebase Evidence

- `<path>:<lines>` — <observation with quoted code or summary>
- ...

### Issue Tracker Evidence

- <linked issues, comments, PRs, historical context>

### External Evidence

- [<source>](<url-or-mcp-ref>) — <summary within 30-word limit>
- ...

## Current State

<Grounded description of how the system behaves today in this
area, with citations. For class A, summarize the existing issue
and the additional context the code review added.>

## Proposed Outcome

<What the system does after this work lands. Describe behavior,
interfaces, and user-visible consequences in factual language.>

## Scope Boundaries

**In Scope:**
- <item 1>
- ...

**Out of Scope:**
- <item 1>
- ...

## Key Requirements (Seed for Spec Session)

1. <requirement 1 — concrete and testable>
2. <requirement 2 — concrete and testable>
...

## Constraints and Considerations

- <constraint 1 — with rationale and citation>
- ...

## Affected Components

- `<path-or-module>` — <how it is affected>
- ...

## Best-Practice References

- <MCP or web citation that informs the approach>
- ...

## Open Questions

- [ ] <question for the spec session to resolve>
- ...

## Risks

- <risk 1 and proposed mitigation>
- ...

## Estimated Impact

- **User_Value:** <1–5>
- **Strategic_Fit:** <1–5>
- **Severity / Opportunity:** <1–5>
- **Feasibility:** <1–5>
- **Evidence_Strength:** <1–5>
- **Composite:** <sum>

## Suggested Scope Indicator

SCOPE_QUICK_FIX | SCOPE_SPEC_REQUIRED | SCOPE_UNCLEAR (rationale)

## References

- Candidate pool entry: `candidate_pool.md#C<nnn>`
- Scoring rationale: `scoring_matrix.md#C<nnn>`
- Code review notes: `code_review_notes.md#O<nnn>` (as applicable)

---

*Drafted by Product Management Agent*
```

## Class-A Update-Comment Payload

The structured update comment added to an existing issue in the Acting
Phase uses this payload:

```
## Product Management Review Update

This issue has been reviewed as part of a product management
pass. The following additional context from the code review and
external research is intended to seed a subsequent specification
cycle.

<full content of the proposal document, minus the "Existing
Issue" header and the duplicate Executive Summary, which the
original issue already conveys in a different form>

*Added by Product Management Agent*
```
