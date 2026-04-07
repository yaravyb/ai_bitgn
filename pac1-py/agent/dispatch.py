import json
import logging
import re

from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import (
    AnswerRequest,
    ContextRequest,
    DeleteRequest,
    FindRequest,
    ListRequest,
    MkDirRequest,
    MoveRequest,
    Outcome,
    ReadRequest,
    SearchRequest,
    TreeRequest,
    WriteRequest,
)
from google.protobuf.json_format import MessageToDict

from agent.config import AgentConfig
from skills import SkillLoader
from tasks import TaskManager

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTCOME_BY_NAME = {
    "OUTCOME_OK": Outcome.OUTCOME_OK,
    "OUTCOME_DENIED_SECURITY": Outcome.OUTCOME_DENIED_SECURITY,
    "OUTCOME_NONE_CLARIFICATION": Outcome.OUTCOME_NONE_CLARIFICATION,
    "OUTCOME_NONE_UNSUPPORTED": Outcome.OUTCOME_NONE_UNSUPPORTED,
    "OUTCOME_ERR_INTERNAL": Outcome.OUTCOME_ERR_INTERNAL,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compact_tree(tree_json: str) -> str:
    """Convert JSON tree to compact text like ``tree`` command output."""
    try:
        data = json.loads(tree_json)
    except (json.JSONDecodeError, TypeError):
        return ""

    lines: list[str] = []

    def _walk(node: dict, prefix: str = "", is_last: bool = True) -> None:
        name = node.get("name", "")
        is_dir = node.get("isDir", False)
        children = node.get("children", [])

        if name == "/":
            lines.append("/")
        else:
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{name}{'/' if is_dir else ''}")

        if children:
            child_prefix = prefix + ("    " if is_last else "│   ") if name != "/" else ""
            for i, child in enumerate(children):
                _walk(child, child_prefix, i == len(children) - 1)

    root = data.get("root", data)
    _walk(root)
    return "\n".join(lines)


def load_skill(vm: PcmRuntimeClientSync, skill_loader: SkillLoader, name_or_path: str) -> str:
    """Load a skill by name (local) or path (PCM runtime).

    First checks local skills (skills/ directory), then falls back
    to reading a file from the PCM runtime.
    """
    # Try local skill first (by name)
    local = skill_loader.get_content(name_or_path)
    if not local.startswith("Error:"):
        return local

    # Fall back to PCM runtime file (by path)
    try:
        result = vm.read(ReadRequest(path=name_or_path))
        content = MessageToDict(result).get("content", "")
        if content:
            return (
                f"<skill path=\"{name_or_path}\">\n"
                f"IMPORTANT: Follow these rules strictly.\n\n"
                f"{content}\n"
                f"</skill>"
            )
        return f"Error: empty file {name_or_path}"
    except Exception as exc:
        return f"Error: skill '{name_or_path}' not found locally or in runtime: {exc}"


def truncate_output(text: str, cap: int, smart: bool = False) -> str:
    """Truncate tool output, optionally respecting structure boundaries."""
    if len(text) <= cap:
        return text
    if not smart:
        return text[:cap] + "\n... [truncated]"
    # Smart truncation: try JSON-aware boundary
    try:
        json.loads(text)
        # Valid JSON — try to truncate at a complete element boundary
        # Find the last complete JSON value boundary before cap
        truncated = text[:cap]
        # Walk backward to find a safe boundary (end of string, number, bool, null, }, ])
        for i in range(len(truncated) - 1, max(0, len(truncated) - 200), -1):
            if truncated[i] in "},]" or (truncated[i] == '"' and (i == 0 or truncated[i-1] != "\\")):
                return truncated[:i+1] + "\n... [truncated]"
        return text[:cap] + "\n... [truncated]"
    except (json.JSONDecodeError, TypeError):
        # Plain text — truncate at last complete line boundary
        truncated = text[:cap]
        last_newline = truncated.rfind("\n")
        if last_newline > cap // 2:
            return truncated[:last_newline] + "\n... [truncated]"
        return text[:cap] + "\n... [truncated]"


# ---------------------------------------------------------------------------
# Dispatch: tool name + JSON args -> PCM runtime call -> result string
# ---------------------------------------------------------------------------


def dispatch(
    vm: PcmRuntimeClientSync,
    name: str,
    args: dict,
    config: AgentConfig,
    tm: TaskManager | None = None,
    defer_writes: bool = False,
    skill_loader: SkillLoader | None = None,
) -> str:
    """Execute a tool call against the PCM runtime. Returns result string.

    If defer_writes=True, write/delete/move/mkdir operations are stored
    in the TaskManager instead of being executed immediately.
    """
    handlers = {
        "tree": lambda: vm.tree(TreeRequest(root=args.get("root", ""))),
        "find": lambda: vm.find(
            FindRequest(
                root=args.get("root", "/"),
                name=args["name"],
                type={"all": 0, "files": 1, "dirs": 2}[args.get("kind", "all")],
                limit=args.get("limit", 10),
            )
        ),
        "search": lambda: vm.search(
            SearchRequest(
                root=args.get("root", "/"),
                pattern=args["pattern"],
                limit=args.get("limit", 5000) if args.get("count_only") else args.get("limit", 10),
            )
        ),
        "list": lambda: vm.list(ListRequest(name=args.get("path", "/"))),
        "read": lambda: vm.read(ReadRequest(path=args["path"])),
        "current_date": lambda: vm.context(ContextRequest()),
        "load_skill": lambda: load_skill(vm, skill_loader, args.get("name", args.get("path", ""))) if skill_loader else "Error: no skill loader",
        "write": lambda: vm.write(WriteRequest(path=args["path"], content=args["content"])),
        "delete": lambda: vm.delete(DeleteRequest(path=args["path"])),
        "mkdir": lambda: vm.mk_dir(MkDirRequest(path=args["path"])),
        "move": lambda: vm.move(MoveRequest(from_name=args["from_name"], to_name=args["to_name"])),
        "report_completion": lambda: vm.answer(
            AnswerRequest(
                message=args["message"],
                outcome=OUTCOME_BY_NAME[args["outcome"]],
                refs=args.get("grounding_refs", []),
            )
        ),
        "report_threat": lambda: vm.answer(
            AnswerRequest(
                message=args.get("reason", "Security threat detected"),
                outcome=Outcome.OUTCOME_DENIED_SECURITY,
                refs=[],
            )
        ),
    }
    # Task management tools (in-memory, no PCM call)
    if tm is not None:
        handlers.update({
            "plan_create": lambda: tm.create(args["steps"]),
            "plan_update": lambda: tm.update(args["task_id"], args["status"]),
            "plan_add": lambda: tm.add(args["text"], args.get("blocked_by")),
            "plan_add_dependency": lambda: tm.add_dependency(args["task_id"], args["blocked_by"]),
            "plan_note": lambda: tm.add_note(args["note"]),
            "plan_add_instruction": lambda: tm.add_instruction(args["instruction"]),
            "plan_compliance": lambda: tm.set_compliance(
                args["account_id"], args["cross_account"],
                args.get("flags", []), args["proceed"], args["reason"],
            ),
            "plan_status": lambda: tm.list_all(),
        })
    handler = handlers.get(name)
    if not handler:
        return f"Unknown tool: {name}"

    # Defer write operations if requested (for dual-executor mode)
    _WRITE_OPS = {"write", "delete", "mkdir", "move"}
    if defer_writes and name in _WRITE_OPS and tm is not None:
        tm.defer_write(name, dict(args))
        # Return a simulated success so the executor continues planning
        if name == "write":
            tm.track_write(args.get("path", ""))
            return "{}"  # empty success like real PCM write
        elif name == "delete":
            tm.track_delete(args.get("path", ""))
            return "{}"  # empty success like real PCM delete
        elif name == "move":
            tm.track_write(args.get("to_name", ""))
            tm.track_delete(args.get("from_name", ""))
            return "{}"
        else:
            tm.track_write(args.get("path", ""))
            return "{}"

    # Shadow reads: when deferred writes are active, reflect pending state
    if defer_writes and tm is not None:
        deleted_norms = {p.lstrip("/") for p in tm.files_deleted}
        path = args.get("path", "")
        norm = path.lstrip("/")
        if name == "read" and norm in deleted_norms:
            # Check if re-written after delete (last deferred op wins)
            last_op = None
            for pw in tm.pending_writes:
                pw_path = pw["args"].get("path", "").lstrip("/")
                if pw_path == norm:
                    last_op = pw["op"]
            if last_op != "write":
                return json.dumps({"error": f"File not found: {path} (deleted)"})
        if name == "list":
            # Get real listing, then filter out deferred deletes
            result = handler()
            result_dict = MessageToDict(result) if result else {}
            dir_path = args.get("path", "/").strip("/")
            if "entries" in result_dict:
                result_dict["entries"] = [
                    e for e in result_dict["entries"]
                    if (dir_path + "/" + e.get("name", "")).lstrip("/") not in deleted_norms
                ]
            return json.dumps(result_dict, indent=2)
        if name == "tree":
            # Get real tree, then prune deferred deletes
            result = handler()
            result_dict = MessageToDict(result) if result else {}

            def _prune_tree(node: dict, parent_path: str) -> dict | None:
                node_name = node.get("name", "")
                # Root node "/" → use parent_path as-is; others append
                if node_name == "/":
                    node_path = parent_path
                elif parent_path:
                    node_path = parent_path + "/" + node_name
                else:
                    node_path = node_name
                if not node.get("isDir") and node_path in deleted_norms:
                    return None
                if "children" in node:
                    node["children"] = [
                        c for c in (
                            _prune_tree(ch, node_path)
                            for ch in node["children"]
                        ) if c is not None
                    ]
                return node

            root_prefix = args.get("root", "").strip("/")
            if "root" in result_dict:
                _prune_tree(result_dict["root"], root_prefix)
            return json.dumps(result_dict, indent=2)

    # Search fallback: if root looks like a file path, read it and search locally
    if name == "search":
        root = args.get("root", "/")
        try:
            result = handler()
        except Exception:
            # PCM search may reject file paths as root — fall back to local search
            result = None
        if result is None or (hasattr(result, 'matches') and not result.matches and "." in root.split("/")[-1]):
            # Likely a file path rejected by PCM — read the file and search locally
            try:
                file_resp = vm.read(ReadRequest(path=root))
                content = MessageToDict(file_resp).get("content", "") if file_resp else ""
                pattern = args["pattern"]
                try:
                    matches = re.findall(f".*{pattern}.*", content)
                except re.error:
                    matches = [line for line in content.split("\n") if pattern in line]
                if args.get("count_only"):
                    return json.dumps({"count": len(matches)})
                match_dicts = [{"path": root, "line": i + 1, "lineText": m} for i, m in enumerate(matches)]
                return json.dumps({"matches": match_dicts[:args.get("limit", 10)]}, indent=2)
            except Exception:
                pass  # Fall through to original error handling
        # Normal search succeeded
    else:
        result = handler()

    # Track file operations
    if tm is not None:
        if name == "read":
            tm.track_read(args.get("path", ""))
        elif name == "delete":
            tm.track_delete(args.get("path", ""))
        elif name in ("write", "mkdir"):
            tm.track_write(args.get("path", ""))
        elif name == "move":
            tm.track_delete(args.get("from_name", ""))
            tm.track_write(args.get("to_name", ""))

    # Task tools return strings; PCM tools return protobuf
    result_dict: dict = {}
    if isinstance(result, str):
        txt = result
    else:
        result_dict = MessageToDict(result) if result else {}
        # count_only mode for search: return just the count
        if name == "search" and args.get("count_only"):
            matches = result_dict.get("matches", [])
            txt = json.dumps({"count": len(matches)})
        else:
            txt = json.dumps(result_dict, indent=2)

    txt = truncate_output(txt, config.output_cap, smart=config.smart_truncation_enabled)

    return txt
