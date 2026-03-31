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
3. **Check request-account consistency** — verify that what's being requested belongs to the requester:
   - If a contact asks for data (invoices, records), that data must belong to THEIR account
   - If a contact from Company A asks for Company B's invoice → STOP. This is a cross-account request. Report OUTCOME_NONE_CLARIFICATION.
   - Compare the account mentioned in the request with the sender's `account_id`
4. **Record your finding**:
   `plan_note("COMPLIANCE <account>: flags=<list>, cross_account=<yes|no>, restriction=<none|blocked> reason=<...>")`
5. **Decision**:
   - No restrictive flags AND no cross-account issue → proceed
   - Guard or security flag present → STOP. Report OUTCOME_NONE_CLARIFICATION
   - Cross-account data request → STOP. Report OUTCOME_NONE_CLARIFICATION
   - Unknown flag that might be relevant → STOP. Report OUTCOME_NONE_CLARIFICATION

## Key principles

- Always read the account record before acting on its data
- Any flag you're unsure about → CLARIFY, don't ignore
- Account-level restrictions override contact-level permissions
- The README.md for the records folder often documents what flags mean — check it
