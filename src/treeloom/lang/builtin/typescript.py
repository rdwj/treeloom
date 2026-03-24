"""TypeScript (and TSX) language visitors for tree-sitter AST to CPG conversion."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tree_sitter

from treeloom.lang.base import TreeSitterVisitor
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

if TYPE_CHECKING:
    from treeloom.graph.cpg import CodePropertyGraph
    from treeloom.lang.protocol import NodeEmitter
    from treeloom.model.nodes import CpgNode, NodeId

logger = logging.getLogger(__name__)

# tree-sitter node types that map to treeloom literal kinds
_LITERAL_TYPES: dict[str, str] = {
    "string": "str",
    "template_string": "str",
    "number": "int",
    "true": "bool",
    "false": "bool",
    "null": "none",
    "undefined": "none",
}


class TypeScriptVisitor(TreeSitterVisitor):
    """Walks a TypeScript tree-sitter parse tree and emits CPG nodes/edges."""

    _language_name = "typescript"

    # Override: tree_sitter_typescript has language_typescript(), not language()
    _ts_language_func_name: str = "language_typescript"

    def _get_parser(self) -> tree_sitter.Parser:
        if self._parser is not None:
            return self._parser

        try:
            import tree_sitter_typescript as _ts_mod
        except ImportError as exc:
            raise ImportError(
                "tree-sitter-typescript is required. "
                "Install with: pip install treeloom[languages]"
            ) from exc

        language_func = getattr(_ts_mod, self._ts_language_func_name, None)
        if language_func is None:
            raise ImportError(
                f"tree_sitter_typescript has no {self._ts_language_func_name!r} function"
            )

        lang = tree_sitter.Language(language_func())
        self._parser = tree_sitter.Parser(lang)
        return self._parser

    @property
    def name(self) -> str:
        return "typescript"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".ts"})

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
                short_name = target.rsplit(".", 1)[-1]
                fn = _resolve_single_call(call_node, short_name, functions, cpg)

            if fn is not None:
                from treeloom.model.edges import CpgEdge

                cpg.add_edge(CpgEdge(source=call_node.id, target=fn.id, kind=EdgeKind.CALLS))
                resolved.append((call_node.id, fn.id))

        return resolved

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

        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)

        ctx.scope_stack.pop()

    def _visit_interface_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Treat interface declarations as CLASS nodes."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        iface_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)
        ctx.emitter.emit_class(iface_name, loc, ctx.current_scope)

    def _visit_enum_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Treat enum declarations as CLASS nodes."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        enum_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)
        ctx.emitter.emit_class(enum_name, loc, ctx.current_scope)

    def _visit_function_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        is_async = any(child.type == "async" for child in node.children)
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        func_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)

        params_node = node.child_by_field_name("parameters")
        param_names = _extract_param_names(params_node, ctx.source) if params_node else []

        func_id = ctx.emitter.emit_function(
            func_name, loc, ctx.current_scope, params=param_names, is_async=is_async
        )

        ctx.scope_stack.append(func_id)
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)
        ctx.scope_stack.pop()

    def _visit_method_definition(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        is_async = any(child.type == "async" for child in node.children)
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        method_name = self._node_text(name_node, ctx.source)
        loc = self._location(node, ctx.file_path)

        params_node = node.child_by_field_name("parameters")
        param_names = _extract_param_names(params_node, ctx.source) if params_node else []

        func_id = ctx.emitter.emit_function(
            method_name, loc, ctx.current_scope, params=param_names, is_async=is_async
        )

        ctx.scope_stack.append(func_id)
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)
        ctx.scope_stack.pop()

    def _visit_lexical_declaration(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle const/let declarations, including arrow function assignments."""
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

        # If the value is an arrow function, emit it as a FUNCTION node
        if value_node is not None and value_node.type == "arrow_function":
            loc = self._location(node, ctx.file_path)
            is_async = any(child.type == "async" for child in value_node.children)
            params_node = value_node.child_by_field_name("parameters")
            param_names: list[str] = []
            if params_node is not None:
                if params_node.type == "formal_parameters":
                    param_names = _extract_param_names(params_node, ctx.source)
                elif params_node.type == "identifier":
                    param_names = [self._node_text(params_node, ctx.source)]

            func_id = ctx.emitter.emit_function(
                var_name, loc, ctx.current_scope, params=param_names, is_async=is_async
            )
            ctx.scope_stack.append(func_id)
            body = value_node.child_by_field_name("body")
            if body is not None:
                if body.type == "statement_block":
                    for child in body.children:
                        self._visit_node(child, ctx)
                else:
                    # Expression body: `(x) => x * 2`
                    self._visit_expression(body, ctx)
            ctx.scope_stack.pop()
            return

        # Regular variable declaration
        loc = self._location(name_node, ctx.file_path)
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
            else:
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
        var_id = ctx.emitter.emit_variable(var_name, loc, ctx.current_scope)
        ctx.defined_vars[var_name] = var_id

        if right is not None:
            rhs_id = self._visit_expression(right, ctx)
            if rhs_id is not None:
                ctx.emitter.emit_definition(var_id, rhs_id)
                ctx.emitter.emit_data_flow(rhs_id, var_id)

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
        module_name = ""
        imported_names: list[str] = []

        for child in node.children:
            if child.type == "string":
                module_name = _extract_string_value(child, ctx.source)
            elif child.type == "import_clause":
                imported_names.extend(_extract_import_names(child, ctx.source))

        ctx.emitter.emit_import(
            module_name, imported_names, loc, ctx.current_scope, is_from=True
        )

    def _visit_if_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        has_else = any(child.type == "else_clause" for child in node.children)
        branch_id = ctx.emitter.emit_branch_node("if", loc, ctx.current_scope, has_else=has_else)

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
                # else_clause children: "else", then a statement_block or if_statement
                else_body = None
                for sub in child.children:
                    if sub.type in ("statement_block", "if_statement"):
                        else_body = sub
                        break
                if else_body is not None:
                    ctx.scope_stack.append(branch_id)
                    if else_body.type == "statement_block":
                        for sub in else_body.children:
                            self._visit_node(sub, ctx)
                    else:
                        self._visit_node(else_body, ctx)
                    ctx.scope_stack.pop()

    def _visit_for_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        loc = self._location(node, ctx.file_path)
        loop_id = ctx.emitter.emit_loop_node("for", loc, ctx.current_scope)

        ctx.scope_stack.append(loop_id)
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self._visit_node(child, ctx)
        ctx.scope_stack.pop()

    def _visit_for_in_statement(
        self, node: tree_sitter.Node, ctx: _VisitContext
    ) -> None:
        """Handle for...of and for...in statements."""
        loc = self._location(node, ctx.file_path)

        # The iterator variable is an identifier child (after const/let/var if present)
        iterator_var: str | None = None
        for child in node.children:
            if child.type == "identifier":
                iterator_var = self._node_text(child, ctx.source)
                break

        loop_id = ctx.emitter.emit_loop_node(
            "for", loc, ctx.current_scope, iterator_var=iterator_var
        )

        ctx.scope_stack.append(loop_id)
        body = node.child_by_field_name("body")
        if body is not None:
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

        ctx.scope_stack.append(loop_id)
        body = node.child_by_field_name("body")
        if body is not None:
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

        if node.type in ("binary_expression", "augmented_assignment_expression"):
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

        # Recurse into named children for other expression types
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

        call_id = ctx.emitter.emit_call(target_name, loc, ctx.current_scope, args=arg_texts)

        for i, arg_id in enumerate(arg_ids):
            if arg_id is not None:
                ctx.emitter.emit_data_flow(arg_id, call_id)
                if i < len(arg_is_var) and arg_is_var[i]:
                    ctx.emitter.emit_usage(arg_id, call_id)

        return call_id


