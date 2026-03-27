"""Tests for NetworkXBackend."""

from __future__ import annotations

import pytest

from treeloom.graph.backend import NetworkXBackend


@pytest.fixture()
def backend() -> NetworkXBackend:
    return NetworkXBackend()


class TestNodeOperations:
    def test_add_and_get_node(self, backend: NetworkXBackend):
        backend.add_node("n1", kind="function", name="foo")
        result = backend.get_node("n1")
        assert result is not None
        assert result["kind"] == "function"
        assert result["name"] == "foo"

    def test_get_nonexistent_node(self, backend: NetworkXBackend):
        assert backend.get_node("missing") is None

    def test_has_node(self, backend: NetworkXBackend):
        assert not backend.has_node("n1")
        backend.add_node("n1")
        assert backend.has_node("n1")

    def test_node_count(self, backend: NetworkXBackend):
        assert backend.node_count() == 0
        backend.add_node("a")
        backend.add_node("b")
        assert backend.node_count() == 2

    def test_all_nodes(self, backend: NetworkXBackend):
        backend.add_node("a", x=1)
        backend.add_node("b", x=2)
        nodes = dict(backend.all_nodes())
        assert len(nodes) == 2
        assert nodes["a"]["x"] == 1
        assert nodes["b"]["x"] == 2

    def test_get_node_returns_dict_not_nx_type(self, backend: NetworkXBackend):
        backend.add_node("n1", foo="bar")
        result = backend.get_node("n1")
        assert type(result) is dict


class TestEdgeOperations:
    def test_add_and_get_edge(self, backend: NetworkXBackend):
        backend.add_node("a")
        backend.add_node("b")
        backend.add_edge("a", "b", key="contains", weight=1.0)
        result = backend.get_edge("a", "b")
        assert result is not None
        assert result["weight"] == 1.0

    def test_get_nonexistent_edge(self, backend: NetworkXBackend):
        backend.add_node("a")
        backend.add_node("b")
        assert backend.get_edge("a", "b") is None

    def test_has_edge(self, backend: NetworkXBackend):
        backend.add_node("a")
        backend.add_node("b")
        assert not backend.has_edge("a", "b")
        backend.add_edge("a", "b", key="contains")
        assert backend.has_edge("a", "b")

    def test_multiple_edges_between_same_pair(self, backend: NetworkXBackend):
        """MultiDiGraph supports multiple edge types between the same node pair."""
        backend.add_node("a")
        backend.add_node("b")
        backend.add_edge("a", "b", key="contains")
        backend.add_edge("a", "b", key="data_flows_to")
        assert backend.edge_count() == 2

    def test_edge_count(self, backend: NetworkXBackend):
        backend.add_node("a")
        backend.add_node("b")
        assert backend.edge_count() == 0
        backend.add_edge("a", "b", key="contains")
        assert backend.edge_count() == 1

    def test_all_edges(self, backend: NetworkXBackend):
        backend.add_node("a")
        backend.add_node("b")
        backend.add_edge("a", "b", key="contains", x=1)
        backend.add_edge("a", "b", key="data_flows_to", x=2)
        edges = list(backend.all_edges())
        assert len(edges) == 2
        keys = {e[2]["key"] for e in edges}
        assert keys == {"contains", "data_flows_to"}

    def test_get_edge_returns_dict_not_nx_type(self, backend: NetworkXBackend):
        backend.add_node("a")
        backend.add_node("b")
        backend.add_edge("a", "b", key="k")
        result = backend.get_edge("a", "b")
        assert type(result) is dict


