"""Taint propagation engine for tracking data flow through the graph.

The engine is generic -- it propagates labels through DATA_FLOWS_TO edges.
What those labels *mean* is entirely up to the consumer (security analysis,
data lineage, PII tracking, etc.).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from treeloom.analysis.summary import compute_summaries
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import CpgNode, NodeId, NodeKind

if TYPE_CHECKING:
    from treeloom.graph.cpg import CodePropertyGraph


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TaintLabel:
    """A label attached to tainted data.

    Must be hashable (frozen) so it can live in frozensets.
    """

    name: str
    origin: NodeId
    attrs: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


@dataclass
class TaintPropagator:
    """Describes how taint flows through a specific function/operation."""

    match: Callable[[CpgNode], bool]
    param_to_return: bool = True
    param_to_param: dict[int, int] | None = None


@dataclass
class TaintPolicy:
    """Consumer-provided policy that drives taint analysis.

    Attributes:
        sources: Returns a TaintLabel if the node introduces taint, else None.
        sinks: Returns True if the node is a sink.
        sanitizers: Returns True if the node sanitizes taint.
        propagators: Custom propagation rules for specific call patterns.
    """

    sources: Callable[[CpgNode], TaintLabel | None]
    sinks: Callable[[CpgNode], bool]
    sanitizers: Callable[[CpgNode], bool]
    propagators: list[TaintPropagator] = field(default_factory=list)


@dataclass
class TaintPath:
    """A single source-to-sink taint path."""

    source: CpgNode
    sink: CpgNode
    intermediates: list[CpgNode]
    labels: frozenset[TaintLabel]
    is_sanitized: bool
    sanitizers: list[CpgNode]


@dataclass
class TaintResult:
    """Aggregated result of a taint analysis run."""

    paths: list[TaintPath]
    _labels_at: dict[str, frozenset[TaintLabel]] = field(
        default_factory=dict, repr=False
    )

    def paths_to_sink(self, sink_id: NodeId) -> list[TaintPath]:
        """Return all paths ending at the given sink."""
        return [p for p in self.paths if p.sink.id == sink_id]

    def paths_from_source(self, source_id: NodeId) -> list[TaintPath]:
        """Return all paths starting from the given source."""
        return [p for p in self.paths if p.source.id == source_id]

    def unsanitized_paths(self) -> list[TaintPath]:
        """Return paths that were NOT sanitized."""
        return [p for p in self.paths if not p.is_sanitized]

    def sanitized_paths(self) -> list[TaintPath]:
        """Return paths that passed through a sanitizer."""
        return [p for p in self.paths if p.is_sanitized]

    def labels_at(self, node_id: NodeId) -> frozenset[TaintLabel]:
        """Return the set of taint labels that reached a given node."""
        return self._labels_at.get(str(node_id), frozenset())


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def run_taint(cpg: CodePropertyGraph, policy: TaintPolicy) -> TaintResult:
    """Execute worklist-based forward taint analysis.

    Algorithm:
    1. Seed the worklist with nodes where ``policy.sources`` returns a label.
    2. Propagate labels along DATA_FLOWS_TO edges.
    3. At sanitizer nodes, mark paths as sanitized but keep propagating.
    4. At CALLS edges, use function summaries to cross call boundaries.
    5. Record a TaintPath whenever a label reaches a sink node.
    """
    # -- Pre-computation ------------------------------------------------------
    summaries = compute_summaries(cpg)

    # Build DATA_FLOWS_TO forward adjacency
    dfg_fwd: dict[str, list[str]] = {}
    for edge in cpg.edges(kind=EdgeKind.DATA_FLOWS_TO):
        dfg_fwd.setdefault(str(edge.source), []).append(str(edge.target))

    # Build CALLS forward adjacency (call site -> callee function)
    calls_fwd: dict[str, list[str]] = {}
    for edge in cpg.edges(kind=EdgeKind.CALLS):
        calls_fwd.setdefault(str(edge.source), []).append(str(edge.target))

    # -- Seed -----------------------------------------------------------------
    labels_at: dict[str, frozenset[TaintLabel]] = {}
    # Track which node each label reached through (for path reconstruction)
    # parent[node_id] = set of predecessor node_ids that propagated taint here
    parent: dict[str, set[str]] = {}
    # Track sanitizer nodes hit on the way to each node
    sanitizers_on_path: dict[str, set[str]] = {}

    # (node_id_str, labels)
    worklist: deque[tuple[str, frozenset[TaintLabel]]] = deque()

    source_nodes: dict[str, CpgNode] = {}  # origin label name -> source CpgNode

    for node in cpg.nodes():
        label = policy.sources(node)
        if label is not None:
            nid = str(node.id)
            labels_at[nid] = frozenset({label})
            worklist.append((nid, frozenset({label})))
            source_nodes[nid] = node
            parent[nid] = set()
            sanitizers_on_path[nid] = set()

    # -- Propagate ------------------------------------------------------------
    sink_hits: list[tuple[str, frozenset[TaintLabel]]] = []

    while worklist:
        current_id, current_labels = worklist.popleft()
        current_node = cpg.node(NodeId(current_id))
        if current_node is None:
            continue

        is_sanitizer = policy.sanitizers(current_node)
        san_set = set(sanitizers_on_path.get(current_id, set()))
        if is_sanitizer:
            san_set.add(current_id)

        targets = list(dfg_fwd.get(current_id, []))

        # Inter-procedural: if current node is a CALL with a resolved callee,
        # propagate taint through the function summary.  When any parameter
        # flows to the return value, taint on the call site should reach
        # nodes that consume the call result.  The visitor typically emits
        # DATA_FLOWS_TO from the call to its assignment target, but if those
        # edges are absent we synthesise them by looking at DEFINED_BY
        # predecessors (variable = call_expr creates DEFINED_BY var -> call).
        if current_node.kind == NodeKind.CALL:
            for callee_id_str in calls_fwd.get(current_id, []):
                callee_id = NodeId(callee_id_str)
                summary = summaries.get(callee_id)
                if summary is not None and summary.params_to_return:
                    # Find nodes that receive this call's result via
                    # DEFINED_BY (variable -> call means call defines the var)
                    for edge in cpg.edges(kind=EdgeKind.DEFINED_BY):
                        if str(edge.target) == current_id:
                            var_id_str = str(edge.source)
                            if var_id_str not in targets:
                                targets.append(var_id_str)

        for target_id in targets:
            target_labels = labels_at.get(target_id, frozenset())
            new_labels = current_labels | target_labels

            if new_labels == target_labels:
                # Fixed point -- no new information
                continue

            labels_at[target_id] = new_labels
            parent.setdefault(target_id, set()).add(current_id)
            sanitizers_on_path[target_id] = san_set

            target_node = cpg.node(NodeId(target_id))
            if target_node is not None and policy.sanitizers(target_node):
                sanitizers_on_path[target_id] = san_set | {target_id}

            if target_node is not None and policy.sinks(target_node):
                sink_hits.append((target_id, new_labels))

            worklist.append((target_id, new_labels))

    # -- Build paths ----------------------------------------------------------
    paths: list[TaintPath] = []
    seen_paths: set[tuple[str, str]] = set()  # (source_origin_id, sink_id)

    for sink_id_str, labels in sink_hits:
        sink_node = cpg.node(NodeId(sink_id_str))
        if sink_node is None:
            continue

        for label in labels:
            origin_str = str(label.origin)
            path_key = (origin_str, sink_id_str)
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)

            source_node = cpg.node(label.origin)
            if source_node is None:
                continue

            intermediates = _reconstruct_path(origin_str, sink_id_str, parent, cpg)

            san_nodes_on_path = sanitizers_on_path.get(sink_id_str, set())
            sanitizer_cpg_nodes = [
                cpg.node(NodeId(s))
                for s in san_nodes_on_path
                if cpg.node(NodeId(s)) is not None
            ]

            path = TaintPath(
                source=source_node,
                sink=sink_node,
                intermediates=intermediates,
                labels=frozenset({label}),
                is_sanitized=len(sanitizer_cpg_nodes) > 0,
                sanitizers=sanitizer_cpg_nodes,
            )
            paths.append(path)

    return TaintResult(paths=paths, _labels_at=labels_at)


def _reconstruct_path(
    source_id: str,
    sink_id: str,
    parent: dict[str, set[str]],
    cpg: CodePropertyGraph,
) -> list[CpgNode]:
    """Reconstruct one path from source to sink using the parent map.

    Returns the list of CpgNodes along the path (including source and sink).
    Uses BFS backward from the sink to find any path to the source.
    """
    if source_id == sink_id:
        node = cpg.node(NodeId(source_id))
        return [node] if node is not None else []

    # BFS backward from sink
    visited: set[str] = {sink_id}
    queue: deque[str] = deque([sink_id])
    back: dict[str, str] = {}

    while queue:
        current = queue.popleft()
        if current == source_id:
            break
        for pred in parent.get(current, set()):
            if pred not in visited:
                visited.add(pred)
                back[pred] = current
                queue.append(pred)

    # Walk forward from source to sink
    path_ids: list[str] = [source_id]
    cursor = source_id
    while cursor != sink_id:
        nxt = back.get(cursor)
        if nxt is None:
            # Could not reconstruct full path; return source + sink
            break
        path_ids.append(nxt)
        cursor = nxt

    if path_ids[-1] != sink_id:
        # Fallback: at minimum include source and sink
        sink_node = cpg.node(NodeId(sink_id))
        src_node = cpg.node(NodeId(source_id))
        result = []
        if src_node:
            result.append(src_node)
        if sink_node:
            result.append(sink_node)
        return result

    return [n for nid in path_ids if (n := cpg.node(NodeId(nid))) is not None]
