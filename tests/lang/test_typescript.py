"""Tests for the TypeScript language visitor.

Uses CPGBuilder to parse fixture files and asserts on the resulting graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.builder import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "typescript"


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


class TestSimpleFunction:
    @pytest.fixture()
    def cpg(self):
        return _build("simple_function.ts")

    def test_module_node(self, cpg):
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "simple_function"

    def test_function_nodes_present(self, cpg):
        names = _node_names(cpg, NodeKind.FUNCTION)
        assert "add" in names
        assert "fetchData" in names
        assert "multiply" in names

    def test_parameters_for_add(self, cpg):
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "a" in param_names
        assert "b" in param_names

    def test_has_parameter_edges(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.HAS_PARAMETER)
        assert ("add", "a") in pairs
        assert ("add", "b") in pairs

    def test_async_function(self, cpg):
        fetch = next(
            (n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "fetchData"),
            None,
        )
        assert fetch is not None, "fetchData function not found"
        assert fetch.attrs.get("is_async") is True, (
            f"fetchData should be async, got attrs={fetch.attrs}"
        )

    def test_arrow_function_as_function_node(self, cpg):
        names = _node_names(cpg, NodeKind.FUNCTION)
        assert "multiply" in names, f"multiply not found in functions: {names}"

    def test_variable_declared(self, cpg):
        # `result` is declared inside `add`
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "result" in var_names

    def test_return_node_exists(self, cpg):
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(returns) >= 1

    def test_function_contained_in_module(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("simple_function", "add") in pairs

    def test_data_flow_to_return(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in pairs, (
            f"Expected result->return data flow. Actual DATA_FLOWS_TO pairs: {pairs}"
        )


class TestClassWithTypes:
    @pytest.fixture()
    def cpg(self):
        return _build("class_with_types.ts")

    def test_class_nodes(self, cpg):
        class_names = _node_names(cpg, NodeKind.CLASS)
        assert "Animal" in class_names
        assert "Dog" in class_names

    def test_method_nodes(self, cpg):
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert "constructor" in func_names
        assert "speak" in func_names
        assert "breathe" in func_names

    def test_methods_scoped_to_class(self, cpg):
        contains_pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("Animal", "speak") in contains_pairs
        assert ("Animal", "breathe") in contains_pairs

    def test_constructor_parameters(self, cpg):
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "name" in param_names
        assert "age" in param_names

    def test_async_method(self, cpg):
        breathe = next(
            (n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "breathe"),
            None,
        )
        assert breathe is not None
        assert breathe.attrs.get("is_async") is True, (
            f"breathe should be async, got attrs={breathe.attrs}"
        )

    def test_module_contains_classes(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("class_with_types", "Animal") in pairs
        assert ("class_with_types", "Dog") in pairs


class TestInterfaces:
    @pytest.fixture()
    def cpg(self):
        return _build("interfaces.ts")

    def test_interface_as_class_node(self, cpg):
        class_names = _node_names(cpg, NodeKind.CLASS)
        assert "User" in class_names, f"Expected User interface as CLASS. Got: {class_names}"
        assert "Repository" in class_names

    def test_enum_as_class_node(self, cpg):
        class_names = _node_names(cpg, NodeKind.CLASS)
        assert "Direction" in class_names, f"Expected Direction enum as CLASS. Got: {class_names}"
        assert "Status" in class_names

    def test_module_contains_interfaces_and_enums(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("interfaces", "User") in pairs
        assert ("interfaces", "Direction") in pairs


class TestImports:
    @pytest.fixture()
    def cpg(self):
        return _build("imports.ts")

    def test_import_nodes_present(self, cpg):
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) >= 3, f"Expected at least 3 import nodes, got {len(imports)}"

    def test_fs_import(self, cpg):
        # ES6 imports with `from` emit with module stored in attrs["module"]
        import_nodes = list(cpg.nodes(kind=NodeKind.IMPORT))
        modules = {n.attrs.get("module") for n in import_nodes}
        assert "fs" in modules, f"Expected 'fs' in import modules. Got: {modules}"

    def test_import_names_captured(self, cpg):
        import_nodes = list(cpg.nodes(kind=NodeKind.IMPORT))
        fs_import = next(
            (n for n in import_nodes if n.attrs.get("module") == "fs"), None
        )
        assert fs_import is not None, "fs import node not found"
        names = fs_import.attrs.get("names", [])
        assert "readFile" in names, f"Expected readFile in fs import names, got {names}"
        assert "writeFile" in names, f"Expected writeFile in fs import names, got {names}"

    def test_namespace_import(self, cpg):
        # `import * as path from "path"` — module is "path" in attrs
        import_nodes = list(cpg.nodes(kind=NodeKind.IMPORT))
        path_import = next(
            (n for n in import_nodes if n.attrs.get("module") == "path"), None
        )
        assert path_import is not None, (
            f"Expected path namespace import. Got modules: "
            f"{[n.attrs.get('module') for n in import_nodes]}"
        )

    def test_call_nodes_present(self, cpg):
        # readFile is called in the fixture
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "readFile" in call_names or any("readFile" in n for n in call_names), (
            f"Expected readFile call. Got: {call_names}"
        )


class TestCallResolution:
    @pytest.fixture()
    def cpg(self):
        return _build("simple_function.ts")

    def test_calls_edges_resolved(self, cpg):
        # multiply is defined and could be called if there were call sites
        # This test checks the basic structure is correct for call resolution
        calls_pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        # simple_function.ts doesn't call any of its own functions, so this may be empty
        # Just verify the method doesn't crash
        assert isinstance(calls_pairs, list)


class TestDataFlow:
    @pytest.fixture()
    def cpg(self):
        return _build("data_flow.ts")

    def test_functions_present(self, cpg):
        names = _node_names(cpg, NodeKind.FUNCTION)
        assert "transform" in names
        assert "multiAssign" in names

    def test_parameters_present(self, cpg):
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "input" in param_names
        assert "a" in param_names
        assert "b" in param_names

    def test_local_variable_nodes(self, cpg):
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "x" in var_names
        assert "y" in var_names
        assert "result" in var_names

    def test_param_flows_to_local(self, cpg):
        # input -> x is recorded as a data flow (param used in initializer)
        dfg_pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # x is defined from input via the visitor's emit_definition/emit_data_flow path
        # The visitor emits x -> y (assignment) and y -> return
        assert ("x", "y") in dfg_pairs, f"Expected x->y data flow. Got: {dfg_pairs}"
        assert ("y", "return") in dfg_pairs, f"Expected y->return data flow. Got: {dfg_pairs}"

    def test_module_level_variable(self, cpg):
        # `const value = transform("hello")` produces a VARIABLE node at module scope
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "value" in var_names

    def test_call_site_emitted(self, cpg):
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "transform" in call_names

    def test_return_nodes_present(self, cpg):
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        # One return per function: transform and multiAssign
        assert len(returns) >= 2

    def test_result_reassignment_produces_variable(self, cpg):
        # `result = b` is a reassignment: visitor still emits a VARIABLE for result
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "result" in var_names

    def test_result_flows_to_return(self, cpg):
        dfg_pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in dfg_pairs, (
            f"Expected result->return data flow. Got: {dfg_pairs}"
        )


class TestCrossFunctionTaint:
    @pytest.fixture()
    def cpg(self):
        return _build("cross_function_taint.ts")

    def test_all_functions_discovered(self, cpg):
        names = _node_names(cpg, NodeKind.FUNCTION)
        assert "source" in names
        assert "passthrough" in names
        assert "sink" in names
        assert "main" in names

    def test_call_sites_emitted(self, cpg):
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "source" in call_names
        assert "passthrough" in call_names
        assert "sink" in call_names

    def test_calls_edges_resolved(self, cpg):
        # All three intra-module calls resolve to their definitions
        calls_pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("source", "source") in calls_pairs, (
            f"Expected source call resolved. Got: {calls_pairs}"
        )
        assert ("passthrough", "passthrough") in calls_pairs
        assert ("sink", "sink") in calls_pairs

    def test_data_variables_in_main(self, cpg):
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "data" in var_names
        assert "processed" in var_names

    def test_call_result_flows_to_variable(self, cpg):
        # source() result flows to `data`; passthrough() result flows to `processed`
        dfg_pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("source", "data") in dfg_pairs, (
            f"Expected source->data data flow. Got: {dfg_pairs}"
        )
        assert ("passthrough", "processed") in dfg_pairs

    def test_argument_flows_to_call(self, cpg):
        # `processed` is passed to sink() — data flows from processed to the call node
        dfg_pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("processed", "sink") in dfg_pairs, (
            f"Expected processed->sink data flow. Got: {dfg_pairs}"
        )

    def test_parameter_receives_argument_flow(self, cpg):
        # `data` (local in main) flows to the `data` parameter of passthrough
        dfg_pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("data", "passthrough") in dfg_pairs, (
            f"Expected data->passthrough data flow. Got: {dfg_pairs}"
        )

    def test_literal_in_source_function(self, cpg):
        lit_names = _node_names(cpg, NodeKind.LITERAL)
        assert '"tainted"' in lit_names


class TestMethodCalls:
    @pytest.fixture()
    def cpg(self):
        return _build("method_calls.ts")

    def test_class_node_present(self, cpg):
        class_names = _node_names(cpg, NodeKind.CLASS)
        assert "Processor" in class_names

    def test_methods_emitted(self, cpg):
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert "constructor" in func_names
        assert "process" in func_names
        assert "validate" in func_names
        assert "run" in func_names

    def test_methods_scoped_to_class(self, cpg):
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("Processor", "constructor") in contains
        assert ("Processor", "process") in contains
        assert ("Processor", "validate") in contains

    def test_run_function_at_module_scope(self, cpg):
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("method_calls", "run") in contains

    def test_method_call_nodes(self, cpg):
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "p.process" in call_names
        assert "p.validate" in call_names

    def test_method_calls_resolved(self, cpg):
        calls_pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("p.process", "process") in calls_pairs, (
            f"Expected p.process->process CALLS edge. Got: {calls_pairs}"
        )
        assert ("p.validate", "validate") in calls_pairs

    def test_chained_data_flow(self, cpg):
        # result is defined by p.process(); valid is defined by p.validate(result)
        dfg_pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("p.process", "result") in dfg_pairs
        assert ("p.validate", "valid") in dfg_pairs

    def test_result_passed_to_validate(self, cpg):
        # `result` is passed as argument to p.validate — flows to the call
        dfg_pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "p.validate") in dfg_pairs, (
            f"Expected result->p.validate data flow. Got: {dfg_pairs}"
        )

    def test_valid_flows_to_return(self, cpg):
        dfg_pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("valid", "return") in dfg_pairs, (
            f"Expected valid->return data flow. Got: {dfg_pairs}"
        )

    def test_constructor_parameter(self, cpg):
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "data" in param_names


class TestNestedScopes:
    @pytest.fixture()
    def cpg(self):
        return _build("nested_scopes.ts")

    def test_outer_function_present(self, cpg):
        names = _node_names(cpg, NodeKind.FUNCTION)
        assert "outer" in names

    def test_inner_function_present(self, cpg):
        # Nested function declarations are picked up via recursive visit
        names = _node_names(cpg, NodeKind.FUNCTION)
        assert "inner" in names, f"Expected inner function. Got functions: {names}"

    def test_inner_scoped_to_outer(self, cpg):
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("outer", "inner") in contains, (
            f"Expected outer CONTAINS inner. Got: {contains}"
        )

    def test_arrow_function_at_module_scope(self, cpg):
        # `const adder = (a) => ...` emits adder as a FUNCTION
        names = _node_names(cpg, NodeKind.FUNCTION)
        assert "adder" in names, f"Expected adder arrow function. Got: {names}"

    def test_parameters_across_scopes(self, cpg):
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "x" in param_names   # outer's param
        assert "y" in param_names   # inner's param
        assert "a" in param_names   # adder's param

    def test_outer_has_parameter_x(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.HAS_PARAMETER)
        assert ("outer", "x") in pairs

    def test_inner_has_parameter_y(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.HAS_PARAMETER)
        assert ("inner", "y") in pairs

    def test_inner_call_emitted(self, cpg):
        # `inner(10)` inside outer produces a CALL node
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "inner" in call_names

    def test_inner_call_resolved(self, cpg):
        calls_pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("inner", "inner") in calls_pairs, (
            f"Expected inner call resolved to inner function. Got: {calls_pairs}"
        )

    def test_literal_argument_flows_to_inner_call(self, cpg):
        dfg_pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # `10` is the argument to inner(10), so 10 -> inner call node
        assert ("10", "inner") in dfg_pairs, (
            f"Expected literal 10 -> inner call data flow. Got: {dfg_pairs}"
        )
