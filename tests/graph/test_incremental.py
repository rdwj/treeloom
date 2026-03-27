"""Tests for incremental CPG rebuild."""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.builder import CPGBuilder
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind


@pytest.fixture()
def tmp_src(tmp_path: Path) -> Path:
    """Create a temporary source directory with two Python files."""
    src = tmp_path / "src"
    src.mkdir()

    (src / "foo.py").write_text(
        "def foo():\n    return 1\n",
        encoding="utf-8",
    )
    (src / "bar.py").write_text(
        "from foo import foo\n\ndef bar():\n    x = foo()\n    return x\n",
        encoding="utf-8",
    )
    return src


class TestRebuildNoChange:
    def test_no_change_is_noop(self, tmp_src: Path):
        builder = CPGBuilder()
        builder.add_directory(tmp_src)
        cpg = builder.build()
        original_nodes = cpg.node_count
        original_edges = cpg.edge_count

        cpg2 = builder.rebuild()
        assert cpg2 is cpg  # Same object
        assert cpg.node_count == original_nodes
        assert cpg.edge_count == original_edges


class TestRebuildModifiedFile:
    def test_modified_file_updates_cpg(self, tmp_src: Path):
        builder = CPGBuilder()
        builder.add_directory(tmp_src)
        cpg = builder.build()

        # Verify foo function exists
        foo_fns = [n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "foo"]
        assert len(foo_fns) >= 1

        # Modify foo.py: rename function
        (tmp_src / "foo.py").write_text(
            "def foo_v2():\n    return 2\n",
            encoding="utf-8",
        )

        cpg2 = builder.rebuild(changed=[tmp_src / "foo.py"])
        assert cpg2 is cpg

        # Old foo is gone, new foo_v2 exists
        fn_names = {n.name for n in cpg.nodes(kind=NodeKind.FUNCTION)}
        assert "foo_v2" in fn_names
        assert "foo" not in fn_names
        # bar still exists
        assert "bar" in fn_names

    def test_add_function_increases_node_count(self, tmp_src: Path):
        builder = CPGBuilder()
        builder.add_directory(tmp_src)
        cpg = builder.build()
        old_fn_count = len(list(cpg.nodes(kind=NodeKind.FUNCTION)))

        # Add a new function to foo.py
        (tmp_src / "foo.py").write_text(
            "def foo():\n    return 1\n\ndef baz():\n    return 3\n",
            encoding="utf-8",
        )

        builder.rebuild(changed=[tmp_src / "foo.py"])
        new_fn_count = len(list(cpg.nodes(kind=NodeKind.FUNCTION)))
        assert new_fn_count == old_fn_count + 1


class TestRebuildDeletedFile:
    def test_deleted_file_removes_nodes(self, tmp_src: Path):
        builder = CPGBuilder()
        builder.add_directory(tmp_src)
        cpg = builder.build()

        # Delete foo.py
        (tmp_src / "foo.py").unlink()

        builder.rebuild(changed=[tmp_src / "foo.py"])

        # foo's nodes are gone
        fn_names = {n.name for n in cpg.nodes(kind=NodeKind.FUNCTION)}
        assert "foo" not in fn_names
        # bar's nodes survive
        assert "bar" in fn_names


class TestRebuildNewFile:
    def test_add_new_file(self, tmp_src: Path):
        builder = CPGBuilder()
        builder.add_directory(tmp_src)
        cpg = builder.build()

        # Create a new file
        (tmp_src / "new.py").write_text(
            "def new_func():\n    return 42\n",
            encoding="utf-8",
        )

        builder.add_file(tmp_src / "new.py")
        builder.rebuild()

        fn_names = {n.name for n in cpg.nodes(kind=NodeKind.FUNCTION)}
        assert "new_func" in fn_names


class TestAnnotationSurvival:
    def test_annotations_survive_on_unchanged_files(self, tmp_src: Path):
        builder = CPGBuilder()
        builder.add_directory(tmp_src)
        cpg = builder.build()

        # Annotate a node in bar.py
        bar_fns = [n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "bar"]
        assert len(bar_fns) >= 1
        bar_id = bar_fns[0].id
        cpg.annotate_node(bar_id, "my_annotation", "preserved")

        # Modify foo.py (not bar.py)
        (tmp_src / "foo.py").write_text(
            "def foo():\n    return 999\n",
            encoding="utf-8",
        )

        builder.rebuild(changed=[tmp_src / "foo.py"])

        # Annotation on bar should survive
        assert cpg.get_annotation(bar_id, "my_annotation") == "preserved"


class TestAutoChangeDetection:
    def test_rebuild_detects_changes_automatically(self, tmp_src: Path):
        builder = CPGBuilder()
        builder.add_directory(tmp_src)
        cpg = builder.build()

        # Modify foo.py
        (tmp_src / "foo.py").write_text(
            "def foo_auto():\n    return 'auto'\n",
            encoding="utf-8",
        )

        # rebuild() without changed= should detect the change
        builder.rebuild()

        fn_names = {n.name for n in cpg.nodes(kind=NodeKind.FUNCTION)}
        assert "foo_auto" in fn_names
