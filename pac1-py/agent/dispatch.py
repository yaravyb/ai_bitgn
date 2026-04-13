import json
import logging
import re

# Frontmatter gap normalizer: strip extra blank lines between closing --- and body.
# LLMs often write "---\n\n# Heading" but strict parsers expect "---\n# Heading".
_FRONTMATTER_GAP_RE = re.compile(r"^(---\n.*?\n---)\n{2,}", re.DOTALL)


def _normalize_frontmatter_gap(content: str) -> str:
    """Ensure exactly one newline between YAML frontmatter closing --- and body."""
    return _FRONTMATTER_GAP_RE.sub(r"\1\n", content)

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
from agent.outcomes import OUTCOME_BY_NAME
from skills import SkillLoader
from tasks import TaskManager

log = logging.getLogger(__name__)


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
# Safe arithmetic evaluator (AST-based, no eval)
# ---------------------------------------------------------------------------

import ast
import operator
from datetime import date, timedelta

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _date_offset(iso_date: str, days: int) -> str:
    """Add/subtract days from an ISO date. Returns ISO string."""
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def _days_between(iso_start: str, iso_end: str) -> int:
    """Count days between two ISO dates."""
    return (date.fromisoformat(iso_end) - date.fromisoformat(iso_start)).days


import pandas as pd

# Shared state for loaded data
_loaded_df: pd.DataFrame | None = None
_loaded_records: list[dict] = []

# Restricted namespace for calculate() — no builtins, no imports
_CALC_NAMESPACE: dict = {
    "__builtins__": {},
    # Math
    "sum": sum, "len": len, "min": min, "max": max,
    "abs": abs, "round": round, "sorted": sorted,
    "str": str, "int": int, "float": float, "bool": bool,
    "any": any, "all": all, "list": list, "set": set, "dict": dict,
    "True": True, "False": False, "None": None,
    # Date helpers
    "date_offset": _date_offset,
    "days_between": _days_between,
    # Pandas
    "pd": pd,
}


def _safe_calculate(expression: str) -> str:
    """Evaluate expression with pandas, arithmetic, and date helpers.

    The expression runs in a restricted namespace: no __builtins__,
    no imports. Only pre-approved functions, pandas, and loaded data
    (df, records) are accessible.
    """
    ns = dict(_CALC_NAMESPACE)
    if _loaded_df is not None:
        ns["df"] = _loaded_df
    ns["records"] = list(_loaded_records)

    try:
        result = eval(compile(expression, "<calc>", "eval"), ns)  # noqa: S307 — restricted namespace, agent-generated only
        # Convert pandas types to Python for clean display
        if isinstance(result, pd.DataFrame):
            return result.to_string(index=False)
        if isinstance(result, pd.Series):
            return result.to_string(index=False)
        if hasattr(result, 'item'):  # numpy scalar
            return str(result.item())
        return str(result)
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# load_records: parse a folder of structured files into a queryable table
# ---------------------------------------------------------------------------

import yaml


