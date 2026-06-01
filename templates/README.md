# Templates

Skeleton files referenced by `KiroProjectSetupPrompt.v2.txt`. Each
template is a minimum viable starting point; the agent is expected to
copy it into the target project (renaming `*.template` to the final
filename) and then extend or adapt it as the project evolves.

| Template | Target path in project | When to use |
|---|---|---|
| `aws_config.py.template` | `src/aws_config.py` | Always (any project that talks to AWS) |
| `aws_accounts.json.template` | `config/aws_accounts.json.template` | Always (any project that talks to AWS) |
| `setup-hooks.sh.template` | `scripts/setup-hooks.sh` | Always |
| `pre-commit-config.yaml.template` | `.pre-commit-config.yaml` | Always |
| `github_wrapper.py.template` | `scripts/github_wrapper.py` | GitHub-hosted projects |
| `gitlab_wrapper.py.template` | `scripts/gitlab_wrapper.py` | GitLab-hosted projects |
| `gitlab.json.template` | `config/gitlab.json.template` | GitLab-hosted projects |

## Conventions

- Template filenames end in `.template`. The agent strips that suffix
  when copying.
- Templates may contain `{{PLACEHOLDER}}` markers. The agent must
  resolve every marker before writing the destination file.
- Templates are minimum viable — the agent extends them per project
  needs. The original templates in this directory are never modified.
