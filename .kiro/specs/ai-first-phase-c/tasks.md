# Implementation Plan — Phase C (Prompt and Skill Cleanup)

## Deletion order (locked)

```
T1 (R1) → T2 (R2 + R3, ATOMIC) → T3 (R4, ATOMIC) → T4 (R4 master grep + pytest) → T5 (R5 + R6 benchmark + report)
```

This order is locked by design.md §"Edit Order and Smoke-test Checkpoints"
and by D4. The rationale is:

- **T1 = R1** first because the validator-prompt loosening is the only edit
  whose effect must be measured in isolation against the t17 5-run battery
  (R1.7). Landing R1 by itself means any change in the t17 misfire rate is
  attributable solely to the prompt loosening, not to a blend of prompt +
  skill rewrites. T1 is also the safest intermediate state to leave the tree
  in if the session is interrupted between commits: the validator no longer
  looks for `DECISION=` markers, but the executor still emits them, so the
  validator simply reads them as inert text alongside its `<source-files>`
  re-verification block (`validator.py:32–45`).
- **T2 = R2 + R3** second, as a single atomic commit. The two skills
  (`compliance-check/SKILL.md` and `inbox-processing/SKILL.md`) are tightly
  cross-referenced — `inbox-processing` Phase 4 explicitly says
  *"For messages marked PROCEED, load `compliance-check` skill"* — and both
  currently describe the same dead `plan_compliance(...)` tool call. Landing
  them in separate commits would create an intermediate tree where one skill
  references the deleted tool and the other does not, which is a more
  confusing half-state than the per-cut atomicity is meant to avoid. **See
  the Atomic-commit invariant section below.**
- **T3 = R4** third, also as a single atomic commit covering
  `identity-verification/SKILL.md:16,33` plus `execution-discipline/SKILL.md:29`.
  The R4 audit surfaced a cross-skill marker-convention dependency: the
  rewritten `inbox-processing/SKILL.md` (T2) instructs the executor to reason
  in free text and to **not** emit `VERIFY <msg>: ... trust=<level>`
  markers, but `identity-verification/SKILL.md` lines 16 and 33 still
  template that exact marker, and `execution-discipline/SKILL.md:29` still
  names the `VERIFY plan_notes` requirement by that label. Landing the three
  edits in one commit means the cross-file marker convention flips from
  "everywhere" to "nowhere" in a single step. **See the Atomic-commit
  invariant section below.**
- **T4 = R4 master grep + pytest verification battery** runs after T3 lands.
  This is a pure verification task — no production commit, just the master
  grep battery, the YAML front-matter loader smoke check, and `pytest
  pac1-py/tests/`. Produces a verification log artifact only.
- **T5 = R5 benchmark re-run + R6 anti-masking confirmation** runs the full
  PAC1 benchmark, the post-T3 t17 5-run confirmation battery, and writes
  `phase-c-completion-report.md`. No production commit.

Each step's "Scope check" must run `git diff --stat HEAD~1` against the
allowed-files list below. Any file outside the list in the diff is a scope
violation and must be reverted before the commit can proceed.

## Scope enforcement

### Allowed files for Phase C edits (authoritative 5-file list)

1. `pac1-py/agent/prompts.py` (T1 — `build_validator_system` surgical edit only;
   `build_executor_system` and `build_planner_system` are grep-clean per the
   R4 audit and are NOT touched)
2. `pac1-py/skills/compliance-check/SKILL.md` (T2 — step 4 narrative rewrite)
3. `pac1-py/skills/inbox-processing/SKILL.md` (T2 — per-phase narrative rewrite)
4. `pac1-py/skills/identity-verification/SKILL.md` (T3 — lines 16 and 33 template rewrite)
5. `pac1-py/skills/execution-discipline/SKILL.md` (T3 — line 29 phrasing fix)

### Forbidden files in Phase C (scope violation if touched)

- Every Python file under `pac1-py/` other than the surgical
  `build_validator_system` edit inside `pac1-py/agent/prompts.py`. Specifically
  forbidden: `pac1-py/main.py`, `pac1-py/tasks.py`, `pac1-py/tools.py`,
  `pac1-py/skills.py`, `pac1-py/agent/__init__.py`, `pac1-py/agent/bootstrap.py`,
  `pac1-py/agent/planner.py`, `pac1-py/agent/executor.py`,
  `pac1-py/agent/validator.py`, `pac1-py/agent/dispatch.py`,
  `pac1-py/agent/context.py`, `pac1-py/agent/llm.py`,
  `pac1-py/agent/config.py`.
- Every test file under `pac1-py/tests/**` (including `conftest.py`,
  `test_compact_tree.py`, `test_skill_loader.py`, `test_dispatch.py`,
  `test_task_manager.py`).
- `pac1-py/skills/security-posture/SKILL.md` and
  `pac1-py/skills/date-arithmetic/SKILL.md` (both grep-verified
  audit-clean — no edits).
- Every `AGENTS.md` or `README.md` under `pac1-py/`.
- `pac1-py/observability/**`.
- Every file under `.kiro/specs/` other than files inside
  `.kiro/specs/ai-first-phase-c/`.

Every task below includes a mandatory **Scope check**: the task's git diff
MUST touch only files from the 5-file allowlist and nothing from the
forbidden list. The implementation phase MUST reject any diff that violates
this invariant.

## Parallelizability

Phase C is **fully sequential**. The chain T1 → T2 → T3 → T4 → T5 is locked
by D4 and by Risk #4 (cross-file marker-convention inconsistency window):

- **T1 must precede T2 and T3** because the post-T1 t17 5-run battery is the
  empirical gate for R1.7 and its measurement must attribute any rate change
  to the prompt edit in isolation, not to a blend of prompt + skill changes.
