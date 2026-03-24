"""Tests for JSON export/import."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from treeloom.export.json import from_json, to_json
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
    attrs: dict | None = None,
) -> CpgNode:
    return CpgNode(
        id=NodeId(id_str),
        kind=kind,
        name=name,
        location=SourceLocation(file=Path(file), line=line),
        scope=NodeId(scope) if scope else None,
        attrs=attrs or {},
    )


@pytest.fixture()
def sample_cpg() -> CodePropertyGraph:
    cpg = CodePropertyGraph()
    mod = _make_node("mod", NodeKind.MODULE, "test_mod", "test.py", 1)
    func = _make_node("fn", NodeKind.FUNCTION, "foo", "test.py", 2, scope="mod",
                       attrs={"is_async": True})
    var = _make_node("var", NodeKind.VARIABLE, "x", "test.py", 3, scope="fn")
    cpg.add_node(mod)
    cpg.add_node(func)
    cpg.add_node(var)
    cpg.add_edge(CpgEdge(source=NodeId("mod"), target=NodeId("fn"), kind=EdgeKind.CONTAINS))
    cpg.add_edge(CpgEdge(source=NodeId("fn"), target=NodeId("var"), kind=EdgeKind.CONTAINS))
    cpg.add_edge(CpgEdge(source=NodeId("fn"), target=NodeId("var"), kind=EdgeKind.DATA_FLOWS_TO))
    cpg.annotate_node(NodeId("fn"), "role", "entry_point")
    cpg.annotate_edge(NodeId("mod"), NodeId("fn"), "weight", 1.5)
    return cpg


class TestJsonRoundTrip:
    def test_round_trip_preserves_structure(self, sample_cpg: CodePropertyGraph):
        restored = from_json(to_json(sample_cpg))

        assert restored.node_count == sample_cpg.node_count
        assert restored.edge_count == sample_cpg.edge_count

    def test_round_trip_preserves_nodes(self, sample_cpg: CodePropertyGraph):
        restored = from_json(to_json(sample_cpg))
        fn = restored.node(NodeId("fn"))
        assert fn is not None
        assert fn.name == "foo"
        assert fn.kind == NodeKind.FUNCTION
        assert fn.scope == NodeId("mod")

    def test_round_trip_preserves_attrs(self, sample_cpg: CodePropertyGraph):
        restored = from_json(to_json(sample_cpg))
        fn = restored.node(NodeId("fn"))
        assert fn is not None
        assert fn.attrs == {"is_async": True}

    def test_round_trip_preserves_location(self, sample_cpg: CodePropertyGraph):
        restored = from_json(to_json(sample_cpg))
        fn = restored.node(NodeId("fn"))
        assert fn is not None
        assert fn.location is not None
        assert fn.location.line == 2
        assert fn.location.file == Path("test.py")

    def test_round_trip_preserves_edges(self, sample_cpg: CodePropertyGraph):
        restored = from_json(to_json(sample_cpg))
        edge_kinds = {e.kind for e in restored.edges()}
        assert EdgeKind.CONTAINS in edge_kinds
        assert EdgeKind.DATA_FLOWS_TO in edge_kinds

    def test_round_trip_preserves_node_annotations(self, sample_cpg: CodePropertyGraph):
        restored = from_json(to_json(sample_cpg))
        assert restored.get_annotation(NodeId("fn"), "role") == "entry_point"

    def test_round_trip_preserves_edge_annotations(self, sample_cpg: CodePropertyGraph):
        restored = from_json(to_json(sample_cpg))
        assert restored.get_edge_annotation(NodeId("mod"), NodeId("fn"), "weight") == 1.5

    def test_output_is_valid_json(self, sample_cpg: CodePropertyGraph):
        output = to_json(sample_cpg)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)
        assert "treeloom_version" in parsed
        assert "nodes" in parsed
        assert "edges" in parsed

    def test_empty_cpg_round_trip(self):
        cpg = CodePropertyGraph()
        restored = from_json(to_json(cpg))
        assert restored.node_count == 0
        assert restored.edge_count == 0

    def test_indent_parameter(self, sample_cpg: CodePropertyGraph):
        compact = to_json(sample_cpg, indent=0)
        pretty = to_json(sample_cpg, indent=4)
        # Both must parse to equivalent data.
        assert json.loads(compact) == json.loads(pretty)

    def test_colon_ids_round_trip(self):
        """Node IDs with colons (the real format) must survive round-trip."""
        cpg = CodePropertyGraph()
        cpg.add_node(_make_node("function:foo.py:1:0:1", NodeKind.FUNCTION, "foo"))
        cpg.add_node(_make_node("variable:foo.py:3:4:2", NodeKind.VARIABLE, "x"))
        cpg.add_edge(CpgEdge(
            source=NodeId("function:foo.py:1:0:1"),
            target=NodeId("variable:foo.py:3:4:2"),
            kind=EdgeKind.CONTAINS,
        ))
        restored = from_json(to_json(cpg))
        assert restored.node(NodeId("function:foo.py:1:0:1")) is not None
        assert restored.node(NodeId("variable:foo.py:3:4:2")) is not None
        assert restored.edge_count == 1
