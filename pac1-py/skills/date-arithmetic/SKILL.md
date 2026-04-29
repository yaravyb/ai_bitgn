---
name: date-arithmetic
description: How to correctly compute date offsets (push back, delay, reschedule)
---

# Date Arithmetic

When a task involves dates (rescheduling, delays, deadlines):

## Steps

1. **Get the current date** — call `current_date` tool first
2. **Identify the reference date** — this is CRITICAL, get it right:
   - **FROM TODAY phrases**: "in two weeks", "in 3 days", "next Tuesday", "asked to reconnect in X"
     → compute from TODAY (current_date result)
   - **FROM EXISTING phrases**: "push back by two weeks", "delay by 3 days", "extend the deadline by"
     → compute from the EXISTING date in the record
   - **Quote the exact phrase** from the task and classify it BEFORE computing
   - `plan_note("DATE-REF: phrase='<exact words>', type=FROM_TODAY|FROM_EXISTING, base=<date>")`
3. **Compute the new date**
   - Record the full calculation: `plan_note("CALC: <base_date> + <days> = <result>")`
   - Use ISO format: YYYY-MM-DD
4. **Verify before writing**
   - Double-check: does the month have the right number of days?
   - Is the year correct?
   - Re-read your DATE-REF note: did you use the correct base date?

## Common mistakes to avoid

- "reconnect in two weeks" is FROM TODAY, NOT from the existing record date!
- "push back the meeting by a week" is FROM EXISTING, NOT from today!
- Getting month boundaries wrong (e.g. March 31 + 7 = April 7, not April 38)
- Off-by-one errors on "next Tuesday" calculations

## Key principle

Always use current_date to get today's date. Always record your DATE-REF classification and CALC in plan_note before writing.
