"""C++ language visitor for tree-sitter AST to CPG conversion."""

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

# tree-sitter node types that map to LITERAL with a type label
_LITERAL_TYPES: dict[str, str] = {
    "number_literal": "int",
    "string_literal": "str",
    "char_literal": "str",
    "true": "bool",
    "false": "bool",
    "null": "none",
    "nullptr": "none",
}


class CppVisitor(TreeSitterVisitor):
    """Walks a C++ tree-sitter parse tree and emits CPG nodes/edges."""

    _language_name = "cpp"

    @property
    def name(self) -> str:
        return "cpp"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh"})

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
            fn = _resolve_single_call(call_node, target, functions, cpg)
            if fn is None and "." in target:
                fn = _resolve_single_call(
                    call_node, target.rsplit(".", 1)[-1], functions, cpg
                )
            if fn is None and "::" in target:
                fn = _resolve_single_call(
                    call_node, target.rsplit("::", 1)[-1], functions, cpg
                )
            if fn is not None:
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

    def _visit_class_specifier(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle class_specifier and struct_specifier."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        class_name = self._node_text(name_node, ctx.source)
        class_id = ctx.emitter.emit_class(
            class_name,
            self._location(node, ctx.file_path),
            ctx.current_scope,
        )
        ctx.scope_stack.append(class_id)
        ctx.defined_vars.push()
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)
        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_function_definition(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle function_definition at any scope."""
        declarator = node.child_by_field_name("declarator")
        if declarator is None:
            return
        func_name, params_node = _extract_func_name_and_params(declarator)
        if not func_name:
            return

        func_id = ctx.emitter.emit_function(
            func_name,
            self._location(node, ctx.file_path),
            ctx.current_scope,
            params=None,  # we emit params with type annotations below
        )
        ctx.scope_stack.append(func_id)
        ctx.defined_vars.push()

        if params_node is not None:
            self._emit_typed_params(params_node, func_id, ctx)

        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)

        ctx.defined_vars.pop()
        ctx.scope_stack.pop()

    def _visit_template_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle template<...> function/class declarations."""
        for child in node.children:
            if child.type in ("function_definition", "class_specifier", "struct_specifier"):
                self._visit_node(child, ctx)

    def _visit_namespace_definition(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Treat namespace body contents as if at enclosing scope."""
        body = node.child_by_field_name("body")
        if body is None:
            return
        for child in body.children:
            self._visit_node(child, ctx)

    def _visit_field_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Emit member variables declared in a class body."""
        for child in node.children:
            if child.type == "field_identifier":
                field_name = self._node_text(child, ctx.source)
                var_id = ctx.emitter.emit_variable(
                    field_name,
                    SourceLocation(
                        file=ctx.file_path,
                        line=child.start_point.row + 1,
                        column=child.start_point.column,
                    ),
                    ctx.current_scope,
                )
                ctx.defined_vars[field_name] = var_id
            elif child.type == "init_declarator":
                # field with in-class initializer: int x = 5;
                name_child = child.child_by_field_name("declarator")
                if name_child is not None and name_child.type in (
                    "field_identifier", "identifier"
                ):
                    field_name = self._node_text(name_child, ctx.source)
                    var_id = ctx.emitter.emit_variable(
                        field_name,
                        SourceLocation(
                            file=ctx.file_path,
                            line=name_child.start_point.row + 1,
                            column=name_child.start_point.column,
                        ),
                        ctx.current_scope,
                    )
                    ctx.defined_vars[field_name] = var_id

    def _visit_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle local variable declarations: `int x = expr;`"""
        for child in node.children:
            if child.type == "init_declarator":
                declarator = child.child_by_field_name("declarator")
                value_node = child.child_by_field_name("value")
                if declarator is None:
                    continue
                if declarator.type == "identifier":
                    var_name = self._node_text(declarator, ctx.source)
                    var_id = ctx.emitter.emit_variable(
                        var_name,
                        SourceLocation(
                            file=ctx.file_path,
                            line=declarator.start_point.row + 1,
                            column=declarator.start_point.column,
                        ),
                        ctx.current_scope,
                    )
                    ctx.defined_vars[var_name] = var_id
                    if value_node is not None:
                        rhs_id = self._visit_expression(value_node, ctx)
                        if rhs_id is not None:
                            ctx.emitter.emit_definition(var_id, rhs_id)
                            ctx.emitter.emit_data_flow(rhs_id, var_id)
                elif declarator.type == "function_declarator":
                    # `Dog d("Rex")` — constructor call declared as variable
                    inner_decl = declarator.child_by_field_name("declarator")
                    args_node = declarator.child_by_field_name("parameters")
                    ctor_name = (
                        self._node_text(inner_decl, ctx.source)
                        if inner_decl is not None
                        else self._node_text(declarator, ctx.source)
                    )
                    arg_texts, arg_ids, arg_is_var = self._collect_args(
                        args_node, ctx
                    )
                    call_id = ctx.emitter.emit_call(
                        ctor_name,
                        self._location(child, ctx.file_path),
                        ctx.current_scope,
                        args=arg_texts,
                    )
                    self._wire_args(arg_ids, arg_is_var, call_id, ctx)

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
            self._location(node, ctx.file_path), ctx.current_scope
        )
        for child in node.children:
            if child.type in ("return", ";"):
                continue
            expr_id = self._visit_expression(child, ctx)
            if expr_id is not None:
                ctx.emitter.emit_data_flow(expr_id, ret_id)
                if child.type == "identifier":
                    ctx.emitter.emit_usage(expr_id, ret_id)

    def _visit_preproc_include(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        header = ""
        for child in node.children:
            if child.type in ("system_lib_string", "string_literal"):
                header = self._node_text(child, ctx.source).strip("<>\"")
        if header:
            ctx.emitter.emit_import(
                header, [header], loc, ctx.current_scope, is_from=False
            )

    def _visit_using_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        names: list[str] = []
        for child in node.children:
            if child.type == "identifier":
                names.append(self._node_text(child, ctx.source))
            elif child.type == "qualified_identifier":
                names.append(self._node_text(child, ctx.source))
        module_name = names[0] if names else ""
        ctx.emitter.emit_import(
            module_name, names, loc, ctx.current_scope, is_from=False
        )

    def _visit_if_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        has_else = node.child_by_field_name("alternative") is not None
        branch_id = ctx.emitter.emit_branch_node(
            "if",
            self._location(node, ctx.file_path),
            ctx.current_scope,
            has_else=has_else,
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
            "for", self._location(node, ctx.file_path), ctx.current_scope
        )
        # Visit init declaration within loop scope so `i` is scoped to loop
        ctx.scope_stack.append(loop_id)
        for child in node.children:
            if child.type == "declaration":
                self._visit_declaration(child, ctx)
        ctx.scope_stack.pop()

        body = node.child_by_field_name("body")
        if body is not None:
            ctx.scope_stack.append(loop_id)
            for child in body.children:
                self._visit_node(child, ctx)
            ctx.scope_stack.pop()

    def _visit_for_range_loop(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle C++ range-based for: `for (auto x : container)`."""
        iterator_var: str | None = None
        type_seen = False
        for child in node.children:
            if child.type in (
                "placeholder_type_specifier",
                "primitive_type",
                "type_identifier",
                "qualified_identifier",
            ):
                type_seen = True
            elif type_seen and child.type == "identifier":
                iterator_var = self._node_text(child, ctx.source)
                break

        loop_id = ctx.emitter.emit_loop_node(
            "for",
            self._location(node, ctx.file_path),
            ctx.current_scope,
            iterator_var=iterator_var,
        )

        if iterator_var is not None:
            for child in node.children:
                if (
                    child.type == "identifier"
                    and self._node_text(child, ctx.source) == iterator_var
                ):
                    var_id = ctx.emitter.emit_variable(
                        iterator_var,
                        SourceLocation(
                            file=ctx.file_path,
                            line=child.start_point.row + 1,
                            column=child.start_point.column,
                        ),
                        loop_id,
                    )
                    ctx.defined_vars[iterator_var] = var_id
                    break

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
            "while", self._location(node, ctx.file_path), ctx.current_scope
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

    def _visit_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        if node.type == "call_expression":
            return self._visit_call_expression(node, ctx)
        if node.type in _LITERAL_TYPES:
            return ctx.emitter.emit_literal(
                self._node_text(node, ctx.source),
                _LITERAL_TYPES[node.type],
                self._location(node, ctx.file_path),
                ctx.current_scope,
            )
        if node.type == "identifier":
            return ctx.defined_vars.get(self._node_text(node, ctx.source))
        if node.type == "assignment_expression":
            self._visit_assignment_expression(node, ctx)
            return None
        if node.type in ("binary_expression", "conditional_expression"):
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
        if node.type == "condition_clause":
            # C++ wraps if/while conditions in condition_clause
            for child in node.children:
                if child.is_named:
                    return self._visit_expression(child, ctx)
            return None
        # Recurse into named children for other expression types
        for child in node.children:
            if child.is_named:
                self._visit_expression(child, ctx)
        return None

    def _visit_call_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> NodeId | None:
        """Emit a CALL node for a call_expression."""
        func_node = node.child_by_field_name("function")
        if func_node is None:
            return None

        target_name = _extract_call_target(func_node, ctx.source)
        args_node = node.child_by_field_name("arguments")
        arg_texts, arg_ids, arg_is_var = self._collect_args(args_node, ctx)

        call_id = ctx.emitter.emit_call(
            target_name,
            self._location(node, ctx.file_path),
            ctx.current_scope,
            args=arg_texts,
        )
        self._wire_args(arg_ids, arg_is_var, call_id, ctx)
        return call_id

    def _visit_assignment_expression(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None:
            return
        var_name = self._node_text(left, ctx.source)
        var_id = ctx.emitter.emit_variable(
            var_name,
            SourceLocation(
                file=ctx.file_path,
                line=left.start_point.row + 1,
                column=left.start_point.column,
            ),
            ctx.current_scope,
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
            if child.type != "parameter_declaration":
                continue
            # Last identifier child is the param name; earlier named children form the type.
            name_node: tree_sitter.Node | None = None
            type_parts: list[str] = []
            for sub in child.children:
                if sub.type == "identifier":
                    name_node = sub
                elif sub.is_named and sub.type != "identifier":
                    type_parts.append(self._node_text(sub, ctx.source))
            if name_node is None:
                continue
            param_name = self._node_text(name_node, ctx.source)
            type_ann = " ".join(type_parts) if type_parts else None
            param_id = ctx.emitter.emit_parameter(
                param_name,
                SourceLocation(
                    file=ctx.file_path,
                    line=name_node.start_point.row + 1,
                    column=name_node.start_point.column,
                ),
                func_id,
                type_annotation=type_ann,
                position=pos,
            )
            ctx.defined_vars[param_name] = param_id
            pos += 1

    def _collect_args(
        self,
        args_node: tree_sitter.Node | None,
        ctx: _VisitContext,
    ) -> tuple[list[str], list[NodeId | None], list[bool]]:
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
        for i, arg_id in enumerate(arg_ids):
            if arg_id is not None:
                ctx.emitter.emit_data_flow(arg_id, call_id)
                if i < len(arg_is_var) and arg_is_var[i]:
                    ctx.emitter.emit_usage(arg_id, call_id)


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
    "class_specifier": CppVisitor._visit_class_specifier,
    "struct_specifier": CppVisitor._visit_class_specifier,
    "function_definition": CppVisitor._visit_function_definition,
    "template_declaration": CppVisitor._visit_template_declaration,
    "namespace_definition": CppVisitor._visit_namespace_definition,
    "field_declaration": CppVisitor._visit_field_declaration,
    "declaration": CppVisitor._visit_declaration,
    "expression_statement": CppVisitor._visit_expression_statement,
    "return_statement": CppVisitor._visit_return_statement,
    "preproc_include": CppVisitor._visit_preproc_include,
    "using_declaration": CppVisitor._visit_using_declaration,
    "if_statement": CppVisitor._visit_if_statement,
    "for_statement": CppVisitor._visit_for_statement,
    "for_range_loop": CppVisitor._visit_for_range_loop,
    "while_statement": CppVisitor._visit_while_statement,
}


def _extract_func_name_and_params(
    declarator: tree_sitter.Node,
) -> tuple[str, tree_sitter.Node | None]:
    """Recursively unwrap a C++ declarator to find the function name and params.

    C++ declarators can be nested: pointer_declarator -> function_declarator,
    reference_declarator -> function_declarator, etc.
    """
    if declarator.type == "function_declarator":
        name_node = declarator.child_by_field_name("declarator")
        params_node = declarator.child_by_field_name("parameters")
        if name_node is None:
            return "", params_node
        if name_node.type in ("identifier", "field_identifier"):
            return name_node.text.decode("utf-8", errors="replace"), params_node
        if name_node.type in ("qualified_identifier", "destructor_name"):
            return name_node.text.decode("utf-8", errors="replace"), params_node
        # May be a nested declarator (e.g. pointer_declarator)
        return _extract_func_name_and_params(name_node)[0], params_node

    # pointer_declarator, reference_declarator, etc. — recurse
    for child in declarator.children:
        if child.is_named and child.type in (
            "function_declarator",
            "pointer_declarator",
            "reference_declarator",
        ):
            return _extract_func_name_and_params(child)

    return "", None


def _extract_call_target(
    func_node: tree_sitter.Node,
    source: bytes,
) -> str:
    """Extract a human-readable call target name from the function expression."""
    if func_node.type == "identifier":
        return func_node.text.decode("utf-8", errors="replace")
    if func_node.type == "field_expression":
        obj = func_node.child_by_field_name("argument")
        field = func_node.child_by_field_name("field")
        obj_text = obj.text.decode("utf-8", errors="replace") if obj else ""
        field_text = field.text.decode("utf-8", errors="replace") if field else ""
        sep = func_node.child_by_field_name("operator")
        sep_text = sep.text.decode("utf-8", errors="replace") if sep else "."
        return f"{obj_text}{sep_text}{field_text}"
    if func_node.type == "qualified_identifier":
        return func_node.text.decode("utf-8", errors="replace")
    return func_node.text.decode("utf-8", errors="replace")


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
    # Disambiguate by scope for qualified calls (e.g., "Foo::bar" or "obj.method")
    call_target = call_node.name
    for sep in ("::", "."):
        if sep in call_target:
            qualifier = call_target.rsplit(sep, 1)[0]
            for fn in candidates:
                scope = cpg.scope_of(fn.id)
                if scope is not None and scope.name == qualifier:
                    return fn
    return candidates[0]
