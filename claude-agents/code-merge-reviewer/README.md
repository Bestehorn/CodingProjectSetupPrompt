# Code Merge Reviewer

A mandatory, dedicated subagent for integrating local code with remote code whenever a
**conflict** arises (rebase, merge, `stash pop`). It exists to stop the single most
damaging careless behavior in autonomous git work: resolving a conflict by blindly
"taking one side", which silently overwrites another developer's changes and
reintroduces bugs.

## What it guarantees

- **Holistic first, then line-by-line.** It reviews the whole merge (what's being
  integrated and why, conflicted *and* clean changes) before resolving anything, then
  decides **every conflict hunk line by line**.
- **Both intents preserved.** Blind `--theirs`/`--ours`/`-X ours`/`-X theirs`/accept-all
  is forbidden. A side is dropped only with a recorded, evidence-based reason that it is
  safe (superseded/duplicated/obsolete); otherwise both intents are kept.
- **Regression-avoidance is the prime directive.** After resolving, it runs the full
  test suite in the target tree and only declares the merge done when the suite is green
  — a merge that breaks tests means a change was lost or two changes interact badly, and
  it goes back and fixes the resolution (never weakens the test).
- **Evidence + decision log.** It returns a structured merge report (per-file resolution
  summary, what was preserved/dropped and why, quoted final test result) and writes
  `DL-NNN` entries.

It never pushes and never opens PRs — it hands a cleanly-integrated, test-verified tree
back to the caller.

## How it's used (mandatory delegation)

Any agent that hits a merge/rebase conflict MUST delegate it to `code-merge-reviewer`
via the `Agent` tool rather than resolving conflicts itself. The
`issue-work-orchestrator` does this in its Remote Sync sub-procedure and in the PR
rebase step; its `tools:` line includes `Agent(code-merge-reviewer, …)`. Because
subagents cannot nest, the delegation must originate from a main-session agent (the
orchestrator, or you in an interactive session).

The shared rule `.claude/rules/keep-git-clean.md` points all agents at this agent for
conflict resolution.

## Install

```bash
mkdir -p .claude/agents
cp claude-agents/code-merge-reviewer/code-merge-reviewer.md .claude/agents/
```

`ClaudeCodeSetupPrompt.txt` (Part 13) installs it alongside the issue-work-orchestrator.

## Scope and state

- Tools: Read, Write, Edit, Bash, Grep, Glob (no remote/wrapper ops — it works on the
  local tree only).
- State: `.claude/agent-state/code-merge-reviewer/`; decisions logged per
  `.claude/rules/agent-state-convention.md`.
- Follows `keep-git-clean`, `no-output-shortening`, `no-guessing`, `use-venv`,
  `no-ai-attribution`. Never touches `.kiro/`.
