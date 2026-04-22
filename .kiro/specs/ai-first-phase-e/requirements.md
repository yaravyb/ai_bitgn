# Requirements Document

## Project Description (Input)
Phase E: pac1-prod hardening — push the PAC1-Prod benchmark score from 87.5% (91/104) to 95%+ by addressing 13 remaining failure patterns on the `bitgn/pac1-prod` benchmark with `openai/qwen3.5:27b-q4_K_M`. Focus areas:

1. **Finance line-item triple-filter queries** (5 tasks) — questions like "how much did VENDOR charge for ITEM N days ago" fail because the agent can't compose vendor+date+line_item filters. Needs: normalized `line_items` column in `load_records` output + prompt guidance on the triple-filter pattern.

2. **Hybrid security guard** (3 tasks) — internal file sharing detection is 80% reliable via LLM semantic check. Adding a structural fallback (outbox attachments referencing `30_knowledge/`, `90_memory/`, `99_system/`, or any `AGENTS.md` → BLOCK) gives deterministic security coverage.

3. **Indirect project reference resolution** (1-2 tasks) — queries like "start date for NORA-at-home project" fail when the project name doesn't match exactly. Agent should search `goal`, `alias`, `notes` fields in project READMEs.

4. **Calculate expression-only enforcement** (1 task) — agent wastes 343s writing multi-line Python programs (import, def, for, semicolons) in `calculate()` which accepts only expressions. Tool description + error messages need to be explicit.

5. **Multilingual inbox verbs** (1 task) — Chinese/Japanese/Arabic task prompts bypass the English-only inbox verb list. Need verb-synonymy across languages OR LLM pre-normalization.

6. **OCR character preservation** (1 task) — umlauts and special characters dropped during markdown→frontmatter migration ("Düsenschmiede" → "Düenschmiede"). Needs byte-for-byte copy of key fields from source.

Primary input: `.kiro/specs/ai-first-phase-d/pac1-prod-improvement-plan.md` — contains full failure analysis, categorization, priority order, and architecture summary.

Baseline state:
- Current: 91/104 = 87.5%
- Previous rounds: 71/104 (68.3%) → 80/104 (76.9%) → 91/104 (87.5%)
- Branch: `feature/simplify-approach`
- Benchmark: `bitgn/pac1-prod` (104 tasks, randomized variants per run)
- Tool adoption: 60 `load_records` + 130 `calculate` calls per full run

Target: 95-98% (99-102/104). Remaining ~3% is model-capability limits unlikely to be fixed without a stronger base model.

## Introduction

Phase E is a **follow-up tightening pass** on top of Phase D. It is not a major architectural push — the pipeline shape `Bootstrap → Planner → Executor → Security Guard → Validator → Apply Writes → Submit` is preserved verbatim, the outcome-code protocol established in Phase D (R-DOI) is preserved, the narrative anchors landed in Phase D are preserved, and the anti-masking guard from Phase A R6.4 / Phase C R6 / Phase D R7 is carried forward (see R9 below).

Phase E targets the 13 remaining failures from the `bitgn/pac1-prod` round-3 run, grouped into seven scoped requirements (R1–R7) plus two cross-cutting requirements (R8 multi-run verification, R9 anti-masking guard). The improvement plan document `.kiro/specs/ai-first-phase-d/pac1-prod-improvement-plan.md` is the authoritative source for failure classification, root-cause analysis, and expected-impact estimates. Each Phase E requirement lists the specific failing task IDs it targets (t001, t005, t011, t018, t030, t035, t036, t041, t058, t073, t080, t084, and the birthday task on t012) and ties each acceptance criterion to a concrete architectural touchpoint (file, function, prompt section).

Phase E's empirical bar inherits Phase D's multi-run convention: **per-task 5-run pre-commit batteries** before each commit, plus a **multi-run full-benchmark average** after all Phase E work lands. The target is ≥ 99/104 (95.2%) averaged across ≥ 3 independent `bitgn/pac1-prod` runs; optimistic target is ≥ 100/104 (96.2%). The remaining ~3% is acknowledged as LLM base-model capability limit (umlaut OCR drop, unusual multi-statement `calculate()` phrasing) and is not blocking Phase E acceptance.

Phase E's edit surface is deliberately narrower than Phase D's:
- **R1** edits `pac1-py/agent/dispatch.py` only (line-item normalization in `load_records`).
- **R2** edits `pac1-py/agent/prompts.py` only (triple-filter pattern anchor).
- **R3** edits `pac1-py/agent/dispatch.py` and/or `pac1-py/agent/prompts.py` (indirect project reference resolution — implementation choice deferred to `spec-design`).
- **R4** edits `pac1-py/agent/executor.py` and/or a new `pac1-py/agent/security_guard.py` (structural security fallback — exact location deferred to `spec-design`).
- **R5** edits `pac1-py/tools.py` (tool description) and `pac1-py/agent/dispatch.py` (error hint in `_safe_calculate` SyntaxError path).
- **R6** edits `pac1-py/skills/inbox-processing/SKILL.md` only (multilingual verb additions).
- **R7** (optional) edits `pac1-py/agent/dispatch.py` only (OCR byte-for-byte copy) if pursued.

