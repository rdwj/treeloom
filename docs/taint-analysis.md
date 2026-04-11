# Taint Analysis with treeloom

treeloom includes a generic taint analysis engine that propagates labels through data flow edges. The engine knows nothing about security, PII, or compliance — it just tracks how labeled data moves through your code. What those labels mean is up to you.

This guide covers the engine, its API, and worked examples. For how a security consumer like sanicode wires the engine into a full analysis pipeline, see [sanicode-integration.md](sanicode-integration.md).

## How the Engine Works

The taint engine is a worklist-based forward analysis over the CPG's data flow graph.

1. **Seeding.** The engine calls `policy.sources(node)` on every node. If the callback returns a `TaintLabel`, that node is a source and its label is added to the worklist.

2. **Propagation.** For each node on the worklist, the engine follows outgoing `DATA_FLOWS_TO` edges. The current label set is propagated to each successor. If a successor gains new labels it didn't previously have, it's added to the worklist.

3. **Sanitizers.** When the engine reaches a node where `policy.sanitizers(node)` returns `True`, it records the sanitizer on any paths passing through it and sets `TaintPath.is_sanitized = True`. Propagation continues — sanitizers mark paths, they don't terminate them.

4. **Sinks.** When a node with labels reaches a node where `policy.sinks(node)` returns `True`, the engine records a `TaintPath`.

5. **Termination.** The worklist converges because label sets at each node can only grow (a monotone lattice), and the set of possible labels is finite.

Call boundaries are handled via function summaries computed during `build()`. When taint reaches a call site whose callee has a computed summary, the engine propagates labels from arguments to the return value according to the summary's `params_to_return` mapping, then continues propagation from the call site's result.

## Defining a TaintPolicy

`TaintPolicy` is the only configuration object the engine needs.

```python
from treeloom import TaintPolicy, TaintLabel, TaintPropagator, NodeKind

policy = TaintPolicy(
    sources=lambda node: (
        TaintLabel("user_input", node.id)
        if node.kind == NodeKind.PARAMETER
        else None
    ),
    sinks=lambda node: (
        node.kind == NodeKind.CALL
        and node.name in {"cursor.execute", "os.system", "eval"}
    ),
    sanitizers=lambda node: (
        node.kind == NodeKind.CALL
        and node.name in {"escape", "parameterize", "html.escape"}
    ),
    propagators=[],          # see "Custom Propagators" below
    implicit_param_sources=False,
)
```

All three callbacks receive a `CpgNode`. Sources return `TaintLabel | None`; sinks and sanitizers return `bool`.

### TaintLabel

A label carries the name of the taint source, the node that introduced it, and an optional attrs dict for any metadata you want to attach.

```python
from treeloom import TaintLabel

# Minimal label
label = TaintLabel(name="user_input", origin=node.id)

# With metadata — useful for attaching domain, severity, or tracking IDs
label = TaintLabel(
    name="pii",
    origin=node.id,
    attrs={"field": "email", "regulation": "GDPR"},
)
```

Labels are `frozen` dataclasses and hashable. A node accumulates a `frozenset[TaintLabel]` as analysis progresses.

## Reading TaintResult

`cpg.taint(policy)` returns a `TaintResult`. The main entry point is `result.paths`, a list of all `TaintPath` objects found.

```python
result = cpg.taint(policy)

print(f"Total paths:       {len(result.paths)}")
print(f"Unsanitized paths: {len(result.unsanitized_paths())}")
print(f"Sanitized paths:   {len(result.sanitized_paths())}")
```

**Filtering methods:**

```python
# Paths that never passed through a sanitizer — highest priority
for path in result.unsanitized_paths():
    ...

# Paths where a sanitizer was present — may still be interesting
for path in result.sanitized_paths():
    ...

# All paths that end at a specific sink node
paths = result.paths_to_sink(sink_node_id)

# All paths that originate from a specific source node
paths = result.paths_from_source(source_node_id)
```

**Per-node and per-edge label queries:**

```python
# Which labels have reached a given node?
labels = result.labels_at(node_id)
for label in labels:
    print(label.name, label.origin)

# Which labels flow along a specific edge?
labels = result.edge_labels(source_id, target_id)
```

