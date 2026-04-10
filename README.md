# treeloom

A language-agnostic Code Property Graph (CPG) library for Python. treeloom parses source code via tree-sitter, builds a unified graph combining AST, control flow, data flow, and call graph layers, and provides query and analysis APIs on top of it.

## Features

- **Multi-language parsing** -- Python, JavaScript, TypeScript, Go, Java, C, C++, and Rust via tree-sitter grammars
- **Unified graph model** -- AST structure, control flow, data flow, and call graphs in a single queryable graph
- **Taint analysis** -- generic label-propagation engine for tracking data flow from sources to sinks, with sanitizer support and field-sensitive propagation
- **Stdlib propagation models** -- YAML-based data flow models for Python stdlib (json, pickle, subprocess, os.path, etc.) loaded via `load_models()`
- **Incremental rebuild** -- `CPGBuilder.rebuild()` re-parses only changed files, preserving unchanged nodes, edges, and annotations
- **Type-aware call resolution** -- constructor tracking and MRO-based method dispatch for Python
- **Import-following resolution** -- calls to imported functions resolve across file boundaries when the source module is in the CPG
- **Pattern matching** -- chain-based pattern queries for finding code patterns across the graph
- **Visualization** -- export to JSON, Graphviz DOT, or interactive HTML (Cytoscape.js)
- **Consumer annotations** -- attach arbitrary metadata to nodes without modifying the structural graph
- **Overlay system** -- inject visual styling for domain-specific visualization (e.g., security analysis results)
- **Serialization** -- full round-trip JSON serialization including annotations
- **Portable graphs** -- `CPGBuilder(relative_root=...)` stores relative file paths, making serialized graphs portable across machines

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

## Documentation