- **T2 and T3 cannot be parallelized**: between T2 and T3, the tree contains
  the rewritten `inbox-processing/SKILL.md` (which no longer instructs the
  executor to emit `trust=<level>` or `VERIFY <msg>` markers) and the
  unchanged `identity-verification/SKILL.md` (which still templates exactly
  those markers at lines 16 and 33). An executor LLM that loads both skills
  in Phase 1 of `inbox-processing` would see a cross-file marker convention
  conflict. This window is bounded by Risk #4 to "at most one commit cycle"
  and is the explicit reason **the benchmark and the t17 5-run battery MUST
  NOT run between T2 and T3** (see T2's task body and the Edit Order table
  in design.md).
- **T4 must follow T3** because the master grep battery presupposes all
  three production cuts have landed.
- **T5 must follow T4** because the PAC1 benchmark re-run is the final
  honest check and depends on a green test suite + clean grep battery.

No task in this file carries a `(P)` marker — the chain is fully linear by
design, not by absence of analysis.

## TDD adaptation note

Classical red → green → refactor does not apply to prompt and skill text
cleanup. Each task below uses the same **grep-based "red/green" pattern**
that Phase A used for surgical deletion:

- **Red check** = a shell one-liner (`rg ...`) that currently matches the
  dead-letter literal to be removed. The command is captured in the task
  acceptance criteria, not in a Python test file.
- **Green check** = the same `rg` command (or a complementary one) returning
  zero matches after the rewrite.
- **Refactor** = `pytest pac1-py/tests/` must remain green with no
  collateral breakage (the smoke check catches accidental YAML front-matter
  corruption that would break `SkillLoader` at import time), plus, for T1
  only, the **t17 5-run iterative gate** for R1.7.

The t17 5-run battery is the one non-grep gate in the chain: it runs the
agent against task `t17` five times in a row and measures the rate at which
the validator over-corrects an `OUTCOME_OK` response to
`OUTCOME_NONE_CLARIFICATION`. The Phase A baseline for this measurement is
**~14% (1 misfire in 7 runs)**, captured in
`phase-a-completion-report.md` line 149 ("1/7 observations"). Phase C's
target is **≤ 1%** (operationally: 0/5 misfires on a five-run battery, or
≤ 1/10 misfires on a ten-run extension if 0/5 is not conclusive).

Phase C does not edit any test file. The test suite is expected to be
green-by-construction after each commit because no test asserts on any of
the dead-letter literals being removed — the three Phase A test deletions
already cleared the test-side fallout.

## Atomic-commit invariant

Two of the production commits below must each land as a single atomic commit
covering multiple files. This mirrors Phase A's risk-register-row-3 treatment
of T4's `validator.py`/`executor.py`/`test_decision_lock.py` cascade.

### T2 atomic-commit invariant (R2 + R3 in one commit)

T2 must land as a single git commit covering both:

1. `pac1-py/skills/compliance-check/SKILL.md` step 4 narrative rewrite (R2).
2. `pac1-py/skills/inbox-processing/SKILL.md` per-phase narrative rewrite,
   covering Phase 1 step 3, Phase 1.5 CONFLICT-check, Phase 3 steps 6/7/8,
   Phase 4 (the entire `plan_compliance` block + the `decision-lock`
   sentence), Phase 5 lines 82–83, and the bottom "Key rule" sentence (R3).

