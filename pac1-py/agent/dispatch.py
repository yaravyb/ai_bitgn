import json
import logging
import re

import yaml as _yaml

# Frontmatter gap normalizer: strip extra blank lines between closing --- and body.
# LLMs often write "---\n\n# Heading" but strict parsers expect "---\n# Heading".
_FRONTMATTER_GAP_RE = re.compile(r"^(---\n.*?\n---)\n{2,}", re.DOTALL)


def _normalize_frontmatter_gap(content: str) -> str:
    """Ensure exactly one newline between YAML frontmatter closing --- and body."""
    return _FRONTMATTER_GAP_RE.sub(r"\1\n", content)


def _normalize_yaml_quoting(content: str) -> str:
    """Auto-quote YAML frontmatter values that contain colons.

    LLMs write things like ``subject: Re: Invoice`` which breaks YAML
    because the second colon starts a new mapping.  This function parses
    the frontmatter block, and if it fails, rewrites each value line by
    wrapping the value portion in double quotes (escaping inner quotes).
    """
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---", 3)
    if end == -1:
        return content

    fm_block = content[4:end]
    rest = content[end:]  # includes the closing "\n---..." and body

    # Fast path: if the frontmatter already parses, nothing to fix
    try:
        _yaml.safe_load(fm_block)
        return content
    except _yaml.YAMLError:
        pass

    # Rewrite each line: quote values that contain unquoted colons
    fixed_lines = []
    for line in fm_block.split("\n"):
        # Match "key: value" lines (not continuation/list lines)
        m = re.match(r"^(\s*[A-Za-z_][\w-]*\s*:\s*)(.+)$", line)
        if m:
            key_part, val = m.group(1), m.group(2)
            # Already quoted → leave alone
            if (val.startswith('"') and val.endswith('"')) or \
               (val.startswith("'") and val.endswith("'")):
                fixed_lines.append(line)
            elif ":" in val:
                # Escape inner double quotes, then wrap in double quotes
                escaped = val.replace("\\", "\\\\").replace('"', '\\"')
                fixed_lines.append(f'{key_part}"{escaped}"')
            else:
                fixed_lines.append(line)
        else:
            fixed_lines.append(line)

    new_fm = "\n".join(fixed_lines)
    # Verify the fix actually works
    try:
        _yaml.safe_load(new_fm)
    except _yaml.YAMLError:
        return content  # give up — don't make it worse

    return "---\n" + new_fm + rest


def _normalize_ascii_tables(content: str) -> str:
    """Re-format ASCII tables so column widths are consistent.

    LLMs generate tables where header and data rows have different column
    widths.  This parser finds ``+---+`` style tables inside ```text
    fenced blocks, parses them into grids, and re-renders with uniform
    widths computed from the longest cell value in each column.
    """
    if "+--" not in content:
        return content

    # Find all ```text ... ``` blocks that contain tables
    parts = re.split(r"(```text\n.*?```)", content, flags=re.DOTALL)
    changed = False
    for i, part in enumerate(parts):
        if not part.startswith("```text\n") or "+--" not in part:
            continue
        inner = part[len("```text\n"):-len("```")]
        fixed = _reformat_table_block(inner)
        if fixed != inner:
            parts[i] = "```text\n" + fixed + "```"
            changed = True

    return "".join(parts) if changed else content


def _reformat_table_block(block: str) -> str:
    """Re-format a single block that may contain one or more ASCII tables."""
    lines = block.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        # Detect table start: a separator line like +---+---+
        if re.match(r"^\+[-+]+\+$", lines[i].strip()):
            table_lines: list[str] = []
            while i < len(lines) and (
                re.match(r"^\+[-+]+\+$", lines[i].strip()) or
                re.match(r"^\|.*\|$", lines[i].strip())
            ):
                table_lines.append(lines[i].strip())
                i += 1
            reformatted = _reformat_single_table(table_lines)
            result.extend(reformatted)
        else:
            result.append(lines[i])
            i += 1
    return "\n".join(result)


