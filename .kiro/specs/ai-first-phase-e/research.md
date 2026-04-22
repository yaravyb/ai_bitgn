# Phase E Research & Design Decisions

## Summary

- **Feature:** `ai-first-phase-e`
- **Discovery Scope:** Extension (brownfield, narrow-scope tightening pass)
- **Discovery type:** Light (per `design-discovery-light.md`). ~90% of Phase E infrastructure already in place from Phases A/C/D per gap-analysis; the pipeline shape is preserved; new code is additive.
- **Key Findings:**
  1. **Workspace line-item schema reality is `{item, qty, unit_eur, line_eur}`**, not the `{item, qty, price, line_total}` named in R1 AC1. Confirmed at `tests/test_dispatch.py:235` (fixture) and `full_pac1_prod.txt:1409, 1896` (live traces). Design resolves via D1 (adopt workspace shape verbatim).
  2. **`_load_records` JSON-serialization at `dispatch.py:676-681` directly contradicts R1 AC4** (which mandates `list[dict]`). Design resolves via D2 (selective exemption `_LIST_COLUMN_EXEMPT = {"line_items"}`).
  3. **Rule 0 `±3 days` at `prompts.py:110` conflicts with R2 AC1 `±1-2 days`.** Design resolves via D3 (pick ±2 and update both loci in the R2 commit).

## Research Log

### Q1: CJK vendor content in ASCII line-items tables — does the existing `^\+[-+]+\+$` separator regex and `|`-split cell extraction handle Unicode cell bodies correctly?

- **Context:** R1.c risk in gap-analysis. t080 uses the vendor `深圳市海云电子`; the bill file includes this vendor's name in at least one cell. The existing `_parse_ascii_table` regex for separator lines is `^\+[-+]+\+$` (ASCII-only), and cells are extracted by splitting on `|` then stripping whitespace. Question: does any step here silently drop or mangle CJK characters?
- **Sources Consulted:**
  - `pac1-py/agent/dispatch.py:438-455` (existing `_parse_ascii_table` implementation).
  - Python 3.x `str.split`, `str.strip` documentation (stdlib, Unicode-aware by default).
  - `pac1-py/full_pac1_prod.txt:1409` (live trace showing CJK vendor in a 2-column key-value ASCII table row that currently parses).
- **Findings:**
  - The separator regex `^\+[-+]+\+$` only matches the `+---+---+` lines between cells — those lines contain only ASCII `+` and `-`. CJK text appears inside the pipe-delimited cell rows, which are matched by `stripped.startswith("|") and stripped.endswith("|")` — no ASCII-only constraint.
  - `"| 深圳市海云电子 |".split("|")` returns `['', ' 深圳市海云电子 ', '']` — Python string split is Unicode-aware; the CJK bytes pass through verbatim.
  - `str.strip()` on CJK content strips only leading/trailing whitespace (U+0020 space, U+3000 ideographic space, etc.) — no CJK character loss.
  - No additional encoding/decoding layer between the file read (which already returns a `str`) and the parser — the `content` arg to `_parse_ascii_table` is already a Python `str` (UTF-8-decoded at read time).
- **Implications:**
  - CJK cell content is safe. The new `_parse_line_items_table` (R1) uses the same row regex approach and will also be Unicode-safe.
  - Unit test `test_parse_line_items_table_cjk_vendor` in R1's test suite covers this explicitly (a synthetic table with `深圳市海云电子` as a row's item field, asserts the item string round-trips byte-for-byte).
  - No regex change needed. R1's parser re-uses the separator regex verbatim.

### Q2: What exact shape does a `line_items` YAML frontmatter block take when the workspace provides it as YAML (not as ASCII body)?

