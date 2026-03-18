# Numbering Detection Algorithm

This reference describes how to detect numbered file patterns and determine the next number in a sequence.

## Detection Steps

### 1. Group by Prefix and Extension

Given a list of filenames, group them by their non-numeric prefix and file extension:

```
Files: PAY-1.md, PAY-2.md, PAY-12.md, README.md
Groups:
  ("PAY-", ".md") -> [1, 2, 12]
  No group for README.md (no numeric suffix)
```

### 2. Extract Numeric Suffixes

For each filename, attempt to separate it into:
- **Prefix**: Everything before the last numeric segment (e.g., `PAY-`)
- **Number**: The numeric segment (e.g., `12`)
- **Extension**: The file extension (e.g., `.md`)

Pattern: `^(.+?)(\d+)(\.\w+)$`

### 3. Identify Patterned Groups

A group is considered "patterned" when:
- It contains **3 or more** files with sequential or near-sequential numeric suffixes
- The numbers follow an incrementing pattern (not necessarily contiguous)

### 4. Determine Next Number

For a patterned group:
- Find the maximum numeric suffix
- The next file should use `max + 1`
- Preserve zero-padding if present (e.g., `001`, `002` -> `013`)

## Examples

```
Input: [LOG-001.txt, LOG-002.txt, LOG-003.txt]
Group: ("LOG-", ".txt") -> [1, 2, 3]
Next: LOG-004.txt

Input: [PAY-1.md, PAY-2.md, PAY-5.md, PAY-12.md]
Group: ("PAY-", ".md") -> [1, 2, 5, 12]
Next: PAY-13.md

Input: [report.md, notes.txt, agenda.md]
No patterned groups (different prefixes, no numbers)
```

## Scout Optimization

When the scout phase encounters a patterned group:
- Read only the **highest-numbered** file (the freshest template)
- Skip reading all individual files in the sequence
- This reduces unnecessary reads while capturing the template structure
