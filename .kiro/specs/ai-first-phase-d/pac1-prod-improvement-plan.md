# PAC1-Prod Improvement Plan

## Current State

- **Score**: 80/104 = 76.9% on `bitgn/pac1-prod` (full run 2026-04-15)
- **Previous**: 71/104 = 68.3% (2026-04-14)
- **Model**: `openai/qwen3.5:27b-q4_K_M`
- **Date**: 2026-04-15
- **Branch**: `feature/simplify-approach`
- **Benchmark**: `bitgn/pac1-prod` (104 tasks, randomized variants per run)

### Round 2 Fixes Applied (commit pending)

Deterministic post-processing pipeline added:
- ASCII table re-formatter (normalizes column widths)
- Queue order fixer (alphanumeric sort for queue_order_id)
- Reply recipient fixer (outbox emails go to inbox sender)
- ASCII table parser for load_records (non-frontmatter files)
- text_match() fuzzy keyword helper + parse_date() via dateutil
- Executor rules 13-15 (display names, line items, entity search)
- Inbox-processing skill updated for data reply handling
- Security guard enhanced for knowledge-sharing detection
- Validator exceptions for OCR and computation tasks

**Estimated score after round 2**: ~88-92/104 = 85-88%

## Remaining Failures: 33 tasks, 8 categories

### P0: OVER-CLARIFY — 6 failures (18%)

Agent finds the answer but reports OUTCOME_NONE_CLARIFICATION instead of OK.

| Task | Question | Root cause |
|------|----------|-----------|
| t001 | "start date of the do-not-degrade lane project" | Agent can't resolve indirect project reference → gives up |
| t005 | "how much did Filamenthütte Wien charge for PLA spool 162 days ago" | Date math or lookup fails → agent clarifies instead of answering |
| t031 | "delete every receipt containing 0.6mm hardened nozzle" | Agent unsure about deletion → clarifies instead of acting |
| t051 | "start date of the morning launch kit project" | Agent can't resolve indirect project reference |
| t077 | "last recorded message from Novak Miles" | Agent can't find the message in entity files |
| t080 | "how much did Müller Bürobedarf charge for label tape refill 52 days ago" | Date math or lookup fails |

**Root cause**: The agent is too cautious (rule 9 "NOT FOUND = CLARIFICATION" combined with rule 11 "INCOMPLETE = CLARIFICATION"). When it encounters ANY ambiguity, it defaults to CLARIFICATION even when the answer IS findable with more effort.

**Fix direction**: 
- Executor rule 10 (FOUND = OK) needs to be stronger — commit to OK when canonical records provide the answer
- For indirect project references ("do-not-degrade lane", "morning launch kit"), the agent should search project READMEs for matching descriptions/goals, not just exact name matches
- For date+amount lookups (t005, t080): `load_records` + `calculate` with `date_offset` should give deterministic results — verify the agent uses the tabular path
- For t031 (deletion): rule 9 should NOT fire on FIX/DELETE tasks (already scoped, may need reinforcement)

### P1: WRONG ANSWER — 5 failures (15%)

Agent produces an incorrect value.

| Task | Question | Expected | Issue |
|------|----------|----------|-------|
| t003 | "projects involving the lab server" | "Black Library Evenings..." | Agent misidentifies which entity is "the lab server" |
| t028 | "projects involving Badger" | "Black Library Evenings..." | Agent finds some but misses projects (incomplete linked_entities search) |
| t058 | "revenue from 'workflow mapping and intake audit'" | "1200" | Arithmetic error or wrong invoice matching |
| t078 | "projects involving Renate Hofer" | "Hearthline..." | Agent finds some but misses projects |
| t100 | "total paid to vendor from bill" | "241" | Wrong total — agent miscalculates or misses invoices |

**Root cause**: Mix of entity resolution ("lab server" → which entity?), incomplete search (not finding all matching projects), and arithmetic errors.

**Fix direction**:
- Entity resolution: the `load_records("10_entities/cast")` approach should help — the agent can search the full entity table for aliases, descriptions, relationships
- Project search: `load_records("40_projects")` + `calculate("df[df['linked_entities'].str.contains('entity.badger')]")` should catch all matches deterministically
- Arithmetic: `calculate()` with pandas should eliminate math errors — verify the agent uses it consistently
- Many of these would benefit from the agent doing `load_records` FIRST and querying instead of reading files one by one

### P2: BAD FRONTMATTER — 3 failures (9%)

Agent creates outbox email files with broken YAML frontmatter.

| Task | Error |
|------|-------|
| t046 | "yaml: line 6: mapping values are not allowed in this context" |
| t071 | same pattern |
| t096 | same pattern |

**Root cause**: Unquoted colons in YAML values. The email subject or body contains a colon (e.g., "Re: Invoice request") which breaks YAML parsing when not quoted.

**Fix direction**:
- **Code fix in dispatch.py**: add a YAML normalizer in the write handler (like the frontmatter gap normalizer). After writing a file with `---` frontmatter, validate the YAML. If invalid, auto-quote string values containing colons.
- OR: add to executor prompt/outbox workflow: "Always quote YAML values that contain colons with double quotes"
- The code fix is more reliable since it's deterministic

### P3: UNDER-CLARIFY — 3 failures (9%)

