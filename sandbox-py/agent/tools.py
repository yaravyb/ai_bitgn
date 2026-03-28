"""Tool schema definitions for the agent.

Pure data module: OpenAI-compatible function calling schemas.
Zero imports from other agent/ modules.
"""

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "tree",
            "description": "Outline directory tree starting from the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Root path to outline.",
                    },
                    "level": {
                        "type": "integer",
                        "description": "Maximum depth level to display. 0 or omitted = unlimited.",
                        "default": 0,
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and folders in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Supports line-range reads and line numbering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to read.",
                    },
                    "number": {
                        "type": "boolean",
                        "description": "If true, prefix each line with its line number (like cat -n).",
                        "default": False,
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line to read (1-based). Omit to start from beginning.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to read (1-based, inclusive). Omit to read to end.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file. Without line range: creates or overwrites. "
                "With start_line/end_line: replaces only the specified lines."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to write to.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line to replace (1-based). Omit for full overwrite.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to replace (1-based, inclusive). Omit for full overwrite.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to delete.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search for a pattern in files under the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern (regex or substring).",
                    },
                    "path": {
                        "type": "string",
                        "description": "Root path to search under.",
                        "default": "/",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Maximum number of results to return.",
                        "default": 5,
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_completion",
            "description": (
                "Report task completion with the answer, grounding references, "
                "completed steps, and a status code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "The final answer to the task.",
                    },
                    "grounding_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths that contributed to the answer.",
                    },
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of completed steps (laconic descriptions).",
                    },
                    "code": {
                        "type": "string",
                        "enum": [
                            "OUTCOME_OK",
                            "OUTCOME_ERR_INTERNAL",
                            "OUTCOME_NONE_UNSUPPORTED",
                            "OUTCOME_DENIED_SECURITY",
                            "OUTCOME_NONE_CLARIFICATION",
                        ],
                        "description": (
                            "PCM outcome code that best matches the situation."
                        ),
                    },
                },
                "required": ["answer", "grounding_refs", "steps", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "Load a built-in skill by name to get full instructions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the skill to load.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compact",
            "description": (
                "Trigger immediate context summarization. Use when the conversation "
                "feels too long or you are losing track of earlier work. This compresses "
                "the full conversation into a summary."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
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
    },
    {
        "type": "function",
        "function": {
            "name": "plan_step_done",
            "description": (
                "Mark one or more plan steps as completed. "
                "Pass a single index or an array of indices. "
                "Returns the updated plan with current completion status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_index": {
                        "description": "0-based index (integer) or array of indices to mark as done.",
                    },
                },
                "required": ["step_index"],
            },
        },
    },
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
    },
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
    },
    {
        "type": "function",
        "function": {
            "name": "plan_note",
            "description": (
                "Save a short note to your persistent plan. Notes survive "
                "context compression. Use to record key facts you will need "
                "later (e.g. IDs, file paths, values read from files)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {
                        "type": "string",
                        "description": (
                            "A short note to save (1-2 sentences). "
                            "Record key facts, not full file contents."
                        ),
                    },
                },
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_date",
            "description": (
                "Get today's date from the sandbox environment. "
                "Use when a task mentions a time reference. "
                "Phrases like 'in two weeks', 'next month' mean relative to TODAY. "
                "Phrases like 'push back by two weeks', 'delay by 10 days' mean relative to the existing date."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]

TOOL_NAMES: set[str] = {s["function"]["name"] for s in TOOL_SCHEMAS}

# Read-only tool subset for the scout phase (Task 1)
_SCOUT_TOOL_NAMES: frozenset[str] = frozenset({"tree", "list_dir", "read_file", "search"})

SCOUT_TOOL_SCHEMAS: list[dict] = [
    s for s in TOOL_SCHEMAS
    if s["function"]["name"] in _SCOUT_TOOL_NAMES
]

_PCM_EXTRA_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "find",
            "description": "Find files or directories by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name pattern to find."},
                    "root": {"type": "string", "description": "Root path to search from.", "default": "/"},
                    "kind": {"type": "string", "enum": ["all", "files", "dirs"], "description": "Type filter.", "default": "all"},
                    "limit": {"type": "integer", "description": "Maximum results.", "default": 10},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mkdir",
            "description": "Create a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to create."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move",
            "description": "Move or rename a file or directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_name": {"type": "string", "description": "Current path."},
                    "to_name": {"type": "string", "description": "New path."},
                },
                "required": ["from_name", "to_name"],
            },
        },
    },
]


def get_tool_schemas(runtime_type: str = "mini") -> list[dict]:
    """Return tool schemas appropriate for the given runtime type."""
    if runtime_type == "pcm":
        return TOOL_SCHEMAS + _PCM_EXTRA_SCHEMAS
    return TOOL_SCHEMAS
