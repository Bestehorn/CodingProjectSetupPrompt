# Analysis of Current Section 9 Structure

## Location
Section 9 is located at lines 1047-1145 in KiroProjectSetupPrompt.txt (PART 9: KIRO HOOKS)

## Current Hook Examples Found

### 1. `post-implementation-ci.json` (lines 1063-1073)
**Current format:**
```json
{
  "name": "Post-Implementation CI Check",
  "description": "Runs CI checks after Kiro completes implementation work",
  "trigger": {
    "type": "onAgentComplete"
  },
  "action": {
    "type": "sendMessage",
    "message": "Implementation complete. Run the post-activity checklist: 1) pytest test/ 2) black/isort/flake8/mypy checks 3) Update docs if needed. Report any failures."
  }
}
```

### 2. `lint-on-save.json` (lines 1075-1085)
**Current format:**
```json
{
  "name": "Lint Python on Save",
  "description": "Runs black and isort on saved Python files",
  "trigger": {
    "type": "onFileChange",
    "pattern": "**/*.py"
  },
  "action": {
    "type": "shell",
    "command": "black --check --quiet ${file} && isort --check-only --quiet ${file}"
  }
}
```

### 3. `run-ci-workflow.json` (lines 1087-1097)
**Current format:**
```json
{
  "name": "Run Full CI Workflow",
  "description": "Manually trigger full CI checks",
  "trigger": {
    "type": "manual"
  },
  "action": {
    "type": "sendMessage",
    "message": "Execute the full CI workflow: 1) Read .gitlab-ci.yml (or .github/workflows/) 2) Run all quality checks 3) Fix any issues 4) Run pytest 5) Fix failing tests. Repeat until all checks pass."
  }
}
```

### 4. `test-coverage.json` (lines 1099-1109)
**Current format:**
```json
{
  "name": "Check Test Coverage",
  "description": "Manually trigger test coverage analysis",
  "trigger": {
    "type": "manual"
  },
  "action": {
    "type": "sendMessage",
    "message": "Analyze test coverage: 1) Run pytest with coverage 2) If below target (check pyproject.toml or CI config for threshold), identify uncovered code 3) Generate tests for uncovered critical paths 4) Repeat until coverage target met."
  }
}
```

### 5. `sync-documentation.json` (lines 1111-1121)
**Current format:**
```json
{
  "name": "Sync Documentation",
  "description": "Manually trigger documentation sync",
  "trigger": {
    "type": "manual"
  },
  "action": {
    "type": "sendMessage",
    "message": "Sync documentation: 1) Read all docs/ files 2) Compare with src/ and cdk/ implementation 3) Identify conflicts and deviations 4) Update docs to match implementation 5) Update docs/forLLMConsumption.md with consolidated info."
  }
}
```

## Workflow-to-Hook Mapping Table (lines 1055-1060)
**Current format:**
```
| Cline Workflow | Kiro Hook |
|----------------|-----------|
| ci-workflow.md | run-ci-workflow.json |
| test-coverage.md | test-coverage.json |
| documentation.md | sync-documentation.json |
```

## Issues Identified

### Issue 1: Incorrect File Extensions (Requirements 1.1, 1.2)
**Problem:** All hook files use `.json` extension instead of `.kiro.hook`

**Affected files:**
- `post-implementation-ci.json` → should be `post-implementation-ci.kiro.hook`
- `lint-on-save.json` → should be `lint-on-save.kiro.hook`
- `run-ci-workflow.json` → should be `run-ci-workflow.kiro.hook`
- `test-coverage.json` → should be `test-coverage.kiro.hook`
- `sync-documentation.json` → should be `sync-documentation.kiro.hook`

**Also in mapping table:**
- `run-ci-workflow.json` → should be `run-ci-workflow.kiro.hook`
- `test-coverage.json` → should be `test-coverage.kiro.hook`
- `sync-documentation.json` → should be `sync-documentation.kiro.hook`

### Issue 2: Missing Required Fields (Requirements 2.1-2.5)
**Problem:** All hook examples are missing required fields

**Missing fields in ALL hooks:**
- `enabled` (boolean) - Required field
- `version` (string) - Required field

**Incorrect field names:**
- `trigger` should be `when`
- `action` should be `then`

**Incorrect nested structure:**
- `trigger.type` values don't match spec:
  - `onAgentComplete` should be `agentComplete`
  - `onFileChange` should be `fileEdited`
  - `manual` is correct
- `action.type` values don't match spec:
  - `sendMessage` should be `askAgent`
  - `shell` is correct