## SCOPE BOUNDARIES

Phase E **will NOT**:
1. **Upgrade the base model** (qwen3.5:27b-q4_K_M → qwen3.5-72b or GPT-4-class). Model upgrade is explicitly out of scope; the remaining ~3% long-tail is accepted as base-model capability limit.
2. **Introduce new structured machine-readable compliance tags** (carries forward Phase C D2 / Phase D R7). R4's structural security fallback is a hardcoded path-prefix check, not a new parser or structured tag.
3. **Hardcode workspace-specific paths beyond the R4 internal-lanes list** (`30_knowledge/`, `90_memory/`, `99_system/`, `AGENTS.md`). The security guard remains workspace-aware for these four prefixes only; no other path hardcoding is permitted.
4. **Restructure the core pipeline** `Bootstrap → Planner → Executor → Security Guard → Validator → Apply Writes → Submit`. All Phase E changes are local to individual stages.
5. **Re-introduce any Phase A deletion** (`extract_decision_outcome`, `plan_compliance` / `_compliance` / `set_compliance` / `get_compliance`, alphabetical post-processor, inbox `[SECURITY CHECK]` injection). See R9.
6. **Edit `bitgn/pac1-prod` benchmark data or task definitions**. Phase E tunes the agent to the benchmark; it does not modify the benchmark itself.
7. **Add per-task special-case branches** (e.g., `if task_id == "t005": ...`). Fixes must generalize across the failure pattern, not hardcode against individual task IDs.
8. **Pursue R7 (OCR umlaut preservation) if it requires architectural changes**. R7 is explicitly P4 / low-impact and may be closed as "accepted LLM capability limit" if the byte-for-byte-copy approach does not land cleanly in a single commit.

## Requirements

### Requirement 1: Structured line-item extraction in load_records
**User Story:** As a pac1-py maintainer, I want `load_records` to parse ASCII-table bodies of bill/invoice files and expose a normalized `line_items` column (a list of `{item, qty, price, line_total}` dicts) on the resulting pandas DataFrame, so that the agent can compose `calculate()` expressions that filter bills by vendor, filter by date, and extract a specific line-item amount in a single query.

**Objective:** Extend the existing ASCII-table parser in `pac1-py/agent/dispatch.py` (`load_records` + `_parse_ascii_table`) to emit a structured `line_items` column alongside the existing frontmatter fields, landed as a single atomic commit with a 5-run pre-commit battery of t005, t030, and t080 passing at ≥ 4/5 each.

**Expected impact:** +3 tasks (t005, t030, t080 per the plan doc impact table).

#### Acceptance Criteria
1. The function `load_records` in `pac1-py/agent/dispatch.py` shall, when parsing a bill/invoice file that contains an ASCII line-items table (either in the file body below frontmatter or as a standalone ASCII-table file), extract each row of the table into a dict with at minimum the keys `item`, `qty`, `price`, and `line_total`, and shall expose the resulting list on the returned DataFrame as a column named `line_items`.
2. WHEN a bill's line-items are encoded in YAML frontmatter as a list of dicts (not as an ASCII table), THE `load_records` function SHALL preserve the existing YAML extraction path and populate the `line_items` column from the frontmatter list without re-parsing the body.
3. IF a bill file contains neither an ASCII line-items table nor a YAML `line_items` frontmatter list, THEN `load_records` SHALL populate the `line_items` column with an empty list `[]` for that row (not `None`, not a missing column), so that downstream `calculate()` expressions can use uniform `.apply(lambda items: ...)` patterns without `None`-checks.
4. The `line_items` column values SHALL be plain Python `list[dict]` objects (not pandas Series, not numpy arrays), so that the agent can write `df[df['line_items'].apply(lambda items: any(item['item'] == 'X' for item in items))]` style filters directly inside `calculate()`.
5. The existing `load_records` contract SHALL be preserved: the return type, the auto-trigger behavior on list() of structured folders with ≥ 3 parseable files, the JSON/YAML/ASCII parsing precedence, and the column set for non-bill files (contacts, accounts, projects, etc.) are unchanged by R1.
6. WHEN a 5-run battery of task `t005` is executed against the post-R1 agent using `bitgn/pac1-prod`, THEN the t005 pass rate SHALL be ≥ 4/5. Same bar for t030 and t080 independently (each task ≥ 4/5 in its own 5-run battery).
7. The existing pac1-py unit test suite shall continue to pass after R1 lands. Any unit test that exercises `load_records` or `_parse_ascii_table` SHALL be updated in the same commit to reflect the new `line_items` column (no red unit tests on any R1 commit boundary).
8. The full 104-task PAC1-Prod benchmark shall still score ≥ 91/104 on any individual run after R1 lands, and shall contribute to the multi-run ≥ 99/104 average measured under Requirement 8.

