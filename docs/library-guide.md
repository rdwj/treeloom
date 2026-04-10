# treeloom Library Guide

This guide covers the treeloom API in depth. If you're integrating treeloom into sanicode specifically, see [sanicode-integration.md](sanicode-integration.md) instead.

All types shown here import from the top-level `treeloom` package.

---

## 1. Building a CPG

`CPGBuilder` is a fluent builder. You add sources, call `build()`, and get back a `CodePropertyGraph`.

```python
from pathlib import Path
from treeloom import CPGBuilder

cpg = CPGBuilder().add_directory(Path("myproject/src/")).build()
print(f"{cpg.node_count} nodes, {cpg.edge_count} edges across {len(cpg.files)} files")
```

### Adding sources

Three methods are available and can be chained:

```python
from pathlib import Path
from treeloom import CPGBuilder

builder = (
    CPGBuilder()
    .add_file(Path("app/main.py"))
    .add_directory(Path("app/lib/"))
    .add_source(b"def helper(x): return x * 2", "generated.py", language="python")
)
cpg = builder.build()
```

`add_directory` recurses into subdirectories. Files with no registered language visitor are silently skipped. Parse errors in individual files produce a warning and are skipped; the build continues.

### Excluding paths from add_directory

The `exclude` parameter accepts gitignore-style glob patterns. Some paths are excluded by default (`__pycache__`, `node_modules`, `.git`, `venv`, `.venv`):

```python
cpg = (
    CPGBuilder()
    .add_directory(
        Path("myproject/"),
        exclude=["**/migrations", "**/tests", "**/*.min.js"],
    )
    .build()
)
```

### Builder options

```python
from treeloom import CPGBuilder, BuildProgressCallback
from treeloom.lang.registry import LanguageRegistry

def on_progress(phase: str, detail: str) -> None:
    print(f"[{phase}] {detail}")

cpg = CPGBuilder(
    registry=LanguageRegistry.default(),   # custom registry, or None for defaults
    progress=on_progress,                  # called between each build phase
    timeout=120.0,                         # raise BuildTimeoutError after N seconds
    relative_root=Path("myproject/"),      # store paths relative to this directory
).add_directory(Path("myproject/src/")).build()
```

The `progress` callback fires between the four build phases: `"Parse"`, `"CFG"`, `"Call resolution"`, and `"Inter-procedural DFG"`. Use it to drive a progress bar or log build time per phase.

The `relative_root` option makes serialized graphs portable. Without it, node IDs and `SourceLocation.file` values contain absolute paths, which break when the graph is loaded on another machine or in CI.

```python
# Portable serialization
cpg = CPGBuilder(relative_root=Path.cwd()).add_directory(Path("src/")).build()
json_str = to_json(cpg)  # paths stored as "src/app.py", not "/home/user/project/src/app.py"
```

### Handling BuildTimeoutError

```python
from treeloom import CPGBuilder, BuildTimeoutError

try:
    cpg = CPGBuilder(timeout=30.0).add_directory(Path("large_project/")).build()
except BuildTimeoutError as e:
    print(f"Build timed out: {e}")
    # partial CPG not available — build() is atomic
```

### Custom language registry

Use a custom registry to restrict which languages are parsed, or to add your own visitor:

```python
from treeloom.lang.registry import LanguageRegistry
from treeloom.lang.builtin.python import PythonVisitor

registry = LanguageRegistry()
registry.register(PythonVisitor())
# Only .py files will be parsed; all others are skipped

cpg = CPGBuilder(registry=registry).add_directory(Path("src/")).build()
```

---

## 2. Navigating the Graph

### Node kinds

`NodeKind` is a string enum. All values are lowercase:

| Enum value          | Represents                                                 |
|---------------------|------------------------------------------------------------|
| `NodeKind.MODULE`   | A source file (one per file)                               |
| `NodeKind.CLASS`    | Class, struct, or interface definition                     |
| `NodeKind.FUNCTION` | Function or method definition                              |
| `NodeKind.PARAMETER`| Function parameter                                         |
| `NodeKind.VARIABLE` | Local variable, global, or field                           |
| `NodeKind.CALL`     | Function call site                                         |
| `NodeKind.LITERAL`  | String, number, boolean, or None literal                   |
| `NodeKind.RETURN`   | Return statement                                           |
| `NodeKind.IMPORT`   | Import statement                                           |
| `NodeKind.BRANCH`   | if/elif/switch/match condition                             |
| `NodeKind.LOOP`     | for/while/do-while loop header                             |
| `NodeKind.BLOCK`    | Basic block (group of sequential statements)               |

### Edge kinds

