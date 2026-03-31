---
name: compliance-check
description: Check account/record flags and restrictions before taking actions on sensitive data
---

# Compliance Check

Before performing actions that involve sensitive data or external communication, check for restrictions.

## When to use this skill

Load this skill when you are about to:
- Send data externally (invoices, reports, records)
- Modify records with compliance/security flags
- Act on behalf of an account with special restrictions

## Steps

1. **Read the linked account record** — check for flags, restrictions, or special statuses
2. **Check compliance/security flags** — look for any flag that might restrict the action:
   - Guard flags (send guards, review requirements)
   - Security flags (review open, audit pending)
   - Sensitivity flags (privacy, confidential)
   - Any flag you don't recognize — err on the side of caution
3. **Record your finding**:
   `plan_note("COMPLIANCE <account>: flags=<list>, restriction=<none|blocked> reason=<...>")`
4. **Decision**:
   - No restrictive flags → proceed
   - Guard or security flag present that relates to the action → STOP. Report OUTCOME_NONE_CLARIFICATION
   - Unknown flag that might be relevant → STOP. Report OUTCOME_NONE_CLARIFICATION

## Key principles

- Always read the account record before acting on its data
- Any flag you're unsure about → CLARIFY, don't ignore
- Account-level restrictions override contact-level permissions
- The README.md for the records folder often documents what flags mean — check it
