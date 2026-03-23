---
name: pattern-match-create
description: Inspect existing files, detect naming and numbering patterns, create matching files.
---

# Pattern Match and Create Protocol

This skill defines the protocol for inspecting existing files in a directory, detecting naming conventions and numbering patterns, reading meta-files for templates, and creating new files that match the discovered patterns.

## Step-by-Step Process

### 1. Read Meta-Files First

Before inspecting data files, read all meta-files in the target directory (`_rules.*`, `RULES.*`, `_config.*`). These often contain explicit instructions about file naming conventions, templates, and numbering schemes.

### 2. Inspect Existing Files

List the directory contents and examine existing files. Look for:

- Consistent naming conventions (e.g., `ISSUE-1.md`, `ISSUE-2.md`)
- Common prefixes and suffixes
- File extensions used
- Directory organization patterns

### 3. Detect Numbering Patterns

When files follow a numeric pattern (e.g., `PAY-1.md` through `PAY-12.md`):

1. Group files by their prefix and extension
2. Extract the numeric suffix from each filename
3. Identify the highest existing number
4. Determine the correct next number for new files

See `references/numbering-detection.md` for the detailed detection algorithm.

### 4. Read Template Examples

Read 1-2 existing files (preferably the highest-numbered one) to understand:

- Internal structure and formatting
- Required sections or headers
- Content patterns and conventions
- Any boilerplate or standard text

### 5. Create Matching Files

When creating new files:

- Match the naming convention exactly (prefix, separator, extension)
- Use the correct next number in the sequence
- Follow the internal structure from template examples
- Apply any rules from meta-files
- Preserve formatting conventions (headers, spacing, etc.)

## Key Principles

- **Observe before acting**: Always read existing files to understand patterns before creating new ones.
- **Meta-files are authoritative**: If a meta-file specifies a template or naming rule, follow it exactly.
- **Consistency over creativity**: Match existing patterns precisely; do not introduce new conventions.
- **Highest-numbered is freshest**: The highest-numbered file is usually the best template for new entries.
