# treeloom — Project Context

treeloom is a language-agnostic Code Property Graph (CPG) library. It parses source code via tree-sitter, builds a unified graph (AST + control flow + data flow + call graph), and provides query and analysis APIs. Its primary consumer is sanicode (a security analysis tool at ~/Developer/sanicode), but it is a general-purpose library with no security-specific concepts.

See `RESEARCH.md` for the full CPG tooling landscape and rationale for building treeloom rather than adopting Joern, CodeQL, or Fraunhofer's CPG.

## Tech Stack

- Python 3.10+, package name `treeloom`
- Graph backend: NetworkX (behind a `GraphBackend` protocol for future swap to rustworkx)
- Parsing: tree-sitter with per-language grammar packages
- No external services, no network calls, fully offline
- Build: Hatchling
- Testing: pytest, 80%+ coverage target

## Project Structure

```
treeloom/
├── src/treeloom/
│   ├── model/          # Data model: nodes, edges, locations
│   │   ├── location.py
│   │   ├── nodes.py
│   │   └── edges.py
│   ├── graph/          # Core CPG, builder, backend abstraction
│   │   ├── backend.py
│   │   ├── cpg.py
│   │   └── builder.py
│   ├── analysis/       # Taint engine, function summaries, reachability
│   │   ├── taint.py
│   │   ├── summary.py
│   │   └── reachability.py
│   ├── query/          # Graph query API and pattern matching
│   │   ├── api.py
│   │   └── pattern.py
│   ├── lang/           # Language visitor protocol + built-in visitors
│   │   ├── protocol.py
│   │   ├── base.py
│   │   ├── registry.py
│   │   └── builtin/
│   │       ├── python.py
│   │       ├── javascript.py
│   │       ├── typescript.py
│   │       ├── go.py
│   │       ├── java.py
│   │       ├── c.py
│   │       ├── cpp.py
│   │       └── rust.py
│   ├── export/         # Serialization: JSON, DOT, HTML
│   │   ├── json.py
│   │   ├── dot.py
│   │   └── html.py
│   ├── overlay/        # Consumer-injected visualization overlays
│   │   └── api.py
│   ├── version.py
│   └── __init__.py
├── tests/
│   ├── fixtures/       # Small source files per language per concept
│   │   └── python/
│   ├── test_model/
│   ├── test_graph/
│   ├── test_analysis/
│   ├── test_query/
│   ├── test_lang/
│   └── test_export/
├── pyproject.toml
├── CLAUDE.md
└── RESEARCH.md
```


## Architecture Overview

treeloom builds a Code Property Graph — a single directed graph that unifies four views of source code:

1. **AST layer**: Module -> Class -> Function -> Parameter/Variable/Call/Literal hierarchy. Edges: `CONTAINS`, `HAS_PARAMETER`, `HAS_RETURN_TYPE`.
2. **CFG layer**: Statement-level control flow (sequential, branching, loops). Edges: `FLOWS_TO`, `BRANCHES_TO`.
3. **DFG layer**: Data flow — where variables are defined and used, how data propagates through assignments, calls, returns. Edges: `DATA_FLOWS_TO`, `DEFINED_BY`, `USED_BY`.
4. **Call graph layer**: Which call sites resolve to which function definitions. Edges: `CALLS`, `RESOLVES_TO`.

The graph is built incrementally by `CPGBuilder`, which uses language-specific `LanguageVisitor` plugins to walk tree-sitter parse trees and emit nodes/edges via a `NodeEmitter` callback.


## Core Data Model

### SourceLocation and SourceRange (`model/location.py`)

```python
@dataclass(frozen=True, slots=True)
class SourceLocation:
    file: Path
    line: int       # 1-based
    column: int = 0 # 0-based

@dataclass(frozen=True, slots=True)
class SourceRange:
    start: SourceLocation
    end: SourceLocation
```

### NodeId (`model/nodes.py`)

```python
@dataclass(frozen=True, slots=True)
class NodeId:
    """Opaque, hashable node identifier. Never construct directly — use CPGBuilder."""
    _value: str

    def __str__(self) -> str:
        return self._value

    def __hash__(self) -> int:
        return hash(self._value)
```

### NodeKind enum (`model/nodes.py`)

```python
class NodeKind(str, Enum):
    MODULE = "module"          # A source file
    CLASS = "class"            # Class/struct/interface definition
    FUNCTION = "function"      # Function/method definition
    PARAMETER = "parameter"    # Function parameter
    VARIABLE = "variable"      # Local variable, global, field
    CALL = "call"              # Function call site
    LITERAL = "literal"        # String/number/boolean literal
    RETURN = "return"          # Return statement
    IMPORT = "import"          # Import statement
    BRANCH = "branch"          # if/switch condition node
    LOOP = "loop"              # for/while loop header
    BLOCK = "block"            # Basic block (group of sequential statements)
```

### CpgNode (`model/nodes.py`)

```python
@dataclass
class CpgNode:
    id: NodeId
    kind: NodeKind
    name: str                              # Human-readable label
    location: SourceLocation | None        # None for synthetic nodes
    scope: NodeId | None = None            # Enclosing function/class/module
    attrs: dict[str, Any] = field(default_factory=dict)
    _tree_node: Any = field(default=None, repr=False, compare=False)  # tree-sitter node, not serialized
```

The `attrs` dict holds language-specific metadata. Common keys by node kind:

