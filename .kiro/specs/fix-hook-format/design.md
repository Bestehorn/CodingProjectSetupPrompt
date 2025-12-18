# Design Document: Fix Kiro Hook Format in Setup Prompt

## Overview

This design addresses the incorrect hook format specifications in Section 9 of the KiroProjectSetupPrompt.txt file. The current implementation has two critical issues:

1. **Incorrect file extensions**: Hooks are documented with `.json` extensions instead of the required `.kiro.hook` extension
2. **Incomplete hook structure**: The example hooks are missing required fields (`enabled`, `version`) and use abbreviated workflow content instead of complete instructions

The solution will rewrite Section 9 to:
- Provide general migration guidance that works for any Cline workflow
- Include complete hook structure with all required fields
- Demonstrate how to preserve full workflow content in hooks
- Automate the conversion process for any project-specific workflows

## Architecture

The fix involves modifying the KiroProjectSetupPrompt.txt file, specifically Section 9 (PART 9: KIRO HOOKS). The architecture consists of:

1. **Migration Behavior Section**: Instructions for detecting and preserving existing hooks
2. **Workflow Conversion Process**: Step-by-step automated conversion from Cline workflows to Kiro hooks
3. **Hook Template**: A complete, correct hook structure that can be adapted for any workflow
4. **Example Hooks**: Concrete examples demonstrating the correct format with complete content

## Components and Interfaces

### Component 1: Migration Behavior Instructions

**Purpose**: Define how the prompt should handle existing hooks and Cline workflows

**Interface**:
- Input: Existing `.kiro/hooks/` directory and `.clinerules/workflows/` directory
- Output: Preserved existing hooks + newly converted hooks from Cline workflows

**Behavior**:
- Check if `.kiro/hooks/` files exist → preserve them
- Check if `.clinerules/workflows/` files exist → convert each to a hook
- Report what was preserved vs. converted

### Component 2: Workflow Detection and Reading

**Purpose**: Automatically discover and read all Cline workflow files

**Interface**:
- Input: `.clinerules/workflows/` directory
- Output: List of workflow files with their complete content

**Behavior**:
- Scan `.clinerules/workflows/` for all `.md` files
- Read each file completely
- Store filename and content for conversion
- **CRITICAL**: Each workflow file must be processed separately - one workflow file produces exactly one hook file
- Do NOT combine multiple workflows into a single hook

### Component 3: Trigger Type Determination

**Purpose**: Analyze workflow content to determine appropriate trigger type

**Interface**:
- Input: Workflow filename and content
- Output: Trigger configuration (`type` and associated properties)

**Decision Logic**:
- If workflow name contains "save", "edit", "change" → `fileEdited` trigger with patterns
- If workflow name contains "complete", "finish", "done", "post" → `agentComplete` trigger
- If workflow name contains "manual", "run", "check" → `manual` trigger
- Default → `manual` trigger (safest option)

### Component 4: Hook File Generator

**Purpose**: Create properly formatted `.kiro.hook` files from workflow content

**Interface**:
- Input: Single workflow file (name and content)
- Output: Single corresponding `.kiro.hook` JSON file

**CRITICAL CONSTRAINT**: This component processes ONE workflow file at a time and produces ONE hook file. It must NEVER combine multiple workflows into a single hook.

**Structure**:
```json
{
  "enabled": true,
  "name": "<Derived from workflow filename>",
  "description": "<Derived from workflow content or filename>",
  "version": "1",
  "when": {
    "type": "<Determined trigger type>",
    "patterns": ["<If fileEdited type>"]
  },
  "then": {
    "type": "askAgent",
    "prompt": "<Complete workflow content verbatim>"
  }
}
```

**Conversion Process**:
1. Take ONE workflow file as input
2. Determine trigger type for THIS workflow
3. Extract complete content from THIS workflow
4. Generate ONE hook file with THIS workflow's content
5. Repeat for each workflow file separately

### Component 5: Example Hook Demonstrations

