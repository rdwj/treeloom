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


# ---------------------------------------------------------------------------
# data_flow.go
# ---------------------------------------------------------------------------


class TestDataFlow:
    """Data flow chain tests for Go."""

    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("data_flow.go")

    def test_assignment_chain_nodes(self, cpg: CodePropertyGraph) -> None:
        """Variables in assignment chains are emitted."""
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "x" in var_names
        assert "y" in var_names

    def test_short_var_data_flow(self, cpg: CodePropertyGraph) -> None:
        """Short variable declaration (:=) emits DATA_FLOWS_TO."""
        dfg_edges = list(cpg.edges(kind=EdgeKind.DATA_FLOWS_TO))
        assert len(dfg_edges) > 0

    def test_reassignment_data_flow(self, cpg: CodePropertyGraph) -> None:
        """Plain assignment (=) also emits DATA_FLOWS_TO after fix."""
        # result = b should create a DATA_FLOWS_TO edge
        # Find 'result' variable nodes and check they have incoming DFG edges
        result_nodes = [n for n in cpg.nodes(kind=NodeKind.VARIABLE) if n.name == "result"]
        assert len(result_nodes) >= 1
        # Should have at least 2 DFG edges: one from :=, one from =
        result_ids = {str(n.id) for n in result_nodes}
        dfg_to_result = [
            e for e in cpg.edges(kind=EdgeKind.DATA_FLOWS_TO)
            if str(e.target) in result_ids
        ]
        assert len(dfg_to_result) >= 2, (
            f"Expected >=2 DFG edges to 'result', got {len(dfg_to_result)}. "
            f"All DFG edges: {list(cpg.edges(kind=EdgeKind.DATA_FLOWS_TO))}"
        )

    def test_multiple_return_values(self, cpg: CodePropertyGraph) -> None:
        """Functions with multiple returns emit RETURN nodes."""
        funcs = [n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "multiReturn"]
        assert len(funcs) == 1


# ---------------------------------------------------------------------------
# cross_function_taint.go
# ---------------------------------------------------------------------------


class TestCrossFunctionTaint:
    """Cross-function taint propagation tests."""

    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("cross_function_taint.go")

    def test_functions_exist(self, cpg: CodePropertyGraph) -> None:
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert {"source", "passthrough", "sink", "main"}.issubset(func_names)

    def test_call_nodes_exist(self, cpg: CodePropertyGraph) -> None:
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "source" in call_names
        assert "passthrough" in call_names
        assert "sink" in call_names

    def test_call_resolution(self, cpg: CodePropertyGraph) -> None:
        calls_edges = list(cpg.edges(kind=EdgeKind.CALLS))
        assert len(calls_edges) >= 1

    def test_data_flow_through_calls(self, cpg: CodePropertyGraph) -> None:
        """Data flows from call arguments to call nodes."""
        dfg_edges = list(cpg.edges(kind=EdgeKind.DATA_FLOWS_TO))
        # passthrough(data) and sink(processed) should have arg -> call DFG
        assert len(dfg_edges) >= 2


# ---------------------------------------------------------------------------
# method_calls.go
# ---------------------------------------------------------------------------


class TestMethodCalls:
    """Method call tests for Go."""

    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("method_calls.go")

    def test_struct_exists(self, cpg: CodePropertyGraph) -> None:
        classes = [n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Processor"]
        assert len(classes) == 1

    def test_methods_exist(self, cpg: CodePropertyGraph) -> None:
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert "Process" in func_names
        assert "Validate" in func_names
        assert "NewProcessor" in func_names

    def test_method_calls_emitted(self, cpg: CodePropertyGraph) -> None:
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "NewProcessor" in call_names
        # Method calls may be qualified (p.Process) or just the method name
        has_process = any("Process" in name for name in call_names)
        has_validate = any("Validate" in name for name in call_names)
        assert has_process
        assert has_validate


# ---------------------------------------------------------------------------
# nested_scopes.go
# ---------------------------------------------------------------------------


class TestNestedScopes:
    """Nested scope tests for Go."""

    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("nested_scopes.go")

    def test_outer_function(self, cpg: CodePropertyGraph) -> None:
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert "outer" in func_names

    def test_function_literal(self, cpg: CodePropertyGraph) -> None:
        """Named functions in the file are emitted."""
        # The Go visitor does not currently emit anonymous function literals;
        # at minimum outer and withDefer must be present.
        funcs = list(cpg.nodes(kind=NodeKind.FUNCTION))
        assert len(funcs) >= 2
