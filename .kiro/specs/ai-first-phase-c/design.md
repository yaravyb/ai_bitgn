# Phase C Design — Prompt and Skill Cleanup Plan for pac1-py

## Overview

Phase C is **prompt and skill text cleanup — no Python is touched**. Phase A's
four surgical Python deletions (commits `0e3bf76`, `a35bed2`, `29e5e78`,
`c236dd9`) removed the framework-level machinery that consumed `trust=`,
`DECISION=`, `CONFLICT`, and `plan_compliance(...)` markers, but — by explicit
D1/D3 scope discipline — left every prompt builder in `pac1-py/agent/prompts.py`
and every `pac1-py/skills/**/SKILL.md` file byte-for-byte untouched. That
discipline did its job: the full 40-task PAC1 benchmark scored **40/40 =
100.00%** post-Phase-A (`phase-a-completion-report.md`, 2026-04-07), empirically
confirming that the four deleted pieces of logic were load-bearing for **0 of
40 tasks**. What Phase A left behind is *prompt rot*: instructions to the LLM
to emit or look for markers that no Python code reads or writes anymore. Phase
C deletes that rot. The change modality is a grep-driven red/green cycle
identical to Phase A's: a red check is an `rg` hit for a dead-letter literal,
the fix is a text rewrite inside the same file, the green check is `rg`
returning zero hits. Phase C preserves the pipeline, preserves the module
boundaries, preserves every Python symbol, and preserves the 40/40 benchmark
baseline as its empirical success bar.

### Goals
- Loosen `build_validator_system` in `pac1-py/agent/prompts.py` so that (a) the
  dead `DECISION=` marker instructions are removed, and (b) the cross-account
  check is re-scoped to inbound-message tasks only, driving the t17-class
  validator misfire rate from ~14% (1/7 observations, `phase-a-completion-report.md`)
  to ≤ 1% on a fresh 5+ run battery (R1).
- Rewrite `pac1-py/skills/compliance-check/SKILL.md` so the executor is no
  longer instructed to call the deleted `plan_compliance(...)` tool (R2).
- Structurally rewrite `pac1-py/skills/inbox-processing/SKILL.md` so the
  load-bearing inbox workflow (list → read in order → evaluate trust → act or
  refuse) survives while every dead-letter marker literal (`trust=`,
  `DECISION=`, `CONFLICT DETECTED`, `plan_compliance`, `decision-lock`) is
  removed (R3).
- Audit every remaining skill file and every other prompt builder for residual
  dead-letter references and rewrite any hit in the same Phase C pass (R4).
- Re-run the full PAC1 benchmark honestly and record the result alongside the
  Phase A baseline; any regression must be addressed through further prompt
  work or deferred to Phase D, never by re-adding Phase A deleted logic (R5).
- Carry forward the Phase A anti-masking guard verbatim (R6).

### Non-Goals (explicitly deferred)
- **D1 — No Python code changes.** Phase C does not edit any file under
  `pac1-py/agent/*.py`, `pac1-py/tasks.py`, `pac1-py/tools.py`,
  `pac1-py/dispatch.py`, or `pac1-py/main.py`. If a Python bug is discovered
  while writing or verifying the prompt/skill edits, the implementation phase
  shall document it in the Phase C completion report and defer it to a fix
  commit on main (for trivial bugs) or to Phase D (for architectural issues).
  The benchmark re-run and the t17 battery are interpreted against the exact
  Python tree produced by Phase A's T4 commit (`c236dd9`).
- **D2 — No test file edits.** Phase C does not touch any file under
  `pac1-py/tests/`. The test suite must remain green after Phase C (R6.9), but
  the green run is achieved by the fact that no test asserts on any of the
  dead-letter literals Phase C is removing — the three Phase A test deletions
  already cleared the test-side fallout. Phase C verifies this by running
  `pytest pac1-py/tests/` as one of its smoke checks, not by editing tests.
- **D3 — No architectural changes.** The Bootstrap → Planner → Executor →
  Validator → Apply → Submit pipeline is preserved byte-for-byte. Module
  boundaries, class contracts, tool composition (`EXECUTOR_TOOLS`), outcome
  enum strings, and the validator's `<source-files>` independent-verification
  block (`validator.py:32–45`, added in commit `0818d07`) all remain
  untouched. Phase C is text-file editing inside files the Python pipeline
  already loads.
- **D4 — No new tool authorship.** The rewritten `compliance-check/SKILL.md`
  and `inbox-processing/SKILL.md` shall not introduce any new tool name that
  does not already exist in `pac1-py/tools.py` as of the Phase C commit.
  Phase C is subtraction and rewriting, not net-new functionality. The only
  tool names the rewritten skills may reference are those already exported by
  `EXECUTOR_TOOLS` (verified per R2.5 by `rg 'name.*plan_note' pac1-py/tools.py`
  returning at least one hit — confirmed at `tools.py:429`).
- **JSON-only cross-reference grounding** — Phase B, feature rework,
  architecturally independent.
- **Outcome-protocol isolation** — Phase D, architectural refactor of outcome
  codes.
- **t30 performance investigation** — Phase B/C follow-up per
  `phase-a-completion-report.md`, not a Phase C deliverable.

## Architecture (preserved)

Phase C does not change module boundaries, class contracts, tool composition,
or pipeline ordering. Everything listed in this section **stays**:

### Pipeline shape
```mermaid
graph LR
    Bootstrap --> Planner
    Planner --> Executor
    Executor --> Validator
    Validator --> Apply
    Apply --> CrossRef
    CrossRef --> Submit
```

All six stages remain in their current files:
`agent/bootstrap.py` → `agent/planner.py` → `agent/executor.py::_run_executor`
→ `agent/validator.py::validate_completion` → deferred-write apply loop in
`agent/executor.py` → `_follow_cross_references` → `vm.answer`.

### State and constants preserved verbatim
- `build_executor_system` and `build_planner_system` in
  `pac1-py/agent/prompts.py` are **not edited** — the R4 audit confirmed they
  contain zero hits for the dead-letter literal set (`rg` verified against the
  current file, 2026-04-07). Their bodies remain byte-for-byte identical.
  Only `build_validator_system` is edited in R1.
- The validator's `raw_files_section` independent-verification block at
  `validator.py:32–45` is preserved verbatim. This is the block added in
  commit `0818d07` that re-reads raw files the executor touched and injects
  them into the validator's system context as `<source-files>`. R1's
  design explicitly leans on this block for correctness: the re-scoped
  cross-account check in the cleaned validator prompt operates against the
  same raw-file evidence the validator already sees, so no validator
  correctness depends on a structured `plan_note` tag being present. This
  is the architectural reason D2 below resolves R2 toward narrative
  reasoning rather than a structured `plan_note("COMPLIANCE: ...")` tag.
- Every `plan_*` tool schema in `pac1-py/tools.py` stays — `plan_note`
  (`tools.py:429`), `plan_create`, `plan_update`, `plan_add`,
  `plan_add_dependency`, `plan_add_instruction`, `plan_status` — and every
  handler entry in `pac1-py/agent/dispatch.py` stays. Phase C does not
  remove or add any tool.
- Every outcome enum literal (`OUTCOME_OK`, `OUTCOME_DENIED_SECURITY`,
  `OUTCOME_NONE_CLARIFICATION`, `OUTCOME_NONE_UNSUPPORTED`,
  `OUTCOME_ERR_INTERNAL`) stays in the prompt bodies and in `tools.py`.
- The `SkillLoader` in `pac1-py/skills.py` is untouched. Skill files are
  loaded by path at runtime; rewriting their body does not change the
  loader's behavior and does not change any Python line in the project.
- The three non-touched skill files (`security-posture/SKILL.md`,
  `date-arithmetic/SKILL.md`, `execution-discipline/SKILL.md`) are
  audited-clean per R4 (grep-verified zero hits on the dead-letter literal
  set) and remain byte-for-byte identical — except for one 1-line
  clarification in `execution-discipline/SKILL.md:29` that references the
  `VERIFY plan_notes` convention which R3 is removing (see §Implementation
  Design, R4 subsection).

## Design decisions (binding inputs for implementation)

The Phase C design surfaced six decisions that needed explicit resolution
before the implementation phase can run mechanically. Each is locked here
with its rationale and its impact on the requirement ACs.

### D1. Inbound-vs-outbound task detection in the validator prompt (R1.4)

**Decision:** Use a **hybrid verb-list + explicit phase-of-task gate**
inside the rewritten `build_validator_system`. The cleaned `<checks>` block
shall (a) define the cross-account check as "if and only if the original task
instructs the agent to process an inbound message" and (b) give the validator
LLM an indicator-verb list so it can classify the task in a single reading
pass without relying on path heuristics alone.

Concretely, the rewritten `<checks>` bullet 2 shall contain a sub-clause
roughly of the form:

> "Cross-account check (applies **only** to inbound-message tasks — i.e.
> tasks that instruct the agent to **process**, **reply to**, **handle**,
> **respond to**, **verify**, or **evaluate** an already-received message
> from `inbox/` or from a channel. It does **not** apply to outbound-action
> tasks — i.e. tasks that instruct the agent to **email**, **send**,
> **remind**, **compose**, **notify**, **write to `outbox/`**, or
> **create** a new message for a recipient. If the task is outbound, skip
> this check entirely; the user is the originator and there is no `sender`
> for the check to reason about.) When the task IS inbound and the message
> body requests data about a different company than the sender's own
> account, the validator shall escalate the outcome to
> `OUTCOME_NONE_CLARIFICATION` (cross-account block)."

