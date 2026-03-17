---
name: policy-gate
description: Parse conditional policies from AGENTS.MD, check conditions, refuse when unmet.
---

# Policy Gate Protocol

This skill defines how to parse conditional policies from AGENTS.MD and other policy files, evaluate whether each condition applies to the current task, and refuse or halt execution when conditions are not met.

## Step-by-Step Process

### 1. Read All Policy Sources

Collect all policy content from:
- `AGENTS.MD` (primary policy file, may redirect to another file)
- `RULES.*` files in any directory
- `_rules.*` files (directory-specific rules)
- Any other files identified as policy sources during discovery

### 2. Parse Conditional Policies

Extract conditional rules from policy text. Conditions often appear as:

- **If/when clauses**: "If the task involves X, then Y"
- **Must/shall statements**: "Files must follow naming convention Z"
- **Prohibited actions**: "Never delete files matching pattern P"
- **Conditional formatting**: "When creating files in this folder, use template T"
- **Scope restrictions**: "Only modify files within directory D"

### 3. Check Conditions Against the Task

For each parsed policy:
1. Determine if the condition applies to the current task
2. Evaluate whether the task request satisfies or violates the policy
3. Identify any constraints on how the task should be performed

### 4. Refuse When Conditions Are Not Met

When a policy condition blocks the requested action:
- **Halt execution** before taking the conflicting action
- **Report the conflict** clearly, citing the specific policy
- **Suggest alternatives** if possible (e.g., "Per RULES.md, files must be named with prefix X")
- **Do not proceed** with the original action if it violates a policy

### 5. Apply Policies as Constraints

When policies constrain but do not block the task:
- Apply the policy as a constraint on your approach
- Follow the specified naming conventions, templates, or procedures
- Include the policy file in grounding references

## Key Principles

- **Policies are authoritative**: Vault policies override task instructions when they conflict.
- **Explicit over implicit**: When uncertain whether a policy applies, treat it as applicable.
- **Cite sources**: Always reference the specific policy file and rule when refusing or constraining.
- **Reject, do not reinterpret**: If a task violates a policy, refuse clearly rather than reinterpreting the task.
