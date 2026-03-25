"""HTML export and interactive visualization for the Code Property Graph."""

from __future__ import annotations

import json
from typing import Any

from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind
from treeloom.overlay.api import Overlay, OverlayStyle, VisualizationLayer

# Default visualization layers when the caller does not provide any.
_DEFAULT_LAYERS: list[VisualizationLayer] = [
    VisualizationLayer(
        name="Structure",
        edge_kinds=frozenset({EdgeKind.CONTAINS, EdgeKind.HAS_PARAMETER}),
        node_kinds=frozenset({
            NodeKind.MODULE, NodeKind.CLASS, NodeKind.FUNCTION,
            NodeKind.PARAMETER, NodeKind.VARIABLE, NodeKind.CALL,
            NodeKind.LITERAL, NodeKind.RETURN, NodeKind.BRANCH,
            NodeKind.LOOP, NodeKind.BLOCK,
        }),
        default_visible=True,
    ),
    VisualizationLayer(
        name="Data Flow",
        edge_kinds=frozenset(
            {EdgeKind.DATA_FLOWS_TO, EdgeKind.DEFINED_BY, EdgeKind.USED_BY}
        ),
        default_visible=True,
    ),
    VisualizationLayer(
        name="Control Flow",
        edge_kinds=frozenset({EdgeKind.FLOWS_TO, EdgeKind.BRANCHES_TO}),
        default_visible=True,
    ),
    VisualizationLayer(
        name="Call Graph",
        edge_kinds=frozenset({EdgeKind.CALLS, EdgeKind.RESOLVES_TO}),
        default_visible=True,
    ),
    VisualizationLayer(
        name="Imports",
        node_kinds=frozenset({NodeKind.IMPORT}),
        edge_kinds=frozenset({EdgeKind.IMPORTS}),
        default_visible=False,
    ),
]

# Cytoscape node shapes per NodeKind.
_CY_SHAPES: dict[NodeKind, str] = {
    NodeKind.MODULE: "barrel",
    NodeKind.CLASS: "rectangle",
    NodeKind.FUNCTION: "round-rectangle",
    NodeKind.PARAMETER: "ellipse",
    NodeKind.VARIABLE: "ellipse",
    NodeKind.CALL: "diamond",
    NodeKind.LITERAL: "tag",
    NodeKind.RETURN: "ellipse",
    NodeKind.IMPORT: "ellipse",
    NodeKind.BRANCH: "hexagon",
    NodeKind.LOOP: "hexagon",
    NodeKind.BLOCK: "rectangle",
}

# Cytoscape edge colors per EdgeKind.
_CY_EDGE_COLORS: dict[EdgeKind, str] = {
    EdgeKind.CONTAINS: "#999",
    EdgeKind.HAS_PARAMETER: "#999",
    EdgeKind.HAS_RETURN_TYPE: "#999",
    EdgeKind.DATA_FLOWS_TO: "#2196F3",
    EdgeKind.DEFINED_BY: "#2196F3",
    EdgeKind.USED_BY: "#2196F3",
    EdgeKind.FLOWS_TO: "#333",
    EdgeKind.BRANCHES_TO: "#E53935",
    EdgeKind.CALLS: "#4CAF50",
    EdgeKind.RESOLVES_TO: "#4CAF50",
    EdgeKind.IMPORTS: "#999",
}

_CY_EDGE_STYLES: dict[EdgeKind, str] = {
    EdgeKind.CONTAINS: "solid",
    EdgeKind.HAS_PARAMETER: "solid",
    EdgeKind.HAS_RETURN_TYPE: "solid",
    EdgeKind.DATA_FLOWS_TO: "solid",
    EdgeKind.DEFINED_BY: "solid",
    EdgeKind.USED_BY: "solid",
    EdgeKind.FLOWS_TO: "solid",
    EdgeKind.BRANCHES_TO: "dashed",
    EdgeKind.CALLS: "dotted",
    EdgeKind.RESOLVES_TO: "dotted",
    EdgeKind.IMPORTS: "dashed",
}


