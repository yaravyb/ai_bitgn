# Requirements: persistent-task-planner

> Initialized: 2026-03-25T18:00:00Z
> Status: requirements-generated

## Problem Statement

The agent framework suffers from two related problems with weak models (observed with openai.gpt-oss-120b at 47% score):

1. **Cycling after context compression**: After micro-compact or auto-compact, weak models forget what they already did and re-read the same files in infinite loops. Benchmark tasks t18, t19, t20 show the model reading `docs/inbox-task-processing.md` 7-8 times in 30 steps.

2. **Planning gap**: Task t17 shows the model completed 90% of the work (wrote an email correctly) but forgot to update `outbox/seq.json` because it never created a plan that included all required steps.

Both problems share a root cause: the model's plan exists only in conversation messages, which are lost or summarized during context compression. The execution-discipline skill already instructs "Plan Before Acting" but the plan is ephemeral.

### Solution Overview

Add persistent task planning tools (`plan_create`, `plan_step_done`, `plan_step_skip`, `plan_status`) that store the execution plan as a JSON file on disk (`.plan/steps.json`). The plan survives context compression, enabling the model to reorient by reading its plan after compaction. Plans are also revisable — the model can skip steps that turn out to be unnecessary, or call `plan_create` again to completely revise the plan when the approach is wrong. The replan checkpoint (Point E) suggests plan revision when the model is stuck. Inspired by the s07_task_system.py reference agent pattern of "state that survives compression -- because it's outside the conversation."

## Requirements

### 1. Plan Creation Tool

**Description**: The agent shall provide a `plan_create` tool that allows the model to decompose a task into discrete steps stored on disk.

**Acceptance Criteria**:
- When the model calls `plan_create` with a `steps` parameter (array of strings), the agent shall create a `.plan/steps.json` file on the sandbox filesystem containing each step with a `pending` status.
- When `plan_create` is called, the agent shall return the created plan as a JSON object showing all steps and their statuses.
- When `plan_create` is called and a `.plan/steps.json` file already exists, the agent shall overwrite the existing plan with the new one (single plan per agent run).
- When `plan_create` is called with an empty steps array, the agent shall return an error indicating that at least one step is required.

### 2. Step Completion Tool

**Description**: The agent shall provide a `plan_step_done` tool that allows the model to mark individual steps as completed during execution.

**Acceptance Criteria**:
- When the model calls `plan_step_done` with a `step_index` parameter (0-based integer), the agent shall update the corresponding step's status to `done` in `.plan/steps.json`.
- When `plan_step_done` is called, the agent shall return the updated plan showing all steps and their current completion status.
- When `plan_step_done` is called with a `step_index` that is out of range, the agent shall return an error indicating the valid index range.
- When `plan_step_done` is called and no plan exists (`.plan/steps.json` is missing), the agent shall return an error indicating that no plan has been created yet.

### 3. Plan Status Tool

**Description**: The agent shall provide a `plan_status` tool that allows the model to read its current plan state at any time, particularly after context compression.

**Acceptance Criteria**:
- When the model calls `plan_status` (no parameters required), the agent shall return the full plan from `.plan/steps.json` showing all steps and their completion status.
- When `plan_status` is called and no plan exists, the agent shall return a message indicating that no plan has been created yet.
- When the plan is returned, the agent shall include a summary line showing the count of completed steps versus total steps (e.g., "3/5 steps completed").

### 4. Plan Schema Structure

**Description**: The plan JSON file shall use a simple, flat schema that is easy for weak models to parse after context compression.

**Acceptance Criteria**:
- When a plan is created, the `.plan/steps.json` file shall contain a JSON object with a `steps` array where each element has `index` (integer), `description` (string), and `status` (string: `pending`, `done`, or `skipped`).
- When a plan is stored on disk, the JSON file shall be human-readable (indented formatting) so it is easy for the model to parse from a `read_file` response.
- When a plan is read or returned by any plan tool, the response shall include a top-level `total` count and `completed` count alongside the `steps` array.

### 5. Tool Schema Registration

