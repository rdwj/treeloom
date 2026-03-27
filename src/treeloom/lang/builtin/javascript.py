"""JavaScript language visitor for tree-sitter AST to CPG conversion."""

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
    "number": "number",
    "string": "str",
    "template_string": "str",
    "true": "bool",
    "false": "bool",
    "null": "none",
    "undefined": "none",
}


class JavaScriptVisitor(TreeSitterVisitor):
    """Walks a JavaScript tree-sitter parse tree and emits CPG nodes/edges."""

    _language_name = "javascript"

    @property
    def name(self) -> str:
        return "javascript"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".js", ".mjs", ".cjs"})

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
            fn = self._resolve_single_call(call_node, target, functions, cpg)

            # Qualified name fallback: obj.method -> method
            if fn is None and "." in target:
                short_name = target.rsplit(".", 1)[-1]
                fn = self._resolve_single_call(
                    call_node, short_name, functions, cpg
                )

            if fn is not None:
                from treeloom.model.edges import CpgEdge

                cpg.add_edge(
                    CpgEdge(source=call_node.id, target=fn.id, kind=EdgeKind.CALLS)
                )
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

        # Prefer method scoped inside a class for qualified calls
        call_target = call_node.name
        if "." in call_target:
            qualifier = call_target.rsplit(".", 1)[0]
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

    # -- Handlers -------------------------------------------------------------

    def _visit_class_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        class_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)

        class_id = ctx.emitter.emit_class(class_name, loc, ctx.current_scope)
        ctx.scope_stack.append(class_id)
        ctx.defined_vars.push()

        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)

        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_function_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle function_declaration and generator_function_declaration."""
        is_async = any(c.type == "async" for c in node.children)
        name_node = node.child_by_field_name("name")
        func_name = (
            self._node_text(name_node, ctx.source) if name_node else "<anonymous>"
        )
        self._emit_function(node, func_name, ctx, is_async=is_async)

    def _visit_function_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle anonymous function expressions assigned to variables."""
        is_async = any(c.type == "async" for c in node.children)
        name_node = node.child_by_field_name("name")
        func_name = (
            self._node_text(name_node, ctx.source)
            if name_node
            else ctx.pending_func_name or "<anonymous>"
        )
        ctx.pending_func_name = None
        self._emit_function(node, func_name, ctx, is_async=is_async)

    def _visit_arrow_function(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        func_name = ctx.pending_func_name or "<arrow>"
        ctx.pending_func_name = None
        self._emit_function(node, func_name, ctx, is_async=False)

    def _visit_method_definition(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        func_name = self._node_text(name_node, ctx.source)
        is_async = any(c.type == "async" for c in node.children)
        self._emit_function(node, func_name, ctx, is_async=is_async)

    def _emit_function(
        self,
        node: tree_sitter.Node,
        func_name: str,
        ctx: _VisitContext,
        is_async: bool = False,
    ) -> None:
        """Shared function emission logic for all function-like nodes."""
        loc = self._location(node, ctx.file_path)
        params_node = node.child_by_field_name("parameters")
        param_names = (
            _extract_param_names(params_node, ctx.source) if params_node else []
        )

        func_id = ctx.emitter.emit_function(
            func_name, loc, ctx.current_scope, params=param_names, is_async=is_async
        )

        ctx.scope_stack.append(func_id)
        ctx.defined_vars.push()

        body = node.child_by_field_name("body")
        if body is not None:
            if body.type == "statement_block":
                for child in body.children:
                    self._visit_node(child, ctx)
            else:
                # Arrow function with expression body (e.g. `x => x * 2`)
                self._visit_expression(body, ctx)

        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_lexical_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle const/let declarations."""
        for child in node.children:
            if child.type == "variable_declarator":
                self._visit_variable_declarator(child, ctx)

    def _visit_variable_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle var declarations."""
        for child in node.children:
            if child.type == "variable_declarator":
                self._visit_variable_declarator(child, ctx)

    def _visit_variable_declarator(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        name_node = node.child_by_field_name("name")
        value_node = node.child_by_field_name("value")
        if name_node is None:
            return

        var_name = self._node_text(name_node, ctx.source)
        loc = self._location(name_node, ctx.file_path)

        # If RHS is a function/arrow, pass name hint so it gets a useful name
        if value_node is not None and value_node.type in (
            "function_expression",
            "arrow_function",
        ):
            ctx.pending_func_name = var_name
            self._visit_node(value_node, ctx)
            # Emit variable after so the function exists first
            var_id = ctx.emitter.emit_variable(var_name, loc, ctx.current_scope)
            ctx.defined_vars[var_name] = var_id
        else:
            var_id = ctx.emitter.emit_variable(var_name, loc, ctx.current_scope)
            ctx.defined_vars[var_name] = var_id

            if value_node is not None:
                rhs_id = self._visit_expression(value_node, ctx)
                if rhs_id is not None:
                    ctx.emitter.emit_definition(var_id, rhs_id)
                    ctx.emitter.emit_data_flow(rhs_id, var_id)

    def _visit_expression_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
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

        if left.type == "identifier":
            var_name = self._node_text(left, ctx.source)
            loc = self._location(left, ctx.file_path)
            var_id = ctx.emitter.emit_variable(var_name, loc, ctx.current_scope)
            ctx.defined_vars[var_name] = var_id

            if right is not None:
                rhs_id = self._visit_expression(right, ctx)
                if rhs_id is not None:
                    ctx.emitter.emit_definition(var_id, rhs_id)
                    ctx.emitter.emit_data_flow(rhs_id, var_id)
        elif right is not None:
            # member expression LHS (this.x = ...) — still process RHS
            self._visit_expression(right, ctx)

    def _visit_return_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        ret_id = ctx.emitter.emit_return(loc, ctx.current_scope)

        for child in node.children:
            if child.type == "return":
                continue
            expr_id = self._visit_expression(child, ctx)
            if expr_id is not None:
                ctx.emitter.emit_data_flow(expr_id, ret_id)
                if child.type == "identifier":
                    ctx.emitter.emit_usage(expr_id, ret_id)

    def _visit_import_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        module_name = ""
        imported_names: list[str] = []
        aliases: dict[str, str] = {}

        for child in node.children:
            if child.type == "string":
                raw = self._node_text(child, ctx.source)
                module_name = raw.strip("'\"")
            elif child.type == "import_clause":
                clause_names, clause_aliases = _extract_import_names(child, ctx.source)
                imported_names.extend(clause_names)
                aliases.update(clause_aliases)

        ctx.emitter.emit_import(
            module_name, imported_names, loc, scope,
            is_from=bool(imported_names),
            aliases=aliases or None,
        )

    def _visit_if_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        has_else = any(c.type == "else_clause" for c in node.children)

        branch_id = ctx.emitter.emit_branch_node(
            "if", loc, ctx.current_scope, has_else=has_else
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

        for child in node.children:
            if child.type == "else_clause":
                # The last named child of else_clause is the body
                body = next(
                    (c for c in reversed(child.children) if c.is_named), None
                )
                if body is not None:
                    if body.type == "if_statement":
                        self._visit_else_if(body, ctx, parent_branch=branch_id)
                    else:
                        ctx.scope_stack.append(branch_id)
                        for sub in body.children:
                            self._visit_node(sub, ctx)
                        ctx.scope_stack.pop()

    def _visit_else_if(
        self,
        node: tree_sitter.Node,
        ctx: _VisitContext,
        parent_branch: NodeId | None = None,
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = parent_branch if parent_branch is not None else ctx.current_scope
        has_else = any(c.type == "else_clause" for c in node.children)
        elif_id = ctx.emitter.emit_branch_node("elif", loc, scope, has_else=has_else)

        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)

        consequence = node.child_by_field_name("consequence")
        if consequence is not None:
            ctx.scope_stack.append(elif_id)
            for child in consequence.children:
                self._visit_node(child, ctx)
            ctx.scope_stack.pop()

        for child in node.children:
            if child.type == "else_clause":
                body = next(
                    (c for c in reversed(child.children) if c.is_named), None
                )
                if body is not None:
                    if body.type == "if_statement":
                        self._visit_else_if(body, ctx, parent_branch=elif_id)
                    else:
                        ctx.scope_stack.append(elif_id)
                        for sub in body.children:
                            self._visit_node(sub, ctx)
                        ctx.scope_stack.pop()

    def _visit_for_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)

        iterator_var: str | None = None
        init = node.child_by_field_name("initializer")
        if init is not None:
            iterator_var = _extract_for_init_var(init, ctx.source)

        loop_id = ctx.emitter.emit_loop_node(
            "for", loc, ctx.current_scope, iterator_var=iterator_var
        )

        if iterator_var is not None and init is not None:
            var_loc = self._location(init, ctx.file_path)
            var_id = ctx.emitter.emit_variable(iterator_var, var_loc, loop_id)
            ctx.defined_vars[iterator_var] = var_id

        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            for child in body.children:
                self._visit_node(child, ctx)
            ctx.scope_stack.pop()

    def _visit_for_in_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle for-in and for-of statements."""
        loc = self._location(node, ctx.file_path)

        left = node.child_by_field_name("left")
        iterator_var: str | None = None
        if left is not None and left.type == "identifier":
            iterator_var = self._node_text(left, ctx.source)

        loop_id = ctx.emitter.emit_loop_node(
            "for", loc, ctx.current_scope, iterator_var=iterator_var
        )

        if iterator_var is not None and left is not None:
            var_loc = self._location(left, ctx.file_path)
            var_id = ctx.emitter.emit_variable(iterator_var, var_loc, loop_id)
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
        loc = self._location(node, ctx.file_path)
        loop_id = ctx.emitter.emit_loop_node("while", loc, ctx.current_scope)

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

        if node.type in ("member_expression", "subscript_expression"):
            return None

        if node.type in ("binary_expression", "logical_expression"):
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left:
                self._visit_expression(left, ctx)
            if right:
                self._visit_expression(right, ctx)
            return None

        if node.type == "parenthesized_expression":
            for child in node.children:
                if child.is_named:
                    return self._visit_expression(child, ctx)
            return None

        if node.type == "await_expression":
            for child in node.children:
                if child.is_named:
                    return self._visit_expression(child, ctx)
            return None

        if node.type == "assignment_expression":
            self._visit_assignment_expression(node, ctx)
            return None

        for child in node.children:
            if child.is_named:
                self._visit_expression(child, ctx)
        return None

    def _visit_call_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
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


# -- Visit context -----------------------------------------------------------


class _VisitContext:
    """Mutable state carried through the tree walk."""

    __slots__ = (
        "emitter",
        "file_path",
        "source",
        "scope_stack",
        "defined_vars",
        "pending_func_name",
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
        self.pending_func_name: str | None = None

    @property
    def current_scope(self) -> NodeId:
        return self.scope_stack[-1]


# -- Handler dispatch table --------------------------------------------------

_NODE_HANDLERS: dict[str, Any] = {
    "class_declaration": JavaScriptVisitor._visit_class_declaration,
    "function_declaration": JavaScriptVisitor._visit_function_declaration,
    "generator_function_declaration": JavaScriptVisitor._visit_function_declaration,
    "function_expression": JavaScriptVisitor._visit_function_expression,
    "arrow_function": JavaScriptVisitor._visit_arrow_function,
    "method_definition": JavaScriptVisitor._visit_method_definition,
    "lexical_declaration": JavaScriptVisitor._visit_lexical_declaration,
    "variable_declaration": JavaScriptVisitor._visit_variable_declaration,
    "expression_statement": JavaScriptVisitor._visit_expression_statement,
    "return_statement": JavaScriptVisitor._visit_return_statement,
    "import_statement": JavaScriptVisitor._visit_import_statement,
    "if_statement": JavaScriptVisitor._visit_if_statement,
    "for_statement": JavaScriptVisitor._visit_for_statement,
    "for_in_statement": JavaScriptVisitor._visit_for_in_statement,
    "while_statement": JavaScriptVisitor._visit_while_statement,
}


# -- Helpers -----------------------------------------------------------------


def _extract_param_names(
    params_node: tree_sitter.Node, source: bytes
) -> list[str]:
    """Extract parameter names from a formal_parameters node."""
    names: list[str] = []
    for child in params_node.children:
        if child.type == "identifier":
            names.append(child.text.decode("utf-8", errors="replace"))
        elif child.type == "assignment_pattern":
            # default parameter: name = default
            left = child.child_by_field_name("left")
            if left is not None and left.type == "identifier":
                names.append(left.text.decode("utf-8", errors="replace"))
        elif child.type == "rest_pattern":
            for sub in child.children:
                if sub.type == "identifier":
                    names.append("..." + sub.text.decode("utf-8", errors="replace"))
    return names


def _extract_import_names(
    clause_node: tree_sitter.Node, source: bytes
) -> tuple[list[str], dict[str, str]]:
    """Extract imported names and aliases from an import_clause node.

    Returns ``(names, aliases)`` where ``names`` is the list of original
    imported identifiers and ``aliases`` maps original name to local alias
    (e.g. ``{"foo": "bar"}`` for ``import { foo as bar } from '...'``).
    """
    names: list[str] = []
    aliases: dict[str, str] = {}
    for child in clause_node.children:
        if child.type == "identifier":
            # default import: import Foo from '...'
            names.append(child.text.decode("utf-8", errors="replace"))
        elif child.type == "named_imports":
            for spec in child.children:
                if spec.type == "import_specifier":
                    # spec.children[0] is the exported name, alias field is the local name
                    alias_node = spec.child_by_field_name("alias")
                    orig_node = spec.children[0] if spec.children else None
                    if orig_node is not None and orig_node.is_named:
                        orig = orig_node.text.decode("utf-8", errors="replace")
                        names.append(orig)
                        if alias_node is not None:
                            aliases[orig] = alias_node.text.decode("utf-8", errors="replace")
        elif child.type == "namespace_import":
            # import * as ns from '...'
            for sub in child.children:
                if sub.type == "identifier":
                    names.append(sub.text.decode("utf-8", errors="replace"))
    return names, aliases


def _extract_for_init_var(init_node: tree_sitter.Node, source: bytes) -> str | None:
    """Extract loop variable name from a for-statement initializer."""
    if init_node.type == "lexical_declaration":
        for child in init_node.children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                if name_node is not None and name_node.type == "identifier":
                    return name_node.text.decode("utf-8", errors="replace")
    elif init_node.type == "identifier":
        return init_node.text.decode("utf-8", errors="replace")
    return None