| Enum value                | Layer         | Meaning                                            |
|---------------------------|---------------|----------------------------------------------------|
| `EdgeKind.CONTAINS`       | AST           | Parent contains child                              |
| `EdgeKind.HAS_PARAMETER`  | AST           | Function → parameter                               |
| `EdgeKind.HAS_RETURN_TYPE`| AST           | Function → return type annotation                  |
| `EdgeKind.FLOWS_TO`       | Control flow  | Sequential statement flow                          |
| `EdgeKind.BRANCHES_TO`    | Control flow  | Conditional or loop branch                         |
| `EdgeKind.DATA_FLOWS_TO`  | Data flow     | Data flows from source to target                   |
| `EdgeKind.DEFINED_BY`     | Data flow     | Variable ← its definition                          |
| `EdgeKind.USED_BY`        | Data flow     | Variable → its usage site                          |
| `EdgeKind.CALLS`          | Call graph    | Call site → function definition                    |
| `EdgeKind.RESOLVES_TO`    | Call graph    | Dynamic dispatch resolution                        |
| `EdgeKind.IMPORTS`        | Module        | Module → imported module                           |

### Iterating nodes and edges

`cpg.nodes()` returns an iterator. Filter by kind, file, or both:

```python
from treeloom import NodeKind, EdgeKind
from pathlib import Path

# All functions in the graph
for fn in cpg.nodes(kind=NodeKind.FUNCTION):
    print(fn.name, fn.location)

# All call sites in one file
auth_py = Path("src/auth.py")
for call in cpg.nodes(kind=NodeKind.CALL, file=auth_py):
    print(f"  {call.name} at line {call.location.line}")

# All data flow edges
for edge in cpg.edges(kind=EdgeKind.DATA_FLOWS_TO):
    src = cpg.node(edge.source)
    tgt = cpg.node(edge.target)
    print(f"{src.name} -> {tgt.name}")
```

`cpg.node(node_id)` does a direct lookup by `NodeId` and returns `CpgNode | None`.

### Node attributes

`CpgNode.attrs` holds structural metadata set by the language visitor. Common keys by kind:

```python
fn = next(cpg.nodes(kind=NodeKind.FUNCTION))
print(fn.attrs.get("is_async"))        # bool
print(fn.attrs.get("is_method"))       # bool
print(fn.attrs.get("decorators"))      # list[str]

param = next(cpg.nodes(kind=NodeKind.PARAMETER))
print(param.attrs.get("type_annotation"))  # "str | None" or None
print(param.attrs.get("position"))         # 0-based int
print(param.attrs.get("default_value"))    # str representation, or None

call = next(cpg.nodes(kind=NodeKind.CALL))
print(call.attrs.get("args_count"))    # int
print(call.attrs.get("receiver"))      # "self", "obj", or None

lit = next(cpg.nodes(kind=NodeKind.LITERAL))
print(lit.attrs.get("literal_type"))   # "str", "int", "float", "bool", "none"
print(lit.attrs.get("raw_value"))      # the literal text from source
```

`attrs` is read-only from the consumer's perspective — do not write to it. Consumer metadata belongs in annotations (see section 3).

### Graph traversal

```python
from treeloom import EdgeKind

fn_node = next(cpg.nodes(kind=NodeKind.FUNCTION))

# Direct successors along CONTAINS edges (the function's children)
children = cpg.successors(fn_node.id, edge_kind=EdgeKind.CONTAINS)

# What calls this function? Walk CALLS edges backward.
callers = cpg.predecessors(fn_node.id, edge_kind=EdgeKind.CALLS)

# No edge_kind filter = all neighbors
all_successors = cpg.successors(fn_node.id)
```

### Scope navigation

Every node except MODULE has a `scope` field pointing to its enclosing function, class, or module:

```python
call = next(cpg.nodes(kind=NodeKind.CALL))
enclosing_fn = cpg.scope_of(call.id)     # CpgNode of enclosing FUNCTION, or None
all_in_fn = cpg.children_of(call.id)     # direct children of this node (via CONTAINS)
```

`scope_of` walks up to the nearest enclosing scope node. `children_of` only returns immediate children — not grandchildren.

### Source location

`CpgNode.location` is a `SourceLocation`:

```python
loc = fn_node.location
print(loc.file)    # Path object
print(loc.line)    # int, 1-based
print(loc.column)  # int, 0-based
```

Nodes can have `location=None` (synthetic nodes introduced during the CFG or inter-procedural DFG phases have no source location).

---

## 3. Annotations

Annotations are how you attach consumer metadata to nodes without touching the structural graph. The key design rule: `CpgNode.attrs` belongs to treeloom; annotations belong to you.

