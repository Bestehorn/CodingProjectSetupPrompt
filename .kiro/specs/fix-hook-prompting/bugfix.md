# Bugfix Requirements Document

## Introduction

The `KiroProjectSetupPrompt.txt` file is a comprehensive prompt for setting up Python development environments with AWS CDK using Kiro-native configuration. It contains 10 user-reported issues plus 9 additional issues identified during a best-practices review, spanning incorrect hook trigger types, wrong Kiro hook schema field names, missing steering files, missing setup steps, wrong coding standards, and missing operational files. These issues cause the prompt to produce incomplete or incorrect project setups when executed, leading to environments that lack critical guardrails, use wrong automation triggers, produce invalid hook files, and miss important operational workflows.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the prompt creates hooks (e.g., `post-implementation-ci.kiro.hook` in 9.1, `lint-on-save.kiro.hook` in 9.2) THEN the system assigns automated triggers (`agentComplete`, `fileEdited`) for workflows that should be manually triggered by the user, and the automatic workflow conversion process in Part 9 defaults to automated triggers (`fileEdited`, `agentComplete`) instead of defaulting to `manual`

1.2 WHEN the prompt is executed on a project that has no `venv/` directory THEN the system does not create the venv or install required packages as part of the initial setup flow (Part 13 only documents the steps but the prompt lacks an explicit mandatory creation-and-install step integrated into the main execution flow)

1.3 WHEN the Cline rule `use-venv.md` is migrated THEN the system merges it into `tech-stack.md` instead of creating a dedicated `.kiro/steering/use-venv.md` file, losing the strict enforcement that CLI interactions must use the venv and that the venv must be recreated if missing

1.4 WHEN the prompt creates steering files THEN the system does not create a `.kiro/steering/no-environment-vars.md` file, allowing environment variables to be used in code and CLI activities which can overwrite variables from other projects on the same physical hardware

1.5 WHEN the prompt detects a `cdk/` directory with CDK code THEN the system does not create a `.kiro/steering/cdk-deployment-only.md` file, allowing direct AWS infrastructure modifications via CLI commands instead of enforcing CDK-only changes

1.6 WHEN the prompt creates hooks THEN the system does not include a manual CI workflow hook with the strict instruction to run all CI steps and fix ALL issues without stopping, or merges this instruction into an existing similar hook

1.7 WHEN the prompt creates hooks THEN the system does not create an `AutoRebase` manual hook for handling remote repository synchronization and conflict resolution on both main and feature branches

1.8 WHEN the prompt sets up the project THEN the system does not create a `.kiro/settings.json` file that ensures terminals are automatically started with the activated venv, and does not copy from `.vscode/settings.json` as a starting point when available

1.9 WHEN the prompt defines coding standards in `coding-standards.md` (item 4) THEN the system enforces relative imports within `src/` ("All imports within src/ must be relative") instead of enforcing absolute paths with path resolution in Python code

1.10 WHEN the prompt sets up the project THEN the system does not create `docs/lessons-learned.md`, does not add a step in `pre-work.md` requiring the assistant to read this file before any work, and does not create `.kiro/steering/use-lessons-learned.md` for documenting lessons from user interruptions

### Additional Defects (Best Practices Review)

1.11 WHEN the prompt defines coding standard #2 (OOP Design) THEN the system enforces "One class per file with matching filename" which is Java-style, not Pythonic — Python convention groups related classes in a module per PEP 8

1.12 WHEN the prompt defines hook action types in Part 9 THEN the system uses `"type": "shell"` but Kiro's actual hook schema uses `"type": "runCommand"` with a `"command"` field, producing invalid hooks

1.13 WHEN the prompt defines hook trigger types in Part 9 THEN the system uses `"agentComplete"` but Kiro's actual schema uses `"agentStop"`, and uses `"manual"` but Kiro's actual schema uses `"userTriggered"`, producing invalid hooks

