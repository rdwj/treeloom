"""Java language visitor for tree-sitter AST to CPG conversion."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from treeloom.lang._scope import ScopeStack
from treeloom.lang.base import TreeSitterVisitor
from treeloom.model.edges import EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import NodeKind

if TYPE_CHECKING:
    import tree_sitter

    from treeloom.graph.cpg import CodePropertyGraph
    from treeloom.lang.protocol import NodeEmitter
    from treeloom.model.nodes import CpgNode, NodeId

logger = logging.getLogger(__name__)

# tree-sitter node types that map to treeloom LITERAL with a type label
_LITERAL_TYPES: dict[str, str] = {
    "decimal_integer_literal": "int",
    "hex_integer_literal": "int",
    "octal_integer_literal": "int",
    "binary_integer_literal": "int",
    "decimal_floating_point_literal": "float",
    "hex_floating_point_literal": "float",
    "string_literal": "str",
    "character_literal": "str",
    "true": "bool",
    "false": "bool",
    "null_literal": "none",
}


class JavaVisitor(TreeSitterVisitor):
    """Walks a Java tree-sitter parse tree and emits CPG nodes/edges."""

    _language_name = "java"

    @property
    def name(self) -> str:
        return "java"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".java"})

    def visit(self, tree: Any, file_path: Path, emitter: NodeEmitter) -> None:
        """Walk the parse tree and emit CPG nodes and edges."""
        root = tree.root_node
        source = root.text
        module_end = self._end_location(root, file_path)
        module_id = emitter.emit_module(
            file_path.stem, file_path,
            end_location=module_end,
        )
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
            fn = _resolve_single_call(call_node, target, functions, cpg)
            if fn is None and "." in target:
                fn = _resolve_single_call(
                    call_node, target.rsplit(".", 1)[-1], functions, cpg
                )
            if fn is not None:
                cpg.add_edge(_make_calls_edge(call_node.id, fn.id))
                resolved.append((call_node.id, fn.id))
        return resolved

    # -- Visit dispatch -------------------------------------------------------

    def _visit_node(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        handler = _NODE_HANDLERS.get(node.type)
        if handler is not None:
            handler(self, node, ctx)
        else:
            for child in node.children:
                self._visit_node(child, ctx)

    # -- Declaration handlers -------------------------------------------------

    def _visit_class_like(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle class_declaration, interface_declaration, enum_declaration."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        class_id = ctx.emitter.emit_class(
            self._node_text(name_node, ctx.source),
            self._location(node, ctx.file_path),
            ctx.current_scope,
            end_location=self._end_location(node, ctx.file_path),
            source_text=self._node_text(node, ctx.source),
        )
        ctx.scope_stack.append(class_id)
        ctx.defined_vars.push()
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)
        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_method_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        func_id = ctx.emitter.emit_function(
            self._node_text(name_node, ctx.source),
            self._location(node, ctx.file_path),
            ctx.current_scope,
            params=None,  # _emit_typed_params handles params with type annotations
            end_location=self._end_location(node, ctx.file_path),
            source_text=self._node_text(node, ctx.source),
        )
        ctx.scope_stack.append(func_id)
        ctx.defined_vars.push()
        params_node = node.child_by_field_name("parameters")
        if params_node is not None:
            self._emit_typed_params(params_node, func_id, ctx)
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)
        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_constructor_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        func_id = ctx.emitter.emit_function(
            self._node_text(name_node, ctx.source),
            self._location(node, ctx.file_path),
            ctx.current_scope,
            params=None,
            end_location=self._end_location(node, ctx.file_path),
            source_text=self._node_text(node, ctx.source),
        )
        ctx.scope_stack.append(func_id)
        ctx.defined_vars.push()
        params_node = node.child_by_field_name("parameters")
        if params_node is not None:
            self._emit_typed_params(params_node, func_id, ctx)
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)
        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_local_variable_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle `Type name = expr;` local variable declarations."""
        type_ann: str | None = None
        for child in node.children:
            if child.type in ("variable_declarator", ";"):
                continue
            if child.is_named:
                type_ann = self._node_text(child, ctx.source)
                break
        for child in node.children:
            if child.type == "variable_declarator":
                self._visit_variable_declarator(child, ctx, type_ann=type_ann)

    def _visit_expression_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        for child in node.children:
            if child.type == "assignment_expression":
                self._visit_assignment_expression(child, ctx)
            elif child.type != ";":
                self._visit_expression(child, ctx)

    def _visit_return_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        ret_id = ctx.emitter.emit_return(
            self._location(node, ctx.file_path), ctx.current_scope,
            end_location=self._end_location(node, ctx.file_path),
        )
        for child in node.children:
            if child.type in ("return", ";"):
                continue
            expr_id = self._visit_expression(child, ctx)
            if expr_id is not None:
                ctx.emitter.emit_data_flow(expr_id, ret_id)
                if child.type == "identifier":
                    ctx.emitter.emit_usage(expr_id, ret_id)

    def _visit_import_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        full_name = ""
        is_wildcard = False
        for child in node.children:
            if child.type in ("import", ";", "static"):
                continue
            if child.type in ("scoped_identifier", "identifier"):
                full_name = self._node_text(child, ctx.source)
            elif child.type == "asterisk":
                is_wildcard = True
        if not full_name:
            return
        if "." in full_name:
            module_name, last = full_name.rsplit(".", 1)
            imported_name = "*" if is_wildcard else last
        else:
            module_name = full_name
            imported_name = full_name
        ctx.emitter.emit_import(
            module_name, [imported_name],
            self._location(node, ctx.file_path),
            ctx.current_scope,
            is_from=True,
            end_location=self._end_location(node, ctx.file_path),
        )

    def _visit_if_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        has_else = node.child_by_field_name("alternative") is not None
        branch_id = ctx.emitter.emit_branch_node(
            "if", self._location(node, ctx.file_path), ctx.current_scope,
            has_else=has_else,
            end_location=self._end_location(node, ctx.file_path),
        )
        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)
        consequence = node.child_by_field_name("consequence")
        if consequence is not None:
            ctx.scope_stack.append(branch_id)
            for child in consequence.children:
                self._visit_node(child, ctx)
            ctx.scope_stack.pop()
        alternative = node.child_by_field_name("alternative")
        if alternative is not None:
            ctx.scope_stack.append(branch_id)
            if alternative.type == "if_statement":
                self._visit_if_statement(alternative, ctx)
            else:
                for child in alternative.children:
                    self._visit_node(child, ctx)
            ctx.scope_stack.pop()

    def _visit_for_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loop_id = ctx.emitter.emit_loop_node(
            "for", self._location(node, ctx.file_path), ctx.current_scope,
            end_location=self._end_location(node, ctx.file_path),
        )
        init = node.child_by_field_name("init")
        if init is not None:
            ctx.scope_stack.append(loop_id)
            self._visit_node(init, ctx)
            ctx.scope_stack.pop()
        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            for child in body.children:
                self._visit_node(child, ctx)
            ctx.scope_stack.pop()

    def _visit_enhanced_for_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        name_node = node.child_by_field_name("name")
        iterator_var = (
            self._node_text(name_node, ctx.source) if name_node is not None else None
        )
        loop_id = ctx.emitter.emit_loop_node(
            "for", self._location(node, ctx.file_path), ctx.current_scope,
            iterator_var=iterator_var,
            end_location=self._end_location(node, ctx.file_path),
        )
        if iterator_var is not None and name_node is not None:
            var_id = ctx.emitter.emit_variable(
                iterator_var,
                SourceLocation(
                    file=ctx.file_path,
                    line=name_node.start_point.row + 1,
                    column=name_node.start_point.column,
                ),
                loop_id,
                end_location=self._end_location(name_node, ctx.file_path),
            )
            ctx.defined_vars[iterator_var] = var_id
        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            for child in body.children:
                self._visit_node(child, ctx)
            ctx.scope_stack.pop()

    def _visit_while_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loop_id = ctx.emitter.emit_loop_node(
            "while", self._location(node, ctx.file_path), ctx.current_scope,
            end_location=self._end_location(node, ctx.file_path),
        )
        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)
        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            for child in body.children:
                self._visit_node(child, ctx)
            ctx.scope_stack.pop()

    # -- Expression visitor ---------------------------------------------------

    def _visit_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        if node.type == "method_invocation":
            return self._visit_call(node, ctx, qualified=True)
        if node.type == "object_creation_expression":
            return self._visit_object_creation(node, ctx)
        if node.type in _LITERAL_TYPES:
            return ctx.emitter.emit_literal(
                self._node_text(node, ctx.source),
                _LITERAL_TYPES[node.type],
                self._location(node, ctx.file_path),
                ctx.current_scope,
                end_location=self._end_location(node, ctx.file_path),
            )
        if node.type == "identifier":
            return ctx.defined_vars.get(self._node_text(node, ctx.source))
        if node.type == "assignment_expression":
            self._visit_assignment_expression(node, ctx)
            return None
        if node.type == "binary_expression":
            return self._visit_binary_expression(node, ctx)
        if node.type == "parenthesized_expression":
            for child in node.children:
                if child.is_named:
                    return self._visit_expression(child, ctx)
            return None
        if node.type == "lambda_expression":
            return self._visit_lambda(node, ctx)
        if node.type in ("array_creation_expression", "array_initializer"):
            return self._visit_array_expression(node, ctx)
        if node.type == "cast_expression":
            # `(Type) expr` — propagate the inner expression's node
            for child in node.children:
                if child.is_named and child.type not in (
                    "type_identifier", "generic_type", "integral_type",
                    "floating_point_type", "boolean_type", "void_type",
                ):
                    return self._visit_expression(child, ctx)
            return None
        for child in node.children:
            if child.is_named:
                self._visit_expression(child, ctx)
        return None

    def _visit_binary_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Handle binary expressions, emitting a concat call node for `+`.

        For the string concatenation operator (`+`) we emit a synthetic CALL
        node named ``<string_concat>`` and wire DATA_FLOWS_TO edges from any
        variable/call operands into it.  This ensures that taint carried by a
        variable survives a pattern like ``"SELECT " + userInput``.

        For all other operators we still visit both operands (so any nested
        calls are processed) but return None because no single node represents
        the compound result.
        """
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")

        # Find operator
        op = None
        for child in node.children:
            if not child.is_named and child.type not in (
                "identifier", "string_literal"
            ):
                op = child.type
                break

        left_id = self._visit_expression(left, ctx) if left else None
        right_id = self._visit_expression(right, ctx) if right else None

        if op == "+":
            # Emit a synthetic concat call so taint can flow through it.
            concat_id = ctx.emitter.emit_call(
                "<string_concat>",
                self._location(node, ctx.file_path),
                ctx.current_scope,
                end_location=self._end_location(node, ctx.file_path),
            )
            if left_id is not None:
                ctx.emitter.emit_data_flow(left_id, concat_id)
            if right_id is not None:
                ctx.emitter.emit_data_flow(right_id, concat_id)
            return concat_id

        return None

    def _visit_lambda(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Visit a lambda expression body so statements inside are processed."""
        # Lambda structure: params `->` body
        # body is the last named child after the `->` token.
        after_arrow = False
        for child in node.children:
            if child.type == "->":
                after_arrow = True
                continue
            if after_arrow:
                if child.type == "block":
                    for stmt in child.children:
                        self._visit_node(stmt, ctx)
                    return None
                elif child.is_named:
                    return self._visit_expression(child, ctx)
        return None

    def _visit_array_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Visit array creation/initializer, propagating taint from elements."""
        # Collect any tainted element nodes and return the last non-None one.
        # A full solution would emit an array node, but for taint purposes
        # visiting the elements (so their DFG is recorded) is sufficient.
        last_id: NodeId | None = None
        target = node
        if node.type == "array_creation_expression":
            # Find the initializer if present
            for child in node.children:
                if child.type == "array_initializer":
                    target = child
                    break
        for child in target.children:
            if child.is_named:
                result = self._visit_expression(child, ctx)
                if result is not None:
                    last_id = result
        return last_id

    def _visit_call(
        self,
        node: tree_sitter.Node,
        ctx: _VisitContext,
        *,
        qualified: bool = False,
    ) -> NodeId | None:
        """Emit a CALL node for a method_invocation, wiring arg data flow."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        method_name = self._node_text(name_node, ctx.source)
        obj_node = node.child_by_field_name("object") if qualified else None
        target_name = (
            f"{self._node_text(obj_node, ctx.source)}.{method_name}"
            if obj_node is not None
            else method_name
        )
        args_node = node.child_by_field_name("arguments")
        arg_texts, arg_ids, arg_is_var = self._collect_args(args_node, ctx)
        call_id = ctx.emitter.emit_call(
            target_name, self._location(node, ctx.file_path),
            ctx.current_scope, args=arg_texts,
            end_location=self._end_location(node, ctx.file_path),
        )
        self._wire_args(arg_ids, arg_is_var, call_id, ctx)
        # Wire receiver object into call so that e.g. `queryParams.get()`
        # carries taint from `queryParams` through to the call result.
        if obj_node is not None:
            receiver_id = self._visit_expression(obj_node, ctx)
            if receiver_id is not None:
                ctx.emitter.emit_data_flow(receiver_id, call_id)
        return call_id

    def _visit_object_creation(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Handle `new ClassName(args)` expressions."""
        type_name = "Object"
        for child in node.children:
            if child.type in ("type_identifier", "generic_type", "scoped_type_identifier"):
                type_name = self._node_text(child, ctx.source)
                break
        args_node = node.child_by_field_name("arguments")
        arg_texts, arg_ids, arg_is_var = self._collect_args(args_node, ctx)
        call_id = ctx.emitter.emit_call(
            f"new {type_name}", self._location(node, ctx.file_path),
            ctx.current_scope, args=arg_texts,
            end_location=self._end_location(node, ctx.file_path),
        )
        self._wire_args(arg_ids, arg_is_var, call_id, ctx)
        return call_id

    # -- Variable and assignment helpers --------------------------------------

    def _visit_variable_declarator(
        self,
        node: tree_sitter.Node,
        ctx: _VisitContext,
        type_ann: str | None = None,
    ) -> NodeId | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        var_name = name_node.text.decode("utf-8", errors="replace")
        loc = SourceLocation(
            file=ctx.file_path,
            line=name_node.start_point.row + 1,
            column=name_node.start_point.column,
        )
        var_id = ctx.emitter.emit_variable(
            var_name, loc, ctx.current_scope,
            end_location=self._end_location(name_node, ctx.file_path),
        )
        ctx.defined_vars[var_name] = var_id
        value_node = node.child_by_field_name("value")
        if value_node is not None:
            rhs_id = self._visit_expression(value_node, ctx)
            if rhs_id is not None:
                ctx.emitter.emit_definition(var_id, rhs_id)
                ctx.emitter.emit_data_flow(rhs_id, var_id)
        return var_id

    def _visit_assignment_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None:
            return
        var_name = left.text.decode("utf-8", errors="replace")
        loc = SourceLocation(
            file=ctx.file_path,
            line=left.start_point.row + 1,
            column=left.start_point.column,
        )
        var_id = ctx.emitter.emit_variable(
            var_name, loc, ctx.current_scope,
            end_location=self._end_location(left, ctx.file_path),
        )
        ctx.defined_vars[var_name] = var_id
        if right is not None:
            rhs_id = self._visit_expression(right, ctx)
            if rhs_id is not None:
                ctx.emitter.emit_definition(var_id, rhs_id)
                ctx.emitter.emit_data_flow(rhs_id, var_id)

    def _emit_typed_params(
        self,
        params_node: tree_sitter.Node,
        func_id: NodeId,
        ctx: _VisitContext,
    ) -> None:
        """Emit PARAMETER nodes with type annotations and positions."""
        pos = 0
        for child in params_node.children:
            if child.type == "formal_parameter":
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")
                if name_node is None:
                    continue
                param_name = name_node.text.decode("utf-8", errors="replace")
                type_ann = (
                    type_node.text.decode("utf-8", errors="replace")
                    if type_node is not None
                    else None
                )
                loc = SourceLocation(
                    file=ctx.file_path,
                    line=name_node.start_point.row + 1,
                    column=name_node.start_point.column,
                )
                param_id = ctx.emitter.emit_parameter(
                    param_name, loc, func_id,
                    type_annotation=type_ann, position=pos,
                    end_location=self._end_location(child, ctx.file_path),
                )
                ctx.defined_vars[param_name] = param_id
                pos += 1
            elif child.type == "spread_parameter":
                pos += 1

    def _collect_args(
        self,
        args_node: tree_sitter.Node | None,
        ctx: _VisitContext,
    ) -> tuple[list[str], list[NodeId | None], list[bool]]:
        """Return (texts, node_ids, is_identifier) for each argument."""
        arg_texts: list[str] = []
        arg_ids: list[NodeId | None] = []
        arg_is_var: list[bool] = []
        if args_node is not None:
            for child in args_node.children:
                if child.is_named:
                    arg_texts.append(self._node_text(child, ctx.source))
                    arg_ids.append(self._visit_expression(child, ctx))
                    arg_is_var.append(child.type == "identifier")
        return arg_texts, arg_ids, arg_is_var

    def _wire_args(
        self,
        arg_ids: list[NodeId | None],
        arg_is_var: list[bool],
        call_id: NodeId,
        ctx: _VisitContext,
    ) -> None:
        """Emit DATA_FLOWS_TO and USED_BY edges for call arguments."""
        for i, arg_id in enumerate(arg_ids):
            if arg_id is not None:
                ctx.emitter.emit_data_flow(arg_id, call_id)
                if i < len(arg_is_var) and arg_is_var[i]:
                    ctx.emitter.emit_usage(arg_id, call_id)


# -- Visit context ------------------------------------------------------------


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


# -- Handler dispatch table ---------------------------------------------------

_NODE_HANDLERS: dict[str, Any] = {
    "class_declaration": JavaVisitor._visit_class_like,
    "interface_declaration": JavaVisitor._visit_class_like,
    "enum_declaration": JavaVisitor._visit_class_like,
    "method_declaration": JavaVisitor._visit_method_declaration,
    "constructor_declaration": JavaVisitor._visit_constructor_declaration,
    "local_variable_declaration": JavaVisitor._visit_local_variable_declaration,
    "expression_statement": JavaVisitor._visit_expression_statement,
    "return_statement": JavaVisitor._visit_return_statement,
    "import_declaration": JavaVisitor._visit_import_declaration,
    "if_statement": JavaVisitor._visit_if_statement,
    "for_statement": JavaVisitor._visit_for_statement,
    "enhanced_for_statement": JavaVisitor._visit_enhanced_for_statement,
    "while_statement": JavaVisitor._visit_while_statement,
}


# -- Module-level helpers -----------------------------------------------------


def _make_calls_edge(call_id: NodeId, func_id: NodeId) -> Any:
    from treeloom.model.edges import CpgEdge

    return CpgEdge(source=call_id, target=func_id, kind=EdgeKind.CALLS)


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
    # Disambiguate by scope for qualified calls (e.g., "Foo.bar")
    if "." in call_node.name:
        qualifier = call_node.name.rsplit(".", 1)[0]
        for fn in candidates:
            scope = cpg.scope_of(fn.id)
            if scope is not None and scope.name == qualifier:
                return fn
    return candidates[0]
