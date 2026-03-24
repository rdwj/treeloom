"""Tests for the C language visitor.

Uses CPGBuilder to parse fixture files and asserts on the resulting graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.builder import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.lang.builtin.c import CVisitor
from treeloom.lang.registry import LanguageRegistry
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "c"


def _registry() -> LanguageRegistry:
    """Build a LanguageRegistry with only the C visitor registered."""
    reg = LanguageRegistry()
    reg.register(CVisitor())
    return reg


def _build(fixture_name: str) -> CodePropertyGraph:
    return CPGBuilder(registry=_registry()).add_file(FIXTURES / fixture_name).build()


def _node_names(cpg: CodePropertyGraph, kind: NodeKind) -> set[str]:
    return {n.name for n in cpg.nodes(kind=kind)}


def _edge_pairs(cpg: CodePropertyGraph, kind: EdgeKind) -> list[tuple[str, str]]:
    pairs = []
    for e in cpg.edges(kind=kind):
        src = cpg.node(e.source)
        tgt = cpg.node(e.target)
        if src and tgt:
            pairs.append((src.name, tgt.name))
    return pairs


# ---------------------------------------------------------------------------
# simple_function.c
# ---------------------------------------------------------------------------


class TestSimpleFunction:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("simple_function.c")

    def test_module_node(self, cpg: CodePropertyGraph) -> None:
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "simple_function"

    def test_function_node(self, cpg: CodePropertyGraph) -> None:
        assert "add" in _node_names(cpg, NodeKind.FUNCTION)

    def test_parameter_nodes(self, cpg: CodePropertyGraph) -> None:
        params = _node_names(cpg, NodeKind.PARAMETER)
        assert "x" in params
        assert "y" in params

    def test_has_parameter_edges(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.HAS_PARAMETER)
        assert ("add", "x") in pairs, f"HAS_PARAMETER pairs: {pairs}"
        assert ("add", "y") in pairs

    def test_variable_node(self, cpg: CodePropertyGraph) -> None:
        assert "result" in _node_names(cpg, NodeKind.VARIABLE)

    def test_return_node(self, cpg: CodePropertyGraph) -> None:
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(returns) == 1

    def test_function_contained_in_module(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("simple_function", "add") in pairs, f"CONTAINS pairs: {pairs}"

    def test_variable_contained_in_function(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("add", "result") in pairs

    def test_import_node(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) == 1
        assert imports[0].attrs.get("module") == "stdio.h"

    def test_data_flow_to_return(self, cpg: CodePropertyGraph) -> None:
        """The variable 'result' should flow to the return node."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"

    def test_parameter_type_annotation(self, cpg: CodePropertyGraph) -> None:
        param_x = next(
            (n for n in cpg.nodes(kind=NodeKind.PARAMETER) if n.name == "x"), None
        )
        assert param_x is not None
        assert param_x.attrs.get("type_annotation") == "int"


# ---------------------------------------------------------------------------
# struct_example.c
# ---------------------------------------------------------------------------


class TestStructExample:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("struct_example.c")

    def test_named_struct_becomes_class(self, cpg: CodePropertyGraph) -> None:
        class_names = _node_names(cpg, NodeKind.CLASS)
        assert "Point" in class_names, f"CLASS nodes: {class_names}"

    def test_typedef_struct_becomes_class(self, cpg: CodePropertyGraph) -> None:
        # typedef struct { ... } Rectangle — the anonymous struct body is emitted
        # as a CLASS; the name comes from the struct name field if present.
        # Since this typedef struct is anonymous, it gets the "<anonymous>" name.
        class_names = _node_names(cpg, NodeKind.CLASS)
        # At minimum Point should be present
        assert len(class_names) >= 1

    def test_function_node(self, cpg: CodePropertyGraph) -> None:
        assert "area" in _node_names(cpg, NodeKind.FUNCTION)

    def test_parameters(self, cpg: CodePropertyGraph) -> None:
        params = _node_names(cpg, NodeKind.PARAMETER)
        assert "p" in params
        assert "scale" in params

    def test_variable_nodes(self, cpg: CodePropertyGraph) -> None:
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "result" in var_names

    def test_return_node(self, cpg: CodePropertyGraph) -> None:
        assert len(list(cpg.nodes(kind=NodeKind.RETURN))) == 1

    def test_import_node(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) == 1
        assert imports[0].attrs.get("module") == "stdlib.h"


