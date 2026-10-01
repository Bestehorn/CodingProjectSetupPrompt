# kiro-prompts/ — reusable Kiro prompts (`@name`)

Kiro counterparts of the Claude Code slash commands in [`claude-commands/`](../claude-commands/).

Kiro has **no user-defined `/name` slash commands** — that is a Claude Code concept. The
equivalent surface is Kiro's *file-based prompts*: a markdown file placed in

- `.kiro/prompts/` — workspace scope (what the setup prompt installs), or
- `~/.kiro/prompts/` — global scope,

invoked in `kiro-cli` chat with the **`@` prefix**: `@auto-work`. Local prompts override
global ones of the same name, and prompts take precedence over same-named file references.
Manage them with `/prompts list`, `/prompts edit <name>`, `/prompts details <name>`.

**File-based prompts take no arguments** (only MCP prompts do). A Claude command that reads
`$ARGUMENTS` therefore has no direct Kiro prompt equivalent — either drop the argument (as
`auto-work` does) or have the user state it in the following message.

The Kiro **IDE** has no `@prompt` invocation. For IDE parity, install a `userTriggered`
`.kiro.hook` whose `askAgent` prompt tells the agent to read the prompt file — that keeps
one source of truth instead of duplicating the workflow into the hook JSON. See
`KiroProjectSetupPrompt.v2.txt` Part 9.4a for the `auto-work` example.

## Contents

| File | Invoke as | Claude Code counterpart |
|---|---|---|
| `auto-work.md` | `@auto-work` (CLI) / "Auto-Work the Issue Backlog" hook (IDE) | `/auto-work` (`claude-commands/auto-work.md`) |
| `continue-work.md` | `@continue-work` (CLI) / "Continue Work" hook (IDE) | `/continue-work` (`claude-commands/continue-work.md`) |
| `close-session.md` | `@close-session` (CLI) / "Close Session" hook (IDE) | `/close-session` (`claude-commands/close-session.md`) |
| `compile-memory.md` | `@compile-memory` (CLI) / "Compile Memory" hook (IDE) | `/compile-memory` (`claude-commands/compile-memory.md`) |

## Install

`KiroProjectSetupPrompt.v2.txt` Part 8A.5 does this for you:

```bash
mkdir -p .kiro/prompts
cp kiro-prompts/auto-work.md      .kiro/prompts/
cp kiro-prompts/continue-work.md  .kiro/prompts/
cp kiro-prompts/close-session.md  .kiro/prompts/
cp kiro-prompts/compile-memory.md .kiro/prompts/
```

`compile-memory` is the maintenance pass that keeps the always-loaded corpus and the memory
docs under their caps (`templates/test_instruction_corpus_budget.py.template`): it archives
aged ledger rows and lessons to `docs/archive/`, turns recurring ones into tests or rules, and
moves incident narratives out of steering files. Run it when the corpus test goes red, and
once per framework update.

`auto-work` depends on the Part 8A advanced fleet (`issue-work-orchestrator`, the
spec-workflow specialists, `code-merge-reviewer`) and the Part 8A.2 gate scripts in
`.kiro/hooks-bin/` — in particular the `issue-loop-gate` gate, the `stop` gate that mechanically
holds the agent in the backlog loop, and the `claim-before-worktree` gate, which blocks
creating a worktree for an unclaimed issue. Like every orchestrator run, it ends with the
agent definition's fixed Completion Block (`ISSUE WORK FINISHED | BLOCKED | FAILED` over a
per-issue table), never a free-form summary.

`continue-work` has no fleet dependency — it restarts any stalled session. Both prompts
assume the `continuous-work` steering rule (Part 8.33) is installed; that rule is the
behavioral fix, and `@continue-work` is only the manual recovery path for when it fails.

`close-session` is the end-of-session close-out: it finishes what is unfinished, then
verifies, then reports ONE fixed nine-row table — one row per step, a single ✅/❌/➖ mark
each, details capped at 60 characters, an `Issues` block of one line per issue worked or
filed underneath, and nothing else (a clean single-issue close-out is 16 lines). Its step 2
is the task-item gate — it counts the issue's `- [ ]` / `- [x]` lines from a fresh wrapper
read and, if the issue was CLOSED while items were still unfinished, REOPENS it, says so,
finishes them, and re-closes. That needs the wrapper's `issue reopen` / `reopen-issue`
subcommand and its checklist toggle (Part 6.2). Its worktree/lock/CI steps degrade gracefully
outside an orchestrator run. Two endings differ from the Claude twin: Kiro has no
session-archive tool (the table is the go-ahead; `/quit` is the user's), and no structured
question tool, so a blocker needing a decision becomes one batched `Questions` block instead
of an `AskUserQuestion` call.
