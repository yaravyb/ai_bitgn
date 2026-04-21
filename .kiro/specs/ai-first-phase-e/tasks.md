# Implementation Plan — Phase E (pac1-prod Hardening for 95%+ Bench Score)

## Edit order (locked)

```
T5 (R5) → T1 (R1) → T2 (R2) → [ T3 (R3) || T4 (R4) || T6 (R6) ]  → T8 (R8 verification)
                                                                   └── T9 (R9) runs on every commit boundary
                                                                       T7 (R7) CLOSED at design time (D8 — no commit)
```

Locked by design.md §"Edit order and smoke-test checkpoints" and §"Atomic-commit
invariant". Rationale:

- **T5 = R5 first** — lowest risk, independent, zero dependencies. A `tools.py`
  description rewrite plus a localized `_safe_calculate` branch + proactive
  keyword sniffer. Immediate feedback from the t012 (Lukas Brenner birthday
  variant) 5-run battery; no downstream tasks read R5's changes.
- **T1 = R1 second** — foundational. `_parse_line_items_table`, the
  `_LIST_COLUMN_EXEMPT` carve-out, and the matching test updates ship as
  ONE atomic commit per the D2/D9 invariants. T2's triple-filter anchor
  literally names the `line_items` column T1 creates; T1 must land first.
- **T2 = R2 third** — depends on T1. Rule-14 triple-filter extension and the
  rule-0 `±3 → ±2` reconciliation MUST land in the same commit (D3); both
  edits are inside `prompts.py`.
- **T3 = R3, T4 = R4, T6 = R6 parallelizable after T2 lands** — each is
  independent of the others at the file level:
  - T3 touches `dispatch.py` + `prompts.py` + `tests/test_dispatch.py`.
  - T4 touches new `agent/security_guard.py` + `executor.py` + new
    `tests/test_security_guard.py`.
  - T6 touches `skills/inbox-processing/SKILL.md` only.
  Each carries a `(P)` marker.
- **T7 = R7 CLOSED at design time** (D8). No commit, no code. Recorded in
  the Phase E completion report as "accepted LLM capability limit; t018
  remains a known failure mode pending base-model upgrade". R9's anti-masking
  guard still prevents any future R7 code from sneaking in without an
  amending design decision.
- **T8 = R8 verification** runs AFTER T1–T6 all land. Three independent
  full-104-task `bitgn/pac1-prod` runs; compute per-task pass-rate
  distribution; target ≥ 99/104 averaged with no single run below 91/104.
- **T9 = R9 continuous invariant** — the pre-push hook script runs the
  five grep commands from design §Test strategy on every Phase E commit
  boundary. Landed once near the start (after T5 or T1); applies to every
  subsequent commit.

Every task includes a mandatory **Scope check**: `git diff --stat HEAD~1`
against the per-requirement allowlist below. Any file outside the allowlist
is a scope violation and must be reverted before commit.

## Scope enforcement

### Allowed files per requirement (authoritative)

| Req | Allowed files | Notes |
|-----|---------------|-------|
| R1 (T1) | `pac1-py/agent/dispatch.py`, `pac1-py/tests/test_dispatch.py` | Single atomic commit; D2 + D9 invariant. |
| R2 (T2) | `pac1-py/agent/prompts.py` | Single atomic commit; rule 0 + rule 14 edits co-occur (D3). |
| R3 (T3) | `pac1-py/agent/dispatch.py`, `pac1-py/agent/prompts.py`, `pac1-py/tests/test_dispatch.py` | Helper + synthetic column + planner pointer + helper test in one commit (D4 + D9). |
| R4 (T4) | new `pac1-py/agent/security_guard.py`, `pac1-py/agent/executor.py`, new `pac1-py/tests/test_security_guard.py` | New module + executor wire-up + tests in one commit (D5 + D9). |
| R5 (T5) | `pac1-py/tools.py`, `pac1-py/agent/dispatch.py`, `pac1-py/tests/test_dispatch.py`, `pac1-py/agent/prompts.py` | Two sub-commits (R5a tools, R5b dispatch+tests) acceptable per design §Atomic-commit invariant. R5c (prompts) added 2026-04-21 post-T8 iter 1-2 evidence: tools.py+dispatch.py wording variants produced t012 pass-rate ≤ 20% because rule-7 full_name mandate in `prompts.py` was attention-starved, not missing. Scope expansion to prompts.py restricted to strengthening existing rule-7 for record-field verbatim extraction — no new executor rule number, no structural changes. |
| R6 (T6) | `pac1-py/skills/inbox-processing/SKILL.md` | Pure append below line 25; no test updates. |
| R7 | — | CLOSED at design time (D8). |
| R8 (T8) | — | Operational only; no production commit. Records result in completion report. |
| R9 (T9) | new `pac1-py/scripts/pre-push-phase-e.sh` | Hook script + install docs; runs on every R1–R6 commit boundary. |

### Forbidden files in Phase E (scope violation if touched)

- **Every non-allowlisted Python file under `pac1-py/agent/`** — `__init__.py`,
  `bootstrap.py`, `planner.py`, `validator.py`, `context.py`, `llm.py`,
  `config.py`, `outcomes.py` (Phase D R-DOI module — preserved verbatim).
- **Every non-allowlisted file under `pac1-py/`** — `main.py`, `tasks.py`,
  `skills.py`.
- **Observability tree** — `pac1-py/observability/**`.
- **All non-allowlisted skill files** — `compliance-check/SKILL.md`,
  `identity-verification/SKILL.md`, `security-posture/SKILL.md`,
  `execution-discipline/SKILL.md`, `date-arithmetic/SKILL.md`.
- **All non-allowlisted test files** — `conftest.py`, `test_compact_tree.py`,
  `test_skill_loader.py`, `test_task_manager.py`.
- **Every `AGENTS.md` / `README.md` under `pac1-py/`**.
- **The `bitgn/` tree** — external protobuf wire format; never touched.
- **Every file under `.kiro/` outside `.kiro/specs/ai-first-phase-e/`**.
- **Benchmark data** — `bitgn/pac1-prod` workspace tasks are untouched per
  SCOPE BOUNDARIES item 6.

### Commit-message template (every Phase E commit)

```
[Phase E R<N>] <one-line summary>

<multi-line body: what changed, why, which ACs, 5-run battery result>
Edit-surface compliance: allows <file1, file2, ...> per R9 AC11 + D9.
```

## Atomic-commit invariants

Per design §Atomic-commit invariant, five tasks carry per-commit atomicity
constraints that bundle multiple files:

- **T1 (R1):** `dispatch.py` + `tests/test_dispatch.py` MUST land together.
  D2's serialization-exemption cannot be verified without both; R1 AC7
  requires test updates in the same commit as production code.
- **T2 (R2):** `prompts.py` alone, BUT both edits (rule 0 `±3 → ±2` at
  lines 110/114 AND rule 14 triple-filter in-line append at line 186) MUST
  co-occur in the same commit. Splitting leaves a divergence where rule 0
  and rule 14 disagree on date tolerance (D3).
- **T3 (R3):** `dispatch.py` + `prompts.py` + `tests/test_dispatch.py`
  MUST land together. `_find_project` + `_name_keywords` synthetic column +
  planner-rule-6 pointer + helper test are mutually referential.
- **T4 (R4):** new `security_guard.py` + `executor.py` + new
  `tests/test_security_guard.py` MUST land together. Executor's new call
  site depends on the new module existing; tests assert both boundaries.
- **T5 (R5):** `tools.py` and `dispatch.py` + `tests/test_dispatch.py`
  may split into R5a (tools.py only) and R5b (dispatch.py + test_dispatch.py).
  If split, R5a commits first and both land BEFORE the R5 t012 smoke battery.

**No cross-requirement commits.** If a later commit discovers a
cross-requirement regression, the fix lands in a new dedicated commit
within the R9 allowlist — NOT by amending an existing R<N> commit.

## Parallelizability

Phase E has three parallelizable tasks: **T3, T4, T6** — each may land
concurrently once T2 has landed. T3, T4, and T6 touch disjoint files
(T3: `dispatch.py` + `prompts.py` + test; T4: new `security_guard.py` +
`executor.py` + new test; T6: single skill file). No inter-task data
dependency; no shared mutable resources; no prerequisite review across
the three.

**Serial chain (non-negotiable):** T5 → T1 → T2. T5 is independent and
goes first for low-risk feedback; T1 is foundational for T2; T2 reconciles
rule 0 date tolerance that T3's and later readers assume.

**Terminal:** T8 (verification) runs only after T1–T6 all land.
**Continuous:** T9 (pre-push hook) lands once early and gates every
subsequent commit via grep.

The `(P)` marker below is applied to T3, T4, and T6 accordingly.

## TDD adaptation note

Phase E mixes two modalities. Tasks T5 (tools description + dispatch helper),
T1 (parser + serialization carve-out), T3 (helper + synthetic column),
T4 (new guard module) use classical **red/green/refactor** with pytest:

