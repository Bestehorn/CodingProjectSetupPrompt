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

## Install

`KiroProjectSetupPrompt.v2.txt` Part 8A.5 does this for you:

```bash
mkdir -p .kiro/prompts
cp kiro-prompts/auto-work.md .kiro/prompts/
```

`auto-work` depends on the Part 8A advanced fleet (`issue-work-orchestrator`, the
spec-workflow specialists, `code-merge-reviewer`) and the Part 8A.2 gate scripts in
`.kiro/hooks-bin/` — in particular `kiro-loop-gate.sh`, the `stop` hook that mechanically
holds the agent in the backlog loop, and `kiro-claim-before-worktree.sh`, which blocks
creating a worktree for an unclaimed issue.
