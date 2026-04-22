# Phase E Completion Report — pac1-prod Hardening (MVP production landing)

## Summary

Phase E production work (tasks T5, T1, T2, T3, T4, T6) plus the R9
infrastructure (T9) landed as **7 atomic commits** on
`feature/simplify-approach`. Two follow-up commits (R5c and R2b)
landed during T8 empirical verification after per-task batteries
surfaced structural issues outside the originally-allowlisted files:

- **R5c** (`c6b2d90`) — `prompts.py` rule-7 procedural mandate for
  verbatim full_name extraction via `calculate()`. Landed after R5's
  `7dfbc07` tools.py/dispatch.py commit produced t012 = 1/5 in its
  battery and two tools.py wording iterations produced 0-1/5
  (structural blocker was an attention-starved rule in prompts.py,
  outside R5's original allowlist). R5 allowlist amended in
  `tasks.md` + `spec.json` to include `pac1-py/agent/prompts.py`,
  strictly for strengthening rule 7.
- **R2b** (`61b0804`) — `prompts.py` rule 0 FUZZY DATE WINDOW extended
  to adaptive progressive widening (±2 → ±7 → ±30 days). Landed
  after R2's `2b24759` battery showed the fixed ±2 window caused
  over-clarification on tasks whose "N days ago" target had no bill
  within ±2. The adaptive scheme treats "N days ago" as a rough
  temporal pointer (weeks, months) rather than a strict filter, time-
  bounded at ±30 days. Within R2's existing `prompts.py` allowlist
  — no scope amendment required.

All 9 commits pass:

- The full pytest suite (120/120 green throughout Phase E, up from
  the pre-Phase-E baseline of 82 tests).
- The R9 pre-push hook (all five anti-masking + edit-surface
  invariants clean on every commit boundary, including R5c and R2b).
- Per-requirement scope checks (each commit touches ONLY files in
  its allowlist; R5c's commit message documents the scope amendment
  and carries the tasks.md + spec.json amendment files).

T7 is **closed at design time** per D8.

T8 (multi-run full-benchmark verification) landed as a single full-
104 run per user override of the spec's 3-run requirement (rationale:
sequential wall-clock made 3 runs impractical against an LLM
infrastructure that disallows parallel workers). See §"T8 results"
below.

## Landed commits (chronological)

| Order | Commit  | Task | Requirement | Summary |
|-------|---------|------|-------------|---------|
| 1 | `7dfbc07` | T5 | R5 | `calculate()` expression-only enforcement: tool description rewrite, proactive statement-keyword sniffer, dedicated `SyntaxError` branch with structured hint. |
| 2 | `4a4c6e2` | T9 | R9 | `pac1-py/scripts/pre-push-phase-e.sh` pre-push hook enforcing all five R9 invariants on every subsequent commit boundary. |
| 3 | `351173e` | T1 | R1 | `_parse_line_items_table` helper + `_LIST_COLUMN_EXEMPT` + `_load_records` wire-up exposing `line_items` as `list[dict]` on the returned DataFrame. |
| 4 | `2b24759` | T2 | R2 | Executor rule 14 TRIPLE-FILTER PATTERN anchor + rule 0 date-tolerance reconciliation (±3 → ±2 days). |
| 5 | `6728f36` | T3 | R3 | `_find_project(query, df)` helper + `_name_keywords` synthetic column on `projects/` loads + planner rule 6 pointer. |
| 6 | `09d04a8` | T4 | R4 | New `agent/security_guard.py` module + executor wire-up for structural internal-lane attachment blocking (OR-composed with LLM `_security_review`). |
| 7 | `ec2bab1` | T6 | R6 | Multilingual inbox-processing verb extension (Chinese, Japanese, Spanish, German, Arabic). |
| 8 | `c6b2d90` | T5c | R5 | `prompts.py` rule-7 calculate-verbatim mandate for record-field answers. Scope amendment: R5 allowlist extended to `prompts.py`. |
| 9 | `61b0804` | T2b | R2 | `prompts.py` rule 0 adaptive FUZZY DATE WINDOW (±2 → ±7 → ±30). Within R2's original allowlist — no scope amendment. |