`labels_at` is useful when you want to check whether taint reaches a node that isn't a declared sink — for instance, to inspect intermediate data before it reaches a call.

## TaintPath Structure

Each `TaintPath` has:

| Field | Type | Description |
|---|---|---|
| `source` | `CpgNode` | The node where taint was introduced |
| `sink` | `CpgNode` | The sink node where the path ends |
| `intermediates` | `list[CpgNode]` | All nodes on the path, including source and sink |
| `labels` | `frozenset[TaintLabel]` | Labels present at the sink |
| `is_sanitized` | `bool` | Whether a sanitizer was encountered on this path |
| `sanitizers` | `list[CpgNode]` | The sanitizer nodes, in order (empty if unsanitized) |

```python
for path in result.unsanitized_paths():
    print(f"{path.source.name} ({path.source.location})")
    print(f"  -> {path.sink.name} ({path.sink.location})")
    print(f"  Labels: {[l.name for l in path.labels]}")
    print(f"  Path ({len(path.intermediates)} nodes):")
    for node in path.intermediates:
        print(f"    {node.kind.value}: {node.name} @ {node.location}")
```

## Custom Propagators

The engine's default propagation follows `DATA_FLOWS_TO` edges mechanically. Some library functions transform tainted data in ways the engine can't see from the CPG alone — `json.loads` returns tainted data if its input is tainted, `str.format` carries taint from its arguments into the result, and so on. `TaintPropagator` lets you model these.

```python
from treeloom import TaintPropagator, NodeKind

# json.loads: tainted input -> tainted return value
json_propagator = TaintPropagator(
    match=lambda node: node.kind == NodeKind.CALL and node.name == "json.loads",
    param_to_return=True,
)

# subprocess.Popen: taint from first arg propagates to the process's stdin (param 1)
popen_propagator = TaintPropagator(
    match=lambda node: node.kind == NodeKind.CALL and node.name in {
        "subprocess.Popen", "subprocess.run", "subprocess.call"
    },
    param_to_return=True,
    param_to_param={0: 1},  # arg 0 (cmd) can flow to stdin (arg 1)
)

policy = TaintPolicy(
    sources=...,
    sinks=...,
    sanitizers=...,
    propagators=[json_propagator, popen_propagator],
)
```

`TaintPropagator` fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `match` | `Callable[[CpgNode], bool]` | required | Returns True if this propagator applies to the node |
| `param_to_return` | `bool` | `True` | Taint on any parameter propagates to the return value |
| `param_to_param` | `dict[int, int] \| None` | `None` | Taint from parameter N propagates to parameter M |

When multiple propagators match a node, all of them are applied.

## Stdlib Propagation Models

treeloom ships YAML-based propagation models for common Python stdlib functions so you don't have to define them yourself.

```python
from treeloom.models import load_models, list_builtin_models

# See what's available
for model_name in list_builtin_models():
    print(model_name)
# json, pickle, subprocess, os.path, shlex, base64, ...

# Load specific models
propagators = load_models(["json", "subprocess", "os.path"])

policy = TaintPolicy(
    sources=...,
    sinks=...,
    sanitizers=...,
    propagators=propagators,
)
```

To load all available models:

```python
propagators = load_models()  # no argument = all builtin models
```

Models are YAML files under `src/treeloom/models/`. Each describes which function names match, whether `param_to_return` applies, and any `param_to_param` mappings. You can write your own model files and load them by path:

```python
from treeloom.models import load_models_from_file

propagators = load_models_from_file("myapp/taint-models.yaml")
```

The YAML format:

```yaml
# myapp/taint-models.yaml
models:
  - name: "mylib.sanitize_html"
    match: ["sanitize_html"]
    param_to_return: false   # sanitizer — does not propagate taint

  - name: "mylib.format_query"
    match: ["format_query", "mylib.format_query"]
    param_to_return: true    # output carries taint from inputs
```

## implicit_param_sources

Setting `implicit_param_sources=True` automatically seeds every `PARAMETER` node in the CPG as a taint source. The auto-generated label name is `param:{param_name}`.

