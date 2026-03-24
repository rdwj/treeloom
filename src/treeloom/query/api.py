"""High-level query API for traversing and filtering the Code Property Graph."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import CpgNode, NodeId, NodeKind
from treeloom.query.pattern import ChainPattern, match_chain

if TYPE_CHECKING:
    from treeloom.graph.cpg import CodePropertyGraph

# Priority order for node_at tie-breaking (lower index = higher priority).
_NODE_AT_PRIORITY = [
    NodeKind.FUNCTION,
    NodeKind.CALL,
    NodeKind.VARIABLE,
]


class GraphQuery:
    """Query facade for a :class:`CodePropertyGraph`.

    Obtain an instance via ``cpg.query()``.
    """

    def __init__(self, cpg: CodePropertyGraph) -> None:
        self._cpg = cpg

    # -- Path queries ---------------------------------------------------------

    def paths_between(
        self, source: NodeId, target: NodeId, cutoff: int = 10
    ) -> list[list[CpgNode]]:
        """Return all simple paths from *source* to *target* up to *cutoff* length.

        Each path is a list of :class:`CpgNode` in traversal order.
        """
        backend = self._cpg._backend  # noqa: SLF001
        src_str, tgt_str = str(source), str(target)
        if not backend.has_node(src_str) or not backend.has_node(tgt_str):
            return []

        result: list[list[CpgNode]] = []
        for id_path in backend.all_simple_paths(src_str, tgt_str, cutoff):
            node_path = [self._cpg.node(NodeId(nid)) for nid in id_path]
            if any(n is None for n in node_path):
                continue
            result.append(node_path)  # type: ignore[arg-type]
        return result

    def reachable_from(
        self,
        node_id: NodeId,
        edge_kinds: frozenset[EdgeKind] | None = None,
    ) -> set[CpgNode]:
        """Return all nodes reachable from *node_id* following forward edges.

        When *edge_kinds* is provided, only edges of those kinds are followed.
        """
        if edge_kinds is None:
            # Fast path: use the backend's descendants() which traverses all
            # edge types via NetworkX.
            ids = self._cpg._backend.descendants(str(node_id))  # noqa: SLF001
            return {
                self._cpg.node(NodeId(nid))  # type: ignore[misc]
                for nid in ids
                if self._cpg.node(NodeId(nid)) is not None
            }

        # Filtered BFS: only follow edges of the requested kinds.
        return self._bfs_forward(node_id, edge_kinds)

    def reaching(
        self,
        node_id: NodeId,
        edge_kinds: frozenset[EdgeKind] | None = None,
    ) -> set[CpgNode]:
        """Return all nodes that can reach *node_id* via backward edges.

        When *edge_kinds* is provided, only edges of those kinds are followed
        (in the reverse direction).
        """
        if edge_kinds is None:
            ids = self._cpg._backend.ancestors(str(node_id))  # noqa: SLF001
            return {
                self._cpg.node(NodeId(nid))  # type: ignore[misc]
                for nid in ids
                if self._cpg.node(NodeId(nid)) is not None
            }

        # Filtered backward BFS.
        return self._bfs_backward(node_id, edge_kinds)

    # -- Node lookup ----------------------------------------------------------

    def node_at(self, file: Path, line: int) -> CpgNode | None:
        """Return the highest-priority node at *file*:*line*.

        Priority: FUNCTION > CALL > VARIABLE > everything else.
        """
        candidates: list[CpgNode] = []
        for cpg_node in self._cpg.nodes(file=file):
            if cpg_node.location is not None and cpg_node.location.line == line:
                candidates.append(cpg_node)

        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        def _priority(n: CpgNode) -> int:
            try:
                return _NODE_AT_PRIORITY.index(n.kind)
            except ValueError:
                return len(_NODE_AT_PRIORITY)

        candidates.sort(key=_priority)
        return candidates[0]

    def nodes_in_file(self, file: Path) -> list[CpgNode]:
        """Return all nodes located in *file*, sorted by line number."""
        result = list(self._cpg.nodes(file=file))
        result.sort(key=lambda n: (n.location.line if n.location else 0, n.name))
        return result

    def nodes_in_scope(self, scope_id: NodeId) -> list[CpgNode]:
        """Return all nodes whose scope is *scope_id*."""
        return self._cpg.children_of(scope_id)

    # -- Subgraph extraction --------------------------------------------------

    def subgraph(
        self,
        root: NodeId,
        edge_kinds: frozenset[EdgeKind] | None = None,
        max_depth: int = 10,
    ) -> CodePropertyGraph:
        """Extract a sub-CPG rooted at *root* via BFS up to *max_depth*.

        Returns a new :class:`CodePropertyGraph` containing only the reached
        nodes and their interconnecting edges.
        """
        from treeloom.graph.cpg import CodePropertyGraph

        root_node = self._cpg.node(root)
        if root_node is None:
            return CodePropertyGraph()

        # BFS to collect node IDs.
        visited: set[str] = {str(root)}
        queue: deque[tuple[str, int]] = deque([(str(root), 0)])

        while queue:
            nid_str, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for succ_str in self._cpg._backend.successors(nid_str):  # noqa: SLF001
                if succ_str not in visited:
                    # If edge_kinds filtering requested, check at least one
                    # qualifying edge exists between these nodes.
                    if edge_kinds is not None and not self._has_edge_of_kind(
                        nid_str, succ_str, edge_kinds
                    ):
                        continue
                    visited.add(succ_str)
                    queue.append((succ_str, depth + 1))

        # Build the new CPG from collected nodes and their interconnecting edges.
        sub_cpg = CodePropertyGraph()
        for nid_str in visited:
            node = self._cpg.node(NodeId(nid_str))
            if node is not None:
                sub_cpg.add_node(node)

        for edge in self._cpg.edges():
            src_str = str(edge.source)
            tgt_str = str(edge.target)
            if src_str in visited and tgt_str in visited:
                if edge_kinds is None or edge.kind in edge_kinds:
                    sub_cpg.add_edge(edge)

        # Copy annotations for included nodes.
        for nid_str in visited:
            anns = self._cpg.annotations_for(NodeId(nid_str))
            for key, value in anns.items():
                sub_cpg.annotate_node(NodeId(nid_str), key, value)

        return sub_cpg

    # -- Pattern matching -----------------------------------------------------

    def match_chain(self, pattern: ChainPattern) -> list[list[CpgNode]]:
        """Find all node chains matching *pattern*."""
        return match_chain(self._cpg, pattern)

    # -- Internal helpers -----------------------------------------------------

    def _bfs_forward(
        self, start: NodeId, edge_kinds: frozenset[EdgeKind]
    ) -> set[CpgNode]:
        """BFS following only edges of the given kinds."""
        visited: set[str] = set()
        queue: deque[str] = deque([str(start)])

        while queue:
            nid_str = queue.popleft()
            node = self._cpg.node(NodeId(nid_str))
            if node is None:
                continue
            for kind in edge_kinds:
                for succ in self._cpg.successors(node.id, edge_kind=kind):
                    succ_str = str(succ.id)
                    if succ_str not in visited:
                        visited.add(succ_str)
                        queue.append(succ_str)

        return {
            self._cpg.node(NodeId(nid))  # type: ignore[misc]
            for nid in visited
            if self._cpg.node(NodeId(nid)) is not None
        }

    def _bfs_backward(
        self, start: NodeId, edge_kinds: frozenset[EdgeKind]
    ) -> set[CpgNode]:
        """Backward BFS following only edges of the given kinds."""
        visited: set[str] = set()
        queue: deque[str] = deque([str(start)])

        while queue:
            nid_str = queue.popleft()
            node = self._cpg.node(NodeId(nid_str))
            if node is None:
                continue
            for kind in edge_kinds:
                for pred in self._cpg.predecessors(node.id, edge_kind=kind):
                    pred_str = str(pred.id)
                    if pred_str not in visited:
                        visited.add(pred_str)
                        queue.append(pred_str)

        return {
            self._cpg.node(NodeId(nid))  # type: ignore[misc]
            for nid in visited
            if self._cpg.node(NodeId(nid)) is not None
        }

    def _has_edge_of_kind(
        self, source_str: str, target_str: str, edge_kinds: frozenset[EdgeKind]
    ) -> bool:
        """Check whether any edge of the requested kinds exists between two nodes."""
        for edge in self._cpg.edges():
            if (
                str(edge.source) == source_str
                and str(edge.target) == target_str
                and edge.kind in edge_kinds
            ):
                return True
        return False
