"""Tests for agent.tracker -- GroundingTracker.

TDD: Tests written BEFORE implementation.
Task 2.1: GroundingTracker class with add, add_many, merge, all, __len__, __repr__
Task 2.2: Path normalization -- strip leading /, resolve .., lowercase for comparison, preserve casing
Task 2.3: merge() returns sorted union, never empty if files were read
Task 1 (agent-guard-architecture): Thread-safety via threading.Lock
"""

import threading

import pytest


class TestGroundingTrackerBasic:
    """Task 2.1: Core API."""

    def test_empty_tracker_has_length_zero(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        assert len(t) == 0

    def test_add_single_path(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("workspace/file.txt")
        assert len(t) == 1

    def test_add_duplicate_path_does_not_increase_count(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("workspace/file.txt")
        t.add("workspace/file.txt")
        assert len(t) == 1

    def test_all_returns_set_copy(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        t.add("b.md")
        result = t.all()
        assert isinstance(result, set)
        assert result == {"a.md", "b.md"}
        # Must be a copy, not the internal set
        result.add("c.md")
        assert len(t) == 2

    def test_add_many(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add_many(["a.md", "b.md", "c.md"])
        assert len(t) == 3

    def test_add_many_with_duplicates(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        t.add_many(["a.md", "b.md"])
        assert len(t) == 2

    def test_repr_contains_count(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        t.add("b.md")
        r = repr(t)
        assert "2" in r
        assert "GroundingTracker" in r


class TestPathNormalization:
    """Task 2.2: Path normalization rules."""

    def test_strip_leading_slash(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("/workspace/file.txt")
        assert "workspace/file.txt" in t.all()

    def test_resolve_dotdot(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("workspace/../workspace/file.txt")
        result = t.all()
        assert "workspace/file.txt" in result

    def test_leading_slash_and_dotdot(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("/workspace/../data/file.txt")
        result = t.all()
        assert "data/file.txt" in result

    def test_case_insensitive_dedup(self):
        """Lowercase used for comparison, but original casing is preserved."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("AGENTS.MD")
        t.add("agents.md")
        # Should be treated as the same file
        assert len(t) == 1

    def test_preserves_original_casing(self):
        """The first casing encountered should be preserved."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("AGENTS.MD")
        result = t.all()
        # At least one of the casings should be present
        assert len(result) == 1
        # The stored value should be the first one added
        assert "AGENTS.MD" in result

    def test_second_casing_does_not_override(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("AGENTS.MD")
        t.add("agents.md")
        result = t.all()
        assert len(result) == 1
        assert "AGENTS.MD" in result

    def test_normalize_double_slashes(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("//workspace//file.txt")
        result = t.all()
        assert "workspace/file.txt" in result


class TestMerge:
    """Task 2.3: merge() returns sorted union, never empty."""

    def test_merge_with_no_llm_refs(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("b.md")
        t.add("a.md")
        result = t.merge([])
        assert result == ["a.md", "b.md"]

    def test_merge_unions_llm_refs_and_tracked(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        result = t.merge(["b.md", "c.md"])
        assert "a.md" in result
        assert "b.md" in result
        assert "c.md" in result

    def test_merge_deduplicates(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        result = t.merge(["a.md", "b.md"])
        assert result.count("a.md") == 1

    def test_merge_result_is_sorted(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("z.md")
        t.add("a.md")
        result = t.merge(["m.md"])
        assert result == sorted(result)

    def test_merge_never_empty_when_files_read(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        # Even if LLM provides empty list, merge should include tracked files
        result = t.merge([])
        assert len(result) > 0

    def test_merge_empty_when_nothing_read(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        result = t.merge([])
        assert result == []

    def test_merge_normalizes_llm_refs(self):
        """LLM refs should also be normalized."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        result = t.merge(["/b.md"])
        assert "b.md" in result

    def test_merge_deduplicates_across_casing(self):
        """If tracker has AGENTS.MD and LLM provides agents.md, no duplicate."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("AGENTS.MD")
        result = t.merge(["agents.md"])
        # Should only have one entry for AGENTS.MD
        assert len(result) == 1


class TestTrackerIsLeaf:
    """tracker.py must have zero imports from other agent/ modules."""

    def test_no_agent_imports(self):
        import agent.tracker as mod
        with open(mod.__file__) as f:
            source = f.read()
        import re
        agent_imports = re.findall(r"from\s+agent\.", source)
        assert agent_imports == [], (
            f"tracker.py must not import from agent modules: {agent_imports}"
        )

    def test_imports_only_threading_and_stdlib(self):
        """tracker.py should import threading (for Lock) and remain stdlib-only."""
        import agent.tracker as mod
        with open(mod.__file__) as f:
            source = f.read()
        assert "import threading" in source, (
            "tracker.py must import threading for thread safety"
        )


class TestGroundingTrackerThreadSafety:
    """Task 1 (agent-guard-architecture): Thread-safety tests.

    Spawns multiple threads calling add() and contains() simultaneously
    and verifies no data loss or corruption.
    """

    def test_has_lock_attribute(self):
        """GroundingTracker must have a _lock attribute of type threading.Lock."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        assert hasattr(t, "_lock"), "GroundingTracker must have a _lock attribute"
        assert isinstance(t._lock, type(threading.Lock())), (
            "_lock must be a threading.Lock instance"
        )

    def test_concurrent_add_no_data_loss(self):
        """Multiple threads adding unique paths must not lose any path."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        num_threads = 20
        paths_per_thread = 50
        barrier = threading.Barrier(num_threads)

        def add_paths(thread_id: int) -> None:
            barrier.wait()  # Ensure all threads start at the same time
            for i in range(paths_per_thread):
                t.add(f"thread{thread_id}/file{i}.txt")

        threads = [
            threading.Thread(target=add_paths, args=(tid,))
            for tid in range(num_threads)
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        expected_count = num_threads * paths_per_thread
        assert len(t) == expected_count, (
            f"Expected {expected_count} paths, got {len(t)} -- data loss under concurrency"
        )

    def test_concurrent_add_same_path_no_duplicates(self):
        """Multiple threads adding the same path must result in exactly one entry."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        num_threads = 20
        barrier = threading.Barrier(num_threads)

        def add_same(thread_id: int) -> None:
            barrier.wait()
            t.add("shared/file.txt")

        threads = [
            threading.Thread(target=add_same, args=(tid,))
            for tid in range(num_threads)
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert len(t) == 1, (
            f"Expected 1 path, got {len(t)} -- duplicate introduced under concurrency"
        )

    def test_concurrent_add_and_contains_consistency(self):
        """contains() must return consistent results during concurrent add()."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        num_threads = 10
        paths_per_thread = 100
        errors: list[str] = []
        barrier = threading.Barrier(num_threads * 2)  # writers + readers

        def writer(thread_id: int) -> None:
            barrier.wait()
            for i in range(paths_per_thread):
                t.add(f"writer{thread_id}/file{i}.txt")

        def reader(thread_id: int) -> None:
            barrier.wait()
            for i in range(paths_per_thread):
                path = f"writer{thread_id}/file{i}.txt"
                # Just call contains -- it must not raise or return partial state
                try:
                    t.contains(path)
                except Exception as exc:
                    errors.append(f"contains() raised {exc} for {path}")

        threads = []
        for tid in range(num_threads):
            threads.append(threading.Thread(target=writer, args=(tid,)))
            threads.append(threading.Thread(target=reader, args=(tid,)))
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert errors == [], f"Errors during concurrent access: {errors}"
        # After all writers finish, all paths should be present
        for tid in range(num_threads):
            for i in range(paths_per_thread):
                assert t.contains(f"writer{tid}/file{i}.txt"), (
                    f"writer{tid}/file{i}.txt missing after concurrent add/contains"
                )

    def test_concurrent_add_many_no_data_loss(self):
        """add_many() called concurrently must not lose paths."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        num_threads = 10
        paths_per_thread = 50
        barrier = threading.Barrier(num_threads)

        def add_batch(thread_id: int) -> None:
            barrier.wait()
            paths = [f"batch{thread_id}/file{i}.txt" for i in range(paths_per_thread)]
            t.add_many(paths)

        threads = [
            threading.Thread(target=add_batch, args=(tid,))
            for tid in range(num_threads)
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        expected_count = num_threads * paths_per_thread
        assert len(t) == expected_count, (
            f"Expected {expected_count} paths, got {len(t)} -- data loss in add_many"
        )

    def test_concurrent_merge_does_not_corrupt_state(self):
        """merge() called concurrently with add() must not corrupt internal state."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        num_add_threads = 5
        num_merge_threads = 5
        paths_per_thread = 50
        merge_errors: list[str] = []
        barrier = threading.Barrier(num_add_threads + num_merge_threads)

        def writer(thread_id: int) -> None:
            barrier.wait()
            for i in range(paths_per_thread):
                t.add(f"merge_writer{thread_id}/file{i}.txt")

        def merger(thread_id: int) -> None:
            barrier.wait()
            for _ in range(20):
                try:
                    result = t.merge([f"llm_ref{thread_id}.txt"])
                    if not isinstance(result, list):
                        merge_errors.append(f"merge() returned non-list: {type(result)}")
                    # Result must be sorted
                    if result != sorted(result):
                        merge_errors.append("merge() returned unsorted result")
                except Exception as exc:
                    merge_errors.append(f"merge() raised {exc}")

        threads = []
        for tid in range(num_add_threads):
            threads.append(threading.Thread(target=writer, args=(tid,)))
        for tid in range(num_merge_threads):
            threads.append(threading.Thread(target=merger, args=(tid,)))
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert merge_errors == [], f"Errors during concurrent merge: {merge_errors}"

    def test_concurrent_all_returns_consistent_snapshot(self):
        """all() must return a consistent snapshot even during concurrent add()."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        errors: list[str] = []
        barrier = threading.Barrier(10)

        def writer() -> None:
            barrier.wait()
            for i in range(200):
                t.add(f"snap/file{i}.txt")

        def reader() -> None:
            barrier.wait()
            for _ in range(50):
                try:
                    snapshot = t.all()
                    if not isinstance(snapshot, set):
                        errors.append(f"all() returned non-set: {type(snapshot)}")
                except Exception as exc:
                    errors.append(f"all() raised {exc}")

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=writer))
            threads.append(threading.Thread(target=reader))
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert errors == [], f"Errors during concurrent all(): {errors}"

    def test_concurrent_len_no_error(self):
        """__len__() must not raise during concurrent add()."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        errors: list[str] = []
        barrier = threading.Barrier(10)

        def writer() -> None:
            barrier.wait()
            for i in range(200):
                t.add(f"len_test/file{i}.txt")

        def reader() -> None:
            barrier.wait()
            for _ in range(100):
                try:
                    length = len(t)
                    if not isinstance(length, int) or length < 0:
                        errors.append(f"len() returned invalid value: {length}")
                except Exception as exc:
                    errors.append(f"len() raised {exc}")

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=writer))
            threads.append(threading.Thread(target=reader))
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert errors == [], f"Errors during concurrent len(): {errors}"