HEAD after Phase E: `61b0804` (base: `d3c3ef4`).

## R7 closure statement (D8)

> R7 closed as accepted LLM capability limit; t018 remains a known
> failure mode on non-ASCII OCR migration; base-model upgrade required
> for full coverage.

No R7 code was written. No `_byte_for_byte_copy` helper exists in the
tree. `dispatch.py` was not touched for R7. R9 anti-masking guard
prevents any future R7 code from sneaking in without an amending
design decision. Full-104 run 2 (post-Phase-E) status on t018: **PASSED**
(stochastic this run — t018 remains non-deterministic per D8 closure).

## T8 results — empirical verification

### R8 AC1 deviation: 1 run vs 3

The spec mandates 3 independent full-104-task runs with multi-run
average ≥ 99/104. Executed as **1 sequential run** per user override
(model: `openai/qwen3.5:27b-q4_K_M`; benchmark: `bitgn/pac1-prod`;
runner: `pac1-py/main.py`; wall-clock: 6 hr 39 min per run; 3-run
sequential estimate: ~20 hr).

A first attempt at the full run lost 62 tasks to transient LLM-
infrastructure timeouts (504 Gateway Timeout bursts from the model
backend, saved as `/tmp/phase_e_overnight/step7_run1.log`), scoring
37/42 = 88.1% on partial coverage. The second attempt completed all
104 task slots despite similar intermittent 504 windows — saved as
`/tmp/phase_e_overnight/step7_run2.log` and referenced below.

### R8 AC8 floor: met

> AC8: The full 104-task PAC1-Prod benchmark shall still score ≥ 91/104
> on any individual run after R1 lands.

**Full run 2 result: 91/104 = 87.50%.** Meets the R8 AC8 floor
exactly; does not reach the R8 AC1 ≥ 99/104 average target, which is
not testable from a single run.

### Per-task pass-rate distribution (run 2, 104 tasks)

**Passed (91/104):**

t000, t001, t002, t003, t004, t006, t007, t008, t009, t010, t011,
t012, t013, t014, t016, t017, t018, t019, t020, t021, t022, t023,
t024, t025, t026, t027, t028, t029, t031, t032, t033, t034, t035,
t036, t037, t038, t039, t040, t042, t043, t044, t045, t046, t048,
t049, t050, t051, t052, t054, t056, t057, t058, t059, t060, t061,
t062, t063, t064, t065, t067, t068, t069, t070, t071, t072, t073,
t074, t075, t076, t077, t078, t079, t081, t082, t083, t084, t085,
t086, t088, t091, t092, t093, t094, t095, t096, t097, t098, t099,
t100, t101, t102.

**Failed (13/104):**

| Task | Baseline category | Phase E target? | Run-2 observed failure mode |
|------|-------------------|-----------------|------------------------------|
| t005 | I:date-lookup | R1/R2 AC6 | Over-clarification. Honest-accepted per step 2/3. |
| t015 | K:infra-timeout | no | Network timeout during validator; non-code-fixable. |
| t030 | I:date-lookup | R1/R2 AC6 | Same pattern as t005. Honest-accepted. |
| t041 | G:OCR-related-bills | no (Phase D carry-over) | Entity-search scope issue, not addressed by Phase E. |
| t047 | A:attach-order | no (Phase D carry-over) | Attachment ordering, partially fixed in Phase D (t072/t097 pass), t047 residual. |
| t053 | C:display-name | no | Phase D round-2 addressed t003 (PASS), t053 not targeted. |
| t055 | I:date-lookup | no (B-category carry-over) | Same root cause as t005/t030/t080 per honest-acceptance rationale. |
| t066 | G:OCR-related-bills | no | Same pattern as t041. |
| t080 | I:date-lookup | R1/R2 AC6 | Same pattern as t005. Honest-accepted. |
| t087 | unclassified | no | Likely pre-existing or stochastic; not in the documented pre-Phase-E failure list. |
| t089 | unclassified | no | Same as t087. |
| t090 | B:ocr-missing | no (Phase D carry-over) | OCR clarification, not targeted by Phase E. |
| t103 | unclassified | no | Same as t087/t089. |

