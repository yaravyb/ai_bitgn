"""Tests for the R4 structural security-guard module (D5).

The helper ``structural_security_check`` is a pure function — no I/O,
no LLM calls — that scans pending outbox writes for attachments
referencing the four internal-lane paths (``30_knowledge/``,
``90_memory/``, ``99_system/``) or any ``AGENTS.md`` file (case-
insensitive filename). Returns a citation string on the first match,
``None`` otherwise.
"""


class TestStructuralSecurityCheck:
    """R4 D5 + AC1/AC3/AC4/AC5: structural fallback attachment scan."""

    def test_30_knowledge_attachment_triggers_citation(self):
        from agent.security_guard import structural_security_check
        result = structural_security_check([
            {"op": "write", "args": {"path": "outbox/x.md",
                                     "content": "---\nto: a\nattachments:\n  - 30_knowledge/foo.md\n---\nhi"}},
        ])
        assert result is not None
        assert "30_knowledge" in result

    def test_90_memory_attachment_triggers_citation(self):
        from agent.security_guard import structural_security_check
        result = structural_security_check([
            {"op": "write", "args": {"path": "outbox/x.md",
                                     "content": "---\nto: a\nattachments:\n  - 90_memory/bar.md\n---\nhi"}},
        ])
        assert result is not None
        assert "90_memory" in result

    def test_99_system_attachment_triggers_citation(self):
        from agent.security_guard import structural_security_check
        result = structural_security_check([
            {"op": "write", "args": {"path": "outbox/x.md",
                                     "content": "---\nto: a\nattachments:\n  - 99_system/baz.md\n---\nhi"}},
        ])
        assert result is not None
        assert "99_system" in result

    def test_root_agents_md_attachment_triggers_citation(self):
        from agent.security_guard import structural_security_check
        result = structural_security_check([
            {"op": "write", "args": {"path": "outbox/x.md",
                                     "content": "---\nto: a\nattachments:\n  - AGENTS.md\n---\nhi"}},
        ])
        assert result is not None
        assert "agents" in result.lower()

    def test_nested_agents_md_attachment_triggers_citation(self):
        from agent.security_guard import structural_security_check
        result = structural_security_check([
            {"op": "write", "args": {"path": "outbox/x.md",
                                     "content": "---\nto: a\nattachments:\n  - subdir/AGENTS.md\n---\nhi"}},
        ])
        assert result is not None

    def test_lowercase_agents_md_attachment_case_insensitive(self):
        """R4 AC4: AGENTS.md filename match is case-insensitive."""
        from agent.security_guard import structural_security_check
        result = structural_security_check([
            {"op": "write", "args": {"path": "outbox/x.md",
                                     "content": "---\nto: a\nattachments:\n  - subdir/agents.md\n---\nhi"}},
        ])
        assert result is not None

    def test_dot_slash_prefix_normalized(self):
        """R4 AC5: defensive normalization strips leading './'."""
        from agent.security_guard import structural_security_check
        result = structural_security_check([
            {"op": "write", "args": {"path": "outbox/x.md",
                                     "content": "---\nto: a\nattachments:\n  - ./30_knowledge/foo.md\n---\nhi"}},
        ])
        assert result is not None
        assert "30_knowledge" in result

    def test_workspace_prefix_normalized(self):
        """R4 AC5: defensive normalization strips leading '/workspace/'."""
        from agent.security_guard import structural_security_check
        result = structural_security_check([
            {"op": "write", "args": {"path": "outbox/x.md",
                                     "content": "---\nto: a\nattachments:\n  - /workspace/30_knowledge/foo.md\n---\nhi"}},
        ])
        assert result is not None
        assert "30_knowledge" in result

    def test_non_internal_lane_path_returns_none(self):
        """R4 AC1: paths OUTSIDE the four internal lanes pass."""
        from agent.security_guard import structural_security_check
        result = structural_security_check([
            {"op": "write", "args": {"path": "outbox/x.md",
                                     "content": "---\nto: a\nattachments:\n  - outbox/drafts/y.md\n---\nhi"}},
        ])
        assert result is None

    def test_no_attachments_field_returns_none(self):
        from agent.security_guard import structural_security_check
        result = structural_security_check([
            {"op": "write", "args": {"path": "outbox/x.md",
                                     "content": "---\nto: a\nfrom: b\n---\nhi"}},
        ])
        assert result is None

    def test_empty_pending_writes_returns_none(self):
        from agent.security_guard import structural_security_check
        assert structural_security_check([]) is None

    def test_non_write_ops_skipped(self):
        """Only write operations are scanned — delete/move/mkdir ignored."""
        from agent.security_guard import structural_security_check
        result = structural_security_check([
            {"op": "delete", "args": {"path": "30_knowledge/foo.md"}},
        ])
        assert result is None

    def test_case_sensitive_directory_prefix(self):
        """R4 AC4: directory prefixes (30_knowledge/ etc.) are case-SENSITIVE."""
        from agent.security_guard import structural_security_check
        # Uppercased directory name should NOT trigger.
        result = structural_security_check([
            {"op": "write", "args": {"path": "outbox/x.md",
                                     "content": "---\nto: a\nattachments:\n  - 30_KNOWLEDGE/foo.md\n---\nhi"}},
        ])
        assert result is None
