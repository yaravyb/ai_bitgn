# Design: persistent-task-planner

> Generated: 2026-03-25T21:00:00Z
> Status: design-generated

## 1. Overview

### 1.1 Purpose

This design specifies the architecture for a persistent task planning system that stores execution plans as JSON files on the sandbox filesystem. Plans survive context compression (micro-compact, auto-compact, manual compact), enabling the model to reorient after compaction by reading its plan from disk rather than relying on conversation messages that may be lost or summarized.

### 1.2 Scope

The feature adds four new tools (`plan_create`, `plan_step_done`, `plan_step_skip`, `plan_status`) to the existing agent tool framework, integrates plan state into the replan checkpoint mechanism (with plan revision guidance) and self-verification prompt, and does so entirely within existing Python modules (`tools.py`, `dispatch.py`, `loop.py`, `verify.py`) plus one placeholder addition to the `verification-frame` skill template.

### 1.3 Design Constraints

- **No new Python modules**: All code lives in existing files per Requirement 11.
- **Zero overhead**: When plan tools are unused, no filesystem I/O or LLM calls occur (Requirement 7).
- **Existing patterns**: All additions follow the established handler signature, dispatch map registration, and tool schema format.
- **Type safety**: No `Any` types in public interfaces; precise types for all plan data structures. Status values are constrained to `"pending" | "done" | "skipped"`.

## 2. Architecture

### 2.1 Component Diagram

```
+---------------------+     +---------------------+     +---------------------+
|     tools.py        |     |    dispatch.py       |     |     loop.py         |
|                     |     |                      |     |                     |
| TOOL_SCHEMAS        |     | DISPATCH_MAP         |     | Point E: replan     |
|  + plan_create      |     |  + plan_create       |     |  checkpoint with    |
|  + plan_step_done   |     |  + plan_step_done    |     |  plan injection +   |
|  + plan_step_skip   |     |  + plan_step_skip    |     |  revision guidance  |
|  + plan_status      |     |  + plan_status       |     |                     |
|                     |     |                      |     +---------------------+
| get_tool_schemas()  |     | _handle_plan_create()|
|  returns all incl.  |     | _handle_plan_step()  |     +---------------------+
|  plan tools         |     | _handle_plan_skip()  |     |     verify.py        |
+---------------------+     | _handle_plan_status()|     |                     |
                             +---------------------+     | build_verification  |
                                                         |  _prompt() with     |
                                                         |  {{PLAN_STATUS      |
                                                         |    _SECTION}}       |
                                                         |  placeholder        |
                                                         +---------------------+

                             +---------------------+
                             |  Sandbox Filesystem  |
                             |                      |
                             |  .plan/steps.json    |
                             |  (created on demand) |
                             +---------------------+
```

### 2.2 Data Flow

```
Model calls plan_create(steps=["Read inbox", "Write email", "Update seq"])
  |
  v
dispatch.py: _handle_plan_create()
  |-- Serializes plan to JSON
  |-- vm.write(".plan/steps.json", json_content)
  |-- Returns plan object as JSON string
  v
Model calls plan_step_done(step_index=0)
  |
  v
dispatch.py: _handle_plan_step_done()
  |-- vm.read(".plan/steps.json")
  |-- Parses JSON, updates step[0].status = "done"
  |-- vm.write(".plan/steps.json", updated_json)
  |-- Returns updated plan as JSON string
  v
Model calls plan_step_skip(step_index=2, reason="seq.json does not exist")
  |
  v
dispatch.py: _handle_plan_step_skip()
  |-- vm.read(".plan/steps.json")
  |-- Parses JSON, updates step[2].status = "skipped", adds reason
  |-- vm.write(".plan/steps.json", updated_json)
  |-- Returns updated plan with skip_reason and adjusted counts
  v
[Context compression occurs]
  v
loop.py: Point E replan checkpoint triggers
  |-- vm.read(".plan/steps.json")  -- only if file exists
  |-- If pending steps exist: formats plan + revision guidance
  |-- If all steps done: suggests report_completion
  |-- Injects checkpoint with plan state
  v
Model calls plan_status()
  |
  v
dispatch.py: _handle_plan_status()
  |-- vm.read(".plan/steps.json")
  |-- Returns full plan with completed/total/skipped counts
  v
Model calls report_completion(...)
  |
  v
loop.py: verification interception
  |-- vm.read(".plan/steps.json")  -- only if file exists
  |-- Injects plan status into verification prompt
  |-- Model reviews incomplete steps before confirming
```

## 3. Plan File Schema

### 3.1 File Location

Path: `.plan/steps.json` (relative to sandbox filesystem root)