### Requirement 2: Triple-filter query pattern guidance in executor/planner prompts
**User Story:** As a pac1-py maintainer, I want `build_executor_system` and/or `build_planner_system` in `pac1-py/agent/prompts.py` to contain an explicit **triple-filter pattern anchor** describing how to compose vendor + date + line-item filters for finance queries like "how much did VENDOR charge for ITEM N days ago", so that the planner emits a correct `load_records → date_offset → filter by counterparty → filter by line_items → sum price` sequence instead of giving up and returning `OUTCOME_NONE_CLARIFICATION`.

**Objective:** Add a triple-filter pattern anchor to the executor and/or planner prompt, co-located with the existing tabular-query guidance (executor rules 13–15 that landed in round 2), with a 5-run pre-commit battery of t005, t030, t058, t080, and t084 passing at ≥ 4/5 each.

**Expected impact:** +2-3 tasks (overlapping with R1 on t005/t030/t080; exclusive targets are t058 and t084 per the plan doc).

#### Acceptance Criteria
1. The file `pac1-py/agent/prompts.py` shall contain, inside `build_executor_system` and/or `build_planner_system`, a **triple-filter pattern anchor** of the form: *"For finance queries matching the pattern 'how much did VENDOR charge for ITEM N days ago' (or equivalent phrasings), compose three filters: (1) compute the target date via `date_offset(today, -N)`; (2) filter bills where `counterparty` (or `supplier`) matches VENDOR; (3) filter to the matching line item via `line_items` column and sum `line_total` (or `price` if `line_total` absent). Use a ±1–2 day date tolerance when the bill date does not fall exactly on the computed target date."*
2. The triple-filter anchor SHALL explicitly name the `line_items` column introduced by R1 and SHALL show at least one example `calculate()` expression using the column (e.g. `df[df['counterparty'].str.contains('VENDOR') & (abs((df['date'] - target_date).dt.days) <= 2)]['line_items'].apply(lambda items: sum(i['line_total'] for i in items if 'ITEM' in i['item']))`).
3. The triple-filter anchor SHALL also cover the **service-line revenue aggregation variant** for t058 / t084 — when the task asks for "revenue from SERVICE_NAME since DATE", the same triple-filter composition applies to `invoices/` (filter by date range, filter by `line_items` service match, sum `line_total`).
4. The triple-filter anchor SHALL be co-located with (and immediately adjacent to) the existing executor rules 13–15 (display names, line items, entity search) that landed in round 2. It SHALL NOT be added as a new top-level section or a new prompt function.
5. The existing executor/planner prompt content SHALL be preserved unchanged outside the triple-filter anchor insertion: all round-1/round-2 rules, the grounding guards, the empty-message guard, the security coherence guard, and the existing tool-usage guidance remain verbatim.
6. WHEN a 5-run battery of task `t005` is executed against the post-R2 agent, THEN the t005 pass rate SHALL be ≥ 4/5. Same bar for t030, t058, t080, and t084 independently.
7. WHEN a 5-run battery of task `t058` is executed and the task asks for service-line revenue aggregation on `invoices/`, THEN the agent SHALL emit a plan that includes `load_records` on the invoices folder, a date-range filter, a `line_items` service-name filter, and a `calculate()` call that sums the matching line totals.
8. The full 104-task PAC1-Prod benchmark shall still score ≥ 91/104 on any individual run after R2 lands, and shall contribute to the multi-run ≥ 99/104 average measured under Requirement 8.

### Requirement 3: Indirect project reference resolution
**User Story:** As a pac1-py maintainer, I want the project-query handling path to search the `goal`, `alias`, and `notes` fields of project README frontmatter (not just the project `name` field) when the task question mentions a project by an indirect reference (e.g. "NORA-at-home", "morning launch kit"), so that indirect project references resolve to the correct project record instead of triggering `OUTCOME_NONE_CLARIFICATION` on an empty lookup result.

**Objective:** Extend project-query resolution in `pac1-py/agent/dispatch.py` (or the equivalent planner/executor prompt surface in `pac1-py/agent/prompts.py` — implementation choice deferred to `spec-design`) to fall back to a substring/keyword search across `goal`, `alias`, and `notes` when an exact `name` match returns zero rows, with a 5-run pre-commit battery of t001 passing at ≥ 4/5.