The two files are tightly coupled: `inbox-processing` Phase 4 explicitly
references `compliance-check` by name (*"For messages marked PROCEED, load
`compliance-check` skill"*), and both files currently describe the same
deleted `plan_compliance(...)` tool call. Splitting this across two commits
leaves an intermediate tree where one skill references a tool the other
skill no longer uses, which is exactly the cross-file inconsistency the
atomic invariant exists to prevent. The task's commit step is therefore
explicitly **one git commit**.

### T3 atomic-commit invariant (R4 cross-skill convention flip in one commit)

T3 must land as a single git commit covering both:

1. `pac1-py/skills/identity-verification/SKILL.md` lines 16 and 33 — both
   `plan_note("VERIFY <msg>: ...")` template literals rewritten to free-text
   narrative.
2. `pac1-py/skills/execution-discipline/SKILL.md` line 29 — the
   *"you MUST have VERIFY plan_notes for each message before acting"*
   sentence rephrased to *"you MUST have a free-text `plan_note` for each
   message describing what you verified before acting"*.

Splitting this across two commits leaves an intermediate tree where the
`VERIFY plan_notes` convention is partially rewritten and partially still
named — i.e. a cross-file marker-convention inconsistency mirroring the one
T2 atomicity prevents. The whole purpose of T3 is to flip the
`VERIFY <msg>` convention from "named in three places" to "named in zero
places" in a single step. The task's commit step is therefore explicitly
**one git commit**.

Both invariants are enforced at implementation time: any T2 or T3 commit
that touches only one of its bundled files must be amended (or split-and-
re-merged) before proceeding to the next task.

---

## Tasks

- [x] 1. Loosen `build_validator_system` in `prompts.py` (T1 = R1)
  - **Status:** done (commit `631e36d`, 2026-04-08; t17 5-run battery 0/5 misfires on iteration 1)
  - **Depends on:** nothing (first cut in the chain)
  - **Files:** `pac1-py/agent/prompts.py` (function `build_validator_system`,
    lines 174–210; specifically the cross-account sub-clause at lines
    196–199 and the entire `<checks>` bullet 3 at lines 202–206)
  - **Red check:**
    `rg -n 'DECISION=DENY_SECURITY|DECISION=DENY_CLARIFY|DECISION=PROCEED' pac1-py/agent/prompts.py`
    must currently return **3 hits** (lines 203, 204, 205). If it does not,
    stop and re-read design.md §"R1 — Validator prompt loosening" before
    proceeding — the line numbers may have drifted.
  - **Action (single commit):**
    1. **Edit 1 (R1.1–R1.3, R1.6) — delete `<checks>` bullet 3 in its
       entirety.** Remove lines 202–206 (the entire `"3. Look at
       VERIFY...DECISION notes in execution context:\n"` block, including
       the three `DECISION=` sub-bullets and the trailing
       `"a problem → ESCALATE to DENIED_SECURITY or CLARIFICATION.\n"`
       fragment). Renumber the existing bullet 4
       (`"4. If the proposed outcome is already non-OK, approve it.\n"`)
       to `"3. ..."` so the check list stays numbered contiguously.
    2. **Edit 2 (R1.4, R1.5) — rewrite the cross-account sub-clause at
       lines 196–199 to be inbound-only**, with the indicator-verb list from
       D1 baked into the instruction. The after-state must (a) gate the
       check on inbound-message tasks only, (b) name an indicator-verb list
       for inbound (`process`, `reply to`, `handle`, `respond to`, `verify`,
       `evaluate`) and outbound (`email`, `send`, `remind`, `compose`,
       `notify`, `write to outbox/`, `create`), (c) explicitly state that
       outbound tasks skip the check entirely, and (d) preserve the
       inbound-task escalation to `OUTCOME_NONE_CLARIFICATION` when the
       message body requests data about a different company than the
       sender's account. The proposed wording is in design.md §"R1 — Edit
       2"; the implementation phase may refine the wording but must
       preserve the inbound/outbound gating semantics and the verb list.
  - **Preserve:** the `<role>` header (lines 176–177), the `<rules>` block
    (lines 178–187), `<checks>` bullet 1 (lines 189–190), `<checks>` bullet
    2 lead-in (lines 191–193), the email-match sub-clause (lines 194–195),
    the security-flags sub-clause (lines 200–201), and the final
    `"Use the validate_answer tool."` line (209) all remain
    byte-for-byte. R1.8 is satisfied by this scoping. The function
    signature `build_validator_system() -> str` is unchanged.
  - **Green check:**
    - `rg -n 'DECISION=DENY_SECURITY|DECISION=DENY_CLARIFY|DECISION=PROCEED' pac1-py/agent/prompts.py`
      returns **0 hits** (R1.6).
    - `rg -n 'VERIFY\.\.\.DECISION|verify_decision' pac1-py/agent/prompts.py`
      returns **0 hits** (R1.3).
    - `rg -ni 'inbound|outbound' pac1-py/agent/prompts.py` returns **≥ 1
      hit** (the new cross-account gate is present).
  - **Import / smoke check:**
    `python -c "from agent.prompts import build_validator_system; s = build_validator_system(); assert 'DECISION=' not in s; assert ('INBOUND' in s.upper() or 'inbound' in s); assert len(s) > 500"`
    succeeds with exit 0.
  - **Pytest check:** `pytest pac1-py/tests/` passes fully. The test suite
    is unaffected by this edit (no test asserts on any `DECISION=` literal
    inside the validator prompt).
  - **t17 5-run battery (R1.7 iterative gate — pre-commit, MANDATORY):**
    Run task `t17` five consecutive times against the locally-edited tree
    (do **not** commit yet). Record the outcome of each run. The gate
    passes if **0/5 runs** show a validator misfire (an `OUTCOME_OK`
    over-corrected to `OUTCOME_NONE_CLARIFICATION`), or if a ten-run
    extension shows ≤ 1/10 misfires when 0/5 is not conclusive. The
    Phase A baseline for this measurement is **~14% (1 misfire in 7 runs,
    per `phase-a-completion-report.md` line 149)**; the target is **≤ 1%**.

    **The t17 5-run battery is an iterative gate. Maximum 5 wording
    iterations; escalate after 3 unsuccessful iterations per the Risk #2
    mitigation paths (either (a) add more concrete examples of outbound
    tasks the validator should NOT flag directly into the prompt text,
    making the instruction more few-shot-like, or (b) document the
    achievable rate in the Phase C completion report and defer the
    residual brittleness to Phase D, which can architect a task-
    classification step earlier in the pipeline). Do NOT commit T1 until
    the gate passes or escalation lands.** Neither escalation path
    re-adds Phase A deleted logic.

    Record the iteration count and the per-run outcomes in a scratch
    log to be folded into `phase-c-completion-report.md` at T5.
  - **Scope check:** `git diff --stat HEAD~1` touches **only**
    `pac1-py/agent/prompts.py`. No other file in the diff.
  - **Commit:** single commit titled
    `phase-c: loosen build_validator_system — drop dead DECISION= block, gate cross-account on inbound-only (R1)`.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

- [x] 2. Rewrite `compliance-check` and `inbox-processing` skills (T2 = R2 + R3, ATOMIC)
  - **Status:** done (atomic commit `27d054e`, 2026-04-08; master grep returns 0 hits; inbox-processing = 110 lines, within [80, 120])
  - **Depends on:** Task 1 (T1 must be committed and the t17 gate passed
    before T2 begins)
  - **Files (single atomic commit):**
    - `pac1-py/skills/compliance-check/SKILL.md` — step 4 at lines 29–30
      (current `plan_compliance(...)` tool-call literal).
    - `pac1-py/skills/inbox-processing/SKILL.md` — Phase 1 step 3 at lines
      14–15, Phase 1.5 conflict-check at line 23, Phase 3 steps 6/7/8 at
      lines 42, 46, 50, the rule bullets at lines 51–61 (specifically
      `trust=admin` at line 53 and the `DENY_SECURITY/DENY_CLARIFY/PROCEED`
      labels at lines 56–60), Phase 4 lines 63–77 (the entire
      `plan_compliance(...)` block plus the `decision-lock` sentence),
      Phase 5 lines 82–83, and the bottom "Key rule" sentence at line 100.
  - **Atomic-commit invariant:** Both files MUST land in the same git
    commit. See "Atomic-commit invariant" section above for the rationale —
    splitting this across two commits leaves the tree in a state where one
    skill references the deleted `plan_compliance` tool while the other
    does not, which is the exact cross-file inconsistency the invariant
    exists to prevent.
  - **Red check:**
    - `rg -n 'plan_compliance|set_compliance|get_compliance|trust=admin|trust=valid|trust=blacklist|trust=unmarked|DECISION=DENY_SECURITY|DECISION=DENY_CLARIFY|DECISION=PROCEED|CONFLICT DETECTED|decision-lock' pac1-py/skills/compliance-check/SKILL.md pac1-py/skills/inbox-processing/SKILL.md`
      must currently return **at least 8 hits** across the two files
      (verified pre-task: `compliance-check/SKILL.md:30` and
      `inbox-processing/SKILL.md:23,53,67,69,77,82,83`).
    - `rg -n 'VERIFY msg_' pac1-py/skills/inbox-processing/SKILL.md` must
      currently return **3 hits** (lines 42, 46, 50).
  - **Action (single atomic commit covering both files):**
    1. **`compliance-check/SKILL.md` step 4 (R2.1, R2.3) — narrative
       rewrite.** Replace lines 29–30 with the D2 narrative branch:
       *"4. **Record your reasoning** in a free-text `plan_note`. Describe
       what you checked (which account records you read, which flags you
       saw, whether the request is cross-account), what you concluded,
       and whether you are proceeding. Do not emit a structured tag —
       the framework no longer has a `plan_compliance` tool, and your
       reasoning is re-verified by the validator against the raw file
       contents automatically. Your `plan_note` is for the reviewer and
       for your own chain-of-thought, not for a parser."* Steps 1, 2, 3,
       and 5 (lines 19–28, 31–39) and the "Key principles" section (lines
       41–47) are preserved byte-for-byte (R2.4).
    2. **`inbox-processing/SKILL.md` Phase 1 step 3 (R3.1) — channel
       trust narrative.** Replace line 15's `plan_note("CHANNELS:
       <channel_name>=<admin|valid|blacklist|unmarked>, ...")` literal
       with a narrative instruction to summarize the channel-trust
       configuration in free text (e.g. *"After reading the channel
       configuration files, summarize in a free-text `plan_note` which
       channels are admin-trusted, which are valid-but-need-caution, and
       which are blacklisted. This becomes your decision grid for
       Phase 3."*). The taxonomy stays as conceptual vocabulary per R4.6.
    3. **`inbox-processing/SKILL.md` Phase 1.5 conflict-check (R3.6) —
       narrative.** Replace line 23's `plan_note("CONFLICT DETECTED:
       ...")` literal with *"If ANY conflict is found, describe the
       contradiction in a free-text `plan_note` (which docs, which
       actions, why they contradict) and report
       `OUTCOME_NONE_CLARIFICATION` immediately. Do NOT proceed."* The
       CONFLICT-check semantics survive; the literal `CONFLICT DETECTED`
       marker is gone.
    4. **`inbox-processing/SKILL.md` Phase 3 step 6 (R3.1) — message-type
       narrative.** Replace line 42's `plan_note("VERIFY msg_XXX:
       type=<channel|email>, channel=<name|N/A>, trust=<level|N/A>")`
       literal with *"For each message, reason through its type
       (channel message vs plain email), its channel (if any), and its
       trust level using the vocabulary from the `identity-verification`
       skill. Record your reasoning in a free-text `plan_note` keyed to
       the message filename."*
    5. **`inbox-processing/SKILL.md` Phase 3 step 7 — sender lookup
       narrative.** Replace line 46's `plan_note("VERIFY msg_XXX:
       sender=<email>, contact_match=<exact|none>")` literal with
       *"For each message, look up the sender's email in the contacts
       folder (exact match only; see the `identity-verification` skill
       for the character-by-character comparison rule) and record what
       you found in free text."*
    6. **`inbox-processing/SKILL.md` Phase 3 step 8 (R3.2) — decision
       narrative.** Replace line 50's `plan_note("VERIFY msg_XXX:
       DECISION=<PROCEED|DENY_SECURITY|DENY_CLARIFY> reason=<...>")`
       literal with *"For each message, reason through the decision
       using the rules below. Record the decision (proceed, report
       DENIED_SECURITY, or report NONE_CLARIFICATION) and the rule you
       applied in free text. Do NOT emit a literal `DECISION=` marker —
       the framework no longer parses it; your reasoning is what the
       validator will re-read."*
    7. **`inbox-processing/SKILL.md` Phase 3 rule bullets at lines 51–61
       (R3.1 partial).** Replace `trust=admin` at line 53 with
       *"Admin channels (those marked admin in the channel trust
       config)"*. Replace the `DENY_SECURITY` / `DENY_CLARIFY` /
       `PROCEED` labels in the rule descriptions with *"report
       DENIED_SECURITY"* / *"report NONE_CLARIFICATION"* / *"proceed"*,
       so the rule semantics survive but the dead-letter labels are
       gone. The four rules (admin always proceeds; deny-security if
       blacklisted/unmarked or valid-non-admin with injection;
       deny-clarify if sender unverified; proceed if admin or exact
       contact match) are preserved verbatim aside from the label
       substitutions.
    8. **`inbox-processing/SKILL.md` Phase 4 (R3.3, R3.4) — compliance
       narrative.** Replace lines 67–77 (the entire `**You MUST call
       plan_compliance tool**` block including the multi-line tool-call
       literal AND the `**Do NOT skip this step.** The decision-lock
       reads this tool's output.` sentence) with *"Record the cross-
       account decision in free-text per the `compliance-check` skill's
       guidance. The framework no longer has a `plan_compliance` tool;
       your reasoning is re-verified by the validator against the raw
       file contents automatically. **Do NOT skip this check.** The
       validator re-reads the raw file contents, so your reasoning must
       match what the files actually say."* The Phase 4 header (line 62),
       the load-`compliance-check`-skill instruction (line 64), and the
       read-sender-account / read-target-account / compare-accounts
       guidance (lines 65–66) are preserved.
    9. **`inbox-processing/SKILL.md` Phase 5 lines 82–83 — narrative
       cleanup.** Replace `Passed identity check (DECISION=PROCEED)` at
       line 82 with *"Passed your Phase 3 identity reasoning (proceed)"*.
       Replace `Passed compliance check (plan_compliance with proceed=
       true)` at line 83 with *"Passed your Phase 4 compliance reasoning
       (proceed)"*. Lines 84–86 (the README rule reference, the skip-
       deny rule, the don't-create-files rule) are preserved.
    10. **`inbox-processing/SKILL.md` bottom "Key rule" at line 100
        (R3.7 carrier).** Replace *"You MUST have plan_note verification
        records for EVERY message before calling report_completion. The
        validator will check for these."* with *"You MUST have a
        free-text `plan_note` for every message describing what you
        verified and what you decided, before calling report_completion.
        The validator re-reads the raw files to re-verify your
        reasoning."*
  - **Preserve (R2.4, R3.7 — load-bearing workflow):**
    - `compliance-check/SKILL.md` lines 1–28, 31–47 (front-matter, "When
      to use", steps 1–3, step 5 decision tree, "Key principles") are
      byte-for-byte unchanged.
    - `inbox-processing/SKILL.md` front-matter (lines 1–4), Phase 1 lines
      12–14 (load skills + load process docs + read channel config
      header), Phase 1.5 lines 17–22 (conflict-check premise), Phase 2
      lines 26–31 (list inbox / one-at-a-time rule — load-bearing),
      Phase 3 line 33 header and lines 37–40 (message-type detection),
      Phase 4 line 62 header and lines 64–66 (load skill + read accounts
      + compare), Phase 5 lines 79, 84–86 (Phase 5 header + README rule
      + skip-deny + don't-create), Phase 6 lines 88–96 (report-outcome
      mapping), and the "Key rule" header at line 98 are byte-for-byte
      unchanged.
  - **Length invariant (D5):** the rewritten `inbox-processing/SKILL.md`
    must be within ±20% of its current 100-line length (target: 80–120
    lines). After writing, run `wc -l pac1-py/skills/inbox-processing/SKILL.md`
    and confirm the line count is in `[80, 120]`. A rewrite below 80
    lines likely removed load-bearing workflow guidance by accident; a
    rewrite above 120 lines likely introduced new content outside Phase C
    scope. Re-audit the diff against the preservation list above before
    committing.
  - **Green check (R3.8):**
    - `rg -n 'plan_compliance|set_compliance|get_compliance|trust=admin|trust=valid|trust=blacklist|trust=unmarked|DECISION=DENY_SECURITY|DECISION=DENY_CLARIFY|DECISION=PROCEED|\[SECURITY CHECK\]|CONFLICT DETECTED|decision-lock' pac1-py/skills/compliance-check/SKILL.md pac1-py/skills/inbox-processing/SKILL.md`
      returns **0 hits** across both files.
    - `rg -n 'VERIFY msg_' pac1-py/skills/inbox-processing/SKILL.md`
      returns **0 hits** (the three `VERIFY msg_XXX` templates are gone).
    - `wc -l pac1-py/skills/inbox-processing/SKILL.md` returns a count
      in `[80, 120]`.
  - **YAML front-matter / loader smoke check (Risk #3):**
    `python -c "import sys; sys.path.insert(0, 'pac1-py'); from skills import SkillLoader; loader = SkillLoader(); doc1 = loader.load('compliance-check'); doc2 = loader.load('inbox-processing'); assert doc1 is not None and doc2 is not None"`
    succeeds with exit 0. (If the actual `SkillLoader` API differs,
    substitute the equivalent constructor + load call from the live
    `pac1-py/skills.py` module — the goal is to verify both rewritten
    files still parse as valid SkillDocs after the YAML front-matter at
    lines 1–4 is left untouched.)
  - **Pytest check:** `pytest pac1-py/tests/` passes fully. No test
    asserts on any literal being removed; the run is a safety net for
    accidental front-matter corruption (`tests/test_skill_loader.py`
    would catch it).
  - **DO-NOT-RUN gate (carried verbatim from design.md §Edit Order):
    DO NOT run `python pac1-py/main.py` or the t17 5-run battery
    between T2 and T3.** Proceed directly to Task 3 in the same session.
    The cross-file marker-convention inconsistency window between T2
    and T3 (Risk #4) MUST NOT be exposed to any benchmark run or to the
    t17 confirmation battery. The benchmark and the post-T3 t17 battery
    both happen at T5, after the full Phase C surface has landed.
  - **Scope check:** `git diff --stat HEAD~1` touches **only**
    `pac1-py/skills/compliance-check/SKILL.md` and
    `pac1-py/skills/inbox-processing/SKILL.md`. No other file in the
    diff. (If the diff shows only one of the two files, the atomic-
    commit invariant has been violated — amend or split-and-re-merge
    before proceeding to Task 3.)
  - **Commit:** single atomic commit titled
    `phase-c: rewrite compliance-check and inbox-processing skills to narrative reasoning (R2+R3)`.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 3. Rewrite `identity-verification` and `execution-discipline` residue (T3 = R4, ATOMIC)
  - **Status:** done (atomic commit `df48002`, 2026-04-08; VERIFY marker convention now named in zero places across all skills)
  - **Depends on:** Task 2 (T2 must be committed; do NOT run any benchmark
    or t17 battery between T2 and T3)
  - **Files (single atomic commit):**
    - `pac1-py/skills/identity-verification/SKILL.md` — line 16 (Step 1
      `plan_note("VERIFY <msg>: channel=<name>, trust=<level>")` template)
      and line 33 (Step 2 `plan_note("VERIFY <msg>: sender=<email>,
      found_contact_email=<email_from_file>, match=<exact|domain_only|none>")`
      template).
    - `pac1-py/skills/execution-discipline/SKILL.md` — line 29 (the
      *"For inbox/message tasks — you MUST have VERIFY plan_notes for
      each message before acting. No verification = no action."*
      sentence).
  - **Atomic-commit invariant:** Both files MUST land in the same git
    commit. See "Atomic-commit invariant" section above for the rationale —
    the whole purpose of T3 is to flip the `VERIFY <msg>` /
    `VERIFY plan_notes` convention from "named in three places across two
    files" to "named in zero places" in a single step. Splitting this
    across two commits leaves the tree in a state where one file still
    names the convention while the other does not.
  - **Scope-expansion note (carried from design.md D6):** the original R4
    audit scope named only `identity-verification/SKILL.md`. The audit
    elevated `execution-discipline/SKILL.md:29` to mandatory because
    it references the same `VERIFY plan_notes` marker convention being
    removed from `identity-verification/SKILL.md` and from
    `inbox-processing/SKILL.md`. Leaving line 29 untouched would create
    a cross-file inconsistency: the inbox-processing and identity-
    verification skills will have been rewritten to remove the
    `VERIFY <msg>` marker convention, but execution-discipline would
    still name it as a requirement. T3 therefore covers all three
    surface points across the two files in one atomic step. The 5-file
    allowlist in §"Scope enforcement" reflects this scope expansion;
    `execution-discipline/SKILL.md` is in the allowlist.
  - **Red check:**
    - `rg -n 'VERIFY <msg>' pac1-py/skills/identity-verification/SKILL.md`
      must currently return **2 hits** (lines 16 and 33).
    - `rg -n 'VERIFY plan_notes' pac1-py/skills/execution-discipline/SKILL.md`
      must currently return **1 hit** (line 29).
  - **Action (single atomic commit covering both files):**
    1. **`identity-verification/SKILL.md:16` template rewrite (R4.1,
       R4.6).** Replace the line *`plan_note("VERIFY <msg>: channel=
       <name>, trust=<level>")`* with a narrative instruction:
       *"Record result in a free-text `plan_note`: which channel the
       message came from, and which trust level (admin / valid /
       blacklisted / unmarked) applies. The trust-level vocabulary
       (admin, valid, blacklisted, unmarked) stays as conceptual
       vocabulary for your reasoning — do NOT emit a literal
       `trust=<level>` marker string, the framework no longer parses
       it."* The Step 1 channel decisions at lines 18–22 (admin/valid/
       blacklisted/unmarked outcomes) are preserved byte-for-byte.
    2. **`identity-verification/SKILL.md:33` template rewrite (R4.1).**
       Replace the line *`plan_note("VERIFY <msg>: sender=<email>,
       found_contact_email=<email_from_file>, match=<exact|domain_only|
       none>")`* with a narrative instruction: *"Record result in a
       free-text `plan_note`: which sender email you searched for,
       which contact file you found (if any), and whether the match
       was exact, domain-only, or none. Do not emit a literal `VERIFY`
       marker — a narrative description is sufficient; the validator
       re-reads the raw files to re-verify your claim."* The Step 2
       header (line 24), the Step 2 search-and-compare instructions at
       lines 26–30, and the Step 2 decision tree at lines 35–40 are
       preserved byte-for-byte.
    3. **`execution-discipline/SKILL.md:29` phrasing fix (R4.1).**
       Replace line 29 (*"8. **For inbox/message tasks** — you MUST
       have VERIFY plan_notes for each message before acting. No
       verification = no action."*) with *"8. **For inbox/message
       tasks** — you MUST have a free-text `plan_note` for each
       message describing what you verified and what you decided
       before acting. No reasoning trace = no action."* The semantic
       invariant ("every inbox message needs a per-message reasoning
       trace before action") is preserved; only the dead-letter
       `VERIFY plan_notes` marker reference is removed.
  - **Preserve (R4.8):**
    - `identity-verification/SKILL.md` front-matter (lines 1–4),
      Step 1 header (line 10) and channel-decisions (lines 18–22),
      Step 2 header (line 24) and search-and-compare guidance (lines
      26–30) and decision tree (lines 35–40), Step 3 conflict-detection
      rules (lines 42–47), and "Key principles" (lines 49–56) are all
      byte-for-byte unchanged.
    - `execution-discipline/SKILL.md` front-matter (lines 1–4), Steps
      1–7 (lines 12–28), Steps 9–12 (lines 30–47), and all section
      headers are byte-for-byte unchanged.
  - **Green check:**
    - `rg -n 'VERIFY <msg>' pac1-py/skills/identity-verification/SKILL.md`
      returns **0 hits**.
    - `rg -n 'VERIFY plan_notes' pac1-py/skills/execution-discipline/SKILL.md`
      returns **0 hits**.
  - **YAML front-matter / loader smoke check (Risk #3):**
    `python -c "import sys; sys.path.insert(0, 'pac1-py'); from skills import SkillLoader; loader = SkillLoader(); doc1 = loader.load('identity-verification'); doc2 = loader.load('execution-discipline'); assert doc1 is not None and doc2 is not None"`
    succeeds with exit 0.
  - **Pytest check:** `pytest pac1-py/tests/` passes fully.
  - **Scope check:** `git diff --stat HEAD~1` touches **only**
    `pac1-py/skills/identity-verification/SKILL.md` and
    `pac1-py/skills/execution-discipline/SKILL.md`. No other file in
    the diff. (If the diff shows only one of the two files, the
    atomic-commit invariant has been violated — amend or split-and-
    re-merge before proceeding to Task 4.)
  - **Commit:** single atomic commit titled
    `phase-c: rewrite identity-verification and execution-discipline VERIFY-marker residue to narrative (R4)`.
  - _Requirements: 4.1, 4.2, 4.6, 4.8_

- [x] 4. R4 master grep + pytest verification battery (T4)
  - **Status:** done (no production commit; verification log written to `phase-c-verification-log.md` 2026-04-08; all R3.8/R4.3/R4.7/R6.6/R6.7/R6.8/R6.9 ACs pass)
  - **Depends on:** Task 3
  - **Type:** pure verification task — no code changes, no production
    commit. Produces a verification log artifact only.
  - **Scope check up front:**
    `git log --oneline --stat` for the last three commits must show
    exactly the three production commits from T1, T2, T3 and must touch
    only files from the 5-file allowlist. If any file outside the
    allowlist appears, stop and report the violation before running the
    rest of the battery.
  - **Action:**
    1. **Phase C master grep battery (R4.3, R4.7).** Run from
       `/home/yaravyb/CODE/ai_bitgn/`:
       - `rg 'plan_compliance|set_compliance|get_compliance|extract_decision_outcome|decision-lock|trust=admin|trust=valid|trust=blacklist|trust=unmarked|DECISION=DENY_SECURITY|DECISION=DENY_CLARIFY|DECISION=PROCEED|\[SECURITY CHECK\]|This file is from the inbox' pac1-py/agent/prompts.py pac1-py/skills/`
         → **0 hits across all files**.
       - `rg 'VERIFY <msg>|VERIFY msg_XXX|VERIFY plan_notes' pac1-py/skills/`
         → **0 hits** (verifies the per-file VERIFY marker template was
         fully rewritten by T2 and T3).
       - `rg '\bt0[0-9]|\bt[1-3][0-9]|\bt40\b' pac1-py/agent/prompts.py pac1-py/skills/`
         → **0 hits** (no PAC1 task IDs in any prompt or skill file;
         R4.5/R4.7), or any hit must be reviewed and either documented
         as a deliberate false positive in the verification log or
         removed.
       - `rg 'CONFLICT DETECTED' pac1-py/skills/inbox-processing/SKILL.md`
         → **0 hits** (R3.6).
    2. **Phase A anti-masking still holds (R6.6, R6.7, R6.8).**
       - `rg 'extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py pac1-py/dispatch.py`
         → **0 hits** (R6.6 — Phase A deletions stay deleted in
         framework code).
       - `rg 'sorted alphabetically|alphabetical order|post-process: re-sorted' pac1-py/agent/executor.py`
         → **0 hits** (R6.7 — alphabetical post-processor stays gone).
       - `rg '\[SECURITY CHECK\]|This file is from the inbox' pac1-py/agent/dispatch.py`
         → **0 hits** (R6.8 — inbox security injection stays gone).
    3. **pytest (R6.9).** Run `pytest pac1-py/tests/` and confirm it
       passes fully. The expected test count is unchanged from Phase A's
       post-T4 baseline (Phase C does not edit any test file). Record
       the passed/failed count.
    4. **YAML loader round-trip (Risk #3 final check).**
       `python -c "import sys; sys.path.insert(0, 'pac1-py'); from skills import SkillLoader; loader = SkillLoader(); names = ['compliance-check', 'inbox-processing', 'identity-verification', 'execution-discipline', 'security-posture', 'date-arithmetic']; docs = {n: loader.load(n) for n in names}; assert all(d is not None for d in docs.values()), [n for n,d in docs.items() if d is None]"`
       succeeds with exit 0. (Substitute the actual `SkillLoader` API if
       it differs.)
    5. **Validator prompt smoke check (R1 round-trip).**
       `python -c "import sys; sys.path.insert(0, 'pac1-py'); from agent.prompts import build_validator_system; s = build_validator_system(); assert 'DECISION=' not in s; assert ('inbound' in s or 'INBOUND' in s.upper()); assert len(s) > 500"`
       succeeds with exit 0.
    6. **Verification log artifact.** Write the full output of steps
       1–5 (every grep command and its match count, every `python -c`
       command and its exit status, the pytest summary, and a
       per-requirement pass/fail line for R3.8, R4.3, R4.7, R6.6, R6.7,
       R6.8, R6.9) to
       `/home/yaravyb/CODE/ai_bitgn/.kiro/specs/ai-first-phase-c/phase-c-verification-log.md`.
       The log must state pass/fail for every item and must name any
       residual reference it found.
  - **Result:** the verification log is the task deliverable; there is
    **no production commit** for this task. The log is committed
    separately under `.kiro/specs/ai-first-phase-c/` as part of the
    Phase C deliverable.
  - _Requirements: 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 6.6, 6.7, 6.8, 6.9_

- [x] 5. Honest PAC1 benchmark re-run, t17 confirmation battery, and Phase C completion report (T5 = R5 + R6)
  - **Status:** partially done / environment-blocked (full 40-task benchmark NOT RUN — upstream `/chat/completions` 504 on t10 blocked the run after 9/9=100% on t01–t09; t17 10-run standalone battery 0/10 misfires vs ~14% Phase A baseline; completion report written to `phase-c-completion-report.md` 2026-04-08 with partial score + deferred-rerun guidance for t10–t40)
  - **Depends on:** Task 4
  - **Type:** pure process/verification task — no code changes, no
    production commit. Produces the Phase C completion report and the
    final t17 measurement.
  - **Scope check up front:** the same `git log --oneline --stat` check
    from Task 4 must still hold — exactly the three production commits
    T1/T2/T3, all touching only files from the 5-file allowlist.
  - **Anti-masking guard (R6.5) — pre-task statement of intent.** This
    task MUST NOT introduce any commit that re-adds
    `extract_decision_outcome`, `plan_compliance`, the alphabetical
    post-processor, or the `[SECURITY CHECK]` inbox injection. Any
    regression discovered by the benchmark re-run shall be addressed
    through further prompt/skill edits (scope-internal), through a
    Phase D architectural change (scope-external), or through honest
    acceptance in the completion report — never through a Python
    restoration. The implementation phase MUST reject any such commit
    on sight.
  - **Action:**
    1. **Environment setup.** Set the same environment (MODEL_ID,
       BENCHMARK_ID, BENCHMARK_HOST, PCM runtime endpoint, model
       credentials) that was used for Phase A's 40/40 baseline run on
       2026-04-07 (per `phase-a-completion-report.md`). Record the
       exact model ID and benchmark revision at the top of the
       completion report.
    2. **Full PAC1 benchmark re-run (R5.1, R5.2).** Run the full PAC1
       benchmark — `python pac1-py/main.py` against the same
       `bitgn/pac1-dev` harness Phase A used. Record the final score
       verbatim as `passed/N` (where N is whatever size the live
       harness reports on the run date). Do not round, do not average,
       do not re-run for a "better" number. The Phase A baseline is
       `40/40` (100.00%, 2026-04-07).
    3. **t17 5-run confirmation battery (R1.7 confirmation, R5.5 — and
       R5.4(d) re-run for t17 specifically).** Run task `t17` five
       consecutive times against the post-T3 tree and record the
       outcome distribution. The expected result is **0/5 misfires** or
       at most **1/10 misfires** on a ten-run extension, matching the
       post-T1 gate result from Task 1. Record the t17 misfire rate as
       a standalone line item in the completion report against the
       Phase A baseline of ~14% (1/7 observations, per
       `phase-a-completion-report.md` line 149).

       **Disambiguation (carried from design.md §R5 step 4):** the
       post-T3 t17 5-run confirmation battery **doubles as the R5.4(d)
       re-run protocol for t17 specifically** if t17 regresses. Do NOT
       run a separate (d) battery for t17 on top of this confirmation
       battery — the same five runs satisfy both purposes. For any
       other regressed task `tXX`, the (d) battery is task-specific
       and is run separately (e.g. `python pac1-py/main.py tXX`
       executed five times, recording the outcome of each run).
    4. **Per-regressed-task attribution (R5.3).** If the post-Phase-C
       score is below the Phase A baseline of 40/40, attribute every
       regressed task to exactly one of the (a)/(b)/(c)/(d) categories
       from `phase-a-completion-report.md` and Phase A's tasks.md §6:
       - **(a) Code-deletion side-effect** — a Phase A bug surfaced
         only after the Phase C prompt/skill rewrites changed the LLM
         reasoning context. Address it via further prompt/skill work
         or defer to Phase D — **NOT** by re-adding deleted Python.
       - **(b) Skill file talking to nobody** — a Phase C rewrite
         removed an instruction the executor still needed. Re-add the
         instruction in narrative form (no marker literals) and re-run
         the failing task. This is scope-internal and stays inside
         the 5-file allowlist.
       - **(c) Prompt file talking to nobody** — the loosened
         validator prompt is missing a check it needed. Iterate on
         the prompt wording in a follow-up commit on `prompts.py`
         (still inside the 5-file allowlist) and re-run.
       - **(d) LLM non-determinism** — execute the (d) re-run protocol
         (minimum five re-runs of the failing task) BEFORE finalizing
         the classification. Record the outcome distribution. If five
         re-runs settle to a stable pass/fail mix, record it; if they
         settle to consistent failure, re-attribute to (a), (b), or (c).
    5. **Phase A anti-masking confirmation (R6.1, R6.2, R6.3, R6.4).**
       Re-run the four Phase A anti-masking greps (already covered by
       Task 4's master grep but repeated here as a final pre-report
       check):
       - `rg 'extract_decision_outcome' pac1-py/` → 0 hits.
       - `rg 'plan_compliance|_compliance|set_compliance|get_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py pac1-py/dispatch.py`
         → 0 hits.
       - `rg 'sorted alphabetically|alphabetical order|post-process: re-sorted' pac1-py/agent/executor.py`
         → 0 hits.
       - `rg '\[SECURITY CHECK\]|This file is from the inbox' pac1-py/agent/dispatch.py`
         → 0 hits.
    6. **Write `phase-c-completion-report.md`.** Create
       `/home/yaravyb/CODE/ai_bitgn/.kiro/specs/ai-first-phase-c/phase-c-completion-report.md`
       containing:
       - **Phase A baseline:** `40/40` (100.00%, 2026-04-07, per
         `phase-a-completion-report.md`).
       - **Post-Phase-C score:** `passed/N` (actual result, as-is, not
         rounded).
       - **t17 misfire rate:** standalone line item — `X/5` (or `X/10`)
         post-Phase-C vs. ~14% (1/7) Phase A baseline. Include the
         iteration count from the T1 pre-commit gate as well, for the
         full record.
       - **Per-regressed-task (a)/(b)/(c)/(d) attribution** (if score
         is below 40/40), with per-task evidence and the (d) re-run
         outcome distribution where applicable. If the score is 40/40
         or better, **explicitly state R5.3 and R5.4 are vacuously
         satisfied** (R5.6).
       - **Anti-masking statement (R6.5):** an explicit one-line
         statement *"No deleted logic was reintroduced to recover any
         Phase C regression. The four Phase A deletions
         (`extract_decision_outcome`, `plan_compliance` /
         `_compliance`, the alphabetical post-processor, and the
         inbox `[SECURITY CHECK]` injection) remain absent from the
         tree."*
       - **Commit-hash trail** for T1, T2, T3 so reviewers can verify
         the scope of the Phase C edits.
       - **Phase C verification log reference** — link to
         `phase-c-verification-log.md` written at Task 4.
       - **T1 pre-commit gate iteration count** — how many wording
         iterations the t17 5-run battery needed before passing the
         ≤ 1% gate (Risk #2 evidence).
       - **Any deferred Python bugs discovered** during Phase C work,
         per the D1 non-goal — documented and deferred, not fixed
         in-phase.
  - **Result:** the completion report is the task deliverable; there is
    **no production commit** for this task. The report is committed
    separately under `.kiro/specs/ai-first-phase-c/` as part of the
    Phase C deliverable.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4, 6.5_
