"""C language visitor for tree-sitter AST to CPG conversion."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from treeloom.lang._scope import ScopeStack
from treeloom.lang.base import TreeSitterVisitor
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

if TYPE_CHECKING:
    import tree_sitter

    from treeloom.graph.cpg import CodePropertyGraph
    from treeloom.lang.protocol import NodeEmitter
    from treeloom.model.nodes import CpgNode, NodeId

logger = logging.getLogger(__name__)

# tree-sitter literal node types -> treeloom literal type names
_LITERAL_TYPES: dict[str, str] = {
    "number_literal": "int",
    "string_literal": "str",
    "char_literal": "str",
    "true": "bool",
    "false": "bool",
    "null": "none",
}


class CVisitor(TreeSitterVisitor):
    """Walks a C tree-sitter parse tree and emits CPG nodes/edges."""

    _language_name = "c"

    @property
    def name(self) -> str:
        return "c"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".c", ".h"})

    def visit(self, tree: Any, file_path: Path, emitter: NodeEmitter) -> None:
        """Walk the parse tree and emit CPG nodes and edges."""
        root = tree.root_node
        source = root.text

        module_id = emitter.emit_module(file_path.stem, file_path)
        ctx = _VisitContext(emitter=emitter, file_path=file_path, source=source)
        ctx.scope_stack.append(module_id)

        for child in root.children:
            self._visit_node(child, ctx)

        ctx.scope_stack.pop()

    def resolve_calls(
        self,
        cpg: CodePropertyGraph,
        *,
        function_nodes: list[CpgNode] | None = None,
        call_nodes: list[CpgNode] | None = None,
    ) -> list[tuple[NodeId, NodeId]]:
        """Link CALL nodes to FUNCTION definitions by name matching."""
        functions: dict[str, list[CpgNode]] = {}
        for n in (function_nodes if function_nodes is not None else cpg.nodes(kind=NodeKind.FUNCTION)):
            functions.setdefault(n.name, []).append(n)

        resolved: list[tuple[NodeId, NodeId]] = []

        for call_node in (call_nodes if call_nodes is not None else cpg.nodes(kind=NodeKind.CALL)):
            target = call_node.name
            candidates = functions.get(target)
            if not candidates:
                continue
            fn = candidates[0]
            cpg.add_edge(_make_calls_edge(call_node.id, fn.id))
            resolved.append((call_node.id, fn.id))

        return resolved

    def _visit_node(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        handler = _NODE_HANDLERS.get(node.type)
        if handler is not None:
            handler(self, node, ctx)
        else:
            for child in node.children:
                self._visit_node(child, ctx)

    def _visit_struct_specifier(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Emit a CLASS node for a named/anonymous struct with a body."""
        body = node.child_by_field_name("body")
        if body is None:
            return
        name_node = node.child_by_field_name("name")
        struct_name = (
            self._node_text(name_node, ctx.source)
            if name_node is not None
            else "<anonymous>"
        )
        loc = self._location(node, ctx.file_path)
        class_id = ctx.emitter.emit_class(struct_name, loc, ctx.current_scope)
        ctx.scope_stack.append(class_id)
        ctx.defined_vars.push()
        for child in body.children:
            self._visit_node(child, ctx)
        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_type_definition(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        for child in node.children:
            if child.type == "struct_specifier":
                self._visit_struct_specifier(child, ctx)

    def _visit_function_definition(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle C function definitions."""
        # The function name lives inside the declarator field.
        declarator = node.child_by_field_name("declarator")
        if declarator is None:
            return

        func_name, param_nodes = _extract_function_declarator(declarator)
        if func_name is None:
            return

        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        # Emit parameters ourselves (not via emit_function) to include C type
        # annotations. emit_function with params= creates nodes without types.
        func_id = ctx.emitter.emit_function(func_name, loc, scope, params=None)
        ctx.scope_stack.append(func_id)
        ctx.defined_vars.push()
        for i, param_node in enumerate(param_nodes):
            self._emit_parameter(param_node, func_id, i, ctx)

        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)
        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _emit_parameter(
        self, node: tree_sitter.Node, func_id: NodeId, position: int, ctx: _VisitContext
    ) -> None:
        name = _extract_param_name(node)
        if not name:
            return
        param_id = ctx.emitter.emit_parameter(
            name,
            self._location(node, ctx.file_path),
            func_id,
            type_annotation=_extract_type_text(node, ctx.source),
            position=position,
        )
        ctx.defined_vars[name] = param_id

    def _visit_declaration(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        for child in node.children:
            if child.type == "init_declarator":
                self._visit_init_declarator(child, ctx)
            elif child.type in ("identifier", "pointer_declarator", "array_declarator"):
                name = _declarator_name(child)
                if name:
                    loc = self._location(child, ctx.file_path)
                    var_id = ctx.emitter.emit_variable(name, loc, ctx.current_scope)
                    ctx.defined_vars[name] = var_id

    def _visit_init_declarator(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        decl_child = node.children[0] if node.children else None
        if decl_child is None:
            return
        name = _declarator_name(decl_child)
        if not name:
            return
        loc = self._location(node, ctx.file_path)
        var_id = ctx.emitter.emit_variable(name, loc, ctx.current_scope)
        ctx.defined_vars[name] = var_id
        value_node = node.child_by_field_name("value")
        if value_node is not None:
            rhs_id = self._visit_expression(value_node, ctx)
            if rhs_id is not None:
                ctx.emitter.emit_definition(var_id, rhs_id)
                ctx.emitter.emit_data_flow(rhs_id, var_id)

    def _visit_expression_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle expression statements (bare calls, assignments, etc.)."""
        for child in node.children:
            if child.type == "assignment_expression":
                self._visit_assignment_expression(child, ctx)
            elif child.is_named:
                self._visit_expression(child, ctx)

    def _visit_assignment_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None:
            return
        var_name = self._node_text(left, ctx.source)
        loc = self._location(left, ctx.file_path)
        var_id = ctx.defined_vars.get(var_name)
        if var_id is None:
            var_id = ctx.emitter.emit_variable(var_name, loc, ctx.current_scope)
            ctx.defined_vars[var_name] = var_id
        if right is not None:
            rhs_id = self._visit_expression(right, ctx)
            if rhs_id is not None:
                ctx.emitter.emit_data_flow(rhs_id, var_id)

    def _visit_return_statement(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        ret_id = ctx.emitter.emit_return(self._location(node, ctx.file_path), ctx.current_scope)
        for child in node.children:
            if child.type in ("return", ";"):
                continue
            expr_id = self._visit_expression(child, ctx)
            if expr_id is not None:
                ctx.emitter.emit_data_flow(expr_id, ret_id)
                if child.type == "identifier":
                    ctx.emitter.emit_usage(expr_id, ret_id)

    def _visit_preproc_include(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        loc = self._location(node, ctx.file_path)
        header = ""
        for child in node.children:
            if child.type in ("string_literal", "system_lib_string"):
                header = self._node_text(child, ctx.source).strip("<>\"")
        ctx.emitter.emit_import(header, [header], loc, ctx.current_scope)

    def _visit_if_statement(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        loc = self._location(node, ctx.file_path)
        has_else = any(child.type == "else_clause" for child in node.children)
        branch_id = ctx.emitter.emit_branch_node("if", loc, ctx.current_scope, has_else=has_else)
        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)
        consequence = node.child_by_field_name("consequence")
        if consequence is not None:
            ctx.scope_stack.append(branch_id)
            self._visit_compound_or_single(consequence, ctx)
            ctx.scope_stack.pop()
        for child in node.children:
            if child.type == "else_clause":
                else_body = child.children[-1] if child.children else None
                if else_body is not None:
                    ctx.scope_stack.append(branch_id)
                    self._visit_compound_or_single(else_body, ctx)
                    ctx.scope_stack.pop()

    def _visit_for_statement(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        loc = self._location(node, ctx.file_path)
        iterator_var: str | None = None
        for child in node.children:
            if child.type == "declaration":
                # `for (int i = 0; ...)` — first init_declarator identifier
                for sub in child.children:
                    if sub.type == "init_declarator":
                        name_child = sub.children[0] if sub.children else None
                        if name_child is not None:
                            iterator_var = _declarator_name(name_child)
                        break
                break

        loop_id = ctx.emitter.emit_loop_node(
            "for", loc, ctx.current_scope, iterator_var=iterator_var
        )

        # Emit the iterator variable inside the loop scope
        if iterator_var is not None:
            for child in node.children:
                if child.type == "declaration":
                    ctx.scope_stack.append(loop_id)
                    self._visit_declaration(child, ctx)
                    ctx.scope_stack.pop()
                    break

        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            self._visit_compound_or_single(body, ctx)
            ctx.scope_stack.pop()

    def _visit_while_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        loop_id = ctx.emitter.emit_loop_node("while", loc, ctx.current_scope)

        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)

        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            self._visit_compound_or_single(body, ctx)
            ctx.scope_stack.pop()

    def _visit_compound_or_single(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Visit a compound_statement or a single statement node."""
        if node.type == "compound_statement":
            for child in node.children:
                self._visit_node(child, ctx)
        else:
            self._visit_node(node, ctx)

    # -- Expression visitor ---------------------------------------------------

    def _visit_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Visit an expression, emitting CPG nodes where needed.

        Returns the NodeId of the primary emitted node (for data flow wiring),
        or None if no meaningful node was emitted.
        """
        if node.type == "call_expression":
            return self._visit_call_expression(node, ctx)

        if node.type in _LITERAL_TYPES:
            loc = self._location(node, ctx.file_path)
            value = self._node_text(node, ctx.source)
            return ctx.emitter.emit_literal(
                value, _LITERAL_TYPES[node.type], loc, ctx.current_scope
            )

        if node.type == "identifier":
            return ctx.defined_vars.get(self._node_text(node, ctx.source))

        if node.type == "parenthesized_expression":
            for child in node.children:
                if child.is_named:
                    return self._visit_expression(child, ctx)
            return None

        if node.type in ("binary_expression", "unary_expression"):
            for child in node.children:
                if child.is_named:
                    self._visit_expression(child, ctx)
            return None

        if node.type == "assignment_expression":
            self._visit_assignment_expression(node, ctx)
            return None

        # Recurse into named children for anything else
        for child in node.children:
            if child.is_named:
                self._visit_expression(child, ctx)
        return None

    def _visit_call_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Handle a function call expression."""
        func_node = node.child_by_field_name("function")
        if func_node is None:
            return None

        target_name = self._node_text(func_node, ctx.source)
        loc = self._location(node, ctx.file_path)

        args_node = node.child_by_field_name("arguments")
        arg_texts: list[str] = []
        arg_ids: list[NodeId | None] = []
        arg_is_var: list[bool] = []
        if args_node is not None:
            for child in args_node.children:
                if child.is_named:
                    arg_texts.append(self._node_text(child, ctx.source))
                    arg_ids.append(self._visit_expression(child, ctx))
                    arg_is_var.append(child.type == "identifier")

        call_id = ctx.emitter.emit_call(
            target_name, loc, ctx.current_scope, args=arg_texts
        )

        for i, arg_id in enumerate(arg_ids):
            if arg_id is not None:
                ctx.emitter.emit_data_flow(arg_id, call_id)
                if i < len(arg_is_var) and arg_is_var[i]:
                    ctx.emitter.emit_usage(arg_id, call_id)

        return call_id


class _VisitContext:
    """Mutable state carried through the tree walk."""

    __slots__ = ("emitter", "file_path", "source", "scope_stack", "defined_vars")

    def __init__(
        self,
        emitter: NodeEmitter,
        file_path: Path,
        source: bytes,
    ) -> None:
        self.emitter = emitter
        self.file_path = file_path
        self.source = source
        self.scope_stack: list[NodeId] = []
        self.defined_vars: ScopeStack = ScopeStack()

    @property
    def current_scope(self) -> NodeId:
        return self.scope_stack[-1]


_NODE_HANDLERS: dict[str, Any] = {
    "function_definition": CVisitor._visit_function_definition,
    "struct_specifier": CVisitor._visit_struct_specifier,
    "type_definition": CVisitor._visit_type_definition,
    "declaration": CVisitor._visit_declaration,
    "expression_statement": CVisitor._visit_expression_statement,
    "return_statement": CVisitor._visit_return_statement,
    "preproc_include": CVisitor._visit_preproc_include,
    "if_statement": CVisitor._visit_if_statement,
    "for_statement": CVisitor._visit_for_statement,
    "while_statement": CVisitor._visit_while_statement,
}


def _make_calls_edge(call_id: NodeId, func_id: NodeId) -> Any:
    from treeloom.model.edges import CpgEdge

    return CpgEdge(source=call_id, target=func_id, kind=EdgeKind.CALLS)


def _extract_function_declarator(
    node: tree_sitter.Node,
) -> tuple[str | None, list[tree_sitter.Node]]:
    """Return (function_name, parameter_declaration_nodes) from a declarator."""
    if node.type == "function_declarator":
        name_node = node.child_by_field_name("declarator")
        params_node = node.child_by_field_name("parameters")
        func_name = _declarator_name(name_node) if name_node else None
        params: list[tree_sitter.Node] = (
            [c for c in params_node.children if c.type == "parameter_declaration"]
            if params_node is not None
            else []
        )
        return func_name, params

    if node.type == "pointer_declarator":
        inner = node.child_by_field_name("declarator")
        if inner is not None:
            return _extract_function_declarator(inner)

    return None, []


def _declarator_name(node: tree_sitter.Node) -> str | None:
    """Extract the plain identifier from any declarator node."""
    if node.type == "identifier":
        return node.text.decode("utf-8", errors="replace")
    if node.type in ("pointer_declarator", "array_declarator"):
        inner = node.child_by_field_name("declarator")
        if inner is not None:
            return _declarator_name(inner)
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode("utf-8", errors="replace")
    return None


def _extract_param_name(node: tree_sitter.Node) -> str | None:
    """Extract the parameter name from a parameter_declaration node."""
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode("utf-8", errors="replace")
        if child.type in ("pointer_declarator", "array_declarator"):
            return _declarator_name(child)
    return None


def _extract_type_text(node: tree_sitter.Node, _source: bytes) -> str | None:
    """Extract the type annotation text from a parameter_declaration."""
    parts = [
        child.text.decode("utf-8", errors="replace")
        for child in node.children
        if child.type in ("primitive_type", "type_identifier", "sized_type_specifier")
    ]
    return " ".join(parts) if parts else None
