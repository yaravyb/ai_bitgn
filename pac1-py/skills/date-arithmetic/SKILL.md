---
name: date-arithmetic
description: How to correctly compute date offsets (push back, delay, reschedule)
---

# Date Arithmetic

When a task involves dates (rescheduling, delays, deadlines):

## Steps

1. **Get the current date** — call `current_date` tool first
2. **Identify the reference date**
   - "in two weeks" → relative to TODAY
   - "push back by two weeks" → relative to the EXISTING date in the record
   - "next Tuesday" → relative to TODAY
3. **Compute the new date**
   - Record the calculation with plan_note: "existing: 2026-03-15, +14 days = 2026-03-29"
   - Use ISO format: YYYY-MM-DD
4. **Verify before writing**
   - Double-check: does the month have the right number of days?
   - Is the year correct?

## Common mistakes to avoid

- Adding days to TODAY when you should add to the existing date
- Adding to the existing date when you should add to TODAY
- Getting month boundaries wrong (e.g. March 31 + 7 = April 7, not April 38)
- Off-by-one errors on "next Tuesday" calculations

## Key principle

Always use current_date to get today's date. Always record your calculation in plan_note before writing.
