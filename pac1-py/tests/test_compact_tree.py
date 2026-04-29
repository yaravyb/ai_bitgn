import json

from agent.dispatch import compact_tree


class TestCompactTree:
    def test_normal_json_tree(self):
        tree = json.dumps({
            "root": {
                "name": "/",
                "isDir": True,
                "children": [
                    {"name": "docs", "isDir": True, "children": [
                        {"name": "README.md", "isDir": False, "children": []},
                    ]},
                    {"name": "config.json", "isDir": False, "children": []},
                ],
            }
        })
        result = compact_tree(tree)
        assert "/" in result
        assert "docs/" in result
        assert "README.md" in result
        assert "config.json" in result

    def test_root_node_handling(self):
        tree = json.dumps({
            "root": {
                "name": "/",
                "isDir": True,
                "children": [
                    {"name": "file.txt", "isDir": False, "children": []},
                ],
            }
        })
        result = compact_tree(tree)
        lines = result.strip().split("\n")
        assert lines[0] == "/"
        assert "file.txt" in lines[1]

    def test_malformed_input_returns_empty(self):
        assert compact_tree("not json") == ""
        assert compact_tree("") == ""
        assert compact_tree(None) == ""

    def test_nested_directories(self):
        tree = json.dumps({
            "root": {
                "name": "/",
                "isDir": True,
                "children": [
                    {"name": "a", "isDir": True, "children": [
                        {"name": "b", "isDir": True, "children": [
                            {"name": "c.txt", "isDir": False, "children": []},
                        ]},
                    ]},
                ],
            }
        })
        result = compact_tree(tree)
        assert "a/" in result
        assert "b/" in result
        assert "c.txt" in result

    def test_without_root_wrapper(self):
        """compact_tree should handle data without 'root' key."""
        tree = json.dumps({
            "name": "/",
            "isDir": True,
            "children": [
                {"name": "hello.md", "isDir": False, "children": []},
            ],
        })
        result = compact_tree(tree)
        assert "hello.md" in result
