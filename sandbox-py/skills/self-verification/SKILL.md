---
name: self-verification
description: Verification checklist for pre-submission answer review — injected into verification prompt.
---

## Verification Checklist

1. Re-read the policy files above. Does the answer comply with ALL format rules (exact casing, whitespace, punctuation, response codes)?
2. If you performed file operations (write_file, delete_file), verify they succeeded by re-reading or listing the affected paths.
3. Check that all grounding references point to files that actually exist.
4. Verify the answer is complete and addresses the full task requirement.
5. **Scope audit** (MANDATORY — do this step by step):
   a) List every file you wrote, modified, or deleted.
   b) For each file, state which specific words in the task require that operation.
   c) If any operation cannot be traced to specific task words, it is unrequested.
   d) If the task constrains scope ("keep the diff focused", "don't touch anything else"), undo any unrequested writes before submitting.
6. **Filename audit** (MANDATORY):
   a) What was the original source filename?
   b) What filename did you use when creating derived files?
   c) If they differ (e.g. you added or removed segments), delete the wrong-named files and recreate them with the EXACT source basename.
7. **Process completeness audit** (MANDATORY):
   a) Which process/policy files govern this task type?
   b) List every procedure or action those files require (file naming, updates to counters/sequences, format rules, required fields).
   c) For each required procedure, confirm you performed it. If you read a value from a supporting file (counter, sequence, index) and used it, did you also write the updated value back?
   d) If any required procedure was missed, perform it before submitting.