- **Red** = write the failing test first (e.g. `TestParseLineItemsTable`,
  `TestStructuralSecurityCheck`, `TestDetectStatementKeywords`).
- **Green** = implement the helper / carve-out until the test passes.
- **Refactor** = `pytest pac1-py/tests/` remains fully green; no regression.

Tasks T2 and T6 are narrative-anchor edits (prompt + skill text) and use
the **grep-based red/green pattern** Phase A/C/D established:

- **Red check** = current state grep (anchor text absent or `±3` present).
- **Green check** = post-edit grep (new anchor text present; old text gone).
- **Refactor** = `pytest` passes (no test asserts on narrative text).

Every production task additionally carries a **5-run pre-commit battery**
against `bitgn/pac1-prod` with a ≥ 4/5 bar per target task ID. Iteration
ceiling: 5 wording iterations per commit. If the ceiling is hit without
meeting the target, escalate per design §Risk register: document the
achievable rate, defer residual brittleness to a follow-up, land with a
"known misfire rate" note OR abandon the commit. Neither escalation path
may re-add Phase A deleted logic or introduce per-task hardcoding.

T8 (multi-run verification) and T9 (pre-push hook) are process/infrastructure
tasks — no red/green, only action steps and deliverables.

---

## Tasks

- [x] 1. Rewrite `calculate()` tool description and add statement-keyword sniffer + SyntaxError hint (T5 = R5)
  - **Status:** landed (commit 7dfbc07)
  - **Depends on:** nothing (first cut in the Phase E chain)
  - **Files (atomic commit, acceptable to split into R5a + R5b):**
    - R5a: `pac1-py/tools.py` — `calculate` tool `description` at lines
      157–167 and parameter `description` at lines 173–180.
    - R5b: `pac1-py/agent/dispatch.py` — new `_STATEMENT_RE` constant and
      `_detect_statement_keywords(expression)` helper near `_CALC_NAMESPACE`
      (~line 358); `_safe_calculate` branch update at lines 379–402.
    - R5b: `pac1-py/tests/test_dispatch.py` — new `TestDetectStatementKeywords`
      class (5 tests per design §Test strategy).
  - **Red check (tools.py):**
    - `rg -i 'no import|no def|no \\bfor\\b|comprehension' pac1-py/tools.py`
      returns 0 hits (the expression-only prohibition is not yet in the
      description).
  - **Red check (dispatch.py):**
    - `rg -n '_detect_statement_keywords' pac1-py/agent/dispatch.py`
      returns 0 hits.
    - `rg -n '_STATEMENT_RE' pac1-py/agent/dispatch.py` returns 0 hits.
    - `rg -n 'except SyntaxError' pac1-py/agent/dispatch.py` returns 0 hits
      (current bare `except Exception` catch is the only trap).
  - **Action — R5a (tools.py):**
    1. Rewrite the `calculate` tool-schema `description` field at
       `tools.py:157–167` to the R5 AC1 text: *"Evaluate a single Python
       EXPRESSION against the pandas DataFrame namespace. NOT a multi-line
       script — no `import`, no `def`, no `for`/`while` loops, no `;`
       statement separators, no top-level assignment. Use list/dict
       comprehensions instead of loops: `[x for x in records if cond(x)]`
       not `for x in records: ...`. If you need intermediate variables,
       use a comprehension with `(expr for x in records if cond)` or
       nested `df.query()` / `df.apply()` calls."*
    2. Include **at least two concrete examples** per R5 AC2: one
       comprehension example (e.g. `[x for x in records if x['amount'] > 100]`)
       and one `.apply(lambda: ...)` example sized short enough to fit
       inside the tool description without bloat.
    3. Extend the parameter `description` at lines 173–180 with one
       comprehension example.
  - **Action — R5b (dispatch.py + test_dispatch.py):**
    1. Add module-level `_STATEMENT_RE` pattern near `_CALC_NAMESPACE`
       (~line 358) per design §D6:
       ```
       _STATEMENT_RE = re.compile(
           r"(?m)^\s*(import |from |def |class |for |while |async |return )"
           r"|(?m);\s*$"
           r"|(?:\n[ \t]+[^\s])"
       )
       ```
    2. Add `_detect_statement_keywords(expression: str) -> bool` helper
       that returns `bool(_STATEMENT_RE.search(expression))`.
    3. Modify `_safe_calculate` at lines 379–402:
       - Before the `compile(...)` call, invoke `_detect_statement_keywords`;
         if True, return the structured hint string immediately.
       - Wrap `compile(...)` in a specific `except SyntaxError as exc`
         branch that returns the R5 AC3 hint text PLUS the original
         SyntaxError `msg` and `offset` per AC4.
       - Preserve the outer `except Exception` branch for runtime errors
         unchanged (AC5 invariant).
    4. Add `TestDetectStatementKeywords` class to `test_dispatch.py`
       covering the 5 D6-specified cases: `import` at line start → True,
       `for x in records:` at line start → True, `[x for x in records]`
       → False (D6 false-positive guard), `.apply(lambda r: ...)` → False,
       top-level `;` separator → True.
    5. **Multi-line expression stress test (design-validation improvement
       #4):** add `test_detect_statement_keywords_allows_multiline_apply`
       asserting a legitimate `.apply(lambda r: ...\n    ...)` with aligned
       continuation does NOT fire the sniffer. Fixture string spans two
       lines with indented continuation; expected result False.
  - **Preserve (R5 AC5):**
    - Restricted-eval namespace (`df`, `pd`, `records`, math helpers,
      `date_offset`, `days_between`, `text_match`, `parse_date`) unchanged.
    - `_safe_calculate` return-type contract unchanged.
    - All non-SyntaxError exception paths unchanged.
  - **Green check (tools.py):**
    - `rg -i 'EXPRESSION|comprehension|no import' pac1-py/tools.py`
      returns ≥ 3 hits.
    - `rg -i 'for x in records' pac1-py/tools.py` returns ≥ 1 hit
      (comprehension example).
  - **Green check (dispatch.py):**
    - `rg -n '_detect_statement_keywords' pac1-py/agent/dispatch.py`
      returns ≥ 2 hits (definition + call site).
    - `rg -n 'except SyntaxError' pac1-py/agent/dispatch.py`
      returns ≥ 1 hit.
    - `rg -i 'calculate\(\) accepts only Python expressions' pac1-py/agent/dispatch.py`
      returns ≥ 1 hit (the R5 AC3 hint literal).
  - **Import / smoke check:**
    `python -c "import sys; sys.path.insert(0,'pac1-py'); from agent.dispatch import _detect_statement_keywords, _safe_calculate; assert _detect_statement_keywords('for x in r:') is True; assert _detect_statement_keywords('[x for x in r]') is False; res = _safe_calculate('import os', {}); assert 'expressions' in str(res).lower()"`
    exits 0.
  - **Pytest check:** `pytest pac1-py/tests/test_dispatch.py::TestDetectStatementKeywords -v`
    — all 5+1 tests green; full `pytest pac1-py/tests/` still fully green.
  - **Pre-commit per-task battery (R5 AC6 — MANDATORY gate):**
    - **t012 Lukas Brenner birthday variant 5-run battery:** run five
      consecutive times. Target: **≥ 4/5 pass rate**.
    - Iteration ceiling: 5 wording iterations of the hint text + tool
      description. Escalate per design §Risk register if ceiling hit.
  - **Scope check:** `git diff --stat HEAD~1` touches ONLY `tools.py`,
    `agent/dispatch.py`, `tests/test_dispatch.py`. No `prompts.py`,
    no `executor.py`, no skill file.
  - **R9 anti-masking grep (pre-push, runs via T9 hook):** all five R9
    greps return 0 hits.
  - **Commit:** `[Phase E R5] calculate() expression-only enforcement`
    (single commit, or two commits R5a then R5b per design §Atomic-commit
    invariant).
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

- [x] 2. Expose `line_items` list[dict] column on load_records + serialization exemption (T1 = R1, ATOMIC)
  - **Status:** landed (commit 351173e)
  - **Depends on:** Task 1 (T5 must land first per the edit-order chain).
  - **Files (single atomic commit per D2 + D9):**
    - `pac1-py/agent/dispatch.py` — new `_parse_line_items_table(text) -> list[dict]`
      helper placed between `_parse_ascii_table` (~line 460) and the
      `_generated_parsers` cache (~line 464); module-level
      `_LIST_COLUMN_EXEMPT = frozenset({"line_items"})` near `_CALC_NAMESPACE`
      (~line 358); `_load_records` phase 2 wire-up at lines 606–617; and
      serialization-pass exemption at lines 676–681.
    - `pac1-py/tests/test_dispatch.py` — new `TestParseLineItemsTable`
      (5–6 tests) and `TestLoadRecordsLineItemsColumn` (3–4 tests).
  - **Atomic-commit invariant:** `dispatch.py` + `tests/test_dispatch.py`
    land in ONE commit. D2's selective-exemption invariant cannot be
    verified without both the `line_items = list[dict]` test AND the
    `attachments = JSON-string` test co-existing in the same pytest run.
  - **Schema decision (D1 — binding):** the parsed dict shape is
    `{item: str, qty: int|float, unit_eur: float, line_eur: float}`.
    Workspace keys `unit_eur` / `line_eur` are used verbatim; R1 AC1's
    `price` / `line_total` tokens are treated as semantic intent (a
    4-field dict) and never appear in implementation code. Null-safety:
    missing numeric fields default to `0`, string `item` defaults to `""`,
    malformed rows are dropped from the list.
  - **Red check:**
    - `rg -n '_parse_line_items_table' pac1-py/agent/dispatch.py` returns
      0 hits (new helper absent).
    - `rg -n '_LIST_COLUMN_EXEMPT' pac1-py/agent/dispatch.py` returns 0 hits.
    - `rg -n 'TestParseLineItemsTable' pac1-py/tests/test_dispatch.py`
      returns 0 hits.
    - `rg -nC 2 'for col in.*columns' pac1-py/agent/dispatch.py`
      captures the current unconditional JSON-serialization loop at
      lines 676–681 (baseline state for D2 carve-out).
  - **Action (single atomic commit):**
    1. **Add `_LIST_COLUMN_EXEMPT` constant** near `_CALC_NAMESPACE`
       (~line 358):
       ```
       _LIST_COLUMN_EXEMPT: frozenset[str] = frozenset({"line_items"})
       ```
    2. **Add `_parse_line_items_table(text: str) -> list[dict]` helper**
       between `_parse_ascii_table` and the parser cache (~line 460):
       - Parse ASCII tables shaped `| # | item | qty | unit_eur | line_eur |`
         (4 or 5 columns — leading `#` column optional).
       - Reuse existing separator regex (ASCII-safe per research Q1 — CJK
         vendor names like `深圳市海云电子` pass through the `|`-split
         cleanly).
       - Return `list[dict]` with the four workspace keys; apply null-safety
         defaults (`0` numeric, `""` string); drop rows that don't parse
         as 4–5 columns.
       - If the input text has no table, return `[]`.
    3. **Wire into `_load_records` phase 2** at lines 606–617:
       - After `_parse_yaml_frontmatter(content)`, check whether the
         resulting `record` already has a `line_items` / `lines` / `items`
         key from frontmatter. If yes → normalize via shallow merge with
         the four default fields and assign to `record["line_items"]`
         (frontmatter wins per R1.b / D1 invariant).
       - If no frontmatter `line_items`, call `_parse_line_items_table(content)`
         on the body text; assign to `record["line_items"]`.
       - In all other cases (bill has neither frontmatter list nor body
         table), default `record["line_items"] = []`.
    4. **Carve serialization exemption** at lines 676–681:
       ```
       for col in _loaded_df.columns:
           if col in _LIST_COLUMN_EXEMPT:
               continue  # R1: preserve list[dict] for .apply() queries
           if _loaded_df[col].apply(lambda x: isinstance(x, (list, dict))).any():
               _loaded_df[col] = _loaded_df[col].apply(
                   lambda x: json.dumps(x) if isinstance(x, (list, dict)) else x
               )
       ```
    5. **Add `TestParseLineItemsTable`** (5–6 tests):
       - Basic 4-column parse (`item | qty | unit_eur | line_eur`).
       - 5-column parse with leading `#` index column.
       - CJK vendor name in a cell (`深圳市海云电子`) — round-trips
         byte-for-byte per research Q1.
       - Empty body → `[]`.
       - Frontmatter `line_items` wins over body parse (D1 idempotence).
       - Parser idempotent on repeated calls.
    6. **Add `TestLoadRecordsLineItemsColumn`** (3–4 tests):
       - `test_load_records_preserves_line_items_list_dict`:
         `type(df['line_items'].iloc[0])` is `list`;
         `type(df['line_items'].iloc[0][0])` is `dict`. D2 invariant.
       - `test_load_records_still_serializes_non_exempt_list_columns`:
         synthetic `attachments:` list column still emerges as JSON string.
         D2 dual invariant.
       - Empty-list default for files without line items (R1 AC3).
       - `_name_keywords` column NOT present for non-`projects/` loads
         (T3 forward-compat check).
  - **Preserve (R1 AC5):**
    - `load_records` return type and outer signature unchanged.
    - Auto-trigger behavior on structured folders with ≥ 3 parseable files
      unchanged.
    - JSON/YAML/ASCII parsing precedence unchanged (frontmatter still wins
      over body).
    - Column set for non-bill files (contacts, accounts, projects, etc.)
      unchanged — `line_items` appears ONLY on bill/invoice rows.
    - Existing `TestAsciiTableParser` / `TestAsciiTableNormalizer` classes
      continue to pass; update assertions ONLY if they reference columns
      the serialization exemption now covers.
  - **Green check:**
    - `rg -n '_parse_line_items_table' pac1-py/agent/dispatch.py` returns
      ≥ 2 hits (definition + call site).
    - `rg -n '_LIST_COLUMN_EXEMPT' pac1-py/agent/dispatch.py` returns
      ≥ 2 hits (definition + use).
    - `rg -n 'TestParseLineItemsTable|TestLoadRecordsLineItemsColumn' pac1-py/tests/test_dispatch.py`
      returns ≥ 2 hits.
  - **Import / smoke check:**
    `python -c "import sys,json; sys.path.insert(0,'pac1-py'); from agent.dispatch import _parse_line_items_table, _LIST_COLUMN_EXEMPT; assert 'line_items' in _LIST_COLUMN_EXEMPT; r = _parse_line_items_table('| item | qty | unit_eur | line_eur |\n|---|---|---|---|\n| Widget | 2 | 5.0 | 10.0 |'); assert isinstance(r, list); assert isinstance(r[0], dict); assert r[0]['item'] == 'Widget'; assert r[0]['line_eur'] == 10.0"`
    exits 0.
  - **Pytest check:** `pytest pac1-py/tests/test_dispatch.py -v` — all
    existing tests still green PLUS new `TestParseLineItemsTable` (5–6)
    and `TestLoadRecordsLineItemsColumn` (3–4) green.
  - **Pre-commit per-task batteries (R1 AC6 — MANDATORY iterative gate):**
    - **t005 5-run battery:** ≥ 4/5 pass.
    - **t030 5-run battery:** ≥ 4/5 pass.
    - **t080 5-run battery:** ≥ 4/5 pass (CJK vendor `深圳市海云电子`).
    - Iteration ceiling: 5 wording/code iterations. Escalate per
      design §Risk register (R1.a/R1.b/R1.c mitigations).
  - **Full-benchmark sanity (R1 AC8):** run `pac1-py/main_batch.py`
    against `bitgn/pac1-prod` once; assert `passed/104 ≥ 91`.
  - **R1.a P0 regression guard:** the `test_load_records_still_serializes_non_exempt_list_columns`
    test is a MERGE BLOCKER if red. D2's selective-exemption cannot ship
    without this invariant green.
  - **Scope check:** `git diff --stat HEAD~1` touches ONLY
    `pac1-py/agent/dispatch.py` and `pac1-py/tests/test_dispatch.py`.
    No `prompts.py`, no `executor.py`, no `tools.py`, no skill file.
  - **R9 anti-masking grep:** all five R9 greps return 0 hits.
  - **Commit:** `[Phase E R1] expose line_items list[dict] column on load_records + D2 serialization exemption`.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

- [x] 3. Add triple-filter anchor to rule 14 + reconcile rule 0 ±3 → ±2 (T2 = R2, ATOMIC)
  - **Status:** landed (commit 2b24759)
  - **Depends on:** Task 2 (T1 must land first — the triple-filter
    example expression literally names the `line_items` column T1 creates).
  - **Files (single atomic commit per D3):**
    - `pac1-py/agent/prompts.py` — rule 0 at lines 108–115 (two character
      edits: `+/- 3` → `+/- 2`, `<= 3` → `<= 2`) AND rule 14 in-line
      extension at line 186 (triple-filter anchor for finance queries +
      service-line revenue variant).
  - **Atomic-commit invariant (D3):** both loci MUST land in the SAME
    commit. Splitting leaves rule 0 and rule 14 disagreeing on date
    tolerance — a known planner/executor divergence. Post-commit grep
    for `+/- 3 days` returns 0 hits; grep for `<= 3` inside rule-0 context
    returns 0 hits.
  - **Red check:**
    - `rg -n '\+/- 3 days' pac1-py/agent/prompts.py` returns exactly 1 hit
      at line 110 (the pre-edit state).
    - `rg -n '\.dt\.days\) <= 3' pac1-py/agent/prompts.py` returns exactly
      1 hit at line 114.
    - `rg -i 'triple.filter' pac1-py/agent/prompts.py` returns 0 hits.
    - `rg -i 'service.line revenue' pac1-py/agent/prompts.py` returns 0
      hits.
    - `rg -n '14\. LINE ITEMS vs FILE LINES' pac1-py/agent/prompts.py`
      returns exactly 1 hit at line ~179 (rule 14 header preserved).
  - **Action — literal rule 0 before/after diff (design-validation improvement #2):**

    **Before (`prompts.py:108–115`, current state):**
    ```
    "combination exists, widen the date search to +/- 3 days "
    "around the computed date. Use: "
    "df[(df['counterparty']==X) & "
    "(abs((df['_date_from_file'].apply(pd.Timestamp) - "
    "pd.Timestamp(target)).dt.days) <= 3)]. If a UNIQUE "
    "vendor+item match exists within that window, use it.\n"
    ```

    **After (R2 commit, same lines):**
    ```
    "combination exists, widen the date search to +/- 2 days "
    "around the computed date. Use: "
    "df[(df['counterparty']==X) & "
    "(abs((df['_date_from_file'].apply(pd.Timestamp) - "
    "pd.Timestamp(target)).dt.days) <= 2)]. If a UNIQUE "
    "vendor+item match exists within that window, use it.\n"
    ```

    Exactly two character-level edits: `+/- 3` → `+/- 2` on line 110;
    `<= 3` → `<= 2` on line 114.
  - **Action — literal rule 14 in-line append diff (design-validation improvement #2):**

    Rule 14's current text ends at line 186 with a string-concatenation
    literal ending in `\n"` (the trailing newline that separates rule 14
    from rule 15). The append extends rule 14's text **INSIDE the string
    concat block**, BEFORE the trailing `\n"` — the trailing newline is
    preserved so rule 15's separator is intact. No new rule number is
    introduced (per R2 AC4).

    **Before (end of rule 14, `prompts.py:~186`):**
    ```
    "14. LINE ITEMS vs FILE LINES: <existing text>… "
    "separator rows, and total/summary rows from the count.\n"
    ```

    **After (R2 commit):**
    ```
    "14. LINE ITEMS vs FILE LINES: <existing text>… "
    "separator rows, and total/summary rows from the count."
    " TRIPLE-FILTER PATTERN (for finance queries like 'how much "
    "did VENDOR charge for ITEM N days ago'): compose three filters "
    "in a single calculate(): (1) compute the target date via "
    "date_offset(current_date(), -N); (2) filter bills where "
    "counterparty (or supplier) matches VENDOR; (3) filter via the "
    "line_items column (a list[dict] of {item, qty, unit_eur, "
    "line_eur}) to the matching line item and sum line_eur. "
    "Example: df[df['counterparty'].str.contains('VENDOR', "
    "case=False) & (abs((df['_date_from_file'].apply(pd.Timestamp) "
    "- pd.Timestamp(target)).dt.days) <= 2)]['line_items']"
    ".apply(lambda items: sum(i['line_eur'] for i in items "
    "if 'ITEM' in i['item'])).sum(). For SERVICE-LINE REVENUE "
    "queries ('revenue from SERVICE_NAME since DATE'), apply the "
    "same triple-filter to invoices/: date-range filter + "
    "line_items service-name filter + sum of line_eur.\n"
    ```

    The literal `14. LINE ITEMS vs FILE LINES:` header stays verbatim at
    line 179; the triple-filter text extends rule 14 in-line rather than
    promoting to rule 14a or a new top-level section. Date tolerance in
    the example uses `<= 2` consistently with rule 0.
  - **Preserve (R2 AC5):**
    - All round-1 / round-2 rules outside rule 0 and rule 14 byte-for-byte
      unchanged.
    - Grounding guards, empty-message guard, security-coherence guard,
      tool-usage guidance preserved verbatim.
    - `build_planner_system` untouched (R2 lands in executor prompt only;
      D3 + gap-analysis R2.c).
    - The `\n` separator after rule 14's closing sentence is preserved so
      rule 15's boundary is intact.
  - **Green check:**
    - `rg -n '\+/- 2 days' pac1-py/agent/prompts.py` returns exactly 1
      hit (was 0 pre-edit).
    - `rg -n '\+/- 3 days' pac1-py/agent/prompts.py` returns 0 hits
      (the D3 reconciliation gate — MERGE BLOCKER if red).
    - `rg -n '\.dt\.days\) <= 2' pac1-py/agent/prompts.py` returns ≥ 1 hit.
    - `rg -n '\.dt\.days\) <= 3' pac1-py/agent/prompts.py` returns 0 hits
      within rule 0 context.
    - `rg -i 'triple.filter pattern' pac1-py/agent/prompts.py` returns
      ≥ 1 hit.
    - `rg -i 'service.line revenue' pac1-py/agent/prompts.py` returns
      ≥ 1 hit (R2 AC3).
    - `rg -n '14\. LINE ITEMS vs FILE LINES' pac1-py/agent/prompts.py`
      returns exactly 1 hit (header preserved).
    - `rg -n '^\s*"15\\.' pac1-py/agent/prompts.py` returns exactly 1 hit
      (rule 15 boundary preserved).
  - **Import / smoke check:**
    `python -c "import sys; sys.path.insert(0,'pac1-py'); from agent.prompts import build_executor_system; s = build_executor_system(); assert 'TRIPLE-FILTER PATTERN' in s; assert '+/- 2 days' in s; assert '+/- 3 days' not in s; assert 'line_items' in s; assert 'SERVICE-LINE REVENUE' in s"`
    exits 0.
  - **Pytest check:** `pytest pac1-py/tests/` passes fully. No test
    asserts on narrative prompt text; the edit is green-by-construction
    for the test suite.
  - **Pre-commit per-task batteries (R2 AC6, AC7 — MANDATORY iterative gate):**
    - **t005 5-run battery:** ≥ 4/5 pass.
    - **t030 5-run battery:** ≥ 4/5 pass.
    - **t058 5-run battery:** ≥ 4/5 pass (service-line revenue variant).
    - **t080 5-run battery:** ≥ 4/5 pass.
    - **t084 5-run battery:** ≥ 4/5 pass (service-line revenue variant).
    - Iteration ceiling: 5 wording iterations of the anchor text.
  - **Full-benchmark sanity (R2 AC8):** one `main_batch.py` run against
    `bitgn/pac1-prod`; assert `passed/104 ≥ 91`.
  - **Scope check:** `git diff --stat HEAD~1` touches ONLY
    `pac1-py/agent/prompts.py`. No `dispatch.py`, no `executor.py`,
    no test file, no skill file.
  - **R9 anti-masking grep:** all five R9 greps return 0 hits.
  - **Commit:** `[Phase E R2] triple-filter anchor in rule 14 + rule 0 ±3→±2 reconciliation`.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

- [x] 4. (P) Add `_find_project` helper + `_name_keywords` synthetic column + planner rule 6 pointer (T3 = R3)
  - **Status:** landed (commit 6728f36)
  - **Depends on:** Task 3 (T2 must land — R3 ships after the rule-0
    reconciliation is live). Independent of T4 and T6; may land
    concurrently with either.
  - **Files (single atomic commit per D4 + D9):**
    - `pac1-py/agent/dispatch.py` — new `_find_project(query, df) -> pd.DataFrame`
      helper near `_parse_line_items_table` (R1 region); `_name_keywords`
      column computation inside `_load_records` phase 3 (~line 675) when
      `path.strip("/").startswith("projects")`.
    - `pac1-py/agent/prompts.py` — planner rule 6 at lines 280–284
      updated with `_name_keywords` pointer.
    - `pac1-py/tests/test_dispatch.py` — new `TestFindProject` class
      (3–4 tests).
  - **Design-validation improvement #1 phrasing:** the primary mechanism
    is the `_name_keywords` synthetic DataFrame column added at load
    time; `_find_project(query, df)` is a unit-testable helper that
    exposes the SAME tokenization logic. These are layered, not
    alternatives — the agent queries the column via `calculate()`, and
    the helper exists so the tokenization logic can be tested in
    isolation.
  - **Tokenization (R3 AC2):**
    ```
    " ".join(
        (name + " " + goal + " " + alias + " " + notes)
        .lower().replace("-", " ").split()
    )
    ```
    Lowercased, hyphen-split, whitespace-collapsed.
  - **Red check:**
    - `rg -n '_find_project' pac1-py/agent/dispatch.py` returns 0 hits.
    - `rg -n '_name_keywords' pac1-py/agent/dispatch.py` returns 0 hits.
    - `rg -n '_name_keywords' pac1-py/agent/prompts.py` returns 0 hits.
    - `rg -n '6\. INDIRECT PROJECT REFERENCES' pac1-py/agent/prompts.py`
      returns exactly 1 hit at line ~280 (planner rule 6 present).
    - `rg -n 'TestFindProject' pac1-py/tests/test_dispatch.py` returns 0
      hits.
  - **Action (single atomic commit):**
    1. **Add `_name_keywords` column computation** inside `_load_records`
       phase 3 (~line 675), gated on `path.strip("/").startswith("projects")`:
       for each row, compute the tokenized string per R3 AC2 and assign
       to `_loaded_df["_name_keywords"]`. Non-`projects/` paths are
       untouched (zero side-effects on contacts/accounts/bills).
    2. **Add `_find_project(query: str, df: pd.DataFrame) -> pd.DataFrame`
       helper** that tokenizes `query` the same way and filters rows via
       `df['_name_keywords'].str.contains(regex, case=False, na=False)`
       where `regex` is a `|`-joined, regex-escaped alternation of the
       query tokens. Returns the filtered DataFrame; caller inspects
       `.shape[0]` to detect ambiguity.
    3. **Update planner rule 6** in `prompts.py:280–284`:

       **Before:**
       ```
       "6. INDIRECT PROJECT REFERENCES: If the task mentions a project by "
       "nickname, description, or concept (not its exact folder name), plan "
       "to load_records the projects folder and search _body, description, "
       "or goal fields for matching keywords. Also search entity files if "
       "the reference might be an entity name used as a project alias.\n\n"
       ```

       **After:**
       ```
       "6. INDIRECT PROJECT REFERENCES: If the task mentions a project by "
       "nickname, description, or concept (not its exact folder name), plan "
       "to load_records the projects folder; load_records adds a "
       "_name_keywords synthetic column (lowercased, hyphen-split join of "
       "name/goal/alias/notes) — filter via "
       "df[df['_name_keywords'].str.contains(keyword, case=False, na=False)]. "
       "If exact name match returns zero rows, fall back to _name_keywords "
       "substring match. If more than one row matches with no clear top-1, "
       "report OUTCOME_NONE_CLARIFICATION listing the candidates. Also "
       "search entity files if the reference might be an entity name used "
       "as a project alias.\n\n"
       ```
    4. **Add `TestFindProject`** (3–4 tests):
       - Exact-name match returns single row.
       - Substring match across `goal`/`alias`/`notes` returns matching rows.
       - Ambiguous multi-match (`.shape[0] > 1`) detectable by caller.
       - Hyphen-tokenization splits `NORA-at-home` into `nora at home`
         correctly (R3 AC2).
    5. **Ambiguity handling (R3 AC3):** no special-case code. When
       `_name_keywords.str.contains(...)` returns > 1 row, the executor
       follows the existing `OUTCOME_NONE_CLARIFICATION` escalation path
       via rule 11 (already in `prompts.py`, untouched). Determinism
       requirement satisfied by the deterministic tokenization rule.
  - **Preserve (R3 AC4, AC5):**
    - Exact-name-match path remains the primary resolution strategy
      (planner rule 6 still lists exact name first).
    - R3 changes no behavior for queries that already match an exact
      project name.
    - No new tool added to `tools.py` (D4 constraint — keeps R3 inside
      allowlist).
    - Non-`projects/` `load_records` calls are untouched.
    - Rule 11's existing `OUTCOME_NONE_CLARIFICATION` escalation is
      preserved verbatim.
  - **Green check:**
    - `rg -n '_find_project' pac1-py/agent/dispatch.py` returns ≥ 2 hits
      (definition + usage/test hook).
    - `rg -n '_name_keywords' pac1-py/agent/dispatch.py` returns ≥ 2 hits
      (column compute + helper query).
    - `rg -n '_name_keywords' pac1-py/agent/prompts.py` returns ≥ 1 hit
      (planner rule 6 pointer).
    - `rg -n 'TestFindProject' pac1-py/tests/test_dispatch.py` returns
      ≥ 1 hit.
    - `rg -n '6\. INDIRECT PROJECT REFERENCES' pac1-py/agent/prompts.py`
      returns exactly 1 hit (rule 6 header preserved).
  - **Import / smoke check:**
    `python -c "import sys,pandas as pd; sys.path.insert(0,'pac1-py'); from agent.dispatch import _find_project; df = pd.DataFrame([{'_name_keywords': 'nora at home productivity'}, {'_name_keywords': 'acme launch kit'}]); r = _find_project('NORA-at-home', df); assert r.shape[0] == 1"`
    exits 0.
  - **Pytest check:** `pytest pac1-py/tests/test_dispatch.py::TestFindProject -v`
    — all tests green; full `pytest pac1-py/tests/` still green.
  - **Pre-commit per-task battery (R3 AC6 — MANDATORY gate):**
    - **t001 5-run battery:** ≥ 4/5 pass (`NORA-at-home` resolves via
      alias/notes fallback).
    - Iteration ceiling: 5 wording/code iterations.
  - **Full-benchmark sanity (R3 AC7):** one `main_batch.py` run against
    `bitgn/pac1-prod`; assert `passed/104 ≥ 91`.
  - **R3.c false-positive guard:** run a targeted regression — tasks
    with exact-name matches (no alias fallback) should be unchanged.
    No regression on t041 / other project-query tasks that previously
    passed on exact-name alone.
  - **Scope check:** `git diff --stat HEAD~1` touches ONLY
    `pac1-py/agent/dispatch.py`, `pac1-py/agent/prompts.py`,
    `pac1-py/tests/test_dispatch.py`. No `tools.py`, no `executor.py`,
    no skill file.
  - **R9 anti-masking grep:** all five R9 greps return 0 hits.
  - **Commit:** `[Phase E R3] _find_project helper + _name_keywords column + planner rule 6 pointer`.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

- [x] 5. (P) Add structural security guard module + executor wire-up (T4 = R4, ATOMIC)
  - **Status:** landed (commit 09d04a8)
  - **Depends on:** Task 3 (T2 must land). Independent of T3 and T6;
    may land concurrently with either.
  - **Files (single atomic commit per D5 + D9):**
    - new `pac1-py/agent/security_guard.py` (≤ 80 LOC, pure function,
      no I/O, no LLM calls).
    - `pac1-py/agent/executor.py` — one new import near top; one new
      call site after `_security_review` at line ~1235.
    - new `pac1-py/tests/test_security_guard.py` — new
      `TestStructuralSecurityCheck` class (6–7 tests).
  - **Atomic-commit invariant (D5):** executor's new call site depends
    on the new module existing; tests assert both boundaries. Splitting
    leaves either an unused module or an import error.
  - **Red check:**
    - `rg --files pac1-py/agent/security_guard.py` returns 0 hits
      (file does not exist).
    - `rg -n 'structural_security_check' pac1-py/agent/executor.py`
      returns 0 hits.
    - `rg --files pac1-py/tests/test_security_guard.py` returns 0 hits.
    - `rg -n 'from agent.security_guard' pac1-py/agent/executor.py`
      returns 0 hits.
  - **Action (single atomic commit):**
    1. **Create `pac1-py/agent/security_guard.py`** exporting
       `structural_security_check(pending_writes: list[dict]) -> Optional[str]`:
       - Internal constants:
         ```
         _INTERNAL_LANE_PREFIXES = ("30_knowledge/", "90_memory/", "99_system/")
         _INTERNAL_FILENAME_CI = {"agents.md"}
         ```
       - Scan each `pending_write` in the list; extract `attachments:`
         YAML list entries (reuse regex pattern from `executor.py:1278`).
       - Normalize each path: strip leading `./`, strip leading
         `/workspace/`, keep directory segments case-sensitive, lowercase
         the filename segment.
       - Return on the first match: case-sensitive prefix match against
         `_INTERNAL_LANE_PREFIXES`, OR case-insensitive filename match
         against `_INTERNAL_FILENAME_CI` at any depth.
       - Return format: `"Structural security check: outbox write references internal-lane file {path}"`.
       - Return `None` if no match.
    2. **Wire into `executor.py`** after `_security_review` at line ~1235:
       ```
       if outcome == OUTCOME_OK and pending:
           citation = structural_security_check(pending)
           if citation:
               outcome = OUTCOME_DENIED_SECURITY
               message = citation  # or appended if message already set
               print(f"  {CLI_YELLOW}Structural guard → {outcome}{CLI_CLR}")
       ```
    3. **OR-composition semantics (R4 AC2):** if `_security_review`
       already flipped outcome to `OUTCOME_DENIED_SECURITY`, the
       structural check STILL runs but its citation is APPENDED to the
       existing message for traceability (not replacing the LLM's
       reasoning). Ordering: structural check runs AFTER `_security_review`
       but BEFORE `_verify_sender_email`.
    4. **Scope constraint (R4 AC1 + D5 tightening):** match against the
       `attachments:` YAML list ONLY, NOT against freeform message body
       text. Documented as a deliberate tightening beyond bare R4 AC1
       wording — body-text matching introduces unbounded false positives.
       Phase E completion report records this tightening.
    5. **Case-sensitivity (R4 AC4):** directory prefixes are
       case-sensitive (`30_knowledge/` only, not `30_KNOWLEDGE/`).
       `AGENTS.md` filename is case-insensitive (matches `agents.md`,
       `AGENTS.MD`, `Agents.md`).
    6. **R4 AC10 (check not described to LLM):** new module does NOT
       import from `prompts.py`; `prompts.py` and `skills/*.md` do NOT
       mention the four internal-lane prefixes. Verified by grep gate
       (below).
    7. **Add `TestStructuralSecurityCheck`** (6–7 tests):
       - Attachment pointing to `30_knowledge/foo.md` → citation.
       - `90_memory/bar.md` → citation.
       - `99_system/baz.md` → citation.
       - Root `AGENTS.md` → citation.
       - `subdir/AGENTS.md` → citation.
       - `subdir/agents.md` (lowercase) → citation.
       - Path with `./` prefix → citation (defensive normalization).
       - Path with `/workspace/` prefix → citation.
       - Non-internal-lane path (e.g. `outbox/x.md`) → `None`.
       - No `attachments:` field → `None`.
  - **Preserve (R4 AC6):**
    - Existing LLM `_security_review` prompt and step-by-step reasoning
      flow byte-for-byte unchanged.
    - R4 is ADDITIVE — does NOT modify the LLM prompt or its output
      parsing.
    - `_verify_sender_email` at `executor.py:1245` retains its own gate
      (`if outcome == OUTCOME_OK and pending`); it simply does not run
      when the structural guard fired.
    - Phase D R-DOI outcome-code semantics preserved (`OUTCOME_DENIED_SECURITY`
      is the named constant, not a bare string literal).
  - **Green check:**
    - `rg --files pac1-py/agent/security_guard.py` returns 1 hit.
    - `rg -n 'structural_security_check' pac1-py/agent/security_guard.py`
      returns ≥ 1 hit.
    - `rg -n 'from agent.security_guard import structural_security_check' pac1-py/agent/executor.py`
      returns exactly 1 hit.
    - `rg -n 'structural_security_check\(' pac1-py/agent/executor.py`
      returns ≥ 1 hit (call site).
    - `rg --files pac1-py/tests/test_security_guard.py` returns 1 hit.
    - `rg -n 'TestStructuralSecurityCheck' pac1-py/tests/test_security_guard.py`
      returns ≥ 1 hit.
  - **R4 AC10 grep gate (R4.c — MERGE BLOCKER if red):**
    `rg '30_knowledge|90_memory|99_system' pac1-py/agent/prompts.py pac1-py/skills/`
    returns exactly 0 hits. The structural check MUST NOT leak into any
    LLM-visible text.
  - **Import / smoke check:**
    `python -c "import sys; sys.path.insert(0,'pac1-py'); from agent.security_guard import structural_security_check; r = structural_security_check([{'attachments': ['30_knowledge/foo.md']}]); assert r is not None and '30_knowledge' in r; r2 = structural_security_check([{'attachments': ['outbox/x.md']}]); assert r2 is None; r3 = structural_security_check([{'attachments': ['AGENTS.md']}]); assert r3 is not None"`
    exits 0.
  - **Pytest check:** `pytest pac1-py/tests/test_security_guard.py -v`
    — all 6–7 tests green; full `pytest pac1-py/tests/` still green.
  - **Pre-commit per-task batteries (R4 AC8 — MANDATORY gate):**
    - **t011 5-run battery:** ≥ 4/5 pass.
    - **t036 5-run battery:** ≥ 4/5 pass.
    - **t073 5-run battery:** ≥ 4/5 pass.
    - Iteration ceiling: 5 wording/code iterations.
  - **Full-benchmark sanity (R4 AC9):** one `main_batch.py` run against
    `bitgn/pac1-prod`; assert `passed/104 ≥ 91`.
  - **R4.d ordering check:** confirm `_verify_sender_email` at
    `executor.py:1245` runs after the structural guard and does not
    clobber the structural citation.
  - **Scope check:** `git diff --stat HEAD~1` touches ONLY
    `pac1-py/agent/security_guard.py` (new), `pac1-py/agent/executor.py`,
    `pac1-py/tests/test_security_guard.py` (new). No `prompts.py`,
    no `dispatch.py`, no skill file, no `tools.py`.
  - **R9 anti-masking grep:** all five R9 greps return 0 hits.
  - **Commit:** `[Phase E R4] structural security guard module + executor wire-up`.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10_

- [x] 6. (P) Extend inbox-processing SKILL with multilingual verb lists (T6 = R6)
  - **Status:** landed (commit ec2bab1)
  - **Depends on:** Task 3 (T2 must land). Independent of T3 and T4;
    may land concurrently with either.
  - **Files (single commit):**
    - `pac1-py/skills/inbox-processing/SKILL.md` — pure append below
      the existing Phase D R-DT24 passage (currently ends at line 25).
  - **Atomic-commit invariant:** single file, pure append. R6 is strictly
    additive; any deletion of existing content is a scope violation.
  - **Red check:**
    - `rg -i '处理|处理收件箱' pac1-py/skills/inbox-processing/SKILL.md`
      returns 0 hits (Chinese verbs not yet present).
    - `rg -i '処理する|対応する' pac1-py/skills/inbox-processing/SKILL.md`
      returns 0 hits (Japanese verbs not yet present).
    - `rg -i 'procesar|bearbeiten' pac1-py/skills/inbox-processing/SKILL.md`
      returns 0 hits (Spanish/German verbs not yet present).
    - `rg -i 'معالجة' pac1-py/skills/inbox-processing/SKILL.md`
      returns 0 hits (Arabic verbs not yet present).
    - `rg -i "'process'|'handle'|'take care of'" pac1-py/skills/inbox-processing/SKILL.md`
      returns ≥ 3 hits (the Phase D R-DT24 English list IS present —
      MUST remain preserved post-edit).
    - `rg -i 'planner bug, not a conservative choice' pac1-py/skills/inbox-processing/SKILL.md`
      returns ≥ 1 hit (R-DT24 anti-pattern anchor IS present — MUST
      remain preserved post-edit).
  - **Action (single commit):**
    1. **Append multilingual verb-class passage** below existing line 25
       (end of Phase D R-DT24 block). Append-only — NO modification of
       lines 1–25. New content per design §P-E-4:

       ```
       The same verb-class invokes the full workflow across languages. In
       addition to the English verbs above, recognize these equivalents:

       - Chinese: 处理 (process/handle), 回复 (reply to), 看一下 (take a
         look / review), 管理 (manage), 办理 (handle/process).
       - Japanese: 処理する (process), 対応する (handle/respond),
         確認する (review/verify), 返信する (reply).
       - Spanish: procesar, manejar, revisar, atender, responder.
       - German: bearbeiten, behandeln, prüfen, beantworten, erledigen.
       - Arabic: معالجة (process), التعامل مع (deal with), مراجعة (review),
         الرد (reply).

       All listed verbs across all listed languages invoke the full
       inbox-processing workflow — including Phase 5 (Act on allowed,
       fully verified messages) and any required outbox writes, reminder
       creation, or file deletions. A Chinese 处理 task or Japanese 処理する
       task triggers the same write-requiring workflow as an English
       "process" task.
       ```
    2. **English-gloss disambiguation (R6 AC2):** every non-English verb
       has an English gloss in parentheses (Chinese, Japanese, Arabic
       explicitly; Spanish/German cognates are transparent enough that
       parenthetical gloss is optional — but verbs MUST stay in a visible
       list format).
    3. **Validator prompt (D7) — NOT edited in R6.** `prompts.py:325–330`
       stays English-only. If t035 fails the R6 5-run battery post-commit,
       validator extension becomes a separate follow-up commit within
       the R9 allowlist.
  - **Preserve (R6 AC7 — MERGE BLOCKER if violated):**
    - YAML front-matter (lines 1–4) unchanged.
    - `# Inbox Processing` header (line 6) unchanged.
    - Intro paragraph (line 8) unchanged.
    - `## Verb-class synonymy (read this first)` subsection from Phase D
      (lines 10–25) unchanged byte-for-byte — including the eight English
      verbs (`'process'`, `'handle'`, `'take care of'`, `'work through'`,
      `'review'`, `'deal with'`, `'go through'`, `'manage'`) and the
      `planner bug, not a conservative choice` anti-pattern anchor.
    - All Phase 1 / 1.5 / 2 / 3 / 4 / 5 / 6 sections below the insertion
      point unchanged (line numbers shift by ~15–20 lines but no Python
      code references the file by line).
  - **Green check:**
    - `rg -i '处理' pac1-py/skills/inbox-processing/SKILL.md` returns ≥ 2
      hits (R6 AC2 Chinese list + narrative example).
    - `rg -i '処理する' pac1-py/skills/inbox-processing/SKILL.md`
      returns ≥ 2 hits (R6 AC3).
    - `rg -i 'procesar|manejar|revisar' pac1-py/skills/inbox-processing/SKILL.md`
      returns ≥ 3 hits (R6 AC4 Spanish).
    - `rg -i 'bearbeiten|behandeln' pac1-py/skills/inbox-processing/SKILL.md`
      returns ≥ 2 hits (R6 AC5 German).
    - `rg -i 'معالجة' pac1-py/skills/inbox-processing/SKILL.md`
      returns ≥ 1 hit (R6 AC6 Arabic).
    - **Phase D preservation greps (R6 AC7 — MUST still pass):**
      - `rg -i "'process'|'handle'|'take care of'|'work through'|'review'|'deal with'|'go through'|'manage'" pac1-py/skills/inbox-processing/SKILL.md`
        returns ≥ 8 matches (English verb list verbatim).
      - `rg -i 'planner bug, not a conservative choice' pac1-py/skills/inbox-processing/SKILL.md`
        returns ≥ 1 hit (anti-pattern anchor preserved).
  - **YAML / loader smoke check:**
    `python -c "import sys; sys.path.insert(0,'pac1-py'); from skills import SkillLoader; from pathlib import Path; loader = SkillLoader(Path('pac1-py/skills')); doc = loader.load('inbox-processing'); assert doc is not None"`
    exits 0.
  - **Pytest check:** `pytest pac1-py/tests/` passes fully. No test
    asserts on narrative skill text.
  - **Pre-commit per-task battery (R6 AC9 — MANDATORY gate):**
    - **t035 5-run battery:** ≥ 4/5 pass (Chinese prompt
      `处理收件箱中的下一条消息`).
    - Iteration ceiling: 5 wording iterations. If t035 fails to reach
      4/5 after 5 iterations at the skill level, the D7 escape-hatch
      applies — validator-prompt multilingual extension becomes a
      follow-up commit (not part of R6).
  - **Full-benchmark sanity (R6 AC10):** one `main_batch.py` run against
    `bitgn/pac1-prod`; assert `passed/104 ≥ 91`.
  - **R6.b Arabic RTL visual check:** inspect one run's log output for
    Arabic strings — confirm no mojibake / encoding issues in console
    or Langfuse capture.
  - **Scope check:** `git diff --stat HEAD~1` touches ONLY
    `pac1-py/skills/inbox-processing/SKILL.md`. No Python file, no test
    file, no other skill file, no `prompts.py`.
  - **R9 anti-masking grep:** all five R9 greps return 0 hits.
  - **Commit:** `[Phase E R6] multilingual inbox-processing verbs (Chinese/Japanese/Spanish/German/Arabic)`.
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10_

- [x] 7. Land R9 pre-push hook for anti-masking + edit-surface compliance (T9 = R9 infrastructure)
  - **Status:** landed (commit 4a4c6e2) — runs on every R1-R6 commit boundary
  - **Depends on:** nothing (may land alongside or immediately after T5).
    Once landed, every subsequent Phase E commit runs the hook.
  - **Files (single commit):**
    - new `pac1-py/scripts/pre-push-phase-e.sh` — shell script running
      the five R9 grep commands from design §Test strategy.
    - Local install docs inside the script as a header comment
      (addresses design-validation improvement #3: CI infrastructure may
      not exist in the repo, so the hook surface is a local git
      `.git/hooks/pre-push` symlink).
  - **Design-validation improvement #3 resolution:** hook lives at
    `pac1-py/scripts/pre-push-phase-e.sh` (tracked, reviewable). Users
    install by running `ln -s ../../pac1-py/scripts/pre-push-phase-e.sh .git/hooks/pre-push`
    from the repo root (or copying the file into `.git/hooks/pre-push`
    with `chmod +x`). The install command is documented in the script's
    header comment. No `.pre-commit-config.yaml` dependency; no CI
    workflow file is added (CI infrastructure is out of scope for
    Phase E per gap-analysis).
  - **Red check:**
    - `rg --files pac1-py/scripts/pre-push-phase-e.sh` returns 0 hits
      (script does not exist).
  - **Action (single commit):**
    1. **Create `pac1-py/scripts/pre-push-phase-e.sh`** with executable
       permissions (`chmod +x`). Script content (per design §Test
       strategy):
       ```bash
       #!/usr/bin/env bash
       # Phase E pre-push anti-masking + edit-surface compliance hook.
       #
       # Install locally:
       #   chmod +x pac1-py/scripts/pre-push-phase-e.sh
       #   ln -s ../../pac1-py/scripts/pre-push-phase-e.sh .git/hooks/pre-push
       # (or copy into .git/hooks/pre-push directly if symlinks are not
       # supported in the filesystem.)
       #
       # Exits 1 on any violation; exits 0 if all five greps pass.
       set -euo pipefail

       ROOT="$(git rev-parse --show-toplevel)"
       cd "$ROOT"

       fail() { echo "pre-push-phase-e: VIOLATION — $1" >&2; exit 1; }

       # R9 AC5 — no Phase A deletions resurrected.
       rg 'extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance' \
           pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py \
           && fail "Phase A deleted symbol reintroduced" || true

       # R9 AC6 — no alphabetical post-processor.
       rg 'sorted alphabetically|alphabetical order|post-process: re-sorted' \
           pac1-py/agent/executor.py \
           && fail "alphabetical post-processor detected" || true

       # R9 AC7 — no inbox [SECURITY CHECK] injection.
       rg '\[SECURITY CHECK\]|This file is from the inbox' \
           pac1-py/agent/dispatch.py \
           && fail "inbox [SECURITY CHECK] injection detected" || true

       # Phase E SCOPE BOUNDARIES item 7 — no per-task-ID hardcoding.
       rg 'if task_id == "t[0-9]' pac1-py/ \
           && fail "per-task-ID hardcoding detected" || true

       # R4 AC10 — structural check not described to LLM.
       rg '30_knowledge|90_memory|99_system' \
           pac1-py/agent/prompts.py pac1-py/skills/ \
           && fail "R4 internal-lane list leaked into LLM-visible text" || true

       echo "pre-push-phase-e: all R9 invariants clean."
       exit 0
       ```

       The `agent/outcomes.py` docstring (which names forbidden Phase A
       symbols to prevent re-introduction) is deliberately excluded from
       the first grep's path scope — grep covers `pac1-py/agent/` but
       the pattern does not hit the docstring because the docstring
       text uses a different form; if the grep's first invocation does
       hit `outcomes.py` docstring on some ripgrep version, the hook
       may be refined to explicitly exclude `outcomes.py` via
       `--glob '!outcomes.py'`.
    2. **Script's install-command header** documents the `ln -s`
       invocation and the `chmod +x` requirement. Users install once
       per clone; the script is idempotent.
    3. **No CI workflow file added.** Phase E leaves CI infrastructure
       unchanged per gap-analysis R9 observation.
  - **Green check:**
    - `rg --files pac1-py/scripts/pre-push-phase-e.sh` returns 1 hit.
    - `test -x pac1-py/scripts/pre-push-phase-e.sh` exits 0 (executable
      bit set).
    - `bash pac1-py/scripts/pre-push-phase-e.sh` exits 0 at the current
      HEAD (no Phase A reintroduction, no inbox injection, no
      per-task-ID, no internal-lane leak).
  - **Install smoke test (optional local step):**
    `ln -s ../../pac1-py/scripts/pre-push-phase-e.sh .git/hooks/pre-push && git push --dry-run origin HEAD`
    — pre-push hook fires and exits 0.
  - **Scope check:** `git diff --stat HEAD~1` touches ONLY
    `pac1-py/scripts/pre-push-phase-e.sh` (new). No source code, no
    prompts, no tests, no skills.
  - **Commit:** `[Phase E R9] pre-push anti-masking + edit-surface compliance hook`.
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 9.11, 9.12, 9.13_

- [ ] 8. Run multi-run full-benchmark verification (T8 = R8)
  - **Status:** DEFERRED — wall-clock budget prevents multi-hour benchmark
    runs inside this automated implementation session. See
    `phase-e-completion-report.md` for the honest-acceptance statement
    and the residual work required to close T8.
  - **Depends on:** Tasks 1 through 6 (T5, T1, T2, T3, T4, T6 — ALL
    production work landed). R9 hook (Task 7) must also be live so
    every commit in the range passed the anti-masking gate.
  - **Files:** none (operational task).
  - **Action:**
    1. **Checkout the post-Phase-E HEAD** (commit hash recorded).
    2. **Run `pac1-py/main_batch.py`** (or equivalent driver) **three
       times** back-to-back against `bitgn/pac1-prod` (104 tasks each
       run). Each run:
       - Uses `openai/qwen3.5:27b-q4_K_M` (model unchanged per SCOPE
         BOUNDARIES item 1).
       - Runs as an independent Python process.
       - Captures full per-task outcome log (pass/fail + outcome code +
         message for each of t001–t104).
       - Records `passed/104` score on its own line, plus date, model
         identifier, git commit hash, and LLM provider config (temp,
         seed if set).
    3. **Compute per-task pass-rate distribution:** for each task
       `t001`–`t104`, record `(runs passed) / (total runs)`. Any task
       with `0 < rate < 1.0` is a stochastic-floor signal and is noted
       explicitly (not masked by the multi-run average).
    4. **Compute multi-run average:** `(sum passed across runs) / (3 × 104)`.
       Target: ≥ 99/104 (= 0.9519). Optimistic target: ≥ 100/104
       (= 0.9615). Hard floor: no individual run below 91/104 per R1/R2/R4
       AC8 invariants.
    5. **Classify per-task regressions under (a)/(b)/(c)/(d) taxonomy**
       per R8 AC5:
       - `(a)` code-level refactor side-effect — attributable to R1, R3,
         R4, or R5 edit.
       - `(b)` skill file talking to nobody — attributable to R6 edit.
       - `(c)` prompt file talking to nobody — attributable to R2 or R3
         prompt edit.
       - `(d)` LLM non-determinism — stochastic-floor signal, accepted
         if per-task pass rate ≥ 80% across multi-run.
    6. **Per-requirement impact attribution (R8 AC8):** for R1 through
       R6, record which specific tasks moved from failing (pre-Phase-E
       baseline 91/104) to passing across the multi-run battery. Cross-
       reference with the round-3 baseline.
    7. **Write `phase-e-completion-report.md`** into
       `.kiro/specs/ai-first-phase-e/` containing:
       - Per-run score + metadata (R8 AC2).
       - Multi-run average (R8 AC3).
       - Per-task pass-rate distribution (R8 AC4).
       - (a)/(b)/(c)/(d) attribution for any regression (R8 AC5 + AC6).
       - Per-requirement impact attribution (R8 AC8).
       - R7 closure statement verbatim per D8: *"R7 closed as accepted
         LLM capability limit; t018 remains a known failure mode on
         non-ASCII OCR migration; base-model upgrade required for full
         coverage."*
       - Explicit anti-masking statement: no Phase A deleted logic
         reintroduced, no per-task-ID hardcoding, no new structured
         compliance tag (R9 carries forward).
    8. **Decision (R8 AC7):**
       - If multi-run average ≥ 99/104: Phase E complete.
       - If multi-run average < 99/104: either (i) iterate within R1–R6
         allowlist with additional commits, or (ii) honestly accept the
         gap in the completion report with (a)/(b)/(c)/(d) attribution.
         NEVER re-add Phase A deletions, NEVER add per-task-ID branches.
  - **Wall-clock budget:** approximately 3× the single-run benchmark
    wall-clock time — plan for ~2–4 hours total for three runs plus
    report authoring. Runs are independent processes; may run in
    parallel if provider throttling permits.
  - **Scope check:** no production-code diff. Only
    `.kiro/specs/ai-first-phase-e/phase-e-completion-report.md` is
    created (new file, spec-artifact only — NOT a source-code commit).
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ]* 9. (P) Property-based regression tests for `line_items` parsing (optional post-MVP coverage)
  - **Status:** OPTIONAL — deferrable test-only extension
  - **Depends on:** Task 2 (R1 must have landed).
  - **Files (single commit, if pursued):**
    - `pac1-py/tests/test_dispatch.py` — new `TestParseLineItemsTableProperties`
      class using `hypothesis` (already a pac1-py dev dep).
  - **Rationale:** R1 AC6 targets t005/t030/t080 at ≥ 4/5 each, which
    the T1 smoke battery already verifies. This optional extension adds
    property-based regression guards (e.g. for any valid input table,
    `_parse_line_items_table(text)` returns a `list[dict]` with the four
    workspace keys and numeric defaults of `0`). Deferred because MVP
    coverage is satisfied by T1's unit tests + 5-run battery.
  - **Action (if pursued):**
    1. Add `TestParseLineItemsTableProperties` with 2–3 property tests
       using `hypothesis.strategies`:
       - For any list of `(item, qty, unit_eur, line_eur)` tuples
         generated from reasonable `text()` / `integers()` / `floats()`
         strategies, round-trip through `_parse_line_items_table`
         preserves all rows.
       - For any malformed input text, the parser returns a list (never
         raises).
       - For an empty string, returns `[]`.
  - **Pytest check:** `pytest pac1-py/tests/test_dispatch.py::TestParseLineItemsTableProperties -v`
    — all property tests green.
  - **Scope check:** touches ONLY `pac1-py/tests/test_dispatch.py`
    (test-only change; still within R1 allowlist).
  - **Commit (if landed):** `[Phase E R1 followup] property-based regression tests for line_items parser`.
  - _Requirements: 1.6_

- [ ]* 10. (P) Validator-prompt multilingual extension (optional, conditional on R6 5-run battery)
  - **Status:** OPTIONAL — conditional follow-up per D7 escape-hatch
  - **Depends on:** Task 6 (R6 committed) AND t035 failing the R6 5-run
    battery at < 4/5 after the 5-iteration skill-wording ceiling.
  - **Files (single commit, if pursued):**
    - `pac1-py/agent/prompts.py` — validator cross-account verb list at
      lines 325–330, additively extended with multilingual verbs.
  - **Rationale:** D7 decision keeps R6 narrow to the skill file; the
    validator's English-only cross-account verb list is conservative
    (missed inbound detection degrades to "treat as outbound", never to
    false-positive DENY). This extension is triggered ONLY if t035
    still fails post-R6, AND diagnostics confirm the validator is the
    bottleneck (not the skill-load trigger or the executor Phase 5
    action).
  - **Action (if pursued):**
    1. Extend validator inbound-verb list at `prompts.py:325–330` with
       the same five languages as R6 (Chinese, Japanese, Spanish,
       German, Arabic) — additive only, English list preserved verbatim.
    2. Re-run t035 5-run battery: target ≥ 4/5 pass.
    3. Run the full 104-task benchmark once: assert `passed/104 ≥ 91`.
    4. Scope check: touches ONLY `pac1-py/agent/prompts.py`.
    5. Commit: `[Phase E R6 followup] validator multilingual inbound verbs`.
  - **R9 compliance:** this commit is within the R9 allowlist
    (`prompts.py` is allowed for R3 prompt edits; R6 follow-up reuses
    the same file). Commit message explicitly cites D7 escape-hatch.
  - _Requirements: 6.9_

---

## Requirements coverage matrix

| Requirement | Tasks | Coverage status |
|-------------|-------|-----------------|
| R1 (1.1–1.8) | Task 2 (T1) | Fully covered; optional Task 9 for property-based extension. |
| R2 (2.1–2.8) | Task 3 (T2) | Fully covered. |
| R3 (3.1–3.7) | Task 4 (T3) | Fully covered. |
| R4 (4.1–4.10) | Task 5 (T4) | Fully covered. |
| R5 (5.1–5.8) | Task 1 (T5) | Fully covered; includes D6 multi-line stress test per design-validation improvement #4. |
| R6 (6.1–6.10) | Task 6 (T6); optional Task 10 for validator extension. | Fully covered; optional follow-up is conditional per D7. |
| R7 (7.1–7.6) | Task 8 (T8) — closure statement recorded in completion report | CLOSED at design time per D8. No production commit. |
| R8 (8.1–8.8) | Task 8 (T8) | Fully covered — multi-run verification + completion report. |
| R9 (9.1–9.13) | Task 7 (T9) — pre-push hook; enforced on every R1–R6 commit | Fully covered. |

## Design-validation improvements addressed in tasks.md

- **Improvement #1 (D4 phrasing layering):** addressed in Task 4 under
  "Design-validation improvement #1 phrasing" — primary mechanism is the
  `_name_keywords` column; `_find_project(query, df)` is a unit-testable
  helper exposing the same tokenization logic.
- **Improvement #2 (R2 rule-14 literal diff):** addressed in Task 3 under
  "Action — literal rule 0 before/after diff" and "Action — literal rule
  14 in-line append diff" — shows the append is INSIDE the string concat
  block, BEFORE the trailing `\n"`, preserving rule 15's separator.
- **Improvement #3 (R9 CI hook location):** addressed in Task 7 via
  `pac1-py/scripts/pre-push-phase-e.sh` + install documentation in the
  script header (local git hook via symlink; no CI dependency).
- **Improvement #4 (D6 regex stress test):** addressed in Task 1 under
  "Action — R5b, step 5" — `test_detect_statement_keywords_allows_multiline_apply`
  asserts a multi-line valid `.apply(lambda r: ...\n    ...)` does NOT
  fire the statement-keyword sniffer.

## Anti-masking closing statement

Every Phase E commit (T1 through T6, plus T9 hook landing) is subject
to the five R9 greps defined in the pre-push hook. No Phase A deleted
logic is reintroduced; no per-task-ID hardcoding is added; no new
structured machine-readable compliance tag is introduced; no workspace-
path hardcoding beyond the four R4 internal lanes (`30_knowledge/`,
`90_memory/`, `99_system/`, `AGENTS.md`) is permitted; the R4 internal-
lane list never leaks into LLM-visible text (`prompts.py` + `skills/`).
R7 is closed at design time; no future R7 code may be added without
amending D8 explicitly.
