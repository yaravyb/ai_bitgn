# Phase E Gap Analysis

## Executive Summary

**Overall gap size: small-to-medium.** ~90% of Phase E infrastructure is already in place from Phases A/C/D. The three most important findings:

**(1) Schema-name mismatch in R1.** Requirements prescribe line-item keys `{item, qty, price, line_total}` but the actual workspace uses `{item, qty, unit_eur, line_eur}` (verified in workspace traces at `full_pac1_prod.txt:1409,1896` and test fixture `tests/test_dispatch.py:235`). R1's parser must either rename at parse time or carry both — the requirement text drifts from reality and needs design-phase reconciliation before R1 is implemented.

**(2) Existing `_parse_ascii_table` is not extensible for R1.** It handles 2-column key-value tables only (`dispatch.py:425-460`); line-item tables are multi-column. R1 effectively adds a NEW helper (`_parse_line_items_table`) rather than extending the existing one, despite the requirement's "extend" wording. Also, `_load_records` auto-JSON-serializes list columns to strings (`dispatch.py:676-681`) — this **directly conflicts with R1 AC4** (which requires `list[dict]`, not strings). R1 must carve an exemption.

**(3) R2 vs existing executor rule 0 have a date-tolerance wording conflict.** Rule 0 says "±3 days" (`prompts.py:110`); R2 AC1 says "±1-2 days." Must be reconciled in the same commit.

R9 anti-masking is currently clean (greps verified all forbidden Phase A deletions remain gone).

**Build order**: R5 → R1 → R2, with R3/R4/R6 in parallel; close R7 as LLM capability limit.

---

## Per-Requirement Analysis

### R1: Structured line-item extraction in load_records

**Existing components**
- `_parse_yaml_frontmatter` (`dispatch.py:412`) — handles YAML frontmatter; preserved, used by AC2.
- `_parse_ascii_table` (`dispatch.py:425`) — **only parses 2-column key-value tables** (`{field, value}`). It does NOT parse multi-column line-item tables.
- `_load_records` phase 2 (`dispatch.py:595-628`) — orchestrates per-file parsing.
- `_load_records` serialization pass (`dispatch.py:676-681`) — **auto-converts all list/dict column values to JSON strings**. Direct conflict with R1 AC4.
- Unit tests exist: `TestAsciiTableParser` (`test_dispatch.py:267-298`), `TestAsciiTableNormalizer` (`test_dispatch.py:212-264`).

**Integration points**
- `_load_records` → new `_parse_line_items_table()` helper invoked alongside `_parse_ascii_table` / frontmatter on bill/invoice files.
- Serialization pass at `dispatch.py:676-681` must be updated to exempt `line_items`.
- Downstream: `_safe_calculate` namespace (`dispatch.py:386-390`) — `df` exposes this column; no change needed.
- Existing display-name / entity-search / line-items guidance in prompts.py exec rule 14 (`prompts.py:179-186`) references "Line Items table" — the R1 column name must be consistent.

**Implementation gap**
- Multi-column ASCII table parser (`| # | item | qty | unit_eur | line_eur |`) missing entirely. `_parse_ascii_table` stops at rows with cell count ≠ 2 (`dispatch.py:449`).
- YAML `line_items:` list extraction not explicit — today a `lines:` or `items:` array in frontmatter would be captured but then JSON-stringified by the serialization pass.
- Empty-list default (AC3) must be added — currently a missing field → missing column or NaN, not `[]`.
- **Schema-name mismatch**: AC1 says keys `{item, qty, price, line_total}`; workspace uses `unit_eur`/`line_eur`. Design choice: rename at parse time, or pass through and update R2 example.

**Risks**
- R1.a: Changing JSON-serialization could regress unrelated columns (e.g. `attachments:` lists) downstream code relies on being strings. **Mitigation**: scope exemption to exactly `line_items`, add regression test.
- R1.b: Bills with both frontmatter `line_items` and ASCII-body `line_items` — parser must be idempotent (AC2). Risk of double-parsing or conflicting values.
- R1.c: CJK vendors (t080 `深圳市海云电子`) — existing regex `^\+[-+]+\+$` is ASCII-only but should tolerate Unicode cell content. Verify.
- R1.d: `_date_from_file` column (`dispatch.py:622-625`) may collide with per-task date filtering in R2's example if file has no parseable date — R2's `±1-2 day` tolerance anchor should mitigate.

