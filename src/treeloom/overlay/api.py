"""Overlay API for consumers to annotate and style graph visualizations."""

from __future__ import annotations

from dataclasses import dataclass, field

from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeId, NodeKind


@dataclass
class OverlayStyle:
    """Visual styling for a node or edge in the graph visualization.

    All fields are optional; ``None`` means "use the default style".
    """

    color: str | None = None
    shape: str | None = None
    size: int | None = None
    line_style: str | None = None  # "solid", "dashed", "dotted"
    width: float | None = None
    label: str | None = None
    opacity: float | None = None  # 0.0–1.0


@dataclass
class Overlay:
    """A named collection of per-node and per-edge visual overrides.

    Consumers create overlays to highlight analysis results (e.g. color
    taint sources red, sanitized paths green) without modifying the CPG
    itself.
    """

    name: str
    description: str = ""
    default_visible: bool = True
    node_styles: dict[NodeId, OverlayStyle] = field(default_factory=dict)
    edge_styles: dict[tuple[NodeId, NodeId], OverlayStyle] = field(
        default_factory=dict
    )


@dataclass
class VisualizationLayer:
    """A named subset of the graph filtered by edge/node kinds.

    Layers let users toggle entire graph views (structure, data flow,
    control flow, call graph) on and off in the HTML visualization.
    """

    name: str
    edge_kinds: frozenset[EdgeKind] | None = None
    node_kinds: frozenset[NodeKind] | None = None
    default_visible: bool = True
    style: OverlayStyle = field(default_factory=OverlayStyle)
