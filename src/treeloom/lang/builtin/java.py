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
        """Link CALL nodes to FUNCTION definitions.

        Uses inferred receiver types and MRO traversal for method calls,
        falling back to name-based matching for plain function calls.
        """
        fn_list = (
            function_nodes if function_nodes is not None
            else list(cpg.nodes(kind=NodeKind.FUNCTION))
        )
        functions: dict[str, list[CpgNode]] = {}
        for n in fn_list:
            functions.setdefault(n.name, []).append(n)

        # Build class hierarchy and method index for type-based resolution
        class_nodes: dict[str, CpgNode] = {}
        for n in cpg.nodes(kind=NodeKind.CLASS):
            class_nodes[n.name] = n

        method_index: dict[tuple[str, str], CpgNode] = {}
        for fn in fn_list:
            scope = cpg.scope_of(fn.id)
            if scope is not None and scope.kind == NodeKind.CLASS:
                method_index[(scope.name, fn.name)] = fn

        # Build import map: local_name -> (module_name, original_name)
        import_map: dict[str, tuple[str, str]] = {}
        for imp_node in cpg.nodes(kind=NodeKind.IMPORT):
            if imp_node.attrs.get("is_from"):
                module = imp_node.attrs.get("module", "")
                for imp_name in imp_node.attrs.get("names", []):
                    import_map[imp_name] = (module, imp_name)

        resolved: list[tuple[NodeId, NodeId]] = []
        for call_node in (call_nodes if call_nodes is not None else cpg.nodes(kind=NodeKind.CALL)):
            target = call_node.name
            fn: CpgNode | None = None

            # Try type-based resolution first for method calls
            receiver_type = call_node.attrs.get("receiver_inferred_type")
            if receiver_type is not None and "." in target:
                method_name = target.rsplit(".", 1)[-1]
                fn = self._resolve_method_via_mro(
                    receiver_type, method_name, method_index, class_nodes,
                )

            # Fall back to name-based resolution
            if fn is None:
                fn = _resolve_single_call(call_node, target, functions, cpg)

            if fn is None and "." in target:
                short_name = target.rsplit(".", 1)[-1]
                fn = _resolve_single_call(
                    call_node, short_name, functions, cpg,
                )

            # Try import-following
            if fn is None and target in import_map:
                imp_module, imp_name = import_map[target]
                imp_candidates = functions.get(imp_name, [])
                for candidate in imp_candidates:
                    scope = cpg.scope_of(candidate.id)
                    if scope is not None and scope.kind == NodeKind.MODULE:
                        mod_parts = imp_module.rsplit(".", 1)
                        if scope.name == imp_module or scope.name in mod_parts:
                            fn = candidate
                            break

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
        """Resolve a method by walking the class hierarchy (left-to-right BFS)."""
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
        # Extract base classes from extends/implements clauses
        bases: list[str] = []
        for child in node.children:
            if child.type in ("superclass", "super_interfaces"):
                for sub in child.children:
                    if sub.type in ("type_identifier", "generic_type", "scoped_type_identifier"):
                        bases.append(self._node_text(sub, ctx.source))
                    elif sub.type == "type_list":
                        for t in sub.children:
                            if t.type in ("type_identifier", "generic_type", "scoped_type_identifier"):
                                bases.append(self._node_text(t, ctx.source))
            elif child.type == "extends_interfaces":
                for sub in child.children:
                    if sub.type == "type_list":
                        for t in sub.children:
                            if t.type in ("type_identifier", "generic_type", "scoped_type_identifier"):
                                bases.append(self._node_text(t, ctx.source))
        class_id = ctx.emitter.emit_class(
            self._node_text(name_node, ctx.source),
            self._location(node, ctx.file_path),
            ctx.current_scope,
            bases=bases or None,
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
        ctx.scope_stack.append(loop_id)
        init = node.child_by_field_name("init")
        if init is not None:
            self._visit_node(init, ctx)
        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)
        update = node.child_by_field_name("update")
        if update is not None:
            self._visit_expression(update, ctx)
        body = node.child_by_field_name("body")
        if body is not None:
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

    def _visit_field_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle class-level field declarations (e.g., `private int x = 5;`)."""
        type_ann: str | None = None
        for child in node.children:
            if child.type in ("variable_declarator", ";"):
                continue
            # Skip modifiers like public/private/static/final
            if child.type == "modifiers":
                continue
            if child.is_named:
                type_ann = self._node_text(child, ctx.source)
                break
        for child in node.children:
            if child.type == "variable_declarator":
                self._visit_variable_declarator(child, ctx, type_ann=type_ann)

    def _visit_switch_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle switch statements/expressions."""
        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)
        branch_id = ctx.emitter.emit_branch_node(
            "switch", self._location(node, ctx.file_path), ctx.current_scope,
            end_location=self._end_location(node, ctx.file_path),
        )
        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(branch_id)
            for child in body.children:
                if child.type == "switch_block_statement_group":
                    for stmt in child.children:
                        if stmt.type not in ("switch_label", ":"):
                            self._visit_node(stmt, ctx)
                elif child.type == "switch_rule":
                    for stmt in child.children:
                        if stmt.type not in ("switch_label", "->"):
                            self._visit_node(stmt, ctx)
                else:
                    self._visit_node(child, ctx)
            ctx.scope_stack.pop()

    def _visit_try_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle try/catch/finally blocks."""
        for child in node.children:
            if child.type == "block":
                # The try body
                for stmt in child.children:
                    self._visit_node(stmt, ctx)
            elif child.type == "catch_clause":
                self._visit_catch_clause(child, ctx)
            elif child.type == "finally_clause":
                for stmt in child.children:
                    if stmt.type == "block":
                        for s in stmt.children:
                            self._visit_node(s, ctx)

    def _visit_try_with_resources_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle try-with-resources (e.g., `try (var r = ...) { ... }`)."""
        for child in node.children:
            if child.type == "resource_specification":
                for resource in child.children:
                    if resource.type == "resource":
                        self._visit_resource(resource, ctx)
            elif child.type == "block":
                for stmt in child.children:
                    self._visit_node(stmt, ctx)
            elif child.type == "catch_clause":
                self._visit_catch_clause(child, ctx)
            elif child.type == "finally_clause":
                for stmt in child.children:
                    if stmt.type == "block":
                        for s in stmt.children:
                            self._visit_node(s, ctx)

    def _visit_catch_clause(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Visit a catch clause, emitting exception variable and body."""
        for child in node.children:
            if child.type == "catch_formal_parameter":
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    var_name = self._node_text(name_node, ctx.source)
                    var_id = ctx.emitter.emit_variable(
                        var_name,
                        self._location(name_node, ctx.file_path),
                        ctx.current_scope,
                        end_location=self._end_location(name_node, ctx.file_path),
                    )
                    ctx.defined_vars[var_name] = var_id
            elif child.type == "block":
                for stmt in child.children:
                    self._visit_node(stmt, ctx)

    def _visit_resource(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Visit a resource in try-with-resources (type name = expr)."""
        name_node = node.child_by_field_name("name")
        value_node = node.child_by_field_name("value")
        if name_node is None:
            return
        var_name = self._node_text(name_node, ctx.source)
        var_id = ctx.emitter.emit_variable(
            var_name,
            self._location(name_node, ctx.file_path),
            ctx.current_scope,
            end_location=self._end_location(name_node, ctx.file_path),
        )
        ctx.defined_vars[var_name] = var_id
        if value_node is not None:
            rhs_id = self._visit_expression(value_node, ctx)
            if rhs_id is not None:
                ctx.emitter.emit_definition(var_id, rhs_id)
                ctx.emitter.emit_data_flow(rhs_id, var_id)

    def _visit_do_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle do-while loops."""
        loop_id = ctx.emitter.emit_loop_node(
            "do_while", self._location(node, ctx.file_path), ctx.current_scope,
            end_location=self._end_location(node, ctx.file_path),
        )
        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            for child in body.children:
                self._visit_node(child, ctx)
            ctx.scope_stack.pop()
        condition = node.child_by_field_name("condition")
        if condition is not None:
            self._visit_expression(condition, ctx)

    def _visit_throw_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Visit thrown expression so calls/variables inside are emitted."""
        for child in node.children:
            if child.type in ("throw", ";"):
                continue
            if child.is_named:
                self._visit_expression(child, ctx)

    def _visit_static_initializer(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Visit static { ... } initializer block."""
        for child in node.children:
            if child.type == "block":
                for stmt in child.children:
                    self._visit_node(stmt, ctx)

    def _visit_synchronized_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Visit synchronized(expr) { ... } blocks."""
        for child in node.children:
            if child.type == "parenthesized_expression":
                self._visit_expression(child, ctx)
            elif child.type == "block":
                for stmt in child.children:
                    self._visit_node(stmt, ctx)

    def _visit_record_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle Java record declarations as CLASS nodes.

        Record components (e.g., ``record Point(int x, int y)``) are emitted
        as PARAMETER nodes scoped to the record class.
        """
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
        # Emit record components as parameters
        params_node = node.child_by_field_name("parameters")
        if params_node is not None:
            self._emit_typed_params(params_node, class_id, ctx)
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)
        ctx.defined_vars.pop()
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
        if node.type == "update_expression":
            # e.g., i++, --j — find the operand and return its NodeId
            for child in node.children:
                if child.type == "identifier":
                    return ctx.defined_vars.get(self._node_text(child, ctx.source))
            return None
        if node.type == "array_access":
            # e.g., args[0] — propagate taint from the array
            for child in node.named_children:
                return self._visit_expression(child, ctx)
            return None
        if node.type == "ternary_expression":
            condition = node.child_by_field_name("condition")
            consequence = node.child_by_field_name("consequence")
            alternative = node.child_by_field_name("alternative")
            if condition is not None:
                self._visit_expression(condition, ctx)
            cons_id = (
                self._visit_expression(consequence, ctx)
                if consequence is not None else None
            )
            alt_id = (
                self._visit_expression(alternative, ctx)
                if alternative is not None else None
            )
            # Emit a synthetic merge node so both branches propagate taint
            if cons_id is not None or alt_id is not None:
                merge_id = ctx.emitter.emit_call(
                    "<ternary>",
                    self._location(node, ctx.file_path),
                    ctx.current_scope,
                    end_location=self._end_location(node, ctx.file_path),
                )
                if cons_id is not None:
                    ctx.emitter.emit_data_flow(cons_id, merge_id)
                if alt_id is not None:
                    ctx.emitter.emit_data_flow(alt_id, merge_id)
                return merge_id
            return None
        if node.type == "method_reference":
            return self._visit_method_reference(node, ctx)
        if node.type == "field_access":
            return self._visit_field_access(node, ctx)
        if node.type == "unary_expression":
            # e.g., !flag, -x — visit the operand
            operand = node.child_by_field_name("operand")
            if operand is not None:
                return self._visit_expression(operand, ctx)
            return None
        if node.type == "instanceof_expression":
            # Visit the LHS so DFG propagates; the type check doesn't produce a value
            left = node.child_by_field_name("left")
            if left is not None:
                return self._visit_expression(left, ctx)
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

        # Find operator (the unnamed child between operands)
        op = None
        for child in node.children:
            if not child.is_named:
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
        """Emit a FUNCTION node for a lambda expression with parameters."""
        # Generate a synthetic name like `lambda$3$5` from the location
        loc = self._location(node, ctx.file_path)
        lambda_name = f"lambda${loc.line}${loc.column}"

        func_id = ctx.emitter.emit_function(
            lambda_name,
            loc,
            ctx.current_scope,
            params=None,
            end_location=self._end_location(node, ctx.file_path),
            source_text=self._node_text(node, ctx.source),
        )
        ctx.scope_stack.append(func_id)
        ctx.defined_vars.push()

        # Emit parameters: either `(Type x, Type y)` via formal_parameters
        # or a single `inferred_parameters` identifier like `x ->`
        for child in node.children:
            if child.type == "->":
                break
            if child.type == "formal_parameters":
                self._emit_typed_params(child, func_id, ctx)
            elif child.type == "inferred_parameters":
                pos = 0
                for param_child in child.children:
                    if param_child.type == "identifier":
                        pname = self._node_text(param_child, ctx.source)
                        ploc = self._location(param_child, ctx.file_path)
                        pid = ctx.emitter.emit_parameter(
                            pname, ploc, func_id, position=pos,
                            end_location=self._end_location(param_child, ctx.file_path),
                        )
                        ctx.defined_vars[pname] = pid
                        pos += 1
            elif child.type == "identifier":
                # Single unparenthesized param: `x -> ...`
                pname = self._node_text(child, ctx.source)
                ploc = self._location(child, ctx.file_path)
                pid = ctx.emitter.emit_parameter(
                    pname, ploc, func_id, position=0,
                    end_location=self._end_location(child, ctx.file_path),
                )
                ctx.defined_vars[pname] = pid

        # Visit body (after the `->` token)
        result: NodeId | None = None
        after_arrow = False
        for child in node.children:
            if child.type == "->":
                after_arrow = True
                continue
            if after_arrow:
                if child.type == "block":
                    for stmt in child.children:
                        self._visit_node(stmt, ctx)
                elif child.is_named:
                    result = self._visit_expression(child, ctx)

        ctx.defined_vars.pop()
        ctx.scope_stack.pop()
        return result

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
        # Infer receiver type for type-based resolution
        receiver_type: str | None = None
        if obj_node is not None:
            obj_text = self._node_text(obj_node, ctx.source)
            receiver_type = ctx.var_types.get(obj_text)
        args_node = node.child_by_field_name("arguments")
        arg_texts, arg_ids, arg_is_var = self._collect_args(args_node, ctx)
        call_id = ctx.emitter.emit_call(
            target_name, self._location(node, ctx.file_path),
            ctx.current_scope, args=arg_texts,
            receiver_inferred_type=receiver_type,
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

    def _visit_method_reference(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Handle method references (e.g., String::toUpperCase, this::process)."""
        # Children: type/expression, "::", method_name
        parts: list[str] = []
        for child in node.children:
            if child.type == "::":
                continue
            if child.is_named:
                parts.append(self._node_text(child, ctx.source))
        target_name = ".".join(parts) if parts else self._node_text(node, ctx.source)
        return ctx.emitter.emit_call(
            target_name,
            self._location(node, ctx.file_path),
            ctx.current_scope,
            end_location=self._end_location(node, ctx.file_path),
        )

    def _visit_field_access(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Handle field access (e.g., obj.field, this.value)."""
        obj_node = node.child_by_field_name("object")
        field_node = node.child_by_field_name("field")
        if field_node is None:
            return None
        obj_text = self._node_text(obj_node, ctx.source) if obj_node else ""
        field_text = self._node_text(field_node, ctx.source)
        dotted_name = f"{obj_text}.{field_text}" if obj_text else field_text

        existing = ctx.defined_vars.get(dotted_name)
        if existing is not None:
            return existing

        # Emit a new variable for the field access and register it
        var_id = ctx.emitter.emit_variable(
            dotted_name,
            self._location(node, ctx.file_path),
            ctx.current_scope,
            end_location=self._end_location(node, ctx.file_path),
        )
        ctx.defined_vars[dotted_name] = var_id

        # Wire DFG from the object if it's in scope
        if obj_node is not None:
            obj_id = ctx.defined_vars.get(self._node_text(obj_node, ctx.source))
            if obj_id is not None:
                ctx.emitter.emit_data_flow(obj_id, var_id)
        return var_id

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
        # Infer type from declared type or constructor call on RHS
        inferred_type = type_ann
        value_node = node.child_by_field_name("value")
        if value_node is not None and value_node.type == "object_creation_expression":
            for child in value_node.children:
                if child.type in ("type_identifier", "generic_type", "scoped_type_identifier"):
                    inferred_type = self._node_text(child, ctx.source)
                    break
        if inferred_type is not None:
            # Strip generics for type tracking (e.g., "List<String>" -> "List")
            base_type = inferred_type.split("<")[0].split("[")[0]
            ctx.var_types[var_name] = base_type
        var_id = ctx.emitter.emit_variable(
            var_name, loc, ctx.current_scope,
            inferred_type=inferred_type,
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
                # Structure: type_identifier, "...", variable_declarator(name=identifier)
                decl = None
                type_text: str | None = None
                for sc in child.children:
                    if sc.type in ("type_identifier", "generic_type", "scoped_type_identifier"):
                        type_text = sc.text.decode("utf-8", errors="replace")
                    elif sc.type == "variable_declarator":
                        decl = sc
                if decl is not None:
                    vname_node = decl.child_by_field_name("name")
                    if vname_node is not None:
                        param_name = vname_node.text.decode("utf-8", errors="replace")
                        type_ann = f"{type_text}..." if type_text else None
                        loc = SourceLocation(
                            file=ctx.file_path,
                            line=vname_node.start_point.row + 1,
                            column=vname_node.start_point.column,
                        )
                        param_id = ctx.emitter.emit_parameter(
                            param_name, loc, func_id,
                            type_annotation=type_ann, position=pos,
                            end_location=self._end_location(child, ctx.file_path),
                        )
                        ctx.defined_vars[param_name] = param_id
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

    __slots__ = ("emitter", "file_path", "source", "scope_stack", "defined_vars", "var_types")

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
        self.var_types: dict[str, str] = {}

    @property
    def current_scope(self) -> NodeId:
        return self.scope_stack[-1]


# -- Handler dispatch table ---------------------------------------------------

_NODE_HANDLERS: dict[str, Any] = {
    "class_declaration": JavaVisitor._visit_class_like,
    "interface_declaration": JavaVisitor._visit_class_like,
    "enum_declaration": JavaVisitor._visit_class_like,
    "record_declaration": JavaVisitor._visit_record_declaration,
    "method_declaration": JavaVisitor._visit_method_declaration,
    "constructor_declaration": JavaVisitor._visit_constructor_declaration,
    "local_variable_declaration": JavaVisitor._visit_local_variable_declaration,
    "field_declaration": JavaVisitor._visit_field_declaration,
    "expression_statement": JavaVisitor._visit_expression_statement,
    "return_statement": JavaVisitor._visit_return_statement,
    "import_declaration": JavaVisitor._visit_import_declaration,
    "if_statement": JavaVisitor._visit_if_statement,
    "for_statement": JavaVisitor._visit_for_statement,
    "enhanced_for_statement": JavaVisitor._visit_enhanced_for_statement,
    "while_statement": JavaVisitor._visit_while_statement,
    "do_statement": JavaVisitor._visit_do_statement,
    "switch_expression": JavaVisitor._visit_switch_expression,
    "try_statement": JavaVisitor._visit_try_statement,
    "try_with_resources_statement": JavaVisitor._visit_try_with_resources_statement,
    "throw_statement": JavaVisitor._visit_throw_statement,
    "static_initializer": JavaVisitor._visit_static_initializer,
    "synchronized_statement": JavaVisitor._visit_synchronized_statement,
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
