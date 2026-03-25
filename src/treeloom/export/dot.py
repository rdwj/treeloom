"""Graphviz DOT export for the Code Property Graph."""

from __future__ import annotations

from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

# Node shape mapping per NodeKind.
_NODE_SHAPES: dict[NodeKind, str] = {
    NodeKind.MODULE: "folder",
    NodeKind.CLASS: "box3d",
    NodeKind.FUNCTION: "component",
    NodeKind.PARAMETER: "ellipse",
    NodeKind.VARIABLE: "ellipse",
    NodeKind.CALL: "diamond",
    NodeKind.LITERAL: "note",
    NodeKind.RETURN: "ellipse",
    NodeKind.IMPORT: "ellipse",
    NodeKind.BRANCH: "hexagon",
    NodeKind.LOOP: "hexagon",
    NodeKind.BLOCK: "rectangle",
}

# Edge visual attributes per EdgeKind: (style, color, penwidth).
_EDGE_STYLES: dict[EdgeKind, tuple[str, str, str]] = {
    EdgeKind.CONTAINS: ("solid", "gray", "1.0"),
    EdgeKind.HAS_PARAMETER: ("solid", "gray", "1.0"),
    EdgeKind.HAS_RETURN_TYPE: ("solid", "gray", "1.0"),
    EdgeKind.DATA_FLOWS_TO: ("bold", "blue", "2.0"),
    EdgeKind.DEFINED_BY: ("bold", "blue", "1.5"),
    EdgeKind.USED_BY: ("bold", "blue", "1.5"),
    EdgeKind.FLOWS_TO: ("solid", "black", "1.0"),
    EdgeKind.BRANCHES_TO: ("dashed", "red", "1.0"),
    EdgeKind.CALLS: ("dotted", "green", "1.5"),
    EdgeKind.RESOLVES_TO: ("dotted", "green", "1.0"),
    EdgeKind.IMPORTS: ("dashed", "gray", "1.0"),
}


def _escape_dot(text: str) -> str:
    """Escape a string for use as a DOT label."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def to_dot(
    cpg: CodePropertyGraph,
    edge_kinds: frozenset[EdgeKind] | None = None,
    node_kinds: frozenset[NodeKind] | None = None,
) -> str:
    """Export the CPG to Graphviz DOT format.

    Parameters
    ----------
    cpg:
        The graph to export.
    edge_kinds:
        If provided, only include edges of these kinds.
    node_kinds:
        If provided, only include nodes of these kinds.
    """
    lines: list[str] = [
        "digraph CPG {",
        '  rankdir=TB;',
        '  node [fontname="Helvetica", fontsize=10];',
        '  edge [fontname="Helvetica", fontsize=8];',
    ]

    # When edge_kinds is specified, only include nodes that appear in at least
    # one edge of the requested kinds.  Compute that set up-front so the node
    # loop below can filter accordingly.
    connected_node_ids: set[str] | None = None
    if edge_kinds is not None:
        connected_node_ids = set()
        for edge in cpg.edges():
            if edge.kind in edge_kinds:
                connected_node_ids.add(str(edge.source))
                connected_node_ids.add(str(edge.target))

    # Emit nodes.
    for node in cpg.nodes():
        if node_kinds is not None and node.kind not in node_kinds:
            continue
        id_str = str(node.id)
        if connected_node_ids is not None and id_str not in connected_node_ids:
            continue
        shape = _NODE_SHAPES.get(node.kind, "ellipse")
        label = _escape_dot(f"{node.kind.value}: {node.name}")
        lines.append(
            f'  "{_escape_dot(id_str)}" [label="{label}", shape={shape}];'
        )

    # Emit edges.
    for edge in cpg.edges():
        if edge_kinds is not None and edge.kind not in edge_kinds:
            continue
        style, color, penwidth = _EDGE_STYLES.get(
            edge.kind, ("solid", "black", "1.0")
        )
        src = _escape_dot(str(edge.source))
        tgt = _escape_dot(str(edge.target))
        label = _escape_dot(edge.kind.value)
        lines.append(
            f'  "{src}" -> "{tgt}" '
            f'[label="{label}", style={style}, color={color}, penwidth={penwidth}];'
        )

    lines.append("}")
    return "\n".join(lines) + "\n"