def _parse_yaml_frontmatter(text: str) -> dict | None:
    """Extract YAML frontmatter from a markdown file. Returns None if no frontmatter."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        return yaml.safe_load(text[4:end]) or {}
    except Exception:
        return None


def _load_records(vm, path: str) -> str:
    """Load all structured files from a folder into a pandas DataFrame.

    Parses JSON files and markdown files with YAML frontmatter.
    Validates structural consistency, infers types, builds df.
    """
    global _loaded_records, _loaded_df

    # List folder
    try:
        list_result = vm.list(ListRequest(name=path.lstrip("/")))
        entries_raw = MessageToDict(list_result).get("entries", [])
        entries = [e.get("name", "") for e in entries_raw if e.get("name", "")]
    except Exception as exc:
        return f"Error listing {path}: {exc}"

    # Filter to parseable files
    files = [e for e in entries if e.endswith((".json", ".md")) and not e.upper().startswith(("README", "AGENTS"))]
    if not files:
        return f"No structured files found in {path}"

    # Parse all files
    records = []
    parse_errors = 0
    for fname in files:
        fpath = f"{path.strip('/')}/{fname}"
        try:
            result = vm.read(ReadRequest(path=fpath))
            content = MessageToDict(result).get("content", "")
            if not content:
                continue
        except Exception:
            parse_errors += 1
            continue

        record = None
        if fname.endswith(".json"):
            try:
                record = json.loads(content)
                if not isinstance(record, dict):
                    record = None
            except json.JSONDecodeError:
                parse_errors += 1
        elif fname.endswith(".md"):
            record = _parse_yaml_frontmatter(content)
            if record is not None:
                # Capture the markdown body for content queries
                body_start = content.find("\n---", 3)
                if body_start != -1:
                    body = content[body_start + 4:].strip()
                    if body:
                        record["_body"] = body[:800]

        if record and isinstance(record, dict):
            record["_file"] = fname
            records.append(record)

    if not records:
        return f"No parseable records in {path} ({parse_errors} parse errors)"

    # Validate structural consistency
    sample = records[:min(5, len(records))]
    field_sets = [set(r.keys()) - {"_file", "_body"} for r in sample]
    common_fields = field_sets[0]
    for fs in field_sets[1:]:
        common_fields &= fs
    if len(common_fields) < 2:
        return f"Inconsistent structure in {path}: files don't share enough common fields"

    # Build DataFrame
    _loaded_records = records
    _loaded_df = pd.DataFrame(records)

    # Serialize list/dict columns to JSON strings for easier querying
    for col in _loaded_df.columns:
        if _loaded_df[col].apply(lambda x: isinstance(x, (list, dict))).any():
            _loaded_df[col] = _loaded_df[col].apply(
                lambda x: json.dumps(x) if isinstance(x, (list, dict)) else x
            )

    # Auto-detect and convert date columns
    for col in _loaded_df.columns:
        if col.startswith("_"):
            continue
        sample_vals = _loaded_df[col].dropna().head(3).astype(str)
        if len(sample_vals) > 0 and sample_vals.str.match(r"^\d{4}-\d{2}-\d{2}").all():
            try:
                _loaded_df[col] = pd.to_datetime(_loaded_df[col], errors="coerce")
            except Exception:
                pass

    # Build summary
    cols = [c for c in _loaded_df.columns if c != "_body"]
    dtypes = {c: str(_loaded_df[c].dtype) for c in cols}
    dtype_info = ", ".join(f"{c}({dtypes[c]})" for c in cols[:15])

    return (
        f"Loaded {len(records)} records into df. "
        f"Columns: {dtype_info}. "
        f"Query with calculate(): "
        f"df['col'].sum(), df[df['col'] == 'X'], "
        f"df[df['_file'].str.contains('keyword')].shape[0], "
        f"df.sort_values('col').head(), "
        f"len(df[df['status'] == 'active'])"
    )


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
        "calculate": lambda: _safe_calculate(args.get("expression", "")),
        "load_records": lambda: _load_records(vm, args.get("path", "")),
        "load_skill": lambda: load_skill(vm, skill_loader, args.get("name", args.get("path", ""))) if skill_loader else "Error: no skill loader",
        "write": lambda: vm.write(WriteRequest(path=args["path"], content=_normalize_frontmatter_gap(args["content"]))),
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

    # Auto-load: when listing a folder with structured files, transparently
    # try load_records() so df is ready for calculate() queries.
    # Falls back silently if files aren't structured.
    if name == "list":
        list_path = args.get("path", "/")
        entries = result_dict.get("entries", [])
        structured_count = sum(
            1 for e in entries
            if e.get("name", "").endswith((".json", ".md"))
            and not e.get("name", "").upper().startswith(("README", "AGENTS"))
        )
        if structured_count >= 3:
            try:
                load_result = _load_records(vm, list_path)
                if "Loaded" in load_result:
                    txt += f"\n\n[AUTO] {load_result}"
            except Exception:
                pass  # silent fallback — agent reads files normally

    return txt