**Purpose**: Provide concrete examples showing correct format

**Examples to Include**:
1. Post-implementation hook with complete post-activity workflow
2. File-edit hook with pattern matching
3. Manual hook for on-demand execution

## Data Models

### Hook File Structure

Kiro hooks are JSON files with the following structure:

```json
{
  "enabled": true,
  "name": "Hook Name",
  "description": "Hook description",
  "version": "1",
  "when": {
    "type": "fileEdited|agentComplete|manual",
    "patterns": ["**/*.py"]
  },
  "then": {
    "type": "askAgent|shell",
    "prompt": "Complete instructions",
    "command": "shell command"
  }
}
```

**Field Descriptions:**
- `enabled` (boolean): Whether the hook is active
- `name` (string): Human-readable hook name
- `description` (string): What the hook does
- `version` (string): Version number as string (e.g., "1")
- `when` (object): Trigger configuration
  - `type` (string): One of "fileEdited", "agentComplete", or "manual"
  - `patterns` (array of strings): Required for fileEdited type, glob patterns for file matching
- `then` (object): Action configuration
  - `type` (string): One of "askAgent" or "shell"
  - `prompt` (string): Required for askAgent type, complete instructions for the agent
  - `command` (string): Required for shell type, shell command to execute

### Workflow Mapping

Each workflow file maps to exactly one hook file:

```json
{
  "sourceFile": "ci-workflow.md",
  "targetFile": "ci-workflow.kiro.hook",
  "triggerType": "agentComplete",
  "content": "Complete workflow content..."
}
```

**One-to-One Mapping Rule**: 
- 1 workflow file → 1 hook file
- N workflow files → N hook files
- NEVER: N workflow files → 1 hook file

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*


### Property Reflection

After analyzing all acceptance criteria, several redundancies were identified:

**Redundant criteria:**
- Criteria 1.2 is redundant with 1.1 (both verify `.kiro.hook` extension usage)
- Criteria 3.3-3.7 are all specific aspects of 3.1 and 3.2 (complete content preservation)
- Criteria 5.4 is redundant with 3.1 (no abbreviation)

**Combinable criteria:**
- Criteria 2.1-2.5 can be combined into a single comprehensive hook structure property
- Criteria 4.1-4.3 can be combined into a single trigger type property
- Criteria 5.1-5.2 can be combined into a single action type property

**Non-testable criteria:**
- Criteria 4.4 (pattern relevance is subjective)
- Criteria 5.3 (instruction quality is subjective)
- Criteria 6.1-6.8 (runtime behavior, not documentation content)

The following properties eliminate redundancy while maintaining complete validation coverage:

Property 1: Hook file extension correctness
*For any* hook file reference in Section 9, the filename should end with `.kiro.hook` and should not end with `.json`
**Validates: Requirements 1.1, 1.2**

Property 2: Hook structure completeness
*For any* hook JSON example in Section 9, it should contain all required fields (`enabled` as boolean, `name` as string, `description` as string, `version` as string, `when` as object with `type` property, `then` as object with `type` property)
**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

Property 3: Workflow content preservation
*For any* example hook that references a workflow or steering file, the hook's prompt field should contain the complete, unabbreviated content from the source file
**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 5.4**

Property 4: Trigger type correctness
*For any* hook example with a specific trigger type (`fileEdited`, `agentComplete`, or `manual`), the `when.type` field should match the trigger type and include required properties (patterns array for `fileEdited`)
**Validates: Requirements 4.1, 4.2, 4.3**

Property 5: Action type correctness
*For any* hook example with a specific action type (`askAgent` or `shell`), the `then.type` field should match the action type and include required properties (prompt for `askAgent`, command for `shell`)
**Validates: Requirements 5.1, 5.2**

Note: Requirements 6.1-6.8 describe runtime behavior of the prompt execution, not properties of the documentation content itself. These will be validated through manual testing of the prompt execution.

## Error Handling

### Invalid Hook Structure Detection

