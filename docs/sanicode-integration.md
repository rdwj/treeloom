# Integrating treeloom into sanicode

This guide covers how to replace sanicode's existing `KnowledgeGraph` with treeloom's Code Property Graph. It assumes you're familiar with sanicode's architecture and want to wire in treeloom as the graph backend.

## Status

treeloom v0.1.0 is implemented with all 8 language visitors (Python, JavaScript, TypeScript, Go, Java, C, C++, Rust), the taint analysis engine, pattern matching, and all export formats. It is ready for integration.

## Adding the Dependency

Add treeloom as a dependency in sanicode's `pyproject.toml`:

```toml
[project]
dependencies = [
    "treeloom[languages] @ git+https://github.com/rdwj/treeloom.git",
    # ... other dependencies
]
```

Or for local development, use a path dependency:

```toml
dependencies = [
    "treeloom[languages] @ file:///Users/you/Developer/treeloom",
]
```

Then install:

```bash
pip install -e ".[dev]"
```

## Migration from KnowledgeGraph

The existing `sanicode/graph/builder.py` uses a plain `nx.DiGraph` with string node IDs and ad-hoc attributes baked into node data. treeloom replaces this with a typed, structured model where the graph is built automatically from source code, and consumer metadata (security roles, CWE IDs) lives in a separate annotation layer.

### Before (KnowledgeGraph)

```python
import networkx as nx

g = nx.DiGraph()
g.add_node("func:app.py:process_input:10", type="function", name="process_input",
           role="entry_point", cwe_ids=[89, 79])
g.add_node("call:app.py:cursor.execute:25", type="call", name="cursor.execute",
           role="sink", cwe_ids=[89])
g.add_edge("func:app.py:process_input:10", "call:app.py:cursor.execute:25",
           edge_type="data_flow")
```

### After (treeloom)

```python
from pathlib import Path
from treeloom import CPGBuilder, NodeKind

# treeloom builds the structural graph automatically
cpg = CPGBuilder().add_directory(Path("myapp/")).build()

# Security metadata goes in annotations, not in the graph structure
for node in cpg.nodes(kind=NodeKind.FUNCTION):
    if node.name == "process_input":
        cpg.annotate_node(node.id, "role", "entry_point")
        cpg.annotate_node(node.id, "cwe_ids", [89, 79])

for node in cpg.nodes(kind=NodeKind.CALL):
    if node.name == "cursor.execute":
        cpg.annotate_node(node.id, "role", "sink")
        cpg.annotate_node(node.id, "cwe_ids", [89])
```

The key difference: treeloom handles parsing, AST construction, data flow edges, and call resolution. Sanicode only needs to annotate the resulting nodes with security semantics.

## The Integration Contract

The full integration follows six steps. Each is shown with working code.

### Step 1: Build the CPG

```python
from pathlib import Path
from treeloom import CPGBuilder

cpg = CPGBuilder().add_directory(Path("target_app/src/")).build()

print(f"Built CPG: {cpg.node_count} nodes, {cpg.edge_count} edges")
print(f"Files analyzed: {len(cpg.files)}")
```

You can also add individual files or raw source bytes:

```python
builder = CPGBuilder()
builder.add_file(Path("main.py"))
builder.add_source(b"def foo(): pass", "snippet.py", language="python")
cpg = builder.build()
```

### Step 2: Annotate Nodes with Security Roles

Walk the CPG and apply sanicode's security classification. This is where your existing role-assignment logic goes -- the only change is the storage mechanism.

```python
from treeloom import NodeKind

# Annotate entry points (e.g., Flask/FastAPI route handlers)
for node in cpg.nodes(kind=NodeKind.FUNCTION):
    if _is_route_handler(node):
        cpg.annotate_node(node.id, "role", "entry_point")

# Annotate sinks (e.g., SQL execution, command execution)
SINK_FUNCTIONS = {"cursor.execute", "os.system", "subprocess.run", "eval", "exec"}
for node in cpg.nodes(kind=NodeKind.CALL):
    if node.name in SINK_FUNCTIONS:
        cpg.annotate_node(node.id, "role", "sink")
        cpg.annotate_node(node.id, "cwe_id", _cwe_for_sink(node.name))

# Annotate sanitizers
SANITIZER_FUNCTIONS = {"escape", "sanitize", "parameterize", "html.escape"}
for node in cpg.nodes(kind=NodeKind.CALL):
    if node.name in SANITIZER_FUNCTIONS:
        cpg.annotate_node(node.id, "role", "sanitizer")

# Domain classification
for node in cpg.nodes(kind=NodeKind.MODULE):
    if "payment" in node.name or "billing" in node.name:
        cpg.annotate_node(node.id, "domain", "financial")
```

