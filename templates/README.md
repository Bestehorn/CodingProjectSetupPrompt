# Templates

Skeleton files referenced by `KiroProjectSetupPrompt.v2.txt` and
`ClaudeCodeSetupPrompt.txt` (the templates are assistant-agnostic and
shared by both). Each template is a minimum viable starting point; the
agent copies it into the target project (renaming `*.template` to the
final filename) and then extends or adapts it as the project evolves.

| Template | Target path in project | When to use |
|---|---|---|
| `aws_config.py.template` | `src/aws_config.py` | Always (any project that talks to AWS) |
| `aws_accounts.json.template` | `config/aws_accounts.json.template` | Always (any project that talks to AWS) |
| `githooks/pre-commit` | `.githooks/pre-commit` | Always (tracked, version-controlled hook) |
| `setup-hooks.sh.template` | `scripts/setup-hooks.sh` | Always (ENABLES the tracked hooks per clone) |
| `pre-commit-config.yaml.template` | `.pre-commit-config.yaml` | Always |
| `github_wrapper.py.template` | `scripts/github_wrapper.py` | GitHub-hosted projects |
| `gitlab_wrapper.py.template` | `scripts/gitlab_wrapper.py` | GitLab-hosted projects |
| `gitlab.json.template` | `config/gitlab.json.template` | GitLab-hosted projects |

Git hooks pattern: the hooks themselves are TRACKED files under the
project's `.githooks/` directory (copied from `templates/githooks/`), so
they are committed and shared with every clone. `setup-hooks.sh` no
longer generates a hook — it points `core.hooksPath` at `.githooks` once
per clone (overriding any system-level hooks dir such as git-defender)
and ensures the hooks are executable. The setup prompt also MIGRATES any
pre-existing customized `.git/hooks/*` into the tracked `.githooks/`.

## Conventions

- Template filenames end in `.template`. The agent strips that suffix
  when copying. (Exception: files under `githooks/` are real hook files
  with no suffix — they are copied verbatim into `.githooks/`, and the
  agent records the executable bit in the index via
  `git update-index --chmod=+x`.)
- Templates may contain `{{PLACEHOLDER}}` markers. The agent must
  resolve every marker before writing the destination file.
- Templates are minimum viable — the agent extends them per project
  needs. The original templates in this directory are never modified.
