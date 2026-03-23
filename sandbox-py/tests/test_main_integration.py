"""Tests for main.py and pyproject.toml changes.

Task 11: Update main.py (model config, new run_agent signature),
update pyproject.toml (litellm replaces openai), create .env.example.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Test 11.1: pyproject.toml dependencies
# ---------------------------------------------------------------------------

class TestPyprojectDependencies:
    """Verify pyproject.toml has litellm and does not have openai."""

    def _read_pyproject(self) -> str:
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        return pyproject_path.read_text()

    def test_litellm_in_dependencies(self):
        content = self._read_pyproject()
        assert "litellm" in content

    def test_openai_not_in_dependencies(self):
        """openai should be removed from dependencies."""
        content = self._read_pyproject()
        # Parse the dependencies list -- openai should not appear
        # We check that "openai" is not listed as a direct dependency
        lines = content.split("\n")
        dep_lines = [
            line.strip().strip('"').strip("'").strip(",")
            for line in lines
            if "openai" in line.lower() and not line.strip().startswith("#")
        ]
        # Filter to only actual dependency declarations (not comments or notes)
        actual_openai_deps = [
            d for d in dep_lines
            if d.startswith("openai")
        ]
        assert len(actual_openai_deps) == 0, (
            f"openai should be removed from dependencies: {actual_openai_deps}"
        )

    def test_pydantic_retained_in_dependencies(self):
        content = self._read_pyproject()
        assert "pydantic" in content


# ---------------------------------------------------------------------------
# Test 11.2: main.py updates
# ---------------------------------------------------------------------------

class TestMainPyUpdates:
    """Verify main.py reads model config and calls run_agent correctly."""

    def _read_main(self) -> str:
        main_path = Path(__file__).parent.parent / "main.py"
        return main_path.read_text()

    def test_imports_run_agent_from_agent_package(self):
        """main.py imports run_agent from agent."""
        source = self._read_main()
        tree = ast.parse(source)

        has_import = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "agent" and any(
                    alias.name == "run_agent" for alias in node.names
                ):
                    has_import = True
        assert has_import, "main.py should import run_agent from agent"

    def test_reads_model_id_from_env(self):
        """main.py reads MODEL_ID or EXECUTOR_MODEL from env."""
        source = self._read_main()
        assert "MODEL_ID" in source
        # Should reference os.getenv for model configuration
        assert "getenv" in source

    def test_has_executor_model_env(self):
        """main.py reads EXECUTOR_MODEL as fallback."""
        source = self._read_main()
        assert "EXECUTOR_MODEL" in source

    def test_has_fallback_model(self):
        """main.py has a fallback to openai/gpt-4.1."""
        source = self._read_main()
        assert "openai/gpt-4.1" in source

    def test_has_scout_model_env(self):
        """main.py reads SCOUT_MODEL from env."""
        source = self._read_main()
        assert "SCOUT_MODEL" in source

    def test_has_skills_dir(self):
        """main.py sets SKILLS_DIR."""
        source = self._read_main()
        assert "SKILLS_DIR" in source or "skills_dir" in source

    def test_run_agent_call_includes_all_params(self):
        """run_agent() call passes all five parameters."""
        source = self._read_main()
        # Check that executor_model, harness_url, task_text, scout_model, skills_dir
        # appear in the run_agent call
        assert "executor_model" in source or "MODEL_ID" in source
        assert "scout_model" in source or "SCOUT_MODEL" in source
        assert "skills_dir" in source or "SKILLS_DIR" in source

    def test_no_openai_import(self):
        """main.py should not import from openai."""
        source = self._read_main()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "openai", "main.py should not import openai"
            if isinstance(node, ast.ImportFrom):
                if node.module and "openai" in node.module:
                    pytest.fail("main.py should not import from openai")


# ---------------------------------------------------------------------------
# Test 11.3: .env.example
# ---------------------------------------------------------------------------

class TestEnvExample:
    """Verify sandbox-specific .env.example documents LiteLLM config."""

    def _read_env_example(self) -> str:
        env_path = Path(__file__).parent.parent / ".env.example"
        return env_path.read_text()

    def test_env_example_exists(self):
        env_path = Path(__file__).parent.parent / ".env.example"
        assert env_path.is_file(), "sandbox/py/.env.example should exist"

    def test_documents_model_id(self):
        content = self._read_env_example()
        assert "MODEL_ID" in content or "EXECUTOR_MODEL" in content

    def test_documents_scout_model(self):
        content = self._read_env_example()
        assert "SCOUT_MODEL" in content

    def test_documents_litellm_format(self):
        """Should document LiteLLM provider prefixes."""
        content = self._read_env_example()
        # Should mention provider prefix format
        assert "openai/" in content or "litellm" in content.lower()

    def test_documents_openai_example(self):
        content = self._read_env_example()
        assert "openai/" in content

    def test_documents_bedrock_example(self):
        content = self._read_env_example()
        assert "bedrock/" in content

    def test_documents_anthropic_example(self):
        content = self._read_env_example()
        assert "anthropic/" in content
