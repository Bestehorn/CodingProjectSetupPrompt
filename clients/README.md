# clients/ — the natural-language assets the prompts install

One folder per client, plus `common/`:

| Folder | Holds | Installed to |
|---|---|---|
| [`common/`](common/) | Content more than one client uses, written once: the spec-workflow phase fragments (`phases/`) and the on-demand docs both clients read (`docs/delivery.md`, `docs/review-contract.md`) | A Claude project's `.claude/` as written; a Kiro project's `.kiro/` with the Claude paths rewritten (setup-kiro PART 8A) |
| [`claude/`](claude/) | What is specific to Claude Code, laid out like a project's `.claude/`: `agents/`, `commands/`, `rules/`, `docs/` | `.claude/` |
| [`kiro/`](kiro/) | What is specific to Kiro, laid out like a project's `.kiro/`: `agents/` (`<name>.json`, and `<name>.md` where the prompt is a file), `prompts/` | `.kiro/` |

**Nothing is written twice.** Content that more than one client uses belongs in `common/`; a client folder keeps
only what genuinely differs for that client — metadata in that client's format, and files no other client has.

That is the target, not yet the state everywhere: `claude/` and `kiro/` still hold parallel versions of the 20
agents and 4 commands that both clients have, and Kiro's steering bodies are still inline in
`prompts/setup-kiro.txt`. Merging each pair into `common/`, with a renderer in `src/` that produces each
client's files from it, is the next step
([proposal](../docs/reports/directory-restructure-proposal-2026-11-07.md) §5). Until then, a change to an agent
or command that exists for both clients is made in both folders.

Per-client details: [`claude/README.md`](claude/README.md) (agent index, tool mapping, permissions, install) and
[`kiro/README.md`](kiro/README.md) (the `@name` prompts and their Claude counterparts). The agent hook runtime
both clients install is Python and lives in [`src/hooks/`](../src/hooks/).