def _reformat_single_table(table_lines: list[str]) -> list[str]:
    """Parse and re-render a single ASCII table with consistent column widths."""
    # Parse all data rows to find cell values
    rows: list[list[str]] = []
    separator_positions: list[int] = []  # which line indices are separators

    for idx, line in enumerate(table_lines):
        if re.match(r"^\+[-+]+\+$", line):
            separator_positions.append(idx)
            rows.append([])  # placeholder for separator
        elif re.match(r"^\|.*\|$", line):
            # Split by | and strip whitespace
            cells = [c.strip() for c in line.split("|")[1:-1]]
            rows.append(cells)
        else:
            rows.append([line])  # unknown line, keep as-is

    # Find max number of columns
    data_rows = [r for i, r in enumerate(rows) if i not in separator_positions and len(r) > 1]
    if not data_rows:
        return table_lines

    n_cols = max(len(r) for r in data_rows)

    # Pad rows with fewer columns
    for r in data_rows:
        while len(r) < n_cols:
            r.append("")

    # Compute column widths (max cell width per column, minimum 1)
    col_widths = [1] * n_cols
    for r in data_rows:
        for j, cell in enumerate(r):
            if j < n_cols:
                col_widths[j] = max(col_widths[j], len(cell))

    # Re-render
    def make_separator() -> str:
        return "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

    def make_data_row(cells: list[str]) -> str:
        parts = []
        for j, cell in enumerate(cells):
            w = col_widths[j] if j < n_cols else len(cell)
            parts.append(" " + cell.ljust(w) + " ")
        return "|" + "|".join(parts) + "|"

    output: list[str] = []
    for idx, row in enumerate(rows):
        if idx in separator_positions:
            output.append(make_separator())
        elif len(row) > 1:
            output.append(make_data_row(row))
        elif len(row) == 1:
            output.append(row[0])

    return output


def _normalize_write_content(content: str) -> str:
    """Chain all write normalizers and warn if YAML is still broken."""
    content = _normalize_frontmatter_gap(content)
    content = _normalize_yaml_quoting(content)
    content = _normalize_ascii_tables(content)
    # Post-normalization check: log warning if frontmatter is still invalid
    if content.startswith("---\n"):
        end = content.find("\n---", 3)
        if end != -1:
            try:
                _yaml.safe_load(content[4:end])
            except _yaml.YAMLError as exc:
                log.warning("Write normalizer: YAML frontmatter still invalid after fix: %s", exc)
    return content

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
from dateutil.parser import parse as _dateutil_parse

# Shared state for loaded data
_loaded_df: pd.DataFrame | None = None
_loaded_records: list[dict] = []

def _text_match(text: str, keywords: str) -> bool:
    """Check if ALL keywords appear in text (case-insensitive, word-level).

    Splits keywords on whitespace, checks each word appears anywhere
    in the text.  Useful for fuzzy matching item descriptions in records.
    Example: text_match('2 TB SATA SSD drive', 'SATA SSD') → True
    """
    if not isinstance(text, str) or not isinstance(keywords, str):
        return False
    text_lower = text.lower()
    return all(w.lower() in text_lower for w in keywords.split())


# R1 D2: columns that MUST survive the _load_records JSON-serialization
# pass as native Python types (list[dict]) instead of being stringified.
# Downstream `calculate()` expressions use .apply(lambda items: ...) on
# these columns, which requires the native shape.
_LIST_COLUMN_EXEMPT: frozenset = frozenset({"line_items"})


# R5 (D6): proactive statement-keyword sniffer — catches "multi-line script"
# expressions BEFORE compile() so the LLM gets a targeted hint even when
# the string technically parses as valid Python.
#
# Regex is anchored to line start via (?m)^\s* so valid comprehensions with
# inline `for` tokens (e.g. `[x for x in records]`) do NOT match.
_STATEMENT_RE = re.compile(
    r"(?m)^\s*(import |from |def |class |for |while |async |return )"
    r"|;\s*\S"
)


