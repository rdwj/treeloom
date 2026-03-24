"""Function summaries: intra-procedural data flow aggregation.

For each function in the CPG, a FunctionSummary captures which parameters
flow to the return value and which flow to internal call sites (potential
sinks). These summaries enable inter-procedural taint analysis without
full function inlining.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeId, NodeKind

if TYPE_CHECKING:
    from treeloom.graph.cpg import CodePropertyGraph


@dataclass
class FunctionSummary:
    """Summarises how data flows through a function.

    Attributes:
        function_id: The NodeId of the FUNCTION node.
        function_name: Human-readable function name.
        params_to_return: 0-based parameter positions whose data reaches
            a RETURN node inside the function.
        params_to_sinks: Mapping from parameter position to a list of
            internal CALL NodeIds that the parameter data reaches.
        introduces_taint: Whether the function body introduces new data
            that was not provided via parameters (e.g. file reads).
    """

    function_id: NodeId
    function_name: str
    params_to_return: list[int] = field(default_factory=list)
    params_to_sinks: dict[int, list[NodeId]] = field(default_factory=dict)
    introduces_taint: bool = False


def compute_summaries(cpg: CodePropertyGraph) -> dict[NodeId, FunctionSummary]:
    """Compute a FunctionSummary for every FUNCTION node in the CPG.

    The algorithm walks intra-procedural DATA_FLOWS_TO edges forward from
    each PARAMETER node.  If a path reaches a RETURN node, that parameter
    position is recorded in ``params_to_return``.  If it reaches a CALL
    node, the call is recorded in ``params_to_sinks``.
    """
    summaries: dict[NodeId, FunctionSummary] = {}

    # Pre-compute the set of children per function for scope filtering
    function_children: dict[str, set[str]] = {}
    for node in cpg.nodes(kind=NodeKind.FUNCTION):
        children = cpg.children_of(node.id)
        function_children[str(node.id)] = {str(c.id) for c in children}

    # Pre-compute DATA_FLOWS_TO adjacency (forward) for quick BFS
    dfg_forward: dict[str, list[str]] = {}
    for edge in cpg.edges(kind=EdgeKind.DATA_FLOWS_TO):
        src = str(edge.source)
        dfg_forward.setdefault(src, []).append(str(edge.target))

    for func_node in cpg.nodes(kind=NodeKind.FUNCTION):
        summary = FunctionSummary(
            function_id=func_node.id,
            function_name=func_node.name,
        )

        scope_nodes = function_children.get(str(func_node.id), set())

        # Find parameter nodes for this function
        params = [
            n for n in cpg.successors(func_node.id, edge_kind=EdgeKind.HAS_PARAMETER)
            if n.kind == NodeKind.PARAMETER
        ]
        # Sort by position attribute for stable ordering
        params.sort(key=lambda p: p.attrs.get("position", 0))

        for param in params:
            position = param.attrs.get("position", 0)
            reachable = _bfs_forward(
                str(param.id), dfg_forward, scope_nodes
            )

            for reached_id in reachable:
                reached_node = cpg.node(NodeId(reached_id))
                if reached_node is None:
                    continue
                if reached_node.kind == NodeKind.RETURN:
                    if position not in summary.params_to_return:
                        summary.params_to_return.append(position)
                elif reached_node.kind == NodeKind.CALL:
                    summary.params_to_sinks.setdefault(position, []).append(
                        reached_node.id
                    )

        summaries[func_node.id] = summary

    return summaries


def _bfs_forward(
    start: str,
    adjacency: dict[str, list[str]],
    scope_nodes: set[str],
) -> set[str]:
    """BFS over DATA_FLOWS_TO edges, restricted to nodes within scope."""
    visited: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        for neighbour in adjacency.get(current, []):
            if neighbour in visited:
                continue
            # Only follow edges to nodes within the same function scope
            # (or the start node itself, which is the parameter)
            if neighbour not in scope_nodes and neighbour != start:
                continue
            visited.add(neighbour)
            queue.append(neighbour)
    return visited