```python
# Write
cpg.annotate_node(node.id, "severity", "high")
cpg.annotate_node(node.id, "tags", ["sql-injection", "unvalidated-input"])

# Read
severity = cpg.get_annotation(node.id, "severity")   # "high"
all_ann  = cpg.annotations_for(node.id)               # {"severity": "high", "tags": [...]}

# Edge annotations
cpg.annotate_edge(source_id, target_id, "confidence", 0.95)
conf = cpg.get_edge_annotation(source_id, target_id, "confidence")
```

Annotations survive JSON serialization:

```python
json_str = to_json(cpg)
cpg2 = from_json(json_str)
assert cpg2.get_annotation(node.id, "severity") == "high"
```

Annotations are stored in a separate dict keyed by node ID string — they do not live in the NetworkX graph or in `CpgNode`. This separation ensures:
- Serialization round-trips are clean: structural data and consumer data serialize independently.
- You cannot accidentally overwrite a structural attribute.
- Multiple consumers can annotate the same graph independently if needed.

---

## 4. Query API

Access via `cpg.query()`, which returns a `GraphQuery` bound to this CPG.

### Path queries

```python
from treeloom import EdgeKind

query = cpg.query()

# All simple paths from source node to target node (up to cutoff hops)
source = next(cpg.nodes(kind=NodeKind.PARAMETER))
sink   = next(cpg.nodes(kind=NodeKind.CALL))
paths  = query.paths_between(source.id, sink.id, cutoff=15)
# paths: list[list[CpgNode]]

for path in paths:
    names = " -> ".join(n.name for n in path)
    print(names)
```

### Reachability

```python
# All nodes reachable from a node (forward BFS)
reachable = query.reachable_from(source.id)
# Filter to only follow data flow edges
dfg_reachable = query.reachable_from(
    source.id,
    edge_kinds=frozenset({EdgeKind.DATA_FLOWS_TO}),
)

# All nodes that can reach a target (backward BFS)
reaching = query.reaching(sink.id)
```

Both return `set[CpgNode]`. Without `edge_kinds`, they follow all edge types. This can produce large sets in dense graphs — prefer passing `edge_kinds` when you know which layer you're interested in.

### Node lookup

```python
from pathlib import Path

# Find the node at a specific source location
node = query.node_at(Path("src/app.py"), line=42)
# Returns CpgNode | None. When multiple nodes share a line,
# priority is: FUNCTION > CALL > VARIABLE > others.

# All nodes in a file
nodes = query.nodes_in_file(Path("src/app.py"))

# All nodes in a scope
fn_children = query.nodes_in_scope(fn_node.id)
```

### Subgraph extraction

```python
from treeloom import EdgeKind

# Extract a subgraph rooted at a function, up to 5 hops deep
sub = query.subgraph(fn_node.id, max_depth=5)
# sub is a new CodePropertyGraph with only the nodes and edges reachable from fn_node

# Limit to data flow edges only
dfg_sub = query.subgraph(
    fn_node.id,
    edge_kinds=frozenset({EdgeKind.DATA_FLOWS_TO, EdgeKind.DEFINED_BY}),
    max_depth=10,
)

# Subgraphs can be exported independently
dot = to_dot(dfg_sub)
```

Subgraphs are useful when you want to focus visualization or analysis on a specific function or module without processing the full graph.

---

## 5. Pattern Matching

`ChainPattern` lets you describe a sequence of node types (with optional wildcards) that must be connected by edges.

### Basic chain

```python
from treeloom import ChainPattern, StepMatcher, NodeKind, EdgeKind

# Find every chain: PARAMETER -> (any path via data flow) -> a call to eval or exec
pattern = ChainPattern(
    steps=[
        StepMatcher(kind=NodeKind.PARAMETER),
        StepMatcher(wildcard=True),
        StepMatcher(kind=NodeKind.CALL, name_pattern=r"eval|exec|os\.system"),
    ],
    edge_kind=EdgeKind.DATA_FLOWS_TO,
)

matches = cpg.query().match_chain(pattern)
# matches: list[list[CpgNode]] — each entry is one matching chain
for chain in matches:
    param, *intermediates, call = chain
    print(f"Param '{param.name}' reaches '{call.name}' via {len(intermediates)} intermediate nodes")
```

### StepMatcher options

Each step can match on any combination of:

```python
StepMatcher(
    kind=NodeKind.CALL,          # match a specific NodeKind
    name_pattern=r"cursor\..+",  # regex matched against node.name
    annotation_key="role",       # node must have this annotation
    annotation_value="sink",     # annotation must equal this value
    wildcard=False,              # if True, matches 0 or more intermediate nodes
)
```

A `wildcard=True` step performs BFS in the given edge direction to find the next non-wildcard step's match. Wildcards make it easy to express "eventually flows to" without enumerating every intermediate step.