**Strategy**
- Add `_parse_line_items_table(text) → list[dict]` as a new helper in `dispatch.py` (NOT extend `_parse_ascii_table` — semantics differ: 2-col kv vs N-col rows).
- Call during `_load_records` phase 2 after `_parse_ascii_table`, storing under `record["line_items"]`.
- YAML frontmatter path: if frontmatter contains `line_items`, `lines`, or `items` as list of dicts, use verbatim; otherwise fall back to body ASCII table.
- Add selective exemption to serialization loop so `line_items` stays as `list[dict]`.
- Post-populate `[]` for missing data after DataFrame is built.
- **Recommendation**: normalize keys to `{item, qty, unit_eur, line_eur}` (actual workspace shape) rather than R1's proposed `{item, qty, price, line_total}`. **The requirement text should be amended** — or keep both sets of keys. Flag for design phase.

**Dependencies**
- R2 depends on R1 (triple-filter example expression uses `df['line_items']`).
- R7 (optional) depends on R1's parser (byte-for-byte copy hooks into same parse path).

**Edit surface confirmation**
- Requirement says R1 edits `pac1-py/agent/dispatch.py` only. **Matches.** But R1 AC7 requires unit test updates — those live in `pac1-py/tests/test_dispatch.py`. R9 edit-surface allowlist must tacitly allow matching test files; recommend R9 be explicitly clarified.

---

### R2: Triple-filter query pattern guidance in executor/planner prompts

**Existing components**
- `build_executor_system()` (`prompts.py:58-211`) — already has rule 0 date+vendor lookup scaffolding (`prompts.py:100-115`), rules 13-15 (display names, line items, entity search).
- `build_planner_system()` (`prompts.py:214-286`) — rule 0 tabular-queries guidance, rule 6 indirect project references.
- **Critical**: executor rule 0 already prescribes ≥±3-day fuzzy date window (`prompts.py:109-115`). R2 AC1 says ±1-2 days. These **differ** — R2's spec must be reconciled, or rule 0 will contradict rule 15+R2 anchor.

**Integration points**
- R2 anchor is adjacent to rules 13-15 in `build_executor_system()` — straightforward insertion.
- Uses `df['line_items']` from R1 — R1 must land first.
- Relies on `date_offset`, `parse_date` already in `_CALC_NAMESPACE` (`dispatch.py:358-376`).

**Implementation gap**
- No explicit "triple-filter pattern" verbiage today. Closest anchor is rule 14 (line items vs file lines, `prompts.py:179-186`) and rule 0 vendor+date. Neither mentions composing vendor + date + line-item in a single calculate() expression.
- No service-line revenue aggregation example (AC3) for t058/t084.
- AC4 requires insertion adjacent to rules 13-15 — no new top-level section.

**Risks**
- R2.a: Prompt bloat. Executor prompt already 150+ lines; adding long `calculate()` example pushes context pressure.
- R2.b: Existing rule 0 vendor+date guidance (`prompts.py:100-115`) has `±3 days` window; R2 AC1 says `±1-2 days`. Design decision needed — recommend picking one and editing both.
- R2.c: **Prompt-talking-to-nobody risk** (Phase A/C/D taxonomy (c)): anchor must land in prompt executor actually reads. Planner uses `build_planner_system()`, executor uses `build_executor_system()` — AC1 says "and/or" so one is sufficient. Put in executor (owns `calculate()` calls).

**Strategy**
- Insert short sub-paragraph under rule 14 (LINE ITEMS) with one `calculate()` expression template and one service-line aggregation example.
- Reconcile date-tolerance wording with existing rule 0.
- Don't duplicate into planner (executor owns expression; planner owns plan outline).

**Dependencies**
- **Depends on R1.** Expression `df['line_items'].apply(...)` presumes R1 exposed that column as `list[dict]`.

**Edit surface**: `pac1-py/agent/prompts.py` only. **Matches.**

---

### R3: Indirect project reference resolution

