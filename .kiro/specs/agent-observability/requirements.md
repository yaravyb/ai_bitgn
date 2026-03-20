# Requirements: agent-observability

> Add minimal LLM observability to the sandbox agents using LiteLLM's native callback mechanism -- maximum visibility with minimum code changes. No custom observability classes, no new packages, no deep span hierarchies.

## Status: Generated

## Context

Current state: The agent (`sandbox/py/agent/`) uses LiteLLM for provider-agnostic LLM access via `litellm.completion()` in `agent/llm.py`. There is currently no tracing, no token/cost tracking, and no way to visualize agent execution flows. The agent uses `print()` statements and Python `logging` for console output (the `print()` to `logging` migration is explicitly out of scope for this spec).

Goal: Add observability with the **smallest possible code footprint** by leveraging LiteLLM's built-in callback support. The ideal integration is a few lines of callback registration that automatically captures every LLM call, plus optionally a single decorator on `run_agent()` to group all calls for one task into a single trace.

### Observability Tool Landscape (Deep Research)

The following tools were evaluated for their LiteLLM integration simplicity, self-hosting options, and what you get for free versus what requires manual instrumentation.

#### Tier 1: Native LiteLLM `success_callback` support (1-2 lines of code)

These tools can be activated by setting `litellm.success_callback = ["<name>"]` and environment variables -- zero changes to LLM call sites:

| Tool | Callback Name | License | Self-Host | What You Get for Free | What Requires Extra Work |
|------|--------------|---------|-----------|----------------------|--------------------------|
| **Langfuse** | `"langfuse"` or `"langfuse_otel"` | MIT (core) | Yes (Docker Compose, K8s) | Model, messages, token usage, cost, latency, finish reason, errors per LLM call; trace UI with timeline | Trace grouping across calls requires passing `trace_id`/`session_id` in metadata; deeper span nesting requires `@observe()` decorator or manual `existing_trace_id` |
| **Arize Phoenix** | `"arize_phoenix"` | Apache 2.0 (fully open) | Yes (Docker, local, notebook) | Per-call tracing, token usage, latency; no feature gates | Requires OTel SDK dependencies; trace grouping less mature than Langfuse |
| **Lunary** | `"lunary"` | MIT | Yes (Docker) | Per-call logging, token usage, cost | Smaller community; less LiteLLM-specific documentation |
| **Opik (Comet)** | `"opik"` | Apache 2.0 | Yes (Docker, K8s) | Per-call tracing, evaluation framework | Self-host lacks user management; Kubernetes for production |
| **Helicone** | `"helicone"` | Apache 2.0 | Yes (Docker) | Per-call logging, cost tracking, caching, rate limiting | Proxy-based approach (URL rewriting) is alternative to callback |
| **LangSmith** | `"langsmith"` | Proprietary (cloud) | No (cloud only) | Deep LangChain integration, tracing, evaluation | Not open source; no self-hosting; vendor lock-in |
| **Braintrust** | `"braintrust"` | Proprietary | No | Auto-tracing, cost tracking, evaluation | Cloud-only; no self-hosting |
| **AgentOps** | `"agentops"` | MIT | No (cloud only) | Per-call tracing, cost tracking | Cloud-only; limited callback control |
| **W&B Weave** | `"wandb"` | Proprietary | No | Auto-tracing via `weave.init()`, experiment tracking | Cloud-only; heavier dependency footprint |
| **MLflow** | `"mlflow"` | Apache 2.0 | Yes | Experiment tracking, model registry | General-purpose MLOps; LLM tracing UI less polished |
| **Logfire (Pydantic)** | `"logfire"` | Apache 2.0 | No | OpenTelemetry-native, structured logging | Cloud-only dashboard; newer/smaller community |

#### Tier 2: OpenTelemetry auto-instrumentation (alternative approach)

| Tool | Approach | Notes |
|------|----------|-------|
| **OpenLLMetry (Traceloop)** | `Traceloop.init()` auto-instruments LiteLLM via OTel | Backend-agnostic (sends to any OTel collector); Apache 2.0; ~2 lines of code; no vendor lock-in but requires choosing a separate backend for visualization |

#### Recommendation

**Langfuse** is the recommended tool for this integration based on:

1. **Simplest meaningful integration**: `litellm.success_callback = ["langfuse"]` + 3 env vars gives you per-call tracing with token/cost/latency tracking and a full trace UI -- zero changes to existing call sites.
2. **Optional trace grouping**: Adding a single `@observe()` decorator on `run_agent()` groups all LLM calls for one task under a single trace, with `propagate_attributes()` for metadata (session, tags, model). Alternatively, passing `metadata={"trace_id": ..., "session_id": ...}` to `litellm.completion()` achieves the same grouping without the decorator.
3. **Self-hosting**: MIT-licensed core, Docker Compose deployment, no feature gates on tracing/eval.
4. **Future flexibility**: `"langfuse_otel"` callback sends data via OpenTelemetry, making it easy to swap backends later.
5. **Largest LiteLLM community**: Most documentation, examples, and GitHub activity for the LiteLLM + Langfuse combination.

