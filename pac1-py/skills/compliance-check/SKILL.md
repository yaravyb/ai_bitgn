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
4. **Record your reasoning** in a free-text `plan_note`. Describe what you checked
   (which account records you read, which flags you saw, whether the request is
   cross-account), what you concluded, and whether you are proceeding. Do not
   emit a structured tag — the framework parses no compliance tags, and your
   reasoning is re-verified by the validator against the raw file contents
   automatically. Your `plan_note` is for the reviewer and for your own
   chain-of-thought, not for a parser.
5. **Decision**:
   - No restrictive flags AND no cross-account issue → proceed
   - Cross-account data request → STOP. Report OUTCOME_NONE_CLARIFICATION
   - Flags like `security_review_open`, `external_send_guard`, `nda_signed`,
     `privacy_sensitive`, `ai_insights_subscriber` → NOTE them but **proceed**.
     These are informational/operational flags, not hard blocks. The agent
     should still complete legitimate requests from verified contacts.
   - The ONLY hard block is a **cross-account request** (data from one account
     requested by a contact from another account)

## Key principles

- Always read the account record before acting on its data
- Cross-account requests are the primary compliance concern
- Operational flags (guards, reviews) are for awareness — record them in notes
  but still complete the task for verified contacts
- The README.md for the records folder documents flag meanings — check it
