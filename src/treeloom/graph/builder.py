"""CPGBuilder: incremental construction of a Code Property Graph from source files."""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import time
import warnings
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from treeloom.analysis.summary import compute_summaries
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind

# Callback type for build progress reporting.
# Called with (phase_name: str, detail: str) at phase boundaries.
BuildProgressCallback = Callable[[str, str], None]

logger = logging.getLogger(__name__)

_DEFAULT_EXCLUDES = [
    "**/__pycache__",
    "**/node_modules",
    "**/.git",
    "**/venv",
    "**/.venv",
]


class BuildTimeoutError(Exception):
    """Raised when a build exceeds the configured timeout."""

    def __init__(self, phase: str, elapsed: float, timeout: float) -> None:
        self.phase = phase
        self.elapsed = elapsed
        self.timeout = timeout
        super().__init__(
            f"Build timed out after {elapsed:.1f}s after completing {phase} "
            f"(limit: {timeout:.0f}s)"
        )


class CPGBuilder:
    """Fluent builder for constructing a CodePropertyGraph from source files.

    Implements the NodeEmitter interface internally -- language visitors call
    the ``emit_*`` methods to populate the graph during the visit phase.
    """

    def __init__(
        self,
        registry: Any | None = None,
        progress: BuildProgressCallback | None = None,
        timeout: float | None = None,
        relative_root: Path | None = None,
        include_source: bool = False,
    ) -> None:
        self._registry = registry
        self._cpg = CodePropertyGraph()
        self._counter: int = 0
        self._sources: list[tuple[bytes, str, str | None]] = []
        self._files: list[Path] = []
        self._file_snapshots: dict[str, str] = {}  # POSIX path string -> content SHA-256
        self._progress = progress
        self._timeout = timeout
        self._build_start: float | None = None
        self._relative_root: Path | None = (
            relative_root.resolve() if relative_root is not None else None
        )
        self._include_source = include_source

    @staticmethod
    def _file_hash(path: Path) -> str:
        """SHA-256 hex digest of file contents."""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _report(self, phase: str, detail: str) -> None:
        """Report build progress via callback and logger."""
        logger.debug("%s: %s", phase, detail)
        if self._progress is not None:
            self._progress(phase, detail)

    def _check_timeout(self, phase: str) -> None:
        """Raise BuildTimeoutError if the build has exceeded its timeout."""
        if self._timeout is None or self._build_start is None:
            return
        elapsed = time.monotonic() - self._build_start
        if elapsed >= self._timeout:
            raise BuildTimeoutError(phase, elapsed, self._timeout)

    def _normalize_path(self, path: Path) -> Path:
        """Convert path to relative if relative_root is configured."""
        if self._relative_root is None:
            return path
        try:
            return path.resolve().relative_to(self._relative_root)
        except ValueError:
            # Path is outside the relative root — use as-is
            return path

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

        Pipeline stages (5 phases):
        1. Parse: select visitor by extension, parse source, emit AST nodes
        2. CFG: construct intra-procedural control flow edges
        3. Call resolution: link call sites to definitions
        4. Function summaries: compute intra-procedural data flow summaries
        5. Inter-procedural DFG: propagate data flow across call boundaries
        """
        self._build_start = time.monotonic()
        registry = self._get_registry()

        # Phase 1: Parse
        self._report("Phase 1/5: Parsing", "")
        t0 = time.monotonic()
        queued_files = self._files
        self._files = []
        for file_path in queued_files:
            self._process_file(file_path, registry)

        queued_sources = self._sources
        self._sources = []
        for source_bytes, filename, language in queued_sources:
            self._process_source(source_bytes, filename, language, registry)
        elapsed = time.monotonic() - t0
        self._report(
            "Phase 1/5: Parsing",
            f"done ({elapsed:.1f}s, {len(self._cpg.files)} files, "
            f"{self._cpg.node_count} nodes)",
        )
        self._check_timeout("Phase 1/5: Parsing")

        # Phase 2: CFG — connect statements within each function
        self._report("Phase 2/5: Building control flow graph", "")
        t0 = time.monotonic()
        self._build_cfg()
        func_count = sum(1 for _ in self._cpg.nodes(kind=NodeKind.FUNCTION))
        elapsed = time.monotonic() - t0
        self._report(
            "Phase 2/5: Building control flow graph",
            f"done ({elapsed:.1f}s, {func_count} functions)",
        )
        self._check_timeout("Phase 2/5: Building control flow graph")

        # Phase 3: Call resolution
        if registry is not None:
            self._report("Phase 3/5: Resolving calls", "")
            t0 = time.monotonic()
            call_count_before = sum(
                1 for _ in self._cpg.edges(kind=EdgeKind.CALLS)
            )
            self._resolve_calls(registry)
            calls_resolved = (
                sum(1 for _ in self._cpg.edges(kind=EdgeKind.CALLS))
                - call_count_before
            )
            total_calls = sum(
                1 for _ in self._cpg.nodes(kind=NodeKind.CALL)
            )
            elapsed = time.monotonic() - t0
            self._report(
                "Phase 3/5: Resolving calls",
                f"done ({elapsed:.1f}s, {calls_resolved}/{total_calls} calls resolved)",
            )
            self._check_timeout("Phase 3/5: Resolving calls")
        else:
            self._report("Phase 3/5: Resolving calls", "skipped (no language registry)")

        # Phase 4: Function summaries
        self._report("Phase 4/5: Computing function summaries", "")
        t0 = time.monotonic()
        summaries = compute_summaries(self._cpg)
        elapsed = time.monotonic() - t0
        self._report(
            "Phase 4/5: Computing function summaries",
            f"done ({elapsed:.1f}s, {len(summaries)} summaries)",
        )
        self._check_timeout("Phase 4/5: Computing function summaries")

        # Phase 5: Inter-procedural DFG — propagate data flow across calls
        self._report("Phase 5/5: Building inter-procedural data flow", "")
        t0 = time.monotonic()
        dfg_edges_before = sum(
            1
            for e in self._cpg.edges(kind=EdgeKind.DATA_FLOWS_TO)
            if e.attrs.get("interprocedural")
        )
        self._build_interprocedural_dfg(summaries)
        dfg_edges_after = sum(
            1
            for e in self._cpg.edges(kind=EdgeKind.DATA_FLOWS_TO)
            if e.attrs.get("interprocedural")
        )
        edges_added = dfg_edges_after - dfg_edges_before
        elapsed = time.monotonic() - t0
        self._report(
            "Phase 5/5: Building inter-procedural data flow",
            f"done ({elapsed:.1f}s, {edges_added} edges added)",
        )
        self._check_timeout("Phase 5/5: Building inter-procedural data flow")

        # Clear tree-sitter node references now that build is complete
        for cpg_node in self._cpg._nodes.values():
            cpg_node._tree_node = None

        # Record file snapshots for incremental rebuild
        for file_path in self._cpg.files:
            try:
                posix_key = str(PurePosixPath(file_path))
                abs_path = (
                    self._relative_root / file_path
                    if self._relative_root is not None
                    else file_path
                )
                self._file_snapshots[posix_key] = self._file_hash(abs_path)
            except OSError:
                pass

        return self._cpg

    # -- NodeEmitter implementation -------------------------------------------

    def emit_module(
        self,
        name: str,
        path: Path,
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
    ) -> NodeId:
        """Emit a MODULE node."""
        loc = SourceLocation(file=path, line=1, column=0)
        return self._emit_node(
            NodeKind.MODULE, name, loc, scope=None,
            end_location=end_location, source_text=source_text,
        )

    def emit_class(
        self, name: str, location: SourceLocation, scope: NodeId,
        bases: list[str] | None = None,
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
    ) -> NodeId:
        """Emit a CLASS node contained in the given scope."""
        attrs: dict[str, Any] = {}
        if bases:
            attrs["bases"] = bases
        node_id = self._emit_node(
            NodeKind.CLASS, name, location, scope=scope, attrs=attrs,
            end_location=end_location, source_text=source_text,
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
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
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
            end_location=end_location,
            source_text=source_text,
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
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
    ) -> NodeId:
        """Emit a PARAMETER node with HAS_PARAMETER edge from its function."""
        node_id = self._emit_node(
            NodeKind.PARAMETER,
            name,
            location,
            scope=function,
            attrs={"type_annotation": type_annotation, "position": position},
            end_location=end_location,
            source_text=source_text,
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
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
    ) -> NodeId:
        """Emit a VARIABLE node contained in the given scope."""
        attrs: dict[str, Any] = {}
        if inferred_type is not None:
            attrs["inferred_type"] = inferred_type
        node_id = self._emit_node(
            NodeKind.VARIABLE, name, location, scope=scope, attrs=attrs,
            end_location=end_location, source_text=source_text,
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
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
    ) -> NodeId:
        """Emit a CALL node contained in the given scope."""
        attrs: dict[str, Any] = {"args_count": len(args) if args else 0}
        if receiver_inferred_type is not None:
            attrs["receiver_inferred_type"] = receiver_inferred_type
        node_id = self._emit_node(
            NodeKind.CALL, target_name, location, scope=scope, attrs=attrs,
            end_location=end_location, source_text=source_text,
        )
        self._emit_contains(scope, node_id)
        return node_id

    def emit_literal(
        self,
        value: str,
        literal_type: str,
        location: SourceLocation,
        scope: NodeId,
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
    ) -> NodeId:
        """Emit a LITERAL node contained in the given scope."""
        node_id = self._emit_node(
            NodeKind.LITERAL,
            value,
            location,
            scope=scope,
            attrs={"literal_type": literal_type, "raw_value": value},
            end_location=end_location, source_text=source_text,
        )
        self._emit_contains(scope, node_id)
        return node_id

    def emit_return(
        self,
        location: SourceLocation,
        scope: NodeId,
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
    ) -> NodeId:
        """Emit a RETURN node contained in the given scope."""
        node_id = self._emit_node(
            NodeKind.RETURN, "return", location, scope=scope,
            end_location=end_location, source_text=source_text,
        )
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
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
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
            end_location=end_location,
            source_text=source_text,
        )
        self._emit_contains(scope, node_id)
        return node_id

    def emit_branch_node(
        self,
        branch_type: str,
        location: SourceLocation,
        scope: NodeId,
        has_else: bool = False,
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
    ) -> NodeId:
        """Emit a BRANCH node contained in the given scope."""
        node_id = self._emit_node(
            NodeKind.BRANCH,
            branch_type,
            location,
            scope=scope,
            attrs={"branch_type": branch_type, "has_else": has_else},
            end_location=end_location, source_text=source_text,
        )
        self._emit_contains(scope, node_id)
        return node_id

    def emit_loop_node(
        self,
        loop_type: str,
        location: SourceLocation,
        scope: NodeId,
        iterator_var: str | None = None,
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
    ) -> NodeId:
        """Emit a LOOP node contained in the given scope."""
        node_id = self._emit_node(
            NodeKind.LOOP,
            loop_type,
            location,
            scope=scope,
            attrs={"loop_type": loop_type, "iterator_var": iterator_var},
            end_location=end_location, source_text=source_text,
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

    def emit_data_flow(self, source: NodeId, target: NodeId, **attrs: Any) -> None:
        """Emit a DATA_FLOWS_TO edge.

        Keyword arguments become edge attrs.  Pass ``field_name=<str>`` to
        record that the edge represents an attribute access, enabling
        field-sensitive taint propagation.
        """
        self._cpg.add_edge(CpgEdge(
            source=source, target=target, kind=EdgeKind.DATA_FLOWS_TO,
            attrs=dict(attrs) if attrs else {},
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
        end_location: SourceLocation | None = None,
        source_text: str | None = None,
    ) -> NodeId:
        """Create a CpgNode, add it to the CPG, and return its ID."""
        node_id = self._next_id(kind, location)
        final_attrs = dict(attrs) if attrs else {}
        if source_text is not None and self._include_source:
            final_attrs["source_text"] = source_text
        cpg_node = CpgNode(
            id=node_id,
            kind=kind,
            name=name,
            location=location,
            end_location=end_location,
            scope=scope,
            attrs=final_attrs,
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

    def _build_interprocedural_dfg(self, summaries: dict[NodeId, Any]) -> None:
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

        *summaries* is a pre-computed mapping of function NodeId to
        FunctionSummary, produced by ``compute_summaries()`` in Phase 4.
        """
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
                            attrs={"interprocedural": True},
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
                                attrs={"interprocedural": True},
                            )
                        )

    # -- Incremental rebuild --------------------------------------------------

    def rebuild(
        self,
        changed: list[Path] | None = None,
    ) -> CodePropertyGraph:
        """Incrementally update the CPG for changed source files.

        If *changed* is provided, only those files are re-parsed.
        Otherwise, all previously tracked files are checked for changes
        by comparing SHA-256 content hashes.

        Annotations on nodes from unchanged files are preserved.
        Annotations on nodes from changed files are invalidated.

        Returns the same CodePropertyGraph instance, updated in place.
        """
        self._build_start = time.monotonic()
        registry = self._get_registry()

        # Determine which files changed
        if changed is not None:
            changed_paths = [
                p.resolve() if not p.is_absolute() else p for p in changed
            ]
        else:
            changed_paths = self._detect_changed_files()

        if not changed_paths and not self._files and not self._sources:
            return self._cpg

        # Collect POSIX keys for changed files
        changed_posix: set[str] = set()

        # Purge nodes/edges from changed files
        for file_path in changed_paths:
            changed_posix.add(str(PurePosixPath(file_path)))
            self._purge_file(file_path)

        # Drain any newly queued files/sources before purging cross-file edges
        new_files = list(self._files)
        new_sources = list(self._sources)
        self._files = []
        self._sources = []

        for f in new_files:
            changed_posix.add(str(PurePosixPath(f)))

        # Purge cross-file edges (CALLS + inter-procedural DFG)
        self._purge_cross_file_edges()

        # Re-parse changed files (if they still exist)
        t0 = time.monotonic()
        for file_path in changed_paths:
            if file_path.exists():
                self._process_file(file_path, registry)

        # Parse new files
        for file_path in new_files:
            self._process_file(file_path, registry)

        for source_bytes, filename, language in new_sources:
            self._process_source(source_bytes, filename, language, registry)
        elapsed = time.monotonic() - t0
        file_count = len(changed_paths) + len(new_files) + len(new_sources)
        self._report("Parse", f"done ({elapsed:.1f}s, {file_count} files re-parsed)")
        self._check_timeout("Parse")

        # Rebuild CFG for changed/new files only
        t0 = time.monotonic()
        self._build_cfg_for_files(changed_posix)
        elapsed = time.monotonic() - t0
        self._report("CFG", f"done ({elapsed:.1f}s, {len(changed_posix)} files)")
        self._check_timeout("CFG")

        # Re-run call resolution globally (conservative)
        if registry is not None:
            t0 = time.monotonic()
            call_count_before = sum(
                1 for _ in self._cpg.edges(kind=EdgeKind.CALLS)
            )
            self._resolve_calls(registry)
            calls_resolved = (
                sum(1 for _ in self._cpg.edges(kind=EdgeKind.CALLS))
                - call_count_before
            )
            total_calls = sum(
                1 for _ in self._cpg.nodes(kind=NodeKind.CALL)
            )
            elapsed = time.monotonic() - t0
            self._report(
                "Call resolution",
                f"done ({elapsed:.1f}s, {calls_resolved}/{total_calls} calls resolved)",
            )
            self._check_timeout("Call resolution")

        # Re-compute function summaries
        t0 = time.monotonic()
        summaries = compute_summaries(self._cpg)
        elapsed = time.monotonic() - t0
        self._report(
            "Function summaries",
            f"done ({elapsed:.1f}s, {len(summaries)} summaries)",
        )
        self._check_timeout("Function summaries")

        # Re-run inter-procedural DFG globally
        t0 = time.monotonic()
        self._build_interprocedural_dfg(summaries)
        elapsed = time.monotonic() - t0
        self._report("Inter-procedural DFG", f"done ({elapsed:.1f}s)")
        self._check_timeout("Inter-procedural DFG")

        # Clear tree-sitter references on new nodes
        for cpg_node in self._cpg._nodes.values():
            cpg_node._tree_node = None

        # Update file snapshots
        for file_path in self._cpg.files:
            try:
                posix_key = str(PurePosixPath(file_path))
                self._file_snapshots[posix_key] = self._file_hash(file_path)
            except OSError:
                pass

        return self._cpg

    def _detect_changed_files(self) -> list[Path]:
        """Compare stored hashes to current file contents and return changed files."""
        changed: list[Path] = []
        for posix_key, old_hash in list(self._file_snapshots.items()):
            file_path = Path(posix_key)
            if not file_path.exists():
                changed.append(file_path)  # deleted
                continue
            try:
                current_hash = self._file_hash(file_path)
                if current_hash != old_hash:
                    changed.append(file_path)
            except OSError:
                changed.append(file_path)
        return changed

    def _purge_file(self, file_path: Path) -> None:
        """Remove all nodes (and their adjacent edges) originating from a file."""
        for node_id in self._cpg.nodes_for_file(file_path):
            self._cpg.remove_node(node_id)
        posix_key = str(PurePosixPath(file_path))
        self._file_snapshots.pop(posix_key, None)

    def _purge_cross_file_edges(self) -> None:
        """Remove all CALLS edges and inter-procedural DATA_FLOWS_TO edges.

        These are rebuilt globally during call resolution and inter-procedural
        DFG phases, so they must be cleared before re-running those phases.
        """
        to_remove: list[tuple[NodeId, NodeId, EdgeKind]] = []
        for edge in self._cpg.edges(kind=EdgeKind.CALLS):
            to_remove.append((edge.source, edge.target, edge.kind))
        for edge in self._cpg.edges(kind=EdgeKind.DATA_FLOWS_TO):
            if edge.attrs.get("interprocedural"):
                to_remove.append((edge.source, edge.target, edge.kind))
        for source, target, kind in to_remove:
            self._cpg.remove_edge(source, target, kind)

    def _build_cfg_for_files(self, changed_files: set[str]) -> None:
        """Build CFG edges for functions in the changed files only."""
        for func in self._cpg.nodes(kind=NodeKind.FUNCTION):
            if func.location is None:
                continue
            file_key = str(PurePosixPath(func.location.file))
            if file_key not in changed_files:
                continue

            children = self._cpg.children_of(func.id)
            if not children:
                continue

            located = [
                (c, c.location) for c in children if c.location is not None
            ]
            located.sort(key=lambda x: (x[1].line, x[1].column))
            sorted_children = [c for c, _ in located]

            for i in range(len(sorted_children) - 1):
                current = sorted_children[i]
                next_node = sorted_children[i + 1]
                if current.kind == NodeKind.RETURN:
                    continue
                self._cpg.add_edge(CpgEdge(
                    source=current.id,
                    target=next_node.id,
                    kind=EdgeKind.FLOWS_TO,
                ))

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
                first_body = bc_located[0][0]
                self._cpg.add_edge(CpgEdge(
                    source=child.id,
                    target=first_body.id,
                    kind=EdgeKind.BRANCHES_TO,
                ))
                if child.kind == NodeKind.LOOP:
                    last_body = bc_located[-1][0]
                    if last_body.kind != NodeKind.RETURN:
                        self._cpg.add_edge(CpgEdge(
                            source=last_body.id,
                            target=child.id,
                            kind=EdgeKind.FLOWS_TO,
                        ))

    def _resolve_calls(self, registry: Any) -> None:
        """Run call resolution for all registered visitors.

        CALL nodes are partitioned by file extension so each visitor only
        resolves calls from its own language (preventing duplicates and
        applying language-specific disambiguation).

        FUNCTION nodes are collected in a single scan.  Each visitor
        receives the full function list so cross-language resolution
        still works (e.g. TypeScript importing JavaScript modules).
        """
        # Single scan: collect all FUNCTION and CALL nodes once upfront.
        # Each visitor receives the full function list so cross-language
        # calls can resolve (e.g. TypeScript importing JavaScript modules).
        all_functions = list(self._cpg.nodes(kind=NodeKind.FUNCTION))

        # Partition CALL nodes by file extension — each call is resolved
        # by exactly one visitor (the one that owns the call's language).
        calls_by_ext: dict[str, list[CpgNode]] = {}
        for n in self._cpg.nodes(kind=NodeKind.CALL):
            if n.location is not None:
                ext = n.location.file.suffix
                calls_by_ext.setdefault(ext, []).append(n)

        seen: set[str] = set()
        for ext in registry.supported_extensions():
            visitor = registry.get_visitor(ext)
            if visitor is None or visitor.name in seen:
                continue
            seen.add(visitor.name)

            # Collect only this visitor's CALL nodes
            visitor_calls: list[CpgNode] = []
            for v_ext in visitor.extensions:
                visitor_calls.extend(calls_by_ext.get(v_ext, []))

            if not visitor_calls:
                continue  # Nothing to resolve for this language

            try:
                visitor.resolve_calls(
                    self._cpg,
                    function_nodes=all_functions,
                    call_nodes=visitor_calls,
                )
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

        self._parse_and_visit(source_bytes, self._normalize_path(file_path), visitor)

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

        self._parse_and_visit(source, self._normalize_path(Path(filename)), visitor)

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
