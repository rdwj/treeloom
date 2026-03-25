"""Tests for DOT export."""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.export.dot import to_dot
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
    g = CodePropertyGraph()
    g.add_node(_make_node("mod", NodeKind.MODULE, "mymod"))
    g.add_node(_make_node("fn", NodeKind.FUNCTION, "foo", scope="mod"))
    g.add_node(_make_node("var", NodeKind.VARIABLE, "x", scope="fn"))
    g.add_node(_make_node("call", NodeKind.CALL, "bar", scope="fn"))
    g.add_node(_make_node("lit", NodeKind.LITERAL, '"hello"', scope="fn"))
    g.add_node(_make_node("br", NodeKind.BRANCH, "if_check", scope="fn"))
    g.add_node(_make_node("lp", NodeKind.LOOP, "for_loop", scope="fn"))
    g.add_node(_make_node("blk", NodeKind.BLOCK, "block0", scope="fn"))
    g.add_node(_make_node("cls", NodeKind.CLASS, "MyClass"))
    g.add_edge(CpgEdge(source=NodeId("mod"), target=NodeId("fn"), kind=EdgeKind.CONTAINS))
    g.add_edge(CpgEdge(source=NodeId("fn"), target=NodeId("var"), kind=EdgeKind.DATA_FLOWS_TO))
    g.add_edge(CpgEdge(source=NodeId("fn"), target=NodeId("call"), kind=EdgeKind.CALLS))
    g.add_edge(CpgEdge(source=NodeId("br"), target=NodeId("blk"), kind=EdgeKind.BRANCHES_TO))
    g.add_edge(CpgEdge(source=NodeId("blk"), target=NodeId("var"), kind=EdgeKind.FLOWS_TO))
    return g


class TestDotOutput:
    def test_starts_with_digraph(self, cpg: CodePropertyGraph):
        dot = to_dot(cpg)
        assert dot.startswith("digraph CPG {")

    def test_ends_with_closing_brace(self, cpg: CodePropertyGraph):
        dot = to_dot(cpg)
        assert dot.strip().endswith("}")

    def test_contains_node_shapes(self, cpg: CodePropertyGraph):
        dot = to_dot(cpg)
        assert "shape=folder" in dot       # MODULE
        assert "shape=component" in dot     # FUNCTION
        assert "shape=ellipse" in dot       # VARIABLE
        assert "shape=diamond" in dot       # CALL
        assert "shape=note" in dot          # LITERAL
        assert "shape=hexagon" in dot       # BRANCH/LOOP
        assert "shape=rectangle" in dot     # BLOCK
        assert "shape=box3d" in dot         # CLASS

    def test_edge_styles(self, cpg: CodePropertyGraph):
        dot = to_dot(cpg)
        # CONTAINS -> solid gray
        assert "color=gray" in dot
        # DATA_FLOWS_TO -> bold blue
        assert "color=blue" in dot
        # CALLS -> dotted green
        assert "style=dotted" in dot
        assert "color=green" in dot
        # BRANCHES_TO -> dashed red
        assert "style=dashed" in dot
        assert "color=red" in dot
        # FLOWS_TO -> solid black
        assert "color=black" in dot

    def test_edge_labels(self, cpg: CodePropertyGraph):
        dot = to_dot(cpg)
        assert 'label="contains"' in dot
        assert 'label="data_flows_to"' in dot

    def test_special_chars_escaped(self, cpg: CodePropertyGraph):
        """The literal node has quotes in its name; they must be escaped."""
        dot = to_dot(cpg)
        # The label should contain the escaped version of "hello"
        assert '\\"hello\\"' in dot

    def test_filter_edge_kinds(self, cpg: CodePropertyGraph):
        dot = to_dot(cpg, edge_kinds=frozenset({EdgeKind.CONTAINS}))
        assert 'label="contains"' in dot
        assert 'label="data_flows_to"' not in dot
        assert 'label="calls"' not in dot

    def test_filter_node_kinds(self, cpg: CodePropertyGraph):
        dot = to_dot(cpg, node_kinds=frozenset({NodeKind.FUNCTION, NodeKind.VARIABLE}))
        assert "shape=component" in dot  # FUNCTION present
        assert "shape=ellipse" in dot    # VARIABLE present
        assert "shape=folder" not in dot  # MODULE excluded
        assert "shape=diamond" not in dot  # CALL excluded

    def test_empty_cpg(self):
        cpg = CodePropertyGraph()
        dot = to_dot(cpg)
        assert "digraph CPG {" in dot
        assert dot.strip().endswith("}")

    def test_arrow_syntax(self, cpg: CodePropertyGraph):
        dot = to_dot(cpg)
        assert "->" in dot

    def test_edge_kind_filter_prunes_disconnected_nodes(self, cpg: CodePropertyGraph):
        """Nodes not connected by any edge of the filtered kinds are excluded (issue #48)."""
        # The fixture CPG has: mod -CONTAINS-> fn, fn -DATA_FLOWS_TO-> var,
        # fn -CALLS-> call, br -BRANCHES_TO-> blk, blk -FLOWS_TO-> var.
        # When filtering to CALLS only, only fn and call should appear as nodes.
        dot = to_dot(cpg, edge_kinds=frozenset({EdgeKind.CALLS}))
        assert 'label="calls"' in dot
        # fn (source) and call (target) must be present
        assert "function: foo" in dot
        assert "call: bar" in dot
        # Nodes not part of any CALLS edge should not appear
        assert "module: mymod" not in dot
        assert "variable: x" not in dot
        assert "literal:" not in dot