class TSXVisitor(TypeScriptVisitor):
    """TSX visitor — TypeScript with JSX. Extends TypeScriptVisitor."""

    _ts_language_func_name = "language_tsx"

    @property
    def name(self) -> str:
        return "tsx"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".tsx"})


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
        self.defined_vars: dict[str, NodeId] = {}

    @property
    def current_scope(self) -> NodeId:
        return self.scope_stack[-1]


# -- Handler dispatch table ---------------------------------------------------

_NODE_HANDLERS: dict[str, Any] = {
    "class_declaration": TypeScriptVisitor._visit_class_declaration,
    "interface_declaration": TypeScriptVisitor._visit_interface_declaration,
    "enum_declaration": TypeScriptVisitor._visit_enum_declaration,
    "function_declaration": TypeScriptVisitor._visit_function_declaration,
    "method_definition": TypeScriptVisitor._visit_method_definition,
    "lexical_declaration": TypeScriptVisitor._visit_lexical_declaration,
    "variable_declaration": TypeScriptVisitor._visit_variable_declaration,
    "expression_statement": TypeScriptVisitor._visit_expression_statement,
    "return_statement": TypeScriptVisitor._visit_return_statement,
    "import_statement": TypeScriptVisitor._visit_import_statement,
    "if_statement": TypeScriptVisitor._visit_if_statement,
    "for_statement": TypeScriptVisitor._visit_for_statement,
    "for_in_statement": TypeScriptVisitor._visit_for_in_statement,
    "while_statement": TypeScriptVisitor._visit_while_statement,
}


# -- Helper functions ---------------------------------------------------------


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

    call_target = call_node.name
    if "." in call_target:
        qualifier = call_target.rsplit(".", 1)[0]
        for fn in candidates:
            scope = cpg.scope_of(fn.id)
            if scope is not None and scope.name == qualifier:
                return fn

    return candidates[0]


def _extract_param_names(
    params_node: tree_sitter.Node, source: bytes
) -> list[str]:
    """Extract parameter names from a formal_parameters node."""
    names: list[str] = []
    for child in params_node.children:
        if child.type in ("required_parameter", "optional_parameter"):
            pattern = child.child_by_field_name("pattern")
            if pattern is not None and pattern.type == "identifier":
                names.append(pattern.text.decode("utf-8", errors="replace"))
        elif child.type == "identifier":
            names.append(child.text.decode("utf-8", errors="replace"))
        elif child.type == "rest_pattern":
            for sub in child.children:
                if sub.type == "identifier":
                    names.append("..." + sub.text.decode("utf-8", errors="replace"))
                    break
    return names


def _extract_string_value(node: tree_sitter.Node, source: bytes) -> str:
    """Extract the string content from a string node (without quotes)."""
    for child in node.children:
        if child.type == "string_fragment":
            return child.text.decode("utf-8", errors="replace")
    return node.text.decode("utf-8", errors="replace").strip("'\"")


def _extract_import_names(clause_node: tree_sitter.Node, source: bytes) -> list[str]:
    """Extract imported binding names from an import_clause node."""
    names: list[str] = []
    for child in clause_node.children:
        if child.type == "identifier":
            names.append(child.text.decode("utf-8", errors="replace"))
        elif child.type == "named_imports":
            for spec in child.children:
                if spec.type == "import_specifier":
                    for sub in spec.children:
                        if sub.type == "identifier":
                            names.append(sub.text.decode("utf-8", errors="replace"))
                            break
        elif child.type == "namespace_import":
            # import * as foo from 'bar'
            for sub in child.children:
                if sub.type == "identifier":
                    names.append(sub.text.decode("utf-8", errors="replace"))
    return names