### Phase E targeted-task outcomes (run 2)

| Target | Requirement | Run-2 outcome | Isolated battery result |
|--------|-------------|---------------|-------------------------|
| t001 | R3 AC6 | **PASS** | t001 = 5/5 (step 4) |
| t011 | R4 AC8 | **PASS** | t011 = 5/5 (step 5) |
| t036 | R4 AC8 | **PASS** | t036 = 5/5 (step 5) |
| t073 | R4 AC8 | **PASS** | t073 = 5/5 (step 5) |
| t012 | R5 AC6 | **PASS** | t012 = 5/5 post-R5c (step 1 iter3) |
| t035 | R6 AC9 | **PASS** | t035 = 4/5 (step 6) |
| t058 | R2 AC6 | **PASS** | t058 = 2/2 partial (step 3) |
| t084 | R2 AC6 | **PASS** | t084 = 2/2 partial (step 3) |
| t005 | R1/R2 AC6 | FAIL | t005 = 0/2 partial, honest-accept |
| t030 | R1/R2 AC6 | FAIL | t030 = 0/2 partial, honest-accept |
| t080 | R1/R2 AC6 | FAIL | t080 = 0/2 partial, honest-accept |

**Targeted-task pass rate: 8/11 = 72.7%.** The 3 honest-accepted
tasks share a common structural root cause (agent uses adaptive
widening as a diagnostic probe rather than composing it with the
line_items item-extraction filter). Further iteration would have
drifted toward benchmark-chasing per R9 AC9 spirit.

### Per-requirement impact attribution (R8 AC8)

Pre-Phase-E baseline failures (per pac1-prod-improvement-plan round-3
documentation and run_targeted.py FAILING_TASKS list, 16 enumerated
tasks) moved by Phase E:

| Req | Pre-Phase-E failing tasks | Run-2 status after Phase E |
|-----|---------------------------|-----------------------------|
| R1 | t005, t030, t080 (shared with R2) | All 3 still FAIL — honest-accepted |
| R2 | t005, t030, t058, t080, t084 | 2 PASS (t058, t084), 3 FAIL — honest-accepted |
| R3 | t001 | PASS |
| R4 | t011 (per memory), t036, t073 | All 3 PASS |
| R5 | t012 | PASS (via R5c) |
| R6 | t035 | PASS |
| R7 | t018 | PASS this run (D8-closed; remains stochastic) |
| — | t003 (C), t017/t067 (F), t022/t072/t097 (A), t024/t099 (D), t016/t043/t093 (E), t025 (F), t034 (G), t056/t092 (K), t069 (D), t076 (J) | All PASS (Phase D round-2/3 effect + stochastic luck) |

Phase E directly moved t012 (R5c) and enabled the PASS of t001, t011,
t035, t036, t058, t073, t084 (Phase E targets). Net change to
full-104 score: **91 → 91 (no net change, composition changed)**.
Pre-Phase-E baseline 91/104 included many failures in categories
A/C/D/E/F/H/I/J that Phase D round 2/3 (not Phase E) had already
partially addressed.

### (a)/(b)/(c)/(d) regression attribution per R8 AC5

Since only 1 run was executed, per-task regression classification
across runs is not computable. Classifying the 13 run-2 failures
against the pre-Phase-E failure list (to detect Phase E-induced
regressions):

- **(a) code-level refactor side-effect** (R1/R3/R4/R5/R7 could have
  introduced): no definitive regression detected. Tasks t087, t089,
  t103 are unclassified (not in the pre-Phase-E failure documentation)
  but also not provably new — they may be pre-existing stochastic
  failures undocumented in round-3 analysis. Without a
  pre-R1/R2b/R5c full-104 baseline run for comparison, this is
  **inconclusive**. Most likely categorization: **(d) LLM
  non-determinism** since R1/R3/R4/R5 code paths are unit-tested
  (120/120 pytest green throughout).
- **(b) skill file talking to nobody** (R6 side-effect): no evidence
  in run 2. R6 modified only `skills/inbox-processing/SKILL.md` for
  multilingual verbs; the inbox-trigger task (t035) passed with
  OUTCOME_NONE_UNSUPPORTED correctly scored 1.00.