**Expected impact:** +1-2 tasks (t001 primary target; t051-style variants per the plan doc impact table).

#### Acceptance Criteria
1. WHEN the agent runs a project-query lookup (e.g. `load_records('projects/')` followed by a name-filter `calculate()` expression) and the exact-match name filter returns zero rows, THE system SHALL fall back to a **substring/keyword search** across the `goal`, `alias`, and `notes` frontmatter fields of the project records, ordered by best match, and SHALL return the top-1 match if any of those fields contains the query keywords.
2. The fallback search SHALL be case-insensitive and SHALL tokenize the query string (splitting on whitespace and hyphens) so that "NORA-at-home" matches a project whose `alias` field contains "NORA at home" or whose `notes` field mentions "NORA" and "home" as separate tokens.
3. IF the fallback search returns more than one candidate with comparable match scores (no clear top-1), THEN the agent SHALL either (a) return `OUTCOME_NONE_CLARIFICATION` with a message listing the candidate projects, or (b) pick the highest-scoring candidate and proceed — the choice of (a) vs (b) is deferred to `spec-design`, but the behavior SHALL be deterministic (not stochastic LLM selection).
4. The exact-name-match path SHALL remain the primary resolution strategy; the fallback search SHALL only trigger when exact-match returns zero rows. R3 SHALL NOT change the behavior for queries that already match an exact project name.
5. The fallback shall be implemented either as a code-level helper in `pac1-py/agent/dispatch.py` (e.g. a `find_project(query)` helper that wraps `load_records('projects/')`) OR as a prompt-level rule in `build_executor_system` instructing the agent to compose the fallback as two `calculate()` calls — `spec-design` will choose; R3 here constrains **what must be true**, not **how to implement**.
6. WHEN a 5-run battery of task `t001` is executed against the post-R3 agent, THEN the t001 pass rate SHALL be ≥ 4/5.
7. The full 104-task PAC1-Prod benchmark shall still score ≥ 91/104 on any individual run after R3 lands, and shall contribute to the multi-run ≥ 99/104 average measured under Requirement 8.

### Requirement 4: Hybrid security guard with structural fallback
**User Story:** As a pac1-py maintainer, I want the independent security guard (currently a pure-LLM step that runs on `OUTCOME_OK` + pending writes) to be augmented with a **structural path-prefix check** that deterministically BLOCKs any outbox write whose `attachments` field references files in internal lanes (`30_knowledge/`, `90_memory/`, `99_system/`, or any `AGENTS.md` at any depth), regardless of the LLM security-guard verdict, so that internal-file-sharing with external contacts is caught by a backstop check even when the LLM misclassifies the request.

**Objective:** Add a structural fallback check to the security-guard flow, co-located with the existing LLM security-guard step (in `pac1-py/agent/executor.py` or a new `pac1-py/agent/security_guard.py` module — exact location deferred to `spec-design`), with a 5-run pre-commit battery of t011, t036, and t073 passing at ≥ 4/5 each.

**Expected impact:** +2-3 tasks (t011, t036, t073 per the plan doc impact table).

#### Acceptance Criteria
1. WHEN the executor pipeline reaches the security-guard stage for a pending outbox write (an email message being sent from `outbox/` to an external contact), AND the pending write's `attachments` field (or the message body referencing files) names any path that starts with `30_knowledge/`, `90_memory/`, `99_system/`, or contains a segment named `AGENTS.md` at any depth, THE security guard SHALL return `OUTCOME_DENIED_SECURITY` regardless of the LLM security-guard verdict.
2. The structural check SHALL run in addition to (not instead of) the existing LLM security-guard step. The two results SHALL be combined with **OR semantics**: if either the LLM check OR the structural check flags the write as unsafe, the outcome is `OUTCOME_DENIED_SECURITY`.
3. The internal-lane path list SHALL be the exact four prefixes `30_knowledge/`, `90_memory/`, `99_system/`, and any file named `AGENTS.md` (at any depth, including root `AGENTS.md` and nested `subdir/AGENTS.md`). No other paths shall be hardcoded as internal lanes in R4.
4. The structural check SHALL be **case-sensitive** for the directory prefixes (matching the actual `bitgn/pac1-prod` workspace layout) and **case-insensitive** for the `AGENTS.md` filename (so `agents.md` and `AGENTS.MD` also match).
5. The structural check SHALL match paths defensively — both `30_knowledge/foo.md` and `./30_knowledge/foo.md` and `/workspace/30_knowledge/foo.md` shall match the `30_knowledge/` prefix (after path normalization).
6. The existing LLM security-guard prompt and step-by-step reasoning flow SHALL be preserved unchanged. R4 is **additive** — it adds a structural check alongside the LLM check, it does NOT modify the LLM prompt or its output parsing.
7. WHEN the structural check fires and the LLM check would have returned `OUTCOME_OK`, THE combined security-guard outcome SHALL be `OUTCOME_DENIED_SECURITY` with a `message` field that explicitly cites the structural rule (e.g. *"Structural security check: outbox write references internal-lane file 30_knowledge/foo.md"*), so that debugging is traceable.
8. WHEN a 5-run battery of task `t011` is executed against the post-R4 agent, THEN the t011 pass rate SHALL be ≥ 4/5. Same bar for t036 and t073 independently.
9. The full 104-task PAC1-Prod benchmark shall still score ≥ 91/104 on any individual run after R4 lands, and shall contribute to the multi-run ≥ 99/104 average measured under Requirement 8.
10. The structural security check SHALL NOT be described to the LLM (neither in the executor prompt nor the security-guard prompt). It is a backstop, not a steering mechanism; the LLM continues to reason about security on its own, and the structural check catches failures deterministically.