**Description**: The plan tool schemas shall be registered alongside existing tool schemas in `tools.py` following the same OpenAI-compatible function calling format.

**Acceptance Criteria**:
- When the agent initializes its tool list, the `plan_create`, `plan_step_done`, `plan_step_skip`, and `plan_status` tool schemas shall be included in the tool schemas returned by `get_tool_schemas()`.
- When tool schemas are defined, the plan tools shall follow the same schema structure as existing tools (type, function, name, description, parameters with required fields).
- When the `plan_create` schema is defined, the `steps` parameter shall be typed as an array of strings with a description explaining its purpose.
- When the `plan_step_done` schema is defined, the `step_index` parameter shall be typed as an integer with a description explaining the 0-based indexing.

### 6. Tool Dispatch Handlers

**Description**: The plan tool dispatch handlers shall be added to `dispatch.py` following the existing handler pattern, without creating new Python modules.

**Acceptance Criteria**:
- When a `plan_create` tool call is dispatched, the handler shall write the plan file to `.plan/steps.json` on the sandbox VM filesystem using the existing `vm.write()` method.
- When a `plan_step_done` tool call is dispatched, the handler shall read the current plan from `.plan/steps.json` using `vm.read()`, update the specified step, and write the updated plan back using `vm.write()`.
- When a `plan_status` tool call is dispatched, the handler shall read and return the current plan from `.plan/steps.json` using `vm.read()`.
- When any plan tool handler encounters a filesystem error (e.g., file not found for `plan_step_done`), it shall return a JSON error object consistent with other tool error responses.
- When plan tool handlers are registered, they shall be added to the `DISPATCH_MAP` dictionary alongside existing handlers.

### 7. Zero Overhead for Strong Models

**Description**: The plan tools shall add zero processing overhead when the model does not use them.

**Acceptance Criteria**:
- When the model does not call any plan tools during execution, no additional filesystem reads, writes, or LLM calls shall occur related to planning.
- When plan tools are registered in the tool schemas, they shall not require any initialization or setup beyond schema inclusion (no pre-created directories or files).
- When the model completes a task without creating a plan, the `.plan/` directory shall not exist on the sandbox filesystem.

### 8. Resilience Integration -- Replan Checkpoint

**Description**: The replan checkpoint mechanism (Point E in loop.py) shall read the plan from disk and include pending steps in the checkpoint message when a plan exists.

**Acceptance Criteria**:
- When a replan checkpoint is triggered (by repetition detection or stall interval) and a `.plan/steps.json` file exists on the sandbox filesystem, the checkpoint message shall include the list of pending (incomplete) steps from the plan.
- When a replan checkpoint is triggered and no plan exists on the sandbox filesystem, the checkpoint message shall behave as it does today (no plan-related content).
- When plan steps are included in the checkpoint message, they shall be formatted as a numbered list showing which steps are done and which are pending, so the model can reorient.

### 9. Pre-Completion Plan Review

**Description**: Before the model calls `report_completion`, the verification mechanism shall reference the plan to check that all steps are completed.

**Acceptance Criteria**:
- When verification is enabled and a plan exists at the time `report_completion` is called, the verification prompt shall include the plan status showing any incomplete steps.
- When the verification prompt includes incomplete plan steps, it shall instruct the model to either complete the missing steps or confirm they are not needed before re-submitting.
- When no plan exists at the time of verification, the verification prompt shall behave as it does today (no plan-related content).

### 10. Plan Survives Context Compression

**Description**: The plan state shall persist through all forms of context compression (micro-compact, auto-compact, manual compact) because it is stored on disk, not in conversation messages.

**Acceptance Criteria**:
- When micro-compact removes older conversation batches, the plan on disk shall remain intact and readable via `plan_status`.
- When auto-compact summarizes the full conversation, the plan on disk shall remain intact and readable via `plan_status`.
- When the model calls `plan_status` after any form of context compression, it shall receive the same plan state that existed before compression.

### 11. No New Python Modules

