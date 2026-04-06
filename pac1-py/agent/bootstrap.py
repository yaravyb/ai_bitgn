import json
import logging

from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import FindRequest, ReadRequest, TreeRequest
from google.protobuf.json_format import MessageToDict

from agent.prompts import CLI_BOLD, CLI_CLR, CLI_CYAN, CLI_DIM, CLI_RED, CLI_YELLOW

log = logging.getLogger(__name__)


def phase1_bootstrap(vm: PcmRuntimeClientSync) -> dict:
    """General-purpose workspace discovery. No LLM calls.

    Returns a context dict with:
      - directory_tree: full tree output (string)
      - agents_md: concatenated content of all AGENTS.md files
      - readmes: concatenated README.md contents
      - skill_paths: list of doc paths from docs/ and 99_process/
    """
    ctx: dict = {"directory_tree": "", "agents_md": ""}

    print(f"\n{CLI_BOLD}{'─' * 50}{CLI_CLR}")
    print(f"{CLI_BOLD}Phase 1: Bootstrap{CLI_CLR} {CLI_DIM}(deterministic, no LLM){CLI_CLR}")
    print(f"{CLI_BOLD}{'─' * 50}{CLI_CLR}")

    # 1. Full directory tree
    try:
        result = vm.tree(TreeRequest(root=""))
        tree_json = MessageToDict(result)
        ctx["directory_tree"] = json.dumps(tree_json, indent=2)
        print(f"  {CLI_CYAN}tree{CLI_CLR} ✓")
    except Exception as exc:
        print(f"  {CLI_RED}tree ✗ {exc}{CLI_CLR}")
        log.warning("Phase 1: tree failed: %s", exc)

    # 2. Find and read ALL AGENTS.md files
    #    Primary: use find to locate them. Fallback: try known paths from tree.
    agents_paths: list[str] = []
    try:
        result = vm.find(FindRequest(name="AGENTS.md", root="/", type=1, limit=10))
        find_dict = MessageToDict(result)
        for entry in find_dict.get("entries", []):
            p = entry.get("path", "")
            if p:
                agents_paths.append(p)
        log.info("Phase 1: find returned %d entries: %s", len(agents_paths), agents_paths)
    except Exception as exc:
        log.warning("Phase 1: find AGENTS.md failed: %s", exc)

    # Fallback: extract AGENTS.md paths from the tree we already have
    if not agents_paths and ctx["directory_tree"]:
        def _extract_paths(node: dict, prefix: str = "", target: str = "AGENTS.MD") -> list[str]:
            paths = []
            name = node.get("name", "")
            if name == "/":
                current = ""
            else:
                current = f"{prefix}/{name}"
            if name.upper() == target and not node.get("isDir"):
                paths.append(current)
            for child in node.get("children", []):
                paths.extend(_extract_paths(child, current, target))
            return paths

        try:
            tree_data = json.loads(ctx["directory_tree"])
            root_node = tree_data.get("root", tree_data)
            agents_paths = _extract_paths(root_node, target="AGENTS.MD")
            if agents_paths:
                print(f"  {CLI_YELLOW}find fallback → extracted from tree: {agents_paths}{CLI_CLR}")
        except Exception:
            pass

    parts: list[str] = []
    for path in agents_paths:
        try:
            read_result = vm.read(ReadRequest(path=path))
            content = MessageToDict(read_result).get("content", "")
            if content:
                print(f"  {CLI_CYAN}read{CLI_CLR} {path} ✓")
                parts.append(f"## {path}\n\n{content}")
        except Exception as exc:
            log.warning("Phase 1: read %s failed: %s", path, exc)

    ctx["agents_md"] = "\n\n---\n\n".join(parts)

    # 3. Read all README.md files (folder conventions, formats, sequences)
    readme_paths: list[str] = []
    if ctx["directory_tree"]:
        try:
            tree_data = json.loads(ctx["directory_tree"])
            root_node = tree_data.get("root", tree_data)
            readme_paths = _extract_paths(root_node, target="README.MD")
        except Exception:
            pass

    readme_parts: list[str] = []
    for path in readme_paths:
        try:
            read_result = vm.read(ReadRequest(path=path))
            content = MessageToDict(read_result).get("content", "")
            if content:
                print(f"  {CLI_CYAN}read{CLI_CLR} {path} ✓")
                readme_parts.append(f"## {path}\n\n{content}")
        except Exception:
            pass
    ctx["readmes"] = "\n\n---\n\n".join(readme_parts)

    # 4. Discover available skills (process docs, workflow docs)
    #    Layer 1: just file paths for the system prompt
    def _extract_doc_paths(node: dict, prefix: str = "") -> list[str]:
        """Extract .md file paths from docs/ and 99_process/ folders."""
        paths = []
        name = node.get("name", "")
        if name == "/":
            current = ""
        else:
            current = f"{prefix}/{name}"
        is_dir = node.get("isDir", False)
        # Only look inside docs/ and 99_process/
        if not is_dir and name.endswith(".md") and name.upper() not in ("AGENTS.MD", "README.MD"):
            if any(p in current.lower() for p in ("/docs/", "/99_process/")):
                paths.append(current)
        for child in node.get("children", []):
            paths.extend(_extract_doc_paths(child, current))
        return paths

    skill_paths: list[str] = []
    if ctx["directory_tree"]:
        try:
            tree_data = json.loads(ctx["directory_tree"])
            root_node = tree_data.get("root", tree_data)
            skill_paths = _extract_doc_paths(root_node)
        except Exception:
            pass
    ctx["skill_paths"] = skill_paths
    if skill_paths:
        print(f"  {CLI_CYAN}skills{CLI_CLR} {len(skill_paths)} docs found")

    return ctx