| NodeKind   | Common attrs keys                                         |
|------------|-----------------------------------------------------------|
| FUNCTION   | `is_async`, `is_method`, `is_static`, `decorators`        |
| PARAMETER  | `type_annotation`, `position`, `default_value`            |
| VARIABLE   | `type_annotation`, `is_global`, `is_field`                |
| CALL       | `args_count`, `is_method_call`, `receiver`                |
| LITERAL    | `literal_type` (str/int/float/bool/none), `raw_value`     |
| IMPORT     | `module`, `names`, `is_from`, `alias`                     |
| BRANCH     | `branch_type` (if/elif/switch/match), `has_else`          |
| LOOP       | `loop_type` (for/while/do_while), `iterator_var`          |

### EdgeKind enum (`model/edges.py`)

```python
class EdgeKind(str, Enum):
    # AST structure
    CONTAINS = "contains"              # Parent -> child containment
    HAS_PARAMETER = "has_parameter"    # Function -> parameter
    HAS_RETURN_TYPE = "has_return_type"# Function -> return type annotation

    # Control flow
    FLOWS_TO = "flows_to"              # Sequential statement flow
    BRANCHES_TO = "branches_to"        # Conditional/loop branch

    # Data flow
    DATA_FLOWS_TO = "data_flows_to"    # Data flows from source to target
    DEFINED_BY = "defined_by"          # Variable <- its definition
    USED_BY = "used_by"                # Variable -> its usage site

    # Call graph
    CALLS = "calls"                    # Call site -> function definition
    RESOLVES_TO = "resolves_to"        # Dynamic dispatch resolution

    # Module structure
    IMPORTS = "imports"                # Module -> imported module
```

### CpgEdge (`model/edges.py`)

```python
@dataclass(frozen=True, slots=True)
class CpgEdge:
    source: NodeId
    target: NodeId
    kind: EdgeKind
    attrs: dict[str, Any] = field(default_factory=dict)
```

## CodePropertyGraph (`graph/cpg.py`)

The central object. Wraps a `GraphBackend` and provides typed access to the CPG.

```python
class CodePropertyGraph:
    # Node access
    def node(self, node_id: NodeId) -> CpgNode | None
    def nodes(self, kind: NodeKind | None = None, file: Path | None = None) -> Iterator[CpgNode]
    def edges(self, kind: EdgeKind | None = None) -> Iterator[CpgEdge]

    # Graph traversal
    def successors(self, node_id: NodeId, edge_kind: EdgeKind | None = None) -> list[CpgNode]
    def predecessors(self, node_id: NodeId, edge_kind: EdgeKind | None = None) -> list[CpgNode]

    # Scope navigation
    def scope_of(self, node_id: NodeId) -> CpgNode | None
    def children_of(self, node_id: NodeId) -> list[CpgNode]

    # Consumer annotations — arbitrary key/value metadata on nodes
    def annotate_node(self, node_id: NodeId, key: str, value: Any) -> None
    def annotate_edge(self, source: NodeId, target: NodeId, key: str, value: Any) -> None
    def get_annotation(self, node_id: NodeId, key: str) -> Any | None
    def get_edge_annotation(self, source: NodeId, target: NodeId, key: str) -> Any | None
    def annotations_for(self, node_id: NodeId) -> dict[str, Any]

    # Query and analysis entry points
    def query(self) -> GraphQuery
    def taint(self, policy: TaintPolicy) -> TaintResult

    # Serialization — JSON node-link format
    def to_dict(self) -> dict[str, Any]
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodePropertyGraph

    # Stats
    @property
    def node_count(self) -> int
    @property
    def edge_count(self) -> int
    @property
    def files(self) -> list[Path]  # All source files in the graph
```

**Implementation notes:**
- Internally stores a `GraphBackend` (NetworkX initially) plus a `dict[str, CpgNode]` for fast node lookup by ID string
- Annotations stored in a separate `dict[str, dict[str, Any]]` keyed by node ID string, NOT in `CpgNode.attrs`. Consumers must not pollute the structural data.
- Edge annotations stored in a separate `dict[tuple[str, str], dict[str, Any]]` keyed by (source_id_str, target_id_str)
- `to_dict()` serializes annotations alongside nodes under a separate `"annotations"` key, and edge annotations under `"edge_annotations"`
- `from_dict()` must round-trip perfectly: `CPG.from_dict(cpg.to_dict())` produces an equivalent graph
- The `_tree_node` field on `CpgNode` is NOT serialized and is set to `None` after `build()` completes


## CPGBuilder (`graph/builder.py`)

Fluent builder for constructing a CPG from source files. Implements `NodeEmitter` internally.

```python
class CPGBuilder:
    def __init__(self, registry: LanguageRegistry | None = None) -> None
    def add_file(self, path: Path) -> CPGBuilder
    def add_directory(self, path: Path, exclude: list[str] | None = None) -> CPGBuilder
    def add_source(self, source: bytes, filename: str, language: str) -> CPGBuilder
    def build(self) -> CodePropertyGraph
```

**Build pipeline (inside `build()`):**