- **Rationale for hybrid (verb list + explicit phase-of-task instruction)
  over pure path-based heuristic:** the t17 diagnostic case study
  (`phase-a-completion-report.md`) shows the failure mode: t17's task text
  is *"Email reminder to Barth Florian at Nordlicht Health ..."* — there is
  no `inbox/` path anywhere in the task text. A pure path heuristic would
  give the validator LLM no signal at all. The indicator-verb list gives
  the LLM a fast lexical signal ("email reminder" contains *email* →
  outbound → skip check), and the explicit phase-of-task instruction gives
  it a semantic backstop for edge cases.
- **Edge-case handling (forwarding, read-only lookups):** a task like
  *"forward the message from `inbox/msg_001.json` to contact Y"* is both
  inbound (processes an inbox message) and outbound (creates a new outbox
  file). The design instructs the validator to treat any task that
  contains an inbound verb as inbound for the purpose of the cross-account
  check, on the principle that the inbound half of the task is where a
  cross-account leak can occur. A task like *"read the contact's email
  from `contacts/X.json`"* is neither inbound nor outbound (it's a pure
  lookup) and the cross-account check does not apply — the outbound verb
  list contains *email*, *send*, *remind*, *compose*, *notify*, *write*,
  *create*; the inbound verb list contains *process*, *reply*, *handle*,
  *respond*, *verify*, *evaluate*; the lookup task matches neither, so
  the validator LLM falls through to the other checks (email match,
  security flags) without running the cross-account check.
- **Robustness claim:** the t17 misfire rate target (≤ 1% on a 5+ run
  battery) is achievable because the indicator-verb signal ("email
  reminder ...") is extracted from the task text directly and does not
  depend on the LLM's multi-hop reasoning about sender identity — which is
  where the ~14% stochastic failures came from. The instruction pattern
  also mirrors the pattern used by `build_planner_system`'s
  `<rejection-checks>` block (`prompts.py:136–147`), which is already
  known to be robust in the 40/40 benchmark run, so the validator LLM is
  being asked to do something it already does well elsewhere in its
  prompt diet.
- **ACs satisfied:** R1.4 (cross-account check gated on inbound only),
  R1.5 (inbound-task protection preserved), R1.7 (≤ 1% misfire rate on
  the 5+ run battery — empirically verified before committing).

### D2. Compliance recording — structured `plan_note` tag vs. narrative reasoning (R2.3)

**Decision:** Use **pure narrative reasoning** for the compliance
recording in the rewritten `compliance-check/SKILL.md`. The rewritten step 4
shall instruct the executor to reason through the cross-account decision
out loud in its chain-of-thought (or in a free-text `plan_note` that
describes the reasoning rather than tagging it as `COMPLIANCE:...`), and
shall NOT instruct the executor to emit a structured
`plan_note("COMPLIANCE: account_id=..., cross_account=true|false,
flags=..., proceed=true|false, reason=...")` tag.

- **Rationale — the validator already re-reads raw files.** Commit
  `0818d07` (`fix: validator independently verifies executor's claims
  against raw files`) added the `raw_files_section` block at
  `validator.py:32–45` that injects the content of every file the executor
  touched into the validator's system context as `<source-files>`. The
  validator LLM re-reads the sender's account record, the target account
  record (if different), and the message body from the raw file evidence,
  independently of whatever the executor wrote in its `plan_note`. A
  structured `plan_note("COMPLIANCE: ...")` tag would therefore add a
  second, redundant signal path for the validator to parse — and redundant
  signal paths are exactly the failure mode Phase A was surgically cleaning
  up (see R1's history: the original `DECISION=` markers were parsed by
  both `extract_decision_outcome` *and* the validator LLM's text reasoning,
  and the double path made the framework behavior harder to reason about).
- **Rationale — narrative reasoning is more auditable in traces, not less.**
  A `plan_note("COMPLIANCE: account_id=acct_042, cross_account=false,
  flags=[], proceed=true, reason=sender is internal Account Manager for
  target company")` tag and a free-text `plan_note("Checked compliance:
  sender acct_042 is the internal Account Manager for the target company;
  no cross-account concern; no restrictive flags on the account record;
  proceeding.")` both render in the executor's `plan render` output. The
  free-text note is **more** readable in the CLI trace, not less, because
  it reads as English prose and a human reviewer does not need to mentally
  parse the `=` / `,` / `[...]` syntax. The structured tag's only advantage
  would be machine-parseability, and no Python machinery parses it — the
  validator LLM reads it as text either way.
- **Rationale — symmetric with R1 prompt cleanup.** R1 is removing the
  `DECISION=` marker instructions from the validator prompt because no
  Python code parses them and the validator LLM reasons from raw file
  content anyway. Using a structured `COMPLIANCE:` marker in R2 would
  replace one dead-letter machine-readable tag with another dead-letter
  machine-readable tag, undoing the simplification Phase C is the home for.
- **Impact on R2 ACs:** R2.3 is satisfied by the narrative branch. The
  rewritten step 4 reads, in plain prose, *"Record your cross-account
  decision in a free-text `plan_note` describing what you checked, what
  you found, and whether to proceed. Do not invent a structured tag — the
  note is for the reviewer and for your own chain-of-thought, not for a
  parser."* R2.4 (preserve the key rules: read linked account, STOP on
  cross-account, operational flags are soft, cross-account is the only
  hard block) is preserved verbatim — those rules survive the step 4
  rewrite because they live in steps 1, 3, and 5 of the skill, which
  Phase C does not touch.
- **ACs satisfied:** R2.1 (no `plan_compliance` literal), R2.2 (no
  `set_compliance` / `get_compliance` literal), R2.3 (narrative branch
  chosen), R2.4 (key rules preserved), R2.5 (no dangling new tool name),
  R2.6 (no new tool authored).

### D3. Commit atomicity — three production commits (R6 smoke-check alignment)

**Decision:** Phase C lands as **three production commits** plus one
spec-deliverables commit, mirroring Phase A's T1→T2→T3→T4→T5 shape but
compressed to three production commits because Phase C has one fewer
requirement with a structural edit target:

| Tag | Requirement(s) | Files edited | Scope |
|---|---|---|---|
| **T1** | R1 | `pac1-py/agent/prompts.py` | Loosen `build_validator_system`: delete `<checks>` bullet 3 (the `DECISION=` block); rewrite `<checks>` bullet 2 cross-account sub-clause to gate on inbound-only. |
| **T2** | R2 + R3 | `pac1-py/skills/compliance-check/SKILL.md`, `pac1-py/skills/inbox-processing/SKILL.md` | Rewrite the two skills together so the `compliance-check` narrative branch and the `inbox-processing` Phase 4 block land in the same commit and stay mutually consistent. Both files go from dead-letter-heavy to narrative-reasoning-only in one atomic step. |
| **T3** | R4 | `pac1-py/skills/identity-verification/SKILL.md`, `pac1-py/skills/execution-discipline/SKILL.md` | Residual audit: rewrite the `trust=<level>` literal template in `identity-verification/SKILL.md:16` to narrative, and rewrite the vestigial `VERIFY plan_notes` reference in `execution-discipline/SKILL.md:29` to match the new narrative pattern from T2. No other skill file is touched (confirmed clean by the audit grep). |