The `.plan/` directory is created implicitly by `vm.write()` (which auto-creates parent directories). No explicit `mkdir` call is needed. The directory does not exist until the model calls `plan_create`.

### 3.2 JSON Schema

Covers Requirements: 4.1, 4.2, 4.3

```json
{
  "steps": [
    {
      "index": 0,
      "description": "Read inbox/task.md to understand requirements",
      "status": "done"
    },
    {
      "index": 1,
      "description": "Write the response email to outbox/",
      "status": "pending"
    },
    {
      "index": 2,
      "description": "Update outbox/seq.json with new sequence number",
      "status": "skipped",
      "skip_reason": "seq.json does not exist in this workspace"
    }
  ],
  "total": 3,
  "completed": 1,
  "skipped": 1
}
```

**Field definitions**:

| Field | Type | Description |
|-------|------|-------------|
| `steps` | `list[StepEntry]` | Ordered array of plan steps |
| `steps[].index` | `int` | 0-based integer index |
| `steps[].description` | `str` | Human-readable step description |
| `steps[].status` | `str` | One of `"pending"`, `"done"`, or `"skipped"` |
| `steps[].skip_reason` | `str` (optional) | Reason for skipping; present only when status is `"skipped"` |
| `total` | `int` | Total number of steps |
| `completed` | `int` | Number of steps with status `"done"` |
| `skipped` | `int` | Number of steps with status `"skipped"` |

### 3.3 Internal Type Definitions

Added to `dispatch.py` (not exported, used only by handler functions):

```python
from typing import TypedDict, NotRequired

class _PlanStep(TypedDict):
    index: int
    description: str
    status: str  # "pending" | "done" | "skipped"
    skip_reason: NotRequired[str]

class _PlanData(TypedDict):
    steps: list[_PlanStep]
    total: int
    completed: int
    skipped: int
```

These types enforce structure within the dispatch handlers. They are module-private (underscore-prefixed) and not part of the public API. The `NotRequired` annotation from `typing` (Python 3.11+) is used for the optional `skip_reason` field.

### 3.4 Summary String Format

The summary field adapts to the presence of skipped steps:

- **No skipped steps**: `"2/5 steps completed"`
- **With skipped steps**: `"2/4 actionable steps completed, 1 skipped"` (denominator = total - skipped)

This format satisfies Requirement 15.5, which specifies that skipped steps do not count as incomplete.

## 4. Tool Schema Definitions

Covers Requirements: 5.1, 5.2, 5.3, 5.4

All schemas are appended to the `TOOL_SCHEMAS` list in `tools.py`, following the identical format used by existing tools.

### 4.1 plan_create Schema

```python
{
    "type": "function",
    "function": {
        "name": "plan_create",
        "description": (
            "Create a persistent execution plan. Steps are saved to disk "
            "and survive context compression. Overwrites any existing plan. "
            "Use this to decompose a task into discrete steps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of step descriptions in execution order. "
                        "Each string describes one discrete action."
                    ),
                },
            },
            "required": ["steps"],
        },
    },
}
```

### 4.2 plan_step_done Schema

```python
{
    "type": "function",
    "function": {
        "name": "plan_step_done",
        "description": (
            "Mark a plan step as completed. Returns the updated plan "
            "with current completion status."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "step_index": {
                    "type": "integer",
                    "description": "0-based index of the step to mark as done.",
                },
            },
            "required": ["step_index"],
        },
    },
}
```

### 4.3 plan_step_skip Schema

```python
{
    "type": "function",
    "function": {
        "name": "plan_step_skip",
        "description": (
            "Mark a plan step as skipped (unnecessary or impossible). "
            "Skipped steps do not count as incomplete. Returns the "
            "updated plan with current status."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "step_index": {
                    "type": "integer",
                    "description": "0-based index of the step to mark as skipped.",
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Optional reason why the step is being skipped."
                    ),
                },
            },
            "required": ["step_index"],
        },
    },
}
```

### 4.4 plan_status Schema

```python
{
    "type": "function",
    "function": {
        "name": "plan_status",
        "description": (
            "Read the current plan status from disk. Use after context "
            "compression to reorient on what remains to be done."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}
```

### 4.5 Registration Impact

After adding the four schemas to `TOOL_SCHEMAS`:

- `TOOL_SCHEMAS` length: 9 -> 13
- `TOOL_NAMES` set: auto-derived, gains `{"plan_create", "plan_step_done", "plan_step_skip", "plan_status"}`
- `get_tool_schemas("mini")` returns 13 schemas (plan tools work on both runtimes)
- `get_tool_schemas("pcm")` returns 16 schemas (13 base + 3 PCM extras)
- `SCOUT_TOOL_SCHEMAS` unchanged (filtered by `_SCOUT_TOOL_NAMES` frozenset, which excludes plan tools)

