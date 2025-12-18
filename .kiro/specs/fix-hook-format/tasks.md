# Implementation Plan: Fix Kiro Hook Format in Setup Prompt

- [x] 1. Read Kiro hook documentation





  - Read all Kiro hook documentation URLs to understand proper format and best practices
  - URLs: hooks/, hooks/types/, hooks/examples/, hooks/management/, hooks/best-practices/, hooks/troubleshooting/
  - _Requirements: All requirements (foundational knowledge)_

- [x] 2. Analyze current Section 9 structure





  - Read KiroProjectSetupPrompt.txt Section 9 (PART 9: KIRO HOOKS)
  - Identify all hook examples and their current format
  - Document what needs to be changed (file extensions, missing fields, abbreviated content)
  - _Requirements: 1.1, 1.2, 2.1-2.5, 3.1-3.7_

- [x] 3. Create migration behavior section





  - Write the migration behavior instructions for Section 9
  - Follow the pattern from other sections (PART 1-8)
  - Include instructions for preserving existing hooks
  - Include instructions for detecting and converting Cline workflows
  - _Requirements: 6.1, 6.2_

- [x] 4. Create workflow conversion process section





  - Write step-by-step instructions for automatic workflow conversion
  - **CRITICAL**: Specify that EACH workflow file must be converted separately
  - Include explicit instruction: "For EACH workflow file in `.clinerules/workflows/`, create ONE corresponding hook file"
  - Prohibit combining multiple workflows into one hook
  - Include trigger type determination heuristics
  - Include file naming convention (workflow.md → workflow.kiro.hook)
  - _Requirements: 6.1-6.8_

- [x] 5. Create hook format reference section





  - Document the complete hook JSON structure
  - Include all required fields with descriptions
  - Include field type requirements (enabled: boolean, version: string, etc.)
  - Include trigger type options and their configurations
  - Include action type options and their configurations
  - Include the complete real-world example hook from the design
  - _Requirements: 2.1-2.5, 4.1-4.3, 5.1-5.2_

- [x] 6. Rewrite example hooks with correct format





  - Replace all `.json` extensions with `.kiro.hook` extensions
  - Add missing fields (enabled, version) to all hook examples
  - Ensure all hooks have proper structure
  - For post-implementation hook: include COMPLETE post-activity workflow content (not abbreviated)
  - For other hooks: ensure they demonstrate the pattern without being prescriptive
  - _Requirements: 1.1, 1.2, 2.1-2.5, 3.1-3.7, 4.1-4.3, 5.1-5.2_

- [x] 7. Update workflow-to-hook mapping table





  - Update the table that maps Cline workflows to Kiro hooks
  - Change all `.json` extensions to `.kiro.hook`
  - Ensure table clearly shows one-to-one mapping
  - _Requirements: 1.1, 1.2, 6.4, 6.5_



- [x] 8. Add content preservation guidelines



  - Write explicit guidelines for preserving complete workflow content
  - Emphasize no abbreviation, no summarization
  - Include examples of what to preserve (numbered steps, code blocks, conditional logic, etc.)
  - _Requirements: 3.1-3.7_

- [x] 9. Verify all changes





  - Read the updated Section 9 completely
  - Verify all hook filenames use `.kiro.hook` extension
  - Verify all hook examples have complete structure
  - Verify example hooks contain complete, unabbreviated content
  - Verify workflow conversion process specifies one-to-one mapping
  - _Requirements: All requirements_

- [x] 10. Final checkpoint





  - Ensure all requirements are addressed
  - Ask the user if questions arise
