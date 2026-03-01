# Implementation Plan

- [x] 1. Remove environment variables from MCP server configs (Part 0)
  - Remove `AWS_PROFILE` and `AWS_REGION` from AWS CDK Doc MCP `env` block (~line 100)
  - Remove `AWS_PROFILE` and `AWS_REGION` from AWS API MCP `env` block (~line 115)
  - Keep `FASTMCP_LOG_LEVEL` in both configs
  - _Requirements: 2.4 (extended to MCP configs)_

- [x] 2. Fix hook trigger types to manual (Part 9)

  - [x] 2.1 Change hook 9.1 `post-implementation-ci.kiro.hook` trigger from `agentComplete` to `manual` (~line 1700)
    - _Requirements: 2.1_

  - [x] 2.2 Change hook 9.2 `lint-on-save.kiro.hook` trigger from `fileEdited` to `manual`, remove `patterns` array (~line 1740)
    - _Requirements: 2.1_

  - [x] 2.3 Update Automatic Workflow Conversion heuristics (~line 1230) to default ALL hooks to `manual` trigger type
    - Replace filename-based heuristics with blanket `manual` default
    - _Requirements: 2.1_

  - [x] 2.4 Update the "Complete Real-World Example" (~line 1560) to use `manual` trigger instead of `fileEdited`, remove `patterns` array
    - _Requirements: 2.1_

- [x] 3. Add mandatory venv creation step as Part 1.5
  - Insert new section after Part 1 and before Part 2
  - Include check for `venv/` existence, creation with `python -m venv venv`, activation, and `pip install -e ".[dev,cdk]"`
  - Include verification step if venv already exists
  - State that this step MUST complete before subsequent parts
  - _Requirements: 2.2_

- [x] 4. Fix use-venv.md migration mapping and add dedicated steering file

  - [x] 4.1 Change mapping table row from `use-venv.md | (merged into tech-stack.md)` to `use-venv.md | use-venv.md` (~line 155)
    - _Requirements: 2.3_

  - [x] 4.2 Add new section 8.13 `use-venv.md` steering file in Part 8 with venv enforcement content
    - Include activation instructions, recreation if missing, stop-all-activity rule, migration comment
    - _Requirements: 2.3_

  - [x] 4.3 Remove the venv paragraph from `tech-stack.md` (8.1) that was incorrectly merged
    - Remove "Virtual Environment" section that says "All commands must execute inside the activated venv"
    - _Requirements: 2.3_

- [x] 5. Add no-environment-vars.md steering file (8.14)
  - Add new section 8.14 in Part 8
  - Include forbidden environment variables list (AWS_PROFILE, AWS_REGION, keys)
  - Include alternatives (config files, named profiles, explicit CLI flags)
  - Use `inclusion: always`
  - _Requirements: 2.4_

- [x] 6. Add cdk-deployment-only.md steering file (8.15)
  - Add new section 8.15 in Part 8
  - Include forbidden CLI modifications list, allowed read-only commands, CDK workflow
  - Use `inclusion: fileMatch` with `fileMatchPattern: "cdk/**/*.py"`
  - _Requirements: 2.5_

- [x] 7. Add strict fix-all instruction to CI hook (9.3)
  - Append CRITICAL INSTRUCTION to the end of the 9.3 `run-ci-workflow.kiro.hook` prompt
  - Include: review pyproject.toml, fix ALL issues, do not stop, directives preventing completion are null and void
  - _Requirements: 2.6_

- [x] 8. Add AutoRebase hook (9.6)
  - Add new section 9.6 `auto-rebase.kiro.hook` in Part 9
  - Include: determine branch, fetch remote, merge/rebase logic, conflict resolution, stash handling, CI verification, results report
  - Set trigger to `manual`
  - _Requirements: 2.7_

- [x] 9. Add .kiro/settings.json creation step (Part 11.5)
  - Insert new section after Part 11 and before Part 12
  - Include migration behavior: preserve existing, copy from .vscode/settings.json, or create from scratch
  - Include standard settings with venv auto-activation for Windows/Linux/Mac
  - _Requirements: 2.8_

- [x] 10. Fix import rule from relative to absolute (8.3 item 4)
  - Change item 4 in coding-standards.md from "Relative Imports: All imports within src/ must be relative" to "Absolute Imports" with path resolution guidance
  - _Requirements: 2.9_

