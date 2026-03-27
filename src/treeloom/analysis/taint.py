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
    # Specific param positions that flow to the return value.
    # Takes precedence over param_to_return when set.
    params_to_return: list[int] | None = None


@dataclass
class TaintPolicy:
    """Consumer-provided policy that drives taint analysis.

    Attributes:
        sources: Returns a TaintLabel if the node introduces taint, else None.
        sinks: Returns True if the node is a sink.
        sanitizers: Returns True if the node sanitizes taint.
        propagators: Custom propagation rules for specific call patterns.
        implicit_param_sources: When True, every PARAMETER node is automatically
            treated as a taint source with label ``param:<name>``.  Explicit
            sources defined by ``sources`` take precedence — parameters that are
            already seeded by the explicit source callback are not overridden.
    """

    sources: Callable[[CpgNode], TaintLabel | None]
    sinks: Callable[[CpgNode], bool]
    sanitizers: Callable[[CpgNode], bool]
    propagators: list[TaintPropagator] = field(default_factory=list)
    implicit_param_sources: bool = False


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
    _edge_labels: dict[tuple[str, str], frozenset[TaintLabel]] = field(
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

    def edge_labels(self, source: NodeId, target: NodeId) -> frozenset[TaintLabel]:
        """Return the taint labels that flow along the edge from *source* to *target*."""
        return self._edge_labels.get((str(source), str(target)), frozenset())

    def apply_to(self, cpg: CodePropertyGraph) -> None:
        """Stamp taint analysis results onto the graph as annotations.

        After calling this, any node/edge in the CPG carries its taint status
        as annotations, making the graph self-describing for downstream
        inspection and subgraph extraction.

        Annotations written per node:
          - ``tainted`` (bool): True if any taint label reached this node.
          - ``taint_labels`` (list[str]): Sorted label names at the node.
          - ``taint_role`` (str): One of ``"source"``, ``"sink"``,
            ``"sanitizer"``, or ``"intermediate"``.
          - ``taint_sanitized`` (bool, sinks only): False if *any* path
            reaching the sink is unsanitized.

        Annotations written per edge (along taint paths):
          - ``tainted`` (bool): True.
          - ``taint_labels`` (list[str]): Labels carried along the path.
        """
        # -- Per-node taint labels ------------------------------------------------
        for node_id_str, labels in self._labels_at.items():
            if labels:
                node_id = NodeId(node_id_str)
                cpg.annotate_node(node_id, "tainted", True)
                cpg.annotate_node(
                    node_id, "taint_labels", sorted({lb.name for lb in labels})
                )

        # -- Roles and edge annotations from paths -------------------------------
        source_ids: set[str] = set()
        sink_ids: set[str] = set()
        sanitizer_ids: set[str] = set()

        for path in self.paths:
            source_ids.add(str(path.source.id))
            sink_ids.add(str(path.sink.id))
            for s in path.sanitizers:
                sanitizer_ids.add(str(s.id))

            # Annotate edges along the path with per-edge label granularity
            for i in range(len(path.intermediates) - 1):
                src = path.intermediates[i].id
                tgt = path.intermediates[i + 1].id
                cpg.annotate_edge(src, tgt, "tainted", True)
                edge_key = (str(src), str(tgt))
                # Prefer per-edge labels; fall back to path-level labels
                # for TaintResults constructed outside run_taint().
                per_edge = self._edge_labels.get(edge_key, path.labels)
                cpg.annotate_edge(
                    src, tgt, "taint_labels",
                    sorted({lb.name for lb in per_edge}),
                )

        # Set taint_role
        for node_id_str in source_ids:
            cpg.annotate_node(NodeId(node_id_str), "taint_role", "source")
        for node_id_str in sink_ids:
            cpg.annotate_node(NodeId(node_id_str), "taint_role", "sink")
        for node_id_str in sanitizer_ids:
            cpg.annotate_node(NodeId(node_id_str), "taint_role", "sanitizer")

        # Intermediate: tainted but not source/sink/sanitizer
        role_ids = source_ids | sink_ids | sanitizer_ids
        for node_id_str, labels in self._labels_at.items():
            if labels and node_id_str not in role_ids:
                cpg.annotate_node(NodeId(node_id_str), "taint_role", "intermediate")

        # Track sanitization status per sink
        for path in self.paths:
            sink_id = path.sink.id
            current = cpg.get_annotation(sink_id, "taint_sanitized")
            if current is None:
                cpg.annotate_node(sink_id, "taint_sanitized", path.is_sanitized)
            elif current and not path.is_sanitized:
                # Any unsanitized path trumps previously-seen sanitized ones
                cpg.annotate_node(sink_id, "taint_sanitized", False)


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
    # Track sanitizer nodes hit on the way to each (origin, node) pair.
    # Key: (origin_node_id_str, current_node_id_str)
    # Value: frozenset of sanitizer node ID strings seen on this origin's path.
    #
    # When two propagation paths from the same origin converge at a node, we
    # take the INTERSECTION of their sanitizer sets.  This tells us which
    # sanitizers are common to ALL routes (useful for the sanitizers field).
    sanitizers_on_path: dict[tuple[str, str], frozenset[str]] = {}

    # Track whether any unsanitized (bypass) path from an origin reaches a
    # node.  Used separately from sanitizers_on_path because the intersection
    # of sanitizer sets can be empty even when every individual path passes
    # through some sanitizer (different sanitizers on different branches).
    # True = a path with NO sanitizers reached this node from this origin.
    has_bypass: dict[tuple[str, str], bool] = {}

    # (node_id_str, labels, sanitizers_carried)
    # The third element is the frozenset of sanitizer IDs seen so far on the
    # path that produced this worklist entry.  Each label in `labels` shares
    # the same origin, so we track one sanitizer set per worklist entry.
    worklist: deque[tuple[str, frozenset[TaintLabel], frozenset[str]]] = deque()

    source_nodes: dict[str, CpgNode] = {}  # origin label name -> source CpgNode

    for node in cpg.nodes():
        label = policy.sources(node)
        if label is not None:
            nid = str(node.id)
            labels_at[nid] = frozenset({label})
            worklist.append((nid, frozenset({label}), frozenset()))
            source_nodes[nid] = node
            parent[nid] = set()
            sanitizers_on_path[(nid, nid)] = frozenset()
            has_bypass[(nid, nid)] = True  # Source starts unsanitized

    # Seed implicit parameter sources
    if policy.implicit_param_sources:
        for node in cpg.nodes(kind=NodeKind.PARAMETER):
            nid = str(node.id)
            if nid in labels_at:
                continue  # Already an explicit source, don't override
            label = TaintLabel(
                name=f"param:{node.name}",
                origin=node.id,
            )
            labels_at[nid] = frozenset({label})
            worklist.append((nid, frozenset({label}), frozenset()))
            source_nodes[nid] = node
            parent[nid] = set()
            sanitizers_on_path[(nid, nid)] = frozenset()
            has_bypass[(nid, nid)] = True  # Source starts unsanitized

    # Track which labels flow along each (source, target) edge.
    edge_labels: dict[tuple[str, str], frozenset[TaintLabel]] = {}

    # -- Propagate ------------------------------------------------------------
    sink_hits: list[tuple[str, frozenset[TaintLabel]]] = []

    while worklist:
        current_id, current_labels, current_sanitizers = worklist.popleft()
        current_node = cpg.node(NodeId(current_id))
        if current_node is None:
            continue

        is_sanitizer = policy.sanitizers(current_node)
        if is_sanitizer:
            current_sanitizers = current_sanitizers | frozenset({current_id})

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

        # Propagator-based: library calls without a resolved callee
        if current_node.kind == NodeKind.CALL and not calls_fwd.get(current_id):
            for propagator in policy.propagators:
                if propagator.match(current_node):
                    # Check if taint should flow to return value
                    should_propagate = False
                    if propagator.params_to_return is not None:
                        should_propagate = len(propagator.params_to_return) > 0
                    elif propagator.param_to_return:
                        should_propagate = True

                    if should_propagate:
                        for edge in cpg.edges(kind=EdgeKind.DEFINED_BY):
                            if str(edge.target) == current_id:
                                var_id_str = str(edge.source)
                                if var_id_str not in targets:
                                    targets.append(var_id_str)
                    break  # First matching propagator wins

        for target_id in targets:
            target_labels = labels_at.get(target_id, frozenset())
            new_labels = current_labels | target_labels

            if new_labels == target_labels:
                # Fixed point for labels -- but we may still need to update
                # sanitizer tracking if this path has a weaker sanitizer set.
                # Check per-origin sanitizer sets below; skip if nothing new.
                needs_update = False
                for label in current_labels:
                    origin_key = (str(label.origin), target_id)
                    existing = sanitizers_on_path.get(origin_key)
                    propagated = current_sanitizers
                    if existing is None or not propagated.issuperset(existing):
                        needs_update = True
                        break
                if not needs_update:
                    continue

            labels_at[target_id] = new_labels
            parent.setdefault(target_id, set()).add(current_id)

            # Track per-edge label flow
            edge_key = (current_id, target_id)
            existing_edge_labels = edge_labels.get(edge_key, frozenset())
            edge_labels[edge_key] = existing_edge_labels | current_labels

            # Update per-origin sanitizer and bypass tracking at the target.
            # Intersection semantics for the sanitizer set (which sanitizers
            # are common to ALL routes).  Bypass tracking is separate: if any
            # route arrives with an empty sanitizer set, a bypass exists.
            path_is_unsanitized = len(current_sanitizers) == 0
            for label in current_labels:
                origin_key = (str(label.origin), target_id)
                existing = sanitizers_on_path.get(origin_key)
                if existing is None:
                    sanitizers_on_path[origin_key] = current_sanitizers
                else:
                    sanitizers_on_path[origin_key] = existing & current_sanitizers
                # Track whether an unsanitized path exists
                if path_is_unsanitized:
                    has_bypass[origin_key] = True
                elif origin_key not in has_bypass:
                    has_bypass[origin_key] = False

            target_node = cpg.node(NodeId(target_id))
            if target_node is not None and policy.sinks(target_node):
                sink_hits.append((target_id, new_labels))

            worklist.append((target_id, new_labels, current_sanitizers))

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

            origin_key = (origin_str, sink_id_str)
            san_node_ids = sanitizers_on_path.get(origin_key, frozenset())
            sanitizer_cpg_nodes = [
                cpg.node(NodeId(s))
                for s in san_node_ids
                if cpg.node(NodeId(s)) is not None
            ]

            # is_sanitized is True when no unsanitized (bypass) path
            # exists from this origin to the sink.  This is tracked
            # separately from the sanitizer intersection because different
            # branches can use different sanitizers and still be safe.
            bypass_exists = has_bypass.get(origin_key, True)
            path = TaintPath(
                source=source_node,
                sink=sink_node,
                intermediates=intermediates,
                labels=frozenset({label}),
                is_sanitized=not bypass_exists,
                sanitizers=sanitizer_cpg_nodes,
            )
            paths.append(path)

    return TaintResult(paths=paths, _labels_at=labels_at, _edge_labels=edge_labels)


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