```python
policy = TaintPolicy(
    sources=lambda node: None,  # no explicit sources needed
    sinks=lambda node: node.kind == NodeKind.CALL and node.name == "cursor.execute",
    sanitizers=lambda node: False,
    implicit_param_sources=True,
)
```

This is useful for two scenarios:

**Finding all data flow paths from any function parameter to any dangerous call.** You get a comprehensive map of the attack surface without needing to enumerate which parameters are user-controlled.

**Library analysis.** If you're analyzing a library (not an application), there are no HTTP handlers or external inputs — but any function parameter could receive attacker-controlled data if the caller is malicious.

When `implicit_param_sources=True`, parameters that are also returned by the explicit `sources` callback keep the explicit label; the implicit `param:name` label is only added for parameters the explicit callback returned `None` for.

## CLI Taint Analysis

You can run taint analysis from the command line using YAML policy files, without writing Python.

```bash
# Run taint analysis, print results to stdout
treeloom taint cpg.json --policy policy.yaml

# Run and write an annotated CPG to disk (node annotations for sources/sinks/paths)
treeloom taint cpg.json --policy policy.yaml --apply -o annotated.cpg.json
```

Policy YAML format:

```yaml
# policy.yaml
sources:
  - kind: parameter          # match by NodeKind
  - kind: call
    name_pattern: "request\\.args\\.get|request\\.form\\.get|request\\.json"
    label: "http_input"

sinks:
  - kind: call
    name_pattern: "cursor\\.execute|execute_query|raw_query"
  - kind: call
    name_pattern: "os\\.system|subprocess\\.run|subprocess\\.call|Popen"

sanitizers:
  - kind: call
    name_pattern: "escape|parameterize|html\\.escape|bleach\\.clean"

implicit_param_sources: false
```

Each entry in `sources`, `sinks`, and `sanitizers` can match on `kind` (a `NodeKind` value, case-insensitive), `name_pattern` (a Python regex matched against `node.name`), or both. For sources, `label` sets the label name (defaults to `"tainted"`).

The `--apply` flag writes the results back as node annotations on the output CPG:

- `role = "source"` on source nodes
- `role = "sink"` on sink nodes that were reached
- `taint_paths = [...]` on sink nodes, listing path lengths and label names

These annotations persist through serialization, so the output can be loaded and visualized with `treeloom viz`.

## Example: Finding SQL Injection

This end-to-end example shows how to go from source code to a list of SQL injection paths.

### The target code

```python
# webapp/routes.py
from flask import request
import db

def search():
    query = request.args.get("q")
    results = db.execute("SELECT * FROM items WHERE name = '" + query + "'")
    return results

def safe_search():
    query = request.args.get("q")
    escaped = db.escape(query)
    results = db.execute("SELECT * FROM items WHERE name = '" + escaped + "'")
    return results
```

### Step 1: Build the CPG

```python
from pathlib import Path
from treeloom import CPGBuilder

cpg = CPGBuilder().add_directory(Path("webapp/")).build()
print(f"CPG: {cpg.node_count} nodes, {cpg.edge_count} edges")
```

### Step 2: Define the policy

```python
from treeloom import TaintPolicy, TaintLabel, NodeKind
from treeloom.models import load_models

# HTTP input sources: Flask request accessors
HTTP_SOURCES = {
    "request.args.get",
    "request.form.get",
    "request.get_json",
    "request.json",
}

# SQL execution sinks
SQL_SINKS = {
    "cursor.execute",
    "execute",      # db.execute shorthand
    "raw",
    "execute_query",
}

# Known sanitizers
SQL_SANITIZERS = {
    "escape",
    "parameterize",
    "db.escape",
}

policy = TaintPolicy(
    sources=lambda node: (
        TaintLabel("http_input", node.id, attrs={"source_type": "http"})
        if node.kind == NodeKind.CALL and node.name in HTTP_SOURCES
        else None
    ),
    sinks=lambda node: node.kind == NodeKind.CALL and node.name in SQL_SINKS,
    sanitizers=lambda node: node.kind == NodeKind.CALL and node.name in SQL_SANITIZERS,
    propagators=load_models(["json"]),  # carry taint through json.loads if needed
)
```

