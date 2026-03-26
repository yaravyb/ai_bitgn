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


def test_tool_schemas_has_thirteen_entries():
    from agent.tools import TOOL_SCHEMAS
    assert len(TOOL_SCHEMAS) == 14


def test_tool_names_is_set():
    from agent.tools import TOOL_NAMES
    assert isinstance(TOOL_NAMES, set)


def test_tool_names_has_thirteen_entries():
    from agent.tools import TOOL_NAMES
    assert len(TOOL_NAMES) == 14


EXPECTED_TOOL_NAMES = {
    "tree",
    "list_dir",
    "read_file",
    "write_file",
    "delete_file",
    "search",
    "report_completion",
    "load_skill",
    "compact",
    "plan_create",
    "plan_step_done",
    "plan_step_skip",
    "plan_status",
    "plan_note",
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

    def test_each_schema_has_required_field_when_properties_exist(self, schemas):
        for schema in schemas:
            params = schema["function"]["parameters"]
            # Tools with no properties (e.g., compact) may omit 'required'
            if params.get("properties"):
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


# ---------------------------------------------------------------------------
# SCOUT_TOOL_SCHEMAS tests (Task 1)
# ---------------------------------------------------------------------------

class TestScoutToolSchemas:
    """Task 1: SCOUT_TOOL_SCHEMAS is a read-only subset of TOOL_SCHEMAS."""

    def test_scout_tool_schemas_exists(self):
        from agent.tools import SCOUT_TOOL_SCHEMAS
        assert isinstance(SCOUT_TOOL_SCHEMAS, list)

    def test_scout_tool_schemas_has_four_entries(self):
        from agent.tools import SCOUT_TOOL_SCHEMAS
        assert len(SCOUT_TOOL_SCHEMAS) == 4

    def test_scout_tool_schemas_contains_correct_tools(self):
        from agent.tools import SCOUT_TOOL_SCHEMAS
        names = {s["function"]["name"] for s in SCOUT_TOOL_SCHEMAS}
        assert names == {"tree", "list_dir", "read_file", "search"}

    def test_scout_tool_schemas_is_subset_of_tool_schemas(self):
        """SCOUT_TOOL_SCHEMAS entries must be the same objects from TOOL_SCHEMAS."""
        from agent.tools import TOOL_SCHEMAS, SCOUT_TOOL_SCHEMAS
        for scout_schema in SCOUT_TOOL_SCHEMAS:
            assert scout_schema in TOOL_SCHEMAS, (
                f"Scout schema {scout_schema['function']['name']} not in TOOL_SCHEMAS"
            )

    def test_scout_tool_schemas_derived_by_filtering(self):
        """Schemas must be the exact same dict objects (not copies)."""
        from agent.tools import TOOL_SCHEMAS, SCOUT_TOOL_SCHEMAS
        tool_map = {id(s): s for s in TOOL_SCHEMAS}
        for scout_schema in SCOUT_TOOL_SCHEMAS:
            assert id(scout_schema) in tool_map, (
                "SCOUT_TOOL_SCHEMAS must reference same objects as TOOL_SCHEMAS"
            )

    def test_scout_tool_names_is_frozenset(self):
        from agent.tools import _SCOUT_TOOL_NAMES
        assert isinstance(_SCOUT_TOOL_NAMES, frozenset)

    def test_existing_exports_unchanged(self):
        """TOOL_SCHEMAS and TOOL_NAMES must still be present and correct."""
        from agent.tools import TOOL_SCHEMAS, TOOL_NAMES
        assert len(TOOL_SCHEMAS) == 14
        assert len(TOOL_NAMES) == 14


class TestGetToolSchemas:
    """get_tool_schemas returns runtime-appropriate schemas."""

    def test_mini_returns_base_tools(self):
        from agent.tools import get_tool_schemas
        schemas = get_tool_schemas("mini")
        names = {s["function"]["name"] for s in schemas}
        assert "tree" in names
        assert "find" not in names
        assert "mkdir" not in names
        assert "move" not in names

    def test_pcm_includes_extra_tools(self):
        from agent.tools import get_tool_schemas
        schemas = get_tool_schemas("pcm")
        names = {s["function"]["name"] for s in schemas}
        assert "tree" in names
        assert "find" in names
        assert "mkdir" in names
        assert "move" in names

    def test_pcm_find_schema_has_required_params(self):
        from agent.tools import get_tool_schemas
        schemas = get_tool_schemas("pcm")
        find_schema = next(s for s in schemas if s["function"]["name"] == "find")
        props = find_schema["function"]["parameters"]["properties"]
        assert "name" in props
        assert "root" in props

    def test_default_returns_mini(self):
        from agent.tools import get_tool_schemas
        schemas_default = get_tool_schemas()
        schemas_mini = get_tool_schemas("mini")
        assert len(schemas_default) == len(schemas_mini)

    def test_pcm_has_more_schemas_than_mini(self):
        from agent.tools import get_tool_schemas
        mini = get_tool_schemas("mini")
        pcm = get_tool_schemas("pcm")
        assert len(pcm) == len(mini) + 3


# ---------------------------------------------------------------------------
# Plan tool schema tests (Task 7.2)
# ---------------------------------------------------------------------------

class TestPlanToolSchemas:
    """Task 7.2: Plan tool schemas have correct structure and parameters."""

    @pytest.fixture
    def schema_map(self):
        from agent.tools import TOOL_SCHEMAS
        return {s["function"]["name"]: s for s in TOOL_SCHEMAS}

    def test_plan_create_exists(self, schema_map):
        assert "plan_create" in schema_map

    def test_plan_create_steps_param_is_array_of_strings(self, schema_map):
        params = schema_map["plan_create"]["function"]["parameters"]
        assert "steps" in params["properties"]
        steps_prop = params["properties"]["steps"]
        assert steps_prop["type"] == "array"
        assert steps_prop["items"]["type"] == "string"
        assert "steps" in params["required"]

    def test_plan_step_done_exists(self, schema_map):
        assert "plan_step_done" in schema_map

    def test_plan_step_done_step_index_required(self, schema_map):
        params = schema_map["plan_step_done"]["function"]["parameters"]
        assert "step_index" in params["properties"]
        assert "step_index" in params["required"]

    def test_plan_step_skip_exists(self, schema_map):
        assert "plan_step_skip" in schema_map

    def test_plan_step_skip_has_step_index_and_optional_reason(self, schema_map):
        params = schema_map["plan_step_skip"]["function"]["parameters"]
        assert "step_index" in params["properties"]
        assert params["properties"]["step_index"]["type"] == "integer"
        assert "step_index" in params["required"]
        assert "reason" in params["properties"]
        assert params["properties"]["reason"]["type"] == "string"
        # reason should NOT be required
        assert "reason" not in params["required"]

    def test_plan_status_exists(self, schema_map):
        assert "plan_status" in schema_map

    def test_plan_status_has_no_required_params(self, schema_map):
        params = schema_map["plan_status"]["function"]["parameters"]
        assert params["properties"] == {}

    def test_plan_tools_not_in_scout_schemas(self):
        from agent.tools import SCOUT_TOOL_SCHEMAS
        names = {s["function"]["name"] for s in SCOUT_TOOL_SCHEMAS}
        for plan_tool in ("plan_create", "plan_step_done", "plan_step_skip", "plan_status"):
            assert plan_tool not in names

    def test_get_tool_schemas_mini_returns_thirteen(self):
        from agent.tools import get_tool_schemas
        schemas = get_tool_schemas("mini")
        assert len(schemas) == 14

    def test_get_tool_schemas_pcm_returns_sixteen(self):
        from agent.tools import get_tool_schemas
        schemas = get_tool_schemas("pcm")
        assert len(schemas) == 17


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