### Requirement 5: calculate() expression-only enforcement
**User Story:** As a pac1-py maintainer, I want the `calculate()` tool description in `pac1-py/tools.py` to explicitly prohibit Python statements (`import`, `def`, `for`, `while`, `;`, multi-line programs) and to direct the LLM toward comprehensions, and I want `_safe_calculate` in `pac1-py/agent/dispatch.py` to return a clearer error hint when `compile(..., mode="eval")` raises `SyntaxError`, so that the agent stops burning 300+ seconds on six variations of a multi-line Python program and instead rewrites the computation as a single expression.

**Objective:** Rewrite the `calculate()` tool-schema description in `pac1-py/tools.py` to explicitly prohibit statements, AND add a specific SyntaxError hint in `_safe_calculate` (`pac1-py/agent/dispatch.py`) that directs the LLM to rewrite as a comprehension, with a 5-run pre-commit battery of the birthday task (t012 Lukas Brenner variant) passing at ≥ 4/5.

**Expected impact:** +1 task (birthday / t012 per the plan doc impact table).

#### Acceptance Criteria
1. The `calculate()` tool schema in `pac1-py/tools.py` shall have its `description` field rewritten to explicitly state: *"Evaluate a single Python EXPRESSION against the pandas DataFrame namespace. NOT a multi-line script — no `import`, no `def`, no `for`/`while` loops, no `;` statement separators, no top-level assignment. Use list/dict comprehensions instead of loops: `[x for x in records if cond(x)]` not `for x in records: ...`. If you need intermediate variables, use a comprehension with `(expr for x in records if cond)` or nested `df.query()` / `df.apply()` calls."*
2. The tool-schema description SHALL additionally include **at least two concrete examples** of correct expression-style usage: one comprehension example and one pandas `.apply(lambda: ...)` example, sized short enough to fit inside the tool description without bloat.
3. The function `_safe_calculate` in `pac1-py/agent/dispatch.py` shall, when `compile(expression, "<calculate>", mode="eval")` raises `SyntaxError`, catch the exception and return a structured error response whose `message` (or equivalent error-hint field) contains the text: *"calculate() accepts only Python expressions, not statements. Rewrite as a comprehension: `[x for x in records if cond(x)]` instead of `for x in records: ...`. Do not use `import`, `def`, `for`, `while`, or `;`."*
4. The SyntaxError hint SHALL also include the original `SyntaxError` message text (offset + msg) so that the LLM can see both the specific syntax problem and the remediation direction.
5. The existing `_safe_calculate` behavior for valid expressions SHALL be preserved unchanged: the restricted-eval namespace (df, pd, records, math helpers, date_offset, days_between, text_match, parse_date), the return-type contract, and all non-SyntaxError exception paths.
6. WHEN a 5-run battery of the birthday task (t012 Lukas Brenner variant) is executed against the post-R5 agent, THEN the task pass rate SHALL be ≥ 4/5.
7. WHEN the agent receives the SyntaxError hint from `_safe_calculate`, THE agent SHALL (per the updated tool description) rewrite the next `calculate()` call as a single expression on its next attempt, rather than retrying the same multi-line script pattern.
8. The full 104-task PAC1-Prod benchmark shall still score ≥ 91/104 on any individual run after R5 lands, and shall contribute to the multi-run ≥ 99/104 average measured under Requirement 8.

### Requirement 6: Multilingual inbox-processing verb support
**User Story:** As a pac1-py maintainer, I want the inbox-processing verb-class synonymy passage in `pac1-py/skills/inbox-processing/SKILL.md` (landed in Phase D R-DT24 as an English-only list) to be extended with Chinese, Japanese, Spanish, German, and Arabic equivalents for "process", "handle", "review", "take care of", so that Chinese-language task prompts like "处理收件箱中的下一条消息" do not bypass the full inbox workflow by falling outside the English-only verb list.