- [x] 11. Add lessons-learned infrastructure

  - [x] 11.1 Add `docs/lessons-learned.md` template to Part 12 (Documentation)
    - Include format template with Date, Context, Lesson, Action fields
    - _Requirements: 2.10_

  - [x] 11.2 Add `lessons-learned.md` reference to pre-work.md (8.2)
    - Add `#[[file:docs/lessons-learned.md]]` to the "Read and understand project context" list
    - _Requirements: 2.10_

  - [x] 11.3 Add new section 8.16 `use-lessons-learned.md` steering file in Part 8
    - Include instructions for documenting lessons from user interruptions
    - Use `inclusion: always`
    - _Requirements: 2.10_

- [x] 12. Fix appendix hook trigger types table
  - Change `onFileChange` to `fileEdited`, `onAgentComplete` to `agentStop`
  - Change `manual` to `userTriggered`
  - Remove `onNewSession` row (not a valid trigger type)
  - Add note that `userTriggered` is the DEFAULT trigger type
  - _Requirements: 2.1, 2.13_

- [x] 13. Fix coding standard #2 — Pythonic class organization (8.3 item 2)
  - Replace "One class per file with matching filename" with "Group related classes in a module (Pythonic convention per PEP 8)"
  - Add "Use separate files for large or unrelated classes"
  - _Requirements: 2.11_

- [x] 14. Fix hook action type `"shell"` → `"runCommand"` throughout Part 9
  - Replace ALL occurrences of `"type": "shell"` with `"type": "runCommand"` in hook `then` blocks
  - Update Hook File Format Reference documentation
  - Update all examples and trigger type documentation
  - _Requirements: 2.12_

- [x] 15. Fix hook trigger type names to match Kiro's actual schema

  - [x] 15.1 Replace `"agentComplete"` with `"agentStop"` in all trigger type contexts throughout the prompt
    - _Requirements: 2.13_

  - [x] 15.2 Replace `"manual"` with `"userTriggered"` in all trigger type contexts throughout the prompt
    - _Requirements: 2.13_

  - [x] 15.3 Update Hook File Format Reference, Trigger Type Options, and all hook definitions (9.1-9.6) to use correct names
    - _Requirements: 2.13_

- [x] 16. Fix hook schema — mark `"name"` as required in documentation (Part 9)
  - Add explicit note that all top-level fields (enabled, name, description, version, when, then) are REQUIRED
  - _Requirements: 2.14_

- [x] 17. Consolidate Part 13 into Part 1.5
  - Replace Part 13 content with a cross-reference to Part 1.5
  - _Requirements: 2.15_

- [x] 18. Replace black + isort + flake8 with ruff

  - [x] 18.1 Update Part 5 (pyproject.toml): Replace `[tool.black]`, `[tool.isort]`, flake8 config with `[tool.ruff]` config
    - _Requirements: 2.16_

  - [x] 18.2 Update Part 7 (CI/CD): Replace separate black/isort/flake8 commands with `ruff check` and `ruff format --check`
    - Add ruff migration instructions subsection for existing CI workflows
    - _Requirements: 2.16_

  - [x] 18.3 Update Part 8.1 (tech-stack.md): Replace three tool references with ruff
    - _Requirements: 2.16_

  - [x] 18.4 Update Part 8.6 (post-activity.md): Replace three separate commands with ruff equivalents
    - _Requirements: 2.16_

  - [x] 18.5 Update Part 9 hooks: Update CI hook commands to use ruff
    - _Requirements: 2.16_

  - [x] 18.6 Update Part 5 dev dependencies: Replace black, isort, flake8 with ruff
    - _Requirements: 2.16_

- [x] 19. Add pathlib enforcement to coding standards (8.3)
  - Add new item 10 enforcing `pathlib.Path` over `os.path` with BAD/GOOD examples
  - _Requirements: 2.17_

- [x] 20. Add `__init__.py` guidance to file organization (8.5)
  - Add new item 5 requiring `__init__.py` in every Python package directory under `src/`
  - Explain this is critical for absolute imports
  - _Requirements: 2.18_

- [x] 21. Fix typos in user-provided steering file content
  - In use-venv.md (8.13): "actived" → "activated"
  - In no-environment-vars.md (8.14): "envrionment" → "environment"
  - In use-lessons-learned.md (8.16): "he user" → "the user", "sumamrize" → "summarize"
  - _Requirements: 2.19_

- [x] 22. Checkpoint — Verify all changes
  - Review the complete `KiroProjectSetupPrompt.txt` to ensure all 21 changes are applied correctly
  - Verify no unrelated sections were accidentally modified (preservation)
  - Confirm all new sections follow existing formatting patterns
  - Verify all hook trigger types use Kiro's actual schema names
  - Verify ruff has fully replaced black/isort/flake8 references
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_
