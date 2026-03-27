"""CPGBuilder: incremental construction of a Code Property Graph from source files."""

from __future__ import annotations

import fnmatch
import logging
import warnings
from pathlib import Path
from typing import Any

from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind

logger = logging.getLogger(__name__)

_DEFAULT_EXCLUDES = [
    "**/__pycache__",
    "**/node_modules",
    "**/.git",
    "**/venv",
    "**/.venv",
]


class CPGBuilder:
    """Fluent builder for constructing a CodePropertyGraph from source files.

    Implements the NodeEmitter interface internally -- language visitors call
    the ``emit_*`` methods to populate the graph during the visit phase.
    """

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry
        self._cpg = CodePropertyGraph()
        self._counter: int = 0
        self._sources: list[tuple[bytes, str, str | None]] = []
        self._files: list[Path] = []

    # -- Fluent configuration -------------------------------------------------

    def add_file(self, path: Path) -> CPGBuilder:
        """Queue a single source file for processing."""
        self._files.append(path)
        return self

    def add_directory(
        self, path: Path, exclude: list[str] | None = None
    ) -> CPGBuilder:
        """Queue all source files under a directory.

        Files matching any pattern in ``exclude`` (gitignore-style) are skipped.
        Default exclusions: __pycache__, node_modules, .git, venv, .venv.
        """
        patterns = _DEFAULT_EXCLUDES + (exclude or [])
        for child in sorted(path.rglob("*")):
            if not child.is_file():
                continue
            if _matches_any(child, path, patterns):
                continue
            self._files.append(child)
        return self

    def add_source(
        self, source: bytes, filename: str, language: str | None = None
    ) -> CPGBuilder:
        """Queue raw source bytes for processing."""
        self._sources.append((source, filename, language))
        return self

    # -- Build ----------------------------------------------------------------

    def build(self) -> CodePropertyGraph:
        """Execute the build pipeline and return the constructed CPG.

        Pipeline stages:
        1. Parse: select visitor by extension, parse source
        2. Visit: visitor walks parse tree, emits nodes/edges via emitter
        3. CFG: construct intra-procedural control flow edges
        4. Call resolution: link call sites to definitions
        5. Inter-procedural DFG: propagate data flow across calls (Phase 3)
        """
        registry = self._get_registry()

        # Process queued files
        for file_path in self._files:
            self._process_file(file_path, registry)

        # Process queued raw sources
        for source_bytes, filename, language in self._sources:
            self._process_source(source_bytes, filename, language, registry)

        # Phase 3: CFG — connect statements within each function
        self._build_cfg()

        # Call resolution: let each visitor link CALL nodes to FUNCTION defs
        if registry is not None:
            self._resolve_calls(registry)

        # Phase 5: Inter-procedural DFG — propagate data flow across calls
        self._build_interprocedural_dfg()

        # Clear tree-sitter node references now that build is complete
        for cpg_node in self._cpg._nodes.values():
            cpg_node._tree_node = None

        return self._cpg

    # -- NodeEmitter implementation -------------------------------------------

    def emit_module(self, name: str, path: Path) -> NodeId:
        """Emit a MODULE node."""
        loc = SourceLocation(file=path, line=1, column=0)
        return self._emit_node(NodeKind.MODULE, name, loc, scope=None)

    def emit_class(
        self, name: str, location: SourceLocation, scope: NodeId,
        bases: list[str] | None = None,
    ) -> NodeId:
        """Emit a CLASS node contained in the given scope."""
        attrs: dict[str, Any] = {}
        if bases:
            attrs["bases"] = bases
        node_id = self._emit_node(
            NodeKind.CLASS, name, location, scope=scope, attrs=attrs,
        )
        self._emit_contains(scope, node_id)
        return node_id

    def emit_function(
        self,
        name: str,
        location: SourceLocation,
        scope: NodeId,
        params: list[str] | None = None,
        is_async: bool = False,
        decorators: list[str] | None = None,
    ) -> NodeId:
        """Emit a FUNCTION node contained in the given scope."""
        attrs: dict[str, Any] = {"is_async": is_async}
        if decorators:
            attrs["decorators"] = decorators
        node_id = self._emit_node(
            NodeKind.FUNCTION,
            name,
            location,
            scope=scope,
            attrs=attrs,
        )
        self._emit_contains(scope, node_id)

        if params:
            for i, param_name in enumerate(params):
                self.emit_parameter(
                    param_name,
                    SourceLocation(file=location.file, line=location.line, column=location.column),
                    node_id,
                    position=i,
                )

        return node_id

    def emit_parameter(
        self,
        name: str,
        location: SourceLocation,
        function: NodeId,
        type_annotation: str | None = None,
        position: int = 0,
    ) -> NodeId:
        """Emit a PARAMETER node with HAS_PARAMETER edge from its function."""
        node_id = self._emit_node(
            NodeKind.PARAMETER,
            name,
            location,
            scope=function,
            attrs={"type_annotation": type_annotation, "position": position},
        )
        self._cpg.add_edge(CpgEdge(
            source=function,
            target=node_id,
            kind=EdgeKind.HAS_PARAMETER,
        ))
        return node_id

    def emit_variable(
        self, name: str, location: SourceLocation, scope: NodeId,
        inferred_type: str | None = None,
    ) -> NodeId:
        """Emit a VARIABLE node contained in the given scope."""
        attrs: dict[str, Any] = {}
        if inferred_type is not None:
            attrs["inferred_type"] = inferred_type
        node_id = self._emit_node(
            NodeKind.VARIABLE, name, location, scope=scope, attrs=attrs,
        )
        self._emit_contains(scope, node_id)
        return node_id

    def emit_call(
        self,
        target_name: str,
        location: SourceLocation,
        scope: NodeId,
        args: list[str] | None = None,
        receiver_inferred_type: str | None = None,
    ) -> NodeId:
        """Emit a CALL node contained in the given scope."""
        attrs: dict[str, Any] = {"args_count": len(args) if args else 0}
        if receiver_inferred_type is not None:
            attrs["receiver_inferred_type"] = receiver_inferred_type
        node_id = self._emit_node(
            NodeKind.CALL, target_name, location, scope=scope, attrs=attrs,
        )
        self._emit_contains(scope, node_id)
        return node_id

    def emit_literal(
        self,
        value: str,
        literal_type: str,
        location: SourceLocation,
        scope: NodeId,
    ) -> NodeId:
        """Emit a LITERAL node contained in the given scope."""
        node_id = self._emit_node(
            NodeKind.LITERAL,
            value,
            location,
            scope=scope,
            attrs={"literal_type": literal_type, "raw_value": value},
        )
        self._emit_contains(scope, node_id)
        return node_id

    def emit_return(self, location: SourceLocation, scope: NodeId) -> NodeId:
        """Emit a RETURN node contained in the given scope."""
        node_id = self._emit_node(NodeKind.RETURN, "return", location, scope=scope)
        self._emit_contains(scope, node_id)
        return node_id

    def emit_import(
        self,
        module: str,
        names: list[str],
        location: SourceLocation,
        scope: NodeId,
        is_from: bool = False,
        aliases: dict[str, str] | None = None,
    ) -> NodeId:
        """Emit an IMPORT node contained in the given scope.

        ``aliases`` maps original name to local alias, e.g.
        ``{"sys": "system"}`` for ``import sys as system``.
        """
        display = f"from {module}" if is_from else f"import {module}"
        attrs: dict[str, Any] = {"module": module, "names": names, "is_from": is_from}
        if aliases:
            attrs["aliases"] = aliases
        node_id = self._emit_node(
            NodeKind.IMPORT,
            display,
            location,
            scope=scope,
            attrs=attrs,
        )
        self._emit_contains(scope, node_id)
        return node_id

    def emit_branch_node(
        self,
        branch_type: str,
        location: SourceLocation,
        scope: NodeId,
        has_else: bool = False,
    ) -> NodeId:
        """Emit a BRANCH node contained in the given scope."""
        node_id = self._emit_node(
            NodeKind.BRANCH,
            branch_type,
            location,
            scope=scope,
            attrs={"branch_type": branch_type, "has_else": has_else},
        )
        self._emit_contains(scope, node_id)
        return node_id

    def emit_loop_node(
        self,
        loop_type: str,
        location: SourceLocation,
        scope: NodeId,
        iterator_var: str | None = None,
    ) -> NodeId:
        """Emit a LOOP node contained in the given scope."""
        node_id = self._emit_node(
            NodeKind.LOOP,
            loop_type,
            location,
            scope=scope,
            attrs={"loop_type": loop_type, "iterator_var": iterator_var},
        )
        self._emit_contains(scope, node_id)
        return node_id

    def emit_branch(
        self,
        from_node: NodeId,
        true_branch: NodeId,
        false_branch: NodeId | None = None,
    ) -> None:
        """Emit BRANCHES_TO edges for a conditional."""
        self._cpg.add_edge(CpgEdge(
            source=from_node, target=true_branch, kind=EdgeKind.BRANCHES_TO
        ))
        if false_branch is not None:
            self._cpg.add_edge(CpgEdge(
                source=from_node, target=false_branch, kind=EdgeKind.BRANCHES_TO
            ))

    def emit_control_flow(self, from_node: NodeId, to_node: NodeId) -> None:
        """Emit a FLOWS_TO edge between two nodes."""
        self._cpg.add_edge(CpgEdge(
            source=from_node, target=to_node, kind=EdgeKind.FLOWS_TO
        ))

    def emit_data_flow(self, source: NodeId, target: NodeId) -> None:
        """Emit a DATA_FLOWS_TO edge."""
        self._cpg.add_edge(CpgEdge(
            source=source, target=target, kind=EdgeKind.DATA_FLOWS_TO
        ))

    def emit_definition(self, variable: NodeId, defined_by: NodeId) -> None:
        """Emit a DEFINED_BY edge from variable to its defining expression."""
        self._cpg.add_edge(CpgEdge(
            source=variable, target=defined_by, kind=EdgeKind.DEFINED_BY
        ))

    def emit_usage(self, variable: NodeId, used_at: NodeId) -> None:
        """Emit a USED_BY edge from variable to its usage site."""
        self._cpg.add_edge(CpgEdge(
            source=variable, target=used_at, kind=EdgeKind.USED_BY
        ))

    # -- Internal helpers -----------------------------------------------------

    def _next_id(self, kind: NodeKind, location: SourceLocation | None) -> NodeId:
        """Generate a unique NodeId."""
        self._counter += 1
        if location is not None:
            file_str = str(location.file)
            return NodeId(
                f"{kind.value}:{file_str}:{location.line}:{location.column}:{self._counter}"
            )
        return NodeId(f"{kind.value}::::{self._counter}")

    def _emit_node(
        self,
        kind: NodeKind,
        name: str,
        location: SourceLocation | None,
        scope: NodeId | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> NodeId:
        """Create a CpgNode, add it to the CPG, and return its ID."""
        node_id = self._next_id(kind, location)
        cpg_node = CpgNode(
            id=node_id,
            kind=kind,
            name=name,
            location=location,
            scope=scope,
            attrs=attrs or {},
        )
        self._cpg.add_node(cpg_node)
        return node_id

    def _emit_contains(self, parent: NodeId, child: NodeId) -> None:
        """Add a CONTAINS edge from parent to child."""
        self._cpg.add_edge(CpgEdge(
            source=parent, target=child, kind=EdgeKind.CONTAINS
        ))

    def _build_cfg(self) -> None:
        """Build intra-procedural control flow edges for each function.

        For every FUNCTION node, sorts its direct children by source location
        and connects them with FLOWS_TO edges (sequential flow) and BRANCHES_TO
        edges (branch/loop entry). RETURN nodes have no outgoing FLOWS_TO. LOOP
        nodes get a back-edge from the last body statement.
        """
        for func in self._cpg.nodes(kind=NodeKind.FUNCTION):
            children = self._cpg.children_of(func.id)
            if not children:
                continue

            # Sort by source location (line, then column); skip locationless nodes
            located = [
                (c, c.location) for c in children if c.location is not None
            ]
            located.sort(key=lambda x: (x[1].line, x[1].column))
            sorted_children = [c for c, _ in located]

            # Sequential FLOWS_TO between adjacent children
            for i in range(len(sorted_children) - 1):
                current = sorted_children[i]
                next_node = sorted_children[i + 1]

                # RETURN terminates flow — no outgoing FLOWS_TO
                if current.kind == NodeKind.RETURN:
                    continue

                self._cpg.add_edge(CpgEdge(
                    source=current.id,
                    target=next_node.id,
                    kind=EdgeKind.FLOWS_TO,
                ))

            # BRANCHES_TO from BRANCH/LOOP nodes into their bodies,
            # and back-edges for loops
            for child in sorted_children:
                if child.kind not in (NodeKind.BRANCH, NodeKind.LOOP):
                    continue

                body_children = self._cpg.children_of(child.id)
                if not body_children:
                    continue

                bc_located = [
                    (bc, bc.location)
                    for bc in body_children
                    if bc.location is not None
                ]
                bc_located.sort(key=lambda x: (x[1].line, x[1].column))
                if not bc_located:
                    continue

                # Entry edge into the body
                first_body = bc_located[0][0]
                self._cpg.add_edge(CpgEdge(
                    source=child.id,
                    target=first_body.id,
                    kind=EdgeKind.BRANCHES_TO,
                ))

                # Loop back-edge: last body statement -> loop header
                if child.kind == NodeKind.LOOP:
                    last_body = bc_located[-1][0]
                    if last_body.kind != NodeKind.RETURN:
                        self._cpg.add_edge(CpgEdge(
                            source=last_body.id,
                            target=child.id,
                            kind=EdgeKind.FLOWS_TO,
                        ))

    def _build_interprocedural_dfg(self) -> None:
        """Create DATA_FLOWS_TO edges across call boundaries.

        For each CALLS edge (call_site -> function_def):
        1. Match argument sources at the call site to callee parameters by
           position, creating DATA_FLOWS_TO edges from each argument to the
           corresponding parameter.
        2. Wire return values back: if the callee has RETURN nodes with
           incoming data flow, connect those sources to the call node so the
           return value propagates to the caller.

        Argument-to-parameter matching is position-based, using source
        location to order the argument nodes. This is a v1 simplification;
        keyword arguments and receiver objects (self) are not handled.
        """
        from treeloom.analysis.summary import compute_summaries

        summaries = compute_summaries(self._cpg)

        for edge in list(self._cpg.edges(kind=EdgeKind.CALLS)):
            call_node = self._cpg.node(edge.source)
            func_node = self._cpg.node(edge.target)
            if call_node is None or func_node is None:
                continue

            # Get the callee's parameters sorted by position
            params = [
                n
                for n in self._cpg.successors(
                    func_node.id, edge_kind=EdgeKind.HAS_PARAMETER
                )
                if n.kind == NodeKind.PARAMETER
            ]
            params.sort(key=lambda p: p.attrs.get("position", 0))

            # Get nodes whose data flows into this call (the arguments).
            # Sort by source location so positional matching works.
            arg_sources = self._cpg.predecessors(
                call_node.id, edge_kind=EdgeKind.DATA_FLOWS_TO
            )
            arg_sources.sort(
                key=lambda n: (
                    n.location.line if n.location else 0,
                    n.location.column if n.location else 0,
                )
            )

            # Match arguments to parameters by position
            for i, param in enumerate(params):
                if i < len(arg_sources):
                    self._cpg.add_edge(
                        CpgEdge(
                            source=arg_sources[i].id,
                            target=param.id,
                            kind=EdgeKind.DATA_FLOWS_TO,
                        )
                    )

            # Wire return values back to the call site.
            # If the function summary shows any parameter flows to return,
            # find RETURN nodes and connect their incoming data to the call.
            summary = summaries.get(func_node.id)
            if summary and summary.params_to_return:
                return_nodes = [
                    n
                    for n in self._cpg.children_of(func_node.id)
                    if n.kind == NodeKind.RETURN
                ]
                for ret in return_nodes:
                    ret_sources = self._cpg.predecessors(
                        ret.id, edge_kind=EdgeKind.DATA_FLOWS_TO
                    )
                    for src in ret_sources:
                        self._cpg.add_edge(
                            CpgEdge(
                                source=src.id,
                                target=call_node.id,
                                kind=EdgeKind.DATA_FLOWS_TO,
                            )
                        )

    def _resolve_calls(self, registry: Any) -> None:
        """Run call resolution for all registered visitors."""
        seen: set[str] = set()
        for ext in registry.supported_extensions():
            visitor = registry.get_visitor(ext)
            if visitor is None or visitor.name in seen:
                continue
            seen.add(visitor.name)
            try:
                visitor.resolve_calls(self._cpg)
            except Exception as e:
                warnings.warn(
                    f"Call resolution failed for {visitor.name}: {e}",
                    stacklevel=2,
                )

    def _get_registry(self) -> Any:
        """Return the language registry, lazily creating the default if needed."""
        if self._registry is not None:
            return self._registry
        try:
            from treeloom.lang.registry import LanguageRegistry

            self._registry = LanguageRegistry.default()
        except ImportError:
            self._registry = None
        return self._registry

    def _process_file(self, file_path: Path, registry: Any) -> None:
        """Parse and visit a single file."""
        if registry is None:
            warnings.warn(
                f"No language registry available; skipping {file_path}",
                stacklevel=2,
            )
            return

        ext = file_path.suffix
        visitor = registry.get_visitor(ext)
        if visitor is None:
            logger.debug("No visitor for extension %s, skipping %s", ext, file_path)
            return

        try:
            source_bytes = file_path.read_bytes()
        except OSError as e:
            warnings.warn(f"Cannot read {file_path}: {e}", stacklevel=2)
            return

        self._parse_and_visit(source_bytes, file_path, visitor)

    def _process_source(
        self, source: bytes, filename: str, language: str | None, registry: Any
    ) -> None:
        """Parse and visit raw source bytes."""
        if registry is None:
            warnings.warn(
                "No language registry available; cannot process inline source",
                stacklevel=2,
            )
            return

        visitor = None
        if language is not None:
            visitor = registry.get_visitor_by_name(language)
        if visitor is None:
            ext = Path(filename).suffix
            visitor = registry.get_visitor(ext) if registry else None
        if visitor is None:
            logger.debug("No visitor for %s (language=%s), skipping", filename, language)
            return

        self._parse_and_visit(source, Path(filename), visitor)

    def _parse_and_visit(self, source: bytes, file_path: Path, visitor: Any) -> None:
        """Run the parse and visit phases for one file."""
        try:
            tree = visitor.parse(source, str(file_path))
        except Exception as e:
            warnings.warn(f"Parse error for {file_path}: {e}", stacklevel=2)
            return

        if hasattr(tree, "root_node") and hasattr(tree.root_node, "has_error"):
            if tree.root_node.has_error:
                warnings.warn(
                    f"Parse tree has errors for {file_path}, skipping",
                    stacklevel=2,
                )
                return

        try:
            visitor.visit(tree, file_path, self)
        except Exception as e:
            warnings.warn(f"Visit error for {file_path}: {e}", stacklevel=2)


def _matches_any(path: Path, root: Path, patterns: list[str]) -> bool:
    """Check if a file path matches any of the exclusion patterns."""
    rel = str(path.relative_to(root))
    for pattern in patterns:
        if fnmatch.fnmatch(rel, pattern):
            return True
        # Also check each path component
        for part in path.parts:
            if fnmatch.fnmatch(part, pattern.replace("**/", "")):
                return True
    return False