**Existing components**
- Planner rule 6 (`prompts.py:280-284`) — already instructs "load_records the projects folder and search _body, description, or goal fields for matching keywords." **This is soft guidance, not a deterministic helper.**
- No `find_project()` helper exists (grep returned zero hits).
- No alias-matching code in `dispatch.py`.

**Integration points**
- Option A (code-level): new `_find_project(query)` helper in `dispatch.py` that wraps `_load_records('projects/')` + substring search across `goal`, `alias`, `notes`. Dispatched as new tool? Or called internally from `_load_records`?
- Option B (prompt-level): strengthen executor rule (not just planner) with deterministic 2-step composition: step 1 exact-match, step 2 fallback across `goal`/`alias`/`notes` via `df[...].apply(lambda r: ...)`.

**Implementation gap**
- No deterministic fallback. Today the LLM *may* do a fallback if it reads rule 6, but t001 failures show it doesn't reliably.
- AC3 requires deterministic (non-stochastic) tie-break when multiple candidates score equally.

**Risks**
- R3.a: Ambiguous matches (multiple projects with partial keyword hits) — AC3 allows either clarification or top-1, but both must be deterministic.
- R3.b: Tokenization rules (AC2 splits on whitespace and hyphens) interact with CJK. "深圳" won't split into useful tokens.
- R3.c: Case-insensitive + tokenized substring search could false-positive match a project whose `notes` field just mentions query words casually.
- R3.d: Code-level helper (Option A) introduces new symbol; prompt-level option (B) doesn't — but B relies on LLM discipline, which is why rule 6 already exists and fails.

**Strategy**
- Recommend **Option A with a narrow code-level helper** for determinism, exposed as new tool `find_project(query)` OR inlined into `_load_records` post-processing that adds a synthetic `_match_keywords` boolean column when called with `projects/`.
- Keep AC3 escalation behavior consistent with existing `OUTCOME_NONE_CLARIFICATION` semantics — when tied, return CLARIFICATION (safer than stochastic top-1).

**Dependencies**
- Independent of R1/R2/R4. Can land in parallel.

**Edit surface**
- Requirement says `dispatch.py` and/or `prompts.py`. **Matches.** If Option A with a new tool, also `pac1-py/tools.py` — **this is NOT in the allowlist for R3**. Recommend either (1) avoid new tools and expose via extension of `_load_records` output, or (2) amend R3's allowlist to include `tools.py`.

---

### R4: Hybrid security guard with structural fallback

**Existing components**
- `_security_review()` (`executor.py:46-128`) — pure-LLM security step, called at `executor.py:1235`. Returns `OUTCOME_DENIED_SECURITY` or `None`.
- Pending-write attachment grounding loop (`executor.py:1262-1279`) — already iterates outbox writes, parses YAML frontmatter, extracts `attachments:` list. Natural composition point.
- `skills/security-posture/SKILL.md` — narrative threat indicators; mentions workspace infrastructure but has no path allowlist.

**Integration points**
- Structural check should compose with `_security_review` via OR (AC2). Cleanest: either (a) extract structural check into new function in `agent/security_guard.py` that returns `Optional[str]`, called before or after `_security_review`, or (b) inline in `_security_review` as pre-check.
- Existing `attachments:` regex at `executor.py:1278` (`r"^attachments:\s*\n((?:\s+-\s+.+\n?)+)"`) is a good template — reuse extraction logic.

**Implementation gap**
- No structural check today. Internal-lane list (`30_knowledge/`, `90_memory/`, `99_system/`, `AGENTS.md`) not encoded anywhere.
- No path normalization helper (AC5 requires defensive matching of `./30_knowledge/`, `/workspace/30_knowledge/`, bare `30_knowledge/`).
- AC7 requires citation message format (`"Structural security check: ..."`) — must plumb through `_security_review` return value.

**Risks**
- R4.a: **False positives.** If outbox message *body* references `AGENTS.md` as quoted mention (not attachment), structural check may over-block. Mitigation: AC1 says "the pending write's `attachments` field (or message body referencing files)" — design must pick one; body-text matching will false-positive more.
- R4.b: Case-sensitivity asymmetry (AC4: case-sensitive for dirs, case-insensitive for `AGENTS.md`) is awkward but implementable. Risk of drift if either dir or filename renamed.
- R4.c: AC10 says structural check must NOT be described to LLM. Verify no leak into `security-posture/SKILL.md` wording.
- R4.d: Ordering with existing `_verify_sender_email` (`executor.py:1245`) — if structural check runs first and denies, email verification is skipped. Order-of-evaluation matters for final message.