### Step 3: Run taint analysis

```python
result = cpg.taint(policy)

print(f"Total paths found:       {len(result.paths)}")
print(f"Unsanitized (SQLi risk): {len(result.unsanitized_paths())}")
print(f"Sanitized (check logic): {len(result.sanitized_paths())}")
```

### Step 4: Report findings

```python
for path in result.unsanitized_paths():
    source = path.source
    sink = path.sink
    print(f"\nSQL Injection Risk")
    print(f"  Source: {source.name} at {source.location}")
    print(f"  Sink:   {sink.name} at {sink.location}")
    print(f"  Labels: {[l.name for l in path.labels]}")
    print(f"  Hops:   {len(path.intermediates)}")

for path in result.sanitized_paths():
    print(f"\nSanitized path (verify correctness):")
    print(f"  Source:    {path.source.name} at {path.source.location}")
    print(f"  Sanitizer: {path.sanitizers[0].name} at {path.sanitizers[0].location}")
    print(f"  Sink:      {path.sink.name} at {path.sink.location}")
```

For the example code above, you'd expect:

- One unsanitized path: `search` -> `request.args.get` -> string concat -> `db.execute`
- One sanitized path: `safe_search` -> `request.args.get` -> `db.escape` -> `db.execute`

### Step 5: Visualize (optional)

```python
from treeloom import Overlay, OverlayStyle, generate_html, NodeKind

overlay = Overlay(name="SQL Injection Analysis")

for path in result.unsanitized_paths():
    overlay.node_styles[path.sink.id] = OverlayStyle(
        color="#E53935", label="SQLi SINK", size=40
    )
    overlay.node_styles[path.source.id] = OverlayStyle(
        color="#FF9800", label="HTTP INPUT", size=40
    )

for path in result.sanitized_paths():
    overlay.node_styles[path.sink.id] = OverlayStyle(
        color="#4CAF50", label="SANITIZED", size=35
    )
    for s in path.sanitizers:
        overlay.node_styles[s.id] = OverlayStyle(
            color="#2196F3", label="SANITIZER", size=35
        )

html = generate_html(
    cpg,
    overlays=[overlay],
    title="SQL Injection Analysis",
    exclude_kinds=frozenset({NodeKind.IMPORT, NodeKind.LITERAL}),
)
with open("sqli-report.html", "w") as f:
    f.write(html)
```

Open `sqli-report.html` in a browser. Nodes are colored by finding type, and you can click any node or edge to inspect its attributes, annotations, and taint labels.

## Performance

The taint engine uses batch convergence: labels that share the same `(name, field_path)` are grouped during propagation so that adding a new origin to an already-tainted node does not re-enqueue it. Combined with indexed graph lookups for scope children and typed edges, the engine scales linearly with CPG size.

In practice, 15 Java files (~300 LOC each, ~2400 CPG nodes) complete a full knowledge graph build including taint analysis in ~120ms. The earlier per-origin propagation scaled quadratically (~2.8s for the same workload).

If you define many sources with distinct label names (e.g., `"db_input"`, `"file_input"`, `"env_var"`), convergence groups them independently. With K distinct label kinds and N nodes, propagation is O(K × N) rather than O(sources × N). For most security analyses, K is 1–3.

## Tips

**Start with `implicit_param_sources=True` to explore the attack surface.** Once you see which parameter-to-sink paths exist, narrow down to the sources you actually care about.

**Check `result.labels_at(node_id)` on intermediate nodes.** This shows exactly which labels are propagating where, which is useful for debugging a policy that's finding too many or too few paths.

**Sanitizers mark, not terminate.** A sanitized path still appears in `result.paths`. Use `result.unsanitized_paths()` for high-priority findings, then review `result.sanitized_paths()` to verify that your sanitizer logic is actually correct.

**Propagators compensate for missing DFG edges.** If a library function transforms tainted data and the engine isn't tracking it, the path will appear to end at the library call even though the taint continues. Use a `TaintPropagator` (or add the function to your YAML models file) to bridge the gap.
