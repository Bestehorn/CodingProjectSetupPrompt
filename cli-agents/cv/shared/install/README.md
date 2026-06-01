# shared/install — PLACEHOLDER

Discovery installer, authored in task 15:

- `install_agents.py` — copies the `cli-agents/cv/` tree to a fixed installed
  root (`.kiro/cv-suite/` for a workspace install, `~/.kiro/cv-suite/` for a
  global install) and generates discovery configs under `.kiro/agents/` (or
  `~/.kiro/agents/`) with absolute `file://` prompt paths and absolute shared-
  script paths, resolved at install time without environment variables.