- `action.message` should be `then.prompt` (for askAgent type)
- `trigger.pattern` should be `when.patterns` (array, not single string)

### Issue 3: Abbreviated Workflow Content (Requirements 3.1-3.7)
**Problem:** Hook prompts contain abbreviated instructions instead of complete workflow content

**Example from `post-implementation-ci.json`:**
- Current: "Implementation complete. Run the post-activity checklist: 1) pytest test/ 2) black/isort/flake8/mypy checks 3) Update docs if needed. Report any failures."
- Should contain: COMPLETE content from `.kiro/steering/post-activity.md` including all steps, sub-steps, code examples, and specific commands

**All hooks with abbreviated content:**
1. `post-implementation-ci.json` - should contain full post-activity.md content
2. `run-ci-workflow.json` - abbreviated CI workflow steps
3. `test-coverage.json` - abbreviated coverage analysis steps
4. `sync-documentation.json` - abbreviated documentation sync steps

### Issue 4: Missing Migration Guidance (Requirements 6.1-6.8)
**Problem:** Section 9 lacks comprehensive guidance for automatic workflow conversion

**Missing components:**
1. No step-by-step workflow detection process
2. No instructions for reading complete workflow content
3. No trigger type determination heuristics
4. No file naming convention guidance
5. No explicit one-to-one mapping requirement (each workflow → one hook)
6. No prohibition against combining multiple workflows into one hook
7. No content preservation guidelines
8. No reporting requirements for conversion results

### Issue 5: Missing Hook Format Reference (Requirements 2.1-2.5, 4.1-4.3, 5.1-5.2)
**Problem:** No comprehensive documentation of hook JSON structure

**Missing documentation:**
1. Complete field descriptions
2. Field type requirements
3. Available trigger types and their configurations
4. Available action types and their configurations
5. Complete real-world example with all fields

### Issue 6: Section Structure Issues
**Problem:** Section 9 doesn't follow the pattern from other sections

**Missing sections:**
1. No "Workflow Conversion Process" section with step-by-step automation
2. No "Hook File Format Reference" section
3. No "Content Preservation Guidelines" section
4. Migration behavior section exists but is minimal

## Summary of Changes Needed

### File Extensions (5 hooks + 3 in table = 8 changes)
- Change all `.json` extensions to `.kiro.hook`

### Hook Structure (5 hooks × 6 field changes each = 30 changes)
For each hook, add/fix:
1. Add `enabled: true` field
2. Add `version: "1"` field
3. Rename `trigger` → `when`
4. Rename `action` → `then`
5. Fix `when.type` values (onAgentComplete → agentComplete, onFileChange → fileEdited)
6. Fix `then.type` values (sendMessage → askAgent)
7. Rename `message` → `prompt` (for askAgent type)
8. Fix `pattern` → `patterns` (make it an array)

### Content Expansion (4 hooks need full content)
1. `post-implementation-ci.kiro.hook` - needs complete post-activity.md content
2. `run-ci-workflow.kiro.hook` - needs complete CI workflow instructions
3. `test-coverage.kiro.hook` - needs complete coverage analysis instructions
4. `sync-documentation.kiro.hook` - needs complete documentation sync instructions

### New Sections to Add
1. **Workflow Conversion Process** section with:
   - Step-by-step detection and reading
   - Trigger type determination heuristics
   - File naming conventions
   - One-to-one mapping requirement
   - Content preservation requirements
   - Reporting requirements

2. **Hook File Format Reference** section with:
   - Complete JSON structure documentation
   - Field descriptions and types
   - Trigger type options
   - Action type options
   - Complete real-world example from design.md

3. **Content Preservation Guidelines** section with:
   - No abbreviation rule
   - What to preserve (steps, code blocks, conditionals, etc.)
   - Examples of complete vs abbreviated content

### Migration Behavior Enhancement
- Expand existing migration behavior section to include workflow conversion details
- Add explicit instructions for one-to-one workflow-to-hook mapping
- Add prohibition against combining workflows

## Requirements Coverage

This analysis addresses:
- **Requirement 1.1, 1.2**: File extension issues identified
- **Requirement 2.1-2.5**: Missing fields and incorrect structure identified
- **Requirement 3.1-3.7**: Abbreviated content identified
- **Requirement 4.1-4.3**: Incorrect trigger configurations identified
- **Requirement 5.1-5.2**: Incorrect action configurations identified
- **Requirement 6.1-6.8**: Missing migration guidance identified