**Strategy**
- New `agent/security_guard.py` with `structural_security_check(pending_writes) → Optional[str]`. Import from executor, call after `_security_review` so LLM's more informative reasoning appears in logs first, but override with structural result via OR.
- Reuse `attachments:` YAML regex from `executor.py:1278`.
- Scope path matching to `attachments:` list only — not body text — to minimize false positives. Tightens AC1 beyond spec; flag for design.

**Dependencies**
- Independent of R1/R2/R3. Can land in parallel.

**Edit surface**
- Spec: `executor.py` and/or new `pac1-py/agent/security_guard.py`. **Matches.** Strategy recommends new file — aligns.

---

### R5: calculate() expression-only enforcement

**Existing components**
- `calculate` tool schema (`tools.py:154-186`) — currently short description, no statement prohibition.
- `_safe_calculate()` (`dispatch.py:379-402`) — calls `compile(expression, "<calc>", "eval")`. Catches all exceptions via bare `except Exception as exc: return f"Error: {exc}"`. **Does NOT distinguish SyntaxError from other errors.**
- Restricted namespace (`dispatch.py:358-376`) — pandas, math helpers, date helpers, `text_match`, `parse_date`.

**Integration points**
- `tools.py` → description rewrite only, 2 examples.
- `dispatch.py::_safe_calculate` → wrap `compile(...)` in narrower try/except for `SyntaxError`, return structured hint.

**Implementation gap**
- No SyntaxError-specific hint. Today agent sees `Error: invalid syntax (<calc>, line 1)` — cryptic.
- No expression-vs-statement narrative in tool schema.

**Risks**
- R5.a: Agent's self-correction relies on SyntaxError message being delivered in-line in tool result. Verify `_safe_calculate` return value is surfaced to LLM intact (no truncation).
- R5.b: Some valid expressions raise SyntaxError in transient ways (e.g. f-string edge cases in restricted namespace). Over-eager hint could mislead on non-statement-related failures. Mitigation: only fire hint when `compile(...)` raises SyntaxError at compile time, not runtime.

**Strategy**
- Minimal, tight change. One message literal in `_safe_calculate`, description rewrite in `tools.py`.
- Recommend also checking for statement-only keywords in expression string (e.g. `^\s*(import |def |for |while |class )` or presence of `;`) and emitting hint even when LLM produces multi-line string that parses as valid-but-intended-as-script.

**Dependencies**
- Independent. Can land in parallel.

**Edit surface**: `tools.py` + `dispatch.py`. **Matches.**

---

### R6: Multilingual inbox-processing verb support

**Existing components**
- `skills/inbox-processing/SKILL.md:10-25` — English verb list landed in Phase D (R-DT24). "Review and summarize is a planner bug" anti-pattern anchor at lines 22-25.
- Validator prompt (`prompts.py:326-330`) also enumerates English verbs for cross-account check. **If R6 adds multilingual verbs only to skill file but not validator prompt, validator continues to be English-only.** Flag for design — acceptable that validator recognizes only English verbs (since validator re-reads task text), or must validator also learn multilingual verbs?

**Integration points**
- Pure skill-file edit. `load_skill('inbox-processing')` injects the file; agent reads it.

**Implementation gap**
- No multilingual verb coverage in skill file. R6 adds Chinese/Japanese/Spanish/German/Arabic entries.

**Risks**
- R6.a: **(b) "Skill file talking to nobody"** (Phase A/C/D taxonomy) — skill only loaded if executor calls `load_skill('inbox-processing')`. If planner didn't detect Chinese task as inbox-related, skill is never loaded, multilingual verbs don't help. Mitigation: verify planner rule 0/1 for inbox-detection works on non-English text (likely yes — planner system prompt is English but LLM handles mixed languages).
- R6.b: Arabic + RTL rendering in tool results. Usually fine in Unicode contexts but worth visual check.
- R6.c: AC7 says "additive only — preserve Phase D R-DT24 verbatim." Must be pure append.

