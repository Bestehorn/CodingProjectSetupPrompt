<!-- Installed to .claude/docs/ by the setup prompt (Part 12/13); the agent reads it at drafting time. -->

# Issue Draft Template and Validation Checklist (issue-intake-agent)

The template below is mandatory for every drafted issue body. The body states THE ASK and
what is needed to locate it, in at most 4,000 bytes (`proportionality.md`). It is not a spec:
no blast-radius analysis, no risk register, no figures measured from logs or live systems, no
inventory of guards and tests that would move, no vendor-page survey. The spec the tier
permits does that work, at the size the tier permits.

## Issue-Body Template

```
# <Concise title, imperative mood, ~70 chars or fewer>

Origin: human-request | spawned-discovery | spawned-residual | agent-sweep
Subject: product | process
Spawned-from: #<N>
Filing-rationale: RESEARCH | DESIGN-OPTIONS | OUT-OF-SCOPE | HUMAN-REQUEST — <one line from gate G.3>
Tier: S | M | L — <one line: why this size, judged from the ASK>

## Ask

<Two to five sentences: what is observed or requested, and what correct looks like.
No hedge words outside the verbatim quote.>

> <exact quote of the user's original message>

## Where

- `<path>` — `<symbol>`: <one line>          (at most five entries; symbols and paths, never line numbers)

## Acceptance criteria (draft)

- AC-1 <EARS clause>                          (at most five; the spec may restate, never expand)
- AC-2 ...

## Unchanged behaviour (draft)

- UB-1 <SHALL CONTINUE TO clause>            (at most three)

## Work items

- [ ] <step a later session takes>            (host task-list syntax; omit for a single-step issue)

## Open questions

- <question>                                  (at most three; a question, not a claim)

## Source

- <the one or two external or repository sources that establish the observation, if any>
```

## Draft Validation Checklist (run before filing)

  - `FILING_GATE: FILE` is recorded in `resume_state.md`, and `filing_gate.md` names the
    branch and the evidence that decided it.
  - The provenance lines are present and consistent with the gate: `Origin:`, `Subject:`,
    `Spawned-from:` (only when Origin is `spawned-*`), `Filing-rationale:` naming one of
    RESEARCH / DESIGN-OPTIONS / OUT-OF-SCOPE / HUMAN-REQUEST, and `Tier:`. The PreToolUse
    gate `.claude/hooks/issue-filing-gate.sh` blocks the create call without the first four.
  - The body is at most 4,000 bytes. Measure it. Over → cut, do not summarize into denser
    prose.
  - The title is concise, imperative, and specific.
  - `Where` has at most five entries, each a symbol and a path, none a line number.
  - Acceptance criteria are at most five and each is testable; unchanged behaviour at most
    three.
  - Open questions are at most three and phrased as questions.
  - No section describes a fix, a design, a risk analysis, a rollout, a measurement, or a
    list of guards; no figure from a log, a metric or a live system appears anywhere.

If the checklist surfaces a defect, revise the draft in place and re-run the checklist.