1. **Parse phase**: For each file, select the language visitor by file extension from the `LanguageRegistry`. Call `visitor.parse(source_bytes, filename)` to get a tree-sitter parse tree. Skip files whose parse tree has `root_node.has_error` (emit a warning).
2. **Visit phase**: For each parsed file, call `visitor.visit(tree, file_path, emitter)`. The visitor walks the tree and calls emitter methods to emit nodes and edges. This produces: AST nodes + CONTAINS/HAS_PARAMETER edges + intra-procedural DFG edges (DEFINED_BY, USED_BY, DATA_FLOWS_TO within a function).
3. **CFG phase**: For each FUNCTION node, construct control flow edges (FLOWS_TO, BRANCHES_TO) between its child statements/blocks. This is language-agnostic — the visitor has already emitted the structural nodes; the builder connects them in statement order, with branches at BRANCH/LOOP nodes.
4. **Call resolution phase**: Call `visitor.resolve_calls(cpg)` for each language visitor to link CALL nodes to FUNCTION nodes with CALLS edges. Resolution is best-effort: unresolved calls remain as orphan CALL nodes (no CALLS edge).
5. **Inter-procedural DFG phase**: Compute function summaries via `compute_summaries(cpg)`. For each call site with a resolved target, propagate DATA_FLOWS_TO edges across the call boundary using the summary (argument N flows to parameter N, return value flows to call site).

**NodeId generation**: The builder generates IDs in the format `"{kind}:{file}:{line}:{col}:{counter}"` where counter disambiguates multiple nodes at the same location. Consumers must treat NodeId as opaque.

**The `exclude` parameter** on `add_directory` supports gitignore-style patterns via `fnmatch`. Default exclusions: `["**/__pycache__", "**/node_modules", "**/.git", "**/venv", "**/.venv"]`.


## GraphBackend Protocol (`graph/backend.py`)

```python
class GraphBackend(Protocol):
    def add_node(self, node_id: str, **attrs: Any) -> None
    def add_edge(self, source: str, target: str, key: str | None = None, **attrs: Any) -> None
    def get_node(self, node_id: str) -> dict[str, Any] | None
    def get_edge(self, source: str, target: str) -> dict[str, Any] | None
    def has_node(self, node_id: str) -> bool
    def has_edge(self, source: str, target: str) -> bool
    def successors(self, node_id: str) -> list[str]
    def predecessors(self, node_id: str) -> list[str]
    def all_nodes(self) -> Iterator[tuple[str, dict[str, Any]]]
    def all_edges(self) -> Iterator[tuple[str, str, dict[str, Any]]]
    def node_count(self) -> int
    def edge_count(self) -> int
    def all_simple_paths(self, source: str, target: str, cutoff: int) -> Iterator[list[str]]
    def descendants(self, node_id: str) -> set[str]
    def ancestors(self, node_id: str) -> set[str]
    def to_dict(self) -> dict[str, Any]
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphBackend
```

**NetworkXBackend implementation notes:**
- Uses `networkx.MultiDiGraph` (NOT `DiGraph`) because multiple edge types can exist between the same node pair (e.g., CONTAINS + DATA_FLOWS_TO).
- Edge kind is stored as the `key` parameter on MultiDiGraph edges.
- `get_edge(source, target)` returns the first edge's attrs if multiple exist. For edge-kind-specific lookup, consumers go through `CodePropertyGraph.edges(kind=...)` which filters appropriately.
- The backend API MUST NOT leak NetworkX types. All return types are Python builtins (`str`, `dict`, `list`, `set`, `tuple`).
- `all_simple_paths` delegates to `nx.all_simple_paths` with cutoff.
- `descendants` delegates to `nx.descendants`.
- `ancestors` delegates to `nx.ancestors`.


## Taint Analysis Engine (`analysis/taint.py`)

The taint engine is generic — it propagates labels through the DFG. What those labels mean is up to the consumer (sanicode uses them for security; other consumers might use them for data lineage, PII tracking, etc.).

### TaintPolicy (consumer-provided)

```python
@dataclass
class TaintPolicy:
    sources: Callable[[CpgNode], TaintLabel | None]   # Returns a label if the node introduces taint, else None
    sinks: Callable[[CpgNode], bool]                   # Is this node a sink?
    sanitizers: Callable[[CpgNode], bool]               # Does this node sanitize taint?
    propagators: list[TaintPropagator] = field(default_factory=list)

@dataclass
class TaintLabel:
    name: str                          # Label name (e.g., "user_input", "env_var")
    origin: NodeId                     # The node that introduced this taint
    attrs: dict[str, Any] = field(default_factory=dict)  # Consumer-defined metadata

@dataclass
class TaintPropagator:
    """Describes how taint flows through a specific function/operation."""
    match: Callable[[CpgNode], bool]   # Does this propagator apply to this node?
    param_to_return: bool = True       # Taint on any param flows to return value?
    param_to_param: dict[int, int] | None = None  # Taint from param N flows to param M
```

### TaintResult

```python
@dataclass
class TaintPath:
    source: CpgNode                    # The taint source node
    sink: CpgNode                      # The sink node
    intermediates: list[CpgNode]       # All nodes on the path, in order (including source and sink)
    labels: frozenset[TaintLabel]      # Which labels reached the sink
    is_sanitized: bool                 # Was a sanitizer on this path?
    sanitizers: list[CpgNode]          # Sanitizer nodes on this path (empty if unsanitized)

@dataclass
class TaintResult:
    paths: list[TaintPath]

    def paths_to_sink(self, sink_id: NodeId) -> list[TaintPath]
    def paths_from_source(self, source_id: NodeId) -> list[TaintPath]
    def unsanitized_paths(self) -> list[TaintPath]
    def sanitized_paths(self) -> list[TaintPath]
    def labels_at(self, node_id: NodeId) -> frozenset[TaintLabel]
```