**Strategy**
- Append sub-paragraph below existing verb list. Include English gloss in parentheses so LLM disambiguation works (AC2 explicitly says gloss).
- Consider also updating validator prompt (`prompts.py:326-330`) to recognize multilingual verbs — flag for design as optional.

**Dependencies**: independent.

**Edit surface**: `skills/inbox-processing/SKILL.md` only. **Matches (but flag validator prompt concern above).**

---

### R7: OCR umlaut preservation (OPTIONAL / P4)

**Existing components**
- `_parse_ascii_table` (`dispatch.py:425-460`) — extracts key-value pairs including `counterparty`. Values string-typed, umlaut-safe at parse time (no character loss in Python string handling).
- Corruption happens downstream when **LLM paraphrases** frontmatter write (`Düsenschmiede` → `Düenschmiede`). See `full_pac1_prod.txt:1897` for corrupted value in plan_note context.

**Integration points**
- OCR write path is LLM-driven — LLM calls `write(path, content)` with self-composed content. Unless intermediate step copies source fields verbatim, LLM decides what goes in.
- Nearest hook: pre-apply step in pending-writes pipeline (`executor.py`: `_drop_fabricated_writes`, `_fix_queue_order`, etc.) could diff write's YAML frontmatter fields against source-ASCII-table fields.

**Implementation gap**
- No byte-for-byte copy mechanism. Entire implementation missing.
- Requires: (a) detect OCR-migration tasks, (b) locate source ASCII table, (c) extract specific fields, (d) overwrite LLM's frontmatter values.

**Risks**
- R7.a: **Hard to land cleanly.** Detecting "OCR task" without per-task hardcoding is genuinely difficult. May require sniffing task text for "OCR" / "migration" keywords, with false-positive risks.
- R7.b: Byte-for-byte field replacement could stomp on intentional LLM edits (e.g. LLM corrected typo in source).
- R7.c: Scope explicitly carved out in SCOPE BOUNDARIES item 8 — may be closed as LLM capability limit.

**Strategy**
- **Recommend: close as "accepted LLM capability limit" per AC5 unless a single-commit additive helper emerges.** Process requirement R9 prohibits expanding scope. Use requirement AC3 to close cleanly.

**Dependencies**: could reuse R1's parser hooks, but independent otherwise.

**Edit surface**: `dispatch.py` only (if pursued). **Matches.**

---

### R8: Honest multi-run benchmark verification

**Gap is operational, not code.**
- Existing: repo has `full_pac1_prod.txt` from single run (untracked). `pac1-py/main_batch.py` and `pac1-py/run_targeted.py` exist (git status shows as untracked). Presumably used to run benchmark rounds.
- Missing: explicit multi-run invocation script + report template.
- AC4 requires per-task pass-rate distribution across runs — need simple aggregator script (not in codebase today per grep).

**Strategy**: design phase should specify a `run-phase-e-bench.sh` or similar driver + markdown template for the Phase E completion report.

**Edit surface**: none (operational). R8 adds no code.

---

### R9: Anti-masking guard (carries forward)

**Current state (verified by grep):**
- `extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance`: only 1 hit in `agent/outcomes.py` — in docstring comment **naming forbidden symbols to prevent re-introduction**. Zero actual definitions. **Clean.**
- `sorted alphabetically|alphabetical order`: zero hits in `agent/executor.py`. **Clean.**
- `\[SECURITY CHECK\]|This file is from the inbox`: zero hits in `agent/dispatch.py`. **Clean.**
- All Phase A deletions remain gone. R9 currently satisfied.

**Strategy**: R9 is forward-looking invariant. Design phase should script the three greps as pre-commit hooks or CI checks for each Phase E commit.

**Edit surface**: R9 governs the allowlist itself; it edits nothing directly.

---

## Cross-Cutting Observations

1. **Schema-name drift.** Requirements R1 AC1 names `{item, qty, price, line_total}`. Actual workspace uses `unit_eur`/`line_eur`. **Design phase must resolve this** — either amend AC1 to use workspace names, or mandate rename in parser and update R2's example expression in lockstep.