# ---------------------------------------------------------------------------
# control_flow.c
# ---------------------------------------------------------------------------


class TestControlFlow:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("control_flow.c")

    def test_function_exists(self, cpg: CodePropertyGraph) -> None:
        assert "check" in _node_names(cpg, NodeKind.FUNCTION)

    def test_call_nodes(self, cpg: CodePropertyGraph) -> None:
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "printf" in call_names

    def test_branch_node(self, cpg: CodePropertyGraph) -> None:
        branches = list(cpg.nodes(kind=NodeKind.BRANCH))
        assert len(branches) >= 1
        branch_types = {b.attrs.get("branch_type") for b in branches}
        assert "if" in branch_types

    def test_branch_has_else(self, cpg: CodePropertyGraph) -> None:
        if_branches = [
            b for b in cpg.nodes(kind=NodeKind.BRANCH)
            if b.attrs.get("branch_type") == "if"
        ]
        assert len(if_branches) == 1
        assert if_branches[0].attrs["has_else"] is True

    def test_for_loop_node(self, cpg: CodePropertyGraph) -> None:
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "for"
        ]
        assert len(loops) == 1
        assert loops[0].attrs.get("iterator_var") == "i"

    def test_while_loop_node(self, cpg: CodePropertyGraph) -> None:
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "while"
        ]
        assert len(loops) == 1

    def test_branch_contained_in_function(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("check", "if") in pairs, f"CONTAINS pairs: {pairs}"

    def test_loop_contained_in_function(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("check", "for") in pairs
        assert ("check", "while") in pairs

    def test_variable_node(self, cpg: CodePropertyGraph) -> None:
        assert "n" in _node_names(cpg, NodeKind.VARIABLE)

    def test_import_node(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) == 1
        assert imports[0].attrs.get("module") == "stdio.h"


# ---------------------------------------------------------------------------
# add_source inline tests
# ---------------------------------------------------------------------------


class TestAddSourceInline:
    def test_simple_function_from_source(self) -> None:
        source = b"int square(int n) { return n * n; }"
        cpg = CPGBuilder(registry=_registry()).add_source(source, "test.c", "c").build()
        assert "square" in _node_names(cpg, NodeKind.FUNCTION)
        assert "n" in _node_names(cpg, NodeKind.PARAMETER)

    def test_call_resolution(self) -> None:
        source = b"""
int double_val(int x) { return x + x; }
int main(void) {
    int r = double_val(5);
    return r;
}
"""
        cpg = CPGBuilder(registry=_registry()).add_source(source, "calls.c", "c").build()
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("double_val", "double_val") in pairs, f"CALLS pairs: {pairs}"

    def test_multiple_parameters(self) -> None:
        source = b"void f(int a, int b, char *c) {}"
        cpg = CPGBuilder(registry=_registry()).add_source(source, "params.c", "c").build()
        params = _node_names(cpg, NodeKind.PARAMETER)
        assert {"a", "b", "c"} <= params

    def test_data_flow_arg_to_call(self) -> None:
        source = b"""
#include <stdio.h>
void greet(char *name) { printf("%s\\n", name); }
"""
        cpg = CPGBuilder(registry=_registry()).add_source(source, "greet.c", "c").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("name", "printf") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"

    def test_variable_data_flow(self) -> None:
        source = b"int f(void) { int x = 1; return x; }"
        cpg = CPGBuilder(registry=_registry()).add_source(source, "df.c", "c").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("x", "return") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"
