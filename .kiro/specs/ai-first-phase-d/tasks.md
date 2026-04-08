# Implementation Plan — Phase D (Outcome-Protocol Isolation and Compliance-Anchor Cleanup)

## Edit order (locked)

```
T1 (R1) → T2 (R2) → T3 (R3) → T4 (R4 = R-DOI, ATOMIC across 4 files) → T5 (R5 conditional, R-DT17R) → T6 (R6 multi-run benchmark) → T7 (R7 + completion report)
```

This order is locked by design.md §"Edit Order and Smoke-test Checkpoints"
and by D7 (Commit atomicity rules per requirement). The rationale is:

- **T1 = R1** first because the bundled R-DT20a + R-DT20b cross-account
  anchors in `compliance-check/SKILL.md` step 3 are the highest-risk single
  edit (D8 Risk #1: cross-account over-flag regression risk on t17). Landing
  R1 by itself means the t20 + t37 + t17 5-run pre-commit batteries
  attribute their pass/fail signal solely to the R1 anchor wording, not to
  a blend of R1 + R2 + R3. R1 also lives in the safest single-file edit
  surface in Phase D — one skill file, step 3 only.
- **T2 = R2** second because the verb-class synonymy passage in
  `inbox-processing/SKILL.md` is a single insertion above Phase 1 with a
  narrow t24 5-run pre-commit battery as its only empirical gate. T2 has
  zero interference risk with T1 (different file, different LLM-reading
  path: T1 governs compliance reasoning, T2 governs planner verb
  interpretation).
- **T3 = R3** third because the validator-prompt hardening (two new bullets
  inside `build_validator_system`'s `<checks>` block) introduces the most
  expensive pre-commit gate in Phase D: a four-battery regression matrix
  (t43 + t17 + t24 + t37). T3 must land AFTER T1 and T2 so the regression
  batteries can verify the new bullets do not over-fire on tasks already
  fixed by R1/R2 anchors. T3 also touches `prompts.py`, the same file as
  T4 — the two edits are structurally disjoint per D11 (T3 edits
  `build_validator_system` at lines 188–211; T4 edits `OUTCOME_CODES_DOC`
  at lines 55–64) but T3 must land first so T4's R-DOI refactor sees a
  stable narrative-anchor baseline.
- **T4 = R4 (R-DOI)** fourth, as a single atomic commit covering 4 files
  (`outcomes.py` new + `dispatch.py` + `executor.py` + `prompts.py`) plus
  one conditional 5th file (`tests/test_dispatch.py`, grep-gated). The
  R-DOI architectural refactor lands LAST among production commits because
  its regression surface is structurally different from T1/T2/T3's
  narrative surface — bundling T4 with any narrative commit would conflate
  two distinct failure-attribution dimensions. **See the Atomic-commit
  invariant section below for the T4 multi-file invariant and the D11
  prompts.py disjoint-region invariant.**
- **T5 = R5 (R-DT17R) gap-extension** fifth, **CONDITIONAL**: the live
  re-audit step at the head of T5 may flip T5 to vacuous-satisfaction. The
  design's D9 audit (this design document, against the case-study corpus)
  found gaps on `review` and `take care of` and prescribes a six-verb
  extension to the validator's inbound verb list at `prompts.py:196–207`.
  T5's first action is to RE-RUN the audit against the live 43-task
  corpus. If the live re-audit confirms the gap, T5 commits the verb-list
  extension. If the live re-audit disagrees with the design audit, T5
  closes vacuously by recording the audit result in the verification log
  with no commit. See task body for the explicit re-audit protocol.
- **T6 = R6 multi-run benchmark verification** runs the full 43-task PAC1
  benchmark **three independent times** per D5, computes the multi-run
  average against the ≥ 42/43 acceptance bar, and writes the per-task
  pass-rate distribution. Pure verification task — no production commit.
  Cost: ~4 hours wall-clock time.
- **T7 = R7 anti-masking guard final check + `phase-d-completion-report.md`**
  produces the spec-deliverables artifact. Pure process task — no
  production commit. Includes the commit-hash trail for T1–T5, the
  multi-run benchmark result from T6, the R-DT17R audit result, and the
  explicit "no Phase A deleted logic reintroduced" anti-masking statement
  per the Phase A and Phase C precedent.

Each step's "Scope check" must run `git diff --stat HEAD~1` against the
allowed-files list below. Any file outside the list in the diff is a scope
violation and must be reverted before the commit can proceed.

## Scope enforcement

### Allowed files for Phase D edits (authoritative 6-file list)

1. `pac1-py/skills/compliance-check/SKILL.md` (T1 — R1 step 3 expansion only)
2. `pac1-py/skills/inbox-processing/SKILL.md` (T2 — R2 verb-class synonymy
   subsection insertion only)
3. `pac1-py/agent/prompts.py` (T3 — R3 `<checks>` bullets 3 and 4 inside
   `build_validator_system` only; T4 — R4 `OUTCOME_CODES_DOC` migration at
   lines 55–64 + import only; T5 conditional — R5 inbound verb-list
   extension at lines 196–207 only)
4. `pac1-py/agent/dispatch.py` (T4 — R4 `OUTCOME_BY_NAME` migration at
   lines 32–38 + import only)
5. `pac1-py/agent/executor.py` (T4 — R4 import update at line 15 +
   bare-literal migration at lines 208, 232, 237, 261, 366, 379, 385 only)
6. `pac1-py/agent/outcomes.py` (T4 — **NEW FILE**, R-DOI target module)

### Conditionally allowed file (grep-gated)

7. `pac1-py/tests/test_dispatch.py` — Allowed in T4 ONLY IF the pre-commit
   grep `rg 'from agent\.dispatch import.*OUTCOME_' pac1-py/tests/test_dispatch.py`
   returns at least one hit. If the grep returns zero hits, this file
   stays in the forbidden list.

### Forbidden files in Phase D (scope violation if touched)

- **Every Python file under `pac1-py/agent/` not in the 6-file allowlist:**
  - `pac1-py/agent/__init__.py`
  - `pac1-py/agent/bootstrap.py`
  - `pac1-py/agent/planner.py`
  - `pac1-py/agent/validator.py` (body — `validator.py` is NOT edited at
    all in Phase D per D4 rationale: it has zero hardcoded outcome-string
    constants)
  - `pac1-py/agent/context.py`
  - `pac1-py/agent/llm.py`
  - `pac1-py/agent/config.py`
- **Every non-agent Python file under `pac1-py/`:**
  - `pac1-py/main.py`
  - `pac1-py/tasks.py`
  - `pac1-py/tools.py` (D5 Non-Goal: JSON-schema enum entries at lines
    281–285, 511–515, 559–561 are LLM-runtime literals, not Python
    identifiers; they are NOT migrated)
  - `pac1-py/skills.py`
- **All files under `pac1-py/observability/**`**.
- **Every skill file NOT in the allowlist:**
  - `pac1-py/skills/identity-verification/SKILL.md`
  - `pac1-py/skills/security-posture/SKILL.md`
  - `pac1-py/skills/execution-discipline/SKILL.md`
  - `pac1-py/skills/date-arithmetic/SKILL.md`
- **All test files under `pac1-py/tests/**` except the conditional
  `test_dispatch.py`:**
  - `pac1-py/tests/conftest.py`
  - `pac1-py/tests/test_compact_tree.py`
  - `pac1-py/tests/test_skill_loader.py`
  - `pac1-py/tests/test_task_manager.py`
- **Every `AGENTS.md` / `README.md` under `pac1-py/`**.
- **The `bitgn/` tree** — the protobuf wire format is external; the
  `bitgn.vm.pcm_pb2.Outcome` enum is NOT touched.
- **Every file under `.kiro/` outside `.kiro/specs/ai-first-phase-d/`**.

Every task below includes a mandatory **Scope check**: the task's git diff
MUST touch only files from the 6-file allowlist (or the conditional
`test_dispatch.py` if its grep-gate was met) and nothing from the
forbidden list. The implementation phase MUST reject any diff that
violates this invariant.

## Parallelizability

Phase D is **fully sequential**. The chain
T1 → T2 → T3 → T4 → (T5 conditional) → T6 → T7 is locked by D7 (commit
atomicity rules) and by D8 (cross-anchor interference matrix):

- **T1 must precede T2 and T3** because the t20 + t37 + t17 5-run
  pre-commit batteries are the empirical gate for R1.8/R1.9/R1.10 and
  their measurement must attribute any rate change to the R1 step 3
  expansion in isolation, not to a blend of R1 + R2 + R3 anchors.
- **T2 must precede T3** because the t24 5-run pre-commit battery is the
  empirical gate for R2.6 and its measurement must attribute the rate
  change to the R2 verb-class subsection alone. T3's regression batteries
  (t17 + t24 + t37 alongside the t43 target) verify that R3's two new
  bullets do not regress R1 or R2 — these batteries presuppose T1 and T2
  have already landed.
- **T3 must precede T4** by the D11 atomicity invariant: both T3 and T4
  edit `prompts.py`, but in disjoint regions. T3 edits
  `build_validator_system` at lines 188–211; T4 edits `OUTCOME_CODES_DOC`
  at lines 55–64 plus one new import at the top of the file. Landing T3
  first means T4's diff to `prompts.py` operates on a known-good post-T3
  baseline, and the post-T4 grep verification (`rg 'OUTCOME_CODES_DOC\s*='
  pac1-py/agent/prompts.py` → 0 hits, meaning the constant is now defined
  only in `outcomes.py`) is mechanically checkable.
- **T4 cannot be split** across multiple commits per D7's R-DOI atomic
  invariant. The four files (`outcomes.py` new + `dispatch.py` +
  `executor.py` + `prompts.py`) must land in a single git commit because
  any phased split leaves an intermediate state where `outcomes.py` exists
  but no consumer imports from it, or where one consumer imports from
  `outcomes.py` while another still defines the same constant locally.
  See "Atomic-commit invariant" section below.
- **T5 must follow T4** because the conditional verb-list extension edits
  `prompts.py` at the same function (`build_validator_system`) that T3
  modified. T5 lands as a separate commit from T3 (per D7) so the T3
  attribution (R3 bullets 3/4) is not mixed with the T5 attribution
  (R5 verb-list gap extension).
- **T6 must follow T4 (or T5 if fires)** because the multi-run 3-run
  benchmark protocol presupposes the entire Phase D production surface
  has landed.
- **T7 must follow T6** because the completion report incorporates the
  T6 multi-run benchmark results, the per-task pass-rate distribution,
  and the (a)/(b)/(c)/(d) attribution for any regressing task.

No task in this file carries a `(P)` marker — the chain is fully linear
by design, not by absence of analysis.

## TDD adaptation note

Classical red → green → refactor does not apply uniformly to a
two-modality phase. Tasks T1, T2, T3, T5 are narrative-anchor edits and
use the same **grep-based "red/green" pattern** Phase A and Phase C used:

- **Red check** = a shell one-liner (`rg ...`) that currently captures
  the pre-edit state — either the absence of the new anchor text, or the
  presence of the to-be-renumbered bullet.
- **Green check** = a complementary `rg ...` after the rewrite that
  verifies the new anchor text is present (and the renumbered bullet
  resolves correctly).
- **Refactor** = `pytest pac1-py/tests/` must remain green (Phase D
  edits no test file in T1/T2/T3/T5, so the test suite is
  green-by-construction; pytest acts as a safety net for accidental
  YAML front-matter corruption or Python syntax errors), plus the
  per-task **5-run pre-commit batteries** described in each task body.

T4 (R-DOI) is an architectural refactor and uses a **dual-mode
verification** pattern:

- **Red check** = the discovery scan in design.md §D4 (`OUTCOME_BY_NAME`
  defined in `dispatch.py`, `OUTCOME_CODES_DOC` defined in `prompts.py`,
  7 bare-literal `"OUTCOME_*"` strings in `executor.py`).
- **Green check** = grep batteries (1 hit each for `OUTCOME_BY_NAME\s*=`
  and `OUTCOME_CODES_DOC\s*=` in `pac1-py/agent/`, both in the new
  `outcomes.py`; 0 hits for bare `"OUTCOME_` literals in `executor.py`),
  plus Python import smoke checks, plus `pytest pac1-py/tests/` 32/32
  green, plus a single 43-task PAC1 benchmark smoke run at ≥ 40/43.

T6 (multi-run benchmark) and T7 (completion report) are pure
process/verification tasks and have neither a red check nor a Python
import check; they only have action steps and a result deliverable.

The per-task 5-run pre-commit batteries are the one non-grep gate
in the chain. They run task `tXX` five consecutive times against the
locally-edited tree (do **not** commit yet) and measure the misfire
rate. The iteration ceiling per commit is 5 attempts (matching Phase C
Risk #2 and Phase D Risk #7 escalation pattern). If the ceiling is hit
without meeting the target, escalate per the D10 protocol: document
the achievable rate, defer residual brittleness to a follow-up phase,
and either land the commit with a "known misfire rate" note OR abandon
the commit. Neither escalation path may re-add Phase A deleted logic.

## Atomic-commit invariant

Two of the production commits below must land as a single atomic commit
covering multiple regions or multiple files. This mirrors Phase A's
risk-register-row-3 treatment of T4 and Phase C's T2/T3 atomicity
treatment.

### T1 atomic-commit invariant (R-DT20a + R-DT20b co-located in step 3)

T1 must land as a single git commit that contains BOTH the AM-overlap
anchor (R-DT20a) AND the business-context-description-mismatch anchor
(R-DT20b) inside step 3 of `pac1-py/skills/compliance-check/SKILL.md`.
Splitting this across two commits would leave an intermediate state
where step 3 has either the structural check without the semantic
check, or vice versa — both of which are known LLM failure modes from
the Phase C case studies (t20 + t37). R1.6 explicitly requires atomic
landing; D1's ordering rationale (structural check first, semantic
check second) means both anchors must be present for the bulleted list
to make narrative sense.

The two anchors share a single file and a single step, so the atomic
invariant here is a "two-bullets-in-one-bulleted-list" invariant rather
than a multi-file invariant. The Scope check enforces it mechanically
by verifying the diff touches exactly one file, and the Green check
verifies BOTH the AM-overlap anchor text AND the business-context anchor
text are present in step 3.

### T4 atomic-commit invariant (R-DOI four-file refactor in one commit)

T4 must land as a single git commit covering all four R-DOI files (plus
the conditional fifth):

1. `pac1-py/agent/outcomes.py` — **NEW FILE** (~65 lines) created from
   scratch with the exact content shape specified in design.md §D4.
2. `pac1-py/agent/dispatch.py` — `OUTCOME_BY_NAME` definition removed
   at lines 32–38, replaced by `from agent.outcomes import OUTCOME_BY_NAME`
   import at the top.
3. `pac1-py/agent/executor.py` — import at line 15 split into
   `from agent.dispatch import dispatch` plus `from agent.outcomes import
   OUTCOME_BY_NAME, OUTCOME_DENIED_SECURITY, OUTCOME_ERR_INTERNAL,
   OUTCOME_OK`; **all 7 bare string literals at lines 208, 232, 237, 261,
   366, 379, 385** migrated to the named constants.
4. `pac1-py/agent/prompts.py` — `OUTCOME_CODES_DOC` definition removed
   at lines 55–64, replaced by `from agent.outcomes import OUTCOME_CODES_DOC`
   import at the top of the file. The interpolation site at line 125
   (`f"<outcome-codes>\n{OUTCOME_CODES_DOC}\n</outcome-codes>"`) is
   preserved unchanged.
5. **Conditional:** `pac1-py/tests/test_dispatch.py` — IF the pre-commit
   grep `rg 'from agent\.dispatch import.*OUTCOME_' pac1-py/tests/test_dispatch.py`
   returns at least one hit, the import is updated in the same atomic
   commit. **Pre-verified at design time (2026-04-08): the grep returns
   ZERO hits — `test_dispatch.py` only imports `dispatch` and
   `truncate_output` from `agent.dispatch`. The conditional edit will
   most likely not fire, but T4's pre-commit step explicitly re-runs
   the grep before committing.**

Splitting T4 across phased commits (e.g. T4a = create `outcomes.py`;
T4b = migrate `dispatch.py`; T4c = migrate `executor.py`;
T4d = migrate `prompts.py`) would leave intermediate states where
`outcomes.py` exists but no consumer imports from it, or where one
consumer imports from `outcomes.py` while another still defines the
same constant locally. An intermediate state with both
`dispatch.py::OUTCOME_BY_NAME = {...}` and
`outcomes.py::OUTCOME_BY_NAME = {...}` would Python-import cleanly
(Python resolves the last import) but would create two sources of
truth that can drift — exactly the failure mode the R4.1 "single
source of truth" requirement exists to prevent. The atomic commit
pattern here mirrors Phase A T4's `c236dd9` and Phase C T2's `27d054e`
multi-file atomic pattern.

### D11 prompts.py disjoint-region invariant (between T3 and T4)

`prompts.py` is the only file touched by both a narrative edit (T3 for
R3) and an architectural edit (T4 for R-DOI). The two edits are
structurally disjoint:

- **T3 region:** `build_validator_system` at lines 188–211 (the
  `<checks>` block, where bullets 3 and 4 are inserted).
- **T4 region:** lines 55–64 (`OUTCOME_CODES_DOC` definition) + the
  top of the file (new `from agent.outcomes import OUTCOME_CODES_DOC`
  import).

These regions do not overlap. The implementation phase MUST verify
the separation mechanically:

- **T3 Scope check** verifies the diff for `prompts.py` touches ONLY
  the `build_validator_system` region (lines 188–211 post-T3) and does
  NOT touch `OUTCOME_CODES_DOC` at lines 55–64. Verified by:
  `rg -n 'OUTCOME_CODES_DOC' pac1-py/agent/prompts.py` → expected hits
  at lines 55 (definition) and 125 (interpolation), unchanged from
  pre-T3 state.
- **T4 Scope check** verifies the diff for `prompts.py` touches ONLY
  the `OUTCOME_CODES_DOC` region (lines 55–64) and the top-of-file
  import region, and does NOT touch `build_validator_system`. Verified
  by: `rg -n 'Empty source-files check|Exact-match semantics' pac1-py/agent/prompts.py`
  → expected hits inside `build_validator_system`, **unchanged** from
  post-T3 state (T4 must not perturb T3's work).
- **Post-T4 final check:** `rg 'OUTCOME_CODES_DOC\s*=' pac1-py/agent/`
  → exactly **ONE** hit, in `outcomes.py`. The pre-T4 hit at
  `prompts.py:55` must be gone.

These invariants are enforced at implementation time as part of T3
and T4's per-task Scope check.

---

## Tasks

- [ ] 1. Bundle R-DT20a + R-DT20b cross-account anchors into `compliance-check/SKILL.md` step 3 (T1 = R1, ATOMIC)
  - **Status:** pending
  - **Depends on:** nothing (first cut in the Phase D chain)
  - **Files (single atomic commit):**
    - `pac1-py/skills/compliance-check/SKILL.md` — step 3 at current
      lines 25–28 (the existing `## Steps` step "Check request-account
      consistency" with three bullet points). Verified from the live
      tree 2026-04-08: lines 25–28 contain exactly the four lines
      design.md §"Implementation Design — R1 Edit 1" cites as the
      "Before state".
  - **Atomic-commit invariant:** Both the AM-overlap anchor (R-DT20a,
    targeting the t20 trap) AND the business-context-description-mismatch
    anchor (R-DT20b, targeting the t37 trap) MUST land in the same git
    commit. See "T1 atomic-commit invariant" section above for the
    rationale.
  - **Red check:**
    - `rg -n '3\. \*\*Check request-account consistency\*\*' pac1-py/skills/compliance-check/SKILL.md`
      must currently return **exactly 1 hit** at line 25.
    - `rg -i 'account_manager' pac1-py/skills/compliance-check/SKILL.md`
      must currently return **0 hits** (the AM-overlap anchor is not
      yet present — this is what T1 introduces).
    - `rg -i 'descriptors' pac1-py/skills/compliance-check/SKILL.md`
      must currently return **0 hits** (the business-context anchor is
      not yet present).
    - `rg -i 'deliberate test condition' pac1-py/skills/compliance-check/SKILL.md`
      must currently return **0 hits**.
    - If any of these red-check hit counts disagrees with the expected
      pre-edit state, stop and re-read design.md §"Implementation
      Design — R1" before proceeding — the file may have drifted from
      the design's verified baseline.
  - **Action (single atomic commit):**
    1. **Edit 1 (R1.1, R1.2) — insert R-DT20a AM-overlap anchor as a
       new bullet inside step 3.** After the existing first bullet ("If
       a contact asks for data (invoices, records), that data must
       belong to THEIR account") and before the existing "If a contact
       from Company A…" bullet, insert a multi-sentence bullet stating:
       *"A contact's 'own account' is determined SOLELY by the
       `account_id` field in the contact's record. Do NOT consult the
       `account_manager` field on `accounts/*.json` records to
       authorize cross-account requests. Same-person-as-account-manager-
       for-multiple-accounts is a deliberate test condition, not an
       authorization. If the request mentions a company different from
       the contact's `account_id`, it is cross-account regardless of
       any `account_manager` overlap."* The exact wording is in
       design.md §D1 "After state" — the implementation phase may
       refine prose but must preserve the anchored semantics.
    2. **Edit 2 (R1.3, R1.4) — insert R-DT20b business-context anchor
       as a second new bullet, immediately after Edit 1.** The bullet
       states: *"When the message body describes a target account
       using descriptive phrases (industry terms like 'digital-health'
       or 'manufacturing', regional descriptors like 'Berlin' or
       'DACH', or workflow/narrative keywords like 'triage backlog' or
       'COO introduction') rather than a literal company name, extract
       the key descriptors from the message and compare them against
       the sender's `account.description`, `account.industry`,
       `account.region`, and `account.notes` fields. If the descriptors
       in the message DO NOT match the sender's account profile, this
       is a cross-account request — STOP and report
       `OUTCOME_NONE_CLARIFICATION`."* The bullet must name at least
       three example descriptor types per R1.4: industry, regional,
       and workflow/narrative.
    3. **Ordering invariant (R1.5, D1 rationale):** AM-overlap (Edit 1)
       comes BEFORE business-context (Edit 2) inside step 3. The
       structural check (R-DT20a) is read first by the LLM as a
       deterministic field comparison; the semantic check (R-DT20b)
       is read second as a fuzzier reasoning step. The two anchors are
       co-located within the existing step 3 bulleted list — they are
       NOT promoted to a new top-level header (no "3a" / "3b"
       sub-section creation).
    4. **No other changes.** The existing first bullet ("If a contact
       asks for data…"), the existing third bullet ("If a contact from
       Company A…"), and the existing fourth bullet ("Compare the
       account mentioned…") are preserved verbatim in their original
       positions. The two new anchors are *added*, not *replacing*.
  - **Preserve (R1.7):**
    - `compliance-check/SKILL.md` YAML front-matter (lines 1–4),
      `# Compliance Check` header (line 6), intro paragraph (line 8),
      `## When to use this skill` section (lines 10–15), `## Steps`
      header (line 17), step 1 (line 19), step 2 (lines 20–24), step 4
      (lines 29–35, the Phase C narrative-reasoning step preserved
      from commit `27d054e`), step 5 (lines 36–44), and `## Key
      principles` (lines 46–52) are byte-for-byte unchanged.
    - The "cross-account request is the ONLY hard block" principle
      (line 43–44) is preserved verbatim.
    - The operational-flag list (`security_review_open`,
      `external_send_guard`, `nda_signed`, `privacy_sensitive`,
      `ai_insights_subscriber` → note but proceed, lines 39–42) is
      preserved verbatim.
  - **Green check:**
    - `rg -i 'account_manager' pac1-py/skills/compliance-check/SKILL.md`
      returns **≥ 1 hit** (the new AM-overlap anchor mentions
      `account_manager`).
    - `rg -i 'deliberate test condition' pac1-py/skills/compliance-check/SKILL.md`
      returns **≥ 1 hit** (the same-person-as-AM disclaimer from R1.2).
    - `rg -i 'descriptors|description|industry' pac1-py/skills/compliance-check/SKILL.md`
      returns **≥ 3 hits** (one per descriptor-type example required
      by R1.4).
    - `rg '3\. \*\*Check request-account consistency\*\*' pac1-py/skills/compliance-check/SKILL.md`
      returns **exactly 1 hit** (the step 3 header is preserved).
    - `rg '^\d\. \*\*' pac1-py/skills/compliance-check/SKILL.md`
      returns **exactly 5 hits** (steps 1, 2, 3, 4, 5 are all still
      present and contiguously numbered — the bullet insertions in
      step 3 must NOT have promoted any bullet to a new top-level
      step).
  - **D8 interference guard (pre-commit grep — guards against
    R3 bullet 4 over-firing on R1 anchor prose):**
    `rg -i 'closest match|approximately|nearest' pac1-py/skills/compliance-check/SKILL.md`
    returns **0 hits**. The R-DT20b business-context anchor must NOT
    use the exact-match anti-pattern phrasing that R3 bullet 4 will
    later trigger on.
  - **YAML front-matter / loader smoke check (Risk #8):**
    `python -c "import sys; sys.path.insert(0, 'pac1-py'); from skills import SkillLoader; from pathlib import Path; loader = SkillLoader(Path('pac1-py/skills')); doc = loader.load('compliance-check'); assert doc is not None"`
    succeeds with exit 0. (Substitute the live `SkillLoader` API if it
    differs — the goal is to verify the rewritten file still parses as
    a valid SkillDoc after the YAML front-matter at lines 1–4 is left
    untouched.)
  - **Pytest check:** `pytest pac1-py/tests/` passes fully (32/32
    expected). The test suite is unaffected by this edit because no
    test asserts on any narrative text inside `compliance-check/SKILL.md`.
  - **Pre-commit per-task batteries (R1.8 + R1.9 + R1.10 — MANDATORY
    iterative gate):** Run all three batteries against the
    locally-edited tree (do **not** commit yet). Record the outcome
    distribution of each. The gate passes if all three targets are met:
    - **t20 5-run battery (R1.8 — confirms R-DT20a fixes the AM-overlap
      trap):** Run task `t20` five consecutive times. Target: **≤ 1/10
      misfires** (drive the failure rate below the ~5% data-conditional
      trap rate). The Phase C baseline is the dedicated 5/5 battery in
      `phase-c-completion-report.md §"t20 — case study"` (no failures
      in the dedicated battery only because the trap data did not
      roll). If 5 runs are inconclusive, extend to 10.
    - **t37 5-run battery (R1.9 — confirms R-DT20b fixes the
      business-context trap):** Run task `t37` five consecutive times.
      Target: **≤ 1/5 misfires**. The baseline is the single observed
      t37 failure in the 2026-04-08 40/43 full benchmark run.
    - **t17 5-run regression battery (R1.10 — confirms R1 anchors do
      NOT re-introduce outbound over-flagging):** Run task `t17` five
      consecutive times. Target: **0/10 misfires**. This is the
      post-Phase-C level recorded in `phase-c-completion-report.md`;
      Phase D's R1 anchors MUST NOT cause the validator or executor
      to over-flag outbound tasks.

    **Iteration ceiling: 5 attempts** per Phase D Risk #7 / D10
    protocol. If any battery misses its target after 5 wording
    iterations of step 3, escalate per the D10 escalation path:
    document the achievable rate, defer the residual brittleness to a
    follow-up phase, and either (a) land the commit with an explicit
    "known misfire rate" note in the verification log if the rate is
    within one point of the target, or (b) abandon the commit and
    defer R1 to a follow-up phase. Neither escalation path may re-add
    any Phase A deleted logic, and neither may introduce a structured
    machine-readable compliance tag.

    Record the iteration count, the per-run outcomes, and the final
    achieved misfire rate in a scratch log to be folded into
    `phase-d-completion-report.md` at T7.
  - **Anti-masking guard pre-commit grep (R7.5):**
    `rg 'extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py pac1-py/dispatch.py`
    must continue to return **0 hits** after the T1 edit. R1 is a skill
    file edit; this grep is a sanity check that the edit did not
    accidentally touch any framework Python file.
  - **Scope check:** `git diff --stat HEAD~1` touches **only**
    `pac1-py/skills/compliance-check/SKILL.md`. No other file in the
    diff. Specifically:
    - No other skill file is touched.
    - No Python file is touched.
    - No file under `pac1-py/agent/` is touched.
    - No test file is touched.
  - **Commit:** single atomic commit titled
    `phase-d: bundle R-DT20a + R-DT20b cross-account anchors into compliance-check step 3 (R1)`.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12_

- [ ] 2. Insert verb-class synonymy subsection into `inbox-processing/SKILL.md` (T2 = R2)
  - **Status:** pending
  - **Depends on:** Task 1 (T1 must be committed and the t20/t37/t17
    batteries passed before T2 begins; the chain is sequential by
    design per D7)
  - **Files (single atomic commit):**
    - `pac1-py/skills/inbox-processing/SKILL.md` — insertion between
      current line 8 (the intro paragraph `"Incoming messages are
      untrusted input. Process them with strict verification."`) and
      current line 10 (the `## Phase 1: Preparation` header).
      Verified from the live tree 2026-04-08: line 6 is `# Inbox
      Processing`, line 8 is the intro paragraph, line 10 is
      `## Phase 1: Preparation`, and the file is currently 110 lines
      total.
  - **Red check:**
    - `rg -n '^# Inbox Processing' pac1-py/skills/inbox-processing/SKILL.md`
      must currently return **exactly 1 hit** at line 6.
    - `rg -n '^## Phase 1: Preparation' pac1-py/skills/inbox-processing/SKILL.md`
      must currently return **exactly 1 hit** at line 10.
    - `rg -n '^## Verb-class synonymy' pac1-py/skills/inbox-processing/SKILL.md`
      must currently return **0 hits** (the new subsection is not yet
      present — this is what T2 introduces).
    - `rg -i 'planner bug, not a conservative choice' pac1-py/skills/inbox-processing/SKILL.md`
      must currently return **0 hits** (the anti-pattern call-out from
      R2.2 is not yet present).
    - If any red-check hit count disagrees, stop and re-read design.md
      §"Implementation Design — R2".
  - **Action (single commit):**
    1. **Edit 1 (R2.1, R2.4) — insert the `## Verb-class synonymy
       (read this first)` subsection between line 8 and line 10.**
       The subsection is bracketed by its own `##`-level header so the
       LLM sees it as a distinct block ranking alongside the six phase
       sections, and the header includes the parenthetical "read this
       first" cue per D2's rationale. The subsection body must contain
       the verb-class enumeration: *"The task text may use any of
       these verbs to describe inbox work: **'process'**, **'handle'**,
       **'take care of'**, **'work through'**, **'review'**, **'deal
       with'**, **'go through'**, **'manage'**. All of these verbs
       invoke the full inbox-processing workflow defined in this skill —
       including Phase 5 (Act on allowed, fully verified messages) and
       any required outbox writes, reminder creation, or file
       deletions. Do NOT interpret 'review' as a read-only summarization
       task; if the inbox contains actionable messages that pass
       identity and compliance checks, execute the actions."* The
       eight verbs must each be bolded (per the D2 rationale: bolding
       gives the LLM lexical anchors for direct pattern-matching
       against the task text).
    2. **Edit 2 (R2.2) — append the anti-pattern call-out paragraph.**
       Immediately after Edit 1's verb enumeration paragraph, insert a
       second paragraph stating: *"A 'review and summarize' plan that
       omits the required writes is a **planner bug**, not a
       conservative choice — the 'Keep diffs focused and ID-stable'
       rule in root `AGENTS.md` is about not making unnecessary edits,
       NOT about skipping required actions."* The exact wording is in
       design.md §D2 "After state" — the implementation phase may
       refine prose but must preserve the "planner bug, not a
       conservative choice" anchor phrase verbatim because the R2
       grep battery checks for that exact phrase.
    3. **No other changes.** Phase 1 (lines 10–17 post-insertion-offset),
       Phase 1.5 (CONFLICT check), Phase 2 (read messages), Phase 3
       (verify each message), Phase 4 (compliance check), Phase 5 (act
       on allowed messages), Phase 6 (report), and the "Key rule"
       closing block at lines 106–110 are preserved byte-for-byte. The
       line numbers of all downstream phases shift by the insertion
       length (~12–15 lines), but no Python or test code references
       `inbox-processing/SKILL.md` by line number — the `SkillLoader`
       reads by YAML front-matter name, not by offset.
  - **Preserve (R2.5):**
    - `inbox-processing/SKILL.md` YAML front-matter (lines 1–4),
      `# Inbox Processing` header (line 6), intro paragraph (line 8),
      Phase 1 (load skills, channel config), Phase 1.5 (CONFLICT
      check), Phase 2 (read messages), Phase 3 (verify each message),
      Phase 4 (compliance check), Phase 5 (act on allowed messages),
      Phase 6 (report), and the "Key rule" closing block are
      byte-for-byte unchanged. R2 is **additive** at the top of the
      file, not a rewrite.
  - **Length invariant:** the rewritten file must be approximately
    122–125 lines (current 110 + ~12–15 insertion). Run `wc -l
    pac1-py/skills/inbox-processing/SKILL.md` and confirm the line
    count is in `[120, 130]`. A file outside this range likely
    indicates either an accidental deletion of existing content
    (below 120) or scope creep into a rewrite (above 130) — re-audit
    the diff against the preservation list above.
  - **Green check:**
    - `rg -n '^## Verb-class synonymy' pac1-py/skills/inbox-processing/SKILL.md`
      returns **exactly 1 hit** (the new subsection header).
    - `rg -i "'process'|'handle'|'take care of'|'work through'|'review'|'deal with'|'go through'|'manage'" pac1-py/skills/inbox-processing/SKILL.md`
      returns **≥ 8 matches** (R2.4 — at least eight verbs
      enumerated).
    - `rg -i 'planner bug, not a conservative choice' pac1-py/skills/inbox-processing/SKILL.md`
      returns **≥ 1 hit** (the anti-pattern call-out from R2.2).
    - `rg -n '^## Verb-class synonymy|^## Phase 1' pac1-py/skills/inbox-processing/SKILL.md`
      returns the Verb-class hit BEFORE the Phase 1 hit (R2.3 —
      placement before Phase 1).
    - `rg '^## Phase' pac1-py/skills/inbox-processing/SKILL.md`
      returns the same number of `## Phase` matches as the pre-T2
      state (Phase 1, 1.5, 2, 3, 4, 5, 6) — the existing phases are
      preserved.
  - **YAML front-matter / loader smoke check (Risk #8):**
    `python -c "import sys; sys.path.insert(0, 'pac1-py'); from skills import SkillLoader; from pathlib import Path; loader = SkillLoader(Path('pac1-py/skills')); doc = loader.load('inbox-processing'); assert doc is not None"`
    succeeds with exit 0.
  - **Pytest check:** `pytest pac1-py/tests/` passes fully (32/32
    expected).
  - **Pre-commit per-task battery (R2.6 — MANDATORY iterative gate):**
    Run the t24 5-run battery against the locally-edited tree (do
    **not** commit yet).
    - **t24 5-run battery (R2.6 — confirms verb-class synonymy fixes
      the planner verb-class gap):** Run task `t24` five consecutive
      times. Target: **≤ 1/5 misfires**. The R2 fix is targeted at
      the deterministic planner verb-class gap (the t24 failure mode
      is deterministic in the planner verb-class gap, not stochastic),
      so the target is to eliminate the failure mode entirely.

    **Iteration ceiling: 5 attempts.** If the battery misses its
    target after 5 wording iterations of the verb-class subsection,
    escalate per the D10 protocol (document the achievable rate, land
    or abandon, never re-add Phase A logic).

    Record the iteration count, the per-run outcomes, and the final
    achieved misfire rate in a scratch log to be folded into
    `phase-d-completion-report.md` at T7.
  - **Anti-masking guard pre-commit grep (R7.5):**
    `rg 'extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py pac1-py/dispatch.py`
    must continue to return **0 hits** after the T2 edit.
  - **Scope check:** `git diff --stat HEAD~1` touches **only**
    `pac1-py/skills/inbox-processing/SKILL.md`. No other file in the
    diff. No Python file, no test file, no other skill file.
  - **Commit:** single commit titled
    `phase-d: insert verb-class synonymy subsection into inbox-processing (R2)`.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

- [ ] 3. Insert empty-source-files + exact-match bullets into `build_validator_system` `<checks>` (T3 = R3)
  - **Status:** pending
  - **Depends on:** Task 2 (T2 must be committed and the t24 battery
    passed before T3 begins; T3's regression batteries on t17/t24/t37
    presuppose T1 and T2 have already landed)
  - **Files (single commit):**
    - `pac1-py/agent/prompts.py` — function `build_validator_system`,
      `<checks>` block at current lines 188–211. Verified from the
      live tree 2026-04-08: line 188 is `"<checks>\n"`, line 210 is
      `"3. If the proposed outcome is already non-OK, approve it.\n"`,
      and line 211 is `"</checks>\n\n"`. The function spans lines
      174–213.
  - **Red check:**
    - `rg -n '"<checks>' pac1-py/agent/prompts.py`
      must currently return **exactly 1 hit** at line 188.
    - `rg -n '3\. If the proposed outcome is already non-OK' pac1-py/agent/prompts.py`
      must currently return **exactly 1 hit** at line 210 (the bullet
      to be renumbered to 5).
    - `rg -i 'empty source-files check' pac1-py/agent/prompts.py`
      must currently return **0 hits** (the new bullet 3 is not yet
      present — this is what T3 introduces).
    - `rg -i 'exact-match semantics' pac1-py/agent/prompts.py`
      must currently return **0 hits** (the new bullet 4 is not yet
      present).
    - **D11 invariant pre-check:** `rg -n 'OUTCOME_CODES_DOC' pac1-py/agent/prompts.py`
      must currently return **exactly 2 hits** at lines 55 (definition)
      and 125 (interpolation). T3 must NOT touch either of these — T4
      handles the `OUTCOME_CODES_DOC` migration. If the line numbers
      have drifted, stop and re-read design.md §D11.
    - If any red-check hit count disagrees, stop and re-read design.md
      §"Implementation Design — R3".
  - **Action (single commit, single function):**
    1. **Edit 1 (R3.1) — insert new bullet 3 (empty-source-files
       check) between the current bullet 2's last sub-bullet ("Security
       flags…", line 208–209) and the current bullet 3 short-circuit
       (line 210).** The new bullet states: *"3. Empty source-files
       check: if the `<source-files>` injection contains zero entries
       AND the executor's proposed message claims specific file
       content, file existence, file dates, file counts, or any other
       file-metadata, escalate to `OUTCOME_NONE_CLARIFICATION`. An
       ungrounded answer cannot be approved regardless of how
       plausible it sounds — a file listing alone is not verification
       of file content."* The exact wording is in design.md §D3
       "After state" — the implementation phase may refine prose but
       must preserve the deterministic semantics: `<source-files>` =
       empty AND message claims file metadata → escalate. The
       precondition AND-clause is load-bearing (it scopes the trigger
       to "claims file metadata", protecting against the D8 Risk #2
       cross-account-STOP false positive).
    2. **Edit 2 (R3.2) — insert new bullet 4 (exact-match semantics)
       immediately after Edit 1's bullet 3.** The new bullet states:
       *"4. Exact-match semantics: if the task asks for something
       matching a precise criterion (exact date, exact count, exact
       identifier) and the executor's answer uses phrases like 'closest
       match', 'approximately', 'nearest', or otherwise admits
       divergence from the requested criterion, escalate to
       `OUTCOME_NONE_CLARIFICATION`. Do not approve best-effort
       approximations on exact-match tasks."* The trigger is on the
       *task type* (exact-match-required) AND the executor's *answer
       prose* (anti-pattern phrase like "closest match"). The trigger
       is narrow by design (D8 Risk #3 mitigation) — a grounded
       executor answer should never contain those phrases.
    3. **Edit 3 (D3 renumbering) — renumber the existing short-circuit
       bullet from 3 to 5.** The current line 210
       `"3. If the proposed outcome is already non-OK, approve it.\n"`
       becomes `"5. If the proposed outcome is already non-OK,
       approve it.\n"`. The check list stays numbered contiguously
       1 → 2 → 3 → 4 → 5. No other content change to this bullet.
    4. **Ordering invariant (D3 rationale):** The new bullets are
       inserted BETWEEN bullet 2's last sub-bullet and the renumbered
       bullet 5, NOT after the short-circuit. Putting the new bullets
       BEFORE the short-circuit ensures they run on every OK-proposed
       path, which is the load-bearing path for the t43 case study.
       Putting them AFTER the short-circuit would mean the validator
       never reads them on any task where the executor already
       reported a non-OK outcome — creating a hole on the t43-class
       failure mode (executor incorrectly reports OK on an ungrounded
       answer).
    5. **No other changes to `prompts.py`.** The `<role>` header
       (lines 176–177), the `<rules>` block (lines 178–187), bullet 1
       (lines 189–190), bullet 2 lead-in (lines 191–193), the
       email-match sub-clause (lines 194–195), the cross-account
       sub-clause (lines 196–207, including the Phase C inbound +
       outbound verb lists), the security-flags sub-bullet (lines
       208–209), and the final `"Use the validate_answer tool."`
       (line 212) are byte-for-byte unchanged. The function signature
       `build_validator_system() -> str` is unchanged. **D11
       invariant:** the `OUTCOME_CODES_DOC` constant at lines 55–64
       and the `OUTCOME_CODES_DOC` interpolation at line 125 are NOT
       touched by T3 — that is T4's job.
  - **Preserve (R3.4, R3.5):**
    - `<checks>` bullet 1 ("Does the message contain the actual answer
      (data, not just file references)?", lines 189–190) preserved
      verbatim.
    - `<checks>` bullet 2 ("INDEPENDENT VERIFICATION: …", lines
      191–209) preserved verbatim, INCLUDING:
      - The email-match sub-bullet (lines 194–195).
      - The cross-account sub-bullet with the Phase C R1 inbound verb
        list (`process`, `reply to`, `handle`, `respond to`, `verify`,
        `evaluate`) and outbound verb list (`email`, `send`, `remind`,
        `compose`, `notify`, `write to outbox/`, `create`) at lines
        196–207.
      - The security-flags sub-bullet (lines 208–209).
    - The Phase C cross-account verb-list classification (R3.5) is
      preserved byte-for-byte. R3 is orthogonal to Phase C R1 — R3
      adds two new bullets at the bullet-3/4 numbering level, while
      the Phase C verb-list lives as a sub-bullet under unchanged
      bullet 2. The two cleanups coexist because they operate on
      different structural levels of the check list.
  - **Green check:**
    - `rg -i 'empty source-files check' pac1-py/agent/prompts.py`
      returns **≥ 1 hit** (R3.1 — the new bullet 3).
    - `rg -i 'exact-match semantics' pac1-py/agent/prompts.py`
      returns **≥ 1 hit** (R3.2 — the new bullet 4).
    - `rg 'Does the message contain the actual answer' pac1-py/agent/prompts.py`
      returns **exactly 1 hit** (R3.4 — bullet 1 preserved).
    - `rg 'INDEPENDENT VERIFICATION' pac1-py/agent/prompts.py`
      returns **exactly 1 hit** (R3.4 — bullet 2 preserved).
    - `rg "'process', 'reply to', 'handle'" pac1-py/agent/prompts.py`
      returns **≥ 1 hit** (R3.5 — Phase C inbound verb list
      preserved at this point in the chain; the T5 conditional may
      extend it later).
    - `rg "'email', 'send', 'remind', 'compose', 'notify'" pac1-py/agent/prompts.py`
      returns **≥ 1 hit** (R3.5 — Phase C outbound verb list
      preserved).
    - `rg '5\. If the proposed outcome is already non-OK' pac1-py/agent/prompts.py`
      returns **exactly 1 hit** (the short-circuit was renumbered to 5).
    - `rg '3\. If the proposed outcome is already non-OK' pac1-py/agent/prompts.py`
      returns **0 hits** (the old bullet 3 number is gone).
  - **D11 invariant post-T3 grep check (Critical: protects against
    accidental T3 spillover into the OUTCOME_CODES_DOC region):**
    `rg -n 'OUTCOME_CODES_DOC' pac1-py/agent/prompts.py`
    returns **exactly 2 hits** at lines 55 and 125 (or
    insertion-shifted equivalents), unchanged from the pre-T3 state.
    If T3 accidentally touched the `OUTCOME_CODES_DOC` region, the
    diff for `prompts.py` will show a change outside the
    `build_validator_system` function and the Scope check will fail.
  - **Import / smoke check:**
    `python -c "import sys; sys.path.insert(0, 'pac1-py'); from agent.prompts import build_validator_system; s = build_validator_system(); assert 'Empty source-files check' in s; assert 'Exact-match semantics' in s; assert 'cross-account' in s.lower(); assert 'DECISION=' not in s; assert len(s) > 800"`
    succeeds with exit 0. The `len(s) > 800` lower bound confirms the
    function still produces a substantive prompt (not an empty
    placeholder); the absence of `DECISION=` confirms Phase C's R1
    cleanup is preserved.
  - **Pytest check:** `pytest pac1-py/tests/` passes fully (32/32
    expected). The validator-prompt edit is internal to the
    `build_validator_system` function body; no test asserts on the
    new bullet text.
  - **Pre-commit per-task battery — 4-battery regression matrix
    (R3.6 + R3.7 — MANDATORY iterative gate, EXPENSIVE):**

    **Wall-clock budget (per concern #3 / D10):** the T3 pre-commit
    gate is the most expensive per-task battery in Phase D. Each
    individual task run takes approximately 100 seconds (~4 minutes
    per 5-run battery). The 4-battery matrix takes approximately
    20 minutes per iteration. With the 5-iteration ceiling, the
    worst-case wall-clock time for the T3 pre-commit gate is
    **approximately 100 minutes (1.7 hours)** if every iteration
    needs the full 4-battery run; **typical: ~20 minutes** for
    iteration 1 if the wording is correct on the first attempt. The
    worst-case Phase A/C-style "5 iterations × 4 batteries × ~7
    minutes per battery (including setup)" upper bound is
    **approximately 2.5–2.7 hours**. Task authors must NOT discover
    the cost mid-implementation — budget the wall-clock time
    explicitly before starting the gate.

    Run all four batteries against the locally-edited tree (do **not**
    commit yet). Record the outcome distribution of each. The gate
    passes only if ALL FOUR targets are met:

    - **t43 5-run battery (R3.6 — primary target, deterministic
      rule):** Run task `t43` five consecutive times. Target:
      **0/5 misfires**. The empty-source-files and exact-match rules
      are deterministic, not stochastic, so the target is full
      elimination of the failure mode (not just "below the noise
      floor").
    - **t17 5-run regression battery (R3.7 — confirms R3 bullets do
      NOT over-fire on outbound tasks):** Run task `t17` five
      consecutive times. Target: **0/10 misfires** preserved (the
      post-Phase-C and post-T1 level).
    - **t24 5-run regression battery (R3.7 — confirms R3 bullets do
      NOT regress R2's verb-class fix):** Run task `t24` five
      consecutive times. Target: **post-T2 pass rate preserved**
      (0/5 misfires expected).
    - **t37 5-run regression battery (R3.7 — confirms R3 bullets do
      NOT regress R1's business-context fix):** Run task `t37` five
      consecutive times. Target: **post-T1 pass rate preserved**
      (0/5 misfires expected).

    **Iteration ceiling: 5 attempts.** If any battery misses its
    target after 5 wording iterations of bullets 3 and 4, escalate
    per D10. Specifically:
    - If t43 misses (under-fire on the deterministic rule): refine
      the empty-source-files or exact-match precondition wording to
      be more explicit; consider adding a concrete example phrase to
      either bullet.
    - If t17/t24/t37 regresses (over-fire): tighten the precondition
      AND-clause on the relevant bullet; verify the trigger is
      narrow enough to skip grounded answers.
    - If both happen simultaneously, the bullet wording is in a
      double-bind and the requirement should be deferred — document
      the achievable rate and either land with a "known misfire
      rate" note or abandon T3 to a follow-up phase.

    Neither escalation path may re-add Phase A deleted logic.

    Record the iteration count, the per-battery per-run outcomes,
    and the final achieved misfire rates in a scratch log to be
    folded into `phase-d-completion-report.md` at T7.
  - **Anti-masking guard pre-commit grep (R7.5):**
    `rg 'extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py pac1-py/dispatch.py`
    must continue to return **0 hits** after the T3 edit. R3 is a
    prompt-text edit inside `prompts.py`; this grep is a sanity check
    that the edit did not accidentally re-introduce any forbidden
    Phase A name.
  - **Scope check:** `git diff --stat HEAD~1` touches **only**
    `pac1-py/agent/prompts.py`. No other file in the diff.
    Additionally, `git diff HEAD~1 -- pac1-py/agent/prompts.py` must
    show changes ONLY inside the `build_validator_system` function
    region (current lines 174–213). If the diff shows any change to
    `OUTCOME_CODES_DOC` (lines 55–64), the CLI color constants (lines
    5–12), `AGENT_CAN`/`AGENT_CANNOT` (lines 18–31), the rule
    constants (lines 37–49), `build_executor_system` (lines 71–126),
    or `build_planner_system` (lines 129–171), the D11 disjoint-region
    invariant has been violated and the commit must be amended.
  - **Commit:** single commit titled
    `phase-d: add empty-source-files + exact-match bullets to validator <checks> (R3)`.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

- [ ] 4. Extract outcome-protocol into `pac1-py/agent/outcomes.py` (T4 = R4 = R-DOI, ATOMIC across 4 files)
  - **Status:** pending
  - **Depends on:** Task 3 (T3 must be committed and the 4-battery
    regression matrix passed before T4 begins; T4's `prompts.py` edit
    operates on the post-T3 state and must not perturb T3's work)
  - **Files (single atomic commit):**
    - `pac1-py/agent/outcomes.py` — **NEW FILE**, ~65 lines, R-DOI
      target module with the exact content shape specified in
      design.md §D4.
    - `pac1-py/agent/dispatch.py` — `OUTCOME_BY_NAME` definition at
      current lines 32–38 removed; new `from agent.outcomes import
      OUTCOME_BY_NAME` import added near the top of the file. Verified
      from the live tree 2026-04-08: lines 32–38 contain exactly the
      5-key dict mapping each `OUTCOME_*` string to its
      `Outcome.OUTCOME_*` protobuf enum value, and line 14 is the
      `from bitgn.vm.pcm_pb2 import (... Outcome ...)` import.
    - `pac1-py/agent/executor.py` — import at current line 15
      (`from agent.dispatch import OUTCOME_BY_NAME, dispatch`) split
      into two import lines; bare string literals at current lines
      208 (`"OUTCOME_OK"`), 232 (`"OUTCOME_ERR_INTERNAL"`), 237
      (`"OUTCOME_OK"`), 261 (`"OUTCOME_DENIED_SECURITY"`), 366
      (`"OUTCOME_OK"`), 379 (`"OUTCOME_OK"`), 385 (`"OUTCOME_OK"`)
      migrated to named constants. Verified from the live tree
      2026-04-08: all 7 line numbers match the design's enumeration.
    - `pac1-py/agent/prompts.py` — `OUTCOME_CODES_DOC` definition at
      current lines 55–64 removed; new `from agent.outcomes import
      OUTCOME_CODES_DOC` import added at the top of the file. The
      f-string interpolation at line 125
      (`f"<outcome-codes>\n{OUTCOME_CODES_DOC}\n</outcome-codes>"`)
      is preserved unchanged.
    - **Conditional:** `pac1-py/tests/test_dispatch.py` — only edited
      if the pre-commit grep at the head of the Action section returns
      at least one hit.
  - **Atomic-commit invariant:** All four files (plus the conditional
    fifth) MUST land in the same git commit. See "T4 atomic-commit
    invariant" section above for the rationale. Splitting this across
    phased commits leaves intermediate states with two sources of
    truth, which is exactly the failure mode R4.1 ("single source of
    truth") exists to prevent.
  - **Red check:**
    - `ls pac1-py/agent/outcomes.py` must currently return **exit 1**
      (the file does not yet exist — this is what T4 creates).
    - `rg -n 'OUTCOME_BY_NAME\s*=' pac1-py/agent/`
      must currently return **exactly 1 hit**, in `dispatch.py` at
      lines 32 (the dict assignment line).
    - `rg -n 'OUTCOME_CODES_DOC\s*=' pac1-py/agent/`
      must currently return **exactly 1 hit**, in `prompts.py` at
      line 55 (the constant assignment line).
    - `rg -c '"OUTCOME_' pac1-py/agent/executor.py`
      must currently return **at least 7** (the 7 bare string
      literals at lines 208, 232, 237, 261, 366, 379, 385). Use
      `rg -n '"OUTCOME_' pac1-py/agent/executor.py` to verify the
      exact line numbers match the design's enumeration.
    - `rg -n 'from agent\.dispatch import OUTCOME_BY_NAME' pac1-py/agent/executor.py`
      must currently return **exactly 1 hit** at line 15.
    - **Conditional pre-commit grep (per D4 conditional test-file
      edit + concern #2):**
      `rg 'from agent\.dispatch import.*OUTCOME_' pac1-py/tests/test_dispatch.py`
      must be run BEFORE making any T4 edit. Record the result. If
      the grep returns **at least 1 hit**, `test_dispatch.py` is
      added to the T4 file list and its import line is updated in
      the same atomic commit. If the grep returns **0 hits**,
      `test_dispatch.py` is NOT edited and stays in the forbidden
      list. **Pre-verified at design time (2026-04-08): the grep
      returns ZERO hits — `test_dispatch.py` only imports `dispatch`
      and `truncate_output` from `agent.dispatch`, not any
      `OUTCOME_*` symbol. The conditional edit will most likely not
      fire.** The Phase D verification log must record the live
      grep result regardless.
    - If any red-check hit count disagrees with the expected pre-edit
      state, stop and re-read design.md §"Implementation Design — R4"
      and §D4 before proceeding — the file may have drifted from the
      design's verified baseline.
  - **Action (single atomic commit covering all four files):**
    1. **Edit 1 (R4.1) — create `pac1-py/agent/outcomes.py` from
       scratch.** New file with the exact content shape specified in
       design.md §D4 "Target module — `pac1-py/agent/outcomes.py` API
       shape". The file contains:
       - Module docstring (~12 lines) carrying the **load-bearing
         anti-masking invariant text from D4 verbatim**, including
         the explicit "MUST NOT contain" name list:
         `compliance_tag`, `set_cross_account`,
         `record_compliance_decision`, `OutcomeTag`, `OutcomeMetadata`,
         and `classify_cross_account`. **Per concern #1, the docstring
         must literally name these forbidden symbols in the "MUST NOT
         contain" enumeration so that the docstring itself is the
         in-module anti-scope-creep guard.** Use the design's docstring
         text (D4 lines starting with `"""Single source of truth for
         the pac1-py outcome-code protocol.`) verbatim or with only
         minor prose refinements that preserve every forbidden-name
         mention.
       - `from bitgn.vm.pcm_pb2 import Outcome` import at the top.
       - Five module-level string constants with explicit `: str`
         type annotations: `OUTCOME_OK`, `OUTCOME_DENIED_SECURITY`,
         `OUTCOME_NONE_CLARIFICATION`, `OUTCOME_NONE_UNSUPPORTED`,
         `OUTCOME_ERR_INTERNAL`. Each constant's value is the
         identical string (`"OUTCOME_OK"`, etc.).
       - `OUTCOME_BY_NAME: dict[str, "Outcome"] = {...}` mapping each
         of the five string constants to its `Outcome.OUTCOME_*`
         protobuf counterpart. The five keys, five values, and 1:1
         mapping are byte-for-byte identical to the current
         `dispatch.py:32-38` dict.
       - `OUTCOME_CODES_DOC: str = (...)` constant carrying the
         current `prompts.py:55-64` text byte-for-byte. Do NOT modify
         the prose inside the constant; the text content is preserved
         for `build_executor_system`'s interpolation.
       - **CRITICAL: the module body must contain ONLY the seven
         names listed above** (5 string constants + 1 dict + 1 doc
         string constant). No helper functions, no factory functions,
         no parser, no class definitions, no imports beyond the
         protobuf `Outcome` enum. The "Explicit boundary vs Phase A's
         deleted compliance-tag surface" enumeration in design.md §D4
         is the binding contract for this module's surface.
       - **Per concern #1, after writing `outcomes.py`, run an
         immediate inline grep verification:**
         `rg -i 'compliance_tag|set_cross_account|record_compliance_decision|OutcomeTag|OutcomeMetadata|classify_cross_account' pac1-py/agent/outcomes.py`
         and confirm the only matches are inside the docstring (the
         "MUST NOT contain" enumeration). The matches must be inside
         a docstring context, never inside an actual function or
         class definition. If any match falls outside the docstring,
         the module body has scope creep and must be rejected before
         the commit.
    2. **Edit 2 (R4.2 dispatch.py) — update `pac1-py/agent/dispatch.py`.**
       - Remove the `OUTCOME_BY_NAME = {...}` dict definition at
         lines 32–38 (7 lines including the closing `}`).
       - Add a new import line `from agent.outcomes import
         OUTCOME_BY_NAME` near the top of the file, placed
         alphabetically among the existing
         `from agent.config import AgentConfig` /
         `from skills import SkillLoader` /
         `from tasks import TaskManager` imports.
       - Preserve the `from bitgn.vm.pcm_pb2 import (... Outcome ...)`
         import at line 14 unchanged. The
         `Outcome.OUTCOME_DENIED_SECURITY` literal usage at line 183
         (inside `report_threat`) still references the protobuf enum
         directly and continues to work.
       - Preserve the `OUTCOME_BY_NAME[args["outcome"]]` usage at
         line 176 (inside `report_completion`) unchanged — the
         dict's behavior is identical because it is the same
         byte-for-byte dict, just imported from a new location.
    3. **Edit 3 (R4.2 executor.py) — update `pac1-py/agent/executor.py`.**
       - **Edit 3a — split the import at line 15.** Replace
         `from agent.dispatch import OUTCOME_BY_NAME, dispatch`
         with two import lines:
         ```
         from agent.dispatch import dispatch
         from agent.outcomes import (
             OUTCOME_BY_NAME,
             OUTCOME_DENIED_SECURITY,
             OUTCOME_ERR_INTERNAL,
             OUTCOME_OK,
         )
         ```
       - **Edit 3b — migrate the 7 bare string literals to named
         constants. Per concern #6, this is an explicit per-line
         action list:**
         - **Line 208:** `"outcome": "OUTCOME_OK"` →
           `"outcome": OUTCOME_OK` (inside the text-rescue-as-
           report_completion return dict).
         - **Line 232:** `args.get("outcome", "OUTCOME_ERR_INTERNAL")` →
           `args.get("outcome", OUTCOME_ERR_INTERNAL)` (inside the
           `report_completion` handler default).
         - **Line 237:** `if outcome == "OUTCOME_OK" and not message.strip():` →
           `if outcome == OUTCOME_OK and not message.strip():`
           (inside the empty-message guard).
         - **Line 261:** `"outcome": "OUTCOME_DENIED_SECURITY"` →
           `"outcome": OUTCOME_DENIED_SECURITY` (inside the
           `report_threat` handler return dict).
         - **Line 366:** `if outcome == "OUTCOME_OK" and pending:` →
           `if outcome == OUTCOME_OK and pending:` (deferred-writes
           gate).
         - **Line 379:** `if outcome == "OUTCOME_OK" and stem_index:` →
           `if outcome == OUTCOME_OK and stem_index:` (cross-reference-
           follow gate).
         - **Line 385:** `outcome_style = CLI_GREEN if outcome == "OUTCOME_OK" else CLI_YELLOW` →
           `outcome_style = CLI_GREEN if outcome == OUTCOME_OK else CLI_YELLOW`
           (outcome-styling for the final-answer print).
       - **Edit 3c — preserve the protobuf-enum usages at lines 342
         and 391.** These lines use `Outcome.OUTCOME_ERR_INTERNAL`
         (the protobuf enum value), which is semantically different
         from the Python-side string constant. They are passed as
         the `outcome` field of `AnswerRequest` (which expects a
         protobuf enum value, not a string). Migrating these to the
         string constant would BREAK the code. They are NOT migrated.
       - **Edit 3d — preserve the `OUTCOME_BY_NAME[plan["rejection"]["outcome"]]`
         usage at line 310** (inside `run_agent`'s planner-rejection
         path) unchanged. The dict key lookup works identically
         because it is the same dict, imported from a new location.
       - **Edit 3e — preserve the `OUTCOME_BY_NAME.get(outcome, Outcome.OUTCOME_ERR_INTERNAL)`
         usage at line 391** (the final `vm.answer` site) unchanged.
       - Preserve the `from bitgn.vm.pcm_pb2 import AnswerRequest, Outcome, ReadRequest`
         import at line 9 unchanged.
       - **Per Risk #4, after the migration, run the post-migration
         grep check:** `rg '"OUTCOME_' pac1-py/agent/executor.py`
         must return **0 hits**. Any remaining bare `"OUTCOME_*"`
         literal indicates a missed migration line and must be
         fixed before the commit.
    4. **Edit 4 (R4.2 prompts.py) — update `pac1-py/agent/prompts.py`.**
       - Remove the `OUTCOME_CODES_DOC = (...)` constant at lines
         55–64 (10 lines), including the section header comment at
         lines 51–53 (`"# ----...\n# Outcome code documentation
         (shared by dispatch and validation)\n# ----..."`). The
         section header is removed because the constant it labels
         is moving out of the file.
       - Add a new import line `from agent.outcomes import
         OUTCOME_CODES_DOC` at the top of the file, placed BEFORE the
         CLI color constants at line 5. Per Python convention,
         imports precede module-level code. Note: `prompts.py`
         currently has zero imports — the file starts with the
         `# CLI color constants` comment block at line 1. The new
         import is the first import in the file.
       - Preserve the f-string interpolation at line 125
         `f"<outcome-codes>\n{OUTCOME_CODES_DOC}\n</outcome-codes>"`
         unchanged. The `OUTCOME_CODES_DOC` name resolves to the
         imported constant after the migration; Python's name
         resolution makes the re-import transparent.
       - **D11 invariant — do NOT touch `build_validator_system`
         (lines 174–213).** T4's edit to `prompts.py` is structurally
         disjoint from T3's edit. The `<checks>` bullets 3 and 4
         added by T3 must remain unchanged. Verified post-T4 by:
         `rg -i 'empty source-files check|exact-match semantics' pac1-py/agent/prompts.py`
         → still returns ≥ 2 hits.
       - Preserve every inline outcome-string mention inside
         `build_executor_system` (lines 89, 91, 97),
         `build_planner_system` (lines 138, 140, 143, 146), and
         `build_validator_system` (lines 179, 180) unchanged. Per
         D4, these inline prose mentions are NOT migrated to named
         constants — they are individual prose sentences embedded
         inside prompt bodies, and migrating them would obscure the
         prose flow without meaningfully reducing the "single source
         of truth" surface.
    5. **Edit 5 (conditional, R4.6) — update `pac1-py/tests/test_dispatch.py`
       import IF the pre-commit grep returned at least one hit.**
       If the grep `rg 'from agent\.dispatch import.*OUTCOME_' pac1-py/tests/test_dispatch.py`
       returned ≥ 1 hit at the start of the Action section, update
       the hit line to `from agent.outcomes import OUTCOME_BY_NAME`
       (or whichever specific outcome name is imported). The update
       happens in the same atomic commit. **Pre-verified at design
       time: the grep returns 0 hits, so this edit will most likely
       not fire. The pre-commit grep MUST be re-run live as part of
       the T4 action sequence regardless — do NOT skip the grep
       based on the design-time pre-verification.**
  - **Preserve (R4.3, R4.4, R4.5):**
    - **Pipeline shape:** Bootstrap → Planner → Executor → Validator
      → Apply → CrossRef → Submit is preserved across the R4
      refactor. R4 is internal: it does not change pipeline shape,
      module boundaries beyond the one new `outcomes.py` file, or
      tool composition.
    - **Validator return contract (R4.4):** `validate_completion`
      returns `None` to mean "approved" and a dict
      `{"outcome": str, "message": str}` to mean "corrected".
      `validator.py` is NOT touched in T4 — per the D4 discovery
      scan, `validator.py` has zero hardcoded outcome-string
      constants. The validator's return contract is therefore
      vacuously preserved.
    - **Scoring contract (R4.5):** Outcome strings round-trip
      through `OUTCOME_BY_NAME` to the `Outcome.OUTCOME_*` protobuf
      enum at the two `vm.answer(AnswerRequest(...))` sites in
      `dispatch.py` (`report_completion` at line 176 and
      `report_threat` at line 183) and at the final-answer
      submission in `executor.py` (line 391). The dict is moved
      byte-for-byte, same 5 keys, same 5 values, same 1:1 mapping.
      No outcome code is added, renamed, or removed.
    - **Deferred-writes gate** at `executor.py:366`
      (`if outcome == OUTCOME_OK and pending:` post-migration)
      preserved as a string-equality comparison. `OUTCOME_OK` is a
      module-level string constant with value `"OUTCOME_OK"`, so
      the equality semantics are unchanged.
    - **`OUTCOME_CODES_DOC` text content** preserved byte-for-byte.
      Only the file location changes (from `prompts.py:55-64` to
      `outcomes.py`).
    - **`pac1-py/agent/validator.py`** untouched.
    - **`pac1-py/tools.py`** untouched (D5 Non-Goal: JSON-schema
      enum entries at lines 281–285, 511–515, 559–561 remain as
      literal strings).
    - **The Phase C narrative-reasoning pattern** in
      `compliance-check/SKILL.md` step 4 is preserved (T4 does not
      touch any skill file).
    - **The R3 bullets 3 and 4** added in T3 to
      `build_validator_system` are preserved (T4 does not touch
      `build_validator_system`).
  - **Green check:**
    - `ls pac1-py/agent/outcomes.py` returns **exit 0** (the file
      now exists).
    - `rg 'OUTCOME_BY_NAME\s*=' pac1-py/agent/` returns **exactly 1
      hit**, in `outcomes.py` (D11 single-source-of-truth invariant).
    - `rg 'OUTCOME_CODES_DOC\s*=' pac1-py/agent/` returns **exactly
      1 hit**, in `outcomes.py` (D11 single-source-of-truth
      invariant).
    - `rg 'from agent\.outcomes import.*OUTCOME_BY_NAME' pac1-py/agent/dispatch.py`
      returns **≥ 1 hit** (the new import in `dispatch.py`).
    - `rg 'OUTCOME_BY_NAME\s*=\s*\{' pac1-py/agent/dispatch.py`
      returns **0 hits** (the dict is no longer defined in
      `dispatch.py`).
    - `rg 'from agent\.outcomes import' pac1-py/agent/executor.py`
      returns **≥ 1 hit** (the new import block in `executor.py`).
    - `rg '"OUTCOME_' pac1-py/agent/executor.py` returns **0 hits**
      (R4 + Risk #4 mitigation: all 7 bare string literals migrated
      to named constants).
    - `rg 'from agent\.outcomes import.*OUTCOME_CODES_DOC' pac1-py/agent/prompts.py`
      returns **≥ 1 hit** (the new import in `prompts.py`).
    - `rg 'OUTCOME_CODES_DOC\s*=\s*\(' pac1-py/agent/prompts.py`
      returns **0 hits** (the constant is no longer defined in
      `prompts.py`).
    - `rg 'from bitgn\.vm\.pcm_pb2 import.*Outcome' pac1-py/agent/dispatch.py`
      returns **≥ 1 hit** (the protobuf `Outcome` import is still
      present at line 14, used by the `Outcome.OUTCOME_DENIED_SECURITY`
      reference at line 183).
    - `rg 'from bitgn\.vm\.pcm_pb2 import.*Outcome' pac1-py/agent/executor.py`
      returns **≥ 1 hit** (the protobuf `Outcome` import is still
      present at line 9, used by `Outcome.OUTCOME_ERR_INTERNAL` at
      lines 342 and 391).
    - `git diff --name-only HEAD~1 HEAD -- pac1-py/agent/validator.py`
      returns **0 lines** (validator.py is NOT touched, per D4 and
      R4.4 — the validator return contract is vacuously preserved).
  - **R-DOI anti-scope-creep grep battery (Risk #5 — CRITICAL,
    addresses concern #1):**
    Run after the T4 edits are made and before the commit:
    - `rg -i 'compliance_tag' pac1-py/agent/outcomes.py` outside
      docstring context → **0 hits** in the module body.
    - `rg -i 'set_cross_account|cross_account_flag' pac1-py/agent/outcomes.py`
      outside docstring context → **0 hits** in the module body.
    - `rg -i 'record_compliance_decision|compliance_decision' pac1-py/agent/outcomes.py`
      outside docstring context → **0 hits** in the module body.
    - `rg 'class OutcomeTag|class OutcomeMetadata|class OutcomeContext' pac1-py/agent/outcomes.py`
      → **0 matches** (no class definitions of any forbidden type).
    - `rg -i 'classify_cross_account|classify_compliance' pac1-py/agent/outcomes.py`
      outside docstring context → **0 hits** in the module body.
    - `rg 'compliance_state' pac1-py/` → **0 matches** repository-
      wide.
    - `python -c "import sys; sys.path.insert(0, 'pac1-py'); import agent.outcomes as o; names = [n for n in dir(o) if not n.startswith('_') and n != 'Outcome']; assert set(names) == {'OUTCOME_OK', 'OUTCOME_DENIED_SECURITY', 'OUTCOME_NONE_CLARIFICATION', 'OUTCOME_NONE_UNSUPPORTED', 'OUTCOME_ERR_INTERNAL', 'OUTCOME_BY_NAME', 'OUTCOME_CODES_DOC'}, f'Unexpected symbols in outcomes: {names}'"`
      → **exit 0**. The module's exported surface is exactly the 7
      names plus the re-exported `Outcome` (which is allowed because
      it is imported from `bitgn.vm.pcm_pb2`, not defined locally).

    **Per concern #1, the inline docstring grep:**
    `rg -A 20 '^\"\"\"' pac1-py/agent/outcomes.py | rg -i 'compliance_tag|set_cross_account|record_compliance_decision|OutcomeTag|OutcomeMetadata|classify_cross_account'`
    SHOULD return **≥ 6 matches** (one per forbidden name in the
    docstring's "MUST NOT contain" enumeration). This is the
    positive-presence verification that the load-bearing
    anti-masking text is in the docstring. If any forbidden name is
    missing from the docstring, the docstring is incomplete and must
    be amended before commit.
  - **Import / smoke check:**
    - `python -c "import sys; sys.path.insert(0, 'pac1-py'); import agent.outcomes; import agent.dispatch; import agent.executor; import agent.prompts; import agent.validator"`
      succeeds with exit 0 (all five modules import cleanly after
      the refactor).
    - `python -c "import sys; sys.path.insert(0, 'pac1-py'); from agent.outcomes import OUTCOME_OK, OUTCOME_DENIED_SECURITY, OUTCOME_NONE_CLARIFICATION, OUTCOME_NONE_UNSUPPORTED, OUTCOME_ERR_INTERNAL, OUTCOME_BY_NAME, OUTCOME_CODES_DOC; assert OUTCOME_OK == 'OUTCOME_OK'; assert OUTCOME_DENIED_SECURITY == 'OUTCOME_DENIED_SECURITY'; assert len(OUTCOME_BY_NAME) == 5; assert 'OUTCOME_OK' in OUTCOME_BY_NAME; assert 'OUTCOME_OK:' in OUTCOME_CODES_DOC"`
      succeeds with exit 0 (all 7 names import correctly, the dict
      has exactly 5 keys, and the doc text is intact).
    - `python -c "import sys; sys.path.insert(0, 'pac1-py'); from agent.prompts import build_executor_system, build_validator_system; s1 = build_executor_system(); s2 = build_validator_system(); assert 'OUTCOME_OK' in s1; assert 'OUTCOME_DENIED_SECURITY' in s1; assert 'OUTCOME_NONE_CLARIFICATION' in s2; assert 'Empty source-files check' in s2; assert 'Exact-match semantics' in s2"`
      succeeds with exit 0 (the prompt builders still produce
      complete prompts after the `OUTCOME_CODES_DOC` migration; the
      T3 bullets 3 and 4 are preserved).
  - **Pytest check (R4.6 — MANDATORY):** `pytest pac1-py/tests/`
    passes fully at **32/32 green**. This is the most likely failure
    mode for T4: an import-path error in the R-DOI refactor would
    surface as a test-collection failure or a runtime ImportError
    on `test_dispatch.py` or `test_compact_tree.py`. If the test
    suite is red after the T4 edits, debug the import resolution
    before committing. **Iteration ceiling for the test-suite gate:
    5 attempts.** If 5 attempts cannot achieve 32/32 green, escalate
    per Phase C Risk #2 — defer the R-DOI refactor to a follow-up
    phase, do NOT commit a red test suite.
  - **PAC1 benchmark smoke run (R4.7):** Run **one** full 43-task
    PAC1 benchmark via `python pac1-py/main.py` against the
    locally-edited tree. Capture the score as `passed/43`. Target:
    **≥ 40/43** on this single smoke run. This is NOT the multi-run
    benchmark for R6 — that is T6's job. T4's smoke run is a
    pre-commit gate that confirms the R-DOI refactor does not break
    the full pipeline at the integration level. If the smoke run
    scores below 40/43, debug the regression before committing.
    **Iteration ceiling: 5 attempts.**
  - **Anti-masking guard pre-commit grep (R7.5):**
    `rg 'extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py pac1-py/dispatch.py`
    must continue to return **0 hits** after the T4 edits. R-DOI
    centralizes outcome-string handling but MUST NOT introduce any
    Phase A deleted name under any guise.
  - **Scope check:** `git diff --name-only HEAD~1 HEAD` returns
    **exactly the expected file list**:
    - `pac1-py/agent/outcomes.py`
    - `pac1-py/agent/dispatch.py`
    - `pac1-py/agent/executor.py`
    - `pac1-py/agent/prompts.py`
    - **Optionally** `pac1-py/tests/test_dispatch.py` IF and only IF
      the pre-commit grep at the head of the Action section returned
      ≥ 1 hit. Per the design-time pre-verification (the grep
      returns 0 hits), the expected diff list is **exactly 4 files**,
      not 5.

    Any other file in the diff is a scope violation and must be
    reverted before the commit can land. Specifically:
    - `pac1-py/agent/validator.py` must NOT be in the diff.
    - `pac1-py/agent/planner.py` must NOT be in the diff.
    - `pac1-py/tools.py` must NOT be in the diff (D5 Non-Goal).
    - `pac1-py/main.py` must NOT be in the diff.
    - No skill file must be in the diff.
    - No test file other than the conditional `test_dispatch.py`
      must be in the diff.

    Additionally, `git diff HEAD~1 -- pac1-py/agent/prompts.py` must
    show changes ONLY in the top-of-file region (new import) and
    the `OUTCOME_CODES_DOC` region (lines 55–64 deletion). The diff
    must NOT touch `build_validator_system` (lines 174–213) — that
    is T3's region per D11. Verified by:
    `rg -i 'empty source-files check|exact-match semantics' pac1-py/agent/prompts.py`
    still returns ≥ 2 hits post-T4 (T3's bullets are preserved).
  - **Commit:** single atomic commit titled
    `phase-d: extract outcome-protocol into agent/outcomes.py (R4 = R-DOI)`.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10_

- [ ] 5. R-DT17R validator verb-list audit and conditional gap-extension (T5 = R5, CONDITIONAL)
  - **Status:** pending (conditional — depends on live re-audit
    result; design-time audit found gaps on `review` and `take care
    of`, but the implementation phase MUST re-verify against the
    live 43-task corpus before committing any code change)
  - **Depends on:** Task 4 (T4 must be committed and the R-DOI
    refactor verified before T5 begins; T5 edits `prompts.py` at the
    same function `build_validator_system` that T3 modified, so T5
    operates on a post-T3-and-post-T4 baseline)
  - **Files (conditional, single commit IF the gap-extension exit
    fires):**
    - `pac1-py/agent/prompts.py` — function `build_validator_system`,
      inbound verb list at current lines 196–207 (the cross-account
      sub-clause inside `<checks>` bullet 2). The exact line numbers
      are post-T3 + post-T4 — the T3 insertion of bullets 3 and 4
      and the T4 import addition will have shifted the
      `build_validator_system` function position, but the cross-
      account sub-clause within bullet 2 remains structurally at the
      same place.
  - **Pre-T5 live re-audit (MANDATORY, addresses concern #4):**

    Before any T5 edit is made, the implementation phase MUST
    re-run the D9 audit against the **live 43-task PAC1 corpus**
    (not the case-study corpus the design phase used). The design
    audit was tentatively gap-extension because the case-study
    narratives in `phase-c-completion-report.md` and
    `phase-d-prerequisites.md` were the only task-text source
    available at design time. The implementation phase has access
    to the live corpus via `bitgn/pac1-dev` and MUST re-verify.

    **Re-audit protocol:**
    1. Extract the current Phase C verb lists from
       `build_validator_system` at the post-T3 + post-T4
       `prompts.py` (lines ~196–207 region):
       - Inbound verbs: `process`, `reply to`, `handle`,
         `respond to`, `verify`, `evaluate`
       - Outbound verbs: `email`, `send`, `remind`, `compose`,
         `notify`, `write to outbox/`, `create`
    2. Iterate over all 43 task texts in the live PAC1 corpus
       (use whatever access pattern the `bitgn/pac1-dev` harness
       exposes — e.g. dump the task text for each `tXX` and grep
       it for verbs).
    3. For each task whose verb is NOT in either the inbound or
       outbound list, record the verb, the task ID, and a one-line
       classification (inbound / outbound / lookup / other).
    4. Compare the gap list against the design-time audit findings
       in design.md §D9. The design-time finding was gaps on
       `review` (t24) and `take care of` (t37).
    5. **Decide the exit path:**
       - If the live re-audit confirms the design-time finding
         (verbs `review` and/or `take care of` are in the live
         corpus and not in the validator's inbound list), proceed
         to the **gap-extension exit (R5.3)** — execute the Action
         section below.
       - If the live re-audit finds **additional** gaps beyond the
         design-time finding, extend the inbound or outbound list
         as needed and update the Phase D verification log to
         record the additional gap(s) and the line of
         `build_validator_system` that was edited. T5's scope is
         bounded at "verb-list extension only" — T5 does NOT
         introduce new check logic, new bullets, or new XML tags.
       - If the live re-audit finds **NO gaps** (no live task uses
         a verb outside the existing lists), proceed to the
         **vacuous-satisfaction exit (R5.2)** — record the audit
         result in the Phase D verification log without any code
         change. T5 closes vacuously.

    Record the full re-audit result (per-task verb classification,
    gap list, exit-path decision, justification) in a scratch log
    to be folded into `phase-d-completion-report.md` at T7.
  - **Red check (only if gap-extension exit fires):**
    - `rg "'process', 'reply to', 'handle', 'respond to', 'verify', 'evaluate'|'process', 'reply to', 'handle', 'respond to', 'verify', or 'evaluate'" pac1-py/agent/prompts.py`
      must currently return **≥ 1 hit** (the current Phase C
      inbound verb list).
    - `rg "'review'.*'take care of'" pac1-py/agent/prompts.py`
      must currently return **0 hits** (the verb-list extension is
      not yet present — this is what T5 introduces if it fires).
  - **Action (single commit, only if gap-extension exit fires):**
    1. **Edit 1 (R5.3) — extend the inbound verb list at
       `prompts.py` lines 196–207** (post-T3 + post-T4 line
       numbers). The current sub-clause inside `<checks>` bullet 2
       reads (with line numbers from the pre-T3 baseline; expect
       small shifts post-T3/T4):
       ```
       "- Cross-account check (applies ONLY to inbound-message tasks): an "
       "inbound-message task is one whose instruction uses verbs like "
       "'process', 'reply to', 'handle', 'respond to', 'verify', or "
       "'evaluate' on an already-received message from inbox/ or a channel. "
       ```
       Extend the inbound verb enumeration to include the six new
       verbs from D9 (matching R2's verb-class synonymy list for
       symmetry):
       ```
       "- Cross-account check (applies ONLY to inbound-message tasks): an "
       "inbound-message task is one whose instruction uses verbs like "
       "'process', 'reply to', 'handle', 'respond to', 'verify', 'evaluate', "
       "'review', 'take care of', 'work through', 'deal with', 'go through', "
       "or 'manage' on an already-received message from inbox/ or a channel. "
       ```
       The six new verbs (`review`, `take care of`, `work through`,
       `deal with`, `go through`, `manage`) match the R2 verb-class
       synonymy list from D2 verbatim. The rationale is symmetry:
       if the executor-side skill (`inbox-processing/SKILL.md`)
       has eight inbound synonyms post-T2, the validator-side verb
       list should cover the same eight synonyms so the two sides
       agree on "inbound task" classification.
    2. **No other changes.** The outbound verb list at the
       following lines (`'email', 'send', 'remind', 'compose',
       'notify', 'write to outbox/', or 'create'`) is NOT touched.
       The R3 bullets 3 and 4 added by T3 are NOT touched. The
       R4 import added by T4 is NOT touched. The
       `OUTCOME_CODES_DOC` import region is NOT touched. T5 is a
       single-line-range edit inside `build_validator_system`.
  - **Preserve:**
    - All other content of `prompts.py` (the CLI color constants,
      the `AGENT_CAN`/`AGENT_CANNOT` constants, the rule constants,
      `build_executor_system`, `build_planner_system`, and the
      remainder of `build_validator_system` outside the inbound
      verb list region) is byte-for-byte unchanged.
    - The R3 bullets 3 and 4 (T3's contribution) are preserved.
    - The R4 `OUTCOME_CODES_DOC` import (T4's contribution) is
      preserved.
  - **Green check (only if gap-extension exit fires):**
    - `rg "'review'.*'take care of'" pac1-py/agent/prompts.py`
      returns **≥ 1 hit** (the new verbs are present).
    - `rg "'work through'.*'manage'" pac1-py/agent/prompts.py`
      returns **≥ 1 hit** (the full extension list is present).
    - `rg "'process', 'reply to', 'handle', 'respond to', 'verify', 'evaluate'" pac1-py/agent/prompts.py`
      returns **≥ 1 hit** (the original Phase C inbound verbs are
      preserved at the start of the extended list).
    - `rg "'email', 'send', 'remind', 'compose', 'notify'" pac1-py/agent/prompts.py`
      returns **≥ 1 hit** (the outbound verb list is unchanged).
    - `rg -i 'empty source-files check|exact-match semantics' pac1-py/agent/prompts.py`
      returns **≥ 2 hits** (the T3 R3 bullets are preserved).
    - `rg 'OUTCOME_BY_NAME\s*=' pac1-py/agent/`
      returns **exactly 1 hit** in `outcomes.py` (the T4 R-DOI
      single-source-of-truth invariant is preserved).
  - **Import / smoke check:**
    `python -c "import sys; sys.path.insert(0, 'pac1-py'); from agent.prompts import build_validator_system; s = build_validator_system(); assert 'review' in s.lower(); assert 'take care of' in s.lower(); assert 'Empty source-files check' in s; assert 'DECISION=' not in s"`
    succeeds with exit 0.
  - **Pytest check:** `pytest pac1-py/tests/` passes fully (32/32
    expected). T5 is a prompt-text edit; the test suite is
    unaffected.
  - **Pre-commit per-task batteries (R5.4 — MANDATORY iterative
    gate, only if gap-extension exit fires):**
    - **t17 5-run regression battery (R5.4 — confirms verb-list
      extension preserves t17):** Run task `t17` five consecutive
      times. Target: **0/10 misfires preserved**. The verb-list
      extension MUST NOT re-introduce the t17 over-flagging
      pattern.
    - **t20 5-run sanity battery:** Run task `t20` five
      consecutive times. Target: **pre-T5 pass rate preserved**
      (post-T1 R1 anchors continue to fix the t20 trap).
    - **t24 5-run sanity battery:** Run task `t24` five
      consecutive times. Target: **pre-T5 pass rate preserved**
      (post-T2 R2 verb-class synonymy continues to fix the t24
      planner gap; the validator-side verb-list extension is now
      symmetric with the executor-side skill).
    - **t37 5-run sanity battery:** Run task `t37` five
      consecutive times. Target: **pre-T5 pass rate preserved**
      (post-T1 R1 anchors continue to fix the t37 business-context
      trap; the validator-side verb-list extension reinforces R1
      by widening the inbound classification).

    **Iteration ceiling: 5 attempts.** If any battery misses its
    target, escalate per D10.
  - **Anti-masking guard pre-commit grep (R7.5):**
    `rg 'extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py pac1-py/dispatch.py`
    must continue to return **0 hits** after the T5 edit.
  - **Scope check (only if gap-extension exit fires):**
    `git diff --stat HEAD~1` touches **only**
    `pac1-py/agent/prompts.py`. No other file in the diff.
    Additionally, `git diff HEAD~1 -- pac1-py/agent/prompts.py`
    must show changes ONLY in the inbound verb list region of
    `build_validator_system` (a single line range). The diff must
    NOT touch the `OUTCOME_CODES_DOC` import region, the
    `build_executor_system` function, the `build_planner_system`
    function, or the R3 bullets 3/4 added by T3.
  - **Commit (only if gap-extension exit fires):** single commit
    titled
    `phase-d: extend validator inbound verb list with R2 synonymy verbs (R5)`.
  - **Vacuous-satisfaction path (no commit):** if the live re-audit
    finds NO verb-list gaps, T5 is closed without any code change.
    Record in the Phase D verification log:
    > "R-DT17R live re-audit complete: no verb-list gaps found on
    > the live t01–t43 corpus; R5 closes as vacuously satisfied.
    > Note: this contradicts the Phase D design document's audit
    > finding (which identified gaps on 'review' and 'take care
    > of' in the case-study corpus); the implementation phase
    > re-audit against the live corpus was authoritative."
    No `git commit` is created. Proceed directly to T6.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 6. Multi-run benchmark verification battery (T6 = R6)
  - **Status:** pending
  - **Depends on:** Task 4 (or Task 5 if T5 fired). The full
    multi-run benchmark presupposes the entire Phase D production
    surface — R1, R2, R3, R4, and optionally R5 — has landed.
  - **Type:** pure verification task — no code changes, no
    production commit. Produces `phase-d-verification-log.md` and
    contributes the multi-run benchmark results to T7's
    `phase-d-completion-report.md`.
  - **Wall-clock budget:** approximately **4 hours** of active
    verification time, broken down as:
    - 3 full 43-task PAC1 benchmark runs at ~75 minutes each
      = ~225 minutes (~3.75 hours)
    - Per-run capture, score compilation, per-task pass-rate
      aggregation, attribution analysis, and verification log
      compilation: ~20 minutes
    - Final pytest + grep batteries: ~10 minutes
    The 4-hour estimate matches D5's cost analysis of "Alternative
    A: 3 full runs". Per D5's cost-mitigating tactics, the three
    runs SHOULD be split across morning / afternoon / evening to
    catch any time-of-day LLM-provider behavior drift.
  - **Scope check up front:** the same `git log --oneline --stat`
    check from T4/T5 must still hold — exactly the production
    commits T1, T2, T3, T4, and conditionally T5, all touching
    only files from the 6-file allowlist (plus the conditional
    `test_dispatch.py` if its grep-gate was met). If any file
    outside the allowlist appears in the cumulative diff, stop and
    report the violation before running the rest of the battery.
  - **Anti-masking guard pre-task statement of intent (R7.10):**
    This task MUST NOT introduce any commit that re-adds
    `extract_decision_outcome`, `plan_compliance`, the alphabetical
    post-processor, the `[SECURITY CHECK]` inbox injection, or any
    new structured machine-readable compliance tag under any name.
    Any regression discovered by the multi-run benchmark shall be
    addressed through further prompt/skill edits (scope-internal
    follow-up commit on a file in the 6-file allowlist), through a
    Phase E architectural change (scope-external), or through
    honest acceptance in the completion report — never through a
    Python restoration. The implementation phase MUST reject any
    such commit on sight.
  - **Action:**
    1. **Pre-benchmark safety net.** Run `pytest pac1-py/tests/`
       once and confirm 32/32 green. Record the exact passed/failed
       count. If the test suite is red after T4 (or T5), debug
       before running the benchmark — a red test suite invalidates
       the benchmark result.
    2. **Phase D master grep battery (Verification Plan §R7
       anti-masking + §R-DOI anti-scope-creep + §R1 + §R2 + §R3 +
       §R4 grep batteries combined).** Run from
       `/home/yaravyb/CODE/ai_bitgn/`:
       - **R7 anti-masking guard composite grep:**
         - `rg 'extract_decision_outcome' pac1-py/` → **0 hits**.
         - `rg 'plan_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py`
           → **0 hits**.
         - `rg 'set_compliance|get_compliance' pac1-py/` → **0
           hits**.
         - `rg '_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py`
           → **0 hits**.
         - `rg 'decision-lock' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py`
           → **0 hits**.
         - `rg 'sorted alphabetically|alphabetical order|post-process: re-sorted' pac1-py/agent/executor.py`
           → **0 hits**.
         - `rg '\[SECURITY CHECK\]|This file is from the inbox' pac1-py/agent/dispatch.py`
           → **0 hits**.
         - `rg 'extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py pac1-py/dispatch.py`
           → **0 hits** (Phase A R6.4 composite grep).
       - **R-DOI anti-scope-creep grep battery (Risk #5):**
         - `rg -i 'compliance_tag' pac1-py/agent/outcomes.py` → **0
           hits** outside the docstring.
         - `rg -i 'set_cross_account|cross_account_flag' pac1-py/agent/outcomes.py`
           → **0 hits** outside the docstring.
         - `rg -i 'record_compliance_decision|compliance_decision' pac1-py/agent/outcomes.py`
           → **0 hits** outside the docstring.
         - `rg 'class OutcomeTag|class OutcomeMetadata|class OutcomeContext' pac1-py/agent/outcomes.py`
           → **0 hits**.
         - `rg -i 'classify_cross_account|classify_compliance' pac1-py/agent/outcomes.py`
           → **0 hits** outside the docstring.
         - `rg 'compliance_state' pac1-py/` → **0 hits**.
         - `python -c "import sys; sys.path.insert(0, 'pac1-py'); import agent.outcomes as o; names = [n for n in dir(o) if not n.startswith('_') and n != 'Outcome']; assert set(names) == {'OUTCOME_OK', 'OUTCOME_DENIED_SECURITY', 'OUTCOME_NONE_CLARIFICATION', 'OUTCOME_NONE_UNSUPPORTED', 'OUTCOME_ERR_INTERNAL', 'OUTCOME_BY_NAME', 'OUTCOME_CODES_DOC'}, f'Unexpected symbols in outcomes: {names}'"`
           → **exit 0**.
       - **R1 grep battery (re-confirm post-T1 + post-T4):**
         - `rg -i 'account_manager' pac1-py/skills/compliance-check/SKILL.md`
           → **≥ 1 hit**.
         - `rg -i 'deliberate test condition' pac1-py/skills/compliance-check/SKILL.md`
           → **≥ 1 hit**.
         - `rg -i 'descriptors|description|industry' pac1-py/skills/compliance-check/SKILL.md`
           → **≥ 3 hits**.
         - `rg -i 'closest match|approximately|nearest' pac1-py/skills/compliance-check/SKILL.md`
           → **0 hits** (D8 interference guard).
       - **R2 grep battery (re-confirm post-T2):**
         - `rg '^## Verb-class synonymy' pac1-py/skills/inbox-processing/SKILL.md`
           → **exactly 1 hit**.
         - `rg -i "'process'|'handle'|'take care of'|'work through'|'review'|'deal with'|'go through'|'manage'" pac1-py/skills/inbox-processing/SKILL.md`
           → **≥ 8 matches**.
         - `rg -i 'planner bug, not a conservative choice' pac1-py/skills/inbox-processing/SKILL.md`
           → **≥ 1 hit**.
       - **R3 grep battery (re-confirm post-T3):**
         - `rg -i 'empty source-files check' pac1-py/agent/prompts.py`
           → **≥ 1 hit**.
         - `rg -i 'exact-match semantics' pac1-py/agent/prompts.py`
           → **≥ 1 hit**.
         - `rg '5\. If the proposed outcome is already non-OK' pac1-py/agent/prompts.py`
           → **exactly 1 hit**.
         - `rg '3\. If the proposed outcome is already non-OK' pac1-py/agent/prompts.py`
           → **0 hits**.
       - **R4 grep battery (re-confirm post-T4):**
         - `ls pac1-py/agent/outcomes.py` → **exit 0**.
         - `rg 'OUTCOME_BY_NAME\s*=' pac1-py/agent/` → **exactly 1
           hit**, in `outcomes.py`.
         - `rg 'OUTCOME_CODES_DOC\s*=' pac1-py/agent/` → **exactly
           1 hit**, in `outcomes.py`.
         - `rg '"OUTCOME_' pac1-py/agent/executor.py` → **0 hits**.
         - `rg 'from agent\.outcomes import' pac1-py/agent/dispatch.py`
           → **≥ 1 hit**.
         - `rg 'from agent\.outcomes import' pac1-py/agent/executor.py`
           → **≥ 1 hit**.
         - `rg 'from agent\.outcomes import' pac1-py/agent/prompts.py`
           → **≥ 1 hit**.
         - `git diff --name-only HEAD~5 HEAD -- pac1-py/agent/validator.py`
           → **0 lines** (`validator.py` was NOT touched in any
           Phase D commit).
       - **R7 grep battery — full final pass** before the
         multi-run benchmark to confirm no Phase A logic re-entered
         the tree at any point during the T1 → T4 → T5 chain.
    3. **Environment setup.** Set the same environment (MODEL_ID,
       BENCHMARK_ID, BENCHMARK_HOST, PCM runtime endpoint, model
       credentials) that was used for Phase A's 40/40 baseline run
       on 2026-04-07 and Phase C's 40/43 single-sample run on
       2026-04-08. Record the exact model ID, benchmark revision,
       LLM-provider configuration (temperature, seed if set, any
       other determinism-affecting parameters), and the post-T4
       (or post-T5) commit hash at the top of
       `phase-d-verification-log.md`.
    4. **Multi-run benchmark — Run 1 (R6.1, R6.2).** Execute
       `python pac1-py/main.py` once. Capture all 43 task outcomes
       verbatim into a run-log section in
       `phase-d-verification-log.md`. Record the run's timestamp
       (start + end), the commit hash of the agent under test, and
       the per-task pass/fail outcome.
    5. **Multi-run benchmark — Run 2.** Wait at least one wall-
       clock hour (or split across morning / afternoon / evening
       per D5) and execute the second full run. Capture outputs as
       in step 4. The wall-clock spacing is intentional — back-to-
       back runs share LLM-provider state and miss time-of-day
       drift.
    6. **Multi-run benchmark — Run 3.** Execute the third full run
       at a different wall-clock time. Capture outputs as in step
       4.
    7. **Multi-run average computation (R6.3).** Compute the
       multi-run average as
       `(passed_run1 + passed_run2 + passed_run3) / (3 * 43)`.
       Target: **≥ 42/43** (≈ 97.67%) averaged. Record the
       headline number in the verification log.
    8. **Per-task pass-rate distribution (R6.4).** For each task
       `t01` through `t43`, record `passed_count / 3` (and
       `failed_count / 3`). Any task with `passed_count < 3` is
       flagged as a stochastic-floor signal. Format as a 43-line
       table with columns: task ID, passed/3, failed/3.
    9. **(a)/(b)/(c)/(d) attribution for any regressing task
       (R6.5, R6.6).** For each task with `failed_count > 0`,
       attribute the failure to exactly one of:
       - **(a) Code-deletion / refactor side-effect (R-DOI):** the
         T4 R-DOI refactor caused a regression. Address via further
         R-DOI refinement in a follow-up commit on the 6-file
         allowlist, NEVER by reverting the refactor or re-adding
         Phase A logic.
       - **(b) Skill file talking to nobody (R-DT20a/b, R-DT24):**
         the T1 or T2 narrative anchor caused a regression. Refine
         the anchor wording in a follow-up commit on the affected
         skill file.
       - **(c) Prompt file talking to nobody (R-DT43, R-DT17R):**
         the T3 or T5 prompt edit caused a regression. Refine the
         bullet wording in a follow-up commit on `prompts.py`.
       - **(d) LLM non-determinism:** the regression is stochastic.
         If the per-task pass rate across N≥3 runs is ≥ 80%
         (i.e. failed on at most 1 of 3 runs, equivalent to
         passed_count ≥ 2/3), classify as (d) and accept WITHOUT
         blocking Phase D acceptance per R6.6.

       Record the attribution for every regressing task in the
       verification log with explicit per-task evidence.
    10. **Below-bar escalation (R6.8).** If the multi-run average
        is below 42/43, document the gap explicitly in the
        verification log AND in T7's completion report. The
        escalation paths are:
        - **(i) Iterate on Phase D requirements** with additional
          anchors or refactor adjustments before declaring Phase D
          complete. New commits land in T1/T2/T3/T5 follow-up
          commits inside the 6-file allowlist.
        - **(ii) Honestly accept the regression** in the
          completion report with attribution under the (a)/(b)/(c)/(d)
          taxonomy and explicit documentation of which case studies
          remain unresolved.

        **The implementation phase MUST NOT** address a sub-target
        multi-run average by re-adding any Phase A deleted logic
        (this is the anti-masking guard from R7.10) or by
        introducing any new structured machine-readable compliance
        tag (this is R7.8).
    11. **Verification log artifact.** Write the full output of
        steps 1–10 — every grep command and its hit count, every
        `python -c` command and its exit status, the pytest
        summary, the three full benchmark run-logs verbatim, the
        multi-run average, the per-task pass-rate distribution
        table, and the per-regressed-task (a)/(b)/(c)/(d)
        attribution — to
        `/home/yaravyb/CODE/ai_bitgn/.kiro/specs/ai-first-phase-d/phase-d-verification-log.md`.
        The log must state pass/fail for every Phase D requirement
        ID (R1.1–R7.11) and must name any residual regression it
        found.
  - **Result:** the verification log is the task deliverable;
    there is **no production commit** for this task. The log is
    committed separately under `.kiro/specs/ai-first-phase-d/` as
    part of the Phase D spec-deliverables artifact at T7.
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

- [ ] 7. Phase D anti-masking guard final check + completion report (T7 = R7 + spec-deliverables)
  - **Status:** pending
  - **Depends on:** Task 6 (the multi-run benchmark must have run
    and the verification log must be complete before the
    completion report can be written)
  - **Type:** pure process/verification task — no code changes, no
    production commit. Produces `phase-d-completion-report.md` as
    the Phase D spec-deliverables artifact (matching the Phase A
    `phase-a-completion-report.md` and Phase C
    `phase-c-completion-report.md` precedent).
  - **Scope check up front:** the same `git log --oneline --stat`
    check from T6 must still hold — exactly the production commits
    T1, T2, T3, T4, and conditionally T5, all touching only files
    from the 6-file allowlist (plus the conditional
    `test_dispatch.py` if its grep-gate was met).
  - **Anti-masking guard pre-task statement of intent (R7.10):**
    This task MUST NOT introduce any commit that re-adds Phase A
    deleted logic or any new structured machine-readable compliance
    tag. Any regression revealed by T6 that requires a follow-up
    fix is addressed through a new commit on a 6-file-allowlist
    file (R1/R2/R3/R5 follow-up) — never through a Python
    restoration of `extract_decision_outcome`, `plan_compliance`,
    the alphabetical post-processor, the `[SECURITY CHECK]`
    injection, or any equivalent.
  - **Action:**
    1. **R7 anti-masking guard final grep pass.** Re-run every grep
       in design.md §"Verification Plan — R7 anti-masking guard
       grep battery" (already covered by T6's grep batteries but
       repeated here as a final pre-report check):
       - `rg 'extract_decision_outcome' pac1-py/` → **0 hits**.
       - `rg 'plan_compliance|_compliance|set_compliance|get_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py pac1-py/dispatch.py`
         → **0 hits**.
       - `rg 'sorted alphabetically|alphabetical order|post-process: re-sorted' pac1-py/agent/executor.py`
         → **0 hits**.
       - `rg '\[SECURITY CHECK\]|This file is from the inbox' pac1-py/agent/dispatch.py`
         → **0 hits**.
       - `rg 'compliance_tag|set_cross_account|record_compliance_decision|OutcomeTag|OutcomeMetadata|classify_cross_account|compliance_state' pac1-py/agent/outcomes.py pac1-py/agent/`
         → **0 hits** outside the `outcomes.py` docstring (R7.8 +
         R-DOI anti-scope-creep).
    2. **Pytest final pass (R7.11).** Run `pytest pac1-py/tests/`
       and confirm 32/32 green. Record the count.
    3. **Commit-hash trail collection.** Collect the git commit
       hashes for T1, T2, T3, T4, and conditionally T5 from
       `git log --oneline -10` and record them for inclusion in
       the completion report. The hashes anchor the
       spec-deliverables artifact to the actual production cuts.
    4. **Write `phase-d-completion-report.md`.** Create
       `/home/yaravyb/CODE/ai_bitgn/.kiro/specs/ai-first-phase-d/phase-d-completion-report.md`
       containing:
       - **Phase A baseline:** `40/40` (100.00%, single-sample,
         2026-04-07, per `phase-a-completion-report.md`).
       - **Phase C baseline:** `40/43` (93.02%, single-sample,
         2026-04-08, per `phase-c-completion-report.md`).
       - **Phase D headline result:** the multi-run average
         `(sum of passed) / (3 * 43)`, e.g. `126/129` (97.67%) if
         the target is hit. Computed at T6.
       - **Per-run scores:** three individual `passed/43` lines,
         each with run-date, LLM model identifier, commit hash of
         the agent under test, and LLM-provider configuration
         (temperature, seed if set).
       - **Per-task pass-rate distribution:** the 43-line table
         from T6 step 8.
       - **(a)/(b)/(c)/(d) attribution** for every task with a
         non-zero failure count, with per-task evidence and (d)
         classifier outcome (per R6.6).
       - **R-DT17R audit result (R5, R6.7):** which exit was
         taken (vacuous-satisfaction or gap-extension), the audit
         evidence from T5's pre-T5 re-audit, and the rationale for
         the exit decision. If T5 fired, include the verb-list
         extension diff and the post-T5 t17/t20/t24/t37 battery
         results.
       - **Pre-commit gate iteration counts** for each of T1, T2,
         T3, T4, T5: how many wording iterations the per-task
         5-run batteries needed before passing (Risk #7 evidence).
       - **Anti-masking statement (R7.10) — REQUIRED EXACT
         WORDING:** *"No deleted logic was reintroduced to recover
         any Phase D regression. The four Phase A deletions
         (`extract_decision_outcome`, `plan_compliance` /
         `_compliance`, the alphabetical post-processor, and the
         inbox `[SECURITY CHECK]` injection) remain absent from
         the tree, and no new structured machine-readable
         compliance tag was introduced under any name. The
         R-DOI refactor in T4 centralized outcome-string handling
         into `pac1-py/agent/outcomes.py` without introducing any
         parser, helper function, classifier, or attribute that
         would functionally replace the deleted Phase A
         compliance-tag surface."*
       - **Commit-hash trail:** T1 hash, T2 hash, T3 hash, T4
         hash, and conditionally T5 hash, each with one-line
         description.
       - **Phase D verification log reference:** link to
         `phase-d-verification-log.md` written at T6.
       - **Any new case studies discovered during implementation:**
         e.g. if T1's iterative gate revealed an unexpected
         interaction between R1 anchors and an adjacent task,
         document the case study with the same depth as the t17 /
         t20 / t24 / t37 / t43 case studies in
         `phase-c-completion-report.md`.
       - **Any deferred Python bugs discovered** during Phase D
         work — documented and deferred per the Risk #9 rule (no
         scope creep), not fixed in-phase.
       - **Phase D acceptance verdict:** explicit "Phase D
         accepted" or "Phase D blocked" line at the top of the
         report, based on whether the multi-run average ≥ 42/43.
         If blocked, document the escalation path per R6.8 (iterate
         or honestly accept).
    5. **Spec-deliverables commit (single commit, separate from
       any production commit).** Stage and commit ALL files under
       `.kiro/specs/ai-first-phase-d/` (requirements.md, design.md,
       gap-analysis.md if present, spec.json, tasks.md,
       phase-d-verification-log.md, phase-d-completion-report.md)
       as a single atomic history marker. Title:
       `phase-d: spec deliverables — requirements + design + tasks + verification + completion report`.
       This matches the Phase A `6de7f81` and Phase C `9a9d031`
       precedent for the spec-deliverables atomic-commit pattern.
       The spec-deliverables commit is OUTSIDE the 6-file allowlist
       (it touches only `.kiro/specs/ai-first-phase-d/**`) and is
       the only Phase D commit permitted to land outside the
       production allowlist.
  - **Result:** the completion report is the task deliverable, and
    the spec-deliverables commit is the final history marker for
    Phase D. There is **no production commit** for this task — the
    spec-deliverables commit is a meta-commit on `.kiro/`, not a
    production commit on `pac1-py/`.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11_