**Description**: All plan tool code shall be added to existing modules without creating new Python files, consistent with the project's architectural constraints.

**Acceptance Criteria**:
- When plan tool schemas are added, they shall be defined in `sandbox-py/agent/tools.py`.
- When plan tool dispatch handlers are added, they shall be defined in `sandbox-py/agent/dispatch.py`.
- When resilience integration code is added, it shall be defined in `sandbox-py/agent/loop.py`.
- When the persistent-task-planner feature is implemented, no new Python files shall be created in the `sandbox-py/agent/` directory.

### 12. Observability and Logging

**Description**: All plan tool operations shall be logged for debugging and benchmark analysis.

**Acceptance Criteria**:
- When `plan_create` is called, the agent shall log an info-level message including the number of steps created.
- When `plan_step_done` is called, the agent shall log an info-level message including the step index and description of the completed step.
- When `plan_status` is called after context compression, the agent shall log an info-level message noting the post-compression plan read with the completed/total count.
- When a replan checkpoint includes plan data, the agent shall log an info-level message indicating that plan steps were included in the checkpoint.

### 13. Existing Test Compatibility

**Description**: All plan tool changes shall maintain backward compatibility with the existing test suite and codebase.

**Acceptance Criteria**:
- When the existing test suite is executed after plan tool changes, all previously passing tests shall continue to pass without modification.
- When plan tools are tested, the tests shall use the existing VM mock pattern to simulate filesystem operations without requiring an actual sandbox VM.
- When `get_tool_schemas()` is called with the existing runtime types, the returned schemas shall include plan tools alongside the existing tools.

### 14. Skill Alignment

**Description**: The execution-discipline skill's "Plan Before Acting" instruction shall be complemented by the persistent plan tools, creating a natural integration between skill guidance and tool capability.

**Acceptance Criteria**:
- When the execution-discipline skill instructs the model to "build a COMPLETE step list", the model shall have `plan_create` available to persist that step list.
- When the execution-discipline skill instructs the model to "review your plan and confirm every step was completed" before calling `report_completion`, the model shall have `plan_status` available to retrieve the plan.
- When the self-verification skill performs a "Process completeness audit", the plan status shall be available as a reference for checking whether all required procedures were completed.

### 15. Plan Step Skip Tool

**Description**: The agent shall provide a `plan_step_skip` tool that allows the model to mark individual steps as skipped when they turn out to be unnecessary or impossible, without recreating the entire plan.

**Acceptance Criteria**:
- When the model calls `plan_step_skip` with a `step_index` parameter (0-based integer) and an optional `reason` parameter (string), the agent shall update the corresponding step's status to `skipped` in `.plan/steps.json`.
- When `plan_step_skip` is called, the agent shall return the updated plan showing all steps and their current statuses, with the skipped step's reason included.
- When `plan_step_skip` is called with a `step_index` that is out of range, the agent shall return an error indicating the valid index range.
- When `plan_step_skip` is called and no plan exists, the agent shall return an error indicating that no plan has been created yet.
- When a step is skipped, it shall not count as incomplete in the plan summary (e.g., a plan with 3 done, 1 skipped, 1 pending shows "3/4 actionable steps completed, 1 skipped").

### 16. Replan Checkpoint Plan Revision Guidance

**Description**: When the replan checkpoint fires and a plan exists with pending steps, the checkpoint message shall suggest that the model can revise its plan.

**Acceptance Criteria**:
- When a replan checkpoint is triggered and a plan exists with pending steps, the checkpoint message shall include guidance suggesting the model can call `plan_create` to create a revised plan if the current approach is not working.
- When a replan checkpoint is triggered and a plan exists with pending steps, the checkpoint message shall include guidance suggesting the model can call `plan_step_skip` to skip steps that are unnecessary or blocked.
- When the checkpoint suggests plan revision, it shall not force the model to revise — the model may choose to continue with the existing plan if it determines the plan is still viable.
- When a replan checkpoint is triggered and all plan steps are completed (none pending), the checkpoint message shall suggest calling `report_completion` since the plan is fully executed.
