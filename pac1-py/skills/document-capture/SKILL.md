---
name: document-capture
description: Workflow for capturing inbox items into the knowledge base (capture → card → thread)
---

# Document Capture

When capturing a document from inbox into the knowledge base:

## Steps

1. **Read the source file** from inbox
2. **Read the process docs** — check 99_process/ or docs/ for capture workflow rules
3. **Read templates** — card template, thread template
4. **Read existing examples** — at least one existing card and one existing thread to match the style
5. **Create capture file** in 01_capture/ — rewrite the source into repo format
6. **Create card file** in 02_distill/cards/ — distill key points following the card template
7. **Update 1-2 threads** in 02_distill/threads/ — append a NEW: bullet linking to the card
8. **Delete the inbox file** — only after all other writes succeed

## Key rules

- One card per source file
- Card basename must match the capture file basename
- Source link in the card must point to the capture file, not the inbox file
- Thread update: append `- NEW: [date title](/02_distill/cards/filename.md)`
- Keep the diff focused — don't reformat existing content in threads