- [docs/](https://github.com/rdwj/treeloom/tree/main/docs) -- user-facing reference and integration guides
- [research/](https://github.com/rdwj/treeloom/tree/main/research) -- CPG tooling landscape, testing reports, and investigation notes
- [benchmarks/](https://github.com/rdwj/treeloom/tree/main/benchmarks) -- performance benchmark suite
- [CLAUDE.md](https://github.com/rdwj/treeloom/blob/main/CLAUDE.md) -- full API specification (data model, algorithms, builder pipeline)

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

### Version 0.5.0

- `self`/`cls` type inference: method calls on `self` and `cls` now resolve via MRO using the enclosing class context, significantly improving Python call resolution rates.
- Import-following call resolution: calls to functions imported via `from module import func` now resolve when the source module is in the CPG.
- Module-scope disambiguation: call resolution now walks the scope chain to match qualifiers against ancestor scopes (module → class → function).
- `CPGBuilder(relative_root=Path(...))` stores all file paths relative to the given root, making serialized CPGs portable across machines.
- 1144 tests

### Version 0.4.1

- Edge queries (`treeloom edges`) now show file:line locations for source and target nodes in all output formats (table, JSON, CSV, TSV). JSON output includes explicit `file` and `line` fields.
- `config --set` and `--unset` now list valid config keys when an unknown key is provided.
- `config --init` warns when the current directory doesn't appear to be a project root and prints the resolved absolute path on success.
- License corrected to MIT across all project metadata.
- 1138 tests

### Version 0.4.0

- Language-filtered call resolution: build no longer hangs on large multi-language repos. CALL nodes are partitioned by language during resolution while FUNCTION nodes remain shared across visitors.
- Build progress callbacks: `CPGBuilder(progress=callback)` accepts a `BuildProgressCallback` callable that receives per-phase status and timing. New public type `BuildProgressCallback`.
- Build timeout: `CPGBuilder(timeout=seconds)` aborts a stalled build with `BuildTimeoutError`. Exposed as `--timeout` CLI flag. New public type `BuildTimeoutError`.
- `LanguageVisitor.resolve_calls()` now accepts optional `function_nodes` and `call_nodes` kwargs for pre-filtered node sets, enabling the language-filtered resolution path.
- Stdlib data flow propagation models: `load_models(["python-stdlib"])` returns `TaintPropagator` instances for json, pickle, os.path, subprocess, urllib.parse, base64, shlex, builtins, and string/dict methods. Also `list_builtin_models()` and `load_model_file()`. Models live in `src/treeloom/models/builtin/` as YAML.
- Basic type inference for call resolution: Python visitor tracks constructor assignments (`d = Dog()`) and records `inferred_type` on VARIABLE nodes, `receiver_inferred_type` on CALL nodes. Class definitions get `attrs["bases"]`. Method calls with known receiver types resolve via MRO before name-matching fallback.
- Incremental/delta-based CPG rebuild: `CPGBuilder.rebuild(changed=...)` re-parses only changed files; unchanged nodes, edges, and annotations are preserved. `CodePropertyGraph` gains `remove_node()` (cascading edge removal), `remove_edge()`, and `nodes_for_file()`. SHA-256 content hashing for auto change detection when `changed` is None.
- Benchmark suite: pytest-benchmark based, synthetic Python at 500/2k/5k LOC exercising build, taint, JSON round-trip, and query. Memory tests via psutil.
- Field-sensitive taint propagation: `TaintLabel.field_path` (str | None) distinguishes `obj.field_a` taint from `obj` taint. Attribute access edges with `field_name` attrs narrow object-level taint to field-level; mismatching fields filtered. `emit_data_flow` now accepts `**attrs`.
- Non-Python language visitor fixture tests: data_flow, cross_function_taint, method_calls, nested_scopes fixtures for JS, Go, TS, Rust, C, C++. Fixed Go visitor bug with missing DATA_FLOWS_TO for reassignments and parameter DFG.
- 1131 tests

### Version 0.3.0

- `TaintPolicy.implicit_param_sources`: treat function parameters as automatic taint sources (#54)
- Per-edge taint labels: `TaintResult.edge_labels(src, tgt)` returns which labels flow along each edge (#56)
- `GraphQuery.paths_to_sink()`: backward traversal from a sink to find all reaching source paths (#57)
- Inter-procedural taint integration tests: verified 3-function call chain propagation (#55)
- Fixed sanitizer convergence: paths through different sanitizers no longer falsely marked unsanitized
- 888 tests (now 1123 on main)

### Version 0.2.7

- Diff defaults to basename matching for cross-directory comparisons (e.g., bad/ vs good/)
- Added `--count` flag to edges command for parity with query
- Documented taint sink-only reporting in llms.txt (engine only reports paths terminating at declared sinks)
- 867 tests

### Version 0.2.6

- Updated llms.txt and llms-full.txt with complete v0.2.5 API reference
- All 15 CLI commands documented with flags and usage examples
- YAML schemas for taint policy, annotation rules, and pattern files
- Discoverability fixes: exclude_kinds, apply_to, field sensitivity surfaced in Gotchas

### Version 0.2.5

- Chained attribute receivers (`request.form.attr`) resolve recursively through DFG
- Basic field sensitivity: `obj.safe` and `obj.unsafe` tracked as separate variables
- `--output-format` flag on query and edges: table, json, csv, tsv, jsonl
- 862 tests

### Version 0.2.4

- Python visitor: subscript (`dict['key']`) and attribute (`obj.attr`) expressions now generate DFG nodes
- Python visitor: decorated functions (Flask `@app.route`), keyword args, `**kwargs`, comprehensions now tracked
- Java visitor: string concatenation with `+` emits DFG, try-catch bodies visited, annotations captured
- Method call return values flow to assigned variables across both Python and Java
- VAmPI (Python) taint paths: 4 → 40; VulnerableApp (Java) SQL injection/XSS/command injection paths found
- Updated llms.txt and integration guide with `exclude_kinds` and `apply_to` patterns for better discoverability
- 849 tests

### Version 0.2.3

- Fixed data flow through chained method calls (`.format().fetchone()` pattern)
- New `treeloom edges` command for querying edges by kind, source/target name
- `treeloom diff --match-by-basename` and `--strip-prefix` for cross-directory comparison
- `treeloom query --scope`, `--count`, `--annotation`, `--annotation-value` filters
- Fixed `--json-errors` flag (errors now propagate to main handler for JSON formatting)
- Build `--progress` skips unsupported file types, `--language` filter restricts parsing
- DOT `--edge-kind` filter prunes disconnected nodes
- Import nodes hidden by default in HTML visualization (togglable "Imports" layer)
- `treeloom viz --exclude-kind` for consumer-controlled node filtering
- Large graph warning (>500 nodes) suggesting subgraph extraction
- 821 tests

### Version 0.2.2

- Fixed data flow tracking through string formatting (.format(), % operator, f-strings)
- Fixed parameter references not generating data flow edges (root cause of taint false negatives)
- Implemented CFG edge generation (flows_to, branches_to) connecting statements within functions
- Implemented inter-procedural data flow: call-site arguments flow to callee parameters, return values flow back
- Taint analysis on vulpy (deliberately vulnerable Flask app) went from 0 to 12 findings including cross-file HTTP-input-to-SQL-injection traces
- 776 tests

### Version 0.2.1

- New CLI commands: `annotate`, `diff`, `pattern`, `subgraph`, `watch`, `serve`, `completions`
- `--json-errors` global flag for machine-readable error output
- `--progress` flag for build command
- Multiple `--policy` files for taint policy composition
- `TaintResult.apply_to(cpg)` stamps taint annotations onto the graph
- `--apply` flag for taint command writes annotated CPG directly
- Fixed variable scoping in all visitors (ScopeStack replaces flat dict)
- Fixed import alias capture in Python, JavaScript, TypeScript visitors
- Fixed taint sanitizer tracking on convergent paths (per-origin intersection)
- Shell completions for bash, zsh, fish
- HTTP JSON API server (`treeloom serve`) with query, node, edges, subgraph endpoints
- 750 tests

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

MIT
