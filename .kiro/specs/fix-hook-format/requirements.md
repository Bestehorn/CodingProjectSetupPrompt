# Requirements Document: Fix Kiro Hook Format in Setup Prompt

## Introduction

The KiroProjectSetupPrompt.txt file contains incorrect hook format specifications in Section 9. The section needs to provide general guidance for converting ANY Cline workflow to Kiro hooks, not just specific examples. The hooks need to be updated to match the proper Kiro hook format, which requires:
1. Files must have the `.kiro.hook` extension
2. Files must follow a specific JSON structure with `enabled`, `name`, `description`, `version`, `when`, and `then` fields
3. The hook content should preserve the complete workflow instructions from the source (Cline workflows or steering files), not abbreviated versions
4. The guidance should be general enough to apply to any project's workflows

## Glossary

- **Kiro_Hook**: A JSON configuration file with `.kiro.hook` extension that defines automated agent behaviors
- **Hook_Trigger**: The `when` field that specifies when a hook should execute
- **Hook_Action**: The `then` field that specifies what action the hook should perform
- **Cline_Workflow**: A markdown file in `.clinerules/workflows/` that defines a sequence of steps for the agent to execute
- **Steering_File**: A markdown file in `.kiro/steering/` that contains rules and instructions for the agent
- **Workflow_Content**: The complete set of instructions and steps defined in a workflow or steering file

## Requirements

### Requirement 1: Hook File Extension

**User Story:** As a Kiro user, I want hooks to have the correct file extension, so that Kiro can properly recognize and execute them.

#### Acceptance Criteria

1. WHEN documenting hook files in Section 9.1 THEN the system SHALL specify the `.kiro.hook` extension for all hook filenames
2. THE documentation SHALL replace all `.json` extensions with `.kiro.hook` extensions in Section 9.1

### Requirement 2: Hook JSON Structure

**User Story:** As a Kiro user, I want hooks to follow the proper JSON structure, so that they are valid and executable.

#### Acceptance Criteria

1. WHEN defining a hook THEN the system SHALL include all required fields: `enabled`, `name`, `description`, `version`, `when`, and `then`
2. THE `enabled` field SHALL be a boolean value
3. THE `version` field SHALL be a string value
4. THE `when` field SHALL contain a `type` property and appropriate pattern properties
5. THE `then` field SHALL contain a `type` property and appropriate action properties

### Requirement 3: Complete Workflow Content Preservation

**User Story:** As a developer, I want hooks to preserve complete workflow instructions from source files, so that no steps or details are lost during conversion.

#### Acceptance Criteria

1. WHEN converting a Cline workflow to a Kiro hook THEN the system SHALL include ALL instructions from the source workflow file
2. WHEN referencing a steering file in a hook THEN the system SHALL include ALL steps and requirements from that steering file
3. THE hook prompt SHALL NOT abbreviate, shorten, or summarize workflow instructions
4. THE hook prompt SHALL preserve all numbered steps, sub-steps, and details from the source
5. THE hook prompt SHALL preserve all code examples, command examples, and specific tool invocations from the source
6. THE hook prompt SHALL preserve all conditional logic and decision points from the source
7. THE hook prompt SHALL preserve all output requirements and reporting instructions from the source

### Requirement 4: Hook Trigger Configuration

**User Story:** As a Kiro user, I want hooks to have properly configured triggers, so that they execute at the appropriate times.

#### Acceptance Criteria

1. WHEN defining a file-based trigger THEN the system SHALL use `type: "fileEdited"` with a `patterns` array
2. WHEN defining an agent completion trigger THEN the system SHALL use `type: "agentComplete"`
3. WHEN defining a manual trigger THEN the system SHALL use `type: "manual"`
4. THE patterns array SHALL include all relevant file patterns for the hook's purpose

### Requirement 5: Hook Action Configuration

**User Story:** As a Kiro user, I want hooks to have properly configured actions, so that they perform the intended operations.

#### Acceptance Criteria

1. WHEN defining an agent message action THEN the system SHALL use `type: "askAgent"` with a `prompt` field
2. WHEN defining a shell command action THEN the system SHALL use `type: "shell"` with a `command` field
3. THE prompt field SHALL contain complete, actionable instructions
4. THE prompt field SHALL NOT use shortened or abbreviated instructions

### Requirement 6: Automatic Workflow Migration

**User Story:** As a user executing the setup prompt, I want the prompt to automatically convert all Cline workflows to Kiro hooks, so that I don't have to manually migrate them.

#### Acceptance Criteria

1. WHEN the setup prompt is executed THEN the system SHALL automatically detect all workflow files in `.clinerules/workflows/`
2. WHEN a workflow file is detected THEN the system SHALL read its complete content
3. WHEN converting a workflow THEN the system SHALL create a corresponding `.kiro.hook` file with the complete workflow content in the prompt field
4. WHEN multiple workflow files exist THEN the system SHALL create one separate hook file for each workflow file
5. THE system SHALL NOT combine multiple workflows into a single hook
6. THE system SHALL determine the appropriate trigger type based on the workflow's purpose and content
7. THE system SHALL preserve all workflow instructions without abbreviation or summarization
8. THE system SHALL report which workflows were converted and to which hook files
