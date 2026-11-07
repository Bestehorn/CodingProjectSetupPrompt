# CodingProjectSetupPrompt

An engineering framework for AI-assisted software projects. Pasting one of its prompts into Claude Code or Kiro
sets up a new project, or brings an existing one up to the framework's current state: git hooks, check and test
scripts, CI, rules, agents, commands, agent hooks and docs, for either client or both.

## Which prompt to paste

| Situation | Paste |
|---|---|
| Set up a project for Claude Code (new, existing, or an existing Kiro project) | [`prompts/setup-claude.txt`](prompts/setup-claude.txt) |
| Set up a project for Kiro | [`prompts/setup-kiro.txt`](prompts/setup-kiro.txt) |
| Update a project that already uses the framework | [`prompts/update.txt`](prompts/update.txt) |

[`prompts/README.md`](prompts/README.md) explains each one.

## Layout

Each top-level directory holds one kind of asset.

| Directory | Holds | Installed into a project? |
|---|---|---|
| [`prompts/`](prompts/) | The prompts an operator pastes | No — they drive the install |
| [`clients/`](clients/) | Natural-language assets per client: `common/` (used by more than one client, written once), `claude/` (laid out like a project's `.claude/`), `kiro/` (laid out like `.kiro/`) | Yes |
| [`src/`](src/) | All Python: `hooks/` (the agent hook runtime both clients install) and `payload/` (project scripts and their tests, laid out like a project root) | Yes |
| [`templates/`](templates/) | Config skeletons, CI workflows, git hooks, and documents shipped verbatim | Yes |
| [`docs/`](docs/) | This repository's own reports and design notes, and the map from the old layout | No |
| [`test/`](test/) | Tests of the framework itself (the layout guard) | No |
| [`scripts/`](scripts/) | This repository's own tools | No |

`archive/` is git-ignored and local only. It holds retired material; the tag `cv-suite-final` restores the CV
suite and the legacy prompts on any clone. Why the layout looks like this, and what comes next, is in
[`docs/reports/directory-restructure-proposal-2026-11-07.md`](docs/reports/directory-restructure-proposal-2026-11-07.md).

## Development

Everything shipped is Python 3.9+ standard library; the suites need pytest.

```bash
python scripts/run_tests.py                       # hook suite, shipped payload tests, layout guard
python scripts/run_tests.py test/test_layout.py   # one suite or file
```

Commits run ruff, ruff-format, a secret scan, a private-key check and bandit through the tracked `.githooks/`
(enable them once per clone with `git config core.hooksPath .githooks`). Tests never gate a commit.