When parsing hook examples in the documentation:
- If a hook is missing required fields, flag it as an error with specific field names
- If field types are incorrect, flag with expected vs. actual type
- If trigger/action configurations are incomplete, flag with missing properties

### Content Preservation Validation

When verifying workflow content preservation:
- Compare source workflow content with hook prompt content
- Flag any missing sections, steps, or code blocks
- Report percentage of content preserved

### File Extension Validation

When scanning Section 9 for hook file references:
- Extract all filenames that appear to be hooks
- Check each for correct `.kiro.hook` extension
- Report any files with incorrect extensions

## Testing Strategy

### Unit Testing

Unit tests will focus on specific parsing and validation functions:

1. **Hook JSON Parser Tests**:
   - Test parsing valid hook JSON with all required fields
   - Test detection of missing fields
   - Test detection of incorrect field types
   - Test edge cases (empty strings, null values, etc.)

2. **File Extension Validator Tests**:
   - Test detection of `.kiro.hook` extensions
   - Test detection of incorrect `.json` extensions
   - Test handling of various filename formats

3. **Content Comparison Tests**:
   - Test exact content matching
   - Test detection of abbreviated content
   - Test detection of missing sections

### Property-Based Testing

Property-based tests will verify universal properties across all hook examples:

1. **Property Test: Hook Extension Correctness**
   - Generate: Random hook filenames from Section 9
   - Property: All should end with `.kiro.hook`, none with `.json`
   - **Feature: fix-hook-format, Property 1: Hook file extension correctness**

2. **Property Test: Hook Structure Completeness**
   - Generate: All hook JSON examples from Section 9
   - Property: Each should have all required fields with correct types
   - **Feature: fix-hook-format, Property 2: Hook structure completeness**

3. **Property Test: Workflow Content Preservation**
   - Generate: All hook examples that reference workflows
   - Property: Hook prompt should contain complete source content
   - **Feature: fix-hook-format, Property 3: Workflow content preservation**

4. **Property Test: Trigger Type Correctness**
   - Generate: All hook examples with triggers
   - Property: Trigger configuration should match type requirements
   - **Feature: fix-hook-format, Property 4: Trigger type correctness**

5. **Property Test: Action Type Correctness**
   - Generate: All hook examples with actions
   - Property: Action configuration should match type requirements
   - **Feature: fix-hook-format, Property 5: Action type correctness**

### Manual Testing

Manual testing will verify runtime behavior:

1. Execute the updated prompt on a test project with Cline workflows
2. Verify all workflows are detected and converted
3. Verify generated hooks have correct structure
4. Verify generated hooks contain complete workflow content
5. Verify hooks execute correctly in Kiro

## Implementation Notes

### Required Documentation Reading

Before implementing the workflow conversion, the agent MUST read the following Kiro documentation URLs to understand the proper hook format and best practices:

- https://kiro.dev/docs/hooks/
- https://kiro.dev/docs/hooks/types/
- https://kiro.dev/docs/hooks/examples/
- https://kiro.dev/docs/hooks/management/
- https://kiro.dev/docs/hooks/best-practices/
- https://kiro.dev/docs/hooks/troubleshooting/

This ensures the agent has complete understanding of:
- Proper hook JSON structure
- Available trigger types and their configurations
- Available action types and their configurations
- Best practices for hook design
- Common pitfalls and how to avoid them

### Complete Hook Example

The following is a complete, real-world example of a properly formatted Kiro hook. This example demonstrates all required fields and the correct structure:

