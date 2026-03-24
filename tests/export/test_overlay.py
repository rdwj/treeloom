"""Tests for the overlay API data structures."""

from __future__ import annotations

from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeId, NodeKind
from treeloom.overlay.api import Overlay, OverlayStyle, VisualizationLayer


class TestOverlayStyle:
    def test_defaults_are_none(self):
        style = OverlayStyle()
        assert style.color is None
        assert style.shape is None
        assert style.size is None
        assert style.line_style is None
        assert style.width is None
        assert style.label is None
        assert style.opacity is None

    def test_explicit_values(self):
        style = OverlayStyle(
            color="red", shape="hexagon", size=40,
            line_style="dashed", width=2.5, label="tainted", opacity=0.8,
        )
        assert style.color == "red"
        assert style.size == 40
        assert style.opacity == 0.8


class TestOverlay:
    def test_empty_overlay(self):
        ov = Overlay(name="test")
        assert ov.name == "test"
        assert ov.description == ""
        assert ov.default_visible is True
        assert ov.node_styles == {}
        assert ov.edge_styles == {}

    def test_overlay_with_styles(self):
        nid = NodeId("fn1")
        src, tgt = NodeId("a"), NodeId("b")
        ov = Overlay(
            name="security",
            description="Security overlay",
            default_visible=False,
            node_styles={nid: OverlayStyle(color="red")},
            edge_styles={(src, tgt): OverlayStyle(width=3.0)},
        )
        assert ov.node_styles[nid].color == "red"
        assert ov.edge_styles[(src, tgt)].width == 3.0
        assert ov.default_visible is False


class TestVisualizationLayer:
    def test_defaults(self):
        layer = VisualizationLayer(name="All")
        assert layer.edge_kinds is None
        assert layer.node_kinds is None
        assert layer.default_visible is True
        assert isinstance(layer.style, OverlayStyle)

    def test_with_kinds(self):
        layer = VisualizationLayer(
            name="Data Flow",
            edge_kinds=frozenset({EdgeKind.DATA_FLOWS_TO, EdgeKind.DEFINED_BY}),
            node_kinds=frozenset({NodeKind.VARIABLE, NodeKind.PARAMETER}),
            default_visible=False,
        )
        assert EdgeKind.DATA_FLOWS_TO in layer.edge_kinds
        assert NodeKind.VARIABLE in layer.node_kinds
        assert layer.default_visible is False