### 4.6 Constant: Plan File Path

A module-level constant in `dispatch.py`:

```python
_PLAN_FILE: str = ".plan/steps.json"
```

This centralizes the plan file path for use across all four handlers and avoids magic strings.

## 5. Dispatch Handler Design

Covers Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 12.1, 12.2, 15.1, 15.2, 15.3, 15.4, 15.5

All handlers follow the established signature:

```python
def _handle_*(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
```

### 5.1 _handle_plan_create

**Purpose**: Creates or overwrites `.plan/steps.json` with a new plan.

**Logic**:

1. Extract `steps` from `args`. If empty array, return error JSON.
2. Build plan data structure with each step as `{"index": i, "description": text, "status": "pending"}`.
3. Compute `total` (length of steps), `completed` (initially 0), `skipped` (initially 0).
4. Serialize to indented JSON string.
5. Call `vm.write(_PLAN_FILE, json_content)`.
6. Log info: `"plan_create: %d steps created"`.
7. Return the plan JSON string (with summary field appended via `_format_plan_response`).

**Error handling**:
- Empty steps array: `{"error": "plan_create requires at least one step"}`
- VM write error: Caught by `dispatch_tool`'s existing `ConnectError` handler.

**Requirements mapped**: 1.1, 1.2, 1.3, 1.4, 6.1, 12.1

### 5.2 _handle_plan_step_done

**Purpose**: Marks a single step as `"done"` via read-modify-write.

**Logic**:

1. Extract `step_index` from `args`.
2. Call `_read_plan(vm)` to get current plan data.
3. If plan not found, return error JSON.
4. Validate `step_index` is within range `[0, total)`. If out of range, return error JSON.
5. Update `steps[step_index]["status"] = "done"`.
6. Remove `skip_reason` key if present (step was previously skipped, now marked done).
7. Recompute `completed` and `skipped` counts.
8. Serialize to indented JSON and call `vm.write(_PLAN_FILE, updated_json)`.
9. Log info: `"plan_step_done: step %d '%s' marked done (%d/%d)"`.
10. Return the updated plan JSON string via `_format_plan_response`.

**Error handling**:
- No plan file: `_read_plan` returns error -> return `{"error": "No plan exists. Call plan_create first."}`
- Index out of range: `{"error": "step_index N is out of range. Valid range: 0 to M."}`
- VM read/write error: Caught by `dispatch_tool`'s existing `ConnectError` handler.

**Read-modify-write pattern**: This handler performs a compound VM operation (read then write). The `vm.read()` response is a protobuf message. The `_read_plan` helper uses `MessageToDict(resp)` to convert it to a dict, then extracts the `"content"` field (which contains the file text as a string), and parses that as JSON. This matches the pattern used by `_handle_read_file`.

**Requirements mapped**: 2.1, 2.2, 2.3, 2.4, 6.2, 12.2

### 5.3 _handle_plan_step_skip

**Purpose**: Marks a single step as `"skipped"` via read-modify-write.

**Logic**:

1. Extract `step_index` and optional `reason` from `args`.
2. Call `_read_plan(vm)` to get current plan data.
3. If plan not found, return error JSON.
4. Validate `step_index` is within range `[0, total)`. If out of range, return error JSON.
5. Update `steps[step_index]["status"] = "skipped"`.
6. If `reason` is provided and non-empty, set `steps[step_index]["skip_reason"] = reason`.
7. Recompute `completed` and `skipped` counts.
8. Serialize to indented JSON and call `vm.write(_PLAN_FILE, updated_json)`.
9. Log info: `"plan_step_skip: step %d '%s' skipped (%d/%d completed, %d skipped)"`.
10. Return the updated plan JSON string via `_format_plan_response`.

**Error handling**:
- No plan file: `_read_plan` returns error -> return `{"error": "No plan exists. Call plan_create first."}`
- Index out of range: `{"error": "step_index N is out of range. Valid range: 0 to M."}`
- VM read/write error: Caught by `dispatch_tool`'s existing `ConnectError` handler.

**Requirements mapped**: 15.1, 15.2, 15.3, 15.4, 15.5, 6.2, 6.4

### 5.4 _handle_plan_status

**Purpose**: Reads and returns the current plan from disk.

**Logic**:

1. Call `_read_plan(vm)` to get current plan data.
2. If plan not found, return message JSON.
3. Log info: `"plan_status: %d/%d steps completed"`.
4. Return the plan JSON string via `_format_plan_response` (includes summary field).

**Error handling**:
- No plan file: Return `{"message": "No plan has been created yet. Use plan_create to create one."}`