### Step 3: Create a TaintPolicy

The policy connects your annotations to the taint engine. The engine itself is generic -- it just follows data flow edges and propagates labels.

```python
from treeloom import TaintPolicy, TaintLabel

policy = TaintPolicy(
    sources=lambda node: (
        TaintLabel("user_input", node.id)
        if cpg.get_annotation(node.id, "role") == "entry_point"
        else None
    ),
    sinks=lambda node: cpg.get_annotation(node.id, "role") == "sink",
    sanitizers=lambda node: cpg.get_annotation(node.id, "role") == "sanitizer",
)
```

You can also define custom propagators for functions that pass taint through in non-obvious ways:

```python
from treeloom import TaintPropagator, NodeKind

policy = TaintPolicy(
    sources=lambda node: (
        TaintLabel("user_input", node.id)
        if cpg.get_annotation(node.id, "role") == "entry_point"
        else None
    ),
    sinks=lambda node: cpg.get_annotation(node.id, "role") == "sink",
    sanitizers=lambda node: cpg.get_annotation(node.id, "role") == "sanitizer",
    propagators=[
        TaintPropagator(
            match=lambda node: node.kind == NodeKind.CALL and node.name == "json.loads",
            param_to_return=True,
        ),
    ],
)
```

### Step 4: Run Taint Analysis

```python
result = cpg.taint(policy)

print(f"Found {len(result.paths)} taint paths")
print(f"  Unsanitized: {len(result.unsanitized_paths())}")
print(f"  Sanitized:   {len(result.sanitized_paths())}")
```

### Step 5: Read Results for Findings

```python
for path in result.unsanitized_paths():
    source = path.source
    sink = path.sink

    # Map to CWE using your annotations
    cwe_id = cpg.get_annotation(sink.id, "cwe_id")

    print(f"Finding: {source.name} -> {sink.name}")
    print(f"  CWE: {cwe_id}")
    print(f"  Source: {source.location}")
    print(f"  Sink:   {sink.location}")
    print(f"  Labels: {[l.name for l in path.labels]}")
    print(f"  Path length: {len(path.intermediates)} nodes")

    # Full path trace
    for node in path.intermediates:
        print(f"    {node.kind.value}: {node.name} @ {node.location}")
```

You can also query results by specific source or sink:

```python
# All paths ending at a specific sink
sink_node = next(cpg.nodes(kind=NodeKind.CALL))
paths_to_sink = result.paths_to_sink(sink_node.id)

# What taint labels reached a given node?
labels = result.labels_at(sink_node.id)
```

### Step 6: Create Overlays for Visualization

Overlays let you color nodes in the HTML visualization based on security analysis results, without modifying the CPG itself.

```python
from treeloom import Overlay, OverlayStyle, generate_html

overlay = Overlay(
    name="Security Analysis",
    description="Taint analysis results",
)

# Color unsanitized sinks red
for path in result.unsanitized_paths():
    overlay.node_styles[path.sink.id] = OverlayStyle(
        color="#E53935", label="UNSANITIZED SINK", size=40
    )
    overlay.node_styles[path.source.id] = OverlayStyle(
        color="#FF9800", label="TAINT SOURCE", size=40
    )
    # Color the path edges
    for i in range(len(path.intermediates) - 1):
        edge_key = (path.intermediates[i].id, path.intermediates[i + 1].id)
        overlay.edge_styles[edge_key] = OverlayStyle(
            color="#E53935", width=3.0
        )

# Color sanitized sinks green
for path in result.sanitized_paths():
    overlay.node_styles[path.sink.id] = OverlayStyle(
        color="#4CAF50", label="SANITIZED", size=35
    )
    for sanitizer in path.sanitizers:
        overlay.node_styles[sanitizer.id] = OverlayStyle(
            color="#2196F3", label="SANITIZER", size=35
        )

html = generate_html(cpg, overlays=[overlay], title="Security Analysis Report")
with open("security-report.html", "w") as f:
    f.write(html)
```