- **Rationale for bundling R2+R3 into T2:** the `compliance-check` and
  `inbox-processing` skills are tightly coupled — Phase 4 of
  `inbox-processing` explicitly references the `compliance-check` skill
  (line 64: *"For messages marked PROCEED, load `compliance-check`
  skill"*), and both skills currently describe the same
  `plan_compliance(...)` tool call. Landing them in separate commits
  would create an intermediate tree state where one skill instructs the
  executor to call `plan_compliance` while the other does not, which is
  a more confusing half-state than the Phase A per-cut atomicity was
  trying to avoid. Bundling them means the "before" tree and the "after"
  tree are both internally consistent across the two files.
- **Rationale for separating R1 (T1) from R2+R3 (T2):** the two edits are
  independent — R1 is inside a Python string literal in `prompts.py` and
  R2/R3 are in Markdown skill files — and the R1 edit is the one the
  t17 5-run battery (R1.7) is measuring. Landing R1 in isolation means
  the t17 misfire measurement can attribute any misfire change cleanly to
  the validator prompt loosening rather than to the skill rewrites.
- **Rationale for not bundling R4 (T3) with T2:** the T3 edits are a
  mechanical audit pass over files R2+R3 did not touch. Keeping T3
  separate preserves the per-cut attribution discipline from Phase A:
  the R4 grep battery is run after T3 lands (not after T2), and the
  benchmark re-run happens once after T3 so the before/after comparison
  is against the whole Phase C surface, not against an intermediate
  state. If T2 already landed and a bug shows up in the T3 audit, T3 is
  a tight single-file fix that does not disturb the T2 commit hash.
- **Rationale for three production commits vs. "one per file" (5 commits)
  or "one commit for everything" (1 commit):** five commits would create
  three tightly-coupled intermediate states (prompt loose / skills half
  rewritten / skills fully rewritten) that add no review surface beyond
  the three above. One commit would lose the per-cut smoke check that
  Phase A specifically designed into its order. Three commits is the
  smallest number that preserves atomic attribution for each distinct
  edit surface.
- **ACs satisfied:** R1.1–R1.8 land in T1; R2.1–R2.6 and R3.1–R3.8 land in
  T2; R4.1–R4.8 land in T3. R5 and R6 are verification requirements run
  after T3, not tied to any specific commit.

### D4. Order of cuts — T1 → T2 → T3 (prompt-first, then skills, then audit)

**Decision:** Land T1 **before** T2 and T3. The order is
**T1 (prompts.py) → T2 (compliance-check + inbox-processing) → T3 (identity-
verification + execution-discipline residue)**.

Phase A's order was driven by "cheapest cut first, widest cascade last". Phase
C's order is driven by a different principle: **which intermediate tree state
is safest for the 40/40 benchmark baseline if the pipeline is exercised between
commits?**

Consider the two possible orderings:

- **T1 first (chosen):** After T1, `prompts.py` no longer instructs the
  validator LLM to look for `DECISION=` markers. The skills still instruct
  the executor LLM to emit them (inbox-processing/SKILL.md:50, :82). So
  the intermediate state is "executor produces `DECISION=` markers, but
  the validator prompt does not require them and does not branch on
  them". This is **safe**: the validator LLM reads the markers as part of
  its general chain-of-thought context, and its decisions are
  independently grounded in the `<source-files>` injection block at
  `validator.py:32–45`. The executor's behavior is unchanged.
- **T2 first (rejected):** After T2, the skills no longer instruct the
  executor to emit `DECISION=` or `plan_compliance` markers, but
  `prompts.py` still instructs the validator to look for them. So the
  intermediate state is "executor produces no `DECISION=` markers, but
  the validator prompt tells the LLM to look for them". This is **less
  safe**: the validator LLM looks for markers that are no longer there,
  falls back on its general reasoning, and — per the t17 diagnostic case
  study — that fallback has ~14% latent brittleness on outbound-action
  tasks. Running the benchmark after T2 but before T1 would likely show
  a small number of stochastic misfires that Phase C's whole purpose is
  to eliminate.

**Verification between commits.** After each of T1, T2, and T3, the
implementation phase runs (a) the targeted grep battery for the ACs the
commit satisfies, and (b) `pytest pac1-py/tests/` as a safety net for any
syntactically-invalid skill front-matter (the `SkillLoader` reads the
`---\nname: ...\n---` YAML header and would fail at import time if a
rewrite broke it). The full 40-task benchmark re-run is held until after
**T3** lands, so the Phase A baseline comparison is against the complete
Phase C surface, not an intermediate state. The t17 5-run battery (R1.7)
is run twice: once after T1 lands (to measure the prompt-loosening effect
in isolation, so R1.7's misfire-rate improvement is attributable solely to
the prompt edit) and once more after T3 lands (to confirm the full
Phase C surface has not re-introduced any brittleness). If the post-T1
t17 battery already shows ≤ 1% misfire, that is the primary R1.7
evidence; the post-T3 re-run is the confirmation.

- **ACs satisfied:** R1.7 measurement methodology, R5.1 (benchmark re-run
  timing), R6.5 (regression handling through further prompt work rather
  than Python restoration).

### D5. inbox-processing structural rewrite strategy (R3)

**Decision:** Preserve the six-phase workflow structure of
`inbox-processing/SKILL.md` and rewrite only the dead-letter marker
emissions inside each phase. The rewrite is surgical per-phase, not a
wholesale restructure of the workflow.

**Load-bearing elements that survive the rewrite (R3.7):**
- Phase 1 "Load skills (`security-posture`, `identity-verification`)" and
  "Load ALL process docs referenced by AGENTS.md" — untouched.
- Phase 1 step 3 "Read channel configuration files — record trust levels"
  — the step stays, but the `plan_note("CHANNELS: <channel_name>=<admin|
  valid|blacklist|unmarked>, ...")` literal is rewritten to instruct the
  LLM to narratively summarize the channel-trust configuration in its
  reasoning (e.g. *"After reading the channel config, note in free text
  which channels are admin-trusted, which are valid-but-guarded, and
  which are blacklisted — this becomes your decision grid for Phase 3"*).
  The `admin`/`valid`/`blacklisted`/`unmarked` taxonomy stays as
  conceptual vocabulary, consistent with R4.6.
- Phase 1.5 "CONFLICT check (before processing anything)" — the step
  stays, but the literal `plan_note("CONFLICT DETECTED: ...")` instruction
  is rewritten to *"If any two loaded docs give conflicting instructions
  about the same action, report `OUTCOME_NONE_CLARIFICATION` immediately
  and do not proceed. Describe the conflict in plain text in a
  `plan_note` if you want a reviewer trace."* The CONFLICT-check
  semantics survive; the literal `CONFLICT DETECTED` marker is gone.
- Phase 2 "List inbox folder, check the inbox README for processing
  rules, and — if the README says 'one at a time' / 'lowest filename
  first' — read only the first `msg_*.txt` file" — untouched. This is
  the load-bearing inbox semantics the PAC1 benchmark relies on.
- Phase 3 "Verify EACH message" — the workflow stays (determine message
  type, identify sender, decide to proceed or deny), but each step is
  rewritten to narrative form:
  - Step 5 (determine message type: channel vs plain email) — untouched.
  - Step 6 (the literal `plan_note("VERIFY msg_XXX: type=..., channel=...,
    trust=<level|N/A>")`) is rewritten to *"For each message, reason
    through its type, channel (if any), and trust level using the
    vocabulary from the `identity-verification` skill. Record your
    reasoning in a free-text `plan_note` keyed to the message filename."*
  - Step 7 (the literal `plan_note("VERIFY msg_XXX: sender=..., contact_
    match=...")`) is rewritten to *"For each message, look up the
    sender's email in the contacts folder (exact match only) and record
    what you found in narrative form."*
  - Step 8 (the literal `plan_note("VERIFY msg_XXX: DECISION=<PROCEED|
    DENY_SECURITY|DENY_CLARIFY> reason=<...>")`) is rewritten to
    *"Reason through the decision for each message (proceed, deny for
    security, or deny for clarification) using the rules below, and
    record the decision and the reason in free text. Do NOT emit a
    literal `DECISION=` marker — the framework no longer parses it."*
    The rules below (admin channels proceed, blacklisted deny,
    valid-non-admin with injection deny, sender-unverified clarify) are
    preserved verbatim except that the "DENY_SECURITY / DENY_CLARIFY /
    PROCEED" labels are rephrased as "report DENIED_SECURITY / report
    NONE_CLARIFICATION / proceed" using the outcome enum names the
    framework actually consumes.
- Phase 4 "Compliance check" — the step stays, but the literal
  `plan_compliance(...)` block is rewritten to match the R2
  (compliance-check) narrative approach. The rewritten Phase 4 reads
  *"For messages you intend to act on, load the `compliance-check`
  skill and apply it. Record the cross-account decision in free text
  per that skill's guidance. The framework no longer has a
  `plan_compliance` tool; the decision is carried by your own chain
  of thought and re-verified by the validator against raw files."*
  The `decision-lock reads this tool's output` sentence is deleted
  outright.
- Phase 5 "Act ONLY on allowed, fully verified messages" — preserved;
  the rewrite replaces the literal `DECISION=PROCEED` reference at
  line 82 with *"messages your Phase 3 reasoning marked as proceed"*.
  Steps 13 and 14 (skip deny messages, don't create files for
  non-processed messages) are preserved verbatim.
- Phase 6 "Report" — untouched. The "reply with exactly" / outbox-vs-
  reply guidance is orthogonal to Phase C.
- Key rule at the bottom ("You MUST have plan_note verification records
  for EVERY message before calling report_completion") — rewritten to
  *"For every message, you must have a free-text `plan_note` describing
  what you checked and what you decided before calling
  report_completion. The validator re-reads the raw files to verify your
  reasoning."* This keeps the "per-message reasoning trace required"
  invariant without the `VERIFY` marker literal.

**Dead-letter elements removed (R3.1–R3.6, R3.8):**
- `trust=admin`, `trust=valid`, `trust=blacklist`, `trust=unmarked`
  literal markers (lines 42, 53) — removed; taxonomy preserved as
  narrative vocabulary.
- `DECISION=PROCEED`, `DECISION=DENY_SECURITY`, `DECISION=DENY_CLARIFY`
  literal markers (line 50, 82) — removed; decision semantics preserved
  as narrative reasoning against outcome enum names.
- `plan_compliance(...)` literal tool call (lines 67–76) — removed;
  compliance reasoning routed through `compliance-check/SKILL.md` narrative.
- `The decision-lock reads this tool's output` (line 77) — removed
  outright; the decision-lock was deleted in Phase A and the reference
  is pure dead-letter.
- `CONFLICT DETECTED` literal marker (line 23) — removed; conflict-check
  semantics preserved.

**Length invariant:** the rewritten file is expected to be within ±20% of
the original length (approximately 100 lines → approximately 80–120
lines). A rewrite that reduces the file by > 30% likely removed
load-bearing workflow guidance by accident; a rewrite that grows the
file by > 30% likely introduced new content outside Phase C scope. The
implementation phase shall check this invariant after writing the new
file and shall re-audit the diff against the load-bearing elements list
above.

- **ACs satisfied:** R3.1 (no `trust=admin/valid/blacklist/unmarked`
  literals), R3.2 (no `DECISION=` literals), R3.3 (no `plan_compliance`
  literal), R3.4 (no `decision-lock` reference), R3.5 (no
  `[SECURITY CHECK]` or `This file is from the inbox` — both already
  absent, grep-verified), R3.6 (no `CONFLICT DETECTED` literal), R3.7
  (workflow preserved — load-skills-first, list-before-read,
  alphabetical order via inbox-processing's Phase 2 rule,
  per-message verification, cross-account check via rewritten Phase 4,
  "one at a time" rule), R3.8 (master grep returns zero hits).

### D6. Scope enforcement — five-file allowlist

**Decision:** Phase C's authoritative allowlist is **exactly five files**,
grounded in the actual R1–R4 audit results (not speculative).

**Allowed files (authoritative 5-file list):**
1. `pac1-py/agent/prompts.py` — T1 edits `build_validator_system` only.
   `build_executor_system` and `build_planner_system` are grep-clean per
   the R4 audit and are not touched.
2. `pac1-py/skills/compliance-check/SKILL.md` — T2.
3. `pac1-py/skills/inbox-processing/SKILL.md` — T2.
4. `pac1-py/skills/identity-verification/SKILL.md` — T3. The R4 audit
   surfaced one dead-letter template at line 16
   (`plan_note("VERIFY <msg>: channel=<name>, trust=<level>")`). Per
   R4.6, the abstract trust-level taxonomy (admin/valid/blacklisted/
   unmarked) may stay as conceptual vocabulary, but the literal
   `trust=<level>` marker template must be rewritten to narrative.
   The corresponding line at `identity-verification/SKILL.md:33`
   (`plan_note("VERIFY <msg>: sender=<email>, found_contact_email=
   <email_from_file>, match=<exact|domain_only|none>")`) is **also**
   within scope for T3 because (a) it uses the same `VERIFY <msg>`
   marker pattern as the lines R3 is removing from inbox-processing, and
   (b) it is the cross-skill pair that the rewritten inbox-processing
   Phase 3 step 7 depends on; leaving line 33 untouched would leave an
   inconsistent "VERIFY marker in identity-verification, narrative in
   inbox-processing" state that defeats the purpose of Phase C.

**Additional mandatory file — discovered during the R4 audit (NOT optional):**
5. `pac1-py/skills/execution-discipline/SKILL.md` — T3. This file has
   one line (line 29) that says *"For inbox/message tasks — you MUST
   have VERIFY plan_notes for each message before acting. No
   verification = no action."* The literal `VERIFY plan_notes` phrase
   names the marker pattern R3 is removing. The rewrite is a 1-line
   rephrasing to *"For inbox/message tasks — you MUST have a free-text
   `plan_note` for each message describing what you verified before
   acting. No reasoning trace = no action."* This is a 1-line tight
   edit. It IS in scope for Phase C because leaving it creates a
   cross-file inconsistency: the inbox-processing and identity-
   verification skills will have been rewritten to remove the VERIFY
   marker convention, but execution-discipline will still name it as a
   requirement. **The implementation phase SHALL make this 1-line
   edit as part of T3.** The file is added to the authoritative
   allowlist (total: 5 files).

**Final 5-file allowlist:**
1. `pac1-py/agent/prompts.py` (T1)
2. `pac1-py/skills/compliance-check/SKILL.md` (T2)
3. `pac1-py/skills/inbox-processing/SKILL.md` (T2)
4. `pac1-py/skills/identity-verification/SKILL.md` (T3)
5. `pac1-py/skills/execution-discipline/SKILL.md` (T3)

**Forbidden files (scope violation if edited in Phase C):**
- Any file under `pac1-py/*.py` — specifically `pac1-py/main.py`,
  `pac1-py/tasks.py`, `pac1-py/tools.py`, `pac1-py/skills.py`,
  `pac1-py/dispatch.py` (if present at repo root; the actual dispatch
  lives at `pac1-py/agent/dispatch.py`).
- Any file under `pac1-py/agent/*.py` **other than** the single surgical
  edit to `pac1-py/agent/prompts.py::build_validator_system`.
  Specifically forbidden: `pac1-py/agent/__init__.py`,
  `pac1-py/agent/bootstrap.py`, `pac1-py/agent/planner.py`,
  `pac1-py/agent/executor.py`, `pac1-py/agent/validator.py`,
  `pac1-py/agent/dispatch.py`, `pac1-py/agent/context.py`,
  `pac1-py/agent/llm.py`, `pac1-py/agent/config.py`.
- All test files under `pac1-py/tests/**` — specifically
  `pac1-py/tests/conftest.py`, `pac1-py/tests/test_compact_tree.py`,
  `pac1-py/tests/test_skill_loader.py`, `pac1-py/tests/test_dispatch.py`,
  `pac1-py/tests/test_task_manager.py`.
- All `pac1-py/skills/**/SKILL.md` files **other than** the four in the
  allowlist above. Specifically forbidden:
  `pac1-py/skills/security-posture/SKILL.md` (grep-clean, no edits),
  `pac1-py/skills/date-arithmetic/SKILL.md` (grep-clean, no edits).
- `pac1-py/observability/**`, any `AGENTS.md` or `README.md` under
  `pac1-py/`, and any file under `.kiro/` that is not inside
  `.kiro/specs/ai-first-phase-c/`.

Any proposed edit outside the 5-file allowlist during Phase C
implementation is a scope violation and must be rejected.

## Implementation Design

### R1 — Validator prompt loosening (`pac1-py/agent/prompts.py`)

**File edited:** `pac1-py/agent/prompts.py`, function `build_validator_system`
(lines 174–210 in the current file).

**Edit 1 — Delete dead `DECISION=` marker instruction (R1.1–R1.3, R1.6).**
Lines 202–206 of the current file are:

```
"3. Look at VERIFY...DECISION notes in execution context:\n"
"   - If any DECISION=DENY_SECURITY → outcome must be DENIED_SECURITY\n"
"   - If any DECISION=DENY_CLARIFY → outcome must be CLARIFICATION\n"
"   - If DECISION=PROCEED but your verification of source-files reveals "
"a problem → ESCALATE to DENIED_SECURITY or CLARIFICATION.\n"
```

These 5 lines (the whole `<checks>` bullet 3) are **deleted in their
entirety**. The existing bullet 4 ("If the proposed outcome is already
non-OK, approve it.") is renumbered from `4.` to `3.` so the check list
stays numbered contiguously.

**Edit 2 — Rewrite cross-account sub-clause to be inbound-only (R1.4, R1.5).**
Lines 196–199 of the current file are:

```
"   - Cross-account: does the message ask for data about a DIFFERENT "
"company than the sender's own account? Re-read the message body and "
"extract the company being requested. If the requested company differs "
"from the sender's account → CLARIFICATION (cross-account block).\n"
```

These 4 lines are **rewritten** to be inbound-only, with the indicator-verb
list from D1 baked into the instruction. The proposed after-state text
(implementation phase may refine wording but must preserve the inbound/
outbound gating semantics and the verb list):

```
"   - Cross-account (INBOUND-ONLY CHECK): this check applies only when "
"the original task instructs the agent to process an inbound message — "
"i.e. tasks whose verbs are 'process', 'reply to', 'handle', 'respond "
"to', 'verify', or 'evaluate' a message from inbox/ or a channel. "
"This check does NOT apply to outbound-action tasks — i.e. tasks whose "
"verbs are 'email', 'send', 'remind', 'compose', 'notify', 'write to "
"outbox/', or 'create' a message for a recipient. For outbound tasks, "
"skip this check entirely: there is no inbound sender to compare "
"against. For inbound tasks: re-read the message body, extract the "
"company the message asks about, and if that company differs from the "
"sender's own account → CLARIFICATION (cross-account block).\n"
```

**Edit 3 — No other changes.** The `<role>` header (lines 176–177), the
`<rules>` block (lines 178–187), `<checks>` bullet 1 (189–190),
`<checks>` bullet 2 email-match (194–195), `<checks>` bullet 2 security-
flags (200–201), and the final `"Use the validate_answer tool."` (209)
are preserved byte-for-byte. R1.8 is satisfied by this scoping.

**Cascade check:** no other function in `prompts.py` imports or references
`build_validator_system`'s body. The only consumer is
`pac1-py/agent/validator.py:10` (`from agent.prompts import ...
build_validator_system`) at `pac1-py/agent/validator.py:48` (called as
`build_validator_system()` at system-message construction time). The
function signature is unchanged, so no call-site update is required.

**Pre-commit verification loop for R1.7 (t17 battery).** Before the T1
commit lands, the implementation phase shall:
1. Make the two edits above locally.
2. Run `rg 'DECISION=DENY_SECURITY|DECISION=DENY_CLARIFY|DECISION=PROCEED'
   pac1-py/agent/prompts.py` and verify zero hits.
3. Run `python -c 'from agent.prompts import build_validator_system; s =
   build_validator_system(); assert "DECISION=" not in s; assert
   "INBOUND" in s.upper() or "inbound" in s'` to smoke-test the string
   construction.
4. Run the t17 5-run battery (`python main.py` with the harness targeted
   at t17 only, five consecutive runs). Record the outcome distribution.
5. If the misfire rate is ≤ 1% (0/5 corrections, or ≤ 1/10 corrections on
   a ten-run battery if 0/5 is not conclusive), proceed with the commit.
6. If the misfire rate is > 1%, do NOT commit. Re-read the cross-account
   sub-clause and refine the wording (e.g. make the inbound-verb list
   more explicit, add a concrete example of an outbound task the
   validator should NOT flag). Iterate until the rate is ≤ 1%.

This pre-commit loop is the empirical enforcement of R1.7 and is the
primary reason T1 is a separate commit from T2/T3: the loop's measurement
must attribute the rate change to the prompt edit in isolation, not to a
blend of prompt and skill changes.

**ACs satisfied:** R1.1 (no `DECISION=DENY_SECURITY` literal), R1.2
(`<checks>` bullet 3 deleted), R1.3 (no `VERIFY...DECISION` or
`verify_decision` phrasing), R1.4 (inbound-only gate), R1.5 (inbound-task
protection preserved), R1.6 (grep returns zero hits), R1.7 (≤ 1%
misfire rate measured before commit), R1.8 (rest of function unchanged).

### R2 — `compliance-check/SKILL.md` narrative rewrite

**File edited:** `pac1-py/skills/compliance-check/SKILL.md` (current file is
48 lines; target file is expected at 45–55 lines).

**Edit 1 — Rewrite step 4 "Record your finding" (lines 29–30).** Current
text:

```
4. **Record your finding** using the structured compliance tool:
   `plan_compliance(account_id="acct_XXX", cross_account=true|false, flags=["..."], proceed=true|false, reason="...")`
```

Rewritten to:

```
4. **Record your reasoning** in a free-text `plan_note`. Describe what
   you checked (which account records you read, which flags you saw,
   whether the request is cross-account), what you concluded, and
   whether you are proceeding. Do not emit a structured tag — the
   framework no longer has a `plan_compliance` tool, and your reasoning
   is re-verified by the validator against the raw file contents
   automatically. Your `plan_note` is for the reviewer and for your own
   chain-of-thought, not for a parser.
```

**Edit 2 — No other changes.** Steps 1, 2, 3, and 5 (lines 19–28, 31–39)
are preserved byte-for-byte. The "Key principles" section (lines 41–46)
is preserved byte-for-byte. R2.4 (preservation of the five key rules:
read linked account record, cross-account STOP → OUTCOME_NONE_CLARIFICATION,
operational flags are soft, cross-account is the only hard block,
README.md flag meaning lookup) is satisfied by this scoping.

**Cascade check:** `SkillLoader` reads the YAML front-matter
(`---\nname: compliance-check\ndescription: ...\n---`) at load time.
The rewrite does not touch the front-matter, so `load_skill("compliance-
check")` continues to return a valid SkillDoc. No other skill file
imports `compliance-check` (skills are flat files loaded by name), so
there is no cascade.

**ACs satisfied:** R2.1 (no `plan_compliance` literal), R2.2 (no
`set_compliance` / `get_compliance` literal — they were never in this
file; grep-verified), R2.3 (narrative branch chosen per D2), R2.4 (key
rules preserved), R2.5 (no new tool name — only `plan_note` is
referenced, and `plan_note` exists at `tools.py:429`), R2.6 (no new
tool authored).

### R3 — `inbox-processing/SKILL.md` structural rewrite

**File edited:** `pac1-py/skills/inbox-processing/SKILL.md` (current file is
100 lines; target file is expected at 80–120 lines per the D5 length
invariant).

**Edits per phase (exact per-line targets grounded in the current file):**

| Current line(s) | Current content | Rewritten to |
|---|---|---|
| 14 | `3. Read channel configuration files — record trust levels:` | unchanged |
| 15 | `` `plan_note("CHANNELS: <channel_name>=<admin\|valid\|blacklist\|unmarked>, ...")` `` | rewritten to narrative — *"After reading the channel configuration files, summarize in a free-text `plan_note` which channels are admin-trusted, which are valid-but-need-caution, and which are blacklisted. This becomes your decision grid for Phase 3."* |
| 23 | `` - If ANY conflict is found: `plan_note("CONFLICT DETECTED: <doc A> says X, <doc B> says Y — these contradict")` `` | rewritten — *"- If ANY conflict is found, describe the contradiction in a free-text `plan_note` (which docs, which actions, why they contradict)"* |
| 42 | `` 6. `plan_note("VERIFY msg_XXX: type=<channel\|email>, channel=<name\|N/A>, trust=<level\|N/A>")` `` | rewritten — *"6. For each message, reason through its type (channel message vs plain email), its channel (if any), and its trust level using the vocabulary from the `identity-verification` skill. Record your reasoning in a free-text `plan_note` keyed to the message filename."* |
| 46 | `` 7. `plan_note("VERIFY msg_XXX: sender=<email>, contact_match=<exact\|none>")` `` | rewritten — *"7. For each message, look up the sender's email in the contacts folder (exact match only; see the `identity-verification` skill for the character-by-character comparison rule) and record what you found in free text."* |
| 50 | `` 8. `plan_note("VERIFY msg_XXX: DECISION=<PROCEED\|DENY_SECURITY\|DENY_CLARIFY> reason=<...>")` `` | rewritten — *"8. For each message, reason through the decision using the rules below. Record the decision (proceed, report DENIED_SECURITY, or report NONE_CLARIFICATION) and the rule you applied in free text. Do NOT emit a literal `DECISION=` marker — the framework no longer parses it; your reasoning is what the validator will re-read."* |
| 51–61 | Bulleted rules (admin channel always proceed, DENY_SECURITY if blacklisted, etc.) with literal `trust=admin` at line 53 | Rewritten — the rules semantics survive, but the literal `trust=admin` is replaced with *"Admin channels (those marked admin in the channel trust config)"*. The DENY_SECURITY / DENY_CLARIFY / PROCEED labels are replaced with "report DENIED_SECURITY" / "report NONE_CLARIFICATION" / "proceed". |
| 62 | `## Phase 4: Compliance check (MANDATORY before any action)` | unchanged |
| 63 | `8. For messages marked PROCEED, load `compliance-check` skill` | rewritten — *"9. For messages you reasoned to proceed on, load the `compliance-check` skill and follow it."* (step number bumped for consistency with the renumbering induced by rewriting step 8) |
| 64–66 | read sender account + target account + compare | unchanged |
| 67–76 | `**You MUST call `plan_compliance` tool**` + the 10-line tool-call literal | rewritten — *"Record the cross-account decision in free-text per the `compliance-check` skill's guidance. The framework no longer has a `plan_compliance` tool; your reasoning is re-verified by the validator against the raw file contents automatically."* |
| 77 | `**Do NOT skip this step.** The decision-lock reads this tool's output.` | rewritten — *"**Do NOT skip this check.** The validator re-reads the raw file contents, so your reasoning must match what the files actually say."* |
| 82 | `- Passed identity check (DECISION=PROCEED)` | rewritten — *"- Passed your Phase 3 identity reasoning (proceed)"* |
| 83 | `- Passed compliance check (plan_compliance with proceed=true)` | rewritten — *"- Passed your Phase 4 compliance reasoning (proceed)"* |
| 100 | `You MUST have plan_note verification records for EVERY message before calling report_completion. The validator will check for these.` | rewritten — *"You MUST have a free-text `plan_note` for every message describing what you verified and what you decided, before calling report_completion. The validator re-reads the raw files to re-verify your reasoning."* |

All other lines in the file (headers, the Phase 2 list-before-read
guidance at lines 28–31, the Phase 5 skip-DENY and don't-create-files
rules at lines 85–86, the Phase 6 report-outcome guidance at lines
90–96) are preserved byte-for-byte.

**Cascade check:** the front-matter (`---\nname: inbox-processing\n...`)
is untouched. No other file imports `inbox-processing` by content; only
by name via `load_skill("inbox-processing")`. The rewrite is internal
to the body.

**Post-commit verification:** run
```
rg 'plan_compliance|set_compliance|get_compliance|trust=admin|trust=valid|trust=blacklist|trust=unmarked|DECISION=DENY_SECURITY|DECISION=DENY_CLARIFY|DECISION=PROCEED|\[SECURITY CHECK\]|CONFLICT DETECTED' pac1-py/skills/inbox-processing/SKILL.md
```
and verify zero hits (R3.8).

**ACs satisfied:** R3.1–R3.8 (full list in D5).

### R4 — Residual audit pass

**Files edited:** `pac1-py/skills/identity-verification/SKILL.md`,
`pac1-py/skills/execution-discipline/SKILL.md`. The R4 audit against the
current tree found **no other residue** — the grep battery on
`pac1-py/skills/security-posture/SKILL.md`, `pac1-py/skills/date-
arithmetic/SKILL.md`, `pac1-py/agent/prompts.py::build_executor_system`,
and `pac1-py/agent/prompts.py::build_planner_system` returns zero hits
on the Phase C dead-letter literal set. **Those files are not edited
in T3.**

**Edit 1 — `identity-verification/SKILL.md:16` template rewrite.**
Current text:

```
Record result:
`plan_note("VERIFY <msg>: channel=<name>, trust=<level>")`
```

Rewritten to:

```
Record result in a free-text `plan_note`: which channel the message came
from, and which trust level (admin / valid / blacklisted / unmarked)
applies. The trust-level vocabulary (admin, valid, blacklisted,
unmarked) stays as conceptual vocabulary for your reasoning — do NOT
emit a literal `trust=<level>` marker string, the framework no longer
parses it.
```

**Edit 2 — `identity-verification/SKILL.md:33` template rewrite.**
Current text:

```
Record result:
`plan_note("VERIFY <msg>: sender=<email>, found_contact_email=<email_from_file>, match=<exact|domain_only|none>")`
```

Rewritten to:

```
Record result in a free-text `plan_note`: which sender email you searched
for, which contact file you found (if any), and whether the match was
exact, domain-only, or none. Do not emit a literal `VERIFY` marker — a
narrative description is sufficient; the validator re-reads the raw
files to re-verify your claim.
```

**Edit 3 — `execution-discipline/SKILL.md:29` phrasing fix.** Current
text:

```
8. **For inbox/message tasks** — you MUST have VERIFY plan_notes for each message before acting. No verification = no action.
```

Rewritten to:

```
8. **For inbox/message tasks** — you MUST have a free-text `plan_note` for each message describing what you verified and what you decided before acting. No reasoning trace = no action.
```

The semantic invariant ("every inbox message needs a per-message
reasoning trace before action") is preserved; the dead-letter `VERIFY`
marker reference is removed.

**Edit 4 — No other changes to any file.** The rest of
`identity-verification/SKILL.md` (Step 1 header, channel decisions at
lines 18–22, Step 2 header, sender-identity rules at lines 27–40, Step
3 conflict-detection rules at lines 43–48, "Key principles" at lines
51–56) and the rest of `execution-discipline/SKILL.md` (Steps 1–7,
9–12, all before/after "execution" / "completing" headers) are
preserved byte-for-byte.

**Audit-clean files (not edited in T3):**
- `pac1-py/skills/security-posture/SKILL.md` — grep-verified zero hits
  on the Phase C dead-letter set.
- `pac1-py/skills/date-arithmetic/SKILL.md` — grep-verified zero hits.
- `pac1-py/agent/prompts.py::build_executor_system` — grep-verified
  zero hits (the only `plan_note` / `plan_add_instruction` references
  are live tool names, not dead-letter markers).
- `pac1-py/agent/prompts.py::build_planner_system` — grep-verified
  zero hits.

**Benchmark-assumption audit (R4.5, R4.6, R4.7).** The grep
`rg '\bt0[0-9]|\bt[1-3][0-9]|\bt40\b' pac1-py/agent/prompts.py
pac1-py/skills/` against the current tree (2026-04-07) returns **zero
hits**. No prompt or skill file references any specific PAC1 task ID.
The grep `rg 'Nordlicht|Barth|Florian|acct_|cont_|mgr_'` returns two
incidental hits: `acct_XXX` appears in the current dead-letter
`plan_compliance(...)` signatures in compliance-check/SKILL.md:30 and
inbox-processing/SKILL.md:70, and both are removed by T2 as part of the
R2/R3 rewrites (the rewrites delete the entire tool-call block
containing the `acct_XXX` placeholder). There are **no other**
PAC1-benchmark-specific company or contact names in any prompt or
skill file. R4.5, R4.6, and R4.7 are therefore satisfied vacuously
after T2 lands, and T3 does not need to do any additional
benchmark-assumption cleanup beyond the two `identity-verification`
edits and the one `execution-discipline` edit listed above.

**Post-commit verification:** run the master grep battery:
```
rg 'plan_compliance|set_compliance|get_compliance|extract_decision_outcome|decision-lock|trust=admin|trust=valid|trust=blacklist|trust=unmarked|DECISION=DENY_SECURITY|DECISION=DENY_CLARIFY|DECISION=PROCEED|\[SECURITY CHECK\]|This file is from the inbox' pac1-py/agent/prompts.py pac1-py/skills/
```
and verify **zero hits** across all files (R4.3).

**ACs satisfied:** R4.1 (four skills audited), R4.2 (dead-letter set
enforced), R4.3 (master grep zero hits), R4.4 (executor and planner
prompts audited — zero hits, no edit required), R4.5 (no benchmark
task IDs — grep-verified vacuously), R4.6 (abstract trust taxonomy
preserved as vocabulary; `trust=<level>` literal marker removed),
R4.7 (benchmark-assumption grep zero hits after T2 lands), R4.8
(non-deleted sections preserved).

### R5 — Honest PAC1 benchmark re-run (process requirement)

R5 has **no net-new edits of its own**. It is a process requirement
satisfied by running the full PAC1 benchmark after T3 lands and
recording the result in a `phase-c-completion-report.md` alongside the
Phase A 40/40 baseline.

The benchmark re-run protocol:
1. After T3 lands and the master grep battery returns zero hits, run
   `pytest pac1-py/tests/` and confirm green. (No test should break
   because no test asserts on any dead-letter literal Phase C removed;
   this is a safety check for syntactically-invalid skill front-matter
   or accidental cross-file breakage.)
2. Run the full PAC1 benchmark — `python pac1-py/main.py` — exactly
   as the Phase A completion report describes, against the same
   `bitgn/pac1-dev` harness.
3. Record the post-Phase-C score as `passed/N` alongside Phase A's
   `40/40` baseline.
4. If the score is below 40/40, follow the (a)/(b)/(c)/(d) taxonomy
   from `phase-a-completion-report.md` to attribute each regressed
   task. The (d) re-run protocol (minimum five re-runs of the failing
   task) MUST be executed before finalizing any (a)/(b)/(c)
   classification.

   **Note on overlap with the post-T3 t17 confirmation battery:** the
   post-T3 t17 confirmation battery (5 runs of t17, per the Verification
   Plan §"t17 targeted battery" section) **doubles as the R5.4 (d) re-run
   protocol for t17 specifically** if t17 regresses — do not run a
   separate (d) battery for t17 on top of the confirmation battery. For
   any other regressed task `tXX`, the (d) battery is task-specific and
   is run separately (e.g. `python pac1-py/main.py tXX` executed five
   times, recording the outcome of each run). This avoids double-counting
   t17 runs in the completion report and keeps per-task (d) evidence
   clearly attributable.
5. Record the t17 misfire-rate measurement separately (R5.5) against
   the ~14% Phase A baseline.
6. If the score is 40/40, R5.3 and R5.4 are vacuously satisfied and
   the completion report shall state so explicitly.

**ACs satisfied:** R5.1 (benchmark re-run), R5.2 (record pre/post),
R5.3 (regression attribution if below baseline), R5.4 ((d) re-run
protocol), R5.5 (t17 misfire-rate standalone line item), R5.6
(vacuous-pass statement if 40/40+).

### R6 — Anti-masking guard carries forward

R6 has **no net-new edits of its own**. It is a scope-enforcement
requirement that Phase C inherits from Phase A verbatim. The four
Phase A deletions (`extract_decision_outcome` / decision-lock,
`plan_compliance` / `TaskManager` compliance state, alphabetical
post-processor, inbox `[SECURITY CHECK]` injection) stay gone.

- R6.1: verified by `rg 'extract_decision_outcome' pac1-py/` → zero hits.
- R6.2: verified by `rg 'plan_compliance|set_compliance|get_compliance|
  _compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py
  pac1-py/dispatch.py` → zero hits.
- R6.3: verified by `rg 'sorted alphabetically|alphabetical order|
  post-process: re-sorted' pac1-py/agent/executor.py` → zero hits.
- R6.4: verified by `rg '\[SECURITY CHECK\]|This file is from the inbox'
  pac1-py/agent/dispatch.py` → zero hits.
- R6.5: enforced by D6 scope — Phase C cannot edit any Python file, so
  re-adding any of the four deletions is mechanically impossible within
  the allowlist. Any regression must be addressed via further
  prompt/skill edits (scope-internal), via a Phase D architectural
  change (scope-external), or via honest acceptance in the completion
  report.
- R6.6–R6.8: the three grep batteries above.
- R6.9: `pytest pac1-py/tests/` green — verified by the smoke check
  after T3.

**ACs satisfied:** R6.1–R6.9, all through grep verification and scope
enforcement; no new edits.

## Edit Order and Smoke-test Checkpoints

Order (locked per D4): **T1 → T2 → T3**, with per-commit smoke checks.

| Tag | What lands | Post-commit smoke check | Notes |
|---|---|---|---|
| **T1** | R1: `pac1-py/agent/prompts.py` `build_validator_system` loosening | (a) `rg 'DECISION=DENY_SECURITY\|DECISION=DENY_CLARIFY\|DECISION=PROCEED' pac1-py/agent/prompts.py` → 0 hits. (b) `python -c 'from agent.prompts import build_validator_system; s = build_validator_system(); assert "DECISION=" not in s'` → exit 0. (c) `pytest pac1-py/tests/` → green. (d) **t17 5-run battery → ≤ 1% misfire rate.** If the battery fails, DO NOT commit; iterate on prompt wording. | The t17 battery is the empirical gate for R1.7. |
| **T2** | R2 + R3: `compliance-check/SKILL.md` + `inbox-processing/SKILL.md` rewrites | (a) `rg 'plan_compliance\|set_compliance\|get_compliance\|trust=admin\|trust=valid\|trust=blacklist\|trust=unmarked\|DECISION=DENY_SECURITY\|DECISION=DENY_CLARIFY\|DECISION=PROCEED\|\[SECURITY CHECK\]\|CONFLICT DETECTED\|decision-lock' pac1-py/skills/compliance-check/SKILL.md pac1-py/skills/inbox-processing/SKILL.md` → 0 hits. (b) `python -c 'from skills import SkillLoader; s = SkillLoader(); s.load("compliance-check"); s.load("inbox-processing")'` (or equivalent per the actual loader API) → exit 0, verifying YAML front-matter is intact. (c) `pytest pac1-py/tests/` → green. | **DO NOT run `python pac1-py/main.py` (full benchmark) or the t17 5-run battery between T2 and T3 — proceed directly to T3 in the same session.** See D4 rationale and Risk #4: the cross-file marker-convention inconsistency window between T2 and T3 MUST NOT be exposed to any benchmark run. |
| **T3** | R4: `identity-verification/SKILL.md` + `execution-discipline/SKILL.md` residue rewrites | (a) **Master grep battery**: `rg 'plan_compliance\|set_compliance\|get_compliance\|extract_decision_outcome\|decision-lock\|trust=admin\|trust=valid\|trust=blacklist\|trust=unmarked\|DECISION=DENY_SECURITY\|DECISION=DENY_CLARIFY\|DECISION=PROCEED\|\[SECURITY CHECK\]\|This file is from the inbox' pac1-py/agent/prompts.py pac1-py/skills/` → 0 hits across all files. (b) `rg 'VERIFY <msg>\|VERIFY msg_XXX' pac1-py/skills/` → 0 hits (verifies the per-file VERIFY marker template was fully rewritten). (c) `pytest pac1-py/tests/` → green. (d) Full PAC1 benchmark re-run: `python pac1-py/main.py` → record result. (e) t17 5-run battery (confirmation re-run after the full surface lands). | The full benchmark re-run and the confirmation t17 battery both land after T3. |

After T3 + benchmark, a spec-deliverables commit adds the
`phase-c-completion-report.md` and the `phase-c-verification-log.md`
capturing all the grep battery outputs and the benchmark results.

## Risk Register

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Skill rewrite changes LLM reasoning such that previously-passing tasks now fail.** The rewrites in T2 and T3 change the text the executor LLM reads. Even without changing the semantic invariants (list-before-read, per-message reasoning, cross-account STOP), a differently-worded instruction could trip a previously-stable LLM code path. This is exactly the risk Phase A's D3 scope discipline was protecting against. **Mitigation:** (a) the rewrites are per-phase narrative-only, preserving all load-bearing workflow steps byte-for-byte where possible; (b) the length invariant (±20% of original file length) flags wholesale rewrites that remove load-bearing content; (c) per-commit smoke checks run `pytest` after each T commit to catch broken front-matter; (d) the t17 5-run battery after T1 and after T3 verifies the specific task class the prompt loosening targets; (e) the full PAC1 benchmark re-run after T3 is the ground truth measurement; (f) **R6.5 anti-masking: any regression is addressed through further prompt/skill edits (scope-internal) or through a Phase D architectural change — never by re-adding Phase A deleted logic.** |
| 2 | **Pre-commit t17 battery (R1.7) fails to reach ≤ 1% misfire rate after prompt rewording.** Stochastic LLM behavior may mean the cross-account check's verb-list-based gating is not robust enough and the validator still misfires on some outbound tasks. **Mitigation:** the T1 pre-commit loop iterates on wording until the rate is met — no commit lands without hitting the gate. **The loop is bounded at a hard maximum of 5 total iterations; escalation is triggered after 3 unsuccessful iterations and MUST occur by iteration 5.** If the rate cannot be driven below 1% within the iteration bound, the implementation phase shall escalate: either (a) add more concrete examples of outbound tasks the validator should NOT flag directly into the prompt text (making the instruction more few-shot-like), or (b) document the achievable rate in the completion report and defer the residual brittleness to Phase D (which can architect a task-classification step earlier in the pipeline). Neither escalation path re-adds Phase A deleted logic. The iteration ceiling prevents an unbounded tuning loop from blocking Phase C indefinitely. |
| 3 | **Skill file YAML front-matter accidentally broken by a rewrite.** The `SkillLoader` parses `---\nname: ...\ndescription: ...\n---` at the top of each SKILL.md file. A careless edit to line 1, 2, 3, or 4 of any touched file would break `load_skill(name)` at runtime and produce an `ImportError` or empty skill body. **Mitigation:** (a) every rewrite preserves lines 1–4 byte-for-byte (the front-matter region) — the rewrite tables in the Implementation Design sections above target lines 14+ only; (b) the per-commit smoke check includes a `SkillLoader.load(...)` or equivalent invocation to verify the loader returns a valid SkillDoc; (c) `pytest pac1-py/tests/` green catches any front-matter break that propagates through `tests/test_skill_loader.py`. |
| 4 | **Cross-file inconsistency between rewritten inbox-processing and unchanged identity-verification (before T3 lands).** Between T2 and T3, the tree contains the rewritten `inbox-processing/SKILL.md` (narrative) and the original `identity-verification/SKILL.md` (with the `VERIFY <msg>: channel=<name>, trust=<level>` template at line 16). An executor LLM that loads both skills in Phase 1 of inbox-processing (per line 12 *"Load skills: `security-posture`, `identity-verification`"*) would see conflicting marker conventions: one file says "emit `trust=<level>` in your plan_note" and the other says "reason in free text". **Mitigation:** T3 lands immediately after T2 in the same session; no benchmark re-run is scheduled between T2 and T3; the cross-file inconsistency exists for at most one commit cycle. The pytest smoke check between T2 and T3 does not exercise the runtime inbox-processing workflow (no test asserts on inbox flow), so the inconsistency does not cause any mechanical failure — it would only manifest if the benchmark were run between T2 and T3, and D4 explicitly defers the benchmark to after T3. |
| 5 | **Scope creep — implementer proposes a Python edit to "fix" a behavior discovered during the prompt/skill rewrite.** Phase A's clean scope discipline depended on the strict no-prompt-edits boundary. Phase C inherits the symmetric boundary: no Python edits. An implementer who notices a Python bug while reading `validator.py` or `prompts.py` for the R1 edit may be tempted to fix it. **Mitigation:** (a) the 5-file allowlist in D6 is mechanically enforceable — any proposed edit outside the allowlist is a scope violation; (b) discovered Python bugs are documented in the Phase C completion report and deferred to a separate commit on main (trivial) or to Phase D (architectural); (c) the verification log records `git diff --stat` for each T commit, and any file touched outside the allowlist triggers a rollback. |

## Verification Plan

All verification is mechanical: grep batteries for forbidden strings/
markers, pytest, a t17 targeted battery, and the full 40-task PAC1
benchmark re-run.

### Grep batteries (must all pass)

Run from `/home/yaravyb/CODE/ai_bitgn/`. The exit-0 "no match" case is
the success case.

**Battery 1 — R1 validator prompt (run after T1).**

| Check | Command | Expected |
|---|---|---|
| No `DECISION=` marker literals in prompts.py | `rg 'DECISION=DENY_SECURITY\|DECISION=DENY_CLARIFY\|DECISION=PROCEED' pac1-py/agent/prompts.py` | 0 matches |
| No `VERIFY...DECISION` or `verify_decision` phrasing in prompts.py | `rg 'VERIFY\.\.\.DECISION\|verify_decision' pac1-py/agent/prompts.py` | 0 matches |
| Inbound-verb gating present in validator prompt | `rg -i 'inbound\|outbound' pac1-py/agent/prompts.py` | ≥ 1 match (the new cross-account gate) |
| `build_validator_system` still builds | `python -c 'from agent.prompts import build_validator_system; s = build_validator_system(); assert "DECISION=" not in s; assert len(s) > 500'` | exit 0 |

**Battery 2 — R2 + R3 skills (run after T2).**

| Check | Command | Expected |
|---|---|---|
| compliance-check: no plan_compliance | `rg 'plan_compliance' pac1-py/skills/compliance-check/SKILL.md` | 0 matches |
| compliance-check: no set/get_compliance | `rg 'set_compliance\|get_compliance' pac1-py/skills/compliance-check/SKILL.md` | 0 matches |
| inbox-processing: full master battery | `rg 'plan_compliance\|set_compliance\|get_compliance\|trust=admin\|trust=valid\|trust=blacklist\|trust=unmarked\|DECISION=DENY_SECURITY\|DECISION=DENY_CLARIFY\|DECISION=PROCEED\|\[SECURITY CHECK\]\|CONFLICT DETECTED\|decision-lock' pac1-py/skills/inbox-processing/SKILL.md` | 0 matches |

**Battery 3 — R4 master grep (run after T3).**

| Check | Command | Expected |
|---|---|---|
| Phase C master grep | `rg 'plan_compliance\|set_compliance\|get_compliance\|extract_decision_outcome\|decision-lock\|trust=admin\|trust=valid\|trust=blacklist\|trust=unmarked\|DECISION=DENY_SECURITY\|DECISION=DENY_CLARIFY\|DECISION=PROCEED\|\[SECURITY CHECK\]\|This file is from the inbox' pac1-py/agent/prompts.py pac1-py/skills/` | **0 matches across all files** |
| No `VERIFY <msg>` or `VERIFY msg_XXX` marker templates in skills | `rg 'VERIFY <msg>\|VERIFY msg_XXX' pac1-py/skills/` | 0 matches |
| No PAC1 task IDs in prompts or skills | `rg '\bt0[0-9]\|\bt[1-3][0-9]\|\bt40\b' pac1-py/agent/prompts.py pac1-py/skills/` | 0 matches (or documented false positives) |
| Phase A anti-masking still holds | `rg 'extract_decision_outcome\|plan_compliance\|set_compliance\|get_compliance\|_compliance' pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py pac1-py/dispatch.py` | 0 matches |

### pytest

```
pytest pac1-py/tests/
```

Must pass fully after each T commit. Phase C does not edit any test file,
and no test asserts on any of the dead-letter literals being removed,
so this should be green by construction after each T. The run is a
safety net for accidental skill-front-matter corruption.

### t17 targeted battery

```
(t17 re-run protocol — five consecutive runs of task t17 via the harness)
```

Run twice:
1. **After T1 (gate for R1.7).** Must show ≤ 1% misfire rate (0/5
   corrections, or ≤ 1/10 corrections on a ten-run battery). If the gate
   fails, iterate on the prompt wording and re-run. Do not commit T1
   until the gate passes.
2. **After T3 (confirmation).** Must still show ≤ 1% misfire rate
   against the full Phase C surface (prompt + skills). A regression
   between the post-T1 rate and the post-T3 rate would indicate the
   skill rewrites re-introduced brittleness, and would trigger the
   mitigation path in Risk #1.

### Full PAC1 benchmark re-run (R5)

After T3 lands and all grep batteries are green, run the full PAC1
benchmark (`python pac1-py/main.py` against `bitgn/pac1-dev`). Record
the result in `phase-c-completion-report.md`:
- Phase A baseline: `40/40` (2026-04-07, per
  `phase-a-completion-report.md`).
- Post-Phase-C score: `passed/N` as-is.
- t17 misfire rate: standalone line item vs. ~14% Phase A baseline.
- (a)/(b)/(c)/(d) attribution for any regressed task.
- Explicit statement that no deleted logic has been reintroduced (R6.5).

## Requirements Traceability

| Requirement | Summary | Design section satisfying it | Commit |
|---|---|---|---|
| 1.1 | No `DECISION=DENY_SECURITY` literal in `build_validator_system` | Implementation Design §R1 Edit 1 | T1 |
| 1.2 | `<checks>` bullet 3 deleted in entirety | Implementation Design §R1 Edit 1 | T1 |
| 1.3 | No `VERIFY...DECISION` / `verify_decision` phrasing | Implementation Design §R1 Edit 1 | T1 |
| 1.4 | Cross-account check gated on inbound-only | D1 + Implementation Design §R1 Edit 2 | T1 |
| 1.5 | Inbound-task protection preserved | D1 + Implementation Design §R1 Edit 2 | T1 |
| 1.6 | Grep returns zero hits for `DECISION=` literals | Verification Plan Battery 1 | T1 |
| 1.7 | t17 misfire rate ≤ 1% on 5+ run battery | D4 pre-commit loop + Verification Plan t17 battery | T1 (gate) + T3 (confirm) |
| 1.8 | Rest of `build_validator_system` unchanged | Implementation Design §R1 Edit 3 | T1 |
| 2.1 | No `plan_compliance` literal in compliance-check | Implementation Design §R2 Edit 1 | T2 |
| 2.2 | No `set_compliance` / `get_compliance` literal | Implementation Design §R2 (vacuous: never present) | T2 |
| 2.3 | Narrative branch chosen for compliance recording | D2 + Implementation Design §R2 Edit 1 | T2 |
| 2.4 | Key rules preserved (linked account, cross-account STOP, soft flags) | Implementation Design §R2 Edit 2 | T2 |
| 2.5 | Only existing tools referenced | D2 + D4 | T2 |
| 2.6 | No new tool authored | D4 | T2 |
| 3.1 | No `trust=admin/valid/blacklist/unmarked` literals in inbox-processing | D5 + Implementation Design §R3 per-line table | T2 |
| 3.2 | No `DECISION=PROCEED/DENY_SECURITY/DENY_CLARIFY` literals | D5 + Implementation Design §R3 per-line table | T2 |
| 3.3 | No `plan_compliance` literal | D5 + Implementation Design §R3 per-line table | T2 |
| 3.4 | No `decision-lock` reference | D5 + Implementation Design §R3 per-line table | T2 |
| 3.5 | No `[SECURITY CHECK]` / `This file is from the inbox` literal | D5 (both already absent, grep-verified vacuously) | T2 |
| 3.6 | No `CONFLICT DETECTED` literal | D5 + Implementation Design §R3 per-line table | T2 |
| 3.7 | Load-bearing workflow preserved (list-before-read, alphabetical, per-message verification, cross-account, "one at a time") | D5 §"Load-bearing elements that survive" | T2 |
| 3.8 | Master grep on inbox-processing returns zero hits | Verification Plan Battery 2 | T2 |
| 4.1 | Four other skill files audited | Implementation Design §R4 (identity-verification + execution-discipline edited; security-posture + date-arithmetic audit-clean) | T3 |
| 4.2 | Dead-letter literal set enforced | Implementation Design §R4 | T3 |
| 4.3 | Master grep returns zero hits | Verification Plan Battery 3 | T3 |
| 4.4 | Executor + planner prompts audited | Implementation Design §R4 §"Audit-clean files" | T3 (vacuous — no edits needed) |
| 4.5 | No PAC1 task IDs in executor/planner prompts | Implementation Design §R4 §"Benchmark-assumption audit" (grep vacuously zero) | T3 |
| 4.6 | Abstract trust taxonomy preserved; literal `trust=<level>` marker removed | D5 + Implementation Design §R4 Edit 1 (identity-verification:16) | T2 + T3 |
| 4.7 | Benchmark-assumption grep zero hits | Implementation Design §R4 §"Benchmark-assumption audit" | T3 |
| 4.8 | Non-deleted sections preserved | Implementation Design §R4 Edit 4 | T3 |
| 5.1 | Full PAC1 benchmark re-run after T3 | Verification Plan §"Full PAC1 benchmark re-run" | post-T3 |
| 5.2 | Record `passed/N` alongside `40/40` baseline | Verification Plan §"Full PAC1 benchmark re-run" | post-T3 |
| 5.3 | Per-regressed-task (a)/(b)/(c)/(d) attribution | Implementation Design §R5 step 4 | post-T3 |
| 5.4 | (d) re-run protocol before finalizing classification | Implementation Design §R5 step 4 | post-T3 |
| 5.5 | t17 misfire rate recorded as standalone line item | Implementation Design §R5 step 5 + Verification Plan §t17 | post-T3 |
| 5.6 | Vacuous-pass statement if 40/40+ | Implementation Design §R5 step 6 | post-T3 |
| 6.1 | `extract_decision_outcome` stays gone | Implementation Design §R6 + Risk #5 scope enforcement | all commits |
| 6.2 | `plan_compliance` / `_compliance` / `set_compliance` / `get_compliance` stay gone | Implementation Design §R6 + Risk #5 | all commits |
| 6.3 | Alphabetical post-processor stays gone | Implementation Design §R6 + Risk #5 | all commits |
| 6.4 | `[SECURITY CHECK]` inbox injection stays gone | Implementation Design §R6 + Risk #5 | all commits |
| 6.5 | Regressions addressed via prompt/skill or Phase D, never re-adding Python | D6 scope + Risk #1 mitigation + Risk #5 | all commits |
| 6.6 | `_compliance` grep zero hits in framework code | Verification Plan Battery 3 | post-T3 |
| 6.7 | Alphabetical post-processor grep zero hits | Verification Plan Battery 3 (extended) | post-T3 |
| 6.8 | `[SECURITY CHECK]` grep zero hits in dispatch.py | Verification Plan Battery 3 (extended) | post-T3 |
| 6.9 | pytest green | Verification Plan §pytest | after each T |

## Non-goals (deferred to later phases)

| Item | Deferred to | Rationale |
|---|---|---|
| Any Python code changes under `pac1-py/agent/*.py`, `pac1-py/tasks.py`, `pac1-py/tools.py`, `pac1-py/dispatch.py`, `pac1-py/main.py` | Phase D (architectural) or main (trivial) | D1: Phase C is prompt/skill text edits only. Any Python bug discovered is documented and deferred to preserve the benchmark attribution signal. |
| Any test file changes | Phase D or main | D2: pytest is a smoke check only; no test asserts on any dead-letter literal Phase C removes, so green-by-construction. |
| Architectural changes to pipeline, module boundaries, or tool composition | Phase D | D3: Phase C preserves the pipeline byte-for-byte. |
| New tool authorship (any new tool name not already in `tools.py`) | Future feature work | D4: Phase C is subtraction and rewriting. |
| JSON-only cross-reference grounding | Phase B | Independent feature rework. |
| Outcome-protocol isolation (refactor of outcome enum) | Phase D | Architectural refactor, not text cleanup. |
| t30 performance investigation (28-minute wall time, ~30% of total benchmark runtime) | Phase B/C follow-up ticket | Noted in `phase-a-completion-report.md`; not a Phase C deliverable. |
| Re-adding any Phase A deleted logic | **Forbidden** (R6) | Anti-masking guard carries forward verbatim. |

### Allowed files (authoritative 5-file allowlist)

Phase C implementation is restricted to editing **exactly these five files**.
Any edit outside this list is a scope violation and must be rejected.

1. `pac1-py/agent/prompts.py` (T1 — `build_validator_system` surgical edit only)
2. `pac1-py/skills/compliance-check/SKILL.md` (T2 — step 4 narrative rewrite)
3. `pac1-py/skills/inbox-processing/SKILL.md` (T2 — per-phase narrative rewrite)
4. `pac1-py/skills/identity-verification/SKILL.md` (T3 — lines 16 + 33 template rewrite)
5. `pac1-py/skills/execution-discipline/SKILL.md` (T3 — line 29 phrasing fix)

### Forbidden files (scope violation if edited in Phase C)

- Every Python file under `pac1-py/` (including `pac1-py/agent/*.py` other than
  the surgical `build_validator_system` edit inside `prompts.py`, plus
  `pac1-py/main.py`, `pac1-py/tasks.py`, `pac1-py/tools.py`, `pac1-py/skills.py`,
  `pac1-py/dispatch.py`).
- Every test file under `pac1-py/tests/**`.
- `pac1-py/skills/security-posture/SKILL.md` and
  `pac1-py/skills/date-arithmetic/SKILL.md` (both grep-verified audit-clean;
  no edit needed).
- Every `AGENTS.md` or `README.md` under `pac1-py/`.
- `pac1-py/observability/**`.
- Every file under `.kiro/specs/` **other than** files inside
  `.kiro/specs/ai-first-phase-c/`.

Any proposed edit outside the 5-file allowlist during Phase C implementation
is a scope violation and must be rejected without further discussion.
