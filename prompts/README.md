# prompts/ — what an operator pastes

| File | Use it when | What it does |
|---|---|---|
| `setup-claude.txt` | A project should work with Claude Code: brand-new, existing without either client, or an existing Kiro project (its `.kiro/` is kept and stays usable) | Installs `CLAUDE.md`, `.claude/` (settings, hooks, rules, agents, commands, docs), git hooks, check and test scripts, CI and docs |
| `setup-kiro.txt` | A project should work with Kiro | The Kiro counterpart: steering files, `.kiro/agents/`, `.kiro/hooks-bin/`, `@name` prompts, IDE hooks, and the same git hooks, scripts, CI and docs |
| `update.txt` | A project already set up by the framework should catch up with it | Pins one framework commit, inventories every installed asset against it, applies the applicable setup prompt with that delta as the worklist, compiles the project's memory, and lands one PR |

The setup prompts are also the specification `update.txt` follows: it reads the applicable one in full from the
pinned framework commit.

Give the agent the framework as a directory beside the project (for example a directory added to the session).
Framework paths in the prompts (`clients/…`, `src/…`, `templates/…`) are relative to the framework's root;
project paths (`.claude/…`, `scripts/…`, `docs/…`) are relative to the project's root.

The two setup prompts will become thin entry files that read their parts from subfolders of this directory: a
`common` one for what both setups share, and one per client for the rest
([proposal](../docs/reports/directory-restructure-proposal-2026-11-07.md), phase 2). The file names above stay.
