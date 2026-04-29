# Phase E Design Validation Report

## 1. Executive Summary

**Decision: GO (proceed directly to `spec-tasks`).**

The design is concrete, traceable, and internally consistent. All three open gap-analysis questions (D1 schema, D2 JSON-serialization, D3 date-tolerance) are resolved with explicit rationale, tests, and atomic-commit invariants. Cited file:line references all match current code. Risk register is substantive (22 entries, each with a specific mitigation — no `TBD`). The one structural concern (R2's anchor placement collides with the existing rule 14 `\n` boundary at `prompts.py:186`) is a minor implementation-detail polish, not a blocker.

## 2. Dimension Scorecard

| # | Dimension | Score | Justification |
|---|-----------|-------|---------------|
| 1 | Requirements coverage | 5/5 | Every R1–R9 mapped to a design section, code touchpoint, and test (traceability table §Requirements Traceability is complete). |
| 2 | Specificity | 4/5 | Function signatures, before/after prompt diffs, exact file:line targets given; one weak spot — the rule 14 in-line append placement is described textually, not as a literal before/after diff. |
| 3 | Design decisions completeness | 5/5 | D1/D2/D3 resolve all gap-analysis open questions; D4–D9 close secondary ambiguities surfaced during discovery. No new unresolved design questions. |
| 4 | Risk register depth | 5/5 | 22 entries, all with specific mitigations; P0 entries tied to verifiable grep/test gates. |
| 5 | Test strategy | 5/5 | Unit tests per new helper, 5-run pre-commit batteries per R with explicit task IDs + ≥4/5 bar, 3+ run benchmark average ≥99/104 bar, per-task pass-rate distribution captured. |
| 6 | Atomic-commit invariant | 5/5 | Per-R table lists exact files that must land together; R2's "rule 0 + rule 14 in one commit" explicitly prevents the D3 reconciliation gap. |
| 7 | Edit-order sanity | 5/5 | R5 → R1 → R2 matches gap-analysis; parallel groups (R4, R3, R6) correctly identified; terminal R8, continuous R9. |
| 8 | Scope discipline | 5/5 | SCOPE BOUNDARIES preserved; design adds 4 explicit carve-outs (#9–#12) that tighten rather than expand scope. |
| 9 | Traceability | 5/5 | Traceability matrix at §Requirements Traceability covers R1–R9 with components/interfaces/flows. |
| 10 | Anti-masking preservation | 4/5 | R9 grep suite codified in §Test strategy including new prohibitions (per-task hardcode, internal-lane leak); however it is described as "pre-push CI" without naming where the hook actually lives — same gap the gap-analysis flagged. |

**Overall: 48/50 (96%) — GO.**

## 3. D1–D9 Decision Verification

- **D1 (schema keys)** — COHERENT. Rationale is explicit (workspace is ground truth; fixture already uses `unit_eur`/`line_eur`; `full_pac1_prod.txt:1409,1896` cited). R2 example expressions (§P-E-2) use `line_eur`/`unit_eur` consistently. The `{item, qty, price, line_total}` tokens appear **only in D1's own "Problem/Alternatives" discussion** — no leakage into R2/R3 example code. Null-safety spelled out (`0` defaults, row-drop on malformed rows).
- **D2 (`_LIST_COLUMN_EXEMPT`)** — COHERENT. Exact module-level constant, exact loop modification shown. Dual test invariant (`test_load_records_preserves_line_items_list_dict` + `test_load_records_still_serializes_non_exempt_list_columns`) preserves `attachments` serialization behavior. Documented as frozenset for future extension.
- **D3 (±2 days)** — COHERENT. Both loci (rule 0 at `prompts.py:110,114` and new rule 14 anchor) updated to `<=2` in **the same R2 commit**. Failure-data rationale tied to t005/t030/t080. Post-commit grep gate (`+/- 3 days` → zero hits) specified in R2.b mitigation. No residual `±3` in target text.
- **D4 (`_find_project`)** — COHERENT but slightly overloaded. The decision describes two approaches in one block: (a) a `_find_project(query, df)` helper, and (b) a synthetic `_name_keywords` DataFrame column. Both are kept; the helper wraps the column query. This is fine but the design could have been crisper about which is primary — see Improvement #1.
- **D5 (`security_guard.py`)** — COHERENT. OR-composition specified; structural check runs after `_security_review` (preserving LLM's richer reasoning in logs); body-text matching tightening documented; case-sensitivity asymmetry explicit; R4 AC10 verified by grep gate.
- **D6 (sniffer)** — COHERENT. Regex anchored to line start; comprehension false-positive explicitly tested (`test_detect_statement_keywords_allows_comprehensions`). SyntaxError branch retained as second line of defense.
- **D7 (validator untouched)** — COHERENT. Conservative-escalation argument is sound (missed inbound detection degrades to "treat as outbound", never to false-positive DENY). Escape hatch: follow-up commit if t035 5-run fails.
- **D8 (R7 closed)** — COHERENT. Tied to SCOPE BOUNDARIES item 8 and R7 AC3/AC5. Expected impact +0-1 inside the ≥99/104 bar. No code allocated; R9 still guards future R7 code from sneaking in.
- **D9 (allowlist)** — COHERENT. Closes the R9 AC11 vs AC13 ambiguity the gap analysis flagged. Tests + production co-evolve per-commit; `tools.py` confirmed in R5 line.

## 4. Critical Issues (blocking)

**None.** No critical architectural misalignment, no requirement gap, no unresolved open question.

## 5. Improvement Suggestions (non-blocking, for tasks/implementation phase)

1. **D4 phrasing is slightly two-headed.** The design says both "add `_find_project(query)` inside `dispatch.py`" and "Alternative pursued: a fully internal `_find_project` helper that the agent never calls directly — instead, the loader enriches the DataFrame with a queryable `_name_keywords` text column." These aren't alternatives — they're layered. Recommend tasks.md phrase it as: primary mechanism = `_name_keywords` column; `_find_project(query, df)` is the unit-testable helper exposing the same tokenization logic. (Design text §D4 paragraphs 1–2.)
2. **R2 rule-14 append placement.** §P-E-2 says "appended to the rule 14 text at `prompts.py:186` so the literal English `14. LINE ITEMS vs FILE LINES:` header is preserved verbatim". Current rule 14 ends at line 186 with `"separator rows, and total/summary rows from the count.\n"`. The design should specify whether the new text appends inside the same string-concatenation block (before `\n"`) or replaces the trailing `\n`. Recommend a literal "before/after" diff in tasks.md.
3. **R9 CI hook location.** §Test strategy spells out the pre-push grep commands but does not specify the CI hook file (e.g. `.git/hooks/pre-push`, `.pre-commit-config.yaml`, or a CI workflow file). Gap-analysis recommended "scripting the three greps as pre-commit hooks or CI checks." Recommend task-level decision on hook surface before R1 lands.
4. **D6 regex minor.** The `_STATEMENT_RE` pattern shown has three alternatives OR'd together, but the third alternative `(?:\n[ \t]+[^\s])` ("indentation suggesting a statement block") would false-positive on multi-line expressions with aligned continuation (e.g. a long `.apply(lambda: ...\n    ...)`). Recommend tasks.md stress-test this with a fixture of legitimate multi-line valid expressions.

## 6. Traceability Matrix (R1–R9)

| R | Summary | Design Section | Code Touchpoint | Tests | Status |
|---|---------|----------------|-----------------|-------|--------|
| R1 | `line_items` column as `list[dict]` | D1, D2, §Data model §line_items, §Code touchpoints R1 | `dispatch.py:_parse_line_items_table` (new), `_load_records` phase 2 (606-617), `_LIST_COLUMN_EXEMPT` @ ~358, serialization loop (676-681) | `TestParseLineItemsTable`, `TestLoadRecordsLineItemsColumn` | Complete |
| R2 | Triple-filter anchor + ±3→±2 reconciliation | D3, §Prompt anchors P-E-1, P-E-2, §Code touchpoints R2 | `prompts.py:108-115` (rule 0), `prompts.py:186` (rule 14 append) | 5-run battery t005/t030/t058/t080/t084 | Complete |
| R3 | `_find_project` + `_name_keywords` | D4, §Data model §_name_keywords, §Prompt anchors P-E-3 | `dispatch.py:_find_project` (new), `_load_records` phase 3 (~675), `prompts.py:280-284` | `TestFindProject`, t001 5-run | Complete |
| R4 | Structural security guard | D5, §Module boundaries, §Code touchpoints R4 | New `agent/security_guard.py`, `executor.py:1235` call site | `TestStructuralSecurityCheck` (new file), t011/t036/t073 5-run | Complete |
| R5 | `calculate()` expression-only enforcement | D6, §Code touchpoints R5 | `tools.py:157-167`, `tools.py:173-180`, `dispatch.py:_safe_calculate` (379-402), `_detect_statement_keywords` (new @ ~358) | `TestDetectStatementKeywords`, t012 Lukas Brenner 5-run | Complete |
| R6 | Multilingual inbox verbs | D7, §Prompt anchors P-E-4 | `skills/inbox-processing/SKILL.md` append after line 25 | t035 5-run | Complete |
| R7 | OCR byte-for-byte preservation | D8 (closed) | — | — | Closed at design time |
| R8 | Multi-run verification | §Test strategy §Multi-run | Operational only (`run_targeted.py`, `main_batch.py`) | 3+ full 104-task runs | Complete |
| R9 | Anti-masking + allowlist | D9, §Test strategy §R9 continuous greps, §Non-goals | 5 pre-push grep commands | Continuous per-commit | Complete |
