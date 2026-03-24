"""Tests for treeloom.analysis.reachability — forward/backward BFS."""

from __future__ import annotations

from treeloom.analysis.reachability import backward_reachable, forward_reachable
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeId, NodeKind

from .conftest import add_edge, make_node


def _build_chain_cpg() -> CodePropertyGraph:
    """Build a linear chain: a -> b -> c -> d with DATA_FLOWS_TO edges,
    plus a CONTAINS edge from a -> b for edge-kind filtering tests.
    """
    cpg = CodePropertyGraph()
    cpg.add_node(make_node(NodeKind.VARIABLE, "a", "a", line=1))
    cpg.add_node(make_node(NodeKind.VARIABLE, "b", "b", line=2))
    cpg.add_node(make_node(NodeKind.VARIABLE, "c", "c", line=3))
    cpg.add_node(make_node(NodeKind.CALL, "d", "d", line=4))

    add_edge(cpg, "a", "b", EdgeKind.DATA_FLOWS_TO)
    add_edge(cpg, "b", "c", EdgeKind.DATA_FLOWS_TO)
    add_edge(cpg, "c", "d", EdgeKind.DATA_FLOWS_TO)

    # Extra edge of a different kind
    add_edge(cpg, "a", "b", EdgeKind.CONTAINS)

    return cpg


class TestForwardReachable:
    def test_all_edges(self):
        cpg = _build_chain_cpg()
        reachable = forward_reachable(cpg, NodeId("a"))
        names = {n.name for n in reachable}
        assert names == {"b", "c", "d"}

    def test_filtered_by_edge_kind(self):
        cpg = _build_chain_cpg()
        reachable = forward_reachable(
            cpg, NodeId("a"),
            edge_kinds=frozenset({EdgeKind.DATA_FLOWS_TO}),
        )
        names = {n.name for n in reachable}
        assert names == {"b", "c", "d"}

    def test_contains_only(self):
        cpg = _build_chain_cpg()
        reachable = forward_reachable(
            cpg, NodeId("a"),
            edge_kinds=frozenset({EdgeKind.CONTAINS}),
        )
        names = {n.name for n in reachable}
        # Only b is reachable via CONTAINS from a
        assert names == {"b"}

    def test_start_not_in_result(self):
        cpg = _build_chain_cpg()
        reachable = forward_reachable(cpg, NodeId("a"))
        ids = {str(n.id) for n in reachable}
        assert "a" not in ids

    def test_unreachable_node(self):
        cpg = _build_chain_cpg()
        # Add an isolated node
        cpg.add_node(make_node(NodeKind.VARIABLE, "isolated", "iso", line=10))
        reachable = forward_reachable(cpg, NodeId("a"))
        ids = {str(n.id) for n in reachable}
        assert "iso" not in ids


class TestBackwardReachable:
    def test_all_edges(self):
        cpg = _build_chain_cpg()
        reachable = backward_reachable(cpg, NodeId("d"))
        names = {n.name for n in reachable}
        assert names == {"a", "b", "c"}

    def test_filtered_by_edge_kind(self):
        cpg = _build_chain_cpg()
        reachable = backward_reachable(
            cpg, NodeId("d"),
            edge_kinds=frozenset({EdgeKind.DATA_FLOWS_TO}),
        )
        names = {n.name for n in reachable}
        assert names == {"a", "b", "c"}

    def test_target_not_in_result(self):
        cpg = _build_chain_cpg()
        reachable = backward_reachable(cpg, NodeId("d"))
        ids = {str(n.id) for n in reachable}
        assert "d" not in ids

    def test_partial_reachability(self):
        cpg = _build_chain_cpg()
        reachable = backward_reachable(cpg, NodeId("c"))
        names = {n.name for n in reachable}
        assert "d" not in names
        assert "a" in names
        assert "b" in names