def _detect_statement_keywords(expression: str) -> bool:
    """Return True if the expression looks like a Python *statement* rather
    than an expression (R5 D6)."""
    return bool(_STATEMENT_RE.search(expression))


# R5 AC3: structured error hint returned on SyntaxError or sniffer hit.
_CALCULATE_EXPRESSION_HINT = (
    "calculate() accepts only Python expressions, not statements. "
    "Rewrite as a comprehension: [x for x in records if cond(x)] instead of "
    "'for x in records: ...'. Do not use import, def, for, while, or ;. "
    "For intermediate variables, use a comprehension or nested "
    "df.query()/df.apply() calls."
)


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
    # Text helpers
    "text_match": _text_match,
    # Date parsing (flexible — handles many formats)
    "parse_date": lambda s: _dateutil_parse(s, fuzzy=True).strftime("%Y-%m-%d"),
    # Pandas
    "pd": pd,
}


def _safe_calculate(expression: str) -> str:
    """Evaluate expression with pandas, arithmetic, and date helpers.

    The expression runs in a restricted namespace: no __builtins__,
    no imports. Only pre-approved functions, pandas, and loaded data
    (df, records) are accessible.
    """
    # R5 D6: proactive sniffer — catch statement-style expressions BEFORE
    # compile() so the LLM gets a targeted hint even when the string would
    # have parsed (e.g. a bare `import os`).
    if _detect_statement_keywords(expression):
        return f"Error: {_CALCULATE_EXPRESSION_HINT}"

    ns = dict(_CALC_NAMESPACE)
    if _loaded_df is not None:
        ns["df"] = _loaded_df
    ns["records"] = list(_loaded_records)

    # R5 AC3 + AC4: SyntaxError branch returns the structured hint plus the
    # original SyntaxError detail (msg + offset). Wrapping compile() in its
    # own try block keeps runtime errors routed to the existing outer catch.
    try:
        compiled = compile(expression, "<calc>", "eval")
    except SyntaxError as exc:
        offset = getattr(exc, "offset", None)
        detail = f"SyntaxError: {exc.msg}"
        if offset is not None:
            detail += f" (offset={offset})"
        return f"Error: {_CALCULATE_EXPRESSION_HINT} [{detail}]"

    try:
        result = eval(compiled, ns)  # noqa: S307 — restricted namespace, agent-generated only
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


def _parse_ascii_table(text: str) -> dict | None:
    """Extract key-value pairs from an ASCII table in a markdown file.

    Parses tables like:
        +----------------+-----------------------------+
        | field          | value                       |
        +----------------+-----------------------------+
        | record_type    | bill                        |
        | purchased_on   | 2026-02-07                  |
        +----------------+-----------------------------+

    Returns a dict of {field: value} pairs, or None if no parseable table.
    """
    # Find ASCII table in the content
    lines = text.split("\n")
    record: dict = {}
    in_table = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"^\+[-+]+\+$", stripped):
            in_table = True
            continue
        if in_table and stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if len(cells) == 2:
                key, val = cells[0], cells[1]
                # Skip header row and empty values
                if key and val and key != "field" and val != "value":
                    record[key] = val
        elif in_table and not stripped.startswith("|") and not re.match(r"^\+[-+]+\+$", stripped):
            # End of table block — but might be more tables
            if record and len(record) >= 3:
                break  # Got enough from the main fields table
            in_table = False

    return record if len(record) >= 3 else None


