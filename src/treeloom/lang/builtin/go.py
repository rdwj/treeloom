"""Go language visitor for tree-sitter AST to CPG conversion."""

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

# tree-sitter node types for Go literals
_LITERAL_TYPES: dict[str, str] = {
    "interpreted_string_literal": "str",
    "raw_string_literal": "str",
    "int_literal": "int",
    "float_literal": "float",
    "imaginary_literal": "float",
    "rune_literal": "str",
    "true": "bool",
    "false": "bool",
    "nil": "none",
}


class GoVisitor(TreeSitterVisitor):
    """Walks a Go tree-sitter parse tree and emits CPG nodes/edges."""

    _language_name = "go"

    @property
    def name(self) -> str:
        return "go"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".go"})

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
        self, cpg: CodePropertyGraph
    ) -> list[tuple[NodeId, NodeId]]:
        """Link CALL nodes to FUNCTION definitions by name matching."""
        functions: dict[str, list[CpgNode]] = {}
        for n in cpg.nodes(kind=NodeKind.FUNCTION):
            functions.setdefault(n.name, []).append(n)

        resolved: list[tuple[NodeId, NodeId]] = []

        for call_node in cpg.nodes(kind=NodeKind.CALL):
            target = call_node.name
            fn = self._resolve_single_call(call_node, target, functions, cpg)

            # Try qualified name fallback: pkg.Func or receiver.Method
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
        candidates = functions.get(name)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        # Multiple matches — prefer method scoped in a CLASS
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

    # -- Node type handlers ---------------------------------------------------

    def _visit_type_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle 'type X struct { ... }' — emit as CLASS."""
        for child in node.children:
            if child.type == "type_spec":
                self._visit_type_spec(child, ctx)

    def _visit_type_spec(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        # Only emit CLASS for struct types
        type_name_node = node.child_by_field_name("name")
        type_node = node.child_by_field_name("type")
        if type_name_node is None or type_node is None:
            return
        if type_node.type != "struct_type":
            return

        type_name = self._node_text(type_name_node, ctx.source)
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        class_id = ctx.emitter.emit_class(type_name, loc, scope)
        ctx.scope_stack.append(class_id)
        ctx.defined_vars.push()

        # Emit struct fields as VARIABLE nodes. field_declaration_list is an
        # unnamed child of struct_type (no named field access via API).
        for child in type_node.children:
            if child.type == "field_declaration_list":
                for field_decl in child.children:
                    if field_decl.type == "field_declaration":
                        self._visit_field_declaration(field_decl, ctx)

        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_field_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Emit struct field as a VARIABLE node."""
        for child in node.children:
            if child.type == "field_identifier":
                field_name = self._node_text(child, ctx.source)
                loc = self._location(child, ctx.file_path)
                ctx.emitter.emit_variable(field_name, loc, ctx.current_scope)

    def _visit_function_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle top-level 'func Name(params) returnType { ... }'."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        func_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        # Emit the function without params so we can register each parameter's
        # NodeId in defined_vars, enabling identifier lookups inside the body.
        func_id = ctx.emitter.emit_function(func_name, loc, scope, params=None)

        ctx.scope_stack.append(func_id)
        ctx.defined_vars.push()

        params_node = node.child_by_field_name("parameters")
        if params_node is not None:
            self._emit_params_into_defined_vars(params_node, func_id, ctx)

        body = node.child_by_field_name("body")
        if body is not None:
            self._visit_block(body, ctx)
        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_method_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle 'func (recv Type) MethodName(params) returnType { ... }'.

        Methods are emitted as FUNCTION nodes scoped to the module. The
        receiver type is available at resolve_calls time via name matching.
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        method_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        # Emit the method without params so we can register each parameter's
        # NodeId in defined_vars, enabling identifier lookups inside the body.
        func_id = ctx.emitter.emit_function(method_name, loc, scope, params=None)

        ctx.scope_stack.append(func_id)
        ctx.defined_vars.push()

        params_node = node.child_by_field_name("parameters")
        if params_node is not None:
            self._emit_params_into_defined_vars(params_node, func_id, ctx)

        body = node.child_by_field_name("body")
        if body is not None:
            self._visit_block(body, ctx)
        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _emit_params_into_defined_vars(
        self,
        params_node: tree_sitter.Node,
        func_id: NodeId,
        ctx: _VisitContext,
    ) -> None:
        """Emit PARAMETER nodes and register their NodeIds in defined_vars.

        This ensures that parameter names referenced inside the function body
        resolve to their NodeIds when building data-flow edges.
        """
        position = 0
        for child in params_node.children:
            if child.type == "parameter_declaration":
                identifiers = [c for c in child.children if c.type == "identifier"]
                for id_node in identifiers:
                    name = self._node_text(id_node, ctx.source)
                    loc = self._location(id_node, ctx.file_path)
                    param_id = ctx.emitter.emit_parameter(name, loc, func_id, position=position)
                    ctx.defined_vars[name] = param_id
                    position += 1
            elif child.type == "variadic_parameter_declaration":
                for id_node in child.children:
                    if id_node.type == "identifier":
                        name = self._node_text(id_node, ctx.source)
                        loc = self._location(id_node, ctx.file_path)
                        param_id = ctx.emitter.emit_parameter(
                            name, loc, func_id, position=position
                        )
                        ctx.defined_vars[name] = param_id
                        position += 1

    def _visit_block(self, node: tree_sitter.Node, ctx: _VisitContext) -> None:
        """Visit a block (function body). Recurse into statement_list."""
        for child in node.children:
            if child.type == "statement_list":
                for stmt in child.children:
                    self._visit_statement(stmt, ctx)
            elif child.type not in ("{", "}"):
                self._visit_statement(child, ctx)

    def _visit_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        handler = _STMT_HANDLERS.get(node.type)
        if handler is not None:
            handler(self, node, ctx)
        else:
            # Recurse for unrecognized statement types (e.g. labeled, defer, go)
            for child in node.children:
                self._visit_node(child, ctx)

    def _visit_short_var_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle 'x := expr'."""
        lhs = node.child_by_field_name("left")
        rhs = node.child_by_field_name("right")
        if lhs is None:
            return

        scope = ctx.current_scope
        # expression_list on the left may have multiple identifiers (a, b := ...)
        for id_node in _expression_list_identifiers(lhs):
            var_name = self._node_text(id_node, ctx.source)
            loc = self._location(id_node, ctx.file_path)
            var_id = ctx.emitter.emit_variable(var_name, loc, scope)
            ctx.defined_vars[var_name] = var_id

        # Process RHS for calls and data flow into the last emitted var
        if rhs is not None:
            rhs_ids = self._visit_expression_list(rhs, ctx)
            # Wire first RHS to first LHS variable (simplified)
            id_nodes = _expression_list_identifiers(lhs)
            for i, id_node in enumerate(id_nodes):
                var_name = self._node_text(id_node, ctx.source)
                var_id = ctx.defined_vars.get(var_name)
                if var_id is not None and i < len(rhs_ids) and rhs_ids[i] is not None:
                    ctx.emitter.emit_definition(var_id, rhs_ids[i])
                    ctx.emitter.emit_data_flow(rhs_ids[i], var_id)

    def _visit_var_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle 'var x Type = expr' (both top-level and local)."""
        for child in node.children:
            if child.type == "var_spec":
                self._visit_var_spec(child, ctx)

    def _visit_var_spec(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        scope = ctx.current_scope
        rhs = node.child_by_field_name("value")

        for child in node.children:
            if child.type == "identifier":
                var_name = self._node_text(child, ctx.source)
                loc = self._location(child, ctx.file_path)
                var_id = ctx.emitter.emit_variable(var_name, loc, scope)
                ctx.defined_vars[var_name] = var_id

                if rhs is not None:
                    rhs_ids = self._visit_expression_list(rhs, ctx)
                    if rhs_ids and rhs_ids[0] is not None:
                        ctx.emitter.emit_definition(var_id, rhs_ids[0])
                        ctx.emitter.emit_data_flow(rhs_ids[0], var_id)
                break  # one identifier per var_spec

    def _visit_assignment_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle 'x = expr' (reassignment, not declaration)."""
        lhs = node.child_by_field_name("left")
        rhs = node.child_by_field_name("right")
        if lhs is None:
            return

        scope = ctx.current_scope
        lhs_var_ids: list[NodeId | None] = []
        for id_node in _expression_list_identifiers(lhs):
            var_name = self._node_text(id_node, ctx.source)
            # Reuse existing var or create a new one
            var_id = ctx.defined_vars.get(var_name)
            if var_id is None:
                loc = self._location(id_node, ctx.file_path)
                var_id = ctx.emitter.emit_variable(var_name, loc, scope)
                ctx.defined_vars[var_name] = var_id
            lhs_var_ids.append(var_id)

        if rhs is not None:
            rhs_ids = self._visit_expression_list(rhs, ctx)
            for i, var_id in enumerate(lhs_var_ids):
                if var_id is not None and i < len(rhs_ids) and rhs_ids[i] is not None:
                    ctx.emitter.emit_definition(var_id, rhs_ids[i])
                    ctx.emitter.emit_data_flow(rhs_ids[i], var_id)

    def _visit_expression_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        for child in node.children:
            self._visit_expression(child, ctx)

    def _visit_return_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope
        ret_id = ctx.emitter.emit_return(loc, scope)

        for child in node.children:
            if child.type == "expression_list":
                ids = self._visit_expression_list(child, ctx)
                for eid in ids:
                    if eid is not None:
                        ctx.emitter.emit_data_flow(eid, ret_id)

    def _visit_import_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        for child in node.children:
            if child.type == "import_spec":
                self._emit_import_spec(child, loc, scope, ctx)
            elif child.type == "import_spec_list":
                for spec in child.children:
                    if spec.type == "import_spec":
                        self._emit_import_spec(spec, loc, scope, ctx)

    def _emit_import_spec(
        self,
        spec: tree_sitter.Node,
        loc: Any,
        scope: NodeId,
        ctx: _VisitContext,
    ) -> None:
        """Emit a single import spec node."""
        module_name = ""
        for child in spec.children:
            if child.type == "interpreted_string_literal":
                # Extract the content between quotes
                for sub in child.children:
                    if sub.type == "interpreted_string_literal_content":
                        module_name = self._node_text(sub, ctx.source)
        if module_name:
            ctx.emitter.emit_import(module_name, [module_name], loc, scope)

    def _visit_if_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        consequence = node.child_by_field_name("consequence")
        alternative = node.child_by_field_name("alternative")
        has_else = alternative is not None

        branch_id = ctx.emitter.emit_branch_node("if", loc, scope, has_else=has_else)

        # Visit init statement if present (e.g. if x := foo(); x > 0 { ... })
        initializer = node.child_by_field_name("initializer")
        if initializer is not None:
            self._visit_statement(initializer, ctx)

        # Visit condition
        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)

        # Visit consequence block
        if consequence is not None:
            ctx.scope_stack.append(branch_id)
            self._visit_block(consequence, ctx)
            ctx.scope_stack.pop()

        # Visit alternative (else block or else if)
        if alternative is not None:
            ctx.scope_stack.append(branch_id)
            if alternative.type == "block":
                self._visit_block(alternative, ctx)
            else:
                self._visit_statement(alternative, ctx)
            ctx.scope_stack.pop()

    def _visit_for_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle Go's single 'for' loop (covers for, while-style, range)."""
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        # Detect range clause for iterator variable
        iterator_var: str | None = None
        for child in node.children:
            if child.type == "range_clause":
                left = child.child_by_field_name("left")
                if left is not None:
                    ids = _expression_list_identifiers(left)
                    if ids:
                        iterator_var = self._node_text(ids[0], ctx.source)
            elif child.type == "for_clause":
                # Classic C-style for: look at init for variable name
                init = child.child_by_field_name("initializer")
                if init is not None and init.type == "short_var_declaration":
                    lhs = init.child_by_field_name("left")
                    if lhs is not None:
                        ids = _expression_list_identifiers(lhs)
                        if ids:
                            iterator_var = self._node_text(ids[0], ctx.source)

        loop_id = ctx.emitter.emit_loop_node("for", loc, scope, iterator_var=iterator_var)

        # Emit loop variable if present
        if iterator_var is not None:
            # It may already be emitted via short_var_declaration inside for_clause;
            # only emit here if it's a range loop
            for child in node.children:
                if child.type == "range_clause":
                    left = child.child_by_field_name("left")
                    if left is not None:
                        for id_node in _expression_list_identifiers(left):
                            name = self._node_text(id_node, ctx.source)
                            var_loc = self._location(id_node, ctx.file_path)
                            var_id = ctx.emitter.emit_variable(name, var_loc, loop_id)
                            ctx.defined_vars[name] = var_id

        # Visit body
        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            self._visit_block(body, ctx)
            ctx.scope_stack.pop()

    # -- Expression visitor ---------------------------------------------------

    def _visit_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Visit an expression; return the emitted NodeId or None."""
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

        if node.type == "selector_expression":
            # e.g., fmt.Println or p.X — return None; handled in call_expression
            return None

        if node.type in ("binary_expression", "unary_expression"):
            for child in node.children:
                if child.is_named:
                    self._visit_expression(child, ctx)
            return None

        if node.type == "parenthesized_expression":
            for child in node.children:
                if child.is_named:
                    return self._visit_expression(child, ctx)
            return None

        # Recurse into named children for unknown expression types
        for child in node.children:
            if child.is_named:
                self._visit_expression(child, ctx)
        return None

    def _visit_expression_list(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> list[NodeId | None]:
        """Visit an expression_list node; return list of NodeIds."""
        results: list[NodeId | None] = []
        for child in node.children:
            if child.is_named:
                results.append(self._visit_expression(child, ctx))
        return results

    def _visit_call_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
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


# -- Handler dispatch tables --------------------------------------------------

_NODE_HANDLERS: dict[str, Any] = {
    "type_declaration": GoVisitor._visit_type_declaration,
    "function_declaration": GoVisitor._visit_function_declaration,
    "method_declaration": GoVisitor._visit_method_declaration,
    "import_declaration": GoVisitor._visit_import_declaration,
    "var_declaration": GoVisitor._visit_var_declaration,
}

_STMT_HANDLERS: dict[str, Any] = {
    "short_var_declaration": GoVisitor._visit_short_var_declaration,
    "var_declaration": GoVisitor._visit_var_declaration,
    "assignment_statement": GoVisitor._visit_assignment_statement,
    "expression_statement": GoVisitor._visit_expression_statement,
    "return_statement": GoVisitor._visit_return_statement,
    "if_statement": GoVisitor._visit_if_statement,
    "for_statement": GoVisitor._visit_for_statement,
}


# -- Helpers ------------------------------------------------------------------


def _make_calls_edge(call_id: NodeId, func_id: NodeId) -> Any:
    from treeloom.model.edges import CpgEdge

    return CpgEdge(source=call_id, target=func_id, kind=EdgeKind.CALLS)


def _extract_param_names(
    params_node: tree_sitter.Node, source: bytes
) -> list[str]:
    """Extract parameter names from a Go parameter_list node."""
    names: list[str] = []
    for child in params_node.children:
        if child.type == "parameter_declaration":
            # Parameters can be: 'x int', 'x, y int', or just 'int' (unnamed)
            identifiers = [c for c in child.children if c.type == "identifier"]
            for id_node in identifiers:
                name = id_node.text.decode("utf-8", errors="replace")
                names.append(name)
        elif child.type == "variadic_parameter_declaration":
            for id_node in child.children:
                if id_node.type == "identifier":
                    name = id_node.text.decode("utf-8", errors="replace")
                    names.append(name)
    return names


def _extract_receiver_type(
    receiver_list: tree_sitter.Node, source: bytes
) -> str | None:
    """Extract the base type name from a method receiver parameter list."""
    for child in receiver_list.children:
        if child.type == "parameter_declaration":
            for sub in child.children:
                if sub.type == "type_identifier":
                    return sub.text.decode("utf-8", errors="replace")
                if sub.type == "pointer_type":
                    for inner in sub.children:
                        if inner.type == "type_identifier":
                            return inner.text.decode("utf-8", errors="replace")
    return None


def _expression_list_identifiers(
    node: tree_sitter.Node,
) -> list[tree_sitter.Node]:
    """Return all top-level identifier nodes in an expression_list."""
    if node.type == "expression_list":
        return [c for c in node.children if c.type == "identifier"]
    if node.type == "identifier":
        return [node]
    return []