- **Context:** R1 AC2 requires the frontmatter path to be preserved. Gap analysis notes that today's frontmatter may contain `line_items`, `lines`, or `items` as alternate keys (dispatch.py passes through whatever YAML emits), and the serialization pass then stringifies any list-typed column. Before R1 lands, we need the exact shape so the parser's "frontmatter wins" branch (D1 invariant) normalizes correctly.
- **Sources Consulted:**
  - `pac1-py/tests/test_dispatch.py:230-247` (existing fixture: ASCII-table body with `# | item | qty | unit_eur | line_eur` header).
  - `pac1-py/full_pac1_prod.txt:1409, 1896` (live traces showing `unit_eur`/`line_eur` keys in ASCII tables).
  - `pac1-py/agent/dispatch.py:412-422` (`_parse_yaml_frontmatter` — calls `yaml.safe_load`, returns whatever dict YAML produces).
  - Greps against the workspace samples in `full_pac1_prod.txt` for `line_items:`, `lines:`, `items:` as YAML frontmatter keys.
- **Findings:**
  - The canonical workspace representation appears to be the ASCII body table (4-5 columns: `#`, `item`, `qty`, `unit_eur`, `line_eur`). YAML frontmatter `line_items` as a list of dicts is rarer in the live traces inspected — most bills use the ASCII body.
  - When a YAML frontmatter list of dicts IS present, the existing `yaml.safe_load` path returns it as a native `list[dict]`, which is then destructively serialized by the JSON-serialization pass at `dispatch.py:676-681`. After R1's D2 exemption lands, that destructive serialization stops for `line_items` specifically.
  - Alternate keys (`lines`, `items`) are not confirmed in the live traces; R1's parser defensively checks all three keys to cover any future workspace variants.
- **Implications:**
  - R1's YAML branch is: `if record has key in ("line_items", "lines", "items") and value is a list of dicts → normalize via shallow merge with the four default fields, assign to record["line_items"]`. If no such key, fall through to ASCII-body parse.
  - Unit test `test_parse_line_items_frontmatter_wins_over_body` exercises a synthetic bill with both frontmatter `line_items` AND a body ASCII table; the frontmatter list wins, the body is ignored.
  - No schema migration needed — R1 is additive, both paths produce the same normalized `list[dict]` downstream shape.

### Q3: Is the validator prompt's English-only verb enumeration (`prompts.py:325-330`) a practical blocker for t035 post-R6?

- **Context:** R6 extends the inbox-processing SKILL with multilingual verbs. Gap-analysis R6 flagged that the validator prompt at `prompts.py:325-330` enumerates English verbs only for its cross-account check. If the validator doesn't recognize a Chinese task as "inbound", it treats the task as "outbound" and skips the cross-account escalation — potentially ALLOWING a malformed response through. Question: is this a silent correctness problem for t035?
- **Sources Consulted:**
  - `pac1-py/agent/prompts.py:320-340` (validator cross-account check block).
  - t035 failure pattern per `pac1-py/.kiro/specs/ai-first-phase-d/pac1-prod-improvement-plan.md:24-54` (classification: inbox ambiguity in Chinese task text, falling outside English verb list at the SKILL level, not at the validator level).
- **Findings:**
  - The validator's cross-account check is a CONSERVATIVE escalation path: it escalates to `OUTCOME_NONE_CLARIFICATION` when the inbound-message is identified AND the message body asks for data about a different company. If the validator fails to recognize a Chinese task as inbound, it skips the check and the task proceeds as outbound. The worst case is a missed cross-account catch — NOT a false DENIED_SECURITY.
  - t035's failure mode per the plan doc is "agent bypasses the full inbox workflow because Chinese verb `处理` falls outside the English-only SKILL verb list" — the planner/executor path, NOT the validator path. So the fix is skill-level (R6), and the validator's English-only verb list is a *different* gap that does not affect t035 directly.
  - Extending the validator prompt to five languages doubles its surface for a check that is not on the t035 critical path.
