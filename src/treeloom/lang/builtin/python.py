"""Python language visitor for tree-sitter AST to CPG conversion."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from treeloom.lang.base import TreeSitterVisitor
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

if TYPE_CHECKING:
    import tree_sitter

    from treeloom.graph.cpg import CodePropertyGraph
    from treeloom.lang.protocol import NodeEmitter
    from treeloom.model.nodes import CpgNode, NodeId

logger = logging.getLogger(__name__)

# tree-sitter node types that represent literal values
_LITERAL_TYPES: dict[str, str] = {
    "integer": "int",
    "float": "float",
    "string": "str",
    "true": "bool",
    "false": "bool",
    "none": "none",
    "concatenated_string": "str",
}


class PythonVisitor(TreeSitterVisitor):
    """Walks a Python tree-sitter parse tree and emits CPG nodes/edges."""

    _language_name = "python"

    @property
    def name(self) -> str:
        return "python"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".py", ".pyi"})

    def visit(
        self, tree: Any, file_path: Path, emitter: NodeEmitter
    ) -> None:
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
        self, cpg: CodePropertyGraph
    ) -> list[tuple[NodeId, NodeId]]:
        """Link CALL nodes to FUNCTION definitions by name matching."""
        # Build name -> [functions] mapping to handle duplicate names
        # (e.g., Calculator.add and standalone add)
        functions: dict[str, list[CpgNode]] = {}
        for n in cpg.nodes(kind=NodeKind.FUNCTION):
            functions.setdefault(n.name, []).append(n)

        resolved: list[tuple[NodeId, NodeId]] = []

        for call_node in cpg.nodes(kind=NodeKind.CALL):
            target = call_node.name
            fn = self._resolve_single_call(call_node, target, functions, cpg)

            # Try qualified name fallback: module.func or obj.method
            if fn is None and "." in target:
                short_name = target.rsplit(".", 1)[-1]
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
        """Resolve a call to a single function, disambiguating by scope."""
        candidates = functions.get(name)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # Multiple candidates -- try to disambiguate via scope.
        # For method calls like obj.method(), prefer the function scoped
        # inside a CLASS rather than a module-level function.
        call_target = call_node.name
        if "." in call_target:
            qualifier = call_target.rsplit(".", 1)[0]
            for fn in candidates:
                scope = cpg.scope_of(fn.id)
                if scope is not None and scope.name == qualifier:
                    return fn

        # Fall back to first match (best-effort)
        return candidates[0]

    # -- Private visit dispatch -----------------------------------------------

    def _visit_node(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        """Dispatch a single tree-sitter node to the appropriate handler."""
        handler = _NODE_HANDLERS.get(node.type)
        if handler is not None:
            handler(self, node, ctx)
        else:
            # For unrecognized nodes, recurse into children so we still
            # pick up nested constructs (e.g. expressions inside decorators).
            for child in node.children:
                self._visit_node(child, ctx)

    # -- Handlers for specific node types -------------------------------------

    def _visit_class_definition(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        class_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        class_id = ctx.emitter.emit_class(class_name, loc, scope)
        ctx.scope_stack.append(class_id)

        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)

        ctx.scope_stack.pop()

    def _visit_function_definition(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        is_async = node.type == "async_function_definition"
        # For async, the actual function_definition is sometimes nested
        if is_async:
            # In tree-sitter-python, async_function_definition wraps the tokens
            # directly (async, def, name, parameters, :, body)
            pass

        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        func_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        # Collect parameter names for emit_function (it creates params itself)
        params_node = node.child_by_field_name("parameters")
        param_names = _extract_param_names(params_node, ctx.source) if params_node else []

        func_id = ctx.emitter.emit_function(
            func_name, loc, scope, params=param_names, is_async=is_async
        )

        # Now visit the body within the function scope
        ctx.scope_stack.append(func_id)

        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)

        ctx.scope_stack.pop()

    def _visit_assignment(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle `x = expr` and `x += expr` assignments."""
        # The assignment is inside an expression_statement
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None:
            return

        scope = ctx.current_scope
        var_name = self._node_text(left, ctx.source)
        loc = self._location(left, ctx.file_path)
        var_id = ctx.emitter.emit_variable(var_name, loc, scope)

        # Track this variable definition for later USED_BY resolution
        ctx.defined_vars[var_name] = var_id

        # Process the RHS for calls, literals, and data flow
        if right is not None:
            rhs_id = self._visit_expression(right, ctx)
            if rhs_id is not None:
                ctx.emitter.emit_definition(var_id, rhs_id)

    def _visit_expression_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle expression statements (assignments, bare calls, etc.)."""
        for child in node.children:
            if child.type in ("assignment", "augmented_assignment"):
                self._visit_assignment(child, ctx)
            else:
                self._visit_expression(child, ctx)

    def _visit_return_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope
        ret_id = ctx.emitter.emit_return(loc, scope)

        # If there's a return value, emit DATA_FLOWS_TO from the expression
        # to the return node, and USED_BY for variable references
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
        names: list[str] = []

        for child in node.children:
            if child.type == "dotted_name":
                names.append(self._node_text(child, ctx.source))
            elif child.type == "aliased_import":
                dotted = child.child_by_field_name("name")
                if dotted:
                    names.append(self._node_text(dotted, ctx.source))

        module_name = names[0] if names else ""
        ctx.emitter.emit_import(module_name, names, loc, scope, is_from=False)

    def _visit_import_from_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        module_name = ""
        imported_names: list[str] = []
        saw_import = False

        for child in node.children:
            if child.type == "from":
                continue
            if child.type == "import":
                saw_import = True
                continue
            if child.type == "dotted_name":
                text = self._node_text(child, ctx.source)
                if not saw_import:
                    module_name = text
                else:
                    imported_names.append(text)
            elif child.type == "aliased_import":
                dotted = child.child_by_field_name("name")
                if dotted:
                    imported_names.append(self._node_text(dotted, ctx.source))

        ctx.emitter.emit_import(
            module_name, imported_names, loc, scope, is_from=True
        )

    def _visit_if_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        # Determine whether there's an else clause
        has_else = any(child.type == "else_clause" for child in node.children)

        branch_id = ctx.emitter.emit_branch_node(
            "if", loc, scope, has_else=has_else
        )

        # Visit the condition for any calls/refs
        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)

        # Visit if body
        consequence = node.child_by_field_name("consequence")
        if consequence is not None:
            ctx.scope_stack.append(branch_id)
            for child in consequence.children:
                self._visit_node(child, ctx)
            ctx.scope_stack.pop()

        # Visit elif/else clauses
        for child in node.children:
            if child.type == "elif_clause":
                self._visit_elif_clause(child, ctx, parent_branch=branch_id)
            elif child.type == "else_clause":
                body = child.child_by_field_name("body")
                if body is not None:
                    ctx.scope_stack.append(branch_id)
                    for sub in body.children:
                        self._visit_node(sub, ctx)
                    ctx.scope_stack.pop()

    def _visit_elif_clause(
        self,
        node: tree_sitter.Node,
        ctx: _VisitContext,
        parent_branch: NodeId | None = None,
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = parent_branch if parent_branch is not None else ctx.current_scope
        elif_id = ctx.emitter.emit_branch_node("elif", loc, scope)

        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)

        consequence = node.child_by_field_name("consequence")
        if consequence is not None:
            ctx.scope_stack.append(elif_id)
            for child in consequence.children:
                self._visit_node(child, ctx)
            ctx.scope_stack.pop()

    def _visit_for_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        # Extract iterator variable name
        iterator_var: str | None = None
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            iterator_var = self._node_text(left, ctx.source)

        loop_id = ctx.emitter.emit_loop_node(
            "for", loc, scope, iterator_var=iterator_var
        )

        # Emit the iterator variable
        if left is not None and left.type == "identifier" and iterator_var is not None:
            var_loc = self._location(left, ctx.file_path)
            var_id = ctx.emitter.emit_variable(iterator_var, var_loc, loop_id)
            ctx.defined_vars[iterator_var] = var_id

        # The iterable expression
        right = node.child_by_field_name("right")
        if right is not None:
            self._visit_expression(right, ctx)

        # Visit the loop body
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
        scope = ctx.current_scope
        loop_id = ctx.emitter.emit_loop_node("while", loc, scope)

        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)

        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            for child in body.children:
                self._visit_node(child, ctx)
            ctx.scope_stack.pop()

    # -- Expression visitor (returns NodeId of the emitted node, if any) ------

    def _visit_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Visit an expression node, possibly emitting CPG nodes.

        Returns the NodeId of the emitted node (for data flow wiring),
        or None if no node was emitted.
        """
        if node.type == "call":
            return self._visit_call_expression(node, ctx)

        if node.type in _LITERAL_TYPES:
            loc = self._location(node, ctx.file_path)
            value = self._node_text(node, ctx.source)
            lit_type = _LITERAL_TYPES[node.type]
            return ctx.emitter.emit_literal(value, lit_type, loc, ctx.current_scope)

        if node.type == "identifier":
            # This is a variable reference. Look up its definition for USED_BY.
            var_name = self._node_text(node, ctx.source)
            defined_id = ctx.defined_vars.get(var_name)
            return defined_id

        if node.type == "attribute":
            # e.g., self.x or os.path -- return None for now, handled in calls
            return None

        if node.type == "binary_operator":
            # Visit both sides for any nested calls/references
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left:
                self._visit_expression(left, ctx)
            if right:
                self._visit_expression(right, ctx)
            return None

        if node.type == "comparison_operator":
            for child in node.children:
                if child.is_named:
                    self._visit_expression(child, ctx)
            return None

        if node.type == "parenthesized_expression":
            for child in node.children:
                if child.is_named:
                    return self._visit_expression(child, ctx)
            return None

        # For other expression types, recurse into named children
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
        scope = ctx.current_scope

        # Collect argument texts and track which are variable references
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

        call_id = ctx.emitter.emit_call(target_name, loc, scope, args=arg_texts)

        # Wire DATA_FLOWS_TO and USED_BY from argument variable defs to the call
        for i, arg_id in enumerate(arg_ids):
            if arg_id is not None:
                ctx.emitter.emit_data_flow(arg_id, call_id)
                if i < len(arg_is_var) and arg_is_var[i]:
                    ctx.emitter.emit_usage(arg_id, call_id)

        return call_id


