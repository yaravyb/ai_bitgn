# Phase E Design — pac1-prod Hardening for 95%+ Bench Score

## Overview

Phase E is a **narrow, brownfield tightening pass** layered on top of the Phase D outcome-protocol refactor. The `Bootstrap → Planner → Executor → Security Guard → Validator → Apply Writes → Submit` pipeline is preserved byte-for-byte; Phase E adds two deterministic helpers (`_parse_line_items_table` in `dispatch.py`, `structural_security_check` in a new `agent/security_guard.py`), one deterministic project-lookup helper (`_find_project` in `dispatch.py`), one narrower error-handling branch (`_safe_calculate` SyntaxError hint in `dispatch.py`), one tool-schema rewrite (`calculate` in `tools.py`), three prompt anchors (executor rule 14 extension for the triple-filter pattern and rule 0 date-tolerance reconciliation in `prompts.py`), and one skill-file extension (multilingual verb list in `inbox-processing/SKILL.md`). R7 (OCR byte-for-byte preservation) is **closed at design time as an accepted LLM capability limit** per SCOPE BOUNDARIES item 8 (see D8).

The empirical bar inherits Phase D's multi-run convention: per-task 5-run pre-commit batteries per requirement plus a **multi-run full-benchmark average ≥ 99/104 (95.2%)** across ≥ 3 independent `bitgn/pac1-prod` runs, with **no individual run regressing below 91/104**. The R9 anti-masking guard from Phase A R6.4 / Phase C R6 / Phase D R7 carries forward verbatim, plus two new prohibitions introduced in Phase E: (i) no per-task-ID hardcoding (SCOPE BOUNDARIES item 7), (ii) no workspace-path hardcoding beyond the four R4 internal lanes (SCOPE BOUNDARIES item 3).

**Steering directory status:** `.kiro/steering/*.md` remains empty as of Phase E design time (verified). This design operates against the Phase A, Phase C, and Phase D design documents as the de-facto steering pattern; section ordering, Risk Register format, and Edit-Order-and-Smoke-Test-Checkpoints style mirror `ai-first-phase-d/design.md`.

### Goals
- **R1:** Expose a `line_items` column on `load_records` output as `list[dict]` (not JSON string) with workspace-shape keys `{item, qty, unit_eur, line_eur}` (see D1). Land as one atomic commit including test updates.
- **R2:** Add a triple-filter pattern anchor adjacent to executor rule 14 in `prompts.py`, and reconcile rule 0's fuzzy-date window from ±3 days to ±2 days in the same commit (see D3). Depends on R1.
- **R3:** Add a deterministic `_find_project(query)` helper in `dispatch.py` (Option A; see D4) that falls back to substring search across `goal`, `alias`, `notes` when exact name-match is empty; return `OUTCOME_NONE_CLARIFICATION` on ambiguous ties.
- **R4:** Add a new `pac1-py/agent/security_guard.py` module exposing `structural_security_check(pending_writes) -> Optional[str]` that deterministically BLOCKs outbox writes whose `attachments` field references `30_knowledge/`, `90_memory/`, `99_system/`, or any `AGENTS.md` (case-insensitive filename only). Compose with the existing LLM `_security_review` via OR (see D5). The structural check is a backstop — it is not described to the LLM (AC10).
- **R5:** Rewrite the `calculate()` tool-schema description in `tools.py` to explicitly prohibit Python statements, and add a `SyntaxError`-specific hint in `_safe_calculate` (`dispatch.py`). Also add a lightweight statement-keyword sniffer (see D6) that emits the same hint proactively when the expression string matches `^\s*(import |def |for |while |class |async )` or contains `;` with non-string context.
- **R6:** Extend the inbox-processing SKILL verb-class passage with Chinese, Japanese, Spanish, German, and Arabic verb lists, preserving the Phase D R-DT24 English list verbatim. Validator prompt (`prompts.py:325-330`) is **not** edited in Phase E (see D7).
- **R7:** Closed at design time as "accepted LLM capability limit" per AC3/AC5 (see D8). t018 remains a known failure pending base-model upgrade.
- **R8 (multi-run verification):** Execute the full 104-task `bitgn/pac1-prod` benchmark ≥ 3 times after R1–R6 land; compute the multi-run average with per-task pass-rate distribution and (a)/(b)/(c)/(d) attribution. Target ≥ 99/104 averaged (optimistic ≥ 100/104).
- **R9 (anti-masking):** Carry forward Phase A R6.4 / Phase C R6 / Phase D R7 verbatim; enforce the Phase E edit-surface allowlist (see D9, which includes matching test files for R1 and `tools.py` for R5).

### Non-Goals (explicitly deferred or excluded)
- **No base-model upgrade** (qwen3.5:27b-q4_K_M → larger). The remaining ~3% long-tail is accepted as base-model capability limit.
- **No new structured machine-readable compliance tag** under any name. Phase C's D2 decision (narrative reasoning over structured tags) carries forward unchanged.
- **No workspace-path hardcoding beyond the four R4 internal lanes** (`30_knowledge/`, `90_memory/`, `99_system/`, `AGENTS.md`).
- **No pipeline restructuring.** All Phase E changes are local to individual stages.
- **No re-introduction of Phase A deletions** (`extract_decision_outcome`, `plan_compliance` / `_compliance` / `set_compliance` / `get_compliance`, alphabetical post-processor, inbox `[SECURITY CHECK]` injection).
- **No benchmark data edits.** Phase E tunes the agent to the benchmark, not the benchmark itself.
- **No per-task-ID branches** (`if task_id == "tNNN": ...`).
- **No OCR byte-for-byte preservation pursued in Phase E** (R7 closed at design time per D8).
- **No new tools.** R3's fallback is a helper inside `dispatch.py`, not a new tool schema in `tools.py` (see D4).
- **No validator prompt edit for R6.** The validator's English-only verb enumeration at `prompts.py:325-330` stays as-is (see D7).

## Architecture

### Pipeline shape (unchanged from Phase D)

```mermaid
graph LR
    Bootstrap --> Planner
    Planner --> Executor
    Executor --> SecurityGuard
    SecurityGuard --> Validator
    Validator --> ApplyWrites
    ApplyWrites --> CrossRef
    CrossRef --> Submit
```

All seven stages remain in their current files. Phase E inserts at seven specific points inside this shape, none of which change the pipeline graph:

| # | Insertion point | File | Stage | Requirement |
|---|-----------------|------|-------|-------------|
| 1 | New helper `_parse_line_items_table(text)` | `agent/dispatch.py` | Executor (load_records) | R1 |
| 2 | `_load_records` phase 2 call + serialization-exemption list | `agent/dispatch.py` | Executor (load_records) | R1 |
| 3 | Executor rule 14 extension (triple-filter anchor) + rule 0 date-tolerance edit | `agent/prompts.py` | Planner/Executor (prompt) | R2 |
| 4 | New helper `_find_project(query)` + ambiguity-tie handling | `agent/dispatch.py` | Executor (tool path) | R3 |
| 5 | New module `agent/security_guard.py` + call site after `_security_review` | `agent/executor.py` | Security Guard | R4 |
| 6 | `calculate()` tool-schema description rewrite + `_safe_calculate` SyntaxError branch + statement-keyword sniffer | `tools.py`, `agent/dispatch.py` | Executor (tool) | R5 |
| 7 | Verb-class passage extension | `skills/inbox-processing/SKILL.md` | Executor (skill-load) | R6 |

