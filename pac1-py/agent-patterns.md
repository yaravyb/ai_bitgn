# Agent Patterns Analysis for PAC1

Analysis of patterns from `sandbox/examples_of_agents` (s01-s12, s_full) applicable to `pac1-py/agent.py`.

## Current PAC1 Architecture

PAC1 uses **structured output** (instructor + JSON mode) where the model returns a `NextStep` Pydantic object containing a plan and a function to execute. This is fundamentally different from ALL reference examples.

```
PAC1:      LLM -> NextStep JSON -> parse -> dispatch(Pydantic model) -> tool result
Examples:  LLM -> tool_calls     -> parse -> dispatch(JSON args)      -> tool result
```

## Critical Finding: Tool Calling vs Structured Output

**All 12 examples + s_full use native tool calling. None use structured output.**

| Approach | Provider Support | Weak Models | Reasoning Models |
|----------|-----------------|-------------|-----------------|
| **Tool calling** | Universal (LiteLLM translates) | Works (native to all LLMs) | Works (tools bypass reasoning) |
| **Structured output (JSON)** | Partial (json_object mode) | Fragile (empty content, plain text) | Broken (reasoning consumes output) |
| **Structured output (JSON schema)** | OpenAI only (strict mode) | Not supported | Not supported |

### Recommendation: Switch to Tool Calling

The structured output approach causes every problem we've encountered:
- Qwen returns plain text or empty content instead of JSON
- Reasoning models put thinking in `reasoning_content`, leave `content` empty
- instructor's JSON mode injects schema into prompt, bloating context
- Different providers handle `response_format` differently

Tool calling is the universal interface that LiteLLM normalizes across all providers.

---

## Applicable Patterns

### 1. Standard Tool-Call Agent Loop (s01)

The universal pattern across all examples:

```python
def agent_loop(model, messages, tools):
    while True:
        response = completion(model=model, messages=messages, tools=tools, max_tokens=8000)
        choice = response.choices[0]

        # Append assistant message (text + tool calls)
        msg = {"role": "assistant", "content": choice.message.content or ""}
        if choice.message.tool_calls:
            msg["tool_calls"] = [tc.model_dump() for tc in choice.message.tool_calls]
        messages.append(msg)

        # No tool calls = done (model decided to stop or just respond with text)
        if not choice.message.tool_calls:
            return choice.message.content

        # Execute each tool call
        for tc in choice.message.tool_calls:
            args = json.loads(tc.function.arguments)
            result = dispatch(tc.function.name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
```

**Key differences from PAC1:**
- Stop condition is absence of tool_calls (not a special `report_completion` union variant)
- Model can return text alongside tool calls (content + tool_calls coexist)
- Tool schemas are OpenAI JSON dicts, not Pydantic models
- No structured output parsing needed

### 2. Tool Schema Definition (s01-s02)

Tools defined as standard OpenAI function schemas:

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    # ...
]
```

**Advantage over Pydantic union:** Models are trained on this format. It's the native interface.

### 3. Lambda Dispatch Map (s01-s04)

```python
HANDLERS = {
    "tree":   lambda **kw: vm.tree(TreeRequest(root=kw.get("root", ""))),
    "read":   lambda **kw: vm.read(ReadRequest(path=kw["path"])),
    "write":  lambda **kw: vm.write(WriteRequest(path=kw["path"], content=kw["content"])),
    "delete": lambda **kw: vm.delete(DeleteRequest(path=kw["path"])),
    # ...
}

def dispatch(name, args):
    handler = HANDLERS.get(name)
    if not handler:
        return f"Unknown tool: {name}"
    try:
        result = handler(**args)
        return json.dumps(MessageToDict(result), indent=2) if result else "{}"
    except ConnectError as exc:
        return f"Error {exc.code}: {exc.message}"
```

**Advantage:** Errors become tool results (model sees them and adapts), instead of crashing the agent.

### 4. Output Capping (s02+)

```python
output = str(result)
if len(output) > 50000:
    output = output[:50000] + "\n... [truncated]"
```

**PAC1 gap:** No output capping. Large tree/read results bloat context unboundedly.

### 5. Context Compression — 3 Layers (s06)

**Layer 1: Micro-compact (every turn, no LLM call)**
```python
def micro_compact(messages, keep_recent=3):
    tool_msgs = [i for i, m in enumerate(messages) if m["role"] == "tool"]
    for idx in tool_msgs[:-keep_recent]:
        if len(messages[idx]["content"]) > 100:
            messages[idx]["content"] = "[cleared]"
```

**Layer 2: Auto-compact (token threshold, uses LLM)**
```python
def estimate_tokens(messages):
    return len(json.dumps(messages)) // 4

if estimate_tokens(messages) > 50000:
    summary = completion(model=model, messages=[
        {"role": "system", "content": "Summarize this conversation concisely."},
        {"role": "user", "content": json.dumps(messages)},
    ])
    messages[:] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"<context-summary>{summary}</context-summary>"},
        {"role": "assistant", "content": "Understood, continuing."},
    ]
```

**Layer 3: Manual compact (agent calls `compact` tool)**

**PAC1 gap:** No context management at all. Messages grow unboundedly across 30 steps.

### 6. Error as Tool Result (s03+)

Every example wraps tool execution in try-except and returns errors as tool content:

```python
try:
    output = handler(**args)
except Exception as e:
    output = f"Error: {e}"
messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
```

**PAC1 gap:** ConnectError is caught and printed, but the error text IS appended to messages. However, other exceptions would crash the loop. Should catch broadly.

### 7. `report_completion` as a Regular Tool (s01 pattern adaptation)

Instead of encoding completion as a Pydantic union variant, make it a regular tool:

```python
{
    "type": "function",
    "function": {
        "name": "report_completion",
        "description": "Signal task is done or blocked. Call when finished.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "outcome": {"type": "string", "enum": ["OUTCOME_OK", "OUTCOME_DENIED_SECURITY", ...]},
                "grounding_refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["message", "outcome"],
        },
    },
}
```

The loop checks if `report_completion` was called and breaks.

---

## Migration Path: Structured Output -> Tool Calling

### What changes

| Component | Before (structured output) | After (tool calling) |
|-----------|--------------------------|---------------------|
| LLM call | `instructor.create(response_model=NextStep)` | `litellm.completion(tools=TOOLS)` |
| Response parse | Pydantic `NextStep` object | `message.tool_calls[0].function` |
| Tool schemas | Pydantic models with Union | OpenAI JSON schema dicts |
| Dispatch | `isinstance(cmd, Req_Tree)` | `handlers[tc.function.name](**args)` |
| Stop condition | `isinstance(cmd, ReportTaskCompletion)` | `tc.function.name == "report_completion"` |
| Dependencies | `instructor`, `annotated-types` | None extra |
| Provider support | JSON mode only | Universal |

### What stays the same

- LiteLLM for multi-provider routing
- Langfuse observability (via LiteLLM callbacks)
- PCM runtime dispatch (vm.tree, vm.read, etc.)
- System prompt structure
- Retry logic for network errors
- Metadata forwarding for tracing

---

## Priority Order for Implementation

1. **Switch to tool calling** — fixes weak model support, removes instructor dependency
2. **Add output capping** — prevents context blowup from large tool results
3. **Add micro-compact** — clears old tool results, cheap (no LLM call)
4. **Add auto-compact** — summarize when context exceeds threshold
5. **Wrap dispatch in try-except** — errors become tool results, not crashes
