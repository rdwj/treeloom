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
        3. CFG: construct control flow edges (stub -- Phase 2)
        4. Call resolution: link call sites to definitions (stub -- Phase 2)
        5. Inter-procedural DFG: propagate data flow across calls (stub -- Phase 3)
        """
        registry = self._get_registry()

        # Process queued files
        for file_path in self._files:
            self._process_file(file_path, registry)

        # Process queued raw sources
        for source_bytes, filename, language in self._sources:
            self._process_source(source_bytes, filename, language, registry)

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
        self, name: str, location: SourceLocation, scope: NodeId
    ) -> NodeId:
        """Emit a CLASS node contained in the given scope."""
        node_id = self._emit_node(NodeKind.CLASS, name, location, scope=scope)
        self._emit_contains(scope, node_id)
        return node_id

    def emit_function(
        self,
        name: str,
        location: SourceLocation,
        scope: NodeId,
        params: list[str] | None = None,
        is_async: bool = False,
    ) -> NodeId:
        """Emit a FUNCTION node contained in the given scope."""
        node_id = self._emit_node(
            NodeKind.FUNCTION,
            name,
            location,
            scope=scope,
            attrs={"is_async": is_async},
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
        self, name: str, location: SourceLocation, scope: NodeId
    ) -> NodeId:
        """Emit a VARIABLE node contained in the given scope."""
        node_id = self._emit_node(NodeKind.VARIABLE, name, location, scope=scope)
        self._emit_contains(scope, node_id)
        return node_id

    def emit_call(
        self,
        target_name: str,
        location: SourceLocation,
        scope: NodeId,
        args: list[str] | None = None,
    ) -> NodeId:
        """Emit a CALL node contained in the given scope."""
        node_id = self._emit_node(
            NodeKind.CALL,
            target_name,
            location,
            scope=scope,
            attrs={"args_count": len(args) if args else 0},
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
    ) -> NodeId:
        """Emit an IMPORT node contained in the given scope."""
        display = f"from {module}" if is_from else f"import {module}"
        node_id = self._emit_node(
            NodeKind.IMPORT,
            display,
            location,
            scope=scope,
            attrs={"module": module, "names": names, "is_from": is_from},
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