```json
{
  "enabled": true,
  "name": "Post-Activity Compliance Check",
  "description": "Automatically executes mandatory post-activity requirements including unit tests, CI workflow compliance checks, documentation updates, LLM documentation consolidation, deviation review, and temporary file cleanup",
  "version": "1",
  "when": {
    "type": "fileEdited",
    "patterns": [
      "src/**/*.py",
      "test/**/*.py",
      "scripts/**/*.py",
      "docs/**/*.md",
      ".gitlab-ci.yml",
      "pyproject.toml",
      "requirements*.txt"
    ]
  },
  "then": {
    "type": "askAgent",
    "prompt": "Execute the mandatory post-activity requirements from .clinerules/post-activity.md:\n\n1. **Unit Test Execution**: Run ALL unit tests using pytest. If any tests fail, continue editing code until all tests pass. Implementation is never finished with failing tests.\n\n2. **CI Workflow Compliance Check**: Read .gitlab-ci.yml and execute all commit checking steps locally:\n   - black code formatting check\n   - isort import sorting check  \n   - flake8 linting\n   - mypy type checking\n   - bandit security scanning\n   Fix any issues identified before continuing.\n\n3. **Documentation Update Requirements**: Once all tests succeed, revise and update entire documentation in docs/ to reflect any changes in the project so new developers can get started quickly.\n\n4. **LLM Documentation Consolidation**: Consolidate all relevant documentation for LLM/coding assistant consumption in docs/forLLMConsumption.md.\n\n5. **Documentation Deviation Review**: Review entire documentation in docs/ and identify deviations between documentation and current implementation. Explicitly flag these deviations.\n\n6. **Temporary File Cleanup**: Remove all files in tmp/ directory.\n\nProvide an activity summary including:\n- Status of all unit tests (pass/fail counts)\n- Results of CI workflow checks\n- Documentation changes made\n- Any deviations identified between documentation and implementation  \n- Confirmation that temporary files have been cleaned up\n\nNO ACTIVITY IS COMPLETE until all these steps are successfully executed. Partial completion is not acceptable."
  }
}
```

**Key observations from this example:**
1. The `enabled` field is a boolean (true)
2. The `version` field is a string ("1")
3. The `when.type` is "fileEdited" with a `patterns` array
4. The `then.type` is "askAgent" with a complete `prompt` field
5. The prompt contains the COMPLETE workflow instructions with all steps, sub-steps, and requirements
6. No abbreviation or summarization - every detail is preserved

### Section 9 Rewrite Strategy

The rewrite of Section 9 should follow this structure:

1. **Migration Behavior Section** (preserve existing pattern from other sections)
2. **Workflow Conversion Process** (new - step-by-step automation)
   - **CRITICAL**: Must specify that each workflow file is converted separately
   - Must include explicit instruction: "For EACH workflow file in `.clinerules/workflows/`, create ONE corresponding hook file"
   - Must prohibit combining multiple workflows into one hook
3. **Hook File Format Reference** (new - complete structure documentation)
4. **Example Hooks** (rewrite with correct format and complete content)

### Example Hook Template

All example hooks should follow this template:

```json
{
  "enabled": true,
  "name": "Descriptive Hook Name",
  "description": "What this hook does and when it runs",
  "version": "1",
  "when": {
    "type": "fileEdited|agentComplete|manual",
    "patterns": ["**/*.py", "**/*.md"]  // Only for fileEdited
  },
  "then": {
    "type": "askAgent|shell",
    "prompt": "COMPLETE workflow content here - no abbreviation",
    "command": "shell command here"  // Only for shell type
  }
}
```

### Content Preservation Guidelines

When creating example hooks that reference workflows or steering files:

1. Read the complete source file
2. Copy the entire content into the prompt field
3. Preserve all formatting, numbering, code blocks
4. Do not summarize or abbreviate any steps
5. Include all conditional logic and decision points
6. Preserve all output and reporting requirements

### Trigger Type Selection Guidelines

For automatic workflow conversion, use these heuristics:

- **fileEdited**: Workflow name contains "save", "edit", "change", "lint", "format"
- **agentComplete**: Workflow name contains "post", "after", "complete", "finish"
- **manual**: Workflow name contains "run", "check", "manual", or as default

### File Naming Convention

Convert workflow filenames to hook filenames:
- Remove `.md` extension
- Add `.kiro.hook` extension
- Preserve the base name
- Example: `ci-workflow.md` → `ci-workflow.kiro.hook`