**Requirements mapped**: 3.1, 3.2, 3.3, 6.3, 12.3

### 5.5 Helper Function: _read_plan

To avoid code duplication between `_handle_plan_step_done`, `_handle_plan_step_skip`, and `_handle_plan_status`, a shared helper extracts the plan-reading logic:

```python
def _read_plan(vm) -> tuple[_PlanData | None, str | None]:
    """Read and parse the plan file from the VM.

    Returns (plan_data, None) on success, or (None, error_json) on failure.
    """
```

This function:
1. Calls `vm.read(_PLAN_FILE)`.
2. Converts via `MessageToDict(resp)`.
3. Extracts and parses the JSON content from the `"content"` field.
4. Returns the parsed `_PlanData` dict or an error string.

Both `_handle_plan_step_done`, `_handle_plan_step_skip`, and `_handle_plan_status` call this helper. The replan checkpoint in `loop.py` uses a separate helper (see Section 6) because it operates with different error semantics (fail-open instead of fail-with-error).

### 5.6 Helper Function: _format_plan_response

Shared formatting for the plan JSON response returned to the model:

```python
def _format_plan_response(plan: _PlanData) -> str:
    """Format a plan data dict as an indented JSON string with summary."""
```

Logic:
1. Compute `actionable = plan["total"] - plan["skipped"]`.
2. If `plan["skipped"] > 0`: set summary to `"{completed}/{actionable} actionable steps completed, {skipped} skipped"`.
3. If `plan["skipped"] == 0`: set summary to `"{completed}/{total} steps completed"`.
4. Add `"summary"` key to plan dict.
5. Serialize with `json.dumps(plan, indent=2)`.

### 5.7 DISPATCH_MAP Registration

Four new entries in `DISPATCH_MAP`:

```python
DISPATCH_MAP: dict[str, Callable] = {
    # ... existing 12 entries ...
    "plan_create": _handle_plan_create,
    "plan_step_done": _handle_plan_step_done,
    "plan_step_skip": _handle_plan_step_skip,
    "plan_status": _handle_plan_status,
}
```

### 5.8 Thread Safety Consideration

`dispatch_parallel()` could theoretically dispatch `plan_step_done` or `plan_step_skip` concurrently with another plan operation. This is safe in practice because:

1. The LLM never issues two plan operations in the same parallel batch (plan tools are sequential by nature).
2. If it did, the VM's filesystem operations are serialized server-side.
3. No in-process shared mutable state exists (each handler reads from VM, processes, writes back).

No additional locking is needed.

## 6. Resilience Integration -- Replan Checkpoint

Covers Requirements: 8.1, 8.2, 8.3, 12.4, 16.1, 16.2, 16.3, 16.4

### 6.1 Integration Point

Location: `loop.py`, Point E replan checkpoint (line ~616-657), inside the `if _replan_triggered:` block.

### 6.2 Plan Reading at Checkpoint

After the existing checkpoint message construction (the `checkpoint_msg = (...)` expression, line ~640-652) and before `messages.append(...)`, add plan-aware content:

```
[existing checkpoint construction code builds checkpoint_msg]

# --- Plan-aware checkpoint augmentation ---
plan_section = _read_plan_for_checkpoint(runtime)
if plan_section:
    checkpoint_msg = checkpoint_msg.replace("</checkpoint>", plan_section + "\n</checkpoint>")
    log.info("Re-plan checkpoint: plan steps included")

messages.append({"role": "user", "content": checkpoint_msg})
```

The plan section is injected before the closing `</checkpoint>` tag so it appears within the checkpoint block.

### 6.3 Helper Function: _read_plan_for_checkpoint

A new function in `loop.py` that reads the plan from the VM:

```python
def _read_plan_for_checkpoint(vm) -> str | None:
    """Read plan from VM filesystem and format for checkpoint injection.

    Returns a formatted string with plan status and revision guidance,
    or None if no plan exists.
    Uses the same vm.read() + MessageToDict pattern as dispatch handlers.
    Errors are silently caught (fail-open: checkpoint works without plan).
    """
```

**Logic**:
1. Try `vm.read(".plan/steps.json")`.
2. On `ConnectError` (file not found): return `None`.
3. Parse via `MessageToDict`, extract `"content"` field, parse JSON.
4. Compute `pending_count`, `completed_count`, `skipped_count`.
5. Format as a numbered list showing done/pending/skipped status.
6. **If pending steps exist**: Append revision guidance (Requirement 16.1, 16.2, 16.3).
7. **If all steps done (none pending)**: Append completion suggestion (Requirement 16.4).
8. Return formatted string wrapped in a `<plan-status>` tag.