### Module boundaries (one new file)

- **New:** `pac1-py/agent/security_guard.py` — exports `structural_security_check(pending_writes: list[dict]) -> Optional[str]` returning `None` (pass) or a citation string (for use by the caller to build the `OUTCOME_DENIED_SECURITY` message). The module is ≤ 80 LOC, pure function, no I/O, no LLM calls. Placed alongside `_security_review` in `executor.py` so the two-step guard (LLM then structural, combined OR) is obvious.
- **Extended:** `pac1-py/agent/dispatch.py` — new private helpers `_parse_line_items_table`, `_find_project`, `_detect_statement_keywords`; edits to `_load_records` (serialization-exemption), `_safe_calculate` (SyntaxError branch).
- **Extended:** `pac1-py/agent/prompts.py` — one inline extension to executor rule 14, one one-line edit to rule 0 (±3 → ±2 days).
- **Extended:** `pac1-py/agent/executor.py` — one new import, one new call after `_security_review` at line 1235 (see §Code touchpoints).
- **Extended:** `pac1-py/tools.py` — `calculate` tool description rewrite at lines 157-167 and 173-180.
- **Extended:** `pac1-py/skills/inbox-processing/SKILL.md` — one new sub-paragraph appended below the existing English verb-class passage at lines 10-25.
- **Extended:** `pac1-py/tests/test_dispatch.py` — new test classes for `_parse_line_items_table`, `_find_project`, `_detect_statement_keywords`; update existing `TestAsciiTableParser` only if it asserts on columns now exempt from JSON serialization.

### Technology Stack (layers impacted)

| Layer | Choice / Version | Role in Feature | Notes |
|-------|------------------|-----------------|-------|
| CLI / Agent runtime | Python 3.11+ (project baseline) | Hosts dispatch, executor, prompts edits | Unchanged |
| Tooling | pandas (existing), `dateutil` (existing), PyYAML (existing) | R1 parser uses PyYAML for frontmatter; R2 executor expressions use pandas `.apply(lambda ...)` | No new deps |
| LLM provider | `litellm` + `openai/qwen3.5:27b-q4_K_M` | Phase E does not upgrade the model (SCOPE BOUNDARIES item 1) | Model pinning stays |
| Benchmark | `bitgn/pac1-prod` (104 tasks, randomized variants per run) | R8 multi-run verification harness | Operational only — no code change |
| Observability | Existing Langfuse hook (unchanged) | No Phase E changes | Per Phase-E modular-refactor memo: keep as-is |

No new external dependencies. All Phase E code uses the Python standard library plus libraries already in the project's virtual env.

## Design decisions (binding inputs for implementation)

Phase E design surfaced nine decisions that need explicit resolution before implementation. D1–D3 resolve the three open questions called out in the gap analysis; D4–D9 resolve secondary load-bearing choices surfaced during discovery.

### D1. Line-item schema — adopt workspace shape `{item, qty, unit_eur, line_eur}` verbatim (R1)

**Problem:** Requirement R1 AC1 names the keys `{item, qty, price, line_total}`. The actual `bitgn/pac1-prod` workspace uses `{item, qty, unit_eur, line_eur}` — verified at `pac1-py/tests/test_dispatch.py:235` (existing test fixture uses these exact keys) and at `pac1-py/full_pac1_prod.txt:1409, 1896` (live task traces). Three options:
1. **Rename at parse time** — parser emits `{item, qty, price, line_total}` regardless of source; R2's example expression uses the requirement keys.
2. **Preserve workspace keys verbatim** — parser emits `{item, qty, unit_eur, line_eur}` exactly as the workspace has them; R2's example expression uses the workspace keys.
3. **Dual-namespace** — parser emits both sets of keys, caller picks.

**Decision: Option 2 — preserve workspace keys verbatim.** The parser emits `{"item": str, "qty": int|float, "unit_eur": float, "line_eur": float}`. R2's triple-filter example expression uses `line_eur` (not `line_total`) and `unit_eur` (not `price`). R1 AC1 is treated as an inexact prescription of *intent* (a 4-field dict with those 4 semantic fields) and the field names are aligned to the workspace reality at implementation time.

**Rationale:**
- The workspace schema is the ground truth. Renaming at parse time creates a lie: the agent sees `price` in the DataFrame but the source file uses `unit_eur`, which breaks debuggability and contradicts the requirement's "preserve the existing contract" ethos (R1 AC5).
- The existing `TestAsciiTableNormalizer` fixture already uses `unit_eur`/`line_eur` — renaming would force a test rewrite that adds no value.
- Dual-namespace doubles memory per DataFrame row and invites the LLM to pick the wrong one.
- R2's example expression must use these exact keys; the R2 edit lands in the same commit as R1's test update, so key-name drift is impossible by construction.

**Requirement-text reconciliation:** R1 AC1 and R2 AC1/AC2 examples are treated as *semantic* specifications (4 fields: line-item name, quantity, per-unit price, line total). The implementation names them `item`, `qty`, `unit_eur`, `line_eur`. The Phase E completion report records this decision explicitly.

**Null-safety:** Missing numeric fields default to `0` (not `None`) so `sum(i['line_eur'] for i in items)` never blows up. String field `item` defaults to the empty string. Any row whose cells don't cleanly parse as 4-5 columns is dropped from the list (not included as a garbled dict).

### D2. `_load_records` JSON-serialization — carve selective exemption for `line_items` only (R1)

**Problem:** `dispatch.py:676-681` auto-serializes any list/dict DataFrame column to JSON strings so downstream `df['col'] == "{...}"` filters work. R1 AC4 requires `line_items` to remain as `list[dict]` for `.apply(lambda items: ...)` patterns. Three options:
1. **Carve a selective exemption** — skip serialization for a known exempt list (`line_items`) only.
2. **Drop the serialization pass entirely** — all list/dict columns stay as native Python types.
3. **Re-architect** — move serialization to a per-column opt-in flag.

**Decision: Option 1 — selective exemption list.** Modify `dispatch.py:676-681` to read:

```python
_LIST_COLUMN_EXEMPT = {"line_items"}   # module-level constant
for col in _loaded_df.columns:
    if col in _LIST_COLUMN_EXEMPT:
        continue  # R1: preserve list[dict] for .apply() queries
    if _loaded_df[col].apply(lambda x: isinstance(x, (list, dict))).any():
        _loaded_df[col] = _loaded_df[col].apply(
            lambda x: json.dumps(x) if isinstance(x, (list, dict)) else x
        )
```

**Rationale:**
- Minimum blast radius. Option 2 would silently change the type of every existing list/dict column (e.g. `attachments:` lists) and risks breaking downstream `calculate()` expressions that assume JSON-string semantics. Regression risk is high and distributed across many tests.
- Option 3 adds a per-column flag that nothing else consumes — premature abstraction. Exemption list is the narrowest possible change that satisfies R1 AC4 and R1 AC5 jointly.
- The exemption list is a module-level constant, so R7 or a future phase can extend it without touching the loop body.

**Test invariant:** A new test `test_load_records_preserves_line_items_list_dict` asserts that after a synthetic workspace parse, `type(df['line_items'].iloc[0])` is `list` and `type(df['line_items'].iloc[0][0])` is `dict`. A second test `test_load_records_still_serializes_non_exempt_list_columns` asserts that a synthetic `attachments` column with list values is still JSON-stringified. Both tests live in the same R1 commit.

