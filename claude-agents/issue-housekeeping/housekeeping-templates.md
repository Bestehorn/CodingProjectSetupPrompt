<!-- Installed to .claude/docs/ by the setup prompt (Part 12/13); the agent reads it at drafting time. -->

# Issue-Comment and Spec-Prompt Templates (issue-housekeeping-agent)

Every comment the agent posts to an issue, and every Kiro spec prompt it
drafts, follows the applicable template below exactly.

## Template A — Resolution Evidence Comment (Phase A.3)

```
## Issue Resolution Evidence

This issue has been resolved in the current codebase.

**Evidence:**
- [Commit <hash>]: <commit message> (addresses <specific aspect>)
- [File <path>:<lines>]: <description of current implementation>
- [Test <test-name>]: Verifies the correct behavior described
  in this issue

**Conclusion:** The problem described in this issue no longer
exists in the codebase as of commit <current-HEAD>.

*Documented by Issue Housekeeping Agent*
```

## Template B — Triage Comment (Phase B.4)

```
## Issue Triage

**Classification:** Type1 (Quick Fix) | Type2 (Spec Required)
**Rationale:** <evidence-based rationale>

<For Type1:>
**Planned Approach:** <description of the fix>

<For Type2:>
**Spec Session Required:** <reason why this needs a spec session>

*Triaged by Issue Housekeeping Agent*
```

## Template C1 — Implementation Plan Comment (Phase C.1)

```
## Implementation Plan

**Root Cause:** <description with code citations>
**Fix Approach:**
1. <step 1 with file:line references>
2. <step 2 with file:line references>
...
**Test Plan:**
- <test 1 description>
- <test 2 description>

*Planned by Issue Housekeeping Agent*
```

## Template C2 — Resolution Comment (Phase C.8)

```
## Resolution

**Fix Commit:** <hash>
**Changes:**
- [<file>:<lines>]: <description of change>
...
**Verification:**
- All tests pass (<N> passed, <M> skipped, 0 failed)
- New tests added: <list of test names>
- These tests verify: <what they verify>

**Evidence that the issue is resolved:**
- <specific evidence point 1>
- <specific evidence point 2>

*Fixed by Issue Housekeeping Agent*
```

## Template D1 — Kiro Spec Prompt (Phase D.2)

```
# Spec Prompt: <Issue Title>

## Context
Issue #<number>: <title>
<Summary of the problem or feature request>

## Current State
<Description of the current implementation with code citations>

## Problem Statement
<Precise description of what needs to change and why>

## Requirements
1. <Requirement 1 — concrete and testable>
2. <Requirement 2 — concrete and testable>
...

## Constraints
- <Constraint 1 with rationale>
- <Constraint 2 with rationale>
...

## Affected Components
- [<file/module>]: <how it is affected>
...

## Suggested Approach (Optional)
<If the agent has a recommended approach, describe it here with
evidence for why it is appropriate>

## Open Questions
- <Question 1 that the spec session needs to resolve>
...

## References
- Issue: #<number>
- Related code: <file references>
- Related documentation: <doc references>
- External references: <MCP/web research citations>
```

## Template D2 — Spec Prompt Posting Comment (Phase D.3)

```
## Kiro Spec Session Prompt

This issue requires a dedicated spec session due to: <reason>.

The following prompt has been prepared for the Kiro spec session:

<spec prompt content>

*Drafted by Issue Housekeeping Agent*
```