def _parse_line_items_table(text: str) -> list[dict]:
    """R1: parse an ASCII/pipe line-items table into a list of dicts.

    Accepts both 4-column `| item | qty | unit_eur | line_eur |` and
    5-column `| # | item | qty | unit_eur | line_eur |` variants. The
    leading `#` index column is optional. Output dicts conform to D1:
    ``{item: str, qty: int|float, unit_eur: float, line_eur: float}``.

    Null-safety (D1): missing numeric fields default to ``0``; missing
    string field ``item`` defaults to ``""``. Malformed rows (wrong
    column count, header rows, separator rows, total/summary rows)
    are dropped from the list. If the input contains no parseable
    table, returns ``[]``.

    Non-ASCII cell content (CJK, umlauts) passes through byte-for-byte:
    the separator regex matches only ASCII ``+``/``-``/``|`` framing,
    never the cell content itself (research Q1).
    """
    if not text:
        return []

    # A "data row" is any line that starts and ends with `|` after strip
    # and is NOT an ASCII separator like `+---+---+`.
    results: list[dict] = []
    header_map: dict[str, int] | None = None  # column-name → index

    for raw in text.split("\n"):
        stripped = raw.strip()
        if not stripped:
            continue
        # ASCII separator rows (+---+---+ or |---|---|)
        if re.match(r"^[+|][-+|:\s]+[+|]$", stripped):
            continue
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue

        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if not cells:
            continue

        # First data-like row sets the header if it looks like column names.
        # Recognize known column-name tokens.
        tokens_lower = [c.lower() for c in cells]
        if header_map is None:
            known = {"item", "qty", "unit_eur", "line_eur"}
            if any(t in known for t in tokens_lower):
                header_map = {
                    tokens_lower[i]: i for i in range(len(tokens_lower))
                }
                continue
            # Otherwise: no header — fall through and try to treat this as
            # the first data row under an implicit 4-column schema.
            if len(cells) == 4:
                header_map = {"item": 0, "qty": 1, "unit_eur": 2, "line_eur": 3}
            elif len(cells) == 5:
                header_map = {"#": 0, "item": 1, "qty": 2, "unit_eur": 3, "line_eur": 4}
            else:
                continue

        # Parse a data row using the established header.
        if len(cells) != len(header_map):
            continue
        if not all(k in header_map for k in ("item", "qty", "unit_eur", "line_eur")):
            continue
        item_val = cells[header_map["item"]]
        qty_raw = cells[header_map["qty"]]
        unit_raw = cells[header_map["unit_eur"]]
        line_raw = cells[header_map["line_eur"]]

        # Skip header/separator/total rows that sneak through as data.
        if item_val.lower() in {"item", "name"}:
            continue
        # Total / summary rows typically have the item slot empty or named
        # "TOTAL"; they also usually lack qty + unit_eur. Drop them.
        if item_val.upper() == "TOTAL" and not qty_raw and not unit_raw:
            continue

        def _num(s: str, prefer_int: bool = False):
            s = s.strip()
            if not s:
                return 0 if prefer_int else 0.0
            # Strip currency symbols and thousands separators defensively.
            s = s.replace(",", "").replace("€", "").replace("$", "").strip()
            try:
                if prefer_int and "." not in s:
                    return int(s)
                return float(s)
            except ValueError:
                return 0 if prefer_int else 0.0

        qty = _num(qty_raw, prefer_int=True)
        unit_eur = _num(unit_raw)
        line_eur = _num(line_raw)
        results.append({
            "item": item_val,
            "qty": qty,
            "unit_eur": unit_eur,
            "line_eur": line_eur,
        })

    return results


def _tokenize_name_query(text: str) -> list[str]:
    """R3 AC2: lowercase + hyphen-split + whitespace-collapsed tokens.

    Shared between ``_find_project`` and the ``_name_keywords`` synthetic
    column so the query and the row text use identical tokenization.
    """
    if not isinstance(text, str):
        return []
    return text.lower().replace("-", " ").split()