## Data Model Mapping

How sanicode's existing concepts map to treeloom annotations:

| sanicode concept | treeloom annotation                              |
|------------------|--------------------------------------------------|
| Entry point      | `annotate_node(node_id, "role", "entry_point")`  |
| Sink             | `annotate_node(node_id, "role", "sink")`         |
| Sanitizer        | `annotate_node(node_id, "role", "sanitizer")`    |
| Auth guard       | `annotate_node(node_id, "role", "auth_guard")`   |
| CWE ID           | `annotate_node(node_id, "cwe_id", 89)`           |
| Domain           | `annotate_node(node_id, "domain", "financial")`  |

Annotations are stored in a separate dict on `CodePropertyGraph`, not in `CpgNode.attrs`. This is a deliberate design decision: `attrs` holds structural/language metadata set by the tree-sitter visitors, while annotations hold consumer-defined metadata. This separation prevents security classification from corrupting the structural graph and ensures clean serialization round-trips.

To read annotations back:

```python
role = cpg.get_annotation(node.id, "role")          # single value
all_anns = cpg.annotations_for(node.id)              # full dict
```

## Caching with JSON Serialization

treeloom CPGs serialize to JSON with full round-trip fidelity, including annotations. This lets sanicode cache built graphs between runs.

```python
from treeloom import to_json, from_json

# After building and annotating
json_str = to_json(cpg)
with open("cache/project-cpg.json", "w") as f:
    f.write(json_str)

# On subsequent runs, load from cache
with open("cache/project-cpg.json") as f:
    cpg = from_json(f.read())

# Annotations survive the round-trip
role = cpg.get_annotation(some_node_id, "role")  # still "entry_point"
```

The serialization contract: `from_json(to_json(cpg))` always produces an equivalent graph. Node IDs, edge kinds, attributes, and all annotations are preserved. The only thing not serialized is the `_tree_node` field on `CpgNode` (the raw tree-sitter node reference), which is already cleared after `build()` completes.

## Key Types Reference

These are the types sanicode will interact with most. Import them all from the top-level `treeloom` package.

**Building:**

- `CPGBuilder` -- fluent builder with `add_file()`, `add_directory()`, `add_source()`, and `build()`
- `CodePropertyGraph` -- the built graph; provides `node()`, `nodes()`, `edges()`, `annotate_node()`, `get_annotation()`, `taint()`, `query()`, `to_dict()`, `from_dict()`

**Data model:**

- `NodeId` -- opaque, hashable node identifier
- `NodeKind` -- enum: `MODULE`, `CLASS`, `FUNCTION`, `PARAMETER`, `VARIABLE`, `CALL`, `LITERAL`, `RETURN`, `IMPORT`, `BRANCH`, `LOOP`, `BLOCK`
- `EdgeKind` -- enum: `CONTAINS`, `HAS_PARAMETER`, `DATA_FLOWS_TO`, `DEFINED_BY`, `USED_BY`, `FLOWS_TO`, `BRANCHES_TO`, `CALLS`, `RESOLVES_TO`, `IMPORTS`
- `CpgNode` -- node data: `id`, `kind`, `name`, `location`, `scope`, `attrs`
- `CpgEdge` -- edge data: `source`, `target`, `kind`, `attrs`
- `SourceLocation` -- file path + line (1-based) + column (0-based)

**Taint analysis:**

- `TaintPolicy` -- callbacks for sources, sinks, sanitizers, and propagators
- `TaintLabel` -- a label with a name, origin node, and optional attrs
- `TaintResult` -- list of `TaintPath` objects with filtering methods
- `TaintPath` -- source node, sink node, intermediate path, labels, sanitizer info

**Visualization:**

- `Overlay` -- per-node and per-edge visual styling
- `OverlayStyle` -- color, shape, size, line style, width, label, opacity
- `VisualizationLayer` -- toggleable graph layer filtered by edge/node kinds
- `generate_html(cpg, layers, overlays, title)` -- produces self-contained HTML
- `to_dot(cpg, edge_kinds, node_kinds)` -- Graphviz DOT output
- `to_json(cpg)` / `from_json(json_str)` -- JSON serialization