**Output format when pending steps exist** (Requirements 8.3, 16.1, 16.2, 16.3):

```
<plan-status>
Your execution plan (2/4 actionable steps completed, 1 skipped):
1. [DONE] Read inbox/task.md
2. [DONE] Write email to outbox/
3. [PENDING] Update outbox/seq.json
4. [SKIPPED] Verify formatting rules (not applicable)

If your current approach is not working, you can:
- Call plan_create with a revised step list to replace this plan.
- Call plan_step_skip to skip steps that are unnecessary or blocked.
You may also continue with the current plan if it is still viable.
</plan-status>
```

**Output format when all steps done** (Requirement 16.4):

```
<plan-status>
Your execution plan (3/3 steps completed):
1. [DONE] Read inbox/task.md
2. [DONE] Write email to outbox/
3. [DONE] Update outbox/seq.json

All plan steps are completed. Consider calling report_completion.
</plan-status>
```

### 6.4 Zero Overhead When No Plan Exists

When no plan exists, `vm.read(".plan/steps.json")` raises a `ConnectError` with a not-found code. The helper catches this and returns `None`. The checkpoint message proceeds without plan content, identical to current behavior (Requirement 8.2).

**Cost when no plan exists**: One VM read call per replan trigger. This is acceptable because replan triggers are rare (repetition/cycling detection or stall interval of 8+ steps).

### 6.5 Non-Coercive Guidance (Requirement 16.3)

The checkpoint guidance uses permissive language ("you can", "you may also continue"). The model is never forced to revise its plan. The guidance provides options: revise via `plan_create`, skip via `plan_step_skip`, or continue with the current plan.

## 7. Pre-Completion Plan Review (Verification Integration)

Covers Requirements: 9.1, 9.2, 9.3

### 7.1 New Placeholder in Verification Frame

Add a `{{PLAN_STATUS_SECTION}}` placeholder to the `verification-frame` skill template (`sandbox-py/skills/verification-frame/SKILL.md`):

```
<verification>
You are about to submit the following answer. Before submitting, verify it is correct.

## Proposed Answer
Code: {{CODE}}
Answer: {{ANSWER}}

{{POLICY_SECTION}}

{{CHECKLIST_SECTION}}

{{SOURCE_BASENAME_SECTION}}

{{PLAN_STATUS_SECTION}}

## Instructions
...
</verification>
```

The placeholder is placed after `{{SOURCE_BASENAME_SECTION}}` and before `## Instructions`, consistent with the existing placeholder ordering pattern.

### 7.2 Updated build_verification_prompt Signature

```python
def build_verification_prompt(
    answer: str,
    code: str,
    policy_contents: dict[str, str],
    checklist_body: str = "",
    source_basename: str | None = None,
    frame_template: str | None = None,
    plan_status: str = "",        # NEW parameter
) -> str:
```

The new `plan_status` parameter receives a pre-formatted string containing the plan status. The function performs placeholder substitution:

```python
result = result.replace("{{PLAN_STATUS_SECTION}}", plan_status)
```

When `plan_status` is empty, the placeholder is replaced with an empty string, producing no visible change in the verification prompt. This maintains backward compatibility (Requirement 9.3).

**Fallback path**: The inline fallback frame (used when `frame_template` is `None`) also gains a plan status section. If `plan_status` is non-empty, it is appended between the source section and the Instructions section.

### 7.3 Plan Status Section Content

When a plan exists with incomplete steps, the section content is:

```
## Plan Status -- Incomplete Steps Detected
Your execution plan has 2 of 4 actionable steps still pending:
- Step 2: [PENDING] Update outbox/seq.json
- Step 3: [PENDING] Verify file was written correctly

Review these incomplete steps. Either complete them before re-submitting,
or confirm they are intentionally skipped by calling plan_step_skip.
```

When all steps are done (or done + skipped), the section content is:

```
## Plan Status
All 3 plan steps completed (1 skipped).
```

### 7.4 Integration in loop.py

At the two verification interception points (tool-call path ~line 974 and text-only path ~line 771), read the plan from the VM before calling `build_verification_prompt`:

```python
plan_status_text = _read_plan_for_verification(runtime)
prompt = build_verification_prompt(
    answer, code, summary.policy_files,
    checklist_body=verification_checklist,
    source_basename=None,
    frame_template=verification_frame,
    plan_status=plan_status_text,
)
```

### 7.5 Helper Function: _read_plan_for_verification

```python
def _read_plan_for_verification(vm) -> str:
    """Read plan from VM and format as a verification section.

    Returns formatted plan status string, or empty string if no plan exists.
    """
```

