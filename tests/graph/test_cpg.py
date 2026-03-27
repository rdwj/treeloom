"""Tests for CodePropertyGraph."""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind


def _make_node(
    id_str: str,
    kind: NodeKind = NodeKind.VARIABLE,
    name: str = "x",
    file: str = "test.py",
    line: int = 1,
    scope: str | None = None,
) -> CpgNode:
    return CpgNode(
        id=NodeId(id_str),
        kind=kind,
        name=name,
        location=SourceLocation(file=Path(file), line=line),
        scope=NodeId(scope) if scope else None,
    )


@pytest.fixture()
def cpg() -> CodePropertyGraph:
    """A small CPG with a module containing a function containing a variable."""
    g = CodePropertyGraph()
    mod = _make_node("mod", NodeKind.MODULE, "test", "test.py", 1)
    func = _make_node("fn", NodeKind.FUNCTION, "foo", "test.py", 2, scope="mod")
    var = _make_node("var", NodeKind.VARIABLE, "x", "test.py", 3, scope="fn")
    g.add_node(mod)
    g.add_node(func)
    g.add_node(var)
    g.add_edge(CpgEdge(source=NodeId("mod"), target=NodeId("fn"), kind=EdgeKind.CONTAINS))
    g.add_edge(CpgEdge(source=NodeId("fn"), target=NodeId("var"), kind=EdgeKind.CONTAINS))
    return g


class TestNodeAccess:
    def test_node_lookup(self, cpg: CodePropertyGraph):
        node = cpg.node(NodeId("fn"))
        assert node is not None
        assert node.name == "foo"

    def test_node_missing(self, cpg: CodePropertyGraph):
        assert cpg.node(NodeId("nonexistent")) is None

    def test_nodes_no_filter(self, cpg: CodePropertyGraph):
        all_nodes = list(cpg.nodes())
        assert len(all_nodes) == 3

    def test_nodes_by_kind(self, cpg: CodePropertyGraph):
        funcs = list(cpg.nodes(kind=NodeKind.FUNCTION))
        assert len(funcs) == 1
        assert funcs[0].name == "foo"

    def test_nodes_by_file(self, cpg: CodePropertyGraph):
        nodes = list(cpg.nodes(file=Path("test.py")))
        assert len(nodes) == 3
        nodes = list(cpg.nodes(file=Path("other.py")))
        assert len(nodes) == 0

    def test_node_count(self, cpg: CodePropertyGraph):
        assert cpg.node_count == 3


class TestEdgeAccess:
    def test_edges_no_filter(self, cpg: CodePropertyGraph):
        all_edges = list(cpg.edges())
        assert len(all_edges) == 2

    def test_edges_by_kind(self, cpg: CodePropertyGraph):
        contains = list(cpg.edges(kind=EdgeKind.CONTAINS))
        assert len(contains) == 2
        calls = list(cpg.edges(kind=EdgeKind.CALLS))
        assert len(calls) == 0

    def test_edge_count(self, cpg: CodePropertyGraph):
        assert cpg.edge_count == 2


class TestTraversal:
    def test_successors(self, cpg: CodePropertyGraph):
        succs = cpg.successors(NodeId("mod"))
        assert len(succs) == 1
        assert succs[0].name == "foo"

    def test_successors_with_edge_kind(self, cpg: CodePropertyGraph):
        succs = cpg.successors(NodeId("mod"), edge_kind=EdgeKind.CONTAINS)
        assert len(succs) == 1
        succs = cpg.successors(NodeId("mod"), edge_kind=EdgeKind.CALLS)
        assert len(succs) == 0

    def test_predecessors(self, cpg: CodePropertyGraph):
        preds = cpg.predecessors(NodeId("fn"))
        assert len(preds) == 1
        assert preds[0].kind == NodeKind.MODULE

    def test_predecessors_with_edge_kind(self, cpg: CodePropertyGraph):
        preds = cpg.predecessors(NodeId("fn"), edge_kind=EdgeKind.CONTAINS)
        assert len(preds) == 1
        preds = cpg.predecessors(NodeId("fn"), edge_kind=EdgeKind.DATA_FLOWS_TO)
        assert len(preds) == 0


class TestScopeNavigation:
    def test_scope_of(self, cpg: CodePropertyGraph):
        scope = cpg.scope_of(NodeId("var"))
        assert scope is not None
        assert scope.name == "foo"

    def test_scope_of_root(self, cpg: CodePropertyGraph):
        assert cpg.scope_of(NodeId("mod")) is None

    def test_children_of(self, cpg: CodePropertyGraph):
        children = cpg.children_of(NodeId("mod"))
        assert len(children) == 1
        assert children[0].name == "foo"

    def test_children_of_leaf(self, cpg: CodePropertyGraph):
        assert cpg.children_of(NodeId("var")) == []


