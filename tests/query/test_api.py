"""Tests for treeloom.query.api.GraphQuery."""

from __future__ import annotations

from pathlib import Path

from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeId, NodeKind

from .conftest import FAKE_FILE, OTHER_FILE, make_node


class TestPathsBetween:
    def test_simple_linear_path(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        paths = q.paths_between(NodeId("a"), NodeId("d"))
        assert len(paths) == 1
        assert [str(n.id) for n in paths[0]] == ["a", "b", "c", "d"]

    def test_no_path(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        # d -> a has no path (edges are forward only)
        assert q.paths_between(NodeId("d"), NodeId("a")) == []

    def test_branching_paths(self, branching_cpg: CodePropertyGraph) -> None:
        q = branching_cpg.query()
        paths = q.paths_between(NodeId("param"), NodeId("sink"))
        # MultiDiGraph treats different edge keys as distinct paths, so we
        # may get duplicates at the node level. Check unique node sequences.
        path_ids = {tuple(str(n.id) for n in p) for p in paths}
        assert ("param", "branch", "left", "sink") in path_ids
        assert ("param", "branch", "right", "sink") in path_ids
        assert len(path_ids) == 2

    def test_cutoff_limits_depth(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        # cutoff=2 means max path length of 2 edges (3 nodes)
        paths = q.paths_between(NodeId("a"), NodeId("d"), cutoff=2)
        assert paths == []

    def test_missing_node_returns_empty(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        assert q.paths_between(NodeId("a"), NodeId("nonexistent")) == []


class TestReachableFrom:
    def test_all_edges(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        reachable = q.reachable_from(NodeId("a"))
        reachable_ids = {str(n.id) for n in reachable}
        assert "b" in reachable_ids
        assert "c" in reachable_ids
        assert "d" in reachable_ids
        assert "a" not in reachable_ids  # source excluded

    def test_filtered_by_edge_kind(self, branching_cpg: CodePropertyGraph) -> None:
        q = branching_cpg.query()
        # Only follow BRANCHES_TO from "branch" node
        reachable = q.reachable_from(
            NodeId("branch"), edge_kinds=frozenset({EdgeKind.BRANCHES_TO})
        )
        reachable_ids = {str(n.id) for n in reachable}
        assert "left" in reachable_ids
        assert "right" in reachable_ids
        # sink is only reachable via DATA_FLOWS_TO, not BRANCHES_TO
        assert "sink" not in reachable_ids

    def test_leaf_node_has_no_reachable(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        assert q.reachable_from(NodeId("d")) == set()


class TestReaching:
    def test_backward_reachability(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        reaching = q.reaching(NodeId("d"))
        reaching_ids = {str(n.id) for n in reaching}
        # Everything flows into d: a -> b -> c -> d, plus fn CONTAINS d
        assert "a" in reaching_ids
        assert "c" in reaching_ids

    def test_filtered_backward(self, branching_cpg: CodePropertyGraph) -> None:
        q = branching_cpg.query()
        reaching = q.reaching(
            NodeId("sink"), edge_kinds=frozenset({EdgeKind.DATA_FLOWS_TO})
        )
        reaching_ids = {str(n.id) for n in reaching}
        assert "left" in reaching_ids
        assert "right" in reaching_ids
        assert "branch" in reaching_ids
        assert "param" in reaching_ids

    def test_root_node_has_no_reaching(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.MODULE, "mod", "mod")
        cpg.add_node(node)
        q = cpg.query()
        assert q.reaching(NodeId("mod")) == set()


class TestNodeAt:
    def test_single_node_at_line(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        node = q.node_at(FAKE_FILE, 2)
        assert node is not None
        assert node.name == "a"

    def test_priority_function_over_variable(self) -> None:
        """When multiple nodes share a line, FUNCTION wins."""
        cpg = CodePropertyGraph()
        var = make_node(NodeKind.VARIABLE, "x", "var", line=5)
        fn = make_node(NodeKind.FUNCTION, "fn", "fn", line=5)
        cpg.add_node(var)
        cpg.add_node(fn)
        q = cpg.query()
        result = q.node_at(FAKE_FILE, 5)
        assert result is not None
        assert result.kind == NodeKind.FUNCTION

    def test_priority_call_over_variable(self) -> None:
        cpg = CodePropertyGraph()
        var = make_node(NodeKind.VARIABLE, "x", "var", line=5)
        call = make_node(NodeKind.CALL, "foo", "call", line=5)
        cpg.add_node(var)
        cpg.add_node(call)
        q = cpg.query()
        result = q.node_at(FAKE_FILE, 5)
        assert result is not None
        assert result.kind == NodeKind.CALL

    def test_no_node_at_line(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        assert q.node_at(FAKE_FILE, 999) is None

    def test_wrong_file(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        assert q.node_at(Path("nonexistent.py"), 1) is None


class TestNodesInFile:
    def test_returns_all_file_nodes(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        nodes = q.nodes_in_file(FAKE_FILE)
        assert len(nodes) == 5  # fn, a, b, c, d

    def test_sorted_by_line(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        nodes = q.nodes_in_file(FAKE_FILE)
        lines = [n.location.line for n in nodes if n.location]
        assert lines == sorted(lines)

    def test_empty_for_unknown_file(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        assert q.nodes_in_file(Path("unknown.py")) == []

    def test_multi_file(self) -> None:
        cpg = CodePropertyGraph()
        n1 = make_node(NodeKind.FUNCTION, "f1", "f1", line=1, file=FAKE_FILE)
        n2 = make_node(NodeKind.FUNCTION, "f2", "f2", line=1, file=OTHER_FILE)
        cpg.add_node(n1)
        cpg.add_node(n2)
        q = cpg.query()
        assert len(q.nodes_in_file(FAKE_FILE)) == 1
        assert len(q.nodes_in_file(OTHER_FILE)) == 1


class TestNodesInScope:
    def test_returns_children(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        children = q.nodes_in_scope(NodeId("fn"))
        child_ids = {str(n.id) for n in children}
        assert child_ids == {"a", "b", "c", "d"}

    def test_empty_scope(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        # "d" has no children
        assert q.nodes_in_scope(NodeId("d")) == []


class TestSubgraph:
    def test_basic_subgraph(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        sub = q.subgraph(NodeId("a"), max_depth=2)
        # a -> b -> c (depth 2), d is at depth 3 so excluded
        assert sub.node(NodeId("a")) is not None
        assert sub.node(NodeId("b")) is not None
        assert sub.node(NodeId("c")) is not None
        assert sub.node(NodeId("d")) is None

    def test_subgraph_with_edge_filter(self, branching_cpg: CodePropertyGraph) -> None:
        q = branching_cpg.query()
        sub = q.subgraph(
            NodeId("branch"),
            edge_kinds=frozenset({EdgeKind.BRANCHES_TO}),
            max_depth=5,
        )
        # Only BRANCHES_TO edges followed: branch -> left, branch -> right
        assert sub.node(NodeId("branch")) is not None
        assert sub.node(NodeId("left")) is not None
        assert sub.node(NodeId("right")) is not None
        # sink is only reachable via DATA_FLOWS_TO
        assert sub.node(NodeId("sink")) is None

    def test_subgraph_preserves_annotations(self, linear_cpg: CodePropertyGraph) -> None:
        linear_cpg.annotate_node(NodeId("a"), "role", "source")
        q = linear_cpg.query()
        sub = q.subgraph(NodeId("a"), max_depth=1)
        assert sub.get_annotation(NodeId("a"), "role") == "source"

    def test_subgraph_missing_root(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        sub = q.subgraph(NodeId("nonexistent"))
        assert sub.node_count == 0

    def test_subgraph_edges_included(self, linear_cpg: CodePropertyGraph) -> None:
        q = linear_cpg.query()
        sub = q.subgraph(NodeId("a"), max_depth=10)
        edges = list(sub.edges(kind=EdgeKind.DATA_FLOWS_TO))
        edge_pairs = {(str(e.source), str(e.target)) for e in edges}
        assert ("a", "b") in edge_pairs
        assert ("b", "c") in edge_pairs
        assert ("c", "d") in edge_pairs


class TestEmptyCPG:
    def test_paths_between_empty(self) -> None:
        cpg = CodePropertyGraph()
        q = cpg.query()
        assert q.paths_between(NodeId("x"), NodeId("y")) == []

    def test_reachable_from_empty(self) -> None:
        cpg = CodePropertyGraph()
        q = cpg.query()
        # descendants on a non-existent node raises in networkx;
        # but we still test that it handles gracefully if node exists but is isolated.
        cpg.add_node(make_node(NodeKind.MODULE, "m", "m"))
        assert q.reachable_from(NodeId("m")) == set()

    def test_node_at_empty(self) -> None:
        cpg = CodePropertyGraph()
        q = cpg.query()
        assert q.node_at(FAKE_FILE, 1) is None