Agent approves (OUTCOME_OK) when it should clarify.

| Task | Question | Issue |
|------|----------|-------|
| t000 | "When was the workshop printer born?" | Agent fabricates a birthday for an entity that doesn't have one |
| t002 | "Last recorded message from Foundry" | Agent fabricates content that doesn't exist |
| t075 | "house server's DoB" | Agent fabricates a birthday for a system entity |

**Root cause**: Agent answers questions about non-existent data by fabricating plausible values. The validator's source-files check should catch fabrication but sometimes doesn't.

**Fix direction**:
- The `load_records` approach helps: `df[df['_file'].str.contains('foundry')]['birthday']` returns NaN if no birthday field → agent should recognize NaN/missing as "not found" → CLARIFICATION
- Add executor guidance: "If a field is missing from the canonical record (NaN, null, not present), report CLARIFICATION — do not guess or infer"
- Validator bullet 3 (source-files check) should catch fabrication when the value isn't in the source file

### P4: MISSING REFERENCES — 2 failures (6%)

Agent gives correct answer but doesn't include the source file in grounding_refs.

| Task | Question | Missing ref |
|------|----------|------------|
| t026 | "start date for Black Library Evenings" | 40_projects/.../README.MD |
| t076 | "start date for Petra's parts library" | 40_projects/.../README.MD |

**Root cause**: Agent derives the date from the folder name prefix without reading the README. The grounding guards (searched-but-never-read, unread-grounding-refs) help but don't always fire.

**Fix direction**:
- The `load_records("40_projects")` approach should fix this: the records are loaded from the files (which are read), and the file paths end up in grounding_refs automatically
- Verify the auto-load triggers on `list("40_projects")`

### P5: MISSING/UNEXPECTED WRITES — 2 failures (6%)

| Task | Error |
|------|-------|
| t041 | missing file write (OCR task didn't create expected file) |
| t043* | body mismatch (OCR created file with wrong content) |

**Root cause**: OCR/migration tasks are complex (read source file, parse ASCII table, convert to YAML frontmatter, write new file). The LLM sometimes gets the output wrong — CJK characters, markdown table alignment, or missing files.

**Fix direction**:
- These are LLM quality issues on complex generation tasks
- The frontmatter gap normalizer helps with +1 byte issues but doesn't fix content-level errors
- Could add a "write validator" that parses the YAML frontmatter after writing and checks for syntax errors — but this is significant new infrastructure

### P6: NO ANSWER — 1 failure (3%)

| Task | Question |
|------|----------|
| t092 | "Queue up these docs for migration to NORA" |

**Root cause**: Agent exhausted step limit or timed out (628s) on a complex multi-file queue task.

**Fix direction**: Increase `max_executor_steps` from 50 → 75 for complex tasks, or optimize the workflow.

### P7: FRONTMATTER VALUE MISMATCH — 1 failure (3%)

Previously present but not in this run — varies by task variant.

## Estimated Impact per Fix

| Fix | Targets | Effort | Expected improvement |
|-----|---------|--------|---------------------|
| Strengthen tabular query adoption (auto-load + planner) | P0, P1, P3, P4 | Low | +5-8 tasks |
| YAML quoting normalizer for outbox emails | P2 | Medium | +3 tasks |
| Entity resolution via load_records | P1 (t003, t028, t078) | Low | +2-3 tasks |
| Strengthen deletion task handling (rule 9 scope) | P0 (t031) | Low | +1 task |
| NaN/missing field → CLARIFICATION guidance | P3 (t000, t002, t075) | Low | +2 tasks |
| Write validation (YAML syntax check) | P2, P5 | High | +3-4 tasks |

**Conservative estimate**: fixing P0+P1+P2+P3 could bring the score to **~80-85%** (83-88/104).

**Optimistic estimate**: with all fixes + stronger model, **~90%** (94/104).

## Priority Order

1. **YAML quoting normalizer** — deterministic code fix, 3 guaranteed wins
2. **Entity resolution via tabular queries** — improves P0+P1+P3 together (~8 tasks)
3. **NaN/missing field guidance** — low effort, targets fabrication (P3)
4. **Deletion task rule scope** — one-line fix for t031
5. **Write validation** — higher effort, targets P5

## Architecture Summary

Current pipeline:
```
Bootstrap → Planner → Executor → Security Guard → Validator → Apply Writes → Submit
                         ↓
                    load_records (auto on list)
                         ↓
                    calculate (pandas df)
```

Key guardrails in executor:
- Empty message guard
- Grounding guard (file paths in answer but no reads)
- Searched-but-never-read guard
- Unread grounding_refs guard
- Security coherence guard (plan_notes contradict outcome)

Key validator checks:
1. Does answer contain actual data?
2. Independent verification (email match, cross-account, security flags)
3. Empty source-files check (READ tasks, skip computation/write)
4. Exact-match semantics (with name-order exception, no-results clause)
5. Precision enforcement (trim verbose answers, protect atomic values)
6. Security coherence (notes vs outcome contradiction)
7. Short-circuit non-OK outcomes

Independent security guard (separate LLM step):
- Runs on OUTCOME_OK + pending writes
- Step-by-step analysis: sender role → files being sent → workspace vs external
- Catches internal file sharing with external contacts
