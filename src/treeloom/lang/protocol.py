"""Protocol (interface) definitions for language visitor plugins and node emitters."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from treeloom.graph.cpg import CodePropertyGraph
    from treeloom.model.location import SourceLocation
    from treeloom.model.nodes import NodeId


@runtime_checkable
class NodeEmitter(Protocol):
    """Callback interface used by language visitors to emit CPG nodes and edges.

    Implemented by CPGBuilder internally. Language visitors call these methods;
    consumers never interact with NodeEmitter directly.
    """

    def emit_module(self, name: str, path: Path) -> NodeId: ...

    def emit_class(
        self, name: str, location: SourceLocation, scope: NodeId
    ) -> NodeId: ...

    def emit_function(
        self,
        name: str,
        location: SourceLocation,
        scope: NodeId,
        params: list[str] | None = None,
        is_async: bool = False,
    ) -> NodeId: ...

    def emit_parameter(
        self,
        name: str,
        location: SourceLocation,
        function: NodeId,
        type_annotation: str | None = None,
        position: int = 0,
    ) -> NodeId: ...

    def emit_variable(
        self, name: str, location: SourceLocation, scope: NodeId
    ) -> NodeId: ...

    def emit_call(
        self,
        target_name: str,
        location: SourceLocation,
        scope: NodeId,
        args: list[str] | None = None,
    ) -> NodeId: ...

    def emit_literal(
        self,
        value: str,
        literal_type: str,
        location: SourceLocation,
        scope: NodeId,
    ) -> NodeId: ...

    def emit_return(self, location: SourceLocation, scope: NodeId) -> NodeId: ...

    def emit_import(
        self,
        module: str,
        names: list[str],
        location: SourceLocation,
        scope: NodeId,
        is_from: bool = False,
        aliases: dict[str, str] | None = None,
    ) -> NodeId: ...

    # Data flow
    def emit_data_flow(self, source: NodeId, target: NodeId) -> None: ...
    def emit_definition(self, variable: NodeId, defined_by: NodeId) -> None: ...
    def emit_usage(self, variable: NodeId, used_at: NodeId) -> None: ...

    # Structural nodes for control flow
    def emit_branch_node(
        self,
        branch_type: str,
        location: SourceLocation,
        scope: NodeId,
        has_else: bool = False,
    ) -> NodeId: ...

    def emit_loop_node(
        self,
        loop_type: str,
        location: SourceLocation,
        scope: NodeId,
        iterator_var: str | None = None,
    ) -> NodeId: ...

    # Control flow edges
    def emit_control_flow(self, from_node: NodeId, to_node: NodeId) -> None: ...
    def emit_branch(
        self,
        from_node: NodeId,
        true_branch: NodeId,
        false_branch: NodeId | None = None,
    ) -> None: ...


@runtime_checkable
class LanguageVisitor(Protocol):
    """Interface for language-specific tree-sitter visitors.

    Each visitor knows how to parse one language and walk its parse tree
    to emit CPG nodes and edges via a NodeEmitter.
    """

    @property
    def name(self) -> str:
        """Language name, e.g. 'python', 'javascript'."""
        ...

    @property
    def extensions(self) -> frozenset[str]:
        """File extensions handled by this visitor, e.g. frozenset({'.py', '.pyi'})."""
        ...

    def parse(self, source: bytes, filename: str) -> Any:
        """Parse source bytes and return a tree-sitter Tree."""
        ...

    def visit(self, tree: Any, file_path: Path, emitter: NodeEmitter) -> None:
        """Walk the parse tree and emit CPG nodes/edges via the emitter."""
        ...

    def resolve_calls(
        self, cpg: CodePropertyGraph
    ) -> list[tuple[NodeId, NodeId]]:
        """Link call sites to function definitions.

        Returns a list of (call_site_id, function_definition_id) pairs.
        Unresolved calls are simply omitted from the result.
        """
        ...
