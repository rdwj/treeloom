# Getting Started with treeloom

treeloom parses source code into a unified Code Property Graph (CPG) — a single directed graph combining AST structure, control flow, data flow, and the call graph. You can query and analyze it from the CLI or the Python API.

Supported languages: Python, JavaScript, TypeScript, Go, Java, C, C++, Rust.

---

## Installation

```bash
# Core library only (no language parsers)
pip install treeloom

# Core + all language grammars
pip install "treeloom[languages]"

# Everything (languages + dev tools)
pip install "treeloom[all]"
```

**Development setup** (from source):

```bash
git clone https://github.com/rdwj/treeloom.git
cd treeloom
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
```

---

## Building your first CPG

### From the CLI

Point treeloom at a directory and write the CPG to a JSON file:

```bash
treeloom build src/ -o cpg.json --progress
```

`--progress` prints phase updates (Parse, CFG, Call resolution, Inter-procedural DFG) so you can see what's happening. The output `cpg.json` is a portable node-link format you can share, cache, and reload.

To analyze a single file:

```bash
treeloom build main.py -o cpg.json
```

### From Python

```python
from pathlib import Path
from treeloom import CPGBuilder

cpg = CPGBuilder().add_directory(Path("src/")).build()

print(f"Files: {len(cpg.files)}")
print(f"Nodes: {cpg.node_count}, Edges: {cpg.edge_count}")
```

Save the CPG to disk and reload it later:

```python
from treeloom.export.json import to_json, from_json

# Save
with open("cpg.json", "w") as f:
    f.write(to_json(cpg))

# Reload
with open("cpg.json") as f:
    cpg = from_json(f.read())
```

---

## Exploring the graph

### Summary stats

```bash
treeloom info cpg.json
```

This prints node and edge counts broken down by kind — a quick sanity check that the build captured what you expected.

### Listing nodes by kind

List all functions in the graph:

```bash
treeloom query cpg.json --kind function
```

Find all call sites named `eval` (or matching a pattern):

```bash
treeloom query cpg.json --kind call --name "eval"
```

Dangerous call families:

```bash
treeloom query cpg.json --kind call --name "exec|eval|os\.system|subprocess"
```

### Viewing the call graph

```bash
treeloom edges cpg.json --kind calls
```

This prints every `CALLS` edge — which call site resolves to which function definition. Useful for understanding cross-module dependencies.

### From Python

```python
from treeloom import NodeKind, EdgeKind

# Walk all functions
for node in cpg.nodes(kind=NodeKind.FUNCTION):
    print(node.name, node.location)

# Find call sites by name
for node in cpg.nodes(kind=NodeKind.CALL):
    if "eval" in node.name:
        print(node.name, node.location)

# Find what calls a specific function
from treeloom.query.api import GraphQuery
query = cpg.query()
callers = query.reaching(fn_node.id, edge_kinds=frozenset({EdgeKind.CALLS}))
```

---

## Inline example you can run

Save this as `explore.py`, then run `python explore.py` inside any Python project:

```python
from pathlib import Path
from treeloom import CPGBuilder, NodeKind, EdgeKind

cpg = CPGBuilder().add_directory(Path("src/")).build()

print(f"Parsed {len(cpg.files)} file(s) — {cpg.node_count} nodes, {cpg.edge_count} edges\n")

# Show all functions
functions = list(cpg.nodes(kind=NodeKind.FUNCTION))
print(f"Functions ({len(functions)}):")
for fn in functions[:20]:
    loc = fn.location
    print(f"  {fn.name}  ({loc.file}:{loc.line})")

# Show call sites that look risky
print("\nCall sites of interest:")
for call in cpg.nodes(kind=NodeKind.CALL):
    if any(name in call.name for name in ("eval", "exec", "system", "popen")):
        print(f"  {call.name}  ({call.location.file}:{call.location.line})")
```

---

## Visualizing

### Interactive HTML

Generate a self-contained HTML file with layer toggles, click-to-inspect, and search:

```bash
treeloom viz cpg.json --open
```

`--open` launches the file in your default browser immediately. The visualization has four toggleable layers: Structure, Data Flow, Control Flow, and Call Graph.

To save without opening:

```bash
treeloom viz cpg.json -o graph.html
```

### Graphviz DOT

Export to DOT for use with Graphviz, Gephi, or other tools:

```bash
treeloom dot cpg.json -o graph.dot

# Render to PNG
dot -Tpng graph.dot -o graph.png
```

Filter to only the call graph edges:

```bash
treeloom dot cpg.json --edge-kinds calls -o callgraph.dot
```

### From Python

```python
from treeloom.export.html import generate_html
from treeloom.export.dot import to_dot

html = generate_html(cpg, title="My Project CPG")
with open("graph.html", "w") as f:
    f.write(html)

dot = to_dot(cpg)
with open("graph.dot", "w") as f:
    f.write(dot)
```

---

## Next steps

- **[Library Guide](library-guide.md)** — full Python API: CPGBuilder options, graph traversal, annotations, pattern matching.
- **[Taint Analysis](taint-analysis.md)** — data flow tracking with `TaintPolicy`, sources, sinks, sanitizers, and inter-procedural propagation.
- **[CLI Reference](cli-reference.md)** — all commands and flags.
- **[Sanicode Integration](sanicode-integration.md)** — using treeloom as the graph backend for security analysis.
