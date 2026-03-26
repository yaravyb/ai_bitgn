# Tasks: persistent-task-planner

> Generated: 2026-03-25
> Status: pending approval

## Task 1 (P): Add plan tool schemas to tools.py [x]

**Requirements**: 5, 7

Append four OpenAI-compatible tool schemas (`plan_create`, `plan_step_done`, `plan_step_skip`, `plan_status`) to the `TOOL_SCHEMAS` list in `sandbox-py/agent/tools.py`. Each schema follows the identical structure used by existing tools. The `plan_create` schema declares a required `steps` parameter typed as an array of strings. The `plan_step_done` schema declares a required `step_index` parameter typed as an integer with a description explaining 0-based indexing. The `plan_step_skip` schema declares a required `step_index` integer and an optional `reason` string. The `plan_status` schema has no parameters. After adding the schemas, `TOOL_SCHEMAS` grows from 9 to 13, and `TOOL_NAMES` automatically includes the four new names. Verify that `get_tool_schemas("mini")` returns 13 and `get_tool_schemas("pcm")` returns 16. The `SCOUT_TOOL_SCHEMAS` set is unaffected because it is filtered by `_SCOUT_TOOL_NAMES`.

## Task 2 (P): Add plan type definitions, constant, and helper functions to dispatch.py [x]

**Requirements**: 4, 11

Add a module-level constant `_PLAN_FILE: str = ".plan/steps.json"` and two module-private TypedDict classes (`_PlanStep` with fields `index`, `description`, `status`, and `NotRequired` field `skip_reason`; `_PlanData` with fields `steps`, `total`, `completed`, `skipped`) to `sandbox-py/agent/dispatch.py`. Also add two helper functions: `_read_plan(vm)` that reads and parses the plan JSON file from the VM using `vm.read()` and `MessageToDict`, returning `(plan_data, None)` on success or `(None, error_json)` on failure; and `_format_plan_response(plan)` that computes the summary string (adapting denominator when skipped steps exist per Requirement 15.5), adds it to the plan dict, and serializes to indented JSON. These helpers are shared by all four dispatch handlers.

## Task 3: Implement plan_create and plan_status dispatch handlers [x]

**Requirements**: 1, 3, 6, 12

**Depends on**: Task 2

Add `_handle_plan_create` and `_handle_plan_status` to `sandbox-py/agent/dispatch.py`. `_handle_plan_create` extracts the `steps` array from args, rejects empty arrays with an error JSON, builds the plan data structure with each step set to `pending`, writes to `.plan/steps.json` via `vm.write()`, logs an info message with the step count, and returns the plan via `_format_plan_response`. `_handle_plan_status` calls `_read_plan`, returns a friendly "no plan yet" message when no file exists, logs an info message with the completion count, and returns the plan via `_format_plan_response`. Register both handlers in `DISPATCH_MAP`.

## Task 4: Implement plan_step_done and plan_step_skip dispatch handlers [x]

**Requirements**: 2, 15, 6, 12

**Depends on**: Task 3

Add `_handle_plan_step_done` and `_handle_plan_step_skip` to `sandbox-py/agent/dispatch.py`. Both use the read-modify-write pattern: call `_read_plan`, validate `step_index` is in range (return error JSON if not), update the step status (`done` or `skipped`), handle `skip_reason` for skipped steps, recompute `completed` and `skipped` counts, write back via `vm.write()`, log an info message, and return via `_format_plan_response`. `_handle_plan_step_done` removes any existing `skip_reason` if the step was previously skipped. Both return error JSON when no plan exists. Register both handlers in `DISPATCH_MAP`.

## Task 5: Integrate plan status into replan checkpoint in loop.py [x]

**Requirements**: 8, 10, 16

**Depends on**: Task 3

Add a `_read_plan_for_checkpoint(vm)` helper function to `sandbox-py/agent/loop.py` that reads `.plan/steps.json` from the VM, catches `ConnectError` (file not found) and returns `None`, and formats the plan as a numbered list inside `<plan-status>` tags showing `[DONE]`, `[PENDING]`, and `[SKIPPED]` markers. When pending steps exist, append revision guidance suggesting `plan_create` for replanning and `plan_step_skip` for blocked steps, using non-coercive language. When all steps are done, suggest calling `report_completion`. In the Point E replan checkpoint block, call this helper and inject the result before the closing `</checkpoint>` tag. Log an info message when plan steps are included. When no plan exists, the checkpoint behaves identically to its current behavior. The plan on disk is unaffected by context compression (micro-compact, auto-compact), ensuring the model can always reorient.

## Task 6: Integrate plan status into pre-completion verification [x]

**Requirements**: 9, 14

**Depends on**: Task 3

### Sub-tasks

- [x] 6.1. Add a `{{PLAN_STATUS_SECTION}}` placeholder to the `verification-frame` skill template in `sandbox-py/skills/verification-frame/SKILL.md`, placed after `{{SOURCE_BASENAME_SECTION}}` and before `## Instructions`.
- [x] 6.2. Add a `plan_status: str = ""` parameter to `build_verification_prompt` in `sandbox-py/agent/verify.py` and implement placeholder substitution (`{{PLAN_STATUS_SECTION}}` replaced with the value; empty string when no plan). Update the inline fallback frame path to include the plan status section when non-empty.
- [x] 6.3. Add a `_read_plan_for_verification(vm)` helper to `sandbox-py/agent/loop.py` that reads `.plan/steps.json`, returns empty string when no file exists, and formats incomplete steps with a heading and review instructions (or a brief "all completed" message).
- [x] 6.4. Wire `_read_plan_for_verification` at both verification interception points in `loop.py` (tool-call path and text-only path), passing the result as the `plan_status` argument to `build_verification_prompt`.

## Task 7: Update existing test assertions and add plan tool tests [x]

**Requirements**: 13

**Depends on**: Tasks 1, 3, 4

### Sub-tasks

- [x] 7.1. Update `EXPECTED_TOOL_NAMES` in `sandbox-py/tests/test_tools.py` to include `plan_create`, `plan_step_done`, `plan_step_skip`, and `plan_status`. Update count assertions from 9 to 13 for `TOOL_SCHEMAS` and `TOOL_NAMES`. Verify `get_tool_schemas("pcm")` count delta remains at 3.
- [x] 7.2. Add plan tool schema structure tests to `test_tools.py`: verify each schema has correct name, parameter types, and required fields.
- [x] 7.3. Add dispatch handler tests to `sandbox-py/tests/test_dispatch.py` using the existing mock VM pattern: `_handle_plan_create` writes and returns plan JSON; empty steps returns error; `_handle_plan_step_done` reads-updates-writes; invalid index returns error; no plan returns error; `_handle_plan_step_skip` with and without reason; summary counts adjust correctly for skipped steps; `_handle_plan_status` reads and returns plan; no plan returns friendly message; all four handlers registered in `DISPATCH_MAP`.
- [x] 7.4. Add verification prompt tests to `sandbox-py/tests/test_verify.py`: `build_verification_prompt` with `plan_status` parameter substitutes `{{PLAN_STATUS_SECTION}}`; empty `plan_status` produces no visible change; fallback frame includes plan status section when provided.