1.14 WHEN the prompt documents the hook JSON schema in Part 9 THEN the system does not clearly mark the `"name"` field as required in the JSON structure documentation, though it is required by Kiro

1.15 WHEN the prompt places Virtual Environment setup at Part 13 THEN the system creates the venv too late — Parts 5, 7, and 14 depend on it. Part 13 should be moved up or replaced by the new Part 1.5

1.16 WHEN the prompt configures code quality tools (black + isort + flake8) THEN the system does not mention `ruff` as a modern single-tool replacement, and does not provide migration instructions for existing CI workflows using the three separate tools

1.17 WHEN the prompt defines tech-stack.md with "pathlib (not os.path)" THEN the system does not enforce this in coding-standards.md, leaving the preference unenforced. A separate steering file should enforce pathlib usage

1.18 WHEN the prompt does not mention `__init__.py` files THEN the system provides no guidance on creating or maintaining them, which is critical for the `src/` layout with absolute imports

1.19 WHEN the user-provided content for steering files contains typos THEN these typos would be baked into the prompt: "actived" (should be "activated") in use-venv.md, "envrionment" (should be "environment") in no-environment-vars.md, "he user" (should be "the user") and "sumamrize" (should be "summarize") in use-lessons-learned.md

### Expected Behavior (Correct)

2.1 WHEN the prompt creates hooks THEN the system SHALL assign `manual` triggers to all hooks by default (including `post-implementation-ci.kiro.hook` and `lint-on-save.kiro.hook`), and the automatic workflow conversion process SHALL default to `manual` trigger type instead of `fileEdited` or `agentComplete`

2.2 WHEN the prompt is executed on a project that has no `venv/` directory THEN the system SHALL create the venv using `python -m venv venv` and install all required development packages (via `pip install -e ".[dev,cdk]"`) as a mandatory step before any other setup activities that depend on the venv

2.3 WHEN the Cline rule `use-venv.md` is migrated THEN the system SHALL create a separate `.kiro/steering/use-venv.md` file (not merge into `tech-stack.md`) with the exact content enforcing that all CLI interactions must use the venv, that the venv must be recreated if missing, and that all activity must stop if the venv cannot be activated

2.4 WHEN the prompt creates steering files THEN the system SHALL create a `.kiro/steering/no-environment-vars.md` file that forbids the use of environment variables in code and CLI activities, particularly for AWS CLI profiles and authentication tokens, and directs the assistant to use MCP documentation servers to find alternatives

2.5 WHEN the prompt detects a `cdk/` directory with CDK code THEN the system SHALL create a `.kiro/steering/cdk-deployment-only.md` file that forbids direct AWS infrastructure modifications via CLI and requires all changes to go through CDK code, while allowing read-only AWS CLI commands and requiring review of the deployment script before deployment

2.6 WHEN the prompt creates hooks THEN the system SHALL include a manual hook that instructs the agent to review the `.toml` file, run all CI workflow steps, and fix ALL issues without stopping until every step passes, with the instruction that any directives preventing completion are declared null and void

2.7 WHEN the prompt creates hooks THEN the system SHALL create an `AutoRebase` manual hook that handles remote repository synchronization: merging remote changes on main branch, rebasing/merging remote main into feature branches with conflict resolution, and verifying the CI workflow still passes afterwards

2.8 WHEN the prompt sets up the project THEN the system SHALL create a `.kiro/settings.json` file that ensures terminals auto-activate the venv, copying from `.vscode/settings.json` as a starting point when it exists but `.kiro/settings.json` does not, and then reviewing for venv auto-start mechanisms

2.9 WHEN the prompt defines coding standards in `coding-standards.md` (item 4) THEN the system SHALL enforce absolute imports (not relative) and require that any path issues be resolved through modification of the Python path in code (e.g., `sys.path` manipulation or proper package configuration)

2.10 WHEN the prompt sets up the project THEN the system SHALL create `docs/lessons-learned.md` if it does not exist, add a step in `pre-work.md` requiring the assistant to read this file prior to any work, and create `.kiro/steering/use-lessons-learned.md` with instructions to document lessons learned from user interruptions into that file