class TestAnnotations:
    def test_annotate_and_retrieve(self, cpg: CodePropertyGraph):
        cpg.annotate_node(NodeId("fn"), "role", "entry_point")
        assert cpg.get_annotation(NodeId("fn"), "role") == "entry_point"

    def test_annotation_missing(self, cpg: CodePropertyGraph):
        assert cpg.get_annotation(NodeId("fn"), "role") is None

    def test_annotations_for(self, cpg: CodePropertyGraph):
        cpg.annotate_node(NodeId("fn"), "a", 1)
        cpg.annotate_node(NodeId("fn"), "b", 2)
        anns = cpg.annotations_for(NodeId("fn"))
        assert anns == {"a": 1, "b": 2}

    def test_annotations_separate_from_attrs(self, cpg: CodePropertyGraph):
        """Annotations must not pollute CpgNode.attrs."""
        cpg.annotate_node(NodeId("fn"), "role", "sink")
        node = cpg.node(NodeId("fn"))
        assert node is not None
        assert "role" not in node.attrs

    def test_edge_annotation(self, cpg: CodePropertyGraph):
        cpg.annotate_edge(NodeId("mod"), NodeId("fn"), "weight", 0.5)
        assert cpg.get_edge_annotation(NodeId("mod"), NodeId("fn"), "weight") == 0.5

    def test_edge_annotation_missing(self, cpg: CodePropertyGraph):
        assert cpg.get_edge_annotation(NodeId("mod"), NodeId("fn"), "x") is None


class TestSerialization:
    def test_round_trip(self, cpg: CodePropertyGraph):
        cpg.annotate_node(NodeId("fn"), "role", "entry_point")
        cpg.annotate_edge(NodeId("mod"), NodeId("fn"), "weight", 1.0)

        data = cpg.to_dict()
        restored = CodePropertyGraph.from_dict(data)

        assert restored.node_count == cpg.node_count
        assert restored.edge_count == cpg.edge_count

        fn = restored.node(NodeId("fn"))
        assert fn is not None
        assert fn.name == "foo"
        assert fn.kind == NodeKind.FUNCTION
        assert fn.scope == NodeId("mod")

        # Annotations round-trip
        assert restored.get_annotation(NodeId("fn"), "role") == "entry_point"
        assert restored.get_edge_annotation(NodeId("mod"), NodeId("fn"), "weight") == 1.0

    def test_round_trip_preserves_location(self, cpg: CodePropertyGraph):
        data = cpg.to_dict()
        restored = CodePropertyGraph.from_dict(data)
        node = restored.node(NodeId("fn"))
        assert node is not None
        assert node.location is not None
        assert node.location.line == 2
        assert node.location.file == Path("test.py")

    def test_round_trip_preserves_attrs(self):
        cpg = CodePropertyGraph()
        node = CpgNode(
            id=NodeId("n"),
            kind=NodeKind.FUNCTION,
            name="f",
            location=None,
            attrs={"is_async": True, "decorators": ["staticmethod"]},
        )
        cpg.add_node(node)
        restored = CodePropertyGraph.from_dict(cpg.to_dict())
        n = restored.node(NodeId("n"))
        assert n is not None
        assert n.attrs == {"is_async": True, "decorators": ["staticmethod"]}

    def test_version_in_serialized(self, cpg: CodePropertyGraph):
        data = cpg.to_dict()
        assert "treeloom_version" in data

    def test_round_trip_edge_annotations_with_colon_ids(self):
        """Edge annotation round-trip must work with colon-containing node IDs."""
        cpg = CodePropertyGraph()
        cpg.add_node(_make_node("function:foo.py:1:0:1", NodeKind.FUNCTION, "foo"))
        cpg.add_node(_make_node("variable:foo.py:3:4:2", NodeKind.VARIABLE, "x"))
        cpg.add_edge(CpgEdge(
            source=NodeId("function:foo.py:1:0:1"),
            target=NodeId("variable:foo.py:3:4:2"),
            kind=EdgeKind.CONTAINS,
        ))
        cpg.annotate_edge(
            NodeId("function:foo.py:1:0:1"),
            NodeId("variable:foo.py:3:4:2"),
            "weight", 42,
        )

        restored = CodePropertyGraph.from_dict(cpg.to_dict())
        assert restored.get_edge_annotation(
            NodeId("function:foo.py:1:0:1"),
            NodeId("variable:foo.py:3:4:2"),
            "weight",
        ) == 42

    def test_round_trip_with_multiple_edge_kinds(self):
        cpg = CodePropertyGraph()
        cpg.add_node(_make_node("a", NodeKind.FUNCTION, "a"))
        cpg.add_node(_make_node("b", NodeKind.VARIABLE, "b"))
        cpg.add_edge(CpgEdge(source=NodeId("a"), target=NodeId("b"), kind=EdgeKind.CONTAINS))
        cpg.add_edge(CpgEdge(source=NodeId("a"), target=NodeId("b"), kind=EdgeKind.DATA_FLOWS_TO))

        restored = CodePropertyGraph.from_dict(cpg.to_dict())
        assert restored.edge_count == 2
        kinds = {e.kind for e in restored.edges()}
        assert kinds == {EdgeKind.CONTAINS, EdgeKind.DATA_FLOWS_TO}