Similar to `_read_plan_for_checkpoint` but with a different output format (section heading, action instructions for incomplete steps). Returns empty string (not `None`) when no plan exists, because the `plan_status` parameter in `build_verification_prompt` expects a string.

**Logic**:
1. Try `vm.read(".plan/steps.json")`.
2. On `ConnectError`: return `""`.
3. Parse via `MessageToDict`, extract content, parse JSON.
4. Compute pending steps (status == `"pending"`).
5. If pending steps exist: format with "Incomplete Steps Detected" heading and instructions.
6. If no pending steps: format with "All N plan steps completed" message.
7. Return formatted string.

## 8. Compression Survival

Covers Requirements: 10.1, 10.2, 10.3

### 8.1 Design Rationale

The plan survives context compression by architectural design, not by explicit code:

- **Micro-compact** (`_apply_micro_compact`): Clears old tool result message content. The plan file on disk is unaffected because micro-compact only modifies `messages` list entries, not the VM filesystem.

- **Auto-compact** (`_apply_auto_compact`): Summarizes the full conversation into three messages. The plan file on disk is unaffected because auto-compact only calls the LLM for summarization and replaces the `messages` list.

- **Manual compact** (`_handle_compact` sentinel): Triggers auto-compact. Same as above.

### 8.2 Post-Compression Recovery Flow

After any compression:
1. The model receives a summarized context.
2. If a replan checkpoint fires, it includes plan state from disk (Section 6) with revision guidance.
3. The model can also call `plan_status` at any time to read its plan.
4. The plan on disk is identical to what it was before compression.

No additional code is needed for compression survival. This is an inherent property of on-disk state.

## 9. Skill Alignment

Covers Requirements: 14.1, 14.2, 14.3

### 9.1 Execution Discipline Alignment

The `execution-discipline` SKILL.md already instructs:

> "Build a COMPLETE step list" (Section 1, Rule 1)
> "Review your plan and confirm every step was completed" (Section 1, Rule 1)

The plan tools provide the mechanism to persist this step list. No changes to the skill text are needed -- the tools naturally complement the existing instructions. The model can now use `plan_create` to persist the step list and `plan_step_skip` to explicitly mark steps that are not needed.

### 9.2 Self-Verification Alignment

The `self-verification` SKILL.md checklist item 7 ("Process completeness audit") benefits from plan status being available in the verification prompt. The model can cross-reference its plan steps against the audit requirements. Skipped steps with reasons provide documentation for why certain procedures were intentionally omitted.

### 9.3 Verification Frame Update

The `verification-frame` SKILL.md template receives the new `{{PLAN_STATUS_SECTION}}` placeholder (Section 7.1). This is the only skill file modification required.

## 10. Observability and Logging

Covers Requirements: 12.1, 12.2, 12.3, 12.4

All logging uses the existing `log = logging.getLogger(__name__)` pattern.

| Event | Level | Module | Message Format |
|-------|-------|--------|----------------|
| Plan created | INFO | dispatch | `"plan_create: %d steps created"` |
| Step marked done | INFO | dispatch | `"plan_step_done: step %d '%s' marked done (%d/%d completed)"` |
| Step marked skipped | INFO | dispatch | `"plan_step_skip: step %d '%s' skipped (%d/%d completed, %d skipped)"` |
| Plan status read | INFO | dispatch | `"plan_status: %d/%d steps completed"` |
| Plan in checkpoint | INFO | loop | `"Re-plan checkpoint: plan steps included (%d/%d completed)"` |
| Plan in verification | INFO | loop | `"Verification: plan status included (%d/%d completed)"` |
| Plan read error | DEBUG | dispatch/loop | `"Plan file read failed: %s"` |

No new loggers or logging configuration changes are needed.

## 11. Backward Compatibility

Covers Requirements: 7.1, 7.2, 7.3, 13.1, 13.2, 13.3

### 11.1 Zero Overhead When Unused

- **Schema registration**: Tool schemas are static data in `TOOL_SCHEMAS`. Adding them has negligible memory cost and zero runtime cost.
- **Dispatch handlers**: Only invoked when the model calls the tool. No initialization, no pre-created files or directories.
- **Replan checkpoint**: One VM read per replan trigger (rare). Returns immediately on file-not-found.
- **Verification**: One VM read per verification attempt (max 2 per task). Returns immediately on file-not-found.
- **No `.plan/` directory**: Directory does not exist until `plan_create` is called.

### 11.2 Test Suite Impact

Existing tests that assert on `TOOL_SCHEMAS` length (currently `== 9`) and `TOOL_NAMES` size (currently `== 9`) will need to be updated to `== 13`. This is the only modification to existing tests.

