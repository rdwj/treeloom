# treeloom

A language-agnostic Code Property Graph (CPG) library for Python. treeloom parses source code via tree-sitter, builds a unified graph combining AST, control flow, data flow, and call graph layers, and provides query and analysis APIs on top of it.

## Features

- **Multi-language parsing** -- Python, JavaScript, TypeScript, Go, Java, C, C++, and Rust via tree-sitter grammars
- **Unified graph model** -- AST structure, control flow, data flow, and call graphs in a single queryable graph
- **Taint analysis** -- generic label-propagation engine for tracking data flow from sources to sinks, with sanitizer support
- **Pattern matching** -- chain-based pattern queries for finding code patterns across the graph
- **Visualization** -- export to JSON, Graphviz DOT, or interactive HTML (Cytoscape.js)
- **Consumer annotations** -- attach arbitrary metadata to nodes without modifying the structural graph
- **Overlay system** -- inject visual styling for domain-specific visualization (e.g., security analysis results)
- **Serialization** -- full round-trip JSON serialization including annotations

## Quick Start

```python
from pathlib import Path
from treeloom import CPGBuilder, NodeKind, EdgeKind

# Build a CPG from a directory of source files
cpg = CPGBuilder().add_directory(Path("src/")).build()

# Inspect the graph
print(f"{cpg.node_count} nodes, {cpg.edge_count} edges")
print(f"Files: {[str(f) for f in cpg.files]}")

# Find all function definitions
for func in cpg.nodes(kind=NodeKind.FUNCTION):
    print(f"  {func.name} at {func.location}")

# Find all call sites targeting a specific function
for call in cpg.nodes(kind=NodeKind.CALL):
    if call.name == "eval":
        print(f"  eval() called at {call.location}")

# Query: what nodes are reachable from a function via data flow?
func_node = next(cpg.nodes(kind=NodeKind.FUNCTION))
reachable = cpg.query().reachable_from(
    func_node.id, edge_kinds=frozenset({EdgeKind.DATA_FLOWS_TO})
)
```

## Installation

```bash
pip install treeloom              # core only (networkx + tree-sitter)
pip install treeloom[languages]   # with all language grammars
pip install treeloom[all]         # everything (grammars + dev tools)
```

For development:

```bash
git clone https://github.com/rdwj/treeloom.git
cd treeloom
pip install -e ".[all]"
```

## Supported Languages

| Language   | Extensions         | Grammar Package           |
|------------|--------------------|---------------------------|
| Python     | `.py`, `.pyi`      | `tree-sitter-python`      |
| JavaScript | `.js`, `.mjs`, `.cjs` | `tree-sitter-javascript`  |
| TypeScript | `.ts`, `.tsx`          | `tree-sitter-typescript`  |
| Go         | `.go`              | `tree-sitter-go`          |
| Java       | `.java`            | `tree-sitter-java`        |
| C          | `.c`, `.h`         | `tree-sitter-c`           |
| C++        | `.cpp`, `.cc`, ... | `tree-sitter-cpp`         |
| Rust       | `.rs`              | `tree-sitter-rust`        |

Grammar packages are optional dependencies. The core library works without them -- you just can't parse files without the appropriate grammar installed. Missing grammars produce clear error messages, not crashes.

## Architecture

treeloom builds a Code Property Graph -- a single directed graph that unifies four views of source code.

**AST layer.** Module, class, function, parameter, variable, call, and literal nodes connected by containment edges (`CONTAINS`, `HAS_PARAMETER`). This gives you the structural hierarchy of the code.

**Control flow layer.** Statement-level flow between nodes within functions. `FLOWS_TO` edges represent sequential execution; `BRANCHES_TO` edges represent conditional or loop branching.

**Data flow layer.** Tracks where variables are defined and used, and how data propagates through assignments, function calls, and return values. Edges: `DATA_FLOWS_TO`, `DEFINED_BY`, `USED_BY`.

**Call graph layer.** Links call sites to their resolved function definitions. `CALLS` edges connect a call node to the function it invokes. Resolution is best-effort (no full type inference).

## API Overview