- **Implications:**
  - D7 decision: leave validator prompt unchanged in R6. Skill-only extension.
  - If t035 fails the R6 5-run battery (≥ 4/5), diagnose:
    1. Did the planner load the `inbox-processing` skill? → If no, the skill-load trigger needs work (NOT a validator issue).
    2. Did the executor execute Phase 5 writes? → If no, the skill narrative may need stronger language.
    3. Did the validator downgrade OK → CLARIFICATION on a correct response? → Only then does the validator prompt need a multilingual extension, and it gets a follow-up commit within the R9 allowlist.
  - No pre-emptive validator edit. R6 stays tight.

## Architecture Pattern Evaluation

The core pattern for Phase E is **"deterministic layer as backstop, LLM as primary reasoner"** — consistent with the existing codebase philosophy. Each R1–R6 change fits this pattern:

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Deterministic structural check | Path-prefix match against hardcoded internal-lane list (R4) | Zero false negatives on listed lanes; OR-composes cleanly with LLM; no LLM tokens consumed | Deterministic means also zero flexibility; R4 AC10 prohibits LLM visibility | Selected for R4 per D5 |
| Deterministic helper + LLM prompt hint | `_find_project` + `_name_keywords` synthetic column; LLM calls `calculate()` to query it (R3) | Helper is testable in isolation; LLM retains reasoning flexibility via substring regex; ambiguity handled via existing rule 11 escalation | Needs LLM to remember the `_name_keywords` column hint; prompt anchor required | Selected for R3 per D4 |
| Pure prompt anchor | New narrative rule in executor prompt only (R2, R6) | Zero code surface; fast to land; already in Phase D toolkit | "Prompt talking to nobody" risk (taxonomy (c)); LLM may ignore the anchor | Selected for R2, R6 where the underlying data/skill layer is already correct |
| Pure code surface | Parser extension; tool-description rewrite (R1, R5) | Zero reliance on LLM discipline; regression is detected at test time | Narrow — only fixes what the parser/description covers | Selected for R1, R5 where the root cause is a missing data-shape layer |
| Closed / deferred | Accept as LLM capability limit (R7) | Zero code; zero risk; zero cost | Leaves one task failing | Selected for R7 per D8 |

No exotic patterns under consideration. The design sticks to the Phase D pattern toolkit.

## Design Decisions

Cross-references to `design.md` §Design decisions. Full text of each decision lives in design.md; this section summarizes the trade-off analysis.

### Decision: D1. Adopt workspace shape `{item, qty, unit_eur, line_eur}` verbatim

- **Context:** R1 AC1 names `{item, qty, price, line_total}` but workspace uses `{item, qty, unit_eur, line_eur}`.
- **Alternatives Considered:**
  1. Rename at parse time — parser emits requirement's keys regardless of source.
  2. **Preserve workspace keys verbatim** (selected).
  3. Dual-namespace — parser emits both sets.
- **Rationale:** Preserves debuggability (DataFrame column names match source-file cell headers); existing test fixtures already use the workspace shape; doubling the namespace (option 3) invites the LLM to pick the wrong key.
- **Trade-offs:** Requirement text drifts slightly from implementation; design.md records the deliberate deviation.
- **Follow-up:** R2's example expression uses the workspace keys. Phase E completion report notes the AC1 key-name resolution.

### Decision: D2. Selective exemption `_LIST_COLUMN_EXEMPT = {"line_items"}`

- **Context:** `dispatch.py:676-681` JSON-serializes list/dict columns, conflicting with R1 AC4.
- **Alternatives Considered:**
  1. **Carve selective exemption** (selected).
  2. Drop serialization entirely.
  3. Re-architect with per-column opt-in flag.
- **Rationale:** Minimum blast radius; option 2 silently breaks existing `attachments:`-querying expressions; option 3 is premature abstraction.
- **Trade-offs:** Future columns wanting native types must be added to the exemption set (one-line change).
- **Follow-up:** Two tests assert the dual invariant: `line_items` stays native; `attachments` still serializes.

### Decision: D3. Reconcile date tolerance to ±2 days

