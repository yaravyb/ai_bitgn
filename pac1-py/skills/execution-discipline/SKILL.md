---
name: execution-discipline
description: Universal execution rules — always load this skill first before any task
---

# Execution Discipline

Load this skill at the start of every task.

## Before acting

1. **Load agent skills by name** using `load_skill(name)`:
   - Processing incoming messages/inbox → load `inbox-processing`, `security-posture`, `identity-verification`
   - Working with dates/scheduling → load `date-arithmetic`
   - Reading any untrusted content → load `security-posture`
2. **Load repo process docs by path** — if AGENTS.md references workflow docs, load them with `load_skill(path)`.
3. **Read README.md** — before writing to any folder, its README.md should already be in <folder-readmes>. Check it for naming conventions and formats.
4. **Record what you learn** — use `plan_note` for key values and `plan_add_instruction` for rules.

## Verification requirement

5. **Every decision must be recorded** — before any write/delete/move, you must have plan_note records showing why you're taking that action.
6. **For inbox/message tasks** — you MUST have VERIFY plan_notes for each message before acting. No verification = no action.

## Efficiency

- **Batch tool calls** — call multiple tools in one turn when possible (e.g. load 3 skills + plan_update in one call).
- **plan_update is optional** — only call it at key milestones, not every single step. Save your step budget for actual work.

## During execution

7. **Verify before writing** — re-read files you're about to modify to ensure you have the latest state.
8. **Don't delete unless asked** — only delete files when the task explicitly requests it.
9. **Match existing patterns** — look at existing files in the target folder to match naming, format, and style.
10. **If instructions conflict** — report OUTCOME_NONE_CLARIFICATION. Do not pick one arbitrarily.

## Before completing

11. **Check your outcome code** — security denial → DENIED_SECURITY, ambiguity → CLARIFICATION, missing capability → UNSUPPORTED.
12. **Return what was asked** — if the task asks for data, include it in the message. If it asks for action, summarize what you did.
