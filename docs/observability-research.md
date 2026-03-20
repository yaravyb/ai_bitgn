# LLM Observability Tool Research

> Evaluation of 10+ LLM observability tools that integrate with LiteLLM, with a focus on integration simplicity, self-hosting options, and automatic data capture.

---

## Table of Contents

1. [Background](#background)
2. [Evaluation Criteria](#evaluation-criteria)
3. [Comparison Matrix](#comparison-matrix)
4. [Per-Tool Evaluation](#per-tool-evaluation)
5. [Recommendation](#recommendation)
6. [Migration Notes](#migration-notes)

---

## Background

The BitGN sandbox agent (`sandbox/py/agent/`) uses LiteLLM for provider-agnostic LLM access via `litellm.completion()` in `agent/llm.py`. There is currently no tracing, no token/cost tracking, and no way to visualize agent execution flows. This research evaluates observability tools to find the simplest integration path that provides maximum visibility with minimum code changes.

LiteLLM supports two main integration approaches:
1. **Native `success_callback`/`failure_callback`**: Set a callback name (e.g., `litellm.success_callback = ["langfuse"]`) and environment variables. Zero changes to LLM call sites.
2. **OpenTelemetry auto-instrumentation**: Use an OTel SDK to instrument LiteLLM calls and send to any OTel-compatible backend.

---

## Evaluation Criteria

Each tool is evaluated on the following axes:

| Criterion | Description |
|-----------|-------------|
| **Integration Simplicity** | Lines of code required for basic integration (fewer is better) |
| **Free-Tier / Self-Host** | What you get without paying; self-hosting availability |
| **Automatic Data Capture** | What data is recorded without manual instrumentation |
| **License** | Open-source license type |
| **Community / Documentation** | Size and activity of community; quality of LiteLLM-specific docs |

---

## Comparison Matrix

| Tool | Callback Name | Integration (LoC) | Self-Host | License | Free Data | Community |
|------|--------------|-------------------|-----------|---------|-----------|-----------|
| **Langfuse** | `"langfuse"` / `"langfuse_otel"` | 2-3 | Yes (Docker, K8s) | MIT (core) | Model, messages, tokens, cost, latency, errors, trace UI | Large, active |
| **Arize Phoenix** | `"arize_phoenix"` | 2-3 | Yes (Docker, local, notebook) | Apache 2.0 | Per-call tracing, tokens, latency | Medium, growing |
| **Lunary** | `"lunary"` | 2-3 | Yes (Docker) | MIT | Per-call logging, tokens, cost | Small |
| **Opik (Comet)** | `"opik"` | 2-3 | Yes (Docker, K8s) | Apache 2.0 | Per-call tracing, eval framework | Medium |
| **Helicone** | `"helicone"` | 2-3 | Yes (Docker) | Apache 2.0 | Per-call logging, cost, caching, rate limiting | Medium |
| **LangSmith** | `"langsmith"` | 2-3 | No (cloud only) | Proprietary | Deep LangChain integration, tracing, eval | Large |
| **Braintrust** | `"braintrust"` | 2-3 | No (cloud only) | Proprietary | Auto-tracing, cost tracking, eval | Small |
| **AgentOps** | `"agentops"` | 2-3 | No (cloud only) | MIT | Per-call tracing, cost tracking | Small |
| **W&B Weave** | `"wandb"` | 2-3 | No (cloud only) | Proprietary | Auto-tracing, experiment tracking | Large (ML) |
| **MLflow** | `"mlflow"` | 2-3 | Yes (self-hosted) | Apache 2.0 | Experiment tracking, model registry | Large (ML) |
| **Logfire (Pydantic)** | `"logfire"` | 2-3 | No (cloud dashboard) | Apache 2.0 | OTel-native, structured logging | Small |
| **OpenLLMetry (Traceloop)** | OTel auto-instrument | 2-3 | Backend-agnostic | Apache 2.0 | Per-call tracing via OTel | Medium |

### Ranking Summary

| Criterion | Top Picks |
|-----------|-----------|
| **Integration Simplicity** | All Tier 1 tools tie at 2-3 lines; OpenLLMetry also ~2 lines |
| **Free-Tier Capabilities** | Langfuse, Arize Phoenix (no feature gates on self-hosted) |
| **Self-Hosting** | Langfuse, Arize Phoenix, Opik, Helicone, MLflow, Lunary |
| **Community / Docs (LiteLLM-specific)** | Langfuse (most LiteLLM docs/examples), LangSmith (LangChain-focused) |

---

## Per-Tool Evaluation

### 1. Langfuse

- **Callback**: `"langfuse"` (direct) or `"langfuse_otel"` (via OpenTelemetry)
- **Integration**: `litellm.success_callback = ["langfuse"]` + 3 env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`)
- **Automatic Data**: Model name, input messages, output content, tool calls, token usage (prompt/completion/total), estimated cost, latency, finish reason, errors. Full trace UI with timeline.
- **Self-Hosting**: Docker Compose or Kubernetes. MIT-licensed core with no feature gates on tracing or evaluation.
- **License**: MIT (core), proprietary enterprise add-ons
- **Strengths**: Largest LiteLLM community; best documentation for LiteLLM integration; trace grouping via metadata (`trace_id`, `session_id`); evaluation framework; `langfuse_otel` callback for future OTel migration.
- **Weaknesses**: Trace grouping across calls requires passing `trace_id`/`session_id` in metadata (not automatic); `@observe()` decorator does NOT auto-group litellm callback-generated traces (upstream issue langfuse/langfuse#2238).

### 2. Arize Phoenix

- **Callback**: `"arize_phoenix"`
- **Integration**: Callback registration + OTel SDK dependencies
- **Automatic Data**: Per-call tracing, token usage, latency. No feature gates on any functionality.
- **Self-Hosting**: Docker, local process, or Jupyter notebook (zero infrastructure for dev).
- **License**: Apache 2.0 (fully open-source, no proprietary tiers)
- **Strengths**: Fully open with zero feature gates; runs locally without Docker; strong evaluation/experimentation features; Apache 2.0 means no licensing concerns.
- **Weaknesses**: Requires OTel SDK dependencies (heavier install); trace grouping across LLM calls is less mature than Langfuse; fewer LiteLLM-specific examples.

### 3. Lunary

- **Callback**: `"lunary"`
- **Integration**: Callback registration + `LUNARY_PUBLIC_KEY` env var
- **Automatic Data**: Per-call logging, token usage, cost tracking.
- **Self-Hosting**: Docker deployment available.
- **License**: MIT
- **Strengths**: Simple setup; MIT license; self-hostable.
- **Weaknesses**: Smaller community; less LiteLLM-specific documentation; fewer advanced features (evaluation, trace grouping).

### 4. Opik (Comet)

- **Callback**: `"opik"`
- **Integration**: Callback registration + API key
- **Automatic Data**: Per-call tracing, built-in evaluation framework.
- **Self-Hosting**: Docker and Kubernetes deployments.
- **License**: Apache 2.0
- **Strengths**: Strong evaluation framework; Apache 2.0; self-hostable.
- **Weaknesses**: Self-hosted version lacks user management; Kubernetes recommended for production; smaller LiteLLM community presence.

### 5. Helicone

- **Callback**: `"helicone"`
- **Integration**: Callback registration or proxy-based (URL rewriting)
- **Automatic Data**: Per-call logging, cost tracking, built-in caching and rate limiting.
- **Self-Hosting**: Docker deployment.
- **License**: Apache 2.0
- **Strengths**: Unique caching and rate limiting features; proxy approach as alternative; Apache 2.0.
- **Weaknesses**: Proxy-based approach adds a network hop; trace grouping less developed.

### 6. LangSmith

- **Callback**: `"langsmith"`
- **Integration**: Callback registration + `LANGCHAIN_API_KEY` env var
- **Automatic Data**: Deep tracing, evaluation, dataset management. Best-in-class for LangChain-based projects.
- **Self-Hosting**: Not available (cloud only).
- **License**: Proprietary
- **Strengths**: Most polished UI; deep LangChain integration; strong evaluation tooling.
- **Weaknesses**: Cloud-only (no self-hosting); proprietary license; vendor lock-in; primarily LangChain-focused.

### 7. Braintrust

- **Callback**: `"braintrust"`
- **Integration**: Callback registration + API key
- **Automatic Data**: Auto-tracing, cost tracking, evaluation framework.
- **Self-Hosting**: Not available (cloud only).
- **License**: Proprietary
- **Strengths**: Clean UI; built-in evaluation and scoring.
- **Weaknesses**: Cloud-only; proprietary; smaller community.

### 8. AgentOps

- **Callback**: `"agentops"`
- **Integration**: Callback registration + API key
- **Automatic Data**: Per-call tracing, cost tracking, agent session tracking.
- **Self-Hosting**: Not available (cloud only).
- **License**: MIT (SDK), proprietary (platform)
- **Strengths**: Agent-focused features (session tracking, replay).
- **Weaknesses**: Cloud-only dashboard; limited callback control; smaller community.

### 9. W&B Weave (Weights & Biases)

- **Callback**: `"wandb"`
- **Integration**: `weave.init()` + callback registration
- **Automatic Data**: Auto-tracing, experiment tracking, model comparison.
- **Self-Hosting**: Not available (cloud only).
- **License**: Proprietary
- **Strengths**: Strong experiment tracking heritage; large ML community; model comparison features.
- **Weaknesses**: Cloud-only; heavier dependency footprint; proprietary; ML-focused rather than LLM-focused.

### 10. MLflow

- **Callback**: `"mlflow"`
- **Integration**: Callback registration + MLflow tracking server
- **Automatic Data**: Experiment tracking, run logging, model registry.
- **Self-Hosting**: Fully self-hosted (Python server, many deployment options).
- **License**: Apache 2.0
- **Strengths**: Mature project; strong model registry; Apache 2.0; fully self-hostable; large ML community.
- **Weaknesses**: General-purpose MLOps tool (not LLM-specialized); LLM tracing UI less polished than dedicated tools; heavier infrastructure.

### 11. Logfire (Pydantic)

- **Callback**: `"logfire"`
- **Integration**: Callback registration + API key
- **Automatic Data**: OpenTelemetry-native structured logging, LLM call tracing.
- **Self-Hosting**: Not available (cloud-only dashboard); data export via OTel is possible.
- **License**: Apache 2.0 (SDK)
- **Strengths**: OTel-native architecture; excellent Pydantic integration; structured logging.
- **Weaknesses**: Cloud-only dashboard; newer project with smaller community; fewer LiteLLM-specific examples.

### 12. OpenLLMetry (Traceloop)

- **Approach**: `Traceloop.init()` auto-instruments LiteLLM via OpenTelemetry
- **Integration**: ~2 lines (`Traceloop.init()` with exporter config); backend-agnostic
- **Automatic Data**: Per-call tracing via OTel spans (model, messages, tokens, latency).
- **Self-Hosting**: N/A -- it is a client-side SDK that sends to any OTel collector (Jaeger, Grafana Tempo, etc.)
- **License**: Apache 2.0
- **Strengths**: No vendor lock-in; sends to any OTel backend; Apache 2.0; clean architecture.
- **Weaknesses**: Requires choosing and deploying a separate OTel-compatible backend for visualization; no built-in dashboard.

---

## Recommendation

**Langfuse** is the recommended tool for this integration.

### Rationale

1. **Simplest meaningful integration**: `litellm.success_callback = ["langfuse"]` + 3 environment variables gives per-call tracing with token/cost/latency tracking and a full trace UI -- zero changes to existing LLM call sites.

2. **Optional trace grouping**: Passing `metadata={"trace_id": ..., "session_id": ...}` to `litellm.completion()` groups all LLM calls for one task under a single trace. No decorator required.

3. **Self-hosting**: MIT-licensed core, Docker Compose deployment, no feature gates on tracing or evaluation functionality.

4. **Future flexibility**: The `"langfuse_otel"` callback variant sends data via OpenTelemetry, making it straightforward to swap backends later without changing agent code.

5. **Largest LiteLLM community**: Most documentation, examples, and GitHub activity for the LiteLLM + Langfuse combination.

### Why not the alternatives?

- **Arize Phoenix** is the strongest runner-up (Apache 2.0, fully open, zero feature gates) but has less mature trace grouping and fewer LiteLLM-specific docs.
- **LangSmith** has the most polished UI but is cloud-only and proprietary.
- **OpenLLMetry** is excellent for OTel purists but requires deploying a separate visualization backend.
- **MLflow** is too general-purpose for LLM-specific observability needs.

---

## Migration Notes

### Migrating to Arize Phoenix (strongest alternative)

If Langfuse's MIT + enterprise licensing model becomes a concern, Arize Phoenix can be substituted with minimal changes:

1. **Change callback**: Replace `"langfuse"` with `"arize_phoenix"` in `configure_observability()`.
2. **Update env vars**: Replace `LANGFUSE_*` variables with Phoenix configuration (primarily `PHOENIX_COLLECTOR_ENDPOINT`).
3. **Update dependency**: Replace `langfuse>=2.0.0` with `arize-phoenix>=4.0.0` in the `observability` dependency group.
4. **Trace grouping**: Adapt metadata format for Phoenix's OTel-based span grouping (slightly different API surface).

Estimated migration effort: 1-2 hours for a developer familiar with both tools.

### Migrating to OpenTelemetry (vendor-neutral)

For maximum vendor neutrality, the Langfuse `"langfuse_otel"` callback variant already sends data via OTel. Switching to a pure OTel setup (e.g., OpenLLMetry + Jaeger/Grafana Tempo) would involve:

1. Replace the Langfuse callback with `Traceloop.init()`.
2. Configure an OTel exporter for the chosen backend.
3. Deploy the visualization backend (Jaeger, Grafana Tempo, etc.).