| Class / Function       | Purpose                                              |
|------------------------|------------------------------------------------------|
| `CPGBuilder`           | Fluent builder -- add files/directories, call `build()` |
| `CodePropertyGraph`    | Central graph object -- node/edge access, annotations, traversal, serialization |
| `GraphQuery`           | Path queries, reachability, subgraph extraction, pattern matching |
| `TaintPolicy`          | Consumer-defined source/sink/sanitizer callbacks     |
| `TaintResult`          | Taint analysis output -- paths, labels, filtering    |
| `ChainPattern`         | Declarative pattern for matching node chains          |
| `Overlay`              | Per-node/edge visual styling for HTML export         |
| `to_json` / `from_json`| JSON serialization with full round-trip support      |
| `to_dot`               | Graphviz DOT export                                  |
| `generate_html`        | Interactive HTML visualization with Cytoscape.js     |

For full API details, see `CLAUDE.md`.

## Taint Analysis

treeloom's taint engine propagates labels through data flow edges. It is generic -- the labels can represent anything (security-sensitive data, PII, environment variables). What they mean is up to you.

```python
from treeloom import (
    CPGBuilder, CodePropertyGraph, TaintPolicy, TaintLabel, NodeKind,
)
from pathlib import Path

cpg = CPGBuilder().add_directory(Path("myapp/")).build()

# Define what constitutes a source, sink, and sanitizer
policy = TaintPolicy(
    sources=lambda node: (
        TaintLabel("user_input", node.id)
        if node.kind == NodeKind.PARAMETER and node.name == "user_data"
        else None
    ),
    sinks=lambda node: (
        node.kind == NodeKind.CALL and node.name in ("exec", "eval", "os.system")
    ),
    sanitizers=lambda node: (
        node.kind == NodeKind.CALL and node.name == "sanitize"
    ),
)

result = cpg.taint(policy)

for path in result.unsanitized_paths():
    print(f"Unsanitized: {path.source.name} -> {path.sink.name}")
    print(f"  Labels: {[l.name for l in path.labels]}")
    for node in path.intermediates:
        print(f"    {node.kind.value}: {node.name} at {node.location}")
```

## Export and Visualization

### JSON

Full round-trip serialization, including annotations:

```python
from treeloom import to_json, from_json

json_str = to_json(cpg)
restored = from_json(json_str)  # equivalent graph
```

### Graphviz DOT

```python
from treeloom import to_dot, EdgeKind

# Full graph
dot = to_dot(cpg)

# Only data flow edges
dot = to_dot(cpg, edge_kinds=frozenset({EdgeKind.DATA_FLOWS_TO}))

with open("graph.dot", "w") as f:
    f.write(dot)
```

### Interactive HTML

Self-contained HTML with Cytoscape.js. Includes layer toggles, search, click-to-inspect, and overlay support.

```python
from treeloom import generate_html, Overlay, OverlayStyle

html = generate_html(cpg, title="My Project CPG")

with open("cpg.html", "w") as f:
    f.write(html)
```

## Development

Set up a local development environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
```

Run tests:

```bash
pytest
pytest --cov=treeloom --cov-report=html
```

Lint and type-check:

```bash
ruff check src/ tests/
mypy src/treeloom/
```

## Changelog

### Version 0.2.0

- CLI with 7 subcommands: `build`, `info`, `query`, `taint`, `viz`, `dot`, `config`
- YAML-based taint policies for CLI-driven analysis (sources, sinks, sanitizers, propagators)
- Project and user configuration via `.treeloom.yaml` and `~/.config/treeloom/config.yaml`
- Works with `pip install treeloom`, `uvx treeloom`, and `uv tool install treeloom`
- 585 tests

### Version 0.1.0

- Initial release
- Code Property Graph with four layers: AST, control flow, data flow, call graph
- Language visitors: Python, JavaScript, TypeScript/TSX, Go, Java, C, C++, Rust
- Worklist-based taint analysis engine with inter-procedural propagation
- Pattern matching query API with wildcard support
- Export to JSON (round-trip), Graphviz DOT, and interactive HTML (Cytoscape.js)
- Consumer annotation and overlay system for domain-specific visualization
- 539 tests

## License

Apache-2.0
