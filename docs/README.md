# docs/ — this repository's own documentation (never installed into a project)

| Folder | Holds |
|---|---|
| [`reports/`](reports/) | Dated analyses and proposals behind the framework's revisions: root-cause analyses, forensics, designs |
| [`design/agents/`](design/agents/) | Design and authoring notes of the agents: the spec workflow, the issue-work orchestrator, the code-merge reviewer, and the original Kiro discussions and prompt drafts |

Documents that ARE installed into a project's `docs/` live in [`templates/docs/`](../templates/docs/).

## Old paths (before 2026-11-07)

The reports, the design notes' `.txt` drafts and the Kiro specs in `.kiro/specs/` are records: they still name
the paths of their time. This table maps them.

| Old | New |
|---|---|
| `ClaudeCodeSetupPrompt.txt` | `prompts/setup-claude.txt` |
| `KiroProjectSetupPrompt.v2.txt` | `prompts/setup-kiro.txt` |
| `FrameworkUpdatePrompt.txt` | `prompts/update.txt` |
| `KiroProjectSetupPrompt.txt` (v1), `PythonProjectSetupPrompt.txt` | archived (tag `cv-suite-final`) |
| `claude-agents/<family>/<agent>.md` | `clients/claude/agents/<agent>.md` |
| `claude-agents/spec-workflow/rules/` | `clients/claude/rules/` |
| `claude-agents/spec-workflow/phases/` | `clients/common/phases/` |
| `claude-agents/spec-workflow/docs/delivery.md`, `review-contract.md` | `clients/common/docs/` |
| `claude-agents/spec-workflow/docs/run-identity.md` and the four agent-sibling templates | `clients/claude/docs/` (`language-matrix.md` as `dead-code-language-matrix.md`) |
| `claude-agents/spec-workflow/hooks/` | `src/hooks/` |
| `claude-agents/README.md` | `clients/claude/README.md` |
| `claude-agents/{spec-workflow,issue-work-orchestrator,code-merge-reviewer}/README.md` | `docs/design/agents/<family>.md` |
| `claude-commands/` | `clients/claude/commands/` |
| `cli-agents/**/KiroCLIAgent-<Name>.json`, `cli-agents/**/<name>.md` | `clients/kiro/agents/<name>.json`, `clients/kiro/agents/<name>.md` |
| `cli-agents/spec-workflow/hooks/kiro_hooks.py` | `src/hooks/kiro_hooks.py` |
| `cli-agents/issue-work-orchestrator/README.md` | `docs/design/agents/issue-work-orchestrator-kiro.md` |
| `cli-agents/**/*Discussion.txt` and the prompt drafts | `docs/design/agents/` |
| `kiro-prompts/README.md`, `kiro-prompts/*.md` | `clients/kiro/README.md`, `clients/kiro/prompts/` |
| `templates/<name>.py.template` | `src/payload/scripts/<name>.py`; `test_*` → `src/payload/test/`; `aws_config` → `src/payload/src/` |
| `templates/{aws_accounts,delivery,gitlab}.json.template` | `templates/config/` |
| `project-docs/codebuild-ci-backup-mechanism.md`, `project-docs/README.md` | `templates/docs/` |
| `project-docs/<report>.md`, `ClaudeCodePortingAnalysis.md`, `KiroAdaptationAnalysis.md` | `docs/reports/` |
| `claude-agents/cv/`, `cli-agents/cv/`, `.kiro/specs/cv-customizer-agents/` | archived (tag `cv-suite-final`) |
| `scripts/push_repo.ps1` | deleted (`core.hooksPath` is set once per clone) |