**Objective:** Extend the existing verb-class synonymy passage in `inbox-processing/SKILL.md` with multilingual verb entries, preserving the Phase D R-DT24 English list verbatim, with a 5-run pre-commit battery of t035 passing at ≥ 4/5.

**Expected impact:** +1 task (t035 per the plan doc impact table).

#### Acceptance Criteria
1. The file `pac1-py/skills/inbox-processing/SKILL.md` shall extend its existing verb-class synonymy passage (landed in Phase D R-DT24, currently enumerating English verbs "process", "handle", "take care of", "work through", "review", "deal with", "go through", "manage") with **multilingual equivalents** for at minimum the following languages: Chinese (Mandarin), Japanese, Spanish, German, and Arabic.
2. The Chinese verb list SHALL include at minimum: `处理` (process/handle), `回复` (reply to), `看一下` (take a look / review), `管理` (manage), `办理` (handle/process), with each term glossed in English alongside so the LLM can disambiguate.
3. The Japanese verb list SHALL include at minimum: `処理する` (process), `対応する` (handle/respond), `確認する` (review/verify), `返信する` (reply).
4. The Spanish verb list SHALL include at minimum: `procesar`, `manejar`, `revisar`, `atender`, `responder`.
5. The German verb list SHALL include at minimum: `bearbeiten`, `behandeln`, `prüfen`, `beantworten`, `erledigen`.
6. The Arabic verb list SHALL include at minimum: `معالجة` (process), `التعامل مع` (deal with), `مراجعة` (review), `الرد` (reply).
7. The multilingual verb extension SHALL be **additive** — the Phase D R-DT24 English verb list and its anti-pattern anchor ("a 'review and summarize' plan that omits the required writes is a planner bug") SHALL be preserved verbatim. The multilingual section is added as a sub-paragraph or bullet block immediately below the existing English list.
8. The multilingual verb extension SHALL make explicit that **all listed verbs across all listed languages invoke the full inbox-processing workflow** (same Phase 5 action requirement as the English verbs), so that a Chinese `处理` task triggers the same write-requiring workflow as an English "process" task.
9. WHEN a 5-run battery of task `t035` (Chinese prompt `处理收件箱中的下一条消息`) is executed against the post-R6 agent, THEN the t035 pass rate SHALL be ≥ 4/5.
10. The full 104-task PAC1-Prod benchmark shall still score ≥ 91/104 on any individual run after R6 lands, and shall contribute to the multi-run ≥ 99/104 average measured under Requirement 8.

### Requirement 7: OCR umlaut / special-character byte-for-byte preservation (OPTIONAL, P4)
**User Story:** As a pac1-py maintainer, I want OCR-to-frontmatter migration tasks to copy the `counterparty` field (and other load-bearing string fields) byte-for-byte from the source ASCII table into the YAML frontmatter, rather than letting the LLM paraphrase the value and drop umlaut characters (e.g. "Düsenschmiede" → "Düenschmiede"), so that OCR tasks on data with non-ASCII characters produce faithful migrations.

**Objective:** **OPTIONAL, P4 priority.** Add a byte-for-byte field-copy step to the OCR-task handling path in `pac1-py/agent/dispatch.py` (or equivalent) that bypasses the LLM for specific high-risk fields (`counterparty`, `supplier`, vendor names with non-ASCII characters). If the implementation does not land cleanly in a single commit without expanding R7's scope, R7 MAY be closed as "accepted LLM capability limit" per Phase E's SCOPE BOUNDARIES item 8.

**Expected impact:** +0-1 task (t018 per the plan doc impact table, tagged as P4 / low-impact / potentially model-capability-limited).

#### Acceptance Criteria
1. Where the OCR migration path is pursued, the post-R7 agent SHALL, during any task that involves reading an ASCII-table source and writing YAML frontmatter, copy specific high-risk string fields (at minimum: `counterparty`, `supplier`, any field whose value contains non-ASCII characters) **byte-for-byte** from the source ASCII table into the frontmatter output, WITHOUT LLM paraphrasing.
2. The byte-for-byte copy SHALL preserve all non-ASCII characters verbatim, including umlauts (ä, ö, ü, Ä, Ö, Ü, ß), accented characters (é, è, à, ç, etc.), and CJK characters.
3. IF the byte-for-byte copy cannot be implemented as an additive helper in a single commit without expanding scope (e.g. requires a new LLM pass, a new tool schema, or restructuring the OCR task flow), THEN R7 MAY be closed as **"accepted LLM capability limit"** in the Phase E completion report, with explicit documentation that t018 remains a known failure mode pending base-model upgrade.
4. WHERE R7 is pursued, a 5-run battery of task `t018` SHALL be executed against the post-R7 agent, and the t018 pass rate SHALL be ≥ 3/5 (relaxed threshold for P4 requirement). If t018 fails to reach 3/5 even with R7 landed, R7 shall be rolled back and closed as "accepted LLM capability limit".
5. WHERE R7 is closed without landing, the Phase E completion report SHALL explicitly record *"R7 closed as accepted LLM capability limit; t018 remains a known failure mode on non-ASCII OCR migration; base-model upgrade required for full coverage"*.
6. The full 104-task PAC1-Prod benchmark shall still score ≥ 91/104 on any individual run after R7 lands (or after R7 closure), and shall contribute to the multi-run ≥ 99/104 average measured under Requirement 8.

