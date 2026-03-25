"""Tests for HTML visualization export."""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.export.html import _DEFAULT_LAYERS, generate_html
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


@pytest.fixture()
def cpg_with_imports() -> CodePropertyGraph:
    """CPG containing import nodes and an edge connecting to one."""
    g = CodePropertyGraph()
    g.add_node(_make_node("mod", NodeKind.MODULE, "mymod"))
    g.add_node(_make_node("fn", NodeKind.FUNCTION, "foo", scope="mod"))
    g.add_node(_make_node("imp", NodeKind.IMPORT, "os"))
    g.add_edge(CpgEdge(source=NodeId("mod"), target=NodeId("fn"), kind=EdgeKind.CONTAINS))
    g.add_edge(CpgEdge(source=NodeId("mod"), target=NodeId("imp"), kind=EdgeKind.IMPORTS))
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


class TestDefaultLayers:
    def test_imports_layer_exists(self):
        names = [layer.name for layer in _DEFAULT_LAYERS]
        assert "Imports" in names

    def test_imports_layer_off_by_default(self):
        imports_layer = next(ly for ly in _DEFAULT_LAYERS if ly.name == "Imports")
        assert imports_layer.default_visible is False

    def test_imports_layer_covers_import_node_kind(self):
        imports_layer = next(ly for ly in _DEFAULT_LAYERS if ly.name == "Imports")
        assert imports_layer.node_kinds is not None
        assert NodeKind.IMPORT in imports_layer.node_kinds

    def test_structure_layer_excludes_import_kind(self):
        structure_layer = next(ly for ly in _DEFAULT_LAYERS if ly.name == "Structure")
        if structure_layer.node_kinds is not None:
            assert NodeKind.IMPORT not in structure_layer.node_kinds

    def test_imports_layer_in_html(self, cpg: CodePropertyGraph):
        html = generate_html(cpg)
        assert "Imports" in html

    def test_imports_layer_defaultvisible_false_in_json(self, cpg: CodePropertyGraph):
        html = generate_html(cpg)
        # The layer config JSON should show Imports as not default-visible.
        # A simple check: the string "Imports" should appear alongside false.
        import json as _json
        # Find the layerDefs assignment in the script.
        start = html.index("var layerDefs =") + len("var layerDefs =")
        end = html.index(";", start)
        layer_data = _json.loads(html[start:end].strip())
        imports_entry = next(ly for ly in layer_data if ly["name"] == "Imports")
        assert imports_entry["defaultVisible"] is False


class TestExcludeKinds:
    def test_excluded_nodes_absent_from_html(
        self, cpg_with_imports: CodePropertyGraph
    ):
        html = generate_html(
            cpg_with_imports,
            exclude_kinds=frozenset({NodeKind.IMPORT}),
        )
        # The import node name "os" could appear in node data — check that
        # the node id "imp" (used in the fixture) is not present as a node element.
        assert '"imp"' not in html

    def test_edges_to_excluded_nodes_removed(
        self, cpg_with_imports: CodePropertyGraph
    ):
        html = generate_html(
            cpg_with_imports,
            exclude_kinds=frozenset({NodeKind.IMPORT}),
        )
        # The IMPORTS edge from mod -> imp should be gone.
        assert '"imp"' not in html

    def test_non_excluded_nodes_still_present(
        self, cpg_with_imports: CodePropertyGraph
    ):
        html = generate_html(
            cpg_with_imports,
            exclude_kinds=frozenset({NodeKind.IMPORT}),
        )
        assert '"mymod"' in html
        assert '"foo"' in html

    def test_no_exclude_kinds_keeps_imports(
        self, cpg_with_imports: CodePropertyGraph
    ):
        html = generate_html(cpg_with_imports)
        assert '"imp"' in html

    def test_exclude_multiple_kinds(self, cpg: CodePropertyGraph):
        # Exclude both variables and functions — only the module should remain.
        html = generate_html(
            cpg,
            exclude_kinds=frozenset({NodeKind.VARIABLE, NodeKind.FUNCTION}),
        )
        assert '"mymod"' in html
        assert '"foo"' not in html
        assert '"x"' not in html