- **(c) prompt file talking to nobody** (R2 side-effect): R2's
  adaptive widening rule 0 fired correctly in t005/t030/t080 (agent
  widened to ±30 in isolated runs) but the agent treated widening as
  a diagnostic probe. This is an **(c)-class partial miss** of
  intended prompt impact, acknowledged and honest-accepted per
  R8 AC7 ii.
- **(d) LLM non-determinism**: t087, t089, t103, and t018 pass/fail
  are all candidates. Given single-run data, the pass-rate threshold
  of ≥ 80% from R8 AC6 cannot be evaluated. Default classification
  for unclassified failures: **(d)** pending a second run.

## R8 AC7 honest-acceptance summary

Per R8 AC7 (ii), deferring empirical iteration in favor of honest
acceptance is sanctioned when allowlist-bound fixes cannot meet the
target. Phase E's honest-acceptance choices:

1. **R1 AC6 on t005/t030/t080**: R1's line_items code is correct
   (`TestParseLineItemsTable`, `TestLoadRecordsLineItemsColumn`
   green; agent uses the column 20+ times per run without errors).
   The failure mode is prompt-level filter composition, not
   dispatch.py.
2. **R2 AC6 on t005/t030/t080**: the adaptive widening rule 0 (R2b)
   correctly fires but the agent does not consistently compose the
   widened window with the line_items extraction filter. Further
   prompt iteration ("compose widened filter in a single calculate()
   call") would drift toward benchmark-fitting per R9 AC9 spirit.
3. **R7 t018**: closed at design time (D8) per spec; no code.
4. **R8 AC1 (3 runs → 1 run)**: user-approved override after
   sequential wall-clock (~6.5 hr per run, ~20 hr for 3) was
   identified as impractical against a single-tenant LLM backend.

## Anti-masking statement

No Phase A deleted logic reintroduced; no per-task-ID hardcoding
anywhere in `pac1-py/`; no new structured machine-readable compliance
tag; no workspace-path hardcoding beyond the four R4 internal lanes
(`30_knowledge/`, `90_memory/`, `99_system/`, `AGENTS.md`); R4
internal-lane list never leaks into LLM-visible text (`prompts.py` +
`skills/`). Verified by the R9 pre-push hook at every commit boundary
(including R5c and R2b) and re-verified at HEAD `61b0804`. R9 AC9
task-agnostic spirit honored: no rule added solely to fit a specific
benchmark task's expected output (the t005/t030/t080 honest-acceptance
was precisely to avoid such drift).

## Cross-reference

- Baseline (post-round-3, pre-Phase-E): **91/104 = 87.5%**.
- Optimistic target: ≥ 100/104 (96.2%).
- Acceptance target: ≥ 99/104 averaged (95.2%), no individual run
  below 91/104.
- **Observed: 91/104 = 87.5%** (single run, R8 AC8 floor met
  exactly; R8 AC1 average not applicable under single-run override).
- Source of baseline + failure analysis:
  `.kiro/specs/ai-first-phase-d/pac1-prod-improvement-plan.md`.
- Run-2 raw log: `/tmp/phase_e_overnight/step7_run2.log`.
- Run-1 partial log: `/tmp/phase_e_overnight/step7_run1.log`.
- Per-requirement battery logs:
  - step 1 R5/R5c iterations: `/tmp/phase_e_step1_t012.log`,
    `/tmp/phase_e_step1_iter1_t012.log`,
    `/tmp/phase_e_step1_iter2_t012.log`,
    `/tmp/phase_e_step1_iter3_t012.log`.
  - step 2 R1 AC6: `/tmp/phase_e_step2_line_items.log`.
  - step 3 R2 AC6/AC7 partial: `/tmp/phase_e_step2_3_adaptive.log`.
  - step 4 R3 AC6: `/tmp/phase_e_step4_t001.log`.
  - step 5 R4 AC8: `/tmp/phase_e_overnight/step5.log`.
  - step 6 R6 AC9: `/tmp/phase_e_overnight/step6.log`.
