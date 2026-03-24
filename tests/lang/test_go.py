"""Tests for the Go language visitor.

Uses CPGBuilder to parse fixture files and asserts on the resulting graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.builder import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "go"


def _build(fixture_name: str) -> CodePropertyGraph:
    return CPGBuilder().add_file(FIXTURES / fixture_name).build()


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
# simple_function.go
# ---------------------------------------------------------------------------


class TestSimpleFunction:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("simple_function.go")

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

    def test_data_flow_to_return(self, cpg: CodePropertyGraph) -> None:
        """Variable 'result' should flow to the return node."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"


# ---------------------------------------------------------------------------
# struct_methods.go
# ---------------------------------------------------------------------------


class TestStructMethods:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("struct_methods.go")

    def test_struct_emitted_as_class(self, cpg: CodePropertyGraph) -> None:
        assert "Rectangle" in _node_names(cpg, NodeKind.CLASS)

    def test_struct_fields_as_variables(self, cpg: CodePropertyGraph) -> None:
        vars_ = _node_names(cpg, NodeKind.VARIABLE)
        assert "Width" in vars_, f"variables: {vars_}"
        assert "Height" in vars_

    def test_constructor_function(self, cpg: CodePropertyGraph) -> None:
        assert "NewRectangle" in _node_names(cpg, NodeKind.FUNCTION)

    def test_method_declarations(self, cpg: CodePropertyGraph) -> None:
        funcs = _node_names(cpg, NodeKind.FUNCTION)
        assert "Area" in funcs
        assert "Describe" in funcs

    def test_constructor_parameters(self, cpg: CodePropertyGraph) -> None:
        params = _node_names(cpg, NodeKind.PARAMETER)
        assert "w" in params
        assert "h" in params

    def test_import_node(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        modules = {n.attrs.get("module") for n in imports}
        assert "fmt" in modules, f"import modules: {modules}"

    def test_class_contained_in_module(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("struct_methods", "Rectangle") in pairs, f"CONTAINS: {pairs}"


# ---------------------------------------------------------------------------
# imports.go
# ---------------------------------------------------------------------------


class TestImports:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("imports.go")

    def test_import_nodes_present(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) >= 1, "Expected at least one IMPORT node"

    def test_import_names(self, cpg: CodePropertyGraph) -> None:
        modules = {n.attrs.get("module") for n in cpg.nodes(kind=NodeKind.IMPORT)}
        assert "fmt" in modules, f"import modules: {modules}"
        assert "os" in modules
        assert "strings" in modules

    def test_main_function(self, cpg: CodePropertyGraph) -> None:
        assert "main" in _node_names(cpg, NodeKind.FUNCTION)


# ---------------------------------------------------------------------------
# control_flow.go
# ---------------------------------------------------------------------------


class TestControlFlow:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("control_flow.go")

    def test_functions(self, cpg: CodePropertyGraph) -> None:
        funcs = _node_names(cpg, NodeKind.FUNCTION)
        assert "classify" in funcs
        assert "sumTo" in funcs
        assert "printItems" in funcs

    def test_branch_node_from_if(self, cpg: CodePropertyGraph) -> None:
        branches = list(cpg.nodes(kind=NodeKind.BRANCH))
        assert len(branches) >= 1, "Expected at least one BRANCH node"

    def test_loop_node_from_for(self, cpg: CodePropertyGraph) -> None:
        loops = list(cpg.nodes(kind=NodeKind.LOOP))
        assert len(loops) >= 1, f"Expected at least one LOOP node, got {len(loops)}"

    def test_loop_variable(self, cpg: CodePropertyGraph) -> None:
        """The 'i' variable declared in for_clause should appear."""
        vars_ = _node_names(cpg, NodeKind.VARIABLE)
        assert "total" in vars_, f"variables: {vars_}"

    def test_return_nodes(self, cpg: CodePropertyGraph) -> None:
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        # classify has 3 returns, sumTo has 1
        assert len(returns) >= 4, f"Expected >=4 RETURN nodes, got {len(returns)}"

    def test_if_contained_in_function(self, cpg: CodePropertyGraph) -> None:
        """BRANCH node should be contained in 'classify'."""
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        branch_parents = {src for src, tgt in contains}
        assert "classify" in branch_parents, (
            f"No CONTAINS edge sourced from 'classify'. Sources: {branch_parents}"
        )

    def test_for_loop_contained_in_function(self, cpg: CodePropertyGraph) -> None:
        """LOOP node should be contained in 'sumTo' or 'printItems'."""
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        loop_parents = {src for src, tgt in contains}
        assert "sumTo" in loop_parents or "printItems" in loop_parents, (
            f"No CONTAINS from sumTo/printItems. Sources: {loop_parents}"
        )
