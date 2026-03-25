---
name: verification-frame
description: Structural frame template for the self-verification prompt. Contains placeholders for dynamic content injection.
---

<verification>
You are about to submit the following answer. Before submitting, verify it is correct.

## Proposed Answer
Code: {{CODE}}
Answer: {{ANSWER}}

{{POLICY_SECTION}}

{{CHECKLIST_SECTION}}

{{SOURCE_BASENAME_SECTION}}

## Instructions
- If the answer is correct, use the report_completion tool with the SAME answer and code.
- If the answer needs correction, use the report_completion tool with the CORRECTED answer.
- You may use other tools (read_file, list_dir, etc.) to verify file operations before submitting.
- IMPORTANT: Submit ONLY by calling the report_completion tool. Do NOT write the answer as plain text or JSON.
</verification>