Existing tests that assert on `DISPATCH_MAP` coverage (`test_dispatch_map_has_all_tool_names`) will automatically pass because `TOOL_NAMES` and `DISPATCH_MAP` both grow together.

The `get_tool_schemas()` tests for PCM will need their expected count verified: `len(pcm) == len(mini) + 3` remains correct (the delta stays at 3; both base counts increase equally).

The `EXPECTED_TOOL_NAMES` set in `test_tools.py` needs updating to include the four new tool names.

### 11.3 New Test Requirements

New tests follow the existing mock VM pattern (`_make_mock_vm()` fixture, `@patch("agent.dispatch.MessageToDict", ...)`):

**In `test_tools.py`**:
- Plan tool schemas exist in `TOOL_SCHEMAS`
- Schema structure validation (parameters, required fields, types)
- `TOOL_NAMES` includes plan tool names
- Count assertions updated from 9 to 13

**In `test_dispatch.py`**:
- `_handle_plan_create` writes to VM and returns plan JSON
- `_handle_plan_create` with empty steps returns error
- `_handle_plan_step_done` reads, updates, writes back
- `_handle_plan_step_done` with invalid index returns error
- `_handle_plan_step_done` with no plan returns error
- `_handle_plan_step_skip` reads, updates status to "skipped", writes back
- `_handle_plan_step_skip` with reason includes skip_reason in response
- `_handle_plan_step_skip` with invalid index returns error
- `_handle_plan_step_skip` with no plan returns error
- `_handle_plan_step_skip` adjusts completed/skipped/summary counts correctly
- `_handle_plan_status` reads and returns plan
- `_handle_plan_status` with no plan returns message
- All four handlers registered in `DISPATCH_MAP`

**In `test_verify.py`** (existing file):
- `build_verification_prompt` with `plan_status` parameter substitutes placeholder
- `build_verification_prompt` with empty `plan_status` produces no visible change
- Fallback frame includes plan status section when provided

## 12. Requirements Traceability Matrix

| Requirement | Design Section | Component |
|-------------|---------------|-----------|
| 1.1 | 5.1 | dispatch.py: `_handle_plan_create` |
| 1.2 | 5.1 | dispatch.py: `_handle_plan_create` |
| 1.3 | 5.1 | dispatch.py: `_handle_plan_create` |
| 1.4 | 5.1 | dispatch.py: `_handle_plan_create` |
| 2.1 | 5.2 | dispatch.py: `_handle_plan_step_done` |
| 2.2 | 5.2 | dispatch.py: `_handle_plan_step_done` |
| 2.3 | 5.2 | dispatch.py: `_handle_plan_step_done` |
| 2.4 | 5.2 | dispatch.py: `_handle_plan_step_done` |
| 3.1 | 5.4 | dispatch.py: `_handle_plan_status` |
| 3.2 | 5.4 | dispatch.py: `_handle_plan_status` |
| 3.3 | 5.4, 5.6 | dispatch.py: `_format_plan_response` summary |
| 4.1 | 3.2 | Plan JSON schema |
| 4.2 | 3.2, 5.6 | `json.dumps(indent=2)` formatting |
| 4.3 | 3.2, 5.6 | `_format_plan_response` adds `total`/`completed`/`skipped` |
| 5.1 | 4.5 | tools.py: `TOOL_SCHEMAS`, `get_tool_schemas()` |
| 5.2 | 4.1, 4.2, 4.3, 4.4 | tools.py: schema structure |
| 5.3 | 4.1 | tools.py: `plan_create` schema `steps` param |
| 5.4 | 4.2 | tools.py: `plan_step_done` schema `step_index` param |
| 6.1 | 5.1 | dispatch.py: `_handle_plan_create` uses `vm.write()` |
| 6.2 | 5.2, 5.3 | dispatch.py: `_handle_plan_step_done`/`_skip` read-modify-write |
| 6.3 | 5.4 | dispatch.py: `_handle_plan_status` uses `vm.read()` |
| 6.4 | 5.1, 5.2, 5.3, 5.4 | Error handling returns JSON error objects |
| 6.5 | 5.7 | dispatch.py: `DISPATCH_MAP` registration |
| 7.1 | 11.1 | No filesystem I/O when tools unused |
| 7.2 | 11.1 | No initialization beyond schema inclusion |
| 7.3 | 11.1 | `.plan/` directory only created by `plan_create` |
| 8.1 | 6.2, 6.3 | loop.py: checkpoint reads plan from VM |
| 8.2 | 6.4 | loop.py: checkpoint unchanged when no plan |
| 8.3 | 6.3 | loop.py: formatted numbered list in checkpoint |
| 9.1 | 7.2, 7.4 | verify.py + loop.py: plan status in verification |
| 9.2 | 7.3 | Incomplete steps trigger review instruction |
| 9.3 | 7.2 | Empty plan_status parameter = no change |
| 10.1 | 8.1 | On-disk state survives micro-compact |
| 10.2 | 8.1 | On-disk state survives auto-compact |
| 10.3 | 8.2 | `plan_status` returns same state after compression |
| 11.1 | 4.5 | tools.py: schemas added to existing list |
| 11.2 | 5.7 | dispatch.py: handlers in existing module |
| 11.3 | 6.1, 7.4 | loop.py: integration in existing module |
| 11.4 | all | No new Python files created |
| 12.1 | 10 | dispatch.py: `log.info` on plan_create |
| 12.2 | 10 | dispatch.py: `log.info` on plan_step_done |
| 12.3 | 10 | dispatch.py: `log.info` on plan_status |
| 12.4 | 10 | loop.py: `log.info` on checkpoint plan injection |
| 13.1 | 11.2 | Only count assertions need updating |
| 13.2 | 11.3 | Tests use existing mock VM pattern |
| 13.3 | 4.5 | `get_tool_schemas()` returns plan tools for all runtimes |
| 14.1 | 9.1 | `plan_create` complements "build a COMPLETE step list" |
| 14.2 | 9.1 | `plan_status` complements "review your plan" instruction |
| 14.3 | 9.2 | Plan status available during process completeness audit |
| 15.1 | 5.3 | dispatch.py: `_handle_plan_step_skip` updates status to `"skipped"` |
| 15.2 | 5.3 | dispatch.py: `_handle_plan_step_skip` returns updated plan with skip_reason |
| 15.3 | 5.3 | dispatch.py: `_handle_plan_step_skip` validates index range |
| 15.4 | 5.3 | dispatch.py: `_handle_plan_step_skip` returns error when no plan exists |
| 15.5 | 3.4, 5.6 | `_format_plan_response` excludes skipped from incomplete count |
| 16.1 | 6.3 | loop.py: checkpoint suggests `plan_create` for revision |
| 16.2 | 6.3 | loop.py: checkpoint suggests `plan_step_skip` for blocked steps |
| 16.3 | 6.5 | loop.py: non-coercive language, model may continue current plan |
| 16.4 | 6.3 | loop.py: checkpoint suggests `report_completion` when all done |

