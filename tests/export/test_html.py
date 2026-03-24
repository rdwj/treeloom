"""Tests for HTML visualization export."""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.export.html import generate_html
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind
from treeloom.overlay.api import Overlay, OverlayStyle, VisualizationLayer


def _make_node(
    id_str: str,
    kind: NodeKind = NodeKind.VARIABLE,
    name: str = "x",
    file: str = "test.py",
    line: int = 1,
    scope: str | None = None,
) -> CpgNode:
    return CpgNode(
        id=NodeId(id_str),
        kind=kind,
        name=name,
        location=SourceLocation(file=Path(file), line=line),
        scope=NodeId(scope) if scope else None,
    )


@pytest.fixture()
def cpg() -> CodePropertyGraph:
    g = CodePropertyGraph()
    g.add_node(_make_node("mod", NodeKind.MODULE, "mymod"))
    g.add_node(_make_node("fn", NodeKind.FUNCTION, "foo", scope="mod"))
    g.add_node(_make_node("var", NodeKind.VARIABLE, "x", scope="fn"))
    g.add_edge(CpgEdge(source=NodeId("mod"), target=NodeId("fn"), kind=EdgeKind.CONTAINS))
    g.add_edge(CpgEdge(source=NodeId("fn"), target=NodeId("var"), kind=EdgeKind.DATA_FLOWS_TO))
    g.annotate_node(NodeId("fn"), "role", "entry_point")
    return g


class TestHtmlOutput:
    def test_valid_html_structure(self, cpg: CodePropertyGraph):
        html = generate_html(cpg)
        assert "<html" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "<body>" in html

    def test_contains_cytoscape_script(self, cpg: CodePropertyGraph):
        html = generate_html(cpg)
        assert "cytoscape.min.js" in html
        assert "cytoscape-dagre" in html
        assert "dagre.min.js" in html

    def test_contains_node_data(self, cpg: CodePropertyGraph):
        html = generate_html(cpg)
        assert '"mymod"' in html
        assert '"foo"' in html

    def test_default_layers_present(self, cpg: CodePropertyGraph):
        html = generate_html(cpg)
        assert "Structure" in html
        assert "Data Flow" in html
        assert "Control Flow" in html
        assert "Call Graph" in html

    def test_custom_title(self, cpg: CodePropertyGraph):
        html = generate_html(cpg, title="My Custom Graph")
        assert "My Custom Graph" in html

    def test_default_title(self, cpg: CodePropertyGraph):
        html = generate_html(cpg)
        assert "Code Property Graph" in html

    def test_custom_layers(self, cpg: CodePropertyGraph):
        layers = [
            VisualizationLayer(name="Custom Layer", edge_kinds=frozenset({EdgeKind.CONTAINS})),
        ]
        html = generate_html(cpg, layers=layers)
        assert "Custom Layer" in html
        # Default layers should not appear when custom layers are provided.
        assert "Call Graph" not in html

    def test_overlay_included(self, cpg: CodePropertyGraph):
        ov = Overlay(
            name="Security",
            description="Security highlights",
            node_styles={NodeId("fn"): OverlayStyle(color="#ff0000")},
        )
        html = generate_html(cpg, overlays=[ov])
        assert "Security" in html
        assert "#ff0000" in html

    def test_stats_present(self, cpg: CodePropertyGraph):
        html = generate_html(cpg)
        # Stats should mention node/edge totals.
        assert "totalNodes" in html
        assert "totalEdges" in html

    def test_search_input_present(self, cpg: CodePropertyGraph):
        html = generate_html(cpg)
        assert 'id="search"' in html

    def test_empty_cpg(self):
        cpg = CodePropertyGraph()
        html = generate_html(cpg)
        assert "<html" in html
        assert "</html>" in html

    def test_title_escapes_html(self):
        cpg = CodePropertyGraph()
        html = generate_html(cpg, title="A <b>bold</b> & fun title")
        assert "A &lt;b&gt;bold&lt;/b&gt; &amp; fun title" in html

    def test_annotations_in_node_data(self, cpg: CodePropertyGraph):
        html = generate_html(cpg)
        assert "entry_point" in html

    def test_no_overlays_shows_none(self, cpg: CodePropertyGraph):
        html = generate_html(cpg)
        assert "None" in html  # The sidebar shows "None" when no overlays