### Requirement 8: Honest multi-run benchmark verification
**User Story:** As a pac1-py maintainer, I want the full 104-task `bitgn/pac1-prod` benchmark to be re-run **multiple times** after Phase E and to be reported as a multi-run average with per-task pass-rate distribution, so that per-task stochastic failure floors (observed in rounds 1–3) cannot mask or fake either a regression or a fix, and so that the (a)/(b)/(c)/(d) attribution taxonomy from Phase A / C / D remains the operational standard for Phase E acceptance.

**Objective:** Apply Phase D R6's multi-run verification protocol to Phase E, with the per-run bar set to ≥ 91/104 (preserve current score) and the multi-run average bar set to ≥ 99/104 (95.2% target).

#### Acceptance Criteria
1. After all of Requirements 1, 2, 3, 4, 5, 6, and (where pursued) 7 land, the pac1-py maintainer SHALL execute the full 104-task `bitgn/pac1-prod` benchmark against the post-Phase-E agent **at least three independent times**, with each run capturing all 104 task outcomes verbatim into the Phase E completion report.
2. The Phase E completion report SHALL record each individual full-benchmark run's `passed/104` score on its own line, alongside the run's date, the LLM model identifier (`openai/qwen3.5:27b-q4_K_M` unless explicitly upgraded out of scope), the git commit hash of the agent under test, and any LLM provider configuration (temperature, seed, etc.) that affects determinism.
3. The Phase E completion report SHALL compute and record the **multi-run average** as `(sum of passed) / (3 * 104)` (or a higher denominator if more than 3 runs were performed). The acceptance bar for Phase E is **multi-run average ≥ 99/104** (≈ 95.2%), NOT "≥ 99/104 on any single run". Optimistic target is ≥ 100/104 (96.2%).
4. The Phase E completion report SHALL record the **per-task pass-rate distribution** across the multi-run battery: for each task `t001`–`t104`, record how many runs passed and how many failed, so that any task with a non-zero per-task failure rate is visible as a stochastic-floor signal rather than masked by the multi-run average.
5. WHEN any individual task regresses on any individual run (passes in some runs, fails in others), THEN the Phase E completion report SHALL classify the regression under the **(a)/(b)/(c)/(d) taxonomy** carried forward from Phase A / C / D: `(a)` code-level refactor side-effect (R1/R3/R4/R5/R7), `(b)` skill file talking to nobody (R6), `(c)` prompt file talking to nobody (R2), `(d)` LLM non-determinism.
6. WHEN a regression is classified as `(d)` LLM non-determinism AND the per-task pass rate across the full multi-run battery is ≥ 80%, THEN the single-run failures are accepted as stochastic-floor behavior and do NOT block Phase E acceptance.
7. IF the multi-run average is below 99/104, THEN the Phase E maintainer SHALL either (i) iterate on the Phase E requirements with additional fixes before declaring Phase E complete, or (ii) honestly accept the gap in the completion report with attribution under the (a)/(b)/(c)/(d) taxonomy and explicit documentation of which failure patterns remain unresolved. The Phase E maintainer SHALL NOT address a sub-target multi-run average by re-adding any Phase A deleted logic or by introducing per-task hardcoding (this is the anti-masking guard from Requirement 9).
8. The Phase E completion report SHALL cross-reference the round-3 baseline (91/104 = 87.5% per `pac1-prod-improvement-plan.md`) and record the per-requirement impact attribution (which tasks each of R1–R7 actually moved from failing to passing across the multi-run battery).

### Requirement 9: Anti-masking guard (carries forward from Phase A R6.4 / Phase C R6 / Phase D R7)
**User Story:** As a pac1-py maintainer, I want the four Phase A deletions to stay gone after Phase E lands, I want the prohibition on new structured machine-readable compliance tags to be carried forward verbatim, and I want the Phase E edit surface to be restricted to the allowlist in the Introduction, so that any Phase E regression is addressed through further prompt/skill/code changes within the allowlist, through further architectural refactor, or through honest acceptance — never by re-adding framework-level business logic, by re-introducing a parser, or by hardcoding per-task branches.

