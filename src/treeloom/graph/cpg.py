"""CodePropertyGraph: the central graph container and query facade."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from treeloom.graph.backend import GraphBackend, NetworkXBackend
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind
from treeloom.version import __version__

if TYPE_CHECKING:
    from treeloom.analysis.taint import TaintPolicy, TaintResult
    from treeloom.query.api import GraphQuery


class CodePropertyGraph:
    """The central Code Property Graph object.

    Wraps a GraphBackend and provides typed access to nodes, edges,
    annotations, traversal, and serialization.
    """

    def __init__(self, backend: GraphBackend | None = None) -> None:
        self._backend: GraphBackend = backend or NetworkXBackend()
        self._nodes: dict[str, CpgNode] = {}
        self._annotations: dict[str, dict[str, Any]] = {}
        self._edge_annotations: dict[tuple[str, str], dict[str, Any]] = {}
        self._file_nodes: dict[str, set[str]] = {}
        # Scope index: scope_id -> [child_node_ids] for O(1) children_of
        self._scope_children: dict[str, list[str]] = {}
        # Edge kind indexes: (kind_value, source_id) -> [target_ids] and reverse
        self._edge_fwd: dict[tuple[str, str], list[str]] = {}
        self._edge_rev: dict[tuple[str, str], list[str]] = {}

    # -- Node access ----------------------------------------------------------

    def add_node(self, node: CpgNode) -> None:
        """Add a node to the graph."""
        id_str = str(node.id)
        self._nodes[id_str] = node
        self._backend.add_node(
            id_str,
            kind=node.kind.value,
            name=node.name,
        )
        if node.location is not None:
            file_key = str(PurePosixPath(node.location.file))
            self._file_nodes.setdefault(file_key, set()).add(id_str)
        if node.scope is not None:
            self._scope_children.setdefault(str(node.scope), []).append(id_str)

    def remove_node(self, node_id: NodeId) -> None:
        """Remove a node and all its adjacent edges from the graph.

        Also cleans up annotations, the file provenance index, and
        the scope/edge lookup indexes.
        """
        id_str = str(node_id)
        node = self._nodes.pop(id_str, None)

        if node is not None:
            # Clean scope index: remove this node from its parent's children
            if node.scope is not None:
                scope_str = str(node.scope)
                children = self._scope_children.get(scope_str)
                if children is not None:
                    try:
                        children.remove(id_str)
                    except ValueError:
                        pass
            # Remove this node's own children list (orphans stay in _nodes)
            self._scope_children.pop(id_str, None)

            if node.location is not None:
                file_key = str(PurePosixPath(node.location.file))
                file_set = self._file_nodes.get(file_key)
                if file_set is not None:
                    file_set.discard(id_str)
                    if not file_set:
                        del self._file_nodes[file_key]

        # Clean edge indexes before the backend removes the edges.
        # Forward: remove all entries where this node is the source.
        fwd_keys = [k for k in self._edge_fwd if k[1] == id_str]
        for k in fwd_keys:
            # Also clean reverse entries that point back to this source
            kind_str = k[0]
            for tgt in self._edge_fwd[k]:
                rev_key = (kind_str, tgt)
                rev_list = self._edge_rev.get(rev_key)
                if rev_list is not None:
                    try:
                        rev_list.remove(id_str)
                    except ValueError:
                        pass
            del self._edge_fwd[k]
        # Reverse: remove all entries where this node is the target.
        rev_keys = [k for k in self._edge_rev if k[1] == id_str]
        for k in rev_keys:
            kind_str = k[0]
            for src in self._edge_rev[k]:
                fwd_key = (kind_str, src)
                fwd_list = self._edge_fwd.get(fwd_key)
                if fwd_list is not None:
                    try:
                        fwd_list.remove(id_str)
                    except ValueError:
                        pass
            del self._edge_rev[k]

        self._annotations.pop(id_str, None)

        stale_keys = [
            k for k in self._edge_annotations
            if k[0] == id_str or k[1] == id_str
        ]
        for k in stale_keys:
            del self._edge_annotations[k]

        if self._backend.has_node(id_str):
            self._backend.remove_node(id_str)

    def node(self, node_id: NodeId) -> CpgNode | None:
        """Look up a node by its ID."""
        return self._nodes.get(str(node_id))

    def nodes(
        self,
        kind: NodeKind | None = None,
        file: Path | None = None,
    ) -> Iterator[CpgNode]:
        """Iterate over nodes, optionally filtering by kind and/or file."""
        for cpg_node in self._nodes.values():
            if kind is not None and cpg_node.kind != kind:
                continue
            if file is not None:
                if cpg_node.location is None or cpg_node.location.file != file:
                    continue
            yield cpg_node

    def nodes_for_file(self, file: Path) -> list[NodeId]:
        """Return all node IDs originating from the given source file."""
        file_key = str(PurePosixPath(file))
        return [NodeId(nid) for nid in self._file_nodes.get(file_key, set())]

    # -- Edge access ----------------------------------------------------------

    def add_edge(self, edge: CpgEdge) -> None:
        """Add an edge to the graph."""
        src_str = str(edge.source)
        tgt_str = str(edge.target)
        kind_str = edge.kind.value
        self._backend.add_edge(src_str, tgt_str, key=kind_str, **edge.attrs)
        self._edge_fwd.setdefault((kind_str, src_str), []).append(tgt_str)
        self._edge_rev.setdefault((kind_str, tgt_str), []).append(src_str)

    def remove_edge(
        self, source: NodeId, target: NodeId, kind: EdgeKind | None = None
    ) -> None:
        """Remove an edge between two nodes."""
        src_str = str(source)
        tgt_str = str(target)
        self._edge_annotations.pop((src_str, tgt_str), None)
        key = kind.value if kind is not None else None
        self._backend.remove_edge(src_str, tgt_str, key=key)
        # Update edge indexes
        if key is not None:
            fwd_list = self._edge_fwd.get((key, src_str))
            if fwd_list is not None:
                try:
                    fwd_list.remove(tgt_str)
                except ValueError:
                    pass
            rev_list = self._edge_rev.get((key, tgt_str))
            if rev_list is not None:
                try:
                    rev_list.remove(src_str)
                except ValueError:
                    pass
        else:
            # No kind specified: remove all edge kinds between these two nodes.
            fwd_keys = [k for k in self._edge_fwd if k[1] == src_str]
            for k in fwd_keys:
                try:
                    self._edge_fwd[k].remove(tgt_str)
                except ValueError:
                    pass
            rev_keys = [k for k in self._edge_rev if k[1] == tgt_str]
            for k in rev_keys:
                try:
                    self._edge_rev[k].remove(src_str)
                except ValueError:
                    pass

    def edges(self, kind: EdgeKind | None = None) -> Iterator[CpgEdge]:
        """Iterate over edges, optionally filtering by kind."""
        for source_str, target_str, attrs in self._backend.all_edges():
            edge_kind_str = attrs.get("key")
            if edge_kind_str is None:
                continue
            try:
                edge_kind = EdgeKind(edge_kind_str)
            except ValueError:
                continue
            if kind is not None and edge_kind != kind:
                continue
            edge_attrs = {k: v for k, v in attrs.items() if k != "key"}
            yield CpgEdge(
                source=NodeId(source_str),
                target=NodeId(target_str),
                kind=edge_kind,
                attrs=edge_attrs,
            )

    # -- Traversal ------------------------------------------------------------

    def successors(
        self, node_id: NodeId, edge_kind: EdgeKind | None = None
    ) -> list[CpgNode]:
        """Return successor nodes, optionally filtered by edge kind."""
        if edge_kind is None:
            succ_ids = self._backend.successors(str(node_id))
            return [self._nodes[s] for s in succ_ids if s in self._nodes]

        key = (edge_kind.value, str(node_id))
        return [self._nodes[t] for t in self._edge_fwd.get(key, []) if t in self._nodes]

    def predecessors(
        self, node_id: NodeId, edge_kind: EdgeKind | None = None
    ) -> list[CpgNode]:
        """Return predecessor nodes, optionally filtered by edge kind."""
        if edge_kind is None:
            pred_ids = self._backend.predecessors(str(node_id))
            return [self._nodes[p] for p in pred_ids if p in self._nodes]

        key = (edge_kind.value, str(node_id))
        return [self._nodes[s] for s in self._edge_rev.get(key, []) if s in self._nodes]

    # -- Scope navigation -----------------------------------------------------

    def scope_of(self, node_id: NodeId) -> CpgNode | None:
        """Return the enclosing scope node (function/class/module)."""
        cpg_node = self._nodes.get(str(node_id))
        if cpg_node is None or cpg_node.scope is None:
            return None
        return self._nodes.get(str(cpg_node.scope))

    def children_of(self, node_id: NodeId) -> list[CpgNode]:
        """Return direct children (nodes whose scope is this node)."""
        id_str = str(node_id)
        return [
            self._nodes[cid]
            for cid in self._scope_children.get(id_str, [])
            if cid in self._nodes
        ]

    # -- Annotations ----------------------------------------------------------

    def annotate_node(self, node_id: NodeId, key: str, value: Any) -> None:
        """Attach a consumer annotation to a node (separate from attrs)."""
        id_str = str(node_id)
        if id_str not in self._annotations:
            self._annotations[id_str] = {}
        self._annotations[id_str][key] = value

    def annotate_edge(
        self, source: NodeId, target: NodeId, key: str, value: Any
    ) -> None:
        """Attach a consumer annotation to an edge."""
        edge_key = (str(source), str(target))
        if edge_key not in self._edge_annotations:
            self._edge_annotations[edge_key] = {}
        self._edge_annotations[edge_key][key] = value

    def get_annotation(self, node_id: NodeId, key: str) -> Any | None:
        """Retrieve a single annotation value from a node."""
        return self._annotations.get(str(node_id), {}).get(key)

    def get_edge_annotation(
        self, source: NodeId, target: NodeId, key: str
    ) -> Any | None:
        """Retrieve a single annotation value from an edge."""
        edge_key = (str(source), str(target))
        return self._edge_annotations.get(edge_key, {}).get(key)

    def annotations_for(self, node_id: NodeId) -> dict[str, Any]:
        """Return all annotations for a node."""
        return dict(self._annotations.get(str(node_id), {}))

    # -- Serialization --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the CPG to a dict (node-link format)."""
        nodes = []
        for cpg_node in self._nodes.values():
            node_data: dict[str, Any] = {
                "id": str(cpg_node.id),
                "kind": cpg_node.kind.value,
                "name": cpg_node.name,
                "location": _serialize_location(cpg_node.location),
                "end_location": _serialize_location(cpg_node.end_location),
                "scope": str(cpg_node.scope) if cpg_node.scope is not None else None,
                "attrs": cpg_node.attrs,
            }
            nodes.append(node_data)

        edges = []
        for edge in self.edges():
            edges.append({
                "source": str(edge.source),
                "target": str(edge.target),
                "kind": edge.kind.value,
                "attrs": edge.attrs,
            })

        result: dict[str, Any] = {
            "treeloom_version": __version__,
            "nodes": nodes,
            "edges": edges,
            "annotations": {k: dict(v) for k, v in self._annotations.items()},
            "edge_annotations": [
                {"source": k[0], "target": k[1], "annotations": dict(v)}
                for k, v in self._edge_annotations.items()
            ],
        }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodePropertyGraph:
        """Deserialize a CPG from a dict."""
        cpg = cls()

        for node_data in data["nodes"]:
            location = _deserialize_location(node_data["location"])
            end_location = _deserialize_location(node_data.get("end_location"))
            scope = NodeId(node_data["scope"]) if node_data["scope"] is not None else None
            cpg_node = CpgNode(
                id=NodeId(node_data["id"]),
                kind=NodeKind(node_data["kind"]),
                name=node_data["name"],
                location=location,
                end_location=end_location,
                scope=scope,
                attrs=dict(node_data.get("attrs", {})),
            )
            cpg.add_node(cpg_node)

        for edge_data in data["edges"]:
            edge = CpgEdge(
                source=NodeId(edge_data["source"]),
                target=NodeId(edge_data["target"]),
                kind=EdgeKind(edge_data["kind"]),
                attrs=dict(edge_data.get("attrs", {})),
            )
            cpg.add_edge(edge)

        for id_str, ann in data.get("annotations", {}).items():
            cpg._annotations[id_str] = dict(ann)

        for entry in data.get("edge_annotations", []):
            source_str = entry["source"]
            target_str = entry["target"]
            cpg._edge_annotations[(source_str, target_str)] = dict(entry["annotations"])

        return cpg

    # -- Query / analysis entry points ----------------------------------------

    def query(self) -> GraphQuery:
        """Return a query builder for this CPG."""
        from treeloom.query.api import GraphQuery

        return GraphQuery(self)

    def taint(self, policy: TaintPolicy) -> TaintResult:
        """Run taint analysis with the given policy."""
        from treeloom.analysis.taint import run_taint

        return run_taint(self, policy)

    # -- Properties -----------------------------------------------------------

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return self._backend.edge_count()

    @property
    def files(self) -> list[Path]:
        """Return all source files represented in the graph."""
        seen: set[Path] = set()
        result: list[Path] = []
        for cpg_node in self._nodes.values():
            if cpg_node.location is not None and cpg_node.location.file not in seen:
                seen.add(cpg_node.location.file)
                result.append(cpg_node.location.file)
        return sorted(result)


# -- Serialization helpers ----------------------------------------------------


def _serialize_location(loc: SourceLocation | None) -> dict[str, Any] | None:
    if loc is None:
        return None
    return {
        "file": str(PurePosixPath(loc.file)),
        "line": loc.line,
        "column": loc.column,
    }


def _deserialize_location(data: dict[str, Any] | None) -> SourceLocation | None:
    if data is None:
        return None
    return SourceLocation(
        file=Path(data["file"]),
        line=data["line"],
        column=data.get("column", 0),
    )