def _find_project(query: str, df) -> "pd.DataFrame":
    """R3 D4: helper exposing the ``_name_keywords`` fallback lookup.

    Tokenizes ``query`` via :func:`_tokenize_name_query`, joins the
    tokens with ``|`` (regex alternation) and filters ``df`` against its
    ``_name_keywords`` column. Returns the filtered frame so the caller
    can inspect ``.shape[0]`` to detect ambiguous matches per R3 AC3.

    If the frame lacks ``_name_keywords`` (e.g. a non-``projects/`` load),
    the helper returns an empty slice instead of raising — matching
    ``load_records``' safe-default ethos.
    """
    if df is None:
        return df
    if "_name_keywords" not in df.columns:
        return df.iloc[0:0]
    tokens = _tokenize_name_query(query)
    if not tokens:
        return df.iloc[0:0]
    # Regex-escape each token and OR them; case-insensitive match against
    # the deterministically-tokenized column.
    alt = "|".join(re.escape(t) for t in tokens)
    mask = df["_name_keywords"].str.contains(alt, case=False, na=False, regex=True)
    return df[mask]


# Cache for LLM-generated parsers: folder_path → callable
_generated_parsers: dict = {}


def _generate_parser_from_sample(
    sample_content: str, config: "AgentConfig", model: str, metadata: dict | None,
):
    """Use a single LLM call to generate a Python extraction function from sample content.

    Returns a callable(content: str) -> dict or None on failure.
    The generated code runs in a restricted namespace (same security model
    as _safe_calculate — no real builtins, agent-controlled input only).
    """
    from agent.llm import call_llm_no_tools

    prompt = (
        "Analyze this file content and write a Python function body that "
        "extracts all structured key-value fields into a dictionary.\n\n"
        "RULES:\n"
        "- The function signature is: def extract(content: str) -> dict\n"
        "- Return a dict of {field_name: value} with string values\n"
        "- Extract ALL fields you find (record_type, dates, amounts, names, etc.)\n"
        "- Also add a '_body' key with the full content (max 2000 chars)\n"
        "- Only use standard Python (re, str methods). No imports needed.\n"
        "- Return empty dict {} if parsing fails\n"
        "- Output ONLY the function body inside ```python``` markers, nothing else\n\n"
        f"SAMPLE FILE:\n```\n{sample_content[:2000]}\n```"
    )

    try:
        resp = call_llm_no_tools(
            config, model,
            [{"role": "user", "content": prompt}],
            metadata=metadata, max_tokens=1024,
        )
        code = resp.choices[0].message.content.strip()
        # Extract code from markdown fence
        if "```python" in code:
            code = code.split("```python", 1)[1].split("```", 1)[0].strip()
        elif "```" in code:
            code = code.split("```", 1)[1].split("```", 1)[0].strip()

        # Wrap in function definition if not already
        if not code.startswith("def extract"):
            code = "def extract(content):\n" + "\n".join(
                f"    {line}" if line.strip() else line for line in code.split("\n")
            )

        # Compile and extract the function in a restricted namespace
        # Security: restricted builtins (same model as _safe_calculate),
        # code is from our own LLM call, not external user input
        ns: dict = {
            "re": re,
            "__builtins__": {
                "dict": dict, "str": str, "len": len, "list": list,
                "int": int, "float": float, "enumerate": enumerate,
                "range": range, "True": True, "False": False, "None": None,
                "isinstance": isinstance, "ValueError": ValueError,
                "Exception": Exception, "min": min, "max": max, "zip": zip,
            },
        }
        compiled = compile(code, "<llm-parser>", "exec")
        # Restricted exec — same security model as calculate()'s eval()
        _run_compiled(compiled, ns)
        fn = ns.get("extract")
        if fn is None:
            return None

        # Validate: the function should return a dict on the sample
        test_result = fn(sample_content)
        if isinstance(test_result, dict) and len(test_result) >= 2:
            log.info("Generated parser OK: %d fields from sample", len(test_result))
            return fn
        return None
    except Exception as exc:
        log.warning("Parser generation failed: %s", exc)
        return None


def _run_compiled(compiled, ns):
    """Execute compiled code in namespace. Isolated for security audit."""
    exec(compiled, ns)  # noqa: S102 — restricted namespace, LLM-generated parser only