def _build_elements(
    cpg: CodePropertyGraph,
    layers: list[VisualizationLayer],
    exclude_kinds: frozenset[NodeKind] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert the CPG into Cytoscape element dicts.

    Each node/edge is tagged with the layer names it belongs to so the JS
    sidebar can show and hide elements by layer membership.  Nodes whose kind
    is in *exclude_kinds* are omitted entirely, along with any edges whose
    source or target was excluded.
    """
    excluded: set[str] = set()

    cy_nodes: list[dict[str, Any]] = []
    for node in cpg.nodes():
        if exclude_kinds and node.kind in exclude_kinds:
            excluded.add(str(node.id))
            continue

        # Determine which layers claim this node.
        node_layers: list[str] = []
        for layer in layers:
            if layer.node_kinds is not None and node.kind in layer.node_kinds:
                node_layers.append(layer.name)
        # If no layer specifies node_kinds, the node is always present (no
        # layer-based hiding).

        data: dict[str, Any] = {
            "id": str(node.id),
            "label": node.name,
            "kind": node.kind.value,
            "shape": _CY_SHAPES.get(node.kind, "ellipse"),
        }
        if node_layers:
            data["layers"] = node_layers
        if node.location is not None:
            data["file"] = str(node.location.file)
            data["line"] = node.location.line
            data["column"] = node.location.column
        if node.scope is not None:
            data["scope"] = str(node.scope)
        if node.attrs:
            data["attrs"] = node.attrs
        annotations = cpg.annotations_for(node.id)
        if annotations:
            data["annotations"] = annotations
        cy_nodes.append({"data": data})

    cy_edges: list[dict[str, Any]] = []
    for edge in cpg.edges():
        src_str = str(edge.source)
        tgt_str = str(edge.target)
        if src_str in excluded or tgt_str in excluded:
            continue

        edata: dict[str, Any] = {
            "id": f"{edge.source}--{edge.kind.value}-->{edge.target}",
            "source": src_str,
            "target": tgt_str,
            "kind": edge.kind.value,
            "color": _CY_EDGE_COLORS.get(edge.kind, "#333"),
            "lineStyle": _CY_EDGE_STYLES.get(edge.kind, "solid"),
        }
        if edge.attrs:
            edata["attrs"] = edge.attrs
        cy_edges.append({"data": edata})

    return cy_nodes, cy_edges


def _build_layer_config(
    layers: list[VisualizationLayer],
) -> list[dict[str, Any]]:
    """Serialize layer definitions for the JS sidebar."""
    result: list[dict[str, Any]] = []
    for layer in layers:
        entry: dict[str, Any] = {
            "name": layer.name,
            "defaultVisible": layer.default_visible,
        }
        if layer.edge_kinds is not None:
            entry["edgeKinds"] = sorted(ek.value for ek in layer.edge_kinds)
        if layer.node_kinds is not None:
            entry["nodeKinds"] = sorted(nk.value for nk in layer.node_kinds)
        result.append(entry)
    return result


def _build_overlay_config(
    overlays: list[Overlay],
) -> list[dict[str, Any]]:
    """Serialize overlay definitions for the JS sidebar."""
    result: list[dict[str, Any]] = []
    for ov in overlays:
        node_styles: dict[str, dict[str, Any]] = {}
        for nid, style in ov.node_styles.items():
            node_styles[str(nid)] = _style_to_dict(style)
        edge_styles: dict[str, dict[str, Any]] = {}
        for (src, tgt), style in ov.edge_styles.items():
            edge_styles[f"{src}-->{tgt}"] = _style_to_dict(style)
        result.append({
            "name": ov.name,
            "description": ov.description,
            "defaultVisible": ov.default_visible,
            "nodeStyles": node_styles,
            "edgeStyles": edge_styles,
        })
    return result


def _style_to_dict(style: OverlayStyle) -> dict[str, Any]:
    """Convert an OverlayStyle to a plain dict, omitting None values."""
    d: dict[str, Any] = {}
    if style.color is not None:
        d["color"] = style.color
    if style.shape is not None:
        d["shape"] = style.shape
    if style.size is not None:
        d["size"] = style.size
    if style.line_style is not None:
        d["lineStyle"] = style.line_style
    if style.width is not None:
        d["width"] = style.width
    if style.label is not None:
        d["label"] = style.label
    if style.opacity is not None:
        d["opacity"] = style.opacity
    return d


def _compute_stats(cpg: CodePropertyGraph) -> dict[str, Any]:
    """Gather node/edge count statistics for the stats bar."""
    node_counts: dict[str, int] = {}
    for node in cpg.nodes():
        k = node.kind.value
        node_counts[k] = node_counts.get(k, 0) + 1

    edge_counts: dict[str, int] = {}
    for edge in cpg.edges():
        k = edge.kind.value
        edge_counts[k] = edge_counts.get(k, 0) + 1

    return {
        "totalNodes": cpg.node_count,
        "totalEdges": cpg.edge_count,
        "nodeCounts": node_counts,
        "edgeCounts": edge_counts,
    }


def generate_html(
    cpg: CodePropertyGraph,
    layers: list[VisualizationLayer] | None = None,
    overlays: list[Overlay] | None = None,
    title: str = "Code Property Graph",
    exclude_kinds: frozenset[NodeKind] | None = None,
) -> str:
    """Generate a self-contained HTML visualization of the CPG.

    The output loads Cytoscape.js and its Dagre layout plugin from CDN
    and requires no additional local files.

    Args:
        cpg: The Code Property Graph to visualize.
        layers: Visualization layers for the sidebar toggles.  Defaults to
            the built-in layer set, which includes an "Imports" layer that is
            off by default.
        overlays: Consumer-defined visual overlays (e.g. taint highlighting).
        title: Page title and sidebar heading.
        exclude_kinds: Node kinds to omit entirely from the output, along
            with any edges whose source or target is one of the excluded
            nodes.  Useful when import nodes dominate the graph.
    """
    effective_layers = layers if layers is not None else list(_DEFAULT_LAYERS)
    effective_overlays = overlays if overlays is not None else []

    cy_nodes, cy_edges = _build_elements(cpg, effective_layers, exclude_kinds)
    layer_config = _build_layer_config(effective_layers)
    overlay_config = _build_overlay_config(effective_overlays)
    stats = _compute_stats(cpg)

    # Embed data as JSON inside <script> tags.
    nodes_json = json.dumps(cy_nodes, indent=None)
    edges_json = json.dumps(cy_edges, indent=None)
    layers_json = json.dumps(layer_config, indent=None)
    overlays_json = json.dumps(overlay_config, indent=None)
    stats_json = json.dumps(stats, indent=None)
    title_escaped = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return _HTML_TEMPLATE.replace("{{TITLE}}", title_escaped).replace(
        "{{NODES_JSON}}", nodes_json
    ).replace(
        "{{EDGES_JSON}}", edges_json
    ).replace(
        "{{LAYERS_JSON}}", layers_json
    ).replace(
        "{{OVERLAYS_JSON}}", overlays_json
    ).replace(
        "{{STATS_JSON}}", stats_json
    )


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{TITLE}}</title>
<script src="https://unpkg.com/cytoscape/dist/cytoscape.min.js"></script>
<script src="https://unpkg.com/dagre/dist/dagre.min.js"></script>
<script src="https://unpkg.com/cytoscape-dagre/cytoscape-dagre.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, -apple-system, sans-serif; display: flex; height: 100vh; }

  /* Sidebar */
  #sidebar {
    width: 260px; min-width: 260px; background: #f5f5f5; border-right: 1px solid #ddd;
    overflow-y: auto; padding: 12px; font-size: 13px;
  }
  #sidebar h2 { font-size: 15px; margin-bottom: 8px; }
  #sidebar h3 { font-size: 13px; margin: 10px 0 4px; color: #555; }
  #sidebar label { display: block; padding: 2px 0; cursor: pointer; }
  #search { width: 100%; padding: 4px 6px; margin-bottom: 8px; font-size: 13px; }

  /* Stats bar */
  #stats {
    position: absolute; bottom: 0; left: 260px; right: 300px;
    background: rgba(245,245,245,0.95); border-top: 1px solid #ddd;
    padding: 6px 12px; font-size: 12px; color: #555;
  }

  /* Graph canvas */
  #cy { flex: 1; }

  /* Detail panel */
  #detail {
    width: 300px; min-width: 300px; background: #fafafa; border-left: 1px solid #ddd;
    overflow-y: auto; padding: 12px; font-size: 12px; white-space: pre-wrap;
  }
  #detail h3 { font-size: 14px; margin-bottom: 6px; }
  #detail table { width: 100%; border-collapse: collapse; font-size: 12px; }
  #detail td { padding: 2px 4px; vertical-align: top; border-bottom: 1px solid #eee; }
  #detail td:first-child { font-weight: 600; width: 90px; color: #555; }
</style>
</head>
<body>

<div id="sidebar">
  <h2>{{TITLE}}</h2>
  <input id="search" type="text" placeholder="Search nodes...">

  <h3>Layers</h3>
  <div id="layer-toggles"></div>

  <h3>Overlays</h3>
  <div id="overlay-toggles"></div>
</div>

<div id="cy"></div>

<div id="detail">
  <h3>Detail</h3>
  <p id="detail-placeholder" style="color:#999;">Click a node or edge to see details.</p>
  <div id="detail-content" style="display:none;"></div>
</div>

<div id="stats"></div>

<script>
(function() {
  // Embedded data
  var allNodes = {{NODES_JSON}};
  var allEdges = {{EDGES_JSON}};
  var layerDefs = {{LAYERS_JSON}};
  var overlayDefs = {{OVERLAYS_JSON}};
  var stats = {{STATS_JSON}};

  // Initialize Cytoscape
  var cy = cytoscape({
    container: document.getElementById('cy'),
    elements: { nodes: allNodes, edges: allEdges },
    style: [
      { selector: 'node', style: {
        'label': 'data(label)', 'shape': 'data(shape)',
        'font-size': 10, 'text-valign': 'center', 'text-halign': 'center',
        'background-color': '#6FB1FC', 'color': '#333',
        'width': 30, 'height': 30, 'text-wrap': 'ellipsis', 'text-max-width': 80
      }},
      { selector: 'edge', style: {
        'width': 1.5, 'line-color': 'data(color)', 'target-arrow-color': 'data(color)',
        'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
        'line-style': 'data(lineStyle)', 'font-size': 8, 'color': '#999'
      }},
      { selector: '.highlighted', style: { 'background-color': '#FF9800', 'color': '#000' }},
      { selector: '.dimmed', style: { 'opacity': 0.15 }}
    ],
    layout: { name: 'dagre', rankDir: 'TB', nodeSep: 40, edgeSep: 10, rankSep: 60 }
  });

  // -- Layer toggles --
  var layerStates = {};
  var layerContainer = document.getElementById('layer-toggles');
  layerDefs.forEach(function(layer) {
    layerStates[layer.name] = layer.defaultVisible;
    var lbl = document.createElement('label');
    var cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = layer.defaultVisible;
    cb.addEventListener('change', function() {
      layerStates[layer.name] = cb.checked;
      applyVisibility();
    });
    lbl.appendChild(cb);
    lbl.appendChild(document.createTextNode(' ' + layer.name));
    layerContainer.appendChild(lbl);
  });

  // -- Overlay toggles --
  var overlayStates = {};
  var overlayContainer = document.getElementById('overlay-toggles');
  overlayDefs.forEach(function(ov) {
    overlayStates[ov.name] = ov.defaultVisible;
    var lbl = document.createElement('label');
    var cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = ov.defaultVisible;
    cb.addEventListener('change', function() {
      overlayStates[ov.name] = cb.checked;
      applyOverlays();
    });
    lbl.appendChild(cb);
    lbl.appendChild(document.createTextNode(' ' + ov.name));
    overlayContainer.appendChild(lbl);
  });
  if (overlayDefs.length === 0) {
    overlayContainer.innerHTML = '<span style="color:#999;">None</span>';
  }

  // -- Visibility logic --
  function applyVisibility() {
    var anyLayerHasEdgeKinds = layerDefs.some(function(l) { return l.edgeKinds; });
    var anyLayerHasNodeKinds = layerDefs.some(function(l) { return l.nodeKinds; });

    // Edges: visible if at least one active layer claims this edge kind.
    cy.edges().forEach(function(edge) {
      var kind = edge.data('kind');
      var visible = false;
      layerDefs.forEach(function(layer) {
        if (layerStates[layer.name] && layer.edgeKinds && layer.edgeKinds.indexOf(kind) >= 0) {
          visible = true;
        }
      });
      if (!anyLayerHasEdgeKinds) visible = true;
      edge.style('display', visible ? 'element' : 'none');
    });

    // Nodes: if any layer specifies nodeKinds, hide nodes whose kind belongs
    // only to inactive layers.  Nodes not claimed by any layer remain visible.
    if (anyLayerHasNodeKinds) {
      cy.nodes().forEach(function(node) {
        var nodeLayers = node.data('layers');
        if (!nodeLayers || nodeLayers.length === 0) {
          // Not claimed by any layer — always show.
          node.style('display', 'element');
          return;
        }
        var visible = nodeLayers.some(function(ln) { return layerStates[ln]; });
        node.style('display', visible ? 'element' : 'none');
      });
    }
  }
  applyVisibility();

  // -- Overlay application --
  function applyOverlays() {
    // Reset to defaults first.
    cy.nodes().style({ 'background-color': '#6FB1FC', 'border-width': 0 });
    // Apply active overlays.
    overlayDefs.forEach(function(ov) {
      if (!overlayStates[ov.name]) return;
      Object.keys(ov.nodeStyles).forEach(function(nid) {
        var s = ov.nodeStyles[nid];
        var el = cy.getElementById(nid);
        if (el.length) {
          if (s.color) el.style('background-color', s.color);
          if (s.shape) el.style('shape', s.shape);
          if (s.size) { el.style('width', s.size); el.style('height', s.size); }
          if (s.opacity !== undefined && s.opacity !== null) el.style('opacity', s.opacity);
        }
      });
      Object.keys(ov.edgeStyles).forEach(function(eid) {
        var s = ov.edgeStyles[eid];
        var parts = eid.split('-->');
        if (parts.length === 2) {
          cy.edges().forEach(function(e) {
            if (e.data('source') === parts[0] && e.data('target') === parts[1]) {
              if (s.color) e.style('line-color', s.color);
              if (s.lineStyle) e.style('line-style', s.lineStyle);
              if (s.width) e.style('width', s.width);
            }
          });
        }
      });
    });
  }
  applyOverlays();

  // -- Search --
  document.getElementById('search').addEventListener('input', function(e) {
    var q = e.target.value.toLowerCase().trim();
    if (!q) {
      cy.elements().removeClass('dimmed').removeClass('highlighted');
      return;
    }
    cy.elements().addClass('dimmed').removeClass('highlighted');
    cy.nodes().forEach(function(n) {
      if (n.data('label') && n.data('label').toLowerCase().indexOf(q) >= 0) {
        n.removeClass('dimmed').addClass('highlighted');
        n.connectedEdges().removeClass('dimmed');
        n.neighborhood().nodes().removeClass('dimmed');
      }
    });
  });

  // -- Detail panel --
  cy.on('tap', 'node', function(evt) {
    var d = evt.target.data();
    showDetail('Node: ' + d.label, d);
  });
  cy.on('tap', 'edge', function(evt) {
    var d = evt.target.data();
    showDetail('Edge: ' + d.kind, d);
  });
  cy.on('tap', function(evt) {
    if (evt.target === cy) hideDetail();
  });

  function showDetail(title, data) {
    document.getElementById('detail-placeholder').style.display = 'none';
    var el = document.getElementById('detail-content');
    el.style.display = 'block';
    var rows = '<tr><td colspan="2"><strong>' + escHtml(title) + '</strong></td></tr>';
    Object.keys(data).forEach(function(k) {
      if (k === 'id' && data.source) return; // skip edge auto-id
      var v = typeof data[k] === 'object' ? JSON.stringify(data[k], null, 2) : String(data[k]);
      rows += '<tr><td>' + escHtml(k) + '</td><td>' + escHtml(v) + '</td></tr>';
    });
    el.innerHTML = '<table>' + rows + '</table>';
  }
  function hideDetail() {
    document.getElementById('detail-placeholder').style.display = 'block';
    document.getElementById('detail-content').style.display = 'none';
  }
  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // -- Stats bar --
  var sb = document.getElementById('stats');
  var parts = ['Nodes: ' + stats.totalNodes, 'Edges: ' + stats.totalEdges];
  Object.keys(stats.nodeCounts).forEach(function(k) {
    parts.push(k + ': ' + stats.nodeCounts[k]);
  });
  sb.textContent = parts.join('  |  ');
})();
</script>
</body>
</html>
"""