- **Context:** Rule 0 (`±3`) vs R2 AC1 (`±1-2`).
- **Alternatives Considered:** ±1, ±2, ±3, ±5.
- **Rationale:** ±2 is the upper bound of R2 AC1's range and the lower bound of rule 0's current tolerance; failure data in t005/t030/t080 shows 0-2 day variance dominates.
- **Trade-offs:** ±2 may miss one-off edge cases where a bill is 3 days off; multi-run R8 verification will surface them if they matter.
- **Follow-up:** Both loci (rule 0 and new rule-14 anchor) use `<= 2` consistently. grep for `+/- 3 days` post-R2 commit: zero hits.

### Decision: D4. Option A code-level helper (`_find_project`) without new tool

- **Context:** R3 permits either a code-level helper (Option A) or prompt-only guidance (Option B). Option A via a new tool would edit `tools.py`, outside R3's allowlist.
- **Alternatives Considered:**
  1. Option A with new tool in `tools.py` — **rejected** (scope creep).
  2. **Option A with a private helper in `dispatch.py` + synthetic `_name_keywords` column** (selected).
  3. Option B — prompt-only — rejected (existing planner rule 6 is soft guidance and already fails).
- **Rationale:** Keeps R3 inside the `dispatch.py` + `prompts.py` allowlist; deterministic via the `_name_keywords` column; ambiguity handled by rule 11's existing CLARIFICATION escalation.
- **Trade-offs:** `_name_keywords` column is always computed for `projects/` loads (small cost). LLM must remember the column name (handled by planner rule 6 extension).
- **Follow-up:** Unit test `test_find_project_tokenization` + integration test that t001 5-run battery ≥ 4/5.

### Decision: D5. New `agent/security_guard.py` module with `structural_security_check`

- **Context:** R4 permits either inline in `executor.py` or a new module.
- **Alternatives Considered:**
  1. Inline check in `_security_review` (keeps one-file guard).
  2. **New `agent/security_guard.py` module** (selected).
- **Rationale:** Separation of concerns — LLM check vs structural check are independent at the code level; new module is testable in isolation (new `tests/test_security_guard.py`); the check is ≤ 80 LOC and doesn't fit cleanly inside `_security_review`.
- **Trade-offs:** One more file in the agent package; import overhead is negligible.
- **Follow-up:** R4 AC10 compliance — grep `30_knowledge|90_memory|99_system` in `prompts.py` and `skills/` returns zero hits at commit time.

### Decision: D6. Proactive statement-keyword sniffer alongside SyntaxError hint

- **Context:** R5 AC3 requires a SyntaxError-specific hint. Some multi-line scripts parse as valid expressions.
- **Alternatives Considered:**
  1. SyntaxError branch only (AC3 literal).
  2. **SyntaxError branch + proactive line-anchored regex sniffer** (selected).
- **Rationale:** Covers the false-negative case where `compile()` succeeds on an intended-as-script expression; regex is line-anchored to avoid false-positives on comprehensions.
- **Trade-offs:** Small regex maintenance surface; false-positive risk on esoteric valid expressions.
- **Follow-up:** Unit test `test_detect_statement_keywords_allows_comprehensions` verifies `[x for x in records]` does NOT match.

### Decision: D7. Leave validator prompt unchanged in R6

- **Context:** Validator prompt enumerates English verbs only for cross-account check.
- **Alternatives Considered:**
  1. Extend validator prompt to five languages in R6.
  2. **Leave validator unchanged** (selected).
- **Rationale:** t035's failure mode is at the skill-load level, not the validator level; conservative fallback behavior; keeps R6 narrow and R9-clean.
- **Trade-offs:** A different Chinese cross-account task (if it exists elsewhere) may miss its cross-account check; monitored in R8 multi-run.
- **Follow-up:** If t035 fails R6 5-run despite skill extension, validator extension lands in a separate follow-up commit.

### Decision: D8. Close R7 at design time

