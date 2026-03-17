"""Tests for agent.tools -- OpenAI-compatible function schema definitions.

TDD: These tests are written BEFORE the implementation exists.
Task 1.2: TOOL_SCHEMAS list with 8 tool definitions, TOOL_NAMES set.
Task 1.3: Each schema has type:"function", function.name, function.description,
           function.parameters with proper JSON Schema.
"""

import pytest


def test_tool_schemas_is_list():
    from agent.tools import TOOL_SCHEMAS
    assert isinstance(TOOL_SCHEMAS, list)


def test_tool_schemas_has_eight_entries():
    from agent.tools import TOOL_SCHEMAS
    assert len(TOOL_SCHEMAS) == 8


def test_tool_names_is_set():
    from agent.tools import TOOL_NAMES
    assert isinstance(TOOL_NAMES, set)


def test_tool_names_has_eight_entries():
    from agent.tools import TOOL_NAMES
    assert len(TOOL_NAMES) == 8


EXPECTED_TOOL_NAMES = {
    "tree",
    "list_dir",
    "read_file",
    "write_file",
    "delete_file",
    "search",
    "report_completion",
    "load_skill",
}


def test_tool_names_match_expected():
    from agent.tools import TOOL_NAMES
    assert TOOL_NAMES == EXPECTED_TOOL_NAMES


def test_tool_names_match_schemas():
    """TOOL_NAMES must be derived from TOOL_SCHEMAS, not maintained separately."""
    from agent.tools import TOOL_SCHEMAS, TOOL_NAMES
    names_from_schemas = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert names_from_schemas == TOOL_NAMES


class TestSchemaStructure:
    """Task 1.3: Every schema has required fields."""

    @pytest.fixture
    def schemas(self):
        from agent.tools import TOOL_SCHEMAS
        return TOOL_SCHEMAS

    def test_each_schema_has_type_function(self, schemas):
        for schema in schemas:
            assert schema["type"] == "function", (
                f"Schema missing type:'function': {schema}"
            )

    def test_each_schema_has_function_name(self, schemas):
        for schema in schemas:
            assert "name" in schema["function"], (
                f"Schema missing function.name: {schema}"
            )
            assert isinstance(schema["function"]["name"], str)
            assert len(schema["function"]["name"]) > 0

    def test_each_schema_has_function_description(self, schemas):
        for schema in schemas:
            assert "description" in schema["function"], (
                f"Schema missing function.description: {schema}"
            )
            assert isinstance(schema["function"]["description"], str)
            assert len(schema["function"]["description"]) > 0

    def test_each_schema_has_function_parameters(self, schemas):
        for schema in schemas:
            params = schema["function"]["parameters"]
            assert "type" in params
            assert params["type"] == "object"
            assert "properties" in params

    def test_each_schema_has_required_field(self, schemas):
        for schema in schemas:
            params = schema["function"]["parameters"]
            assert "required" in params, (
                f"Schema {schema['function']['name']} missing 'required' field"
            )
            assert isinstance(params["required"], list)


class TestSpecificToolSchemas:
    """Validate individual tool schemas match the design spec (section 4.1)."""

    @pytest.fixture
    def schema_map(self):
        from agent.tools import TOOL_SCHEMAS
        return {s["function"]["name"]: s for s in TOOL_SCHEMAS}

    def test_tree_has_path_param(self, schema_map):
        params = schema_map["tree"]["function"]["parameters"]
        assert "path" in params["properties"]
        assert "path" in params["required"]

    def test_list_dir_has_path_param(self, schema_map):
        params = schema_map["list_dir"]["function"]["parameters"]
        assert "path" in params["properties"]
        assert "path" in params["required"]

    def test_read_file_has_path_param(self, schema_map):
        params = schema_map["read_file"]["function"]["parameters"]
        assert "path" in params["properties"]
        assert "path" in params["required"]

    def test_write_file_has_path_and_content(self, schema_map):
        params = schema_map["write_file"]["function"]["parameters"]
        assert "path" in params["properties"]
        assert "content" in params["properties"]
        assert "path" in params["required"]
        assert "content" in params["required"]

    def test_delete_file_has_path_param(self, schema_map):
        params = schema_map["delete_file"]["function"]["parameters"]
        assert "path" in params["properties"]
        assert "path" in params["required"]

    def test_search_has_pattern_and_optional_path_count(self, schema_map):
        params = schema_map["search"]["function"]["parameters"]
        assert "pattern" in params["properties"]
        assert "pattern" in params["required"]
        # path and count should exist but may or may not be required
        assert "path" in params["properties"]
        assert "count" in params["properties"]

    def test_report_completion_has_answer_refs_steps_code(self, schema_map):
        params = schema_map["report_completion"]["function"]["parameters"]
        assert "answer" in params["properties"]
        assert "grounding_refs" in params["properties"]
        assert "steps" in params["properties"]
        assert "code" in params["properties"]
        assert "answer" in params["required"]

    def test_load_skill_has_name_param(self, schema_map):
        params = schema_map["load_skill"]["function"]["parameters"]
        assert "name" in params["properties"]
        assert "name" in params["required"]

    def test_grounding_refs_is_array_of_strings(self, schema_map):
        props = schema_map["report_completion"]["function"]["parameters"]["properties"]
        assert props["grounding_refs"]["type"] == "array"
        assert props["grounding_refs"]["items"]["type"] == "string"

    def test_steps_is_array_of_strings(self, schema_map):
        props = schema_map["report_completion"]["function"]["parameters"]["properties"]
        assert props["steps"]["type"] == "array"
        assert props["steps"]["items"]["type"] == "string"

    def test_search_count_has_default(self, schema_map):
        props = schema_map["search"]["function"]["parameters"]["properties"]
        assert "default" in props["count"], "search.count should have a default value"
        assert props["count"]["default"] == 5


class TestToolsModuleIsLeaf:
    """Task 1.2: tools.py must have zero imports from other agent/ modules."""

    def test_no_agent_imports(self):
        import importlib
        import agent.tools as mod
        source_file = mod.__file__
        assert source_file is not None
        with open(source_file) as f:
            source = f.read()
        # Should not import from agent.anything
        import re
        agent_imports = re.findall(r"from\s+agent\.", source)
        assert agent_imports == [], (
            f"tools.py must not import from agent modules: {agent_imports}"
        )
