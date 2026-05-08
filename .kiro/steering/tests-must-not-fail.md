---
inclusion: always
---
# Tests Must Not Fail — Mandatory Test Fixing (CRITICAL)

## Core Rule

The tests for this project exist to ensure the timely detection of regressions, errors, and deviations from specs. Whenever a test fails, you MUST fix it. It does not matter if you claim, think, or evaluate that this is a "pre-existing" issue or that the issue is unlikely to be related to any change you have made — you MUST FIX IT.

## Understanding Before Fixing

Fixing a failing test means you must understand what the test case was supposed to test. You will gain this understanding by:

1. **Review ALL related code**: Read the test file, the source code under test, any fixtures, helpers, conftest files, and related modules. Do not skip any file that could be relevant.
2. **Analyze the failure**: Determine the root cause of the test failure. You must prove to yourself that you have understood the purpose of the test (see the no-guessing steering file — no assumptions, only evidence).
3. **Trace the intent**: Identify what behavior the test was designed to verify. Read docstrings, comments, commit history, and spec documents if available.

## Forbidden "Fixes"

Under NO circumstances are the following considered acceptable solutions:

- **Skipping the test** (`@pytest.mark.skip`, `pytest.skip()`)
- **Removing the test**
- **Marking it as expected failure** (`@pytest.mark.xfail`)
- **Commenting out the test**
- **Disabling the test in any way**

The test was implemented to verify a certain behavior. Unless there is a specific, documented design reason to remove it (e.g., the feature it tests has been intentionally removed per a spec change), the test must continue verifying its intended behavior.

## Fix Evaluation Process

1. **Consult documentation**: Access MCP documentation servers (AWS Doc MCP, Strands SDK MCP, AgentCore MCP, CDK Doc MCP, or other relevant sources) to evaluate potential fixes. Also consult internal project documentation (`docs/`).
2. **Evaluate multiple approaches**: Consider at least two potential fixes before choosing one.
3. **Choose the best long-term solution**: Select the fix that is the most maintainable, correct, and aligned with the project's design principles. No short-term fixes, hacks, or workarounds.
4. **Implement the fix**: Apply the chosen solution to the source code (not the test, unless the test itself has a genuine bug in its test logic — not in the assertion expectations).
5. **Rerun the test**: Execute the test to confirm it passes.
6. **Repeat if necessary**: If the test still fails after the fix, go back to step 1 of "Understanding Before Fixing" and repeat the entire procedure until the test succeeds.

## Integration with Other Steering Rules

- All claims about why a test fails must be backed by evidence (per **no-guessing** rule)
- Fixes must follow **coding-standards** and **design-principles**
- After fixing, run the full **post-activity** checklist to ensure no regressions were introduced
- Document any lessons learned from the failure (per **use-lessons-learned** rule)

<!-- MIGRATION: Add any project-specific test fixing policies below -->
