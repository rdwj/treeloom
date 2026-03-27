"""Python language visitor for tree-sitter AST to CPG conversion."""

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
        """Link CALL nodes to FUNCTION definitions.

        Uses inferred receiver types and MRO traversal for method calls,
        falling back to name-based matching for plain function calls.
        """
        functions: dict[str, list[CpgNode]] = {}
        for n in cpg.nodes(kind=NodeKind.FUNCTION):
            functions.setdefault(n.name, []).append(n)

        # Build class hierarchy and method index for type-based resolution
        class_nodes: dict[str, CpgNode] = {}
        for n in cpg.nodes(kind=NodeKind.CLASS):
            class_nodes[n.name] = n

        method_index: dict[tuple[str, str], CpgNode] = {}
        for fn in cpg.nodes(kind=NodeKind.FUNCTION):
            scope = cpg.scope_of(fn.id)
            if scope is not None and scope.kind == NodeKind.CLASS:
                method_index[(scope.name, fn.name)] = fn

        resolved: list[tuple[NodeId, NodeId]] = []

        for call_node in cpg.nodes(kind=NodeKind.CALL):
            target = call_node.name
            fn: CpgNode | None = None

            # Try type-based resolution first for method calls
            receiver_type = call_node.attrs.get("receiver_inferred_type")
            if receiver_type is not None and "." in target:
                method_name = target.rsplit(".", 1)[-1]
                fn = self._resolve_method_via_mro(
                    receiver_type, method_name,
                    method_index, class_nodes,
                )

            # Fall back to name-based resolution
            if fn is None:
                fn = self._resolve_single_call(
                    call_node, target, functions, cpg,
                )

            if fn is None and "." in target:
                short_name = target.rsplit(".", 1)[-1]
                fn = self._resolve_single_call(
                    call_node, short_name, functions, cpg,
                )

            if fn is not None:
                cpg.add_edge(_make_calls_edge(call_node.id, fn.id))
                resolved.append((call_node.id, fn.id))

        return resolved

    @staticmethod
    def _resolve_method_via_mro(
        class_name: str,
        method_name: str,
        method_index: dict[tuple[str, str], CpgNode],
        class_nodes: dict[str, CpgNode],
    ) -> CpgNode | None:
        """Resolve a method by walking the class MRO (left-to-right BFS)."""
        visited: set[str] = set()
        queue = [class_name]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            result = method_index.get((current, method_name))
            if result is not None:
                return result

            node = class_nodes.get(current)
            if node is not None:
                bases = node.attrs.get("bases", [])
                queue.extend(bases)
        return None

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

        # Extract base class names from superclasses (argument_list)
        bases: list[str] = []
        superclasses = node.child_by_field_name("superclasses")
        if superclasses is not None:
            for child in superclasses.children:
                if child.type == "identifier":
                    bases.append(self._node_text(child, ctx.source))
                elif child.type == "attribute":
                    bases.append(self._node_text(child, ctx.source))

        class_id = ctx.emitter.emit_class(
            class_name, loc, scope, bases=bases or None,
        )
        ctx.scope_stack.append(class_id)
        ctx.defined_vars.push()

        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)

        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_decorated_definition(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle @decorator-prefixed function or class definitions.

        Collects decorator names and visits any decorator call expressions for
        DFG purposes, then visits the inner function/class definition with the
        collected decorator names stored in attrs.
        """
        decorator_names: list[str] = []

        for child in node.children:
            if child.type == "decorator":
                # The decorator body is either a plain identifier or a call.
                # Collect the name text for attrs and visit any call for DFG.
                for dec_child in child.children:
                    if dec_child.type == "call":
                        decorator_names.append(
                            self._extract_call_name(dec_child) or ""
                        )
                        # Visit the call so that e.g. @app.route('/path') is
                        # recorded in the graph.
                        self._visit_call_expression(dec_child, ctx)
                    elif dec_child.type in ("identifier", "attribute"):
                        decorator_names.append(
                            self._node_text(dec_child, ctx.source)
                        )
            elif child.type in (
                "function_definition",
                "async_function_definition",
                "class_definition",
            ):
                # Stash decorator names so _visit_function_definition can pick
                # them up when emitting the function node attrs.
                ctx.pending_decorators = decorator_names
                self._visit_node(child, ctx)
                ctx.pending_decorators = []

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

        # Emit the function node without params -- we emit parameters manually
        # below so we can register their NodeIds in defined_vars for later
        # identifier lookups (e.g. when a parameter is used in a .format() call).
        decorators = ctx.pending_decorators or None
        ctx.pending_decorators = []
        func_id = ctx.emitter.emit_function(
            func_name, loc, scope, params=None, is_async=is_async,
            decorators=decorators,
        )

        # Now visit the body within the function scope
        ctx.scope_stack.append(func_id)
        ctx.defined_vars.push()

        # Emit parameters and register them in defined_vars so identifier
        # references (in calls, returns, assignments) resolve correctly.
        params_node = node.child_by_field_name("parameters")
        if params_node is not None:
            position = 0
            for child in params_node.children:
                param_name = _extract_single_param_name(child, ctx.source)
                if param_name is not None:
                    param_loc = self._location(child, ctx.file_path)
                    param_id = ctx.emitter.emit_parameter(
                        param_name, param_loc, func_id, position=position
                    )
                    ctx.defined_vars[param_name] = param_id
                    position += 1

        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)

        ctx.defined_vars.pop()
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

        # Infer type from constructor call on RHS: x = Dog()
        # Only for simple identifier LHS (not tuple unpacking, etc.)
        inferred_type: str | None = None
        if (
            left.type == "identifier"
            and right is not None
            and right.type == "call"
        ):
            call_name = self._extract_call_name(right)
            if call_name is not None:
                short = (
                    call_name.rsplit(".", 1)[-1]
                    if "." in call_name
                    else call_name
                )
                inferred_type = short
                ctx.var_types[var_name] = short

        var_id = ctx.emitter.emit_variable(
            var_name, loc, scope, inferred_type=inferred_type,
        )

        # Track this variable definition for later USED_BY resolution
        ctx.defined_vars[var_name] = var_id

        # Process the RHS for calls, literals, and data flow
        if right is not None:
            rhs_id = self._visit_expression(right, ctx)
            if rhs_id is not None:
                ctx.emitter.emit_definition(var_id, rhs_id)
                ctx.emitter.emit_data_flow(rhs_id, var_id)

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
        aliases: dict[str, str] = {}

        for child in node.children:
            if child.type == "dotted_name":
                names.append(self._node_text(child, ctx.source))
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node:
                    orig = self._node_text(name_node, ctx.source)
                    names.append(orig)
                    if alias_node:
                        aliases[orig] = self._node_text(alias_node, ctx.source)

        module_name = names[0] if names else ""
        ctx.emitter.emit_import(
            module_name, names, loc, scope, is_from=False,
            aliases=aliases or None,
        )

    def _visit_import_from_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        scope = ctx.current_scope

        module_name = ""
        imported_names: list[str] = []
        aliases: dict[str, str] = {}
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
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node:
                    orig = self._node_text(name_node, ctx.source)
                    imported_names.append(orig)
                    if alias_node:
                        aliases[orig] = self._node_text(alias_node, ctx.source)

        ctx.emitter.emit_import(
            module_name, imported_names, loc, scope, is_from=True,
            aliases=aliases or None,
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

            # Check for f-string interpolation: if the string contains
            # {expr} interpolations, the embedded variables flow into the
            # resulting string.  We emit a pseudo-call node instead of a
            # plain literal so taint propagates through.
            if node.type in ("string", "concatenated_string"):
                interp_ids = self._collect_interpolation_ids(node, ctx)
                if interp_ids:
                    fstr_id = ctx.emitter.emit_call(
                        "f-string", loc, ctx.current_scope, args=None
                    )
                    for iid in interp_ids:
                        ctx.emitter.emit_data_flow(iid, fstr_id)
                    return fstr_id

            return ctx.emitter.emit_literal(value, lit_type, loc, ctx.current_scope)

        if node.type == "identifier":
            # This is a variable reference. Look up its definition for USED_BY.
            var_name = self._node_text(node, ctx.source)
            defined_id = ctx.defined_vars.get(var_name)
            return defined_id

        if node.type == "attribute":
            # e.g., obj.attr used as a standalone expression (not as the
            # function part of a call -- that path goes through
            # _visit_call_expression).  Emit a VARIABLE node representing
            # the attribute access so data flow can propagate through it.
            attr_text = self._node_text(node, ctx.source)
            loc = self._location(node, ctx.file_path)

            # Field sensitivity: register the full dotted name in defined_vars
            # so that `request.args` and `request.form` are tracked as
            # separate variables.  Look up the full text first so that any
            # prior definition of the dotted name is reused rather than
            # creating a duplicate node.
            existing_id = ctx.defined_vars.get(attr_text)
            if existing_id is not None:
                return existing_id

            attr_id = ctx.emitter.emit_variable(attr_text, loc, ctx.current_scope)
            ctx.defined_vars[attr_text] = attr_id

            # Wire data from the receiver object.  Handle three receiver types:
            #   1. bare identifier (e.g. `request.form`)
            #   2. attribute access (e.g. `request.form.data`) — recurse
            #   3. subscript (e.g. `obj['key'].attr`) — recurse
            obj_node = node.child_by_field_name("object")
            if obj_node is not None:
                if obj_node.type == "identifier":
                    obj_name = self._node_text(obj_node, ctx.source)
                    obj_def_id = ctx.defined_vars.get(obj_name)
                    if obj_def_id is not None:
                        ctx.emitter.emit_data_flow(obj_def_id, attr_id)
                elif obj_node.type in ("attribute", "subscript"):
                    receiver_id = self._visit_expression(obj_node, ctx)
                    if receiver_id is not None:
                        ctx.emitter.emit_data_flow(receiver_id, attr_id)
            return attr_id

        if node.type == "subscript":
            # e.g., config['database'] or session['username'].
            # Emit a VARIABLE node representing the subscript result so that
            # taint can propagate: object -> subscript_var -> downstream uses.
            sub_text = self._node_text(node, ctx.source)
            loc = self._location(node, ctx.file_path)
            sub_id = ctx.emitter.emit_variable(sub_text, loc, ctx.current_scope)
            # Wire data from the object being subscripted, if it is a
            # resolvable identifier.
            val_node = node.child_by_field_name("value")
            if val_node is not None:
                if val_node.type == "identifier":
                    val_name = self._node_text(val_node, ctx.source)
                    val_def_id = ctx.defined_vars.get(val_name)
                    if val_def_id is not None:
                        ctx.emitter.emit_data_flow(val_def_id, sub_id)
                elif val_node.type in ("attribute", "subscript"):
                    val_id = self._visit_expression(val_node, ctx)
                    if val_id is not None:
                        ctx.emitter.emit_data_flow(val_id, sub_id)
            # Also visit the subscript key so any nested calls/refs are picked up.
            key_node = node.child_by_field_name("subscript")
            if key_node is not None:
                self._visit_expression(key_node, ctx)
            return sub_id

        if node.type == "binary_operator":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            operator = node.child_by_field_name("operator")

            # Detect %-formatting: "format string" % value
            is_percent_fmt = False
            if operator is not None:
                is_percent_fmt = self._node_text(operator, ctx.source) == "%"
            else:
                # Fallback: scan unnamed children for the % token
                for child in node.children:
                    if not child.is_named and child.type == "%":
                        is_percent_fmt = True
                        break

            if is_percent_fmt:
                left_id = self._visit_expression(left, ctx) if left else None
                # Emit a pseudo-call node to represent the % operation so
                # taint can flow from the RHS operand(s) through the result.
                loc = self._location(node, ctx.file_path)
                fmt_id = ctx.emitter.emit_call(
                    "%", loc, ctx.current_scope, args=None
                )
                if left_id is not None:
                    ctx.emitter.emit_data_flow(left_id, fmt_id)

                # The RHS may be a single value or a tuple of values.
                # Wire each element individually so taint propagates from
                # every substitution argument.
                if right is not None:
                    rhs_ids = self._collect_expression_ids(right, ctx)
                    for rid in rhs_ids:
                        ctx.emitter.emit_data_flow(rid, fmt_id)

                return fmt_id

            # Non-% binary operators: visit both sides for nested calls/refs
            left_id = self._visit_expression(left, ctx) if left else None
            if right:
                self._visit_expression(right, ctx)
            return left_id

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

        if node.type == "keyword_argument":
            # e.g., func(name=value) — propagate taint from the value expression
            # to the call.  The keyword name itself is not a data source.
            val_node = node.child_by_field_name("value")
            if val_node is not None:
                return self._visit_expression(val_node, ctx)
            return None

        if node.type == "dictionary_splat":
            # e.g., func(**kwargs) — taint on kwargs propagates into the call.
            for child in node.children:
                if child.is_named and child.type == "identifier":
                    var_name = self._node_text(child, ctx.source)
                    return ctx.defined_vars.get(var_name)
            return None

        if node.type in (
            "list_comprehension",
            "set_comprehension",
            "generator_expression",
        ):
            # Visit the iterable expression and the element expression so calls
            # and variable references inside comprehensions are picked up.
            for child in node.children:
                if child.type == "for_in_clause":
                    iterable = child.child_by_field_name("right")
                    if iterable is not None:
                        self._visit_expression(iterable, ctx)
                elif child.is_named and child.type not in (
                    "for_in_clause",
                    "if_clause",
                ):
                    self._visit_expression(child, ctx)
            return None

        if node.type == "dictionary_comprehension":
            for child in node.children:
                if child.type == "for_in_clause":
                    iterable = child.child_by_field_name("right")
                    if iterable is not None:
                        self._visit_expression(iterable, ctx)
                elif child.is_named:
                    if child.type in ("key", "value"):
                        self._visit_expression(child, ctx)
            return None

        # For other expression types, recurse into named children
        for child in node.children:
            if child.is_named:
                self._visit_expression(child, ctx)

        return None

    def _collect_interpolation_ids(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> list[NodeId]:
        """Collect NodeIds for variables referenced inside f-string interpolations."""
        ids: list[NodeId] = []
        for child in node.children:
            if child.type == "interpolation":
                for inner in child.children:
                    if inner.is_named:
                        expr_id = self._visit_expression(inner, ctx)
                        if expr_id is not None:
                            ids.append(expr_id)
            elif child.is_named:
                # Recurse into concatenated_string parts
                ids.extend(self._collect_interpolation_ids(child, ctx))
        return ids

    def _collect_expression_ids(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> list[NodeId]:
        """Visit an expression and return all leaf NodeIds.

        For tuple/list nodes this visits each element and returns all IDs.
        For a single expression it returns a one-element list (or empty if
        no node was emitted).
        """
        if node.type in ("tuple", "list"):
            ids: list[NodeId] = []
            for child in node.children:
                if child.is_named:
                    eid = self._visit_expression(child, ctx)
                    if eid is not None:
                        ids.append(eid)
            return ids
        eid = self._visit_expression(node, ctx)
        return [eid] if eid is not None else []

    def _visit_call_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Handle a function call expression."""
        func_node = node.child_by_field_name("function")
        if func_node is None:
            return None

        # When the function is an attribute access (e.g. `obj.method`), we
        # handle three receiver cases to wire data flow correctly:
        #
        # 1. Receiver is a call (chained method call, e.g. `foo().bar()`):
        #    Visit the inner call and wire its result to the outer call.
        #    Use "<inner_func>.<method>" as the name for the outer call.
        #
        # 2. Receiver is an attribute (e.g. `request.form.get()`):
        #    Visit the receiver attribute (which itself may recurse) and wire
        #    data flow from that VARIABLE node to this call.  Use the full
        #    dotted text (e.g. "request.form.get") as the call name.
        #
        # 3. Receiver is a simple identifier or anything else:
        #    Use the full attribute text as the call name (existing behaviour).
        receiver_call_id: NodeId | None = None
        if func_node.type == "attribute":
            obj_node = func_node.child_by_field_name("object")
            attr_node = func_node.child_by_field_name("attribute")
            if obj_node is not None and obj_node.type == "call":
                # Case 1: chained call — recursively visit the inner call.
                receiver_call_id = self._visit_expression(obj_node, ctx)
                method_name = (
                    self._node_text(attr_node, ctx.source)
                    if attr_node is not None
                    else self._node_text(func_node, ctx.source)
                )
                inner_func_name = self._extract_call_name(obj_node)
                target_name = (
                    f"{inner_func_name}.{method_name}"
                    if inner_func_name
                    else method_name
                )
            elif obj_node is not None and obj_node.type == "attribute":
                # Case 2: receiver is itself an attribute (chained attribute).
                # Visit the receiver so it emits its VARIABLE node and wires
                # its own receiver chain, then use the full text as this call's name.
                receiver_call_id = self._visit_expression(obj_node, ctx)
                target_name = self._node_text(func_node, ctx.source)
            else:
                target_name = self._node_text(func_node, ctx.source)
        else:
            target_name = self._node_text(func_node, ctx.source)

        # Look up receiver's inferred type for method calls
        receiver_type: str | None = None
        if func_node.type == "attribute":
            obj = func_node.child_by_field_name("object")
            if obj is not None and obj.type == "identifier":
                receiver_name = self._node_text(obj, ctx.source)
                receiver_type = ctx.var_types.get(receiver_name)

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

        call_id = ctx.emitter.emit_call(
            target_name, loc, scope, args=arg_texts,
            receiver_inferred_type=receiver_type,
        )

        # Wire data flow from the chained receiver call (if any) to this call
        if receiver_call_id is not None:
            ctx.emitter.emit_data_flow(receiver_call_id, call_id)

        # Wire DATA_FLOWS_TO and USED_BY from argument variable defs to the call
        for i, arg_id in enumerate(arg_ids):
            if arg_id is not None:
                ctx.emitter.emit_data_flow(arg_id, call_id)
                if i < len(arg_is_var) and arg_is_var[i]:
                    ctx.emitter.emit_usage(arg_id, call_id)

        return call_id

    def _extract_call_name(self, call_node: tree_sitter.Node) -> str | None:
        """Extract the function/method name from a call node.

        Returns the text of the ``function`` child node, which is what
        ``_visit_call_expression`` uses as the call name.  Used to build
        composite names for chained calls without needing to look up already-
        emitted nodes.
        """
        func = call_node.child_by_field_name("function")
        if func is None:
            return None
        return func.text.decode("utf-8", errors="replace") if func.text else None


# -- Visit context (mutable state carried through the walk) -------------------


class _VisitContext:
    """Mutable state carried through the tree walk."""

    __slots__ = (
        "emitter",
        "file_path",
        "source",
        "scope_stack",
        "defined_vars",
        "pending_decorators",
        "var_types",
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
        self.pending_decorators: list[str] = []
        self.var_types: dict[str, str] = {}

    @property
    def current_scope(self) -> NodeId:
        return self.scope_stack[-1]


# -- Handler dispatch table ---------------------------------------------------

_NODE_HANDLERS: dict[str, Any] = {
    "class_definition": PythonVisitor._visit_class_definition,
    "decorated_definition": PythonVisitor._visit_decorated_definition,
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


def _extract_single_param_name(
    child: tree_sitter.Node, source: bytes
) -> str | None:
    """Extract a parameter name from a single tree-sitter parameters child node.

    Returns None for nodes that aren't parameter declarations (punctuation,
    'self', 'cls').
    """
    if child.type == "identifier":
        name = child.text.decode("utf-8", errors="replace")
        if name not in ("self", "cls"):
            return name
    elif child.type == "default_parameter":
        name_node = child.child_by_field_name("name")
        if name_node:
            name = name_node.text.decode("utf-8", errors="replace")
            if name not in ("self", "cls"):
                return name
    elif child.type == "typed_parameter":
        for sub in child.children:
            if sub.type == "identifier":
                name = sub.text.decode("utf-8", errors="replace")
                if name not in ("self", "cls"):
                    return name
                break
    elif child.type == "list_splat_pattern":
        for sub in child.children:
            if sub.type == "identifier":
                return "*" + sub.text.decode("utf-8", errors="replace")
    elif child.type == "dictionary_splat_pattern":
        for sub in child.children:
            if sub.type == "identifier":
                return "**" + sub.text.decode("utf-8", errors="replace")
    return None


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