2. **R1 + R2 are tightly coupled.** R2's acceptance criteria literally reference the `line_items` column R1 creates. Build R1 first; R2 is trivial prompt edit after R1 lands. A single "combined R1+R2" commit may actually be cleaner than two separate commits (both target t005/t030/t080 jointly).

3. **Edit-surface allowlist has two omissions to flag**:
   - R1 needs to edit `tests/test_dispatch.py` for AC7 unit-test updates — not listed in R9 allowlist.
   - R3 Option A (new tool) would edit `tools.py` — not listed in R3's allowlist. Either constrain R3 to dispatch-helper-only approach, or amend allowlist.

4. **Pattern of LLM-dependent layers wrapping deterministic layers.** Codebase philosophy: deterministic code as backstop, LLM as primary reasoner. R4's hybrid security guard is natural continuation — structural OR with LLM verdict. R1 (deterministic parser) and R5 (deterministic error hint) follow same pattern. **Phase E is more structurally homogeneous than Phase D was** — lower architectural risk.

5. **`_parse_ascii_table` naming is misleading.** It parses 2-column key-value tables only. R1's "multi-column line-item parser" is different beast — recommend naming new helper `_parse_line_items_table` to avoid implying extension of `_parse_ascii_table`.

6. **Executor rule 0 vs R2 anchor: wording conflict on date tolerance.** Existing: "widen to +/- 3 days" (`prompts.py:110`). R2 AC1: "±1–2 day date tolerance." Must be reconciled in same commit.

7. **Context bloat.** Executor prompt already long. R2 adds `calculate()` example to it. Phase E may cumulatively push token costs up. Watch for truncation in tests.

---

## Build Order Recommendation

1. **R5 first** (trivial, independent, zero dependencies, +1 task) — lowest risk, gains immediate feedback from benchmark.
2. **R1 second** (foundational for R2; independent otherwise). Biggest single code change in Phase E. Land with test updates in same commit.
3. **R2 third** (depends on R1; trivial once R1 is in).
4. **R4 parallel to R1/R2** (independent; new module; no blocking dependencies).
5. **R3 parallel to R4** (independent; but clarify Option A vs B first to avoid tools.py scope creep).
6. **R6 parallel anytime** (pure skill edit; zero risk).
7. **R7 last or skip** (P4; recommend closing as LLM capability limit unless helper is near-trivial).
8. **R8 (operational)** runs **after** R1-R6 land. R9 is continuous invariant.

**Parallelizable groups**:
- Group A (any order, no inter-deps): R5, R4, R3, R6
- Group B (serial): R1 → R2
- Group C (terminal): R7 (optional), R8 (verification), R9 (continuous)

---

## Files Referenced

- `/home/yaravyb/CODE/ai_bitgn/.kiro/specs/ai-first-phase-e/requirements.md`
- `/home/yaravyb/CODE/ai_bitgn/.kiro/specs/ai-first-phase-e/spec.json`
- `/home/yaravyb/CODE/ai_bitgn/.kiro/specs/ai-first-phase-d/pac1-prod-improvement-plan.md`
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/agent/dispatch.py` (358-402 calc; 405-711 load_records; 425-460 `_parse_ascii_table`; 676-681 JSON-serialization conflict)
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/agent/executor.py` (46-128 `_security_review`; 1235-1241 hook point; 1262-1279 attachments extraction template)
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/agent/prompts.py` (58-211 executor; 214-286 planner; 100-115 rule 0 date window conflict with R2; 179-186 rule 14 adjacency for R2)
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/agent/outcomes.py` (R9 docstring invariants, verified clean)
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/tools.py` (154-186 calculate schema for R5)
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/skills/inbox-processing/SKILL.md` (10-25 Phase D R-DT24 verb list for R6)
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/skills/security-posture/SKILL.md` (verified does not describe R4 internal lanes per AC10)
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/tests/test_dispatch.py` (existing tests; line 235 shows workspace `unit_eur`/`line_eur` schema)
- `/home/yaravyb/CODE/ai_bitgn/pac1-py/full_pac1_prod.txt` (lines 1409, 1896, 1897 confirm workspace line-item schema, confirm Düsenschmiede corruption in existing plan_note output)