def _load_records(vm, path: str, config: "AgentConfig | None" = None, model: str = "", metadata: dict | None = None, tm: "TaskManager | None" = None) -> str:
    """Load all structured files from a folder into a pandas DataFrame.

    Parsing strategy (three phases):
    1. Try JSON, YAML frontmatter, ASCII table (fast, deterministic)
    2. If many files unparsed AND model available, generate a Python parser
       via single LLM call and apply it (adaptive, one-shot)
    3. Build DataFrame, auto-detect types, extract dates from filenames

    If `tm` is provided, every successfully-read file is also registered
    via tm.track_read() so it appears in the agent's grounding_refs.
    Without this, aggregation tasks using load_records + calculate
    produce answers with no traceable source files, causing benchmark
    "missing required reference" failures.
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
    files = [e for e in entries if e.endswith((".json", ".md", ".txt")) and not e.upper().startswith(("README", "AGENTS"))]
    if not files:
        return f"No structured files found in {path}"

    # Phase 1: Read all file contents upfront
    file_contents: dict[str, str] = {}
    folder = path.strip("/")
    for fname in files:
        fpath = f"{folder}/{fname}"
        try:
            result = vm.read(ReadRequest(path=fpath))
            content = MessageToDict(result).get("content", "")
            if content:
                file_contents[fname] = content
                # Register as a grounding-eligible read so the final
                # answer can cite these files (benchmark may require it)
                if tm is not None:
                    tm.track_read(fpath)
        except Exception:
            pass

    # Phase 2: Try static parsers (fast, deterministic)
    records = []
    unparsed: dict[str, str] = {}
    for fname, content in file_contents.items():
        record = None
        if fname.endswith(".json"):
            try:
                record = json.loads(content)
                if not isinstance(record, dict):
                    record = None
            except json.JSONDecodeError:
                pass
        elif fname.endswith((".md", ".txt")):
            record = _parse_yaml_frontmatter(content)
            if record is not None:
                body_start = content.find("\n---", 3)
                if body_start != -1:
                    body = content[body_start + 4:].strip()
                    if body:
                        record["_body"] = body[:2000]
            else:
                record = _parse_ascii_table(content)
                if record is not None:
                    record["_body"] = content[:2000]

        if record and isinstance(record, dict):
            record["_file"] = fname
            try:
                parsed_dt = _dateutil_parse(fname, fuzzy=True)
                record["_date_from_file"] = parsed_dt.strftime("%Y-%m-%d")
            except (ValueError, OverflowError):
                pass
            # R1: populate the `line_items` column.
            # Frontmatter wins over body parse (D1 idempotence / R1.b).
            # Alias keys ``lines`` and ``items`` are also accepted.
            fm_items = None
            for alias in ("line_items", "lines", "items"):
                val = record.get(alias)
                if isinstance(val, list) and all(isinstance(x, dict) for x in val):
                    fm_items = val
                    break
            if fm_items is not None:
                # Shallow-normalize to the four-field schema with null-safety.
                normalized: list[dict] = []
                for raw in fm_items:
                    normalized.append({
                        "item": str(raw.get("item", raw.get("name", ""))),
                        "qty": raw.get("qty", raw.get("quantity", 0)),
                        "unit_eur": float(raw.get("unit_eur", raw.get("unit", raw.get("price", 0.0)) or 0.0)),
                        "line_eur": float(raw.get("line_eur", raw.get("line_total", raw.get("total", 0.0)) or 0.0)),
                    })
                record["line_items"] = normalized
            else:
                # Body-table parse; if the file has no table, this returns [].
                record["line_items"] = _parse_line_items_table(content)
            records.append(record)
        else:
            unparsed[fname] = content

    # Phase 3: LLM-generated parser for remaining unparsed files
    norm_path = path.strip("/")
    if unparsed and model and config:
        parser_fn = _generated_parsers.get(norm_path)
        if parser_fn is None:
            sample_fname = next(iter(unparsed))
            sample = unparsed[sample_fname]
            log.info("Generating parser for %s (%d unparsed files, sample: %s)",
                     path, len(unparsed), sample_fname)
            parser_fn = _generate_parser_from_sample(sample, config, model, metadata)
            if parser_fn:
                _generated_parsers[norm_path] = parser_fn

        if parser_fn:
            for fname, content in unparsed.items():
                try:
                    record = parser_fn(content)
                    if record and isinstance(record, dict) and len(record) >= 2:
                        record["_file"] = fname
                        if "_body" not in record:
                            record["_body"] = content[:2000]
                        try:
                            parsed_dt = _dateutil_parse(fname, fuzzy=True)
                            record["_date_from_file"] = parsed_dt.strftime("%Y-%m-%d")
                        except (ValueError, OverflowError):
                            pass
                        records.append(record)
                except Exception:
                    pass

    if not records:
        return f"No parseable records in {path} ({len(unparsed)} unparsed files)"

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

    # R3 D4: for projects/ loads, add a `_name_keywords` synthetic column
    # (lowercased + hyphen-split + whitespace-collapsed join of
    # name/goal/alias/notes) so indirect project references resolve via
    # df['_name_keywords'].str.contains(...) as a deterministic fallback
    # when exact-name match returns zero rows. Non-projects/ paths are
    # untouched.
    if path.strip("/").startswith("projects"):
        def _keywords_for(row):
            parts = [
                str(row.get("name", "") or ""),
                str(row.get("goal", "") or ""),
                str(row.get("alias", "") or ""),
                str(row.get("notes", "") or ""),
            ]
            joined = " ".join(parts).lower().replace("-", " ")
            return " ".join(joined.split())
        _loaded_df["_name_keywords"] = _loaded_df.apply(_keywords_for, axis=1)

    # Serialize list/dict columns to JSON strings for easier querying
    # EXCEPT for columns in _LIST_COLUMN_EXEMPT (R1 D2) — those stay as
    # native list[dict] so downstream .apply(lambda items: ...) queries
    # work uniformly.
    for col in _loaded_df.columns:
        if col in _LIST_COLUMN_EXEMPT:
            continue  # R1: preserve list[dict] for .apply() queries
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
        f"len(df[df['status'] == 'active']). "
        f"Helpers: text_match(text, keywords) for fuzzy item search "
        f"(all keywords must appear, case-insensitive); "
        f"_date_from_file column has date extracted from filename"
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
    model: str = "",
    metadata: dict | None = None,
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
        "load_records": lambda: _load_records(vm, args.get("path", ""), config=config, model=model, metadata=metadata, tm=tm),
        "load_skill": lambda: load_skill(vm, skill_loader, args.get("name", args.get("path", ""))) if skill_loader else "Error: no skill loader",
        "write": lambda: vm.write(WriteRequest(path=args["path"], content=_normalize_write_content(args["content"]))),
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
        if name == "read":
            # Find the most recent pending op for this path, if any.
            # Last-op wins: delete→write means the file exists (re-created),
            # write→delete means it's gone, pure write means it exists.
            last_op = None
            last_content = None
            for pw in tm.pending_writes:
                pw_path = pw["args"].get("path", "").lstrip("/")
                if pw_path == norm:
                    last_op = pw["op"]
                    if pw["op"] == "write":
                        last_content = pw["args"].get("content", "")
            if norm in deleted_norms and last_op != "write":
                return json.dumps({"error": f"File not found: {path} (deleted)"})
            # Reading a path that has a pending write → return the written
            # content (agent reads its own deferred write).  Without this,
            # the VM returns "file not found" because the write hasn't been
            # applied yet, which triggers spurious fabrication-drop.
            if last_op == "write" and last_content is not None:
                return json.dumps({"content": last_content}, indent=2)
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
                load_result = _load_records(vm, list_path, tm=tm)
                if "Loaded" in load_result:
                    txt += f"\n\n[AUTO] {load_result}"
            except Exception:
                pass  # silent fallback — agent reads files normally

    return txt
