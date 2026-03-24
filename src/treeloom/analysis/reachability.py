"""Reachability analysis: determine if a path exists between graph nodes.

Provides forward and backward BFS traversals over the CPG, with optional
edge-kind filtering.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import CpgNode, NodeId

if TYPE_CHECKING:
    from treeloom.graph.cpg import CodePropertyGraph


def forward_reachable(
    cpg: CodePropertyGraph,
    start: NodeId,
    edge_kinds: frozenset[EdgeKind] | None = None,
) -> set[CpgNode]:
    """Return all nodes reachable from *start* by following forward edges.

    When *edge_kinds* is ``None``, all edge types are followed (delegates
    to the backend's ``descendants`` for efficiency).  When specified, only
    edges of the given kinds are traversed.
    """
    if edge_kinds is None:
        desc_ids = cpg._backend.descendants(str(start))
        return {
            cpg.node(NodeId(nid))
            for nid in desc_ids
            if cpg.node(NodeId(nid)) is not None
        }

    # Manual BFS with edge-kind filtering
    adjacency = _build_forward_adjacency(cpg, edge_kinds)
    visited = _bfs(str(start), adjacency)
    visited.discard(str(start))  # don't include start itself
    return {
        cpg.node(NodeId(nid))
        for nid in visited
        if cpg.node(NodeId(nid)) is not None
    }


def backward_reachable(
    cpg: CodePropertyGraph,
    target: NodeId,
    edge_kinds: frozenset[EdgeKind] | None = None,
) -> set[CpgNode]:
    """Return all nodes from which *target* is reachable by following edges.

    When *edge_kinds* is ``None``, all edge types are considered (delegates
    to the backend's ``ancestors`` for efficiency).  When specified, only
    edges of the given kinds are considered.
    """
    if edge_kinds is None:
        anc_ids = cpg._backend.ancestors(str(target))
        return {
            cpg.node(NodeId(nid))
            for nid in anc_ids
            if cpg.node(NodeId(nid)) is not None
        }

    # Manual BFS over reversed adjacency
    adjacency = _build_reverse_adjacency(cpg, edge_kinds)
    visited = _bfs(str(target), adjacency)
    visited.discard(str(target))  # don't include target itself
    return {
        cpg.node(NodeId(nid))
        for nid in visited
        if cpg.node(NodeId(nid)) is not None
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_forward_adjacency(
    cpg: CodePropertyGraph,
    edge_kinds: frozenset[EdgeKind],
) -> dict[str, list[str]]:
    """Build a forward adjacency list filtered by edge kinds."""
    adj: dict[str, list[str]] = {}
    for kind in edge_kinds:
        for edge in cpg.edges(kind=kind):
            adj.setdefault(str(edge.source), []).append(str(edge.target))
    return adj


def _build_reverse_adjacency(
    cpg: CodePropertyGraph,
    edge_kinds: frozenset[EdgeKind],
) -> dict[str, list[str]]:
    """Build a reverse adjacency list filtered by edge kinds."""
    adj: dict[str, list[str]] = {}
    for kind in edge_kinds:
        for edge in cpg.edges(kind=kind):
            adj.setdefault(str(edge.target), []).append(str(edge.source))
    return adj


def _bfs(start: str, adjacency: dict[str, list[str]]) -> set[str]:
    """Plain BFS over an adjacency list, returning all visited node IDs."""
    visited: set[str] = {start}
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        for neighbour in adjacency.get(current, []):
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append(neighbour)
    return visited