### Taint algorithm

Worklist-based forward analysis:

1. Initialize worklist with all nodes where `policy.sources(node)` returns a non-None label. Each worklist entry is `(node_id, frozenset_of_labels)`.
2. Maintain a map `labels_at: dict[NodeId, frozenset[TaintLabel]]` tracking which labels have reached each node. Initialize source nodes with their labels.
3. Pop a node from the worklist. For each outgoing DATA_FLOWS_TO edge:
   a. Compute the labels that would propagate (current node's labels).
   b. If the target node matches `policy.sanitizers()`, mark those labels as sanitized (do not drop them — record the sanitizer so the consumer can see it was present, but still propagate to detect over-sanitization issues). Set a flag on the path.
   c. If the target's current label set is already a superset of the propagated labels, skip (fixed point reached). Otherwise, update and add to worklist.
   d. If the target matches `policy.sinks()`, record a `TaintPath`.
4. At CALLS edges: look up the function summary for the callee. Use `param_to_return` mappings to propagate taint from arguments to the call site's result. Use `param_to_param` mappings for output parameters.
5. At nodes matching a `TaintPropagator`, apply the propagator's rules instead of default propagation.
6. The engine should be field-sensitive where feasible: track `obj.field` as a separate taint entity from `obj`. This is a best-effort enhancement — if field tracking is not available for a given code pattern, fall back to object-level taint.

**Termination**: The worklist converges because the label sets at each node can only grow (monotone lattice), and the set of possible labels is finite (bounded by the number of source nodes).


## Function Summaries (`analysis/summary.py`)

```python
@dataclass
class FunctionSummary:
    function_id: NodeId
    function_name: str
    params_to_return: list[int]         # Which parameter positions (0-based) flow to the return value
    params_to_sinks: dict[int, list[NodeId]]  # Which parameters flow to which internal sinks
    introduces_taint: bool              # Does the function introduce new taint (e.g., reads from a file)?

def compute_summaries(cpg: CodePropertyGraph) -> dict[NodeId, FunctionSummary]
```

Summaries are computed by walking intra-procedural DFG edges within each function. For each parameter node, follow DATA_FLOWS_TO edges forward. If a path reaches a RETURN node, that parameter flows to the return value. If a path reaches a known sink, record it in `params_to_sinks`.

Summaries are computed once per `build()` and cached on the `CodePropertyGraph` instance. They enable inter-procedural taint without full function inlining.


## Query API (`query/api.py`)

```python
class GraphQuery:
    def __init__(self, cpg: CodePropertyGraph) -> None

    # Path queries
    def paths_between(self, source: NodeId, target: NodeId, cutoff: int = 10) -> list[list[CpgNode]]
    def reachable_from(self, node_id: NodeId, edge_kinds: frozenset[EdgeKind] | None = None) -> set[CpgNode]
    def reaching(self, node_id: NodeId, edge_kinds: frozenset[EdgeKind] | None = None) -> set[CpgNode]

    # Node lookup
    def node_at(self, file: Path, line: int) -> CpgNode | None
    def nodes_in_file(self, file: Path) -> list[CpgNode]
    def nodes_in_scope(self, scope_id: NodeId) -> list[CpgNode]

    # Subgraph extraction
    def subgraph(self, root: NodeId, edge_kinds: frozenset[EdgeKind] | None = None, max_depth: int = 10) -> CodePropertyGraph

    # Pattern matching
    def match_chain(self, pattern: ChainPattern) -> list[list[CpgNode]]
```

**Implementation notes:**
- `paths_between` delegates to `backend.all_simple_paths` with cutoff, then hydrates NodeId lists into CpgNode lists.
- `reachable_from` delegates to `backend.descendants`, optionally filtering by edge kind. When `edge_kinds` is specified, the traversal only follows edges of those kinds.
- `reaching` delegates to `backend.ancestors`, same edge kind filtering.
- `node_at` scans nodes for matching file + line. If multiple nodes exist at the same location (common — e.g., a call and its arguments), returns the first one by node kind priority: FUNCTION > CALL > VARIABLE > others.
- `subgraph` performs BFS from root up to max_depth, collecting all reached nodes and their interconnecting edges, then constructs a new `CodePropertyGraph` from them.


## Pattern Matching (`query/pattern.py`)

```python
@dataclass
class StepMatcher:
    kind: NodeKind | None = None
    name_pattern: str | None = None       # regex matched against node.name
    annotation_key: str | None = None     # node must have this annotation
    annotation_value: Any = None          # annotation must equal this value
    wildcard: bool = False                # matches 0 or more intermediate nodes

@dataclass
class ChainPattern:
    steps: list[StepMatcher]
    edge_kind: EdgeKind | None = None     # restrict traversal to specific edge type
```

**Match algorithm**: For non-wildcard steps, match must be exact at the next hop. For wildcard steps, perform BFS/DFS up to a configurable depth (default 20) looking for the next non-wildcard step's match. Return all matching chains.

Example — find all paths where a parameter reaches an exec-family call via data flow:
```python
pattern = ChainPattern(
    steps=[
        StepMatcher(kind=NodeKind.PARAMETER),
        StepMatcher(wildcard=True),
        StepMatcher(kind=NodeKind.CALL, name_pattern=r"exec|eval|os\.system"),
    ],
    edge_kind=EdgeKind.DATA_FLOWS_TO,
)
matches = cpg.query().match_chain(pattern)
```


## Language Visitor Protocol (`lang/protocol.py`)

```python
@runtime_checkable
class LanguageVisitor(Protocol):
    @property
    def name(self) -> str: ...          # e.g., "python", "javascript"

    @property
    def extensions(self) -> frozenset[str]: ...  # e.g., frozenset({".py", ".pyi"})

    def parse(self, source: bytes, filename: str) -> Any: ...
    # Returns a tree-sitter Tree object

    def visit(self, tree: Any, file_path: Path, emitter: NodeEmitter) -> None: ...
    # Walk the tree and emit nodes/edges via the emitter

    def resolve_calls(self, cpg: CodePropertyGraph) -> list[tuple[NodeId, NodeId]]: ...
    # Returns list of (call_site_id, function_definition_id) pairs
```

## NodeEmitter Protocol (`lang/protocol.py`)

Implemented by `CPGBuilder` internally. Language visitors call these methods; consumers never interact with `NodeEmitter` directly.

```python
class NodeEmitter(Protocol):
    # Structure
    def emit_module(self, name: str, path: Path) -> NodeId: ...
    def emit_class(self, name: str, location: SourceLocation, scope: NodeId) -> NodeId: ...
    def emit_function(self, name: str, location: SourceLocation, scope: NodeId,
                      params: list[str] | None = None, is_async: bool = False) -> NodeId: ...
    def emit_parameter(self, name: str, location: SourceLocation, function: NodeId,
                       type_annotation: str | None = None, position: int = 0) -> NodeId: ...
    def emit_variable(self, name: str, location: SourceLocation, scope: NodeId) -> NodeId: ...
    def emit_call(self, target_name: str, location: SourceLocation, scope: NodeId,
                  args: list[str] | None = None) -> NodeId: ...
    def emit_literal(self, value: str, literal_type: str, location: SourceLocation,
                     scope: NodeId) -> NodeId: ...
    def emit_return(self, location: SourceLocation, scope: NodeId) -> NodeId: ...
    def emit_import(self, module: str, names: list[str], location: SourceLocation,
                    scope: NodeId, is_from: bool = False) -> NodeId: ...

    # Data flow
    def emit_data_flow(self, source: NodeId, target: NodeId) -> None: ...
    def emit_definition(self, variable: NodeId, defined_by: NodeId) -> None: ...
    def emit_usage(self, variable: NodeId, used_at: NodeId) -> None: ...

    # Control flow
    def emit_control_flow(self, from_node: NodeId, to_node: NodeId) -> None: ...
    def emit_branch(self, from_node: NodeId, true_branch: NodeId,
                    false_branch: NodeId | None = None) -> None: ...
```

Each `emit_*` structure method creates a `CpgNode`, adds it to the backend, creates a `CONTAINS` edge from scope to the new node (except for modules, which have no parent), and returns the `NodeId`. Additional edges (e.g., `HAS_PARAMETER` for `emit_parameter`) are added as appropriate.

The data flow methods (`emit_data_flow`, `emit_definition`, `emit_usage`) add edges of the corresponding `EdgeKind` between existing nodes.


## TreeSitterVisitor Base Class (`lang/base.py`)

Provides common tree-sitter plumbing that language-specific visitors inherit:

```python
class TreeSitterVisitor:
    _language_name: str  # Override in subclass, e.g., "python"

    def parse(self, source: bytes, filename: str) -> tree_sitter.Tree
    def _get_parser(self) -> tree_sitter.Parser  # Lazily creates parser for this language
    def _node_text(self, node: tree_sitter.Node, source: bytes) -> str
    def _location(self, node: tree_sitter.Node, file_path: Path) -> SourceLocation
```

**IMPORTANT tree-sitter API notes (v0.25+):**
- `Language.query(pattern)` is deprecated; use `Query(language, pattern)` constructor
- `Query` objects do NOT have `captures()`/`matches()` methods
- Use `QueryCursor(query)` then `cursor.captures(node)` / `cursor.matches(node)`
- `captures()` returns `dict[str, list[Node]]` (keyed by capture name)
- `matches()` returns `list[tuple[int, dict[str, list[Node]]]]`
- `Node.start_point` returns a `Point` with `.row` and `.column` attributes (0-based)
- Lines in treeloom are 1-based, so always add 1 to `.row`

The `_get_parser` method loads the grammar package dynamically. For Python, this means `import tree_sitter_python` and calling its `language()` function. If the grammar package is not installed, raise an `ImportError` with a clear message: `"tree-sitter-python is required. Install with: pip install treeloom[languages]"`.


## Language Registry (`lang/registry.py`)

```python
class LanguageRegistry:
    def register(self, visitor: LanguageVisitor) -> None
    def get_visitor(self, extension: str) -> LanguageVisitor | None
    def get_visitor_by_name(self, name: str) -> LanguageVisitor | None
    def supported_extensions(self) -> frozenset[str]

    @classmethod
    def default(cls) -> LanguageRegistry
```

`default()` returns a registry with all built-in visitors registered. Visitors whose grammar packages are not installed are silently skipped (they'll fail at parse time if someone tries to use them, with a clear error message).


## Export Formats

### JSON (`export/json.py`)

```python
def to_json(cpg: CodePropertyGraph, indent: int = 2) -> str
def from_json(data: str) -> CodePropertyGraph
```

Uses node-link format. Structure:
```json
{
  "treeloom_version": "0.1.0",
  "nodes": [{"id": "...", "kind": "...", "name": "...", "location": {...}, "scope": "...", "attrs": {...}}],
  "edges": [{"source": "...", "target": "...", "kind": "...", "attrs": {...}}],
  "annotations": {"node_id_str": {"key": "value", ...}},
  "edge_annotations": {"source_id:target_id": {"key": "value", ...}}
}
```

`Path` objects serialize as POSIX strings. `NodeId` objects serialize as their string value. `from_json` must reconstruct all types.

### DOT (`export/dot.py`)

```python
def to_dot(
    cpg: CodePropertyGraph,
    edge_kinds: frozenset[EdgeKind] | None = None,
    node_kinds: frozenset[NodeKind] | None = None,
) -> str
```

Graphviz DOT format. Node shapes by kind:
- MODULE: folder
- CLASS: box3d
- FUNCTION: component
- PARAMETER/VARIABLE: ellipse
- CALL: diamond
- LITERAL: note
- BRANCH/LOOP: hexagon
- BLOCK: rectangle

Edge styles by kind:
- CONTAINS: solid gray
- DATA_FLOWS_TO: bold blue
- FLOWS_TO: solid black
- BRANCHES_TO: dashed red
- CALLS: dotted green

Optional filtering by edge/node kinds reduces output to only those types.

### HTML Visualization (`export/html.py`)

```python
def generate_html(
    cpg: CodePropertyGraph,
    layers: list[VisualizationLayer] | None = None,
    overlays: list[Overlay] | None = None,
    title: str = "Code Property Graph",
) -> str
```

Self-contained HTML using Cytoscape.js (loaded from CDN) + Dagre layout. Features:
- Layer toggles in sidebar (Structure, Call Graph, Data Flow, Control Flow) — each layer corresponds to a `VisualizationLayer` with specific edge/node kind filters
- Overlay toggles (consumer-injected via `Overlay` objects)
- Click node/edge to see detail panel with all attributes and annotations
- Search by node name (filters and highlights)
- Zoom/pan
- Statistics bar showing node/edge counts by kind

Default layers when none provided:
1. Structure: CONTAINS + HAS_PARAMETER edges, all node kinds
2. Data Flow: DATA_FLOWS_TO + DEFINED_BY + USED_BY edges
3. Control Flow: FLOWS_TO + BRANCHES_TO edges
4. Call Graph: CALLS + RESOLVES_TO edges


## Overlay System (`overlay/api.py`)

Overlays let consumers inject visual styling on top of the base graph — sanicode uses this to color security-relevant nodes red/green/yellow without treeloom knowing about security.

```python
@dataclass
class OverlayStyle:
    color: str | None = None           # CSS color
    shape: str | None = None           # Cytoscape node shape
    size: int | None = None            # Node size in pixels
    line_style: str | None = None      # "solid", "dashed", "dotted"
    width: float | None = None         # Edge width
    label: str | None = None           # Tooltip text
    opacity: float | None = None       # 0.0–1.0

@dataclass
class Overlay:
    name: str
    description: str = ""
    default_visible: bool = True
    node_styles: dict[NodeId, OverlayStyle] = field(default_factory=dict)
    edge_styles: dict[tuple[NodeId, NodeId], OverlayStyle] = field(default_factory=dict)

@dataclass
class VisualizationLayer:
    name: str
    edge_kinds: frozenset[EdgeKind] | None = None
    node_kinds: frozenset[NodeKind] | None = None
    default_visible: bool = True
    style: OverlayStyle = field(default_factory=OverlayStyle)
```


## Implementation Order

Build in this order, testing each layer before moving to the next:

### Phase 1: Foundation
1. `model/location.py` — SourceLocation, SourceRange
2. `model/nodes.py` — NodeId, NodeKind, CpgNode
3. `model/edges.py` — EdgeKind, CpgEdge
4. `graph/backend.py` — GraphBackend protocol + NetworkXBackend
5. `graph/cpg.py` — CodePropertyGraph (node/edge access, annotations, serialization)
6. `graph/builder.py` — CPGBuilder skeleton (add_file, add_directory, build shell)

### Phase 2: Language Support
7. `lang/protocol.py` — LanguageVisitor + NodeEmitter protocols
8. `lang/base.py` — TreeSitterVisitor base class
9. `lang/registry.py` — LanguageRegistry
10. `lang/builtin/python.py` — Python visitor (first language, validates the architecture end-to-end)

### Phase 3: Analysis
11. `analysis/summary.py` — FunctionSummary + compute_summaries()
12. `analysis/taint.py` — TaintPolicy, TaintLabel, TaintResult, TaintPath, worklist engine
13. `analysis/reachability.py` — Reachability queries (forward/backward BFS with edge kind filtering)

### Phase 4: Query
14. `query/api.py` — GraphQuery
15. `query/pattern.py` — ChainPattern, StepMatcher, match_chain()

### Phase 5: Export & Visualization
16. `export/json.py` — JSON serialization/deserialization
17. `export/dot.py` — DOT export
18. `export/html.py` — HTML visualization with Cytoscape.js
19. `overlay/api.py` — Overlay, OverlayStyle, VisualizationLayer

### Phase 6: Additional Languages
20. `lang/builtin/javascript.py`
21. `lang/builtin/typescript.py`
22. `lang/builtin/go.py`
23. `lang/builtin/java.py`
24. `lang/builtin/c.py`
25. `lang/builtin/cpp.py`
26. `lang/builtin/rust.py`


## Python Visitor Implementation Guide (`lang/builtin/python.py`)

The Python visitor is the reference implementation. Other language visitors follow the same pattern.

### tree-sitter node types to treeloom node kinds

| tree-sitter node type       | treeloom NodeKind | Notes                                    |
|-----------------------------|-------------------|------------------------------------------|
| `module`                    | MODULE            | Top-level, one per file                  |
| `class_definition`          | CLASS             |                                          |
| `function_definition`       | FUNCTION          | Also handles `async_function_definition` |
| `parameters` children       | PARAMETER         | Each `identifier` child of `parameters`  |
| `assignment` LHS            | VARIABLE          | Also `augmented_assignment`              |
| `call`                      | CALL              | `target_name` from function part of call |
| `string` / `integer` / etc. | LITERAL           |                                          |
| `return_statement`          | RETURN            |                                          |
| `import_statement` / `import_from_statement` | IMPORT |                                    |
| `if_statement`              | BRANCH            |                                          |
| `for_statement` / `while_statement` | LOOP      |                                          |

### Visit strategy

Walk the tree recursively. Maintain a scope stack (initially just the MODULE node). When entering a class or function definition, push a new scope. When leaving, pop.

For each node of interest:
1. Create the CPG node via the emitter
2. For assignments: emit VARIABLE for the LHS, then emit DEFINED_BY from variable to the RHS expression
3. For variable references in expressions: emit USED_BY from the variable's most recent definition to the usage site
4. For function calls: emit CALL node, then for each argument, if it's a variable, emit DATA_FLOWS_TO from the variable to the call's corresponding parameter (this is intra-procedural DFG)
5. For return statements: emit RETURN node, emit DATA_FLOWS_TO from the return expression to the RETURN node

### Call resolution

`resolve_calls` iterates over all CALL nodes in the CPG. For each:
1. Look up the `target_name` attribute
2. Search for FUNCTION nodes with matching `name`
3. Handle qualified names: `module.func` -> look for FUNCTION named `func` inside MODULE named `module`
4. Handle method calls: `obj.method()` -> look for FUNCTION named `method` inside CLASS definitions (best-effort, since we don't do full type inference)
5. Return list of (call_node_id, function_node_id) pairs


## Testing Strategy

### Unit tests for model layer
- NodeId hashing and equality
- CpgNode creation, attrs access
- CpgEdge creation
- SourceLocation ordering
- SourceRange containment checks

### Unit tests for GraphBackend
- add_node / get_node / has_node
- add_edge / get_edge / has_edge (including multiple edges between same pair)
- successors / predecessors
- all_simple_paths
- descendants / ancestors
- to_dict / from_dict round-trip

### Language visitor tests
Parse small fixtures, assert expected nodes and edges. One fixture per concept:
- `tests/fixtures/python/simple_function.py` — function with parameters, assignment, return
- `tests/fixtures/python/class_with_methods.py` — class, __init__, methods
- `tests/fixtures/python/function_calls.py` — direct calls, method calls, chained calls
- `tests/fixtures/python/imports.py` — import, from-import, aliased
- `tests/fixtures/python/control_flow.py` — if/elif/else, for, while
- `tests/fixtures/python/data_flow.py` — assignment chains, parameter-to-sink flow

Use golden-file approach where useful: serialize CPG to JSON, compare against expected JSON. But prefer structural assertions (node count, specific node exists, specific edge exists) over full-graph comparison for most tests.

### Taint engine tests
Hand-build CPGs (no parsing) to test propagation logic in isolation:
- Simple source -> sink (one hop)
- Source -> intermediate -> sink (two hops)
- Source -> sanitizer -> sink (sanitized path)
- Source -> branch -> sink (taint through both branches)
- Source -> call -> function -> sink (inter-procedural via summary)
- Convergence test: two sources reaching same sink

Then integration tests: parse a fixture, build CPG, run taint, check results.

### Query tests
Build small CPGs, exercise each query method. Test edge kind filtering for reachable_from/reaching.

### Export tests
- JSON: `from_json(to_json(cpg))` produces equivalent graph (round-trip)
- DOT: output contains expected `digraph`, node declarations, edge declarations
- HTML: output is valid HTML (contains `<html>`, `<script>`, Cytoscape initialization)

### Contract test
Mimics sanicode's usage pattern end-to-end:
1. `CPGBuilder().add_directory(fixture_dir).build()` -> CPG
2. Walk nodes, annotate some as "entry_point", "sink", "sanitizer"
3. Create a TaintPolicy with those annotations
4. `cpg.taint(policy)` -> TaintResult
5. Assert expected paths found
6. Create Overlay coloring annotated nodes
7. `generate_html(cpg, overlays=[overlay])` -> valid HTML

Test fixtures live in `tests/fixtures/{language}/`. Each fixture is a small, focused source file that exercises one concept.


## Design Principles

1. **No security concepts.** treeloom does not know about CWE, OWASP, NIST, STIG, or any compliance framework. It knows about code structure and data flow. Security classification is the consumer's job.
2. **No network calls.** Everything runs locally. No telemetry, no package downloads at runtime.
3. **Backend-agnostic.** The public API never leaks NetworkX types. All public types are treeloom's own dataclasses and enums. If we swap to rustworkx later, no consumer code changes.
4. **Consumer annotations are separate.** `annotate_node()` stores data in a separate dict, not in `CpgNode.attrs`. This prevents consumers from corrupting structural data and ensures annotations don't interfere with serialization round-trips.
5. **Incremental design.** The builder supports adding files one at a time. The graph can be extended after initial construction by calling `add_file` again and re-running `build()`.
6. **Serialization round-trips.** `from_dict(to_dict())` MUST always produce an equivalent graph. This is a hard requirement — sanicode uses it for caching, persistence, and test fixtures.
7. **Graceful degradation.** Missing grammar packages don't crash — they produce clear error messages. Parse errors in individual files produce warnings, not exceptions. The builder skips broken files and continues.


## Relationship with sanicode

sanicode (`~/Developer/sanicode`) is the primary consumer. The integration contract:

1. sanicode calls `CPGBuilder().add_directory(path).build()` to get a full CPG
2. sanicode walks the CPG nodes and annotates them with security roles using `cpg.annotate_node()`:
   - `annotate_node(node_id, "role", "entry_point")` / `"sink"` / `"sanitizer"` / `"auth_guard"`
   - `annotate_node(node_id, "cwe_id", 89)` for SQL injection sinks
   - `annotate_node(node_id, "domain", "financial")` for domain classification
3. sanicode creates a `TaintPolicy` with callables that check annotations:
   ```python
   policy = TaintPolicy(
       sources=lambda node: TaintLabel("user_input", node.id)
           if cpg.get_annotation(node.id, "role") == "entry_point" else None,
       sinks=lambda node: cpg.get_annotation(node.id, "role") == "sink",
       sanitizers=lambda node: cpg.get_annotation(node.id, "role") == "sanitizer",
   )
   ```
4. sanicode calls `cpg.taint(policy)` to run taint analysis
5. sanicode reads `TaintResult` to generate findings, map to compliance controls, produce reports
6. sanicode creates `Overlay` objects to add security visualization (red for unsanitized sinks, green for sanitized paths, etc.)
7. sanicode can serialize the CPG + annotations to JSON for caching between runs

treeloom MUST NOT import from sanicode. The dependency is strictly one-way: sanicode depends on treeloom.


## Public API Surface (`__init__.py`)

Once implemented, the top-level `__init__.py` should export:

```python
from treeloom.model.location import SourceLocation, SourceRange
from treeloom.model.nodes import NodeId, NodeKind, CpgNode
from treeloom.model.edges import EdgeKind, CpgEdge
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.graph.builder import CPGBuilder
from treeloom.analysis.taint import TaintPolicy, TaintLabel, TaintResult, TaintPath, TaintPropagator
from treeloom.query.api import GraphQuery
from treeloom.query.pattern import ChainPattern, StepMatcher
from treeloom.overlay.api import Overlay, OverlayStyle, VisualizationLayer
from treeloom.export.json import to_json, from_json
from treeloom.export.dot import to_dot
from treeloom.export.html import generate_html
```


## Releasing

The version lives in two files that must stay in sync:
- `src/treeloom/version.py` — `__version__ = "x.y.z"`
- `pyproject.toml` — `version = "x.y.z"`


## Working Rules

- **Track work as issues.** When you encounter a bug, gap, or improvement opportunity that you don't immediately fix, create a GitHub issue for it (`gh issue create --repo rdwj/treeloom`). Check for existing issues first to avoid duplicates. Label with appropriate priority (priority-high/medium/low) and category (bug, enhancement, engine, cli). Add to project board 5.


## Don't Forget

- tree-sitter grammar packages are optional dependencies (in the `[languages]` extra). The core library works without them — you just can't parse files without the appropriate grammar installed.
- `NodeEmitter` is implemented by `CPGBuilder` internally, not by consumers. Visitors call it; the builder implements it.
- Use `MultiDiGraph` not `DiGraph` for the NetworkX backend — multiple edge types between the same node pair is a real case (e.g., a function CONTAINS a call AND DATA_FLOWS_TO it).
- Lines are 1-based in treeloom's API (matching what humans see in editors), even though tree-sitter uses 0-based rows. Always add 1 to `node.start_point.row`.
- The `_tree_node` field on `CpgNode` holds the raw tree-sitter node for language visitors that need it during construction. It is NOT serialized and should be set to `None` after `build()` completes to avoid holding references to the parse tree.
- sanicode's existing `KnowledgeGraph` (in `sanicode/graph/builder.py`) uses a plain `nx.DiGraph` with string node IDs and ad-hoc attributes. treeloom replaces this with a typed, structured model. The migration path is: sanicode creates a CPGBuilder, lets treeloom build the CPG, then annotates the CPG nodes with security metadata that was previously baked into the KnowledgeGraph's node attributes.
- The `attrs` dict on `CpgNode` is for structural/language metadata set by visitors. Consumer metadata goes in annotations. This separation is load-bearing for serialization and for preventing consumers from accidentally breaking the graph structure.