- **Context:** R7 is P4/optional; AC3/AC5 permit closure; gap-analysis flags multiple risks (task detection, stomping intentional edits, scope creep).
- **Alternatives Considered:**
  1. Pursue byte-for-byte copy helper.
  2. **Close at design time as accepted LLM capability limit** (selected).
- **Rationale:** Detection without per-task hardcoding requires task-text keyword sniffing (SCOPE BOUNDARIES item 7 risk); impact is +0-1 task inside the ≥ 99/104 bar.
- **Trade-offs:** t018 remains a known failure; documented explicitly in Phase E completion report.
- **Follow-up:** Record the R7 AC5 closure text in the Phase E completion report.

### Decision: D9. Extend R9 allowlist to include test files

- **Context:** R9 AC13 requires test updates in the same commit as production code. R9 AC11 allowlist doesn't explicitly list test files.
- **Alternatives Considered:**
  1. Treat test-file edits as allowlist violations and require separate justification per commit.
  2. **Extend allowlist to implicitly include matching test files per R1/R3/R4/R5** (selected).
- **Rationale:** Aligns R9 AC11 with R9 AC13; removes a known ambiguity.
- **Trade-offs:** None — D9 only codifies what AC13 already requires.
- **Follow-up:** Every Phase E commit-message template includes the D9-extended allowlist statement.

## Risks & Mitigations

See `design.md` §Risk register for the full table. Key P0 risks and their design-level mitigations:

- **R1.a** (JSON-serialization regression) — Mitigated by D2 selective exemption + dual test invariant.
- **R2.b** (rule 0 vs R2 date-tolerance conflict) — Mitigated by D3 atomic edit in R2 commit.
- **R3.d** (prompt-only unreliability) — Mitigated by D4 code-level helper.
- **R4.a** (false positives on body-text mention) — Mitigated by D5 tightening to `attachments:` list only.
- **R4.c** (structural check leaks into LLM text) — Mitigated by CI grep gate.
- **R6.c** (additive-only regression) — Mitigated by R6 commit being a pure append below line 25.

## References

- `/home/yaravyb/CODE/ai_bitgn/.kiro/specs/ai-first-phase-e/requirements.md` — R1–R9 EARS acceptance criteria.
- `/home/yaravyb/CODE/ai_bitgn/.kiro/specs/ai-first-phase-e/gap-analysis.md` — per-requirement existing-components, integration-points, implementation-gap, risks, strategy.
- `/home/yaravyb/CODE/ai_bitgn/.kiro/specs/ai-first-phase-d/pac1-prod-improvement-plan.md` — full failure catalog, round-3 baseline, architecture summary.
- `/home/yaravyb/CODE/ai_bitgn/.kiro/specs/ai-first-phase-d/design.md` — reference for section layout, Risk Register format, Edit-Order-and-Smoke-test-Checkpoints style.
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/agent/dispatch.py` lines 358-402 (calc namespace / `_safe_calculate`), 412-422 (`_parse_yaml_frontmatter`), 425-460 (`_parse_ascii_table`), 547-711 (`_load_records`), 676-681 (JSON-serialization conflict).
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/agent/executor.py` lines 46-128 (`_security_review`), 1234-1248 (security-guard hook), 1278 (attachments regex template).
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/agent/prompts.py` lines 58-211 (`build_executor_system`), 108-115 (rule 0 date window), 179-186 (rule 14 adjacency), 214-286 (`build_planner_system`), 280-284 (planner rule 6), 320-340 (validator cross-account).
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/tools.py` lines 154-186 (calculate schema).
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/tests/test_dispatch.py` lines 212-298 (`TestAsciiTableNormalizer`, `TestAsciiTableParser`), line 235 (workspace `unit_eur`/`line_eur` schema fixture).
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/skills/inbox-processing/SKILL.md` lines 10-25 (Phase D R-DT24 English verb list).
- `/home/yaravyb/.kiro/settings/rules/design-principles.md` — Phase E design rules and section authoring guidance.
- `/home/yaravyb/.kiro/settings/rules/design-discovery-light.md` — discovery process for extensions.