**Objective:** Carry forward Phase A R6.4 / Phase C R6 / Phase D R7 verbatim into Phase E, extending the prohibition to cover (a) the no-per-task-hardcoding constraint from Phase E's SCOPE BOUNDARIES item 7, (b) the no-extra-workspace-path-hardcoding constraint from SCOPE BOUNDARIES item 3, and (c) the edit-surface allowlist from the Introduction.

#### Acceptance Criteria
1. The `pac1-py` codebase shall not contain a function named `extract_decision_outcome` in `agent/validator.py` or anywhere else after Phase E lands.
2. The `pac1-py` codebase shall not contain a tool schema whose `name` is `plan_compliance` in `pac1-py/tools.py` or anywhere else, and the `TaskManager` class in `pac1-py/tasks.py` shall not define a `_compliance` attribute, a `set_compliance` method, or a `get_compliance` method.
3. The `pac1-py/agent/executor.py` module shall not contain any block that checks the task text for the substrings `sorted alphabetically` or `alphabetical order`, nor any post-processing step that re-sorts the lines of `message` after `validate_completion` returns.
4. The `pac1-py/agent/dispatch.py` module shall not contain any branch that inspects whether a `read` tool's `path` argument starts with `inbox/` or `/inbox/`, nor any code that appends the string `[SECURITY CHECK]` (or any equivalent inbox-specific warning block) to the result of the `read` tool.
5. WHEN the grep `rg 'extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py` runs after the Phase E commits, THEN it SHALL return zero hits.
6. WHEN the grep `rg 'sorted alphabetically|alphabetical order|post-process: re-sorted' pac1-py/agent/executor.py` runs after the Phase E commits, THEN it SHALL return zero hits.
7. WHEN the grep `rg '\[SECURITY CHECK\]|This file is from the inbox' pac1-py/agent/dispatch.py` runs after the Phase E commits, THEN it SHALL return zero hits.
8. **No new structured machine-readable compliance tag** shall be introduced as part of Phase E — neither under the name `plan_compliance` nor under any new name (`compliance_tag`, `set_cross_account`, `record_compliance_decision`, `compliance_state`, etc.). The Phase E fixes for R1/R2/R3/R4/R5/R6/R7 are either code-level data-shape changes (R1, R3, R4, R5, R7), prompt narrative edits (R2), or skill narrative edits (R6); no parser, no structured tag, no new machine-readable compliance surface is permitted.
9. **No per-task-ID hardcoding.** The post-Phase-E codebase shall not contain any branch of the form `if task_id == "tNNN": ...` or any equivalent switch on a specific benchmark task ID. All Phase E fixes SHALL generalize to the failure pattern (not the specific task instance).
10. **No workspace-path hardcoding beyond the R4 allowlist.** The post-Phase-E codebase shall hardcode workspace-relative paths ONLY for the four R4 internal lanes (`30_knowledge/`, `90_memory/`, `99_system/`, `AGENTS.md`). No other `bitgn/pac1-prod`-specific paths shall be hardcoded into the agent.
11. **Edit-surface allowlist:** R1 edits `pac1-py/agent/dispatch.py` only. R2 edits `pac1-py/agent/prompts.py` only. R3 edits `pac1-py/agent/dispatch.py` and/or `pac1-py/agent/prompts.py` only. R4 edits `pac1-py/agent/executor.py` and/or a new `pac1-py/agent/security_guard.py` only. R5 edits `pac1-py/tools.py` and `pac1-py/agent/dispatch.py` only. R6 edits `pac1-py/skills/inbox-processing/SKILL.md` only. R7 (if pursued) edits `pac1-py/agent/dispatch.py` only. Any Phase E commit that edits files outside this allowlist MUST be explicitly justified in the commit message with reference to this acceptance criterion.
12. WHEN a Phase E regression is discovered that traces back to any of the R1–R7 edits, THEN the Phase E maintainer SHALL address it through further prompt/skill/code changes within the allowlist (R1–R7), OR by honestly accepting the regression in the completion report with attribution under the (a)/(b)/(c)/(d) taxonomy from Requirement 8 — and SHALL NOT address it by re-adding `extract_decision_outcome`, `plan_compliance`, the alphabetical post-processor, or the inbox `[SECURITY CHECK]` injection to the tree, by introducing any new structured compliance tag, or by hardcoding per-task branches.
13. The pac1-py test suite shall continue to pass after Phase E lands. Any unit test that exercises `load_records`, `_safe_calculate`, the security guard, or the project-query path SHALL be updated in the same commit that changes the production code, so that no Phase E commit boundary is red.
