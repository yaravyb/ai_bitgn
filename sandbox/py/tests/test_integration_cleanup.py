"""Tests for Task 12: Delete legacy agent.py and verify integration.

Verifies:
- Legacy agent.py is deleted
- Import works from agent package
- No circular imports in leaf modules
- run_agent function signature matches expectations
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Test 12.1: Legacy agent.py is deleted
# ---------------------------------------------------------------------------

class TestLegacyAgentDeleted:
    """Verify the monolithic agent.py file is removed."""

    def test_agent_py_does_not_exist(self):
        """sandbox/py/agent.py should not exist."""
        legacy_path = Path(__file__).parent.parent / "agent.py"
        assert not legacy_path.is_file(), (
            "Legacy agent.py should be deleted (replaced by agent/ package)"
        )


# ---------------------------------------------------------------------------
# Test 12.2: main.py imports from agent package
# ---------------------------------------------------------------------------

class TestMainImportsAgent:
    """Verify main.py imports run_agent from the agent package."""

    def test_from_agent_import_run_agent_works(self):
        """Can import run_agent from agent package."""
        from agent import run_agent
        assert callable(run_agent)

    def test_import_has_correct_signature(self):
        """run_agent has the expected five parameters."""
        from agent import run_agent
        sig = inspect.signature(run_agent)
        params = list(sig.parameters.keys())
        assert params == [
            "executor_model", "harness_url", "task_text",
            "scout_model", "skills_dir",
        ]


# ---------------------------------------------------------------------------
# Test 12.3: No circular imports -- leaf modules
# ---------------------------------------------------------------------------

class TestCircularImports:
    """Verify leaf modules have no imports from other agent/ modules."""

    LEAF_MODULES = ["dag", "tracker", "tools", "llm", "prompt", "skills"]

    def _get_agent_imports(self, module_name: str) -> set[str]:
        """Parse module source and return set of agent.* imports."""
        module_path = Path(__file__).parent.parent / "agent" / f"{module_name}.py"
        if not module_path.is_file():
            pytest.skip(f"{module_name}.py does not exist")
        source = module_path.read_text()
        tree = ast.parse(source)

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("agent."):
                    imported_module = node.module.replace("agent.", "")
                    imports.add(imported_module)
        return imports

    def test_dag_has_no_agent_imports(self):
        imports = self._get_agent_imports("dag")
        assert len(imports) == 0, f"dag.py should not import from agent/: {imports}"

    def test_tracker_has_no_agent_imports(self):
        imports = self._get_agent_imports("tracker")
        assert len(imports) == 0, f"tracker.py should not import from agent/: {imports}"

    def test_tools_has_no_agent_imports(self):
        imports = self._get_agent_imports("tools")
        assert len(imports) == 0, f"tools.py should not import from agent/: {imports}"

    def test_llm_has_no_agent_imports(self):
        imports = self._get_agent_imports("llm")
        assert len(imports) == 0, f"llm.py should not import from agent/: {imports}"

    def test_prompt_has_no_agent_imports(self):
        imports = self._get_agent_imports("prompt")
        assert len(imports) == 0, f"prompt.py should not import from agent/: {imports}"

    def test_skills_has_no_agent_imports(self):
        imports = self._get_agent_imports("skills")
        assert len(imports) == 0, f"skills.py should not import from agent/: {imports}"

    def test_only_loop_imports_all_others(self):
        """loop.py is the only module that imports from all agent modules."""
        loop_imports = self._get_agent_imports("loop")
        expected = {"scout", "llm", "dispatch", "prompt", "skills", "tracker", "tools"}
        assert expected.issubset(loop_imports), (
            f"loop.py missing imports: {expected - loop_imports}"
        )

    def test_dispatch_only_imports_tracker_llm_tools(self):
        """dispatch.py should only import from tracker and llm (for ToolCall type)."""
        imports = self._get_agent_imports("dispatch")
        # dispatch imports tracker and llm (for ToolCall type)
        allowed = {"tracker", "llm", "tools"}
        assert imports.issubset(allowed), (
            f"dispatch.py imports beyond allowed set: {imports - allowed}"
        )

    def test_scout_only_imports_dag_dispatch_tracker(self):
        """scout.py should only import from dag, dispatch, tracker."""
        imports = self._get_agent_imports("scout")
        allowed = {"dag", "dispatch", "tracker"}
        assert imports.issubset(allowed), (
            f"scout.py imports beyond allowed set: {imports - allowed}"
        )


# ---------------------------------------------------------------------------
# Test 12.4: run_agent function signature
# ---------------------------------------------------------------------------

class TestRunAgentSignature:
    """Verify the run_agent function signature matches design expectations."""

    def test_run_agent_from_agent_package(self):
        from agent import run_agent
        sig = inspect.signature(run_agent)
        params = sig.parameters

        assert "executor_model" in params
        # With from __future__ import annotations, annotations are strings
        assert "str" in str(params["executor_model"].annotation)

        assert "harness_url" in params
        assert "str" in str(params["harness_url"].annotation)

        assert "task_text" in params
        assert "str" in str(params["task_text"].annotation)

        assert "scout_model" in params
        # scout_model should be optional (str | None)
        assert params["scout_model"].default is None

        assert "skills_dir" in params
        # skills_dir should be optional
        assert params["skills_dir"].default is None

    def test_run_agent_return_type_is_none(self):
        from agent import run_agent
        sig = inspect.signature(run_agent)
        ret = str(sig.return_annotation)
        assert ret == "None" or sig.return_annotation is None