## 13. Scope Estimation

| Component | Estimated Lines | Complexity |
|-----------|----------------|------------|
| tools.py: 4 schemas | ~75 | Low |
| dispatch.py: 4 handlers + 2 helpers + types + constant | ~160 | Medium |
| loop.py: checkpoint augmentation + 2 helpers | ~60 | Medium |
| verify.py: parameter + placeholder substitution | ~12 | Low |
| verification-frame SKILL.md: 1 placeholder | ~2 | Low |
| test_tools.py: updated counts + plan schema tests | ~40 | Low |
| test_dispatch.py: plan handler tests (4 handlers) | ~140 | Medium |
| test_verify.py: plan_status parameter tests | ~25 | Low |
| **Total production code** | **~310** | |
| **Total test code** | **~205** | |

## 14. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `vm.read()` response format differs between Mini and PCM runtimes | Low | High | Both runtimes return protobuf messages with `MessageToDict` compatibility. Verify with both mock patterns in tests. |
| `vm.write()` does not auto-create `.plan/` directory on Mini runtime | Low | Medium | Verify during implementation. If needed, add an explicit `vm.mkdir(".plan")` before `vm.write()` (Mini does not support mkdir, so this applies only to PCM). Alternatively, the model can only use plan tools on PCM runtime. Investigation required during Task 1. |
| Existing test assertions on TOOL_SCHEMAS/TOOL_NAMES count break | Certain | Low | Update count assertions from 9 to 13 and add plan tool names to `EXPECTED_TOOL_NAMES`. This is a known, trivial change. |
| Plan file corruption if JSON parsing fails mid-read-modify-write | Very Low | Medium | `_handle_plan_step_done` and `_handle_plan_step_skip` validate parsed JSON structure before writing. On parse error, return error JSON without writing. |
| Weak models ignore plan tools entirely | Medium | Low | Plan tools are opt-in. The replan checkpoint and verification injection provide passive benefit even without explicit `plan_create` usage. Future iteration: consider auto-prompting plan creation. |
| `NotRequired` from typing requires Python 3.11+ | Low | Low | The project already targets Python 3.11+ (verified from existing type annotations). If needed, fall back to `typing_extensions.NotRequired`. |
| Checkpoint revision guidance is too verbose for weak models | Low | Medium | Guidance is kept to 3 short lines. The model is not required to act on it. Monitor benchmark results and simplify if needed. |