class TestTraversal:
    def test_successors(self, backend: NetworkXBackend):
        backend.add_node("a")
        backend.add_node("b")
        backend.add_node("c")
        backend.add_edge("a", "b", key="e1")
        backend.add_edge("a", "c", key="e2")
        succs = backend.successors("a")
        assert sorted(succs) == ["b", "c"]
        assert all(type(s) is str for s in succs)

    def test_predecessors(self, backend: NetworkXBackend):
        backend.add_node("a")
        backend.add_node("b")
        backend.add_node("c")
        backend.add_edge("a", "c", key="e1")
        backend.add_edge("b", "c", key="e2")
        preds = backend.predecessors("c")
        assert sorted(preds) == ["a", "b"]

    def test_all_simple_paths(self, backend: NetworkXBackend):
        # a -> b -> c, a -> c
        for n in "abcd":
            backend.add_node(n)
        backend.add_edge("a", "b", key="e1")
        backend.add_edge("b", "c", key="e2")
        backend.add_edge("a", "c", key="e3")
        paths = list(backend.all_simple_paths("a", "c", cutoff=5))
        assert len(paths) == 2
        assert ["a", "c"] in paths
        assert ["a", "b", "c"] in paths

    def test_descendants(self, backend: NetworkXBackend):
        for n in "abcd":
            backend.add_node(n)
        backend.add_edge("a", "b", key="e1")
        backend.add_edge("b", "c", key="e2")
        backend.add_edge("a", "d", key="e3")
        desc = backend.descendants("a")
        assert desc == {"b", "c", "d"}
        assert all(type(d) is str for d in desc)

    def test_ancestors(self, backend: NetworkXBackend):
        for n in "abcd":
            backend.add_node(n)
        backend.add_edge("a", "c", key="e1")
        backend.add_edge("b", "c", key="e2")
        backend.add_edge("c", "d", key="e3")
        anc = backend.ancestors("d")
        assert anc == {"a", "b", "c"}

    def test_descendants_empty(self, backend: NetworkXBackend):
        backend.add_node("a")
        assert backend.descendants("a") == set()


class TestSerialization:
    def test_round_trip(self, backend: NetworkXBackend):
        backend.add_node("a", kind="module")
        backend.add_node("b", kind="function")
        backend.add_edge("a", "b", key="contains", weight=1)
        backend.add_edge("a", "b", key="data_flows_to")

        data = backend.to_dict()
        restored = NetworkXBackend.from_dict(data)

        assert restored.node_count() == 2
        assert restored.edge_count() == 2
        assert restored.get_node("a") == {"kind": "module"}
        assert restored.get_node("b") == {"kind": "function"}
        assert restored.has_edge("a", "b")

    def test_round_trip_preserves_edge_keys(self, backend: NetworkXBackend):
        backend.add_node("a")
        backend.add_node("b")
        backend.add_edge("a", "b", key="contains")
        backend.add_edge("a", "b", key="calls")

        data = backend.to_dict()
        restored = NetworkXBackend.from_dict(data)

        edges = list(restored.all_edges())
        keys = {e[2]["key"] for e in edges}
        assert keys == {"contains", "calls"}

    def test_to_dict_returns_plain_dict(self, backend: NetworkXBackend):
        backend.add_node("a")
        data = backend.to_dict()
        assert type(data) is dict
        assert type(data["nodes"]) is list


class TestRemoveNode:
    def test_remove_existing_node(self):
        backend = NetworkXBackend()
        backend.add_node("a")
        backend.add_node("b")
        backend.add_edge("a", "b", key="contains")
        backend.remove_node("a")
        assert not backend.has_node("a")
        assert backend.has_node("b")
        assert not backend.has_edge("a", "b")

    def test_remove_nonexistent_node(self):
        backend = NetworkXBackend()
        backend.remove_node("missing")  # Should not raise

    def test_remove_cascades_edges(self):
        backend = NetworkXBackend()
        backend.add_node("a")
        backend.add_node("b")
        backend.add_node("c")
        backend.add_edge("a", "b", key="e1")
        backend.add_edge("b", "c", key="e2")
        backend.remove_node("b")
        assert backend.edge_count() == 0


class TestRemoveEdge:
    def test_remove_existing_edge(self):
        backend = NetworkXBackend()
        backend.add_node("a")
        backend.add_node("b")
        backend.add_edge("a", "b", key="contains")
        backend.remove_edge("a", "b", key="contains")
        assert not backend.has_edge("a", "b")
        assert backend.has_node("a")
        assert backend.has_node("b")

    def test_remove_nonexistent_edge(self):
        backend = NetworkXBackend()
        backend.add_node("a")
        backend.add_node("b")
        backend.remove_edge("a", "b", key="e1")  # Should not raise

    def test_remove_one_edge_keeps_others(self):
        backend = NetworkXBackend()
        backend.add_node("a")
        backend.add_node("b")
        backend.add_edge("a", "b", key="contains")
        backend.add_edge("a", "b", key="data_flows_to")
        backend.remove_edge("a", "b", key="contains")
        assert backend.has_edge("a", "b")  # data_flows_to still there
        assert backend.edge_count() == 1