### D3. R2 vs executor rule 0 date-tolerance reconciliation — pick ±2 days, update both loci (R2)

**Problem:** `prompts.py:110` currently prescribes `±3 days` ("widen the date search to +/- 3 days around the computed date"). R2 AC1 prescribes `±1-2 days`. Must be reconciled in the same commit (R2's commit).

**Decision: pick ±2 days, update both loci.** R2's new anchor text uses `≤ 2` explicitly. Rule 0's existing `<= 3` at `prompts.py:110-114` is edited to `<= 2` in the same R2 commit.

**Rationale:**
- Failure data: t005/t030/t080 failures per `pac1-prod-improvement-plan.md` show the bill is typically within 0-2 days of the computed target; ±3 admits noise without adding recall (the off-by-one and off-by-two cases dominate; no real failure needs ±3).
- ±1 is too tight given occasional date-parsing noise around month boundaries in the filename-based `_date_from_file` column.
- ±2 is the intersection of R2's "±1-2 day" range. Sticking to the upper bound of R2 AC1 keeps the recall window wide enough for current failures and aligns rule 0 with rule 14's new anchor.
- Keeping the two loci synchronized removes a known divergence that caused planner/executor drift in Phase D.

**Exact edit:** In `prompts.py`, line 110 currently reads `"around the computed date. Use: "` after `"widen the date search to +/- 3 days "`. The edit changes `+/- 3` to `+/- 2` at line 110 and changes `<= 3` to `<= 2` at line 114. R2's new rule-14 anchor uses `<= 2` consistently.

### D4. R3 indirect-reference helper — Option A (code-level helper in `dispatch.py`) without new tool (R3)

**Problem:** R3 permits either Option A (code-level helper) or Option B (prompt-only). Option A has a scope concern: if exposed as a new tool (`find_project(query)`), it edits `tools.py`, which is **not** in R3's edit-surface allowlist (flagged by gap analysis).

**Decision: Option A, helper-only — add `_find_project(query)` inside `dispatch.py` as a private helper that is **not** a new tool.** Invocation happens through the existing `load_records('projects/')` call path: when `_load_records` loads `projects/`, it additionally annotates the DataFrame with a `_name_keywords` index (tokenized `name + goal + alias + notes`) as a synthetic column. The executor rule for indirect project references (Option A + Option B light blend) points the LLM at this new column for the fallback; when exact-name `.contains()` returns zero rows, the executor's next `calculate()` uses `_name_keywords.str.contains(...)` to fall back.

Alternative pursued: a fully internal `_find_project` helper that the agent never calls directly — instead, the loader enriches the DataFrame with a queryable `_name_keywords` text column. This keeps all R3 edits in `dispatch.py` + one-line prompt hint in `prompts.py` and avoids `tools.py` entirely.

**Rationale:**
- Stays inside the R3 allowlist (`dispatch.py` + `prompts.py`). No `tools.py` edit needed.
- Deterministic: the `_name_keywords` column is computed the same way on every load; the LLM's `.str.contains(...)` filter on it is as deterministic as any other `calculate()` filter.
- Ambiguous-tie handling per R3 AC3: if `calculate()` returns more than one row with non-zero `.str.contains` matches, the executor follows the existing `OUTCOME_NONE_CLARIFICATION` escalation path (rule 11 already covers this generically). No special-case code.
- Tokenization per R3 AC2: the `_name_keywords` column is `" ".join((name + " " + goal + " " + alias + " " + notes).lower().replace("-", " ").split())` — lowercased, hyphen-split, whitespace-collapsed. `_find_project` exposes the same tokenization logic as a unit-testable helper.
- CJK handling (R3.b risk): hyphen/whitespace splitting does not help CJK — but t080 and t084 are finance triple-filter failures, not indirect-project-reference failures; the CJK cases are covered by R1+R2. t001 is the only R3 target and is pure English/German tokens.

**Edit surface footprint for R3:** `dispatch.py` (new `_find_project` helper, new `_name_keywords` column added in `_load_records` when path startswith `projects/`), `prompts.py` (one-line extension to planner rule 6 naming the `_name_keywords` column).

### D5. R4 structural security guard — new file `agent/security_guard.py` (R4)

**Problem:** R4 permits either inline in `executor.py` or a new `agent/security_guard.py` module.

**Decision: new file `pac1-py/agent/security_guard.py`.** It exports one pure function:

```python
def structural_security_check(pending_writes: list[dict]) -> Optional[str]:
    """Return a citation string if any pending outbox write attaches internal-lane
    files; return None otherwise. Deterministic, no LLM, no I/O."""
```

The function scans `pending_writes`, extracts any `attachments:` YAML block (reusing the existing regex at `executor.py:1278`), normalizes each attachment path (strip leading `./`, strip leading `/workspace/`, lowercase the filename segment but keep the directory segments case-sensitive), and returns on the first match against the four internal-lane prefixes (`30_knowledge/`, `90_memory/`, `99_system/`) or the case-insensitive filename `AGENTS.md` at any depth. Return format: `"Structural security check: outbox write references internal-lane file {path}"`.

**Integration in `executor.py`:** after `_security_review` at line 1235, add:

```python
if outcome == OUTCOME_OK and pending:
    citation = structural_security_check(pending)
    if citation:
        outcome = OUTCOME_DENIED_SECURITY
        message = citation  # or appended to existing message
        print(f"  {CLI_YELLOW}Structural guard → {outcome}{CLI_CLR}")
```

**OR semantics (R4 AC2):** the two checks compose with short-circuit OR — if LLM `_security_review` already flipped the outcome to `OUTCOME_DENIED_SECURITY`, the structural check still runs but its citation is appended to the message for traceability (not replacing the LLM's reasoning). This keeps the more informative LLM explanation visible in logs.

**Scope constraint (R4 AC1):** match against the `attachments` YAML list only, NOT against freeform message body text. This is a design-time tightening beyond the bare R4 AC1 wording ("the pending write's `attachments` field (or message body referencing files)"): matching body text introduces unbounded false positives (legitimate discussion of internal lanes), which is a worse regression than the narrow recall loss. The gap-analysis R4.a risk calls this out explicitly; we accept the tightening and note it in the Phase E completion report.

**Case-sensitivity (R4 AC4):** prefix match is case-sensitive (`30_knowledge/` only, not `30_KNOWLEDGE/`). Filename match for `AGENTS.md` is case-insensitive (matches `agents.md`, `AGENTS.MD`, `Agents.md`).

**R4 AC10 (check not described to LLM):** the new module does not import anything from `prompts.py`, and `prompts.py` / any `skills/*.md` file does not mention the four internal-lane prefixes. Verified by grep at commit time.

### D6. R5 statement-keyword sniffer — add a proactive sniffer in `_safe_calculate` (R5)

**Problem:** R5 AC3 requires a SyntaxError-specific hint, but some agent-generated multi-line scripts parse as *valid* Python expressions (e.g. a tuple of generator expressions separated by `,` can look like a single expression). A pure SyntaxError trigger misses these.

**Decision: add a lightweight statement-keyword sniffer** that fires the R5 hint proactively when the expression string matches a statement-starting keyword regex OR contains top-level `;`. The sniffer runs BEFORE `compile(...)` so that even valid-parsing-but-intended-as-script expressions get the hint.

```python
_STATEMENT_RE = re.compile(
    r"(?m)^\s*(import |from |def |class |for |while |async |return )"
    r"|(?m);\s*$"          # semicolon at end of line
    r"|(?:\n[ \t]+[^\s])"   # indentation suggesting a statement block
)

def _detect_statement_keywords(expression: str) -> bool:
    return bool(_STATEMENT_RE.search(expression))
```

The SyntaxError branch in `_safe_calculate` catches the remaining cases (e.g. bare `for x in ...: print(x)` which is a syntax error). Both paths return the same structured hint (R5 AC3 text verbatim).

**False-positive guard (R5.b):** the sniffer runs ONLY when `compile(...)` would otherwise succeed. If the LLM writes a valid but statement-looking expression (e.g. a comprehension whose token `for` triggers the regex), the `compile()` succeeds first and `_detect_statement_keywords` fires the hint — trading a small false-positive rate on valid comprehensions for real coverage of the "multi-line script" failure mode. The hint is informational only; the LLM can retry the same expression if it believes the hint is wrong, and the restricted namespace still computes the valid result. **Mitigation:** the regex is tuned to hit only statement-starting keywords at the beginning of a line (`(?m)^\s*(import |from |def |class |for |while |async |return )`). Plain list comprehensions like `[x for x in records]` do NOT match because `for` is not at the start of a line there. This is verified by a unit test `test_detect_statement_keywords_allows_comprehensions`.

### D7. R6 validator prompt update — skill-only, leave validator English-only (R6)

**Problem:** The validator prompt at `prompts.py:325-330` enumerates English verbs only for its cross-account check. R6 adds multilingual verbs to `inbox-processing/SKILL.md`. If the skill gets Chinese/Japanese/Spanish/German/Arabic verbs but the validator's cross-account check stays English-only, the validator may *fail to recognize* an inbound task in a non-English language and skip its cross-account block.

**Decision: edit only the skill file in R6; leave the validator prompt unchanged.** The validator's cross-account check is a CONSERVATIVE escalation: if it skips (because it doesn't recognize the inbound verb), it treats the task as outbound and performs no cross-account check. That's the safe default — no false-positive CLARIFICATION, no false-positive DENIED_SECURITY. The skill-level multilingual expansion only needs to make the executor *reach* the full workflow (Phase 5, write reminders, etc.); recognizing the task as "inbound" happens in the planner+executor which already handle mixed-language task text via the underlying LLM.

**Rationale:**
- The gap-analysis R6.a concern ("skill file talking to nobody") is mitigated by the planner's language-agnostic behavior: the underlying LLM handles Chinese task text as `inbox-processing`-relevant because the PLANNER_TOOL system prompt uses English but the LLM generalizes.
- Extending the validator verb list to five languages doubles the prompt surface for a check that only matters for one failing task (t035). The marginal recall gain is small; the bloat cost is real.
- If t035 fails the R6 5-run battery (≥ 4/5) AFTER the skill-only edit, we can still edit the validator prompt in a follow-up commit within the R9 allowlist (`prompts.py`). R6 as defined stays skill-only; the validator edit becomes a scope-expansion commit with its own commit message justification per R9 AC11.
- R6 AC7 explicitly says "additive only — preserve Phase D R-DT24 verbatim"; that applies to the skill, not to the validator.

### D8. R7 disposition — close at design time as "accepted LLM capability limit" (R7)

**Problem:** R7 (OCR umlaut byte-for-byte preservation) is marked P4 / optional. AC3 explicitly permits closure if the byte-for-byte copy cannot land as an additive helper in a single commit. Gap analysis (R7.a/R7.b/R7.c) flags three non-trivial risks: (i) detecting "OCR task" without per-task hardcoding, (ii) distinguishing intentional LLM edits from OCR paraphrase drift, (iii) SCOPE BOUNDARIES item 8.

**Decision: close R7 at design time.** The Phase E completion report records:

> R7 closed as accepted LLM capability limit; t018 remains a known failure mode on non-ASCII OCR migration; base-model upgrade required for full coverage.

The design does not allocate any code to R7; no `_byte_for_byte_copy` helper is written; `dispatch.py` is not touched for R7. The R9 anti-masking and edit-surface invariants still cover R7 (no new R7-specific code may be added in a future Phase E commit without amending this design decision explicitly).

**Rationale:**
- R7 fails the single-commit additive-helper bar: detecting OCR tasks requires either task-text sniffing (risks per-task keyword hardcoding, SCOPE BOUNDARIES item 7 violation) or a new tool/flag (risks `tools.py` scope expansion, R9 AC11 violation).
- Expected impact per the plan doc is +0-1 task (t018). Closing R7 sacrifices at most 1 task, well inside the ≥ 99/104 bar (optimistic 100/104; pessimistic 99/104 with R7 closed).
- The R7 AC5 text is pre-written; closure is a single-line record-keeping action.

### D9. Edit-surface allowlist finalization — include test files and `tools.py` for R5 (R9)

**Problem:** R9 AC11 lists the per-requirement edit surfaces. Two gap-analysis findings need explicit incorporation:
1. R1 AC7 requires unit-test updates in `pac1-py/tests/test_dispatch.py`, but R9 AC11's R1 line is "R1 edits `pac1-py/agent/dispatch.py` only".
2. R5 AC1 requires editing `pac1-py/tools.py`, and R9 AC11 correctly lists `tools.py` + `dispatch.py` for R5.

**Decision:** extend the R9 AC11 allowlist at implementation time to say:

- R1: `pac1-py/agent/dispatch.py` **AND `pac1-py/tests/test_dispatch.py`** (for AC7 test-update compliance).
- R3: `pac1-py/agent/dispatch.py` AND `pac1-py/agent/prompts.py` **AND `pac1-py/tests/test_dispatch.py`** (for `_find_project` test).
- R4: `pac1-py/agent/executor.py` AND new `pac1-py/agent/security_guard.py` **AND `pac1-py/tests/` (new `test_security_guard.py`)**.
- R5: `pac1-py/tools.py` AND `pac1-py/agent/dispatch.py` **AND `pac1-py/tests/test_dispatch.py`** (for sniffer test).
- R6: `pac1-py/skills/inbox-processing/SKILL.md` only. (No test updates — SKILL files are narrative.)
- R7: closed; no edits.
- R8: none (operational).

**Rationale:**
- Test files co-evolving with the source code they test is not a scope expansion; R9 AC13 already requires test updates in the same commit as production code. The allowlist is extended to match AC13 explicitly, closing an ambiguity the gap analysis flagged.
- `tools.py` for R5 is already on the R5 line of R9 AC11 — no change needed there; this item is restated only for completeness.
- Every commit-message template for Phase E includes a one-line "edit-surface compliance: allows `file1, file2, ...` per R9 AC11 + D9" statement so grep-verification at CI time is mechanical.

## Data model

### `line_items` column schema (R1 + R2)

After `load_records(path)` returns for a bill/invoice folder, the in-process DataFrame (`_loaded_df`) exposes a new column `line_items` of dtype `object` where each cell is a native Python `list[dict]`.

Each dict conforms to:

| Field | Type | Default when missing | Notes |
|-------|------|----------------------|-------|
| `item` | `str` | `""` | Line item description as it appears in the source table. Non-ASCII preserved verbatim. No paraphrase. |
| `qty` | `int` or `float` | `0` | Parsed from the qty cell. Integer if the cell is pure digits; float if it contains a decimal point. |
| `unit_eur` | `float` | `0.0` | Per-unit price in EUR. |
| `line_eur` | `float` | `0.0` | Line total in EUR. |

**Empty-list contract (R1 AC3):** if a bill file contains neither an ASCII line-items table nor a YAML `line_items` frontmatter list, `line_items = []` (not `None`, not `NaN`, not a missing column). Uniform default enables `df['line_items'].apply(lambda items: any(i['item'] == X for i in items))` without `None`-checks.

**Type contract (R1 AC4):** `type(df['line_items'].iloc[k])` is always `list`. `type(df['line_items'].iloc[k][j])` is always `dict` for valid `k, j`. No pandas `Series`, no numpy arrays. This is guaranteed by D2's serialization exemption.

**YAML frontmatter path (R1 AC2):** when a bill's frontmatter contains a `line_items` (or aliases `lines`, `items`) key as a list of dicts, `_load_records` uses that list verbatim (after a shallow normalization that fills in the four default values for missing keys). The ASCII-body parser is NOT invoked in that case.

**Parser idempotence (R1.b risk mitigation):** if both frontmatter `line_items` AND body ASCII table are present, frontmatter wins. The body parser runs only when frontmatter has no `line_items` key.

### `_name_keywords` synthetic column (R3)

When `_load_records(path)` is called with a path that startswith `projects/`, the resulting DataFrame gains a column `_name_keywords` of dtype `str` per row:

```
_name_keywords = " ".join(
    (str(row.get("name", "")) + " " + str(row.get("goal", "")) + " "
     + str(row.get("alias", "")) + " " + str(row.get("notes", ""))).lower()
     .replace("-", " ").split()
)
```

The LLM's fallback query uses `df[df['_name_keywords'].str.contains(keyword_regex, case=False, na=False)]` where `keyword_regex` is a `|`-joined, regex-escaped version of the query tokens. Ambiguity tie-breaking per R3 AC3 is the executor-rule-level escalation to `OUTCOME_NONE_CLARIFICATION` when `.shape[0] > 1`.

The `_name_keywords` column is **not** added to DataFrames for non-`projects/` paths (zero side effects on other folders).

## Prompt anchors

Phase E touches the executor prompt at three places and the inbox-processing skill at one place. Every edit is shown as a before/after patch.

### P-E-1. Rule 0 fuzzy-date window: ±3 → ±2 days (R2, D3)

**File:** `pac1-py/agent/prompts.py`, lines 108-115.

**Before** (current):
```
"combination exists, widen the date search to +/- 3 days "
"around the computed date. Use: "
"df[(df['counterparty']==X) & "
"(abs((df['_date_from_file'].apply(pd.Timestamp) - "
"pd.Timestamp(target)).dt.days) <= 3)]. If a UNIQUE "
"vendor+item match exists within that window, use it.\n"
```

**After** (R2 commit):
```
"combination exists, widen the date search to +/- 2 days "
"around the computed date. Use: "
"df[(df['counterparty']==X) & "
"(abs((df['_date_from_file'].apply(pd.Timestamp) - "
"pd.Timestamp(target)).dt.days) <= 2)]. If a UNIQUE "
"vendor+item match exists within that window, use it.\n"
```

Two character-level edits: `+/- 3` → `+/- 2`, `<= 3` → `<= 2`.

### P-E-2. Rule 14 triple-filter anchor extension (R2 AC1, AC2, AC3; D3)

**File:** `pac1-py/agent/prompts.py`, inserted between existing rule 14 (line 186) and rule 15 (line 187) as an in-line extension to rule 14, NOT a new top-level rule number (per R2 AC4).

**After** (R2 commit — appended to the end of rule 14's existing text at line 186, before the `\n` that separates rules):
```
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

Placement: appended to the rule 14 text at `prompts.py:186` so the literal English "14. LINE ITEMS vs FILE LINES:" header is preserved verbatim; the new content extends rule 14 in-line rather than introducing a rule 14a or a top-level section.

### P-E-3. Planner rule 6 `_name_keywords` pointer (R3, D4)

**File:** `pac1-py/agent/prompts.py`, line 280-284 (existing planner rule 6 body).

**Before** (current):
```
"6. INDIRECT PROJECT REFERENCES: If the task mentions a project by "
"nickname, description, or concept (not its exact folder name), plan "
"to load_records the projects folder and search _body, description, "
"or goal fields for matching keywords. Also search entity files if "
"the reference might be an entity name used as a project alias.\n\n"
```

**After** (R3 commit):
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

### P-E-4. Multilingual verb-class passage (R6)

**File:** `pac1-py/skills/inbox-processing/SKILL.md`, appended below the existing Phase D R-DT24 passage (currently ends at line 25).

**After** (R6 commit):
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

The Phase D R-DT24 English list and the "review and summarize" anti-pattern anchor (lines 22-25) are preserved verbatim.

## Code touchpoints

Per-requirement file:line before/after. Implementation-level detail is kept tight; full code lives in the implementation commits.

### R1: `pac1-py/agent/dispatch.py`

| Locus | Before | After | Signature |
|-------|--------|-------|-----------|
| New helper, placed between `_parse_ascii_table` (ends ~line 460) and the `_generated_parsers` cache (~line 464) | — | Add `_parse_line_items_table` | `def _parse_line_items_table(text: str) -> list[dict]:` |
| `_load_records` phase 2, inside the `.md/.txt` branch at ~line 606-617 | `record = _parse_yaml_frontmatter(content); ... record = _parse_ascii_table(content)` | After frontmatter parse, if `record` has no `line_items` key, call `_parse_line_items_table(content)` and assign to `record["line_items"]`. If ASCII-table branch taken, also call `_parse_line_items_table` (same source text). In all other cases, default `record["line_items"] = []`. | unchanged outer signature |
| `_load_records` serialization pass at lines 676-681 | Unconditional serialization of any list/dict column | Skip columns in `_LIST_COLUMN_EXEMPT = {"line_items"}` | unchanged outer signature |
| Module-level constant, placed near existing module-level constants (e.g. `_CALC_NAMESPACE` area, ~line 358) | — | `_LIST_COLUMN_EXEMPT: frozenset[str] = frozenset({"line_items"})` | — |

### R2: `pac1-py/agent/prompts.py`

One rule-0 edit (two character changes) and one rule-14 in-line extension. See §Prompt anchors P-E-1, P-E-2.

### R3: `pac1-py/agent/dispatch.py` + `pac1-py/agent/prompts.py`

| Locus | Before | After | Signature |
|-------|--------|-------|-----------|
| New helper in `dispatch.py`, placed near `_parse_line_items_table` | — | `_find_project(query: str, df: pd.DataFrame) -> pd.DataFrame` — filter rows whose `_name_keywords` `str.contains(token1|token2|...)` matches | `def _find_project(query: str, df: pd.DataFrame) -> pd.DataFrame:` |
| `_load_records` phase 3, after DataFrame build (~line 675) | — | If `path.strip("/").startswith("projects")`, compute `_name_keywords` column per row from lowercased+hyphen-split join of `name/goal/alias/notes`. Add to `_loaded_df`. | unchanged outer signature |
| `prompts.py` planner rule 6 at lines 280-284 | Current text (see §Prompt anchors P-E-3 "Before") | Updated text naming `_name_keywords` column (see "After") | — |

### R4: new `pac1-py/agent/security_guard.py` + `pac1-py/agent/executor.py`

| Locus | Before | After | Signature |
|-------|--------|-------|-----------|
| New file `agent/security_guard.py` | — | Module exporting `structural_security_check` + internal constants `_INTERNAL_LANE_PREFIXES = ("30_knowledge/", "90_memory/", "99_system/")` and `_INTERNAL_FILENAME_CI = {"agents.md"}` | `def structural_security_check(pending_writes: list[dict]) -> Optional[str]:` |
| `executor.py` imports (top of file) | — | `from agent.security_guard import structural_security_check` | — |
| `executor.py` line 1234-1241 (after `_security_review`) | `if outcome == OUTCOME_OK and pending: security_override = _security_review(...); if security_override: outcome = security_override` | Extend: after the `_security_review` block, run `structural_security_check(pending)`. If it returns a citation, set `outcome = OUTCOME_DENIED_SECURITY`, append the citation to the existing `message` (or use as `message` if empty), log the structural-guard branch. OR semantics per D5. | — |

### R5: `pac1-py/tools.py` + `pac1-py/agent/dispatch.py`

| Locus | Before | After |
|-------|--------|-------|
| `tools.py` lines 157-167 (calculate `description`) | Short pandas examples | Rewritten per R5 AC1 text: "Evaluate a single Python EXPRESSION ... NOT a multi-line script — no `import`, no `def`, no `for`/`while` loops, no `;` statement separators, no top-level assignment. ..." + two examples per AC2 (one comprehension, one `.apply(lambda: ...)`). |
| `tools.py` lines 173-180 (parameter `description`) | "Python/pandas expression. DataFrame: ..." | Extended with one comprehension example (e.g. `[x for x in records if x['amount'] > 100]`) |
| `dispatch.py` module-level near `_CALC_NAMESPACE` (~line 358) | — | Add `_STATEMENT_RE` and `_detect_statement_keywords(expression: str) -> bool` |
| `dispatch.py` `_safe_calculate` at lines 379-402 | Single `try:` / `except Exception` catch, bare error message | (1) Before `compile(...)`, call `_detect_statement_keywords(expression)`; if True, return structured hint. (2) Wrap `compile(...)` in a specific `except SyntaxError` branch that returns the structured hint with the original SyntaxError msg+offset appended (R5 AC4). (3) Preserve the outer `except Exception` branch for runtime errors unchanged. | 

### R6: `pac1-py/skills/inbox-processing/SKILL.md`

Single append after line 25. See §Prompt anchors P-E-4.

### R7

No code changes. Closure recorded in Phase E completion report per R7 AC5 text (D8).

## Risk register

Carried forward from gap-analysis per-requirement risks, with explicit design-time mitigations. Risks are tagged by severity: **P0** = blocking (must be mitigated before commit), **P1** = high (mitigation is part of the implementation plan), **P2** = informational (documented, watched in R8 verification).

| ID | Description | Severity | Mitigation |
|----|-------------|----------|------------|
| R1.a | Changing JSON-serialization could regress unrelated columns (e.g. `attachments:` lists downstream code relies on being strings). | P0 | D2: selective exemption via `_LIST_COLUMN_EXEMPT = {"line_items"}`. Second test `test_load_records_still_serializes_non_exempt_list_columns` asserts `attachments` still serializes. Merge blocker if red. |
| R1.b | Bill with both frontmatter `line_items` and ASCII-body line items — double-parsing or conflict. | P1 | D1 + parser idempotence: frontmatter wins; body parser runs only when frontmatter has no `line_items` key. Unit test `test_parse_line_items_frontmatter_wins_over_body`. |
| R1.c | CJK vendor content in ASCII table cells (t080 `深圳市海云电子`); existing `^\+[-+]+\+$` regex is ASCII-only but cell content may contain Unicode. | P1 | Regex matches separator lines only (ASCII `+`/`-` chars); cell content is split on `|` and passes through as Unicode strings. See Research Q1 in `research.md` for confirmation with a unit test `test_parse_line_items_table_cjk_vendor`. |
| R1.d | `_date_from_file` may be missing when filename has no parseable date; R2's triple-filter then trips. | P2 | R2's ±2-day window is tolerant; R1 AC3 defaults do not affect `_date_from_file`. Covered by the multi-run R8 battery. |
| R2.a | Prompt bloat. Executor prompt already ≥150 lines; adding the triple-filter example pushes context pressure. | P2 | Anchor is ≤ 20 lines of added text inside rule 14. Monitor total prompt token size post-R2; acceptable if ≤ 10% growth. |
| R2.b | Rule 0 `±3 days` vs R2 AC1 `±1-2 days` wording conflict. | P0 | D3: land both edits in the R2 commit. grep for `+/- 3 days` post-commit: zero hits. |
| R2.c | Prompt-talking-to-nobody (taxonomy (c)): anchor must land in the prompt the executor actually reads. | P1 | Anchor lands in `build_executor_system` rule 14 (executor owns `calculate()` calls per gap analysis). Not duplicated into `build_planner_system`. |
| R3.a | Ambiguous matches — multiple projects with partial keyword hits. | P1 | D4 + rule 11 reuse: executor escalates to `OUTCOME_NONE_CLARIFICATION` listing candidates when `.shape[0] > 1`. |
| R3.b | CJK / non-Latin tokens don't split usefully on hyphen/whitespace. | P2 | t001 is English/German only; CJK cases are covered by R1+R2 paths (finance triple-filter). Documented non-goal. |
| R3.c | Case-insensitive + tokenized substring search could false-positive match a project whose `notes` field casually mentions query words. | P1 | `_name_keywords` is a single-column text field; LLM regex uses `|` of keyword tokens only (not AND); escalation to CLARIFICATION via rule 11 on multi-match. Unit test `test_find_project_false_positive_escalation`. |
| R3.d | Prompt-only (Option B) relies on LLM discipline which is why rule 6 already exists and fails. | P0 | D4: Option A code-level helper plus prompt hint naming the deterministic `_name_keywords` column. Not purely prompt-based. |
| R4.a | False positives on message body referencing internal-lane files (not as attachments). | P0 | D5: restrict match to `attachments:` YAML list only. Tightens AC1 wording; documented in Phase E report. |
| R4.b | Case-sensitivity asymmetry (case-sensitive dirs + case-insensitive filename) is awkward. | P1 | D5: encoded in `_INTERNAL_LANE_PREFIXES` (tuple, case-sensitive match) and `_INTERNAL_FILENAME_CI = {"agents.md"}` (set, lowercased basename match). Unit tests cover all four case combinations. |
| R4.c | Structural check leaks into LLM-visible text (R4 AC10 violation). | P0 | grep `rg '30_knowledge|90_memory|99_system' pac1-py/agent/prompts.py pac1-py/skills/` returns zero hits at commit time. Verified in CI. |
| R4.d | Ordering with `_verify_sender_email` at `executor.py:1245` — if structural check runs first and denies, email verification is skipped. | P1 | D5: structural check runs AFTER `_security_review` but BEFORE `_verify_sender_email`. OR semantics with `_security_review` only. `_verify_sender_email` retains its own gate (`if outcome == OUTCOME_OK and pending`) — it simply does not run when structural guard fired. |
| R5.a | SyntaxError hint must reach the LLM in-line in tool result; truncation would silently drop it. | P1 | `_safe_calculate` already surfaces the return string verbatim in the tool result. Unit test `test_syntax_error_hint_in_tool_result` asserts full hint string is returned. |
| R5.b | Statement-keyword sniffer false-positives on valid expressions containing the word `for` (e.g. comprehensions). | P1 | D6: regex is `(?m)^\s*(import |from |def |class |for |while |async |return )` — anchored to line start, so `[x for x in records]` does NOT match (the `for` is not at line start). Unit test `test_detect_statement_keywords_allows_comprehensions`. |
| R6.a | Skill-file-talking-to-nobody — skill only loaded if executor calls `load_skill('inbox-processing')`. | P1 | Planner's rule 1 + `inbox-processing` skill-load trigger already detect inbox tasks on mixed-language text via underlying LLM. Monitored via R8 t035 pass rate. |
| R6.b | Arabic + RTL rendering in tool results / logs. | P2 | Strings are UTF-8 bytes; Python and litellm handle RTL transparently. Visual inspection of one run's log confirms. |
| R6.c | Additive-only requirement; regression of Phase D R-DT24 English list. | P0 | R6 commit is a pure append — diff shows only additions below line 25. grep post-commit: all Phase D R-DT24 English verbs still present verbatim. |
| R7.a | Detecting "OCR task" without per-task hardcoding is hard (keyword sniffing, false positives). | Closed | R7 closed at design time (D8). No code, no risk, no commit. |
| R7.b | Byte-for-byte field replacement could stomp on intentional LLM edits. | Closed | R7 closed (D8). |
| R7.c | Scope creep risk. | Closed | R7 closed (D8). |

## Edit order and smoke-test checkpoints

Mirrors Phase D's "Edit Order and Smoke-test Checkpoints" pattern. Build order is determined by dependency graph + risk, not by requirement ID order.

**Build order:**

1. **R5** (lowest risk, independent, immediate feedback)
   - Commit `R5a`: rewrite `tools.py` calculate description + add two examples.
   - Commit `R5b`: add `_detect_statement_keywords` + sniffer + `_safe_calculate` SyntaxError branch + new unit tests.
   - Smoke test: t012 Lukas Brenner birthday variant 5-run pre-commit battery, target ≥ 4/5.
   - After R5 lands: run full 104-task benchmark once; assert ≥ 91/104 per R5 AC8.

2. **R1** (foundational; R2 depends on it)
   - Commit `R1`: add `_parse_line_items_table`, wire into `_load_records` phase 2, add `_LIST_COLUMN_EXEMPT`, add test classes.
   - Smoke test: t005, t030, t080 each in separate 5-run pre-commit batteries, target ≥ 4/5 each.
   - After R1 lands: full 104-task benchmark once; assert ≥ 91/104 per R1 AC8.

3. **R2** (depends on R1)
   - Commit `R2`: rule-14 triple-filter anchor + rule-0 ±3→±2 edit, same commit.
   - Smoke test: t005, t030, t058, t080, t084 each 5-run, target ≥ 4/5.
   - After R2 lands: full 104-task benchmark once; assert ≥ 91/104.

4. **R4** (parallel with R1/R2; independent)
   - Commit `R4`: new `agent/security_guard.py` + `executor.py` wire-up + `test_security_guard.py` fixtures.
   - Smoke test: t011, t036, t073 each 5-run, target ≥ 4/5.
   - After R4 lands: full 104-task benchmark once; assert ≥ 91/104.

5. **R3** (parallel with R4; independent)
   - Commit `R3`: `_find_project` + `_name_keywords` column in `_load_records` + planner rule 6 edit + unit test.
   - Smoke test: t001 5-run, target ≥ 4/5.
   - After R3 lands: full 104-task benchmark once; assert ≥ 91/104.

6. **R6** (parallel anywhere; zero code risk)
   - Commit `R6`: SKILL.md append.
   - Smoke test: t035 5-run, target ≥ 4/5.
   - After R6 lands: full 104-task benchmark once; assert ≥ 91/104.

7. **R7**: no commit. Close as "accepted LLM capability limit" per D8 + R7 AC5. Record in Phase E completion report.

8. **R8** (terminal verification): after R1–R6 all land, run full 104-task benchmark ≥ 3 times independently; compute multi-run average and per-task pass-rate distribution; record in Phase E completion report with (a)/(b)/(c)/(d) attribution. Target ≥ 99/104 averaged.

9. **R9** (continuous invariant): each Phase E commit runs the three greps from R9 AC5/AC6/AC7 pre-push. Zero hits required. The Phase E commit-message template includes "edit-surface compliance: allows `<files>` per R9 AC11 + D9".

**Parallelizable groups:**
- Group A (any order, no inter-deps): R5, R4, R3, R6
- Group B (serial): R1 → R2
- Group C (terminal): R8 (verification), R9 (continuous)

Recommended concrete schedule (if one implementer): R5 → R1 → R2 → R4 → R3 → R6 → R8 → R7 closure. Total: 7 atomic commits + 1 documentation-only closure.

## Atomic-commit invariant

Per-R commit atomicity rules:

| Req | Files that MUST land in one commit | Rationale |
|-----|------------------------------------|-----------|
| R1 | `agent/dispatch.py` + `tests/test_dispatch.py` | AC7: unit tests updated in same commit; D2 invariant cannot be verified without both. |
| R2 | `agent/prompts.py` alone | D3: rule 0 + rule 14 edits must co-occur or the date-tolerance divergence persists; both are in prompts.py. |
| R3 | `agent/dispatch.py` + `agent/prompts.py` + `tests/test_dispatch.py` | `_find_project` + `_name_keywords` + planner-prompt pointer + helper test are mutually referential; splitting breaks any test run. |
| R4 | new `agent/security_guard.py` + `agent/executor.py` + new `tests/test_security_guard.py` | Executor's new call site depends on the new module existing; tests assert both boundaries. |
| R5 | `tools.py` + `agent/dispatch.py` + `tests/test_dispatch.py` (two sub-commits acceptable: R5a and R5b per §Edit order) | R5a (tools) and R5b (dispatch) can split if each passes tests independently; if split, commit in order tools→dispatch and both land before the R5 smoke test. |
| R6 | `skills/inbox-processing/SKILL.md` alone | AC7 additive-only; no test changes. |
| R7 | (no commit) | Closed per D8. |
| R8 | Operational; records in Phase E completion report (not code). | — |
| R9 | Continuous; every Phase E commit runs the three greps as pre-push gate. | — |

**No cross-requirement commits.** Each commit's message template:

```
[Phase E R<N>] <one-line summary>

<multi-line body: what changed, why, which AC targets, edit-surface compliance>
Edit-surface compliance: allows <file1, file2, ...> per R9 AC11 + D9.
```

If a later commit discovers a cross-requirement regression, the fix lands in a new dedicated commit within the R9 allowlist — NOT by amending an existing R<N> commit.

## Test strategy

### Unit tests (new)

In `pac1-py/tests/test_dispatch.py`:

1. `TestParseLineItemsTable` — 5-6 tests covering: basic 4-column parse, 5-column `# | item | qty | unit_eur | line_eur` variant, CJK vendor name in cell, empty body returns `[]`, frontmatter `line_items` wins over body parse, parser is idempotent on repeated calls.
2. `TestLoadRecordsLineItemsColumn` — 3-4 tests: `line_items` column is `list[dict]` (not string), `_LIST_COLUMN_EXEMPT` preserves non-exempt list columns as JSON strings, empty-list default for files without line items, `_name_keywords` column only added for `projects/` path.
3. `TestFindProject` — 3-4 tests: exact-name match returns single row, substring match across `goal/alias/notes` returns matching rows, ambiguous (`.shape[0] > 1`) is detectable by caller, hyphen-tokenization splits `NORA-at-home` into `nora at home`.
4. `TestDetectStatementKeywords` — 5 tests: `import` at line start → True, `for x in records:` at line start → True, `[x for x in records]` → False (comprehension, `for` not at line start), valid `.apply(lambda: ...)` → False, top-level `;` separator → True.

In new `pac1-py/tests/test_security_guard.py`:

5. `TestStructuralSecurityCheck` — 6-7 tests: attachment pointing to `30_knowledge/foo.md` → citation, `90_memory/bar.md` → citation, root `AGENTS.md` → citation, `subdir/AGENTS.md` → citation, `subdir/agents.md` (lowercase) → citation, path with `./` prefix → citation, path with `/workspace/` prefix → citation, non-internal-lane path (e.g. `outbox/x.md`) → None, no `attachments:` field → None.

### Pre-commit 5-run batteries

Per R1–R6 Objective sections:

| Requirement | Tasks | Target (per task) |
|-------------|-------|-------------------|
| R1 | t005, t030, t080 | ≥ 4/5 each |
| R2 | t005, t030, t058, t080, t084 | ≥ 4/5 each |
| R3 | t001 | ≥ 4/5 |
| R4 | t011, t036, t073 | ≥ 4/5 each |
| R5 | t012 (Lukas Brenner variant) | ≥ 4/5 |
| R6 | t035 | ≥ 4/5 |

Batteries are run via the existing `pac1-py/run_targeted.py` driver (untracked file already in repo; promoted to tracked during R8 setup) against the workspace at `bitgn/pac1-prod` with model `openai/qwen3.5:27b-q4_K_M`.

### Multi-run full-benchmark verification (R8)

After R1–R6 land:

1. Run `pac1-py/main_batch.py` (or equivalent) 3 times back-to-back against `bitgn/pac1-prod` (104 tasks), each run on an independent process, each logging its `passed/104` score and per-task outcome.
2. Compute per-task pass rate = (runs passed) / (total runs). Any task with 0 ≤ rate < 1.0 is a stochastic signal.
3. Compute multi-run average = (sum passed across runs) / (3 × 104). Target ≥ 99/104 (0.9519). Optimistic ≥ 100/104 (0.9615).
4. Record in Phase E completion report: per-run score, multi-run average, per-task pass-rate distribution, per-regression (a)/(b)/(c)/(d) attribution.
5. If multi-run average < 99/104: per R7 of requirements, iterate within allowlist OR accept gap honestly with (a)/(b)/(c)/(d) attribution. Never re-add Phase A deletions, never add per-task hardcoding.

### R9 continuous greps (every Phase E commit)

Pre-push CI:

```bash
rg 'extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py && exit 1
rg 'sorted alphabetically|alphabetical order|post-process: re-sorted' pac1-py/agent/executor.py && exit 1
rg '\[SECURITY CHECK\]|This file is from the inbox' pac1-py/agent/dispatch.py && exit 1
rg 'if task_id == "t[0-9]' pac1-py/ && exit 1  # no per-task hardcoding
rg '30_knowledge|90_memory|99_system' pac1-py/agent/prompts.py pac1-py/skills/ && exit 1  # R4 AC10
```

(Grep pattern for `_compliance` excludes the existing docstring hit in `agent/outcomes.py` which *names* the forbidden symbols to prevent reintroduction; that file is on an explicit allowlist.)

## Requirements Traceability

| Requirement | Summary | Components / Files | Interfaces / Anchors | Flows / Stages |
|-------------|---------|--------------------|----------------------|----------------|
| 1.1–1.8 | `line_items` column on `load_records` output | `agent/dispatch.py` (`_parse_line_items_table`, `_load_records`, `_LIST_COLUMN_EXEMPT`); `tests/test_dispatch.py` | `_parse_line_items_table(text) -> list[dict]`; `line_items` column contract (D1/D2) | Executor (load_records stage) |
| 2.1–2.8 | Triple-filter pattern anchor; ±3→±2 date-tolerance reconciliation | `agent/prompts.py` rule 14 + rule 0 | Prompt anchors P-E-1, P-E-2 | Planner/Executor prompt |
| 3.1–3.7 | Indirect project reference via `_find_project` + `_name_keywords` | `agent/dispatch.py` (`_find_project`, `_name_keywords`); `agent/prompts.py` planner rule 6 | `_find_project(query, df)`; prompt anchor P-E-3 | Executor (load_records + calculate path) |
| 4.1–4.10 | Structural security guard | new `agent/security_guard.py`; `agent/executor.py` wire-up | `structural_security_check(pending_writes) -> Optional[str]`; D5 OR-composition | Security Guard stage |
| 5.1–5.8 | `calculate()` expression-only enforcement | `tools.py` (description); `agent/dispatch.py` (`_detect_statement_keywords`, `_safe_calculate` branch) | Statement sniffer + SyntaxError structured hint (D6) | Executor (tool call) |
| 6.1–6.10 | Multilingual inbox-processing verbs | `skills/inbox-processing/SKILL.md` | Prompt anchor P-E-4 | Executor (skill-load) |
| 7.1–7.6 | OCR byte-for-byte preservation | Closed per D8 | — | — |
| 8.1–8.8 | Multi-run benchmark verification | Operational; Phase E completion report | — | R8 verification stage |
| 9.1–9.13 | Anti-masking guard + edit-surface allowlist | `agent/outcomes.py` docstring (preserved); R9 CI greps; D9 allowlist extension | Pre-push grep gate | Continuous (every commit) |

## Non-goals / scope carve-outs (consolidated)

Inherited verbatim from `requirements.md` SCOPE BOUNDARIES:

1. No base-model upgrade.
2. No new structured machine-readable compliance tags.
3. No workspace-path hardcoding beyond the four R4 internal lanes.
4. No pipeline restructuring.
5. No re-introduction of Phase A deletions.
6. No benchmark data/task edits.
7. No per-task-ID hardcoding.
8. R7 may be closed as accepted LLM capability limit — **closed here at design time per D8**.

Added during Phase E design:

9. **No validator prompt edit for R6** (D7). If t035 fails the R6 5-run battery post-commit, the validator-prompt extension becomes a separate follow-up commit with its own justification.
10. **No new tool for R3** (D4). The `_find_project` fallback is a helper inside `dispatch.py`, exposed to the agent as a synthetic `_name_keywords` DataFrame column. No `tools.py` edit.
11. **No message-body scanning for R4** (D5). Structural match is against `attachments:` YAML list only. Tightens R4 AC1 wording; documented in Phase E report.
12. **No proactive sniffer on valid comprehensions** (D6). Regex is anchored to line start; `[x for x in records]` does not fire the hint.
13. **Test files co-evolve with production code** (D9). `tests/test_dispatch.py` and new `tests/test_security_guard.py` are explicitly in the edit-surface allowlist per R9 AC13.
