# Design: agent-observability

> Minimal observability integration: register LiteLLM callbacks for Langfuse, optionally group traces per task via metadata, zero changes to core agent logic.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Component Design](#2-component-design)
3. [Data Flow](#3-data-flow)
4. [Configuration](#4-configuration)
5. [Requirements Traceability](#5-requirements-traceability)

---

## 1. Architecture Overview

The integration adds a single initialization function that conditionally registers Langfuse as a LiteLLM callback. All tracing happens automatically via LiteLLM's built-in callback mechanism -- no custom observability classes, no new packages, no span hierarchies.

```
main.py
  |
  |  (1) import & call configure_observability()
  |       -> checks env vars, registers litellm callbacks
  |
  |  (2) for each task: run_agent(...)
  |       -> call_llm() -> litellm.completion() -> Langfuse callback fires automatically
  |
  |  No changes to agent/llm.py, agent/loop.py, or any other agent module.
  |
  +-- Langfuse (receives traces via async callback, zero overhead if unconfigured)
```

**Key design decisions**:

- **Callback-only approach**: `litellm.success_callback = ["langfuse"]` and `litellm.failure_callback = ["langfuse"]` capture every LLM call automatically. No decorator, no context threading.
- **Metadata-based trace grouping (optional enhancement)**: To group LLM calls per task, `main.py` passes a `metadata` dict with `trace_id`, `session_id`, and `trace_name` to `litellm.completion()` via a module-level variable or by extending `call_llm()`. This is the optional part -- if skipped, each LLM call appears as an independent trace in Langfuse (still fully useful).
- **No `@observe()` decorator**: The Langfuse `@observe()` decorator does NOT automatically group litellm callback-generated traces (upstream issue langfuse/langfuse#2238). Using it would add complexity with no benefit. Metadata-based grouping is simpler and actually works.

---

## 2. Component Design

### 2.1 New File: `sandbox/py/agent/observability.py`

A single file with one public function. This is NOT a package -- just one flat module.

**Function**: `configure_observability() -> None`

Responsibilities:
- Check if `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set in the environment
- If not set: return immediately (no-op, zero overhead)
- If set: attempt to `import langfuse`, handle `ImportError` gracefully (log warning, return)
- Register callbacks: `litellm.success_callback = ["langfuse"]` and `litellm.failure_callback = ["langfuse"]`
- Log that observability is active

**Interface**:

```python
def configure_observability() -> None:
    """Register Langfuse as LiteLLM callback if credentials are available.

    Activates automatically when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY
    are set. Silently no-ops when credentials are missing or langfuse
    is not installed.
    """
```

Estimated size: ~15 lines of logic.

### 2.2 Modified File: `sandbox/py/main.py`

Add two lines at the top of `main()`:

```python
from agent.observability import configure_observability
# ... at the start of main():
configure_observability()
```

No other changes to main.py.

### 2.3 Optional Enhancement: Per-Task Trace Grouping

If per-task trace grouping is desired (requirement 2), the minimal approach is to pass metadata to `litellm.completion()`. This requires a small change to `call_llm()` to accept and forward an optional `metadata` parameter:

**Modified function signature in `agent/llm.py`**:

```python
def call_llm(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
    metadata: dict[str, str] | None = None,  # NEW: optional Langfuse metadata
) -> LLMResponse:
```

The metadata dict is forwarded to `litellm.completion(**kwargs)` as `kwargs["metadata"] = metadata`.

**Call site in `agent/loop.py`** passes metadata per task:

```python
import uuid
trace_metadata = {
    "trace_id": str(uuid.uuid4()),
    "trace_name": f"run_agent",
    "session_id": os.environ.get("SESSION_ID", ""),
    "trace_metadata": {"model": executor_model, "task": task_text[:200]},
}
# ... in the loop:
response = call_llm(executor_model, messages, tools=TOOL_SCHEMAS, metadata=trace_metadata)
```

This groups all LLM calls for one `run_agent()` invocation under a single Langfuse trace.

**Note**: This optional enhancement touches `llm.py` and `loop.py` but only adds a pass-through parameter. If the team prefers zero changes to existing files, the callback-only approach (section 2.1 + 2.2) still delivers per-call tracing with token/cost/latency data -- just without per-task grouping.

### 2.4 New File: `docs/observability-research.md`

A research document evaluating 10+ LLM observability tools. Content is already drafted in `requirements.md` section "Observability Tool Landscape" and will be expanded into a standalone document with:
- Comparison matrix (integration simplicity, self-hosting, license, community)
- Per-tool evaluation (callback name, free data, strengths/weaknesses)
- Recommendation and rationale
- Migration notes for the strongest alternative (Arize Phoenix)

### 2.5 Modified File: `sandbox/py/pyproject.toml`

Add a new dependency group:

```toml
[dependency-groups]
dev = ["pytest>=9.0.2"]
observability = ["langfuse>=2.0.0"]
```

Installed via `uv sync --group observability`. When not installed, `configure_observability()` catches `ImportError` and no-ops.

### 2.6 Modified File: `sandbox/py/.env.example`

Append a new section:

```
# =============================================================================
# Observability (optional -- Langfuse)
# =============================================================================
# Set these to enable automatic LLM call tracing via Langfuse.
# When unset, the agent runs with zero observability overhead.
#
# LANGFUSE_PUBLIC_KEY=pk-lf-...
# LANGFUSE_SECRET_KEY=sk-lf-...
# LANGFUSE_HOST=https://cloud.langfuse.com  # or self-hosted URL
# SESSION_ID=                                # optional: groups multiple task runs
```

---

## 3. Data Flow

```
main.py::main()
  |
  | configure_observability()
  |   -> checks LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY
  |   -> if present: litellm.success_callback = ["langfuse"]
  |                  litellm.failure_callback = ["langfuse"]
  |   -> if absent:  return (no-op)
  |
  | for each task:
  |   run_agent(executor_model, harness_url, task_text, ...)
  |     |
  |     | call_llm(model, messages, tools, metadata=trace_metadata)
  |     |   -> litellm.completion(**kwargs)
  |     |       -> Langfuse callback fires (async, non-blocking)
  |     |           -> sends: model, messages, tokens, cost, latency, status
  |     |           -> groups by trace_id if metadata provided
  |     |
  |     | (repeat for each step in the executor loop)
  |
  +-- Langfuse dashboard shows traces with full LLM call details
```

**Failure mode**: If Langfuse backend is unreachable, LiteLLM's callback mechanism handles errors internally -- callbacks are fire-and-forget and do not propagate exceptions to the caller. Agent execution continues unaffected.

---

## 4. Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LANGFUSE_PUBLIC_KEY` | No | (unset) | Langfuse public key. Observability activates only when set. |
| `LANGFUSE_SECRET_KEY` | No | (unset) | Langfuse secret key. |
| `LANGFUSE_HOST` | No | `https://cloud.langfuse.com` | Langfuse API host (for self-hosted deployments). |
| `SESSION_ID` | No | (empty) | Optional session ID for grouping multiple task runs. |

**Activation logic**: Observability is active if and only if both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set AND the `langfuse` package is installed. All other cases result in silent no-op.

---

## 5. Requirements Traceability

| Requirement | Design Component | Notes |
|-------------|-----------------|-------|
| 1.1 (callback registration at startup) | `configure_observability()` in `agent/observability.py`, called from `main.py::main()` | Registers before any LLM calls |
| 1.2 (automatic capture of all LLM calls) | LiteLLM's built-in `success_callback` mechanism | Zero changes to call sites |
| 1.3 (failure callback) | `litellm.failure_callback = ["langfuse"]` in `configure_observability()` | Records error type and request |
| 1.4 (no modifications to existing modules) | Callback-only approach; `configure_observability()` is a new file called from `main.py` | `llm.py` and `loop.py` unchanged for basic integration; optional metadata adds one parameter |
| 2.1 (single trace per run_agent) | Optional metadata-based grouping: shared `trace_id` passed to all `call_llm()` calls within one `run_agent()` | Requires optional `metadata` parameter on `call_llm()` |
| 2.2 (trace metadata) | `trace_metadata` dict includes model, task text, trace_id | Passed via `metadata` parameter |
| 2.3 (session grouping) | `SESSION_ID` env var mapped to `session_id` in metadata | Optional, empty string if unset |
| 2.4 (minimal grouping mechanism) | Metadata-based approach (option b): passing `trace_id` via `metadata` to `litellm.completion()` | Chosen over `@observe()` because the decorator does not auto-group litellm callback traces |
| 3.1 (env-var activation) | `configure_observability()` checks `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` | No feature flags needed |
| 3.2 (silent skip when unconfigured) | Early return in `configure_observability()` when env vars unset | Zero overhead path |
| 3.3 (graceful degradation) | LiteLLM callbacks are async/fire-and-forget; failures do not propagate | Built-in LiteLLM behavior |
| 3.4 (.env.example documentation) | New section in `.env.example` | Documents all observability env vars |
| 4.1 (research document) | `docs/observability-research.md` | Evaluates 10+ tools |
| 4.2 (per-tool evaluation) | Research doc includes callback name, free data, self-hosting, license, strengths/weaknesses | Structured comparison |
| 4.3 (comparison matrix) | Research doc includes ranking matrix | Integration simplicity, self-hosting, community |
| 4.4 (recommendation) | Research doc concludes with Langfuse recommendation + Arize Phoenix alternative | With rationale |
| 5.1 (optional dependency group) | `[dependency-groups] observability = ["langfuse>=2.0.0"]` in pyproject.toml | `uv sync --group observability` |
| 5.2 (ImportError handling) | `configure_observability()` catches `ImportError` on `import langfuse` | Falls back to no-op |
| 5.3 (async telemetry) | Langfuse + LiteLLM callbacks are async by default | Non-blocking, no added latency |
