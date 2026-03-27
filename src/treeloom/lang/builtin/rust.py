"""Rust language visitor for tree-sitter AST to CPG conversion."""

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

# tree-sitter node types that map to treeloom literal kinds
_LITERAL_TYPES: dict[str, str] = {
    "string_literal": "str",
    "integer_literal": "int",
    "float_literal": "float",
    "boolean_literal": "bool",
    "char_literal": "str",
}


class RustVisitor(TreeSitterVisitor):
    """Walks a Rust tree-sitter parse tree and emits CPG nodes/edges."""

    _language_name = "rust"

    @property
    def name(self) -> str:
        return "rust"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".rs"})

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
        fn_iter = (
            function_nodes if function_nodes is not None
            else cpg.nodes(kind=NodeKind.FUNCTION)
        )
        for n in fn_iter:
            functions.setdefault(n.name, []).append(n)

        resolved: list[tuple[NodeId, NodeId]] = []

        for call_node in (call_nodes if call_nodes is not None else cpg.nodes(kind=NodeKind.CALL)):
            target = call_node.name
            fn = self._resolve_single_call(call_node, target, functions, cpg)

            # Try qualified fallback: Type::method or obj.method
            if fn is None and ("::" in target or "." in target):
                sep = "::" if "::" in target else "."
                short_name = target.rsplit(sep, 1)[-1]
                fn = self._resolve_single_call(
                    call_node, short_name, functions, cpg
                )

            if fn is not None:
                cpg.add_edge(_make_calls_edge(call_node.id, fn.id))
                resolved.append((call_node.id, fn.id))

        return resolved

    @staticmethod
    def _resolve_single_call(
        call_node: CpgNode,
        name: str,
        functions: dict[str, list[CpgNode]],
        cpg: CodePropertyGraph,
    ) -> CpgNode | None:
        candidates = functions.get(name)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        # Multiple matches — prefer methods scoped inside a CLASS
        target = call_node.name
        for sep in ("::", "."):
            if sep in target:
                qualifier = target.rsplit(sep, 1)[0]
                for fn in candidates:
                    scope = cpg.scope_of(fn.id)
                    if scope is not None and scope.name == qualifier:
                        return fn
        return candidates[0]

    # -- Private visit dispatch -----------------------------------------------

    def _visit_node(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        handler = _NODE_HANDLERS.get(node.type)
        if handler is not None:
            handler(self, node, ctx)
        else:
            for child in node.children:
                self._visit_node(child, ctx)

    # -- Top-level item handlers ----------------------------------------------

    def _visit_struct_item(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        struct_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)

        class_id = ctx.emitter.emit_class(struct_name, loc, ctx.current_scope)
        ctx.struct_map[struct_name] = class_id
        ctx.scope_stack.append(class_id)
        ctx.defined_vars.push()

        # Emit struct fields as VARIABLE nodes
        field_list = node.child_by_field_name("body")
        if field_list is not None:
            for child in field_list.children:
                if child.type == "field_declaration":
                    self._visit_field_declaration(child, ctx)

        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_enum_item(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        enum_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)

        class_id = ctx.emitter.emit_class(enum_name, loc, ctx.current_scope)
        ctx.struct_map[enum_name] = class_id
        # Enum variants are not emitted as individual nodes (too noisy)

    def _visit_impl_item(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle `impl TypeName { ... }` — scope methods to the struct class."""
        type_node = node.child_by_field_name("type")
        if type_node is None:
            return

        type_name = self._node_text(type_node, ctx.source)
        # Look up an already-emitted CLASS node for this type
        impl_scope = ctx.struct_map.get(type_name)

        if impl_scope is not None:
            # Push the struct class as scope for methods
            ctx.scope_stack.append(impl_scope)
        # else: trait impl or unknown type — scope methods to the module

        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                if child.type == "function_item":
                    self._visit_function_item(child, ctx)

        if impl_scope is not None:
            ctx.scope_stack.pop()

    def _visit_function_item(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        func_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        params_node = node.child_by_field_name("parameters")
        param_names = _extract_param_names(params_node, ctx.source) if params_node else []

        func_id = ctx.emitter.emit_function(
            func_name, loc, scope, params=param_names
        )

        ctx.scope_stack.append(func_id)
        ctx.defined_vars.push()
        body = node.child_by_field_name("body")
        if body is not None:
            self._visit_block(body, ctx)
        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_use_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        # The path content is in the second child (after `use`)
        for child in node.children:
            if child.type in (
                "scoped_identifier",
                "identifier",
                "scoped_use_list",
                "use_list",
            ):
                module_path = self._node_text(child, ctx.source)
                # Derive simple module name from last path component
                parts = module_path.replace("::", ".").split(".")
                # Filter out braces/whitespace in complex use statements
                module_name = parts[0] if parts else module_path
                ctx.emitter.emit_import(
                    module_name, [module_path], loc, scope, is_from=False
                )
                return

    def _visit_field_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        for child in node.children:
            if child.type == "field_identifier":
                field_name = self._node_text(child, ctx.source)
                loc = self._location(child, ctx.file_path)
                ctx.emitter.emit_variable(field_name, loc, ctx.current_scope)
                return

    # -- Statement handlers ---------------------------------------------------

    def _visit_block(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        for child in node.children:
            if child.type in ("{", "}"):
                continue
            # Rust blocks can end with a bare expression (tail expression) —
            # visit it as an expression rather than a statement so call nodes
            # and data flow are captured correctly.
            if child.type not in _STMT_HANDLERS and child.type not in (
                "let_declaration",
                "expression_statement",
            ):
                self._visit_expression(child, ctx)
            else:
                self._visit_statement(child, ctx)

    def _visit_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        handler = _STMT_HANDLERS.get(node.type)
        if handler is not None:
            handler(self, node, ctx)
        else:
            # Recurse into expression_statement children
            if node.type == "expression_statement":
                for child in node.children:
                    if child.is_named:
                        self._visit_expression(child, ctx)
            else:
                for child in node.children:
                    self._visit_node(child, ctx)

    def _visit_let_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle `let [mut] name [: Type] = expr;`"""
        pattern = node.child_by_field_name("pattern")
        value = node.child_by_field_name("value")

        var_name: str | None = None
        if pattern is not None:
            if pattern.type == "identifier":
                var_name = self._node_text(pattern, ctx.source)
            elif pattern.type == "mutable_specifier":
                # mut appears before the identifier as a sibling, not a child
                pass

        # In some tree-sitter versions, the identifier follows mutable_specifier
        # as a sibling in the let_declaration children
        if var_name is None:
            for child in node.children:
                if child.type == "identifier":
                    var_name = self._node_text(child, ctx.source)
                    break

        if var_name is None or var_name in ("let", "mut"):
            return

        scope = ctx.current_scope
        loc = self._location(node, ctx.file_path)
        var_id = ctx.emitter.emit_variable(var_name, loc, scope)
        ctx.defined_vars[var_name] = var_id

        if value is not None:
            rhs_id = self._visit_expression(value, ctx)
            if rhs_id is not None:
                ctx.emitter.emit_definition(var_id, rhs_id)
                ctx.emitter.emit_data_flow(rhs_id, var_id)

    def _visit_return_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle `return_expression` (the `;` is in the parent expression_statement)."""
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope
        ret_id = ctx.emitter.emit_return(loc, scope)

        # The return value is the first named child after `return`
        for child in node.children:
            if child.type == "return":
                continue
            if child.is_named:
                expr_id = self._visit_expression(child, ctx)
                if expr_id is not None:
                    ctx.emitter.emit_data_flow(expr_id, ret_id)
                    if child.type == "identifier":
                        ctx.emitter.emit_usage(expr_id, ret_id)
                break

    def _visit_if_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        alternative = node.child_by_field_name("alternative")
        has_else = alternative is not None

        branch_id = ctx.emitter.emit_branch_node(
            "if", loc, scope, has_else=has_else
        )

        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)

        consequence = node.child_by_field_name("consequence")
        if consequence is not None:
            ctx.scope_stack.append(branch_id)
            self._visit_block(consequence, ctx)
            ctx.scope_stack.pop()

        if alternative is not None:
            ctx.scope_stack.append(branch_id)
            # alternative is an else_clause containing a block or if_expression
            for child in alternative.children:
                if child.type == "block":
                    self._visit_block(child, ctx)
                elif child.type == "if_expression":
                    self._visit_if_expression(child, ctx)
            ctx.scope_stack.pop()

    def _visit_for_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        # Iterator variable is in the `pattern` field
        iterator_var: str | None = None
        pattern = node.child_by_field_name("pattern")
        if pattern is not None and pattern.type == "identifier":
            iterator_var = self._node_text(pattern, ctx.source)

        loop_id = ctx.emitter.emit_loop_node(
            "for", loc, scope, iterator_var=iterator_var
        )

        if iterator_var is not None and pattern is not None:
            var_loc = self._location(pattern, ctx.file_path)
            var_id = ctx.emitter.emit_variable(iterator_var, var_loc, loop_id)
            ctx.defined_vars[iterator_var] = var_id

        # Visit the iterable expression
        value = node.child_by_field_name("value")
        if value is not None:
            self._visit_expression(value, ctx)

        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            self._visit_block(body, ctx)
            ctx.scope_stack.pop()

    def _visit_while_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope
        loop_id = ctx.emitter.emit_loop_node("while", loc, scope)

        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)

        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            self._visit_block(body, ctx)
            ctx.scope_stack.pop()

    def _visit_loop_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope
        loop_id = ctx.emitter.emit_loop_node("loop", loc, scope)

        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            self._visit_block(body, ctx)
            ctx.scope_stack.pop()

    def _visit_match_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope
        branch_id = ctx.emitter.emit_branch_node("match", loc, scope)

        value = node.child_by_field_name("value")
        if value is not None:
            self._visit_expression(value, ctx)

        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(branch_id)
            for child in body.children:
                if child.type == "match_arm":
                    arm_value = child.child_by_field_name("value")
                    if arm_value is not None:
                        self._visit_expression(arm_value, ctx)
            ctx.scope_stack.pop()

    # -- Expression visitor ---------------------------------------------------

    def _visit_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Visit an expression node; return the emitted NodeId or None."""
        if node.type == "call_expression":
            return self._visit_call_expression(node, ctx)

        if node.type in _LITERAL_TYPES:
            loc = self._location(node, ctx.file_path)
            value = self._node_text(node, ctx.source)
            lit_type = _LITERAL_TYPES[node.type]
            return ctx.emitter.emit_literal(value, lit_type, loc, ctx.current_scope)

        if node.type == "identifier":
            var_name = self._node_text(node, ctx.source)
            return ctx.defined_vars.get(var_name)

        if node.type == "return_expression":
            self._visit_return_statement(node, ctx)
            return None

        if node.type == "if_expression":
            self._visit_if_expression(node, ctx)
            return None

        if node.type == "for_expression":
            self._visit_for_expression(node, ctx)
            return None

        if node.type == "while_expression":
            self._visit_while_expression(node, ctx)
            return None

        if node.type == "loop_expression":
            self._visit_loop_expression(node, ctx)
            return None

        if node.type == "match_expression":
            self._visit_match_expression(node, ctx)
            return None

        if node.type in ("binary_expression", "unary_expression"):
            for child in node.children:
                if child.is_named:
                    self._visit_expression(child, ctx)
            return None

        if node.type in ("field_expression", "scoped_identifier"):
            # obj.field or Type::assoc — handled in call_expression context
            return None

        if node.type == "reference_expression":
            inner = node.child_by_field_name("value")
            if inner is not None:
                return self._visit_expression(inner, ctx)
            return None

        # Generic: recurse into named children
        for child in node.children:
            if child.is_named:
                self._visit_expression(child, ctx)
        return None

    def _visit_call_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Handle both plain calls and method calls (which use field_expression)."""
        func_node = node.child_by_field_name("function")
        if func_node is None:
            return None

        target_name = self._node_text(func_node, ctx.source)
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        args_node = node.child_by_field_name("arguments")
        arg_texts: list[str] = []
        arg_ids: list[NodeId | None] = []
        if args_node is not None:
            for child in args_node.children:
                if child.is_named:
                    arg_texts.append(self._node_text(child, ctx.source))
                    arg_ids.append(self._visit_expression(child, ctx))

        call_id = ctx.emitter.emit_call(target_name, loc, scope, args=arg_texts)

        for arg_id in arg_ids:
            if arg_id is not None:
                ctx.emitter.emit_data_flow(arg_id, call_id)

        return call_id


# -- Visit context ------------------------------------------------------------


class _VisitContext:
    """Mutable state carried through the tree walk."""

    __slots__ = (
        "emitter",
        "file_path",
        "source",
        "scope_stack",
        "defined_vars",
        "struct_map",
    )

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
        self.struct_map: dict[str, NodeId] = {}

    @property
    def current_scope(self) -> NodeId:
        return self.scope_stack[-1]


# -- Handler dispatch tables --------------------------------------------------

_NODE_HANDLERS: dict[str, Any] = {
    "struct_item": RustVisitor._visit_struct_item,
    "enum_item": RustVisitor._visit_enum_item,
    "impl_item": RustVisitor._visit_impl_item,
    "function_item": RustVisitor._visit_function_item,
    "use_declaration": RustVisitor._visit_use_declaration,
}

_STMT_HANDLERS: dict[str, Any] = {
    "let_declaration": RustVisitor._visit_let_declaration,
    "return_expression": RustVisitor._visit_return_statement,
    "if_expression": RustVisitor._visit_if_expression,
    "for_expression": RustVisitor._visit_for_expression,
    "while_expression": RustVisitor._visit_while_expression,
    "loop_expression": RustVisitor._visit_loop_expression,
    "match_expression": RustVisitor._visit_match_expression,
}


# -- Helpers ------------------------------------------------------------------


def _make_calls_edge(call_id: NodeId, func_id: NodeId) -> Any:
    from treeloom.model.edges import CpgEdge

    return CpgEdge(source=call_id, target=func_id, kind=EdgeKind.CALLS)


def _extract_param_names(
    params_node: tree_sitter.Node, source: bytes
) -> list[str]:
    """Extract parameter names from a Rust `parameters` node.

    Skips self/&self/&mut self receivers.
    """
    names: list[str] = []
    for child in params_node.children:
        if child.type == "parameter":
            # The pattern field holds the identifier
            pattern = child.child_by_field_name("pattern")
            if pattern is not None and pattern.type == "identifier":
                name = pattern.text.decode("utf-8", errors="replace")
                names.append(name)
        # self_parameter / self — skip (receiver)
    return names


