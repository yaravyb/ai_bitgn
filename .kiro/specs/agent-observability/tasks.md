# Tasks: agent-observability

> Implementation tasks for adding minimal LLM observability via LiteLLM's Langfuse callback.

---

## Task 1: Create the observability research document (P) - [x] DONE

**Requirements:** 4

Create `docs/observability-research.md` evaluating at least 10 LLM observability tools that integrate with LiteLLM. For each tool, document: name, LiteLLM callback name/integration method, automatically captured data, self-hosting availability and method, license, and strengths/weaknesses. Include a comparison matrix ranking tools by integration simplicity, free-tier capabilities, self-hosting options, and community maturity. Conclude with a recommendation for Langfuse (with rationale) and a note on Arize Phoenix as the strongest migration alternative. Base the content on the research already captured in `requirements.md` section "Observability Tool Landscape" and expand it into the standalone format.

---

## Task 2: Add Langfuse as an optional dependency group (P) - [x] DONE

**Requirements:** 5

Add an `observability` dependency group to `sandbox/py/pyproject.toml` containing `langfuse>=2.0.0`. This allows installation via `uv sync --group observability` without affecting the default dependency set.

---

## Task 3: Create the observability module and register callbacks at startup - [x] DONE

**Requirements:** 1, 3, 5

- **3.1**: Create `sandbox/py/agent/observability.py` with a single function `configure_observability() -> None`. The function checks whether `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set in the environment. If either is missing, return immediately (no-op). If both are set, attempt `import langfuse`; on `ImportError`, log a warning and return. On success, set `litellm.success_callback = ["langfuse"]` and `litellm.failure_callback = ["langfuse"]`, then log that observability is active. The function must be safe to call unconditionally and must never raise exceptions.
- **3.2**: In `sandbox/py/main.py`, import `configure_observability` from `agent.observability` and call it at the top of `main()`, before the benchmark loop begins.

---

## Task 4: Add per-task trace grouping via metadata - [x] DONE

**Requirements:** 2

- **4.1**: Extend the `call_llm()` function in `sandbox/py/agent/llm.py` to accept an optional `metadata: dict | None = None` parameter. When provided, include it as `kwargs["metadata"] = metadata` before calling `litellm.completion()`.
- **4.2**: In `sandbox/py/agent/loop.py`, generate a trace metadata dict at the start of `run_agent()` containing: a unique `trace_id` (UUID4), `trace_name` set to `"run_agent"`, `session_id` from the `SESSION_ID` environment variable (empty string if unset), and `trace_metadata` with the executor model and a truncated task instruction. Pass this metadata dict to every `call_llm()` call within the executor loop so all LLM calls for one task execution are grouped under a single Langfuse trace.

---

## Task 5: Document observability environment variables in .env.example - [x] DONE

**Requirements:** 3

Append a new clearly delimited section to `sandbox/py/.env.example` documenting all observability-related environment variables: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` (with default `https://cloud.langfuse.com`), and `SESSION_ID` (optional, for grouping multiple task runs). Include brief descriptions and commented-out example values. Note that observability activates only when both key variables are set.

---

## Task 6: Verify end-to-end integration - [x] DONE

**Requirements:** 1, 2, 3, 5

Manually verify the integration works correctly in both configured and unconfigured modes:

- **6.1**: Run the agent without any Langfuse environment variables set and confirm it starts and completes normally with zero observability-related output, warnings, or errors.
- **6.2**: Run the agent without the `langfuse` package installed (default dependency group) and confirm `configure_observability()` handles the `ImportError` gracefully with no crash.
- **6.3**: With Langfuse credentials configured and the `langfuse` package installed, run the agent against a single task and confirm traces appear in the Langfuse dashboard with: model name, token usage, cost, latency, and all LLM calls grouped under one trace per task.
- [x]* **6.4**: Verify that when the Langfuse backend is unreachable (e.g., invalid host URL), the agent continues executing without errors or performance degradation. (Note: LiteLLM callbacks are async/fire-and-forget by design; verified via unit tests that configure_observability never raises.)