class TestFilesProperty:
    def test_files(self, cpg: CodePropertyGraph):
        assert cpg.files == [Path("test.py")]

    def test_files_multiple(self):
        cpg = CodePropertyGraph()
        cpg.add_node(_make_node("a", file="b.py"))
        cpg.add_node(_make_node("b", file="a.py"))
        assert cpg.files == [Path("a.py"), Path("b.py")]

    def test_files_empty(self):
        cpg = CodePropertyGraph()
        assert cpg.files == []

    def test_files_deduplication(self):
        cpg = CodePropertyGraph()
        cpg.add_node(_make_node("a", file="x.py"))
        cpg.add_node(_make_node("b", file="x.py"))
        assert cpg.files == [Path("x.py")]


class TestRemoveNode:
    def test_remove_node(self):
        cpg = CodePropertyGraph()
        node = CpgNode(
            id=NodeId("n1"), kind=NodeKind.VARIABLE, name="x",
            location=SourceLocation(file=Path("a.py"), line=1),
        )
        cpg.add_node(node)
        cpg.annotate_node(NodeId("n1"), "key", "value")
        cpg.remove_node(NodeId("n1"))
        assert cpg.node(NodeId("n1")) is None
        assert cpg.node_count == 0
        assert cpg.get_annotation(NodeId("n1"), "key") is None

    def test_remove_node_cleans_edge_annotations(self):
        cpg = CodePropertyGraph()
        n1 = CpgNode(id=NodeId("n1"), kind=NodeKind.VARIABLE, name="x",
                     location=SourceLocation(file=Path("a.py"), line=1))
        n2 = CpgNode(id=NodeId("n2"), kind=NodeKind.CALL, name="f",
                     location=SourceLocation(file=Path("a.py"), line=2))
        cpg.add_node(n1)
        cpg.add_node(n2)
        cpg.add_edge(CpgEdge(source=NodeId("n1"), target=NodeId("n2"),
                             kind=EdgeKind.DATA_FLOWS_TO))
        cpg.annotate_edge(NodeId("n1"), NodeId("n2"), "tainted", True)
        cpg.remove_node(NodeId("n1"))
        assert cpg.get_edge_annotation(NodeId("n1"), NodeId("n2"), "tainted") is None

    def test_remove_node_updates_file_index(self):
        cpg = CodePropertyGraph()
        node = CpgNode(
            id=NodeId("n1"), kind=NodeKind.VARIABLE, name="x",
            location=SourceLocation(file=Path("a.py"), line=1),
        )
        cpg.add_node(node)
        assert len(cpg.nodes_for_file(Path("a.py"))) == 1
        cpg.remove_node(NodeId("n1"))
        assert len(cpg.nodes_for_file(Path("a.py"))) == 0


class TestNodesForFile:
    def test_nodes_for_file(self):
        cpg = CodePropertyGraph()
        n1 = CpgNode(id=NodeId("n1"), kind=NodeKind.VARIABLE, name="x",
                     location=SourceLocation(file=Path("a.py"), line=1))
        n2 = CpgNode(id=NodeId("n2"), kind=NodeKind.VARIABLE, name="y",
                     location=SourceLocation(file=Path("a.py"), line=2))
        n3 = CpgNode(id=NodeId("n3"), kind=NodeKind.VARIABLE, name="z",
                     location=SourceLocation(file=Path("b.py"), line=1))
        cpg.add_node(n1)
        cpg.add_node(n2)
        cpg.add_node(n3)
        a_nodes = cpg.nodes_for_file(Path("a.py"))
        assert len(a_nodes) == 2
        assert set(str(n) for n in a_nodes) == {"n1", "n2"}

    def test_nodes_for_nonexistent_file(self):
        cpg = CodePropertyGraph()
        assert cpg.nodes_for_file(Path("missing.py")) == []

    def test_file_index_survives_serialization(self):
        cpg = CodePropertyGraph()
        node = CpgNode(
            id=NodeId("n1"), kind=NodeKind.VARIABLE, name="x",
            location=SourceLocation(file=Path("a.py"), line=1),
        )
        cpg.add_node(node)
        restored = CodePropertyGraph.from_dict(cpg.to_dict())
        assert len(restored.nodes_for_file(Path("a.py"))) == 1