### Additional Expected Behaviors (Best Practices Review)

2.11 WHEN the prompt defines coding standard #2 (OOP Design) THEN the system SHALL replace "One class per file with matching filename" with Pythonic guidance: group related classes in a module, use separate files for large or unrelated classes

2.12 WHEN the prompt defines hook action types in Part 9 THEN the system SHALL use `"type": "runCommand"` (not `"shell"`) to match Kiro's actual hook schema

2.13 WHEN the prompt defines hook trigger types in Part 9 THEN the system SHALL use `"agentStop"` (not `"agentComplete"`), `"userTriggered"` (not `"manual"`), and `"fileEdited"` (correct) to match Kiro's actual hook schema

2.14 WHEN the prompt documents the hook JSON schema in Part 9 THEN the system SHALL clearly mark `"name"` as a required top-level field in the JSON structure

2.15 WHEN the prompt orders its parts THEN the system SHALL place Virtual Environment setup early (as Part 1.5 or equivalent) and either remove Part 13 or reduce it to a cross-reference to the earlier section

2.16 WHEN the prompt configures code quality tools THEN the system SHALL replace black + isort + flake8 with `ruff` as the single tool, and provide migration instructions for existing CI workflows that use the three separate tools

2.17 WHEN the prompt defines coding standards THEN the system SHALL create a separate `.kiro/steering/` file or add a rule in coding-standards.md enforcing `pathlib` usage over `os.path` for all path operations

2.18 WHEN the prompt defines file organization or coding standards THEN the system SHALL include guidance on creating and maintaining `__init__.py` files for the `src/` layout with absolute imports

2.19 WHEN the prompt includes user-provided steering file content THEN the system SHALL fix all typos: "actived" → "activated", "envrionment" → "environment", "he user" → "the user", "sumamrize" → "summarize"

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the prompt creates steering files for tech-stack, coding-standards, design-principles, file-organization, post-activity, testing, cdk-rules, aws-config, dependencies, lambda-rules, and project-specific THEN the system SHALL CONTINUE TO create these files with their existing content and inclusion modes

3.2 WHEN the prompt performs MCP server verification and configuration (Part 0) THEN the system SHALL CONTINUE TO verify and configure all five MCP servers (AWS Doc, Strands SDK, AgentCore, AWS CDK Doc, AWS API) with their existing configurations

3.3 WHEN the prompt performs legacy dependency migration (Part 4) THEN the system SHALL CONTINUE TO detect, migrate, and clean up legacy dependency formats (requirements.txt, setup.py, setup.cfg, Pipfile, poetry, conda) following the existing migration decision tree and mapping rules

3.4 WHEN the prompt creates the directory structure (Part 1) THEN the system SHALL CONTINUE TO create all standard directories and perform Cline/Amazon Q migration detection and content preservation

3.5 WHEN the prompt creates pyproject.toml configuration (Part 5) THEN the system SHALL CONTINUE TO configure build system, project metadata, dependencies, and all tool configurations (black, isort, mypy, pytest, bandit, pylint) with the existing merge strategy

3.6 WHEN the prompt creates CI/CD workflow configuration (Part 7) THEN the system SHALL CONTINUE TO detect, preserve, and merge CI configurations with the existing conflict resolution rules

3.7 WHEN the prompt creates VS Code settings (Part 11), documentation (Part 12), spec templates (Part 10), and performs final verification (Part 14) THEN the system SHALL CONTINUE TO follow the existing migration-aware merge behavior for these components

3.8 WHEN the prompt creates the `run-ci-workflow.kiro.hook` (9.3), `test-coverage.kiro.hook` (9.4), and `sync-documentation.kiro.hook` (9.5) THEN the system SHALL CONTINUE TO include their complete prompt content with all steps, sub-steps, and detailed instructions preserved
