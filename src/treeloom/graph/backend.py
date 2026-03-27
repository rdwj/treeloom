"""Storage backends for the Code Property Graph (NetworkX, future: rustworkx)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

import networkx as nx


class GraphBackend(Protocol):
    """Abstract graph storage interface.

    All return types are Python builtins -- implementations must not leak
    library-specific types (e.g., NetworkX node views).
    """

    def add_node(self, node_id: str, **attrs: Any) -> None: ...
    def add_edge(self, source: str, target: str, key: str | None = None, **attrs: Any) -> None: ...
    def get_node(self, node_id: str) -> dict[str, Any] | None: ...
    def get_edge(self, source: str, target: str) -> dict[str, Any] | None: ...
    def has_node(self, node_id: str) -> bool: ...
    def has_edge(self, source: str, target: str) -> bool: ...
    def remove_node(self, node_id: str) -> None: ...
    def remove_edge(self, source: str, target: str, key: str | None = None) -> None: ...
    def successors(self, node_id: str) -> list[str]: ...
    def predecessors(self, node_id: str) -> list[str]: ...
    def all_nodes(self) -> Iterator[tuple[str, dict[str, Any]]]: ...
    def all_edges(self) -> Iterator[tuple[str, str, dict[str, Any]]]: ...
    def node_count(self) -> int: ...
    def edge_count(self) -> int: ...
    def all_simple_paths(self, source: str, target: str, cutoff: int) -> Iterator[list[str]]: ...
    def descendants(self, node_id: str) -> set[str]: ...
    def ancestors(self, node_id: str) -> set[str]: ...
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphBackend: ...


class NetworkXBackend:
    """Graph backend backed by networkx.MultiDiGraph.

    Uses MultiDiGraph (not DiGraph) because multiple edge types can exist
    between the same node pair (e.g., CONTAINS + DATA_FLOWS_TO).
    Edge kind is stored as the ``key`` parameter on MultiDiGraph edges.
    """

    def __init__(self) -> None:
        self._graph: nx.MultiDiGraph = nx.MultiDiGraph()

    def add_node(self, node_id: str, **attrs: Any) -> None:
        self._graph.add_node(node_id, **attrs)

    def add_edge(self, source: str, target: str, key: str | None = None, **attrs: Any) -> None:
        self._graph.add_edge(source, target, key=key, **attrs)

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        if node_id not in self._graph:
            return None
        return dict(self._graph.nodes[node_id])

    def get_edge(self, source: str, target: str) -> dict[str, Any] | None:
        if not self._graph.has_edge(source, target):
            return None
        # Return the first edge's attrs (there may be multiple with different keys)
        edge_data = self._graph.get_edge_data(source, target)
        if not edge_data:
            return None
        first_key = next(iter(edge_data))
        return dict(edge_data[first_key])

    def has_node(self, node_id: str) -> bool:
        return node_id in self._graph

    def has_edge(self, source: str, target: str) -> bool:
        return self._graph.has_edge(source, target)

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all its adjacent edges."""
        if node_id in self._graph:
            self._graph.remove_node(node_id)

    def remove_edge(self, source: str, target: str, key: str | None = None) -> None:
        """Remove an edge. If key is given, remove only that edge kind."""
        if self._graph.has_edge(source, target, key=key):
            self._graph.remove_edge(source, target, key=key)

    def successors(self, node_id: str) -> list[str]:
        return list(self._graph.successors(node_id))

    def predecessors(self, node_id: str) -> list[str]:
        return list(self._graph.predecessors(node_id))

    def all_nodes(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for node_id, attrs in self._graph.nodes(data=True):
            yield str(node_id), dict(attrs)

    def all_edges(self) -> Iterator[tuple[str, str, dict[str, Any]]]:
        for source, target, key, attrs in self._graph.edges(data=True, keys=True):
            edge_attrs = dict(attrs)
            edge_attrs["key"] = key
            yield str(source), str(target), edge_attrs

    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    def all_simple_paths(self, source: str, target: str, cutoff: int) -> Iterator[list[str]]:
        for path in nx.all_simple_paths(self._graph, source, target, cutoff=cutoff):
            yield [str(n) for n in path]

    def descendants(self, node_id: str) -> set[str]:
        return {str(n) for n in nx.descendants(self._graph, node_id)}

    def ancestors(self, node_id: str) -> set[str]:
        return {str(n) for n in nx.ancestors(self._graph, node_id)}

    def to_dict(self) -> dict[str, Any]:
        nodes = []
        for node_id, attrs in self._graph.nodes(data=True):
            nodes.append({"id": str(node_id), "attrs": dict(attrs)})

        edges = []
        for source, target, key, attrs in self._graph.edges(data=True, keys=True):
            edges.append({
                "source": str(source),
                "target": str(target),
                "key": key,
                "attrs": dict(attrs),
            })

        return {"nodes": nodes, "edges": edges}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkXBackend:
        backend = cls()
        for node_data in data["nodes"]:
            backend.add_node(node_data["id"], **node_data["attrs"])
        for edge_data in data["edges"]:
            backend.add_edge(
                edge_data["source"],
                edge_data["target"],
                key=edge_data.get("key"),
                **edge_data["attrs"],
            )
        return backend
