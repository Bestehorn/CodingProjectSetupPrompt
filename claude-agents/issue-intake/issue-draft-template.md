<!-- Installed to .claude/docs/ by the setup prompt (Part 12/13); the agent reads it at drafting time. -->

# Issue Draft Template and Validation Checklist (issue-intake-agent)

The template below is mandatory for every drafted issue body. Every section
that references code or external sources includes inline citations.

## Issue-Body Template

```
# <Concise title, imperative mood, ~70 chars or fewer>

Origin: human-request | spawned-discovery | spawned-residual | agent-sweep
Subject: product | process
Spawned-from: #<N>
Filing-rationale: RESEARCH | DESIGN-OPTIONS | OUT-OF-SCOPE | HUMAN-REQUEST — <one line from gate G.3>

## Summary

<2–5 sentence paraphrase of the observation, grounded in evidence from
the Analysis Phase. Identify the component and the observed behavior.
No hedge words.>

## User Observation (Verbatim)

> <exact quote of the user's original message>

## Context in the Codebase

<Where this applies: file paths with line ranges, scripts, CDK stacks,
handlers, etc. Each reference quoted or summarized with a citation.>

- `<path>:<lines>` — <short description of relevant code>
- ...

## Observed vs. Intended Behavior

**Observed:** <evidence-based description with citations>

**Intended:** <evidence-based description with citations to docstrings,
comments, tests, or design docs, OR "Not explicitly documented" if the
intent is not captured anywhere in the project>

## External References

<MCP query summaries and web research citations. Each entry includes
source, brief description of what the source says, and a URL or MCP
server reference.>

- [<source>](<url-or-mcp-ref>) — <short summary>
- ...

## Suggested Scope

**Indicator:** SCOPE_QUICK_FIX | SCOPE_SPEC_REQUIRED | SCOPE_UNCLEAR

**Rationale:** <evidence-based rationale for the indicator>

## Work Items

<A structured checklist of the concrete steps a later session would take to resolve
this issue, when the work naturally decomposes into more than one step. Use the host's
task-list syntax so it renders as a trackable checklist (GitLab/GitHub `- [ ]` items,
which surface as "0 of N completed"). These describe WHAT must be done (investigation,
the change areas, tests to add, verification), NOT a prescribed implementation. A later
session ticks these off and adds items as it works (per the issue-tracking rule). Omit
this section only for a genuinely single-step issue.>

- [ ] <work item 1>
- [ ] <work item 2>

## Open Questions

<Explicit list of items that remain undefined. Each item is framed as a
question or a TODO. Including an open question is better than guessing.>

- [ ] <question 1>
- [ ] <question 2>

## Adjacent Observations (Optional)

<Findings noticed during analysis that are distinct from the observation
this issue is about. These are noted here and recorded in
`docs/findings-ledger.md` — never filed as separate issues — so the user
or a later session can decide.>

- <adjacent observation 1>

## References

- Original input captured: `.claude/agent-state/issue-intake-agent/input_capture.md`
- Code evidence ledger: `.claude/agent-state/issue-intake-agent/code_evidence.md`
- External research: `.claude/agent-state/issue-intake-agent/mcp_queries.md`,
  `.claude/agent-state/issue-intake-agent/web_research.md`

---

*Drafted by Issue Intake Agent*
```

## Draft Validation Checklist (run before filing)

  - `FILING_GATE: FILE` is recorded in `resume_state.md`, and
    `filing_gate.md` names the branch and the evidence that decided it.
  - The four provenance lines are present and consistent with the gate:
    `Origin:`, `Subject:`, `Spawned-from:` (only when Origin is
    `spawned-*`), and `Filing-rationale:` naming one of RESEARCH /
    DESIGN-OPTIONS / OUT-OF-SCOPE / HUMAN-REQUEST. The PreToolUse gate
    `.claude/hooks/issue-filing-gate.sh` blocks the create call without
    them, so a draft that omits them cannot be filed.
  - The title is concise, imperative, and specific.
  - The Summary contains no hedge words (unless inside the verbatim
    quote block).
  - Every code reference has a file path and line range.
  - At least one external source is cited, OR `mcp_queries.md` /
    `web_research.md` documents a good-faith attempt that yielded no
    useful source and this is noted in the issue.
  - The Suggested Scope indicator is present with rationale.
  - Open Questions are phrased as questions, not as claims.
  - A Work Items checklist is present (host task-list syntax) when the
    work decomposes into more than one step; omitted only for a truly
    single-step issue.
  - No content inside the drafted body describes planned fixes.
    Implementation approaches belong in a later spec session.

If the checklist surfaces a defect, revise the draft in place and
re-run the checklist.
