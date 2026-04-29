from tasks import TaskManager


class TestTaskManager:
    def test_create_plan(self):
        tm = TaskManager()
        result = tm.create(["Step 1", "Step 2", "Step 3"])
        assert "Step 1" in result
        assert "Step 2" in result
        assert "Step 3" in result
        assert "(0/3 done)" in result

    def test_update_status_transitions(self):
        tm = TaskManager()
        tm.create(["Task A"])
        result = tm.update(1, "in_progress")
        assert "[>]" in result
        result = tm.update(1, "completed")
        assert "[x]" in result
        assert "(1/1 done)" in result

    def test_add_with_blocked_by(self):
        tm = TaskManager()
        tm.create(["First task"])
        tm.add("Second task", blocked_by=[1])
        result = tm.render()
        assert "blocked by: [1]" in result

    def test_completing_unblocks_dependents(self):
        tm = TaskManager()
        tm.create(["Blocker"])
        tm.add("Blocked", blocked_by=[1])
        # Blocked task can't start
        error = tm.update(2, "in_progress")
        assert "blocked" in error.lower()
        # Complete the blocker
        tm.update(1, "completed")
        # Now blocked task can start
        result = tm.update(2, "in_progress")
        assert "[>]" in result

    def test_defer_write_and_get_pending_writes(self):
        tm = TaskManager()
        tm.defer_write("write", {"path": "/test.md", "content": "hello"})
        tm.defer_write("delete", {"path": "/old.md"})
        pending = tm.get_pending_writes()
        assert len(pending) == 2
        assert pending[0]["op"] == "write"
        assert pending[1]["op"] == "delete"

    def test_track_read_write_delete(self):
        tm = TaskManager()
        tm.track_read("/a.md")
        tm.track_write("/b.md")
        tm.track_delete("/c.md")
        # Duplicates should be ignored
        tm.track_read("/a.md")
        tm.track_write("/b.md")
        assert tm._files_read == ["/a.md"]
        assert tm._files_written == ["/b.md"]
        assert tm._files_deleted == ["/c.md"]

    def test_render_output_format(self):
        tm = TaskManager()
        tm.set_instructions(["Rule 1", "Rule 2"])
        tm.create(["Do stuff"])
        tm.add_note("Important note")
        result = tm.render()
        assert "Instructions:" in result
        assert "Rule 1" in result
        assert "Notes:" in result
        assert "Important note" in result
        assert "Plan:" in result

    def test_files_deleted_property(self):
        tm = TaskManager()
        tm.track_delete("/x.md")
        assert tm.files_deleted == ["/x.md"]

    def test_pending_writes_property(self):
        tm = TaskManager()
        tm.defer_write("write", {"path": "/y.md", "content": "data"})
        assert len(tm.pending_writes) == 1
        assert tm.pending_writes[0]["op"] == "write"
