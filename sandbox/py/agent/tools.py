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
            "description": "Read the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to read.",
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
            "description": "Write content to a file, creating or overwriting it.",
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
                        "enum": ["completed", "failed"],
                        "description": "Completion status code.",
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
]

TOOL_NAMES: set[str] = {s["function"]["name"] for s in TOOL_SCHEMAS}

# Read-only tool subset for the scout phase (Task 1)
_SCOUT_TOOL_NAMES: frozenset[str] = frozenset({"tree", "list_dir", "read_file", "search"})

SCOUT_TOOL_SCHEMAS: list[dict] = [
    s for s in TOOL_SCHEMAS
    if s["function"]["name"] in _SCOUT_TOOL_NAMES
]