### Annotation-based patterns

Combine structural and consumer-defined conditions in one pattern:

```python
# Find: annotated entry_point -> (any data flow path) -> annotated sink
pattern = ChainPattern(
    steps=[
        StepMatcher(annotation_key="role", annotation_value="entry_point"),
        StepMatcher(wildcard=True),
        StepMatcher(annotation_key="role", annotation_value="sink"),
    ],
    edge_kind=EdgeKind.DATA_FLOWS_TO,
)
matches = cpg.query().match_chain(pattern)
```

---

## 6. Serialization

### JSON round-trip

`to_json` and `from_json` serialize the full graph — nodes, edges, structural attributes, and all annotations:

```python
from treeloom import to_json, from_json

json_str = to_json(cpg)          # str, indented JSON
cpg2     = from_json(json_str)   # equivalent CodePropertyGraph

# Round-trip guarantee: all data is preserved
assert cpg2.node_count == cpg.node_count
assert cpg2.edge_count == cpg.edge_count
assert cpg2.get_annotation(node_id, "role") == cpg.get_annotation(node_id, "role")
```

The JSON format uses node-link representation with a top-level version field:

```json
{
  "treeloom_version": "0.2.2",
  "nodes": [...],
  "edges": [...],
  "annotations": {"node-id-str": {"key": "value"}},
  "edge_annotations": {"src-id:tgt-id": {"key": "value"}}
}
```

`Path` objects serialize as POSIX strings. `NodeId` objects serialize as their string value. The `_tree_node` field on `CpgNode` (the raw tree-sitter parse node) is not serialized — it is `None` after `build()` completes.

### Dict form

If you need programmatic access to the serialized structure rather than a string:

```python
data = cpg.to_dict()                    # dict
cpg2 = CodePropertyGraph.from_dict(data)
```

This is equivalent to `to_json`/`from_json` but skips the JSON encoding step. Useful when you want to transform the graph data before writing it, or embed it in a larger JSON document.

### Selective export

For visualization-only use cases where you don't need full round-trip fidelity:

```python
from treeloom import to_dot, generate_html, NodeKind, EdgeKind

# DOT: filter to data flow edges only
dot = to_dot(
    cpg,
    edge_kinds=frozenset({EdgeKind.DATA_FLOWS_TO, EdgeKind.CALLS}),
    node_kinds=frozenset({NodeKind.FUNCTION, NodeKind.CALL, NodeKind.PARAMETER}),
)

# HTML: include custom layers and overlays
from treeloom import VisualizationLayer, OverlayStyle

call_graph_layer = VisualizationLayer(
    name="Call Graph",
    edge_kinds=frozenset({EdgeKind.CALLS, EdgeKind.RESOLVES_TO}),
    node_kinds=frozenset({NodeKind.FUNCTION, NodeKind.CALL}),
    default_visible=True,
)

html = generate_html(
    cpg,
    layers=[call_graph_layer],
    title="My Project — Call Graph",
)
with open("output.html", "w") as f:
    f.write(html)
```

`generate_html` produces a self-contained HTML file. Cytoscape.js is loaded from CDN. The sidebar shows layer toggles and a search box. Clicking a node or edge opens a detail panel showing all attributes and annotations.

See [sanicode-integration.md](sanicode-integration.md) for a full overlay example including `OverlayStyle` for coloring nodes.

---

## Caveats and edge cases

**Multiple edges between the same node pair.** The graph backend is a `MultiDiGraph`, so CONTAINS and DATA_FLOWS_TO can both exist between the same source and target. When filtering with `cpg.edges(kind=EdgeKind.CONTAINS)`, you get only that edge type. Iterating without a kind filter returns all edges.

**Unresolved calls.** If a call target cannot be resolved (e.g., it comes from a third-party library not in the build), the CALL node exists in the graph with no outgoing CALLS edge. This is intentional — unknown calls remain visible as orphan CALL nodes.

**Synthetic nodes.** The CFG and inter-procedural DFG phases can introduce nodes with `location=None`. Always null-check `node.location` before accessing `.line` or `.column`.

**Import node volume.** In real Python codebases, IMPORT nodes often account for 50–60% of nodes. Filter or exclude them when building visualizations:

```python
html = generate_html(
    cpg,
    exclude_kinds=frozenset({NodeKind.IMPORT, NodeKind.LITERAL}),
)
```

This only affects the HTML output; the underlying CPG and any taint results are unchanged.

**Grammar packages are optional.** The core library installs without language grammars. To parse source files, install the `languages` extra:

```bash
pip install "treeloom[languages]"
```

If a grammar package is missing when you try to parse that language's files, you get a clear `ImportError` rather than a silent failure.