# -- Visit context (mutable state carried through the walk) -------------------


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
        self.defined_vars: dict[str, NodeId] = {}

    @property
    def current_scope(self) -> NodeId:
        return self.scope_stack[-1]


# -- Handler dispatch table ---------------------------------------------------

_NODE_HANDLERS: dict[str, Any] = {
    "class_definition": PythonVisitor._visit_class_definition,
    "function_definition": PythonVisitor._visit_function_definition,
    "async_function_definition": PythonVisitor._visit_function_definition,
    "expression_statement": PythonVisitor._visit_expression_statement,
    "return_statement": PythonVisitor._visit_return_statement,
    "import_statement": PythonVisitor._visit_import_statement,
    "import_from_statement": PythonVisitor._visit_import_from_statement,
    "if_statement": PythonVisitor._visit_if_statement,
    "for_statement": PythonVisitor._visit_for_statement,
    "while_statement": PythonVisitor._visit_while_statement,
}


def _make_calls_edge(call_id: NodeId, func_id: NodeId) -> Any:
    """Create a CALLS edge."""
    from treeloom.model.edges import CpgEdge

    return CpgEdge(source=call_id, target=func_id, kind=EdgeKind.CALLS)


def _extract_param_names(
    params_node: tree_sitter.Node, source: bytes
) -> list[str]:
    """Extract parameter names from a tree-sitter parameters node."""
    names: list[str] = []
    for child in params_node.children:
        if child.type == "identifier":
            name = child.text.decode("utf-8", errors="replace")
            if name != "self" and name != "cls":
                names.append(name)
        elif child.type == "default_parameter":
            name_node = child.child_by_field_name("name")
            if name_node:
                name = name_node.text.decode("utf-8", errors="replace")
                if name != "self" and name != "cls":
                    names.append(name)
        elif child.type == "typed_parameter":
            # e.g., x: int
            for sub in child.children:
                if sub.type == "identifier":
                    name = sub.text.decode("utf-8", errors="replace")
                    if name != "self" and name != "cls":
                        names.append(name)
                    break
        elif child.type == "list_splat_pattern":
            for sub in child.children:
                if sub.type == "identifier":
                    names.append("*" + sub.text.decode("utf-8", errors="replace"))
        elif child.type == "dictionary_splat_pattern":
            for sub in child.children:
                if sub.type == "identifier":
                    names.append("**" + sub.text.decode("utf-8", errors="replace"))
    return names