**Alternative worth noting**: Arize Phoenix (Apache 2.0, fully open, zero feature gates) is the strongest runner-up. If Langfuse's MIT + enterprise licensing model becomes a concern, Phoenix can be swapped in with minimal changes (`"arize_phoenix"` callback).

---

## Requirement 1: Automatic LLM Call Tracing via Callback

Every LLM call made through LiteLLM must be automatically traced and sent to the observability backend with zero modifications to existing call sites.

### Acceptance Criteria

1. **The agent shall** register the chosen observability tool as a LiteLLM callback (e.g., `litellm.success_callback = ["langfuse"]` and `litellm.failure_callback = ["langfuse"]`) during startup, before any LLM calls are made.
2. **Every call to `litellm.completion()` shall** be automatically captured by the callback, recording: model name, input messages, output content, tool calls returned, token usage (prompt, completion, total), estimated cost, latency, and completion status (success or error).
3. **When** an LLM call fails, **the failure callback shall** record the error type, error message, and the request that caused it.
4. **The callback registration shall** require no modifications to `agent/llm.py`, `agent/loop.py`, or any other existing agent module -- only a new initialization step at startup.

---

## Requirement 2: Per-Task Trace Grouping and Metadata

LLM calls belonging to the same agent task execution must be grouped under a single trace with meaningful metadata for filtering and analysis.

### Acceptance Criteria

1. **Each `run_agent()` invocation shall** produce a single top-level trace in the observability backend that groups all LLM calls made during that task execution.
2. **Each trace shall** include the following metadata: (a) executor model identifier, (b) task instruction text (or a truncated summary), (c) a unique trace ID for the execution.
3. **When** session-level grouping is desired, **the trace shall** support a session ID (passable via environment variable or function parameter) that groups multiple task executions within a single benchmark run.
4. **The trace grouping mechanism shall** use one of the following minimal approaches: (a) a single `@observe()` decorator on `run_agent()`, or (b) passing a shared `trace_id` via the `metadata` parameter to `litellm.completion()` calls -- whichever requires fewer code changes.

---

## Requirement 3: Configuration and Graceful Degradation

The observability integration must be activated purely via environment variables and must never interfere with normal agent operation.

### Acceptance Criteria

1. **The observability system shall** be activated by setting the backend's credential environment variables (e.g., `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`); no code changes or feature flags required.
2. **When** the credential environment variables are not set, **the agent shall** skip callback registration entirely and operate with zero observability overhead -- no warnings, no errors, no attempted connections.
3. **When** the observability backend is unavailable or unreachable at runtime, **the agent shall** continue executing normally without errors or performance degradation; telemetry delivery failures must not propagate to the agent's main logic.
4. **The `.env.example` file shall** document all observability-related environment variables with descriptions and example values, including the self-hosted backend URL variable (e.g., `LANGFUSE_HOST`).

---

## Requirement 4: Observability Tool Research Documentation

The project must include a documented analysis of the LLM observability tool landscape to justify the chosen solution and serve as a reference for future reevaluation.

### Acceptance Criteria

1. **The project shall** include a research document (`docs/observability-research.md`) that evaluates at least eight LLM observability tools that integrate with LiteLLM.
2. **For each evaluated tool, the research document shall** include: (a) tool name, (b) LiteLLM integration method and callback name, (c) what data is automatically captured for free, (d) self-hosting availability and method, (e) license, (f) notable strengths and weaknesses.
3. **The research document shall** include a comparison matrix ranking tools by: integration simplicity (lines of code), free-tier capabilities, self-hosting options, and community/documentation maturity.
4. **The research document shall** conclude with a recommendation, rationale, and a note on the strongest alternative for future migration.

---

## Requirement 5: Minimal Dependency Footprint

The observability integration must not burden the project with heavy or required dependencies.

### Acceptance Criteria

1. **The observability library (e.g., `langfuse`) shall** be declared as an optional dependency group (e.g., `pip install .[observability]` or `uv sync --group observability`), not a required dependency.
2. **When** the observability dependency is not installed, **importing and running the agent shall** succeed without errors -- the callback registration step must handle `ImportError` gracefully.
3. **The observability integration shall** send telemetry asynchronously (non-blocking) and must not add perceptible latency to LLM calls or tool dispatch operations.
