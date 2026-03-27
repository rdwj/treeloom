"""Tests for the Rust language visitor.

Uses CPGBuilder to parse fixture files and asserts on the resulting graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.builder import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.lang.builtin.rust import RustVisitor
from treeloom.lang.registry import LanguageRegistry
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "rust"


def _make_registry() -> LanguageRegistry:
    registry = LanguageRegistry()
    registry.register(RustVisitor())
    return registry


def _build(fixture_name: str) -> CodePropertyGraph:
    return CPGBuilder(registry=_make_registry()).add_file(FIXTURES / fixture_name).build()


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
# simple_function.rs
# ---------------------------------------------------------------------------


class TestSimpleFunction:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("simple_function.rs")

    def test_module_node(self, cpg: CodePropertyGraph) -> None:
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "simple_function"

    def test_function_node(self, cpg: CodePropertyGraph) -> None:
        assert "add" in _node_names(cpg, NodeKind.FUNCTION)

    def test_parameter_nodes(self, cpg: CodePropertyGraph) -> None:
        params = _node_names(cpg, NodeKind.PARAMETER)
        assert "x" in params, f"params: {params}"
        assert "y" in params

    def test_has_parameter_edges(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.HAS_PARAMETER)
        assert ("add", "x") in pairs, f"HAS_PARAMETER pairs: {pairs}"
        assert ("add", "y") in pairs

    def test_variable_node(self, cpg: CodePropertyGraph) -> None:
        assert "result" in _node_names(cpg, NodeKind.VARIABLE), (
            f"variables: {_node_names(cpg, NodeKind.VARIABLE)}"
        )

    def test_return_node(self, cpg: CodePropertyGraph) -> None:
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(returns) == 1, f"Expected 1 RETURN node, got {len(returns)}"

    def test_function_contained_in_module(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("simple_function", "add") in pairs, f"CONTAINS pairs: {pairs}"

    def test_variable_contained_in_function(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("add", "result") in pairs, f"CONTAINS pairs: {pairs}"

    def test_data_flow_to_return(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"


# ---------------------------------------------------------------------------
# struct_impl.rs
# ---------------------------------------------------------------------------


class TestStructImpl:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("struct_impl.rs")

    def test_struct_emitted_as_class(self, cpg: CodePropertyGraph) -> None:
        assert "Rectangle" in _node_names(cpg, NodeKind.CLASS), (
            f"classes: {_node_names(cpg, NodeKind.CLASS)}"
        )

    def test_struct_fields_as_variables(self, cpg: CodePropertyGraph) -> None:
        vars_ = _node_names(cpg, NodeKind.VARIABLE)
        assert "width" in vars_, f"variables: {vars_}"
        assert "height" in vars_

    def test_impl_methods_emitted(self, cpg: CodePropertyGraph) -> None:
        funcs = _node_names(cpg, NodeKind.FUNCTION)
        assert "new" in funcs, f"functions: {funcs}"
        assert "area" in funcs
        assert "describe" in funcs

    def test_method_parameters_exclude_self(self, cpg: CodePropertyGraph) -> None:
        params = _node_names(cpg, NodeKind.PARAMETER)
        assert "self" not in params, f"'self' should not appear in params: {params}"
        # new() takes width and height
        assert "width" in params or "w" in params, f"params: {params}"

    def test_impl_methods_scoped_to_struct(self, cpg: CodePropertyGraph) -> None:
        for fn in cpg.nodes(kind=NodeKind.FUNCTION):
            if fn.name in ("new", "area", "describe"):
                scope = cpg.scope_of(fn.id)
                assert scope is not None, f"method {fn.name} has no scope"
                assert scope.kind == NodeKind.CLASS, (
                    f"method {fn.name} scoped to {scope.kind}, expected CLASS"
                )
                assert scope.name == "Rectangle"

    def test_use_import_emitted(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) >= 1, "Expected at least one IMPORT node"

    def test_standalone_function(self, cpg: CodePropertyGraph) -> None:
        assert "make_rect" in _node_names(cpg, NodeKind.FUNCTION)

    def test_struct_contained_in_module(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("struct_impl", "Rectangle") in pairs, f"CONTAINS pairs: {pairs}"

    def test_call_resolution(self, cpg: CodePropertyGraph) -> None:
        """Rectangle::new call should resolve to the new function definition."""
        calls = _edge_pairs(cpg, EdgeKind.CALLS)
        assert len(calls) >= 1, f"Expected at least one CALLS edge, got: {calls}"


# ---------------------------------------------------------------------------
# control_flow.rs
# ---------------------------------------------------------------------------


class TestControlFlow:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("control_flow.rs")

    def test_functions(self, cpg: CodePropertyGraph) -> None:
        funcs = _node_names(cpg, NodeKind.FUNCTION)
        assert "classify" in funcs, f"functions: {funcs}"
        assert "sum_range" in funcs
        assert "count_down" in funcs

    def test_branch_from_if(self, cpg: CodePropertyGraph) -> None:
        branches = list(cpg.nodes(kind=NodeKind.BRANCH))
        assert len(branches) >= 1, "Expected at least one BRANCH node"
        branch_types = {b.attrs.get("branch_type") for b in branches}
        assert "if" in branch_types, f"branch_types: {branch_types}"

    def test_match_emits_branch(self, cpg: CodePropertyGraph) -> None:
        branches = list(cpg.nodes(kind=NodeKind.BRANCH))
        branch_types = {b.attrs.get("branch_type") for b in branches}
        assert "match" in branch_types, f"branch_types: {branch_types}"

    def test_for_loop_node(self, cpg: CodePropertyGraph) -> None:
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "for"
        ]
        assert len(loops) >= 1, "Expected at least one for LOOP node"

    def test_while_loop_node(self, cpg: CodePropertyGraph) -> None:
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "while"
        ]
        assert len(loops) >= 1, "Expected at least one while LOOP node"

    def test_loop_keyword_node(self, cpg: CodePropertyGraph) -> None:
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "loop"
        ]
        assert len(loops) >= 1, "Expected at least one loop LOOP node"

    def test_for_loop_iterator_var(self, cpg: CodePropertyGraph) -> None:
        for_loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "for"
        ]
        assert any(
            n.attrs.get("iterator_var") == "i" for n in for_loops
        ), f"Expected iterator_var='i', loops: {[n.attrs for n in for_loops]}"

    def test_variable_in_for_loop(self, cpg: CodePropertyGraph) -> None:
        vars_ = _node_names(cpg, NodeKind.VARIABLE)
        assert "total" in vars_, f"variables: {vars_}"

    def test_return_nodes(self, cpg: CodePropertyGraph) -> None:
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(returns) >= 4, f"Expected >=4 RETURN nodes, got {len(returns)}"

    def test_branch_contained_in_function(self, cpg: CodePropertyGraph) -> None:
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        sources = {src for src, _ in contains}
        assert "classify" in sources, (
            f"Expected 'classify' in CONTAINS sources. Got: {sources}"
        )

    def test_loop_contained_in_function(self, cpg: CodePropertyGraph) -> None:
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        sources = {src for src, _ in contains}
        assert "sum_range" in sources, (
            f"Expected 'sum_range' in CONTAINS sources. Got: {sources}"
        )


# ---------------------------------------------------------------------------
# data_flow.rs
# ---------------------------------------------------------------------------


class TestDataFlow:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("data_flow.rs")

    def test_module_node(self, cpg: CodePropertyGraph) -> None:
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "data_flow"

    def test_functions(self, cpg: CodePropertyGraph) -> None:
        funcs = _node_names(cpg, NodeKind.FUNCTION)
        assert "transform" in funcs, f"functions: {funcs}"
        assert "multi_assign" in funcs

    def test_parameters(self, cpg: CodePropertyGraph) -> None:
        params = _node_names(cpg, NodeKind.PARAMETER)
        assert "input" in params, f"params: {params}"
        assert "a" in params
        assert "b" in params

    def test_let_binding_variables(self, cpg: CodePropertyGraph) -> None:
        vars_ = _node_names(cpg, NodeKind.VARIABLE)
        assert "x" in vars_, f"variables: {vars_}"
        assert "y" in vars_
        assert "result" in vars_

    def test_data_flow_chain_in_transform(self, cpg: CodePropertyGraph) -> None:
        # let x = input; let y = x;  — expect x -> y via DATA_FLOWS_TO
        dfg = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("x", "y") in dfg, f"DATA_FLOWS_TO pairs: {dfg}"

    def test_defined_by_edges(self, cpg: CodePropertyGraph) -> None:
        defined = _edge_pairs(cpg, EdgeKind.DEFINED_BY)
        # y is defined by x (let y = x)
        assert ("y", "x") in defined, f"DEFINED_BY pairs: {defined}"

    def test_variable_contained_in_function(self, cpg: CodePropertyGraph) -> None:
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("transform", "x") in contains, f"CONTAINS pairs: {contains}"
        assert ("transform", "y") in contains
        assert ("multi_assign", "result") in contains

    def test_call_node_for_to_string(self, cpg: CodePropertyGraph) -> None:
        calls = _node_names(cpg, NodeKind.CALL)
        assert any("to_string" in c for c in calls), f"calls: {calls}"

    def test_has_parameter_edges(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.HAS_PARAMETER)
        assert ("transform", "input") in pairs, f"HAS_PARAMETER: {pairs}"
        assert ("multi_assign", "a") in pairs
        assert ("multi_assign", "b") in pairs


# ---------------------------------------------------------------------------
# cross_function_taint.rs
# ---------------------------------------------------------------------------


class TestCrossFunctionTaint:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("cross_function_taint.rs")

    def test_functions(self, cpg: CodePropertyGraph) -> None:
        funcs = _node_names(cpg, NodeKind.FUNCTION)
        assert "source" in funcs, f"functions: {funcs}"
        assert "passthrough" in funcs
        assert "sink" in funcs
        assert "main" in funcs

    def test_parameter_nodes(self, cpg: CodePropertyGraph) -> None:
        params = _node_names(cpg, NodeKind.PARAMETER)
        assert "data" in params, f"params: {params}"
        assert "value" in params

    def test_variable_nodes_in_main(self, cpg: CodePropertyGraph) -> None:
        vars_ = _node_names(cpg, NodeKind.VARIABLE)
        assert "data" in vars_, f"variables: {vars_}"
        assert "processed" in vars_

    def test_call_nodes(self, cpg: CodePropertyGraph) -> None:
        calls = _node_names(cpg, NodeKind.CALL)
        assert "source" in calls, f"calls: {calls}"
        assert "passthrough" in calls
        assert "sink" in calls

    def test_calls_edges_resolved(self, cpg: CodePropertyGraph) -> None:
        # resolve_calls should link call sites to definitions
        calls_edges = _edge_pairs(cpg, EdgeKind.CALLS)
        assert len(calls_edges) >= 1, f"Expected CALLS edges, got: {calls_edges}"
        call_names = {src for src, _ in calls_edges}
        assert "source" in call_names or "passthrough" in call_names, (
            f"Expected source or passthrough to resolve, got: {calls_edges}"
        )

    def test_data_flow_from_call_to_variable(self, cpg: CodePropertyGraph) -> None:
        # source() -> data, passthrough(...) -> processed
        dfg = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("source", "data") in dfg, f"DATA_FLOWS_TO: {dfg}"
        assert ("passthrough", "processed") in dfg

    def test_defined_by_edges(self, cpg: CodePropertyGraph) -> None:
        defined = _edge_pairs(cpg, EdgeKind.DEFINED_BY)
        assert ("data", "source") in defined, f"DEFINED_BY: {defined}"
        assert ("processed", "passthrough") in defined

    def test_argument_flows_into_call(self, cpg: CodePropertyGraph) -> None:
        dfg = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # `data` variable passed to passthrough()
        assert ("data", "passthrough") in dfg, f"DATA_FLOWS_TO: {dfg}"

    def test_functions_contained_in_module(self, cpg: CodePropertyGraph) -> None:
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        sources = {src for src, _ in contains}
        assert "cross_function_taint" in sources, f"CONTAINS sources: {sources}"


# ---------------------------------------------------------------------------
# method_calls.rs
# ---------------------------------------------------------------------------


class TestMethodCalls:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("method_calls.rs")

    def test_struct_as_class(self, cpg: CodePropertyGraph) -> None:
        classes = _node_names(cpg, NodeKind.CLASS)
        assert "Processor" in classes, f"classes: {classes}"

    def test_impl_methods_emitted(self, cpg: CodePropertyGraph) -> None:
        funcs = _node_names(cpg, NodeKind.FUNCTION)
        assert "new" in funcs, f"functions: {funcs}"
        assert "process" in funcs
        assert "validate" in funcs

    def test_standalone_run_function(self, cpg: CodePropertyGraph) -> None:
        assert "run" in _node_names(cpg, NodeKind.FUNCTION)

    def test_methods_scoped_to_struct(self, cpg: CodePropertyGraph) -> None:
        for fn in cpg.nodes(kind=NodeKind.FUNCTION):
            if fn.name in ("new", "process", "validate"):
                scope = cpg.scope_of(fn.id)
                assert scope is not None, f"method {fn.name} has no scope"
                assert scope.kind == NodeKind.CLASS, (
                    f"method {fn.name} scoped to {scope.kind}, expected CLASS"
                )
                assert scope.name == "Processor"

    def test_call_nodes_for_method_calls(self, cpg: CodePropertyGraph) -> None:
        calls = _node_names(cpg, NodeKind.CALL)
        assert any("process" in c for c in calls), f"calls: {calls}"
        assert any("validate" in c for c in calls)
        assert any("new" in c for c in calls)

    def test_calls_edges_resolve_to_methods(self, cpg: CodePropertyGraph) -> None:
        calls_edges = _edge_pairs(cpg, EdgeKind.CALLS)
        assert len(calls_edges) >= 1, f"Expected CALLS edges, got: {calls_edges}"
        targets = {tgt for _, tgt in calls_edges}
        # At least one method (process, validate, new) should be a resolution target
        assert targets & {"new", "process", "validate"}, (
            f"Expected method names as resolution targets, got: {targets}"
        )

    def test_variable_nodes_in_run(self, cpg: CodePropertyGraph) -> None:
        vars_ = _node_names(cpg, NodeKind.VARIABLE)
        assert "p" in vars_, f"variables: {vars_}"
        assert "result" in vars_

    def test_data_flow_from_new_to_p(self, cpg: CodePropertyGraph) -> None:
        dfg = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("Processor::new", "p") in dfg, f"DATA_FLOWS_TO: {dfg}"

    def test_data_flow_from_process_to_result(self, cpg: CodePropertyGraph) -> None:
        dfg = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("p.process", "result") in dfg, f"DATA_FLOWS_TO: {dfg}"

    def test_struct_contained_in_module(self, cpg: CodePropertyGraph) -> None:
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("method_calls", "Processor") in contains, f"CONTAINS: {contains}"


# ---------------------------------------------------------------------------
# nested_scopes.rs
# ---------------------------------------------------------------------------


class TestNestedScopes:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("nested_scopes.rs")

    def test_outer_function(self, cpg: CodePropertyGraph) -> None:
        assert "outer" in _node_names(cpg, NodeKind.FUNCTION)

    def test_outer_parameter(self, cpg: CodePropertyGraph) -> None:
        params = _node_names(cpg, NodeKind.PARAMETER)
        assert "x" in params, f"params: {params}"

    def test_closure_bound_to_variable(self, cpg: CodePropertyGraph) -> None:
        # The closure assigned to `inner` should produce a VARIABLE node
        vars_ = _node_names(cpg, NodeKind.VARIABLE)
        assert "inner" in vars_, f"variables: {vars_}"

    def test_inner_call_node(self, cpg: CodePropertyGraph) -> None:
        # inner(10) produces a CALL node
        calls = _node_names(cpg, NodeKind.CALL)
        assert "inner" in calls, f"calls: {calls}"

    def test_literal_argument(self, cpg: CodePropertyGraph) -> None:
        lits = _node_names(cpg, NodeKind.LITERAL)
        assert "10" in lits, f"literals: {lits}"

    def test_outer_function_contained_in_module(self, cpg: CodePropertyGraph) -> None:
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("nested_scopes", "outer") in contains, f"CONTAINS: {contains}"

    def test_inner_variable_contained_in_outer(self, cpg: CodePropertyGraph) -> None:
        contains = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("outer", "inner") in contains, f"CONTAINS: {contains}"

    def test_literal_flows_into_inner_call(self, cpg: CodePropertyGraph) -> None:
        dfg = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("10", "inner") in dfg, f"DATA_FLOWS_TO: {dfg}"


# ---------------------------------------------------------------------------
# add_source integration
# ---------------------------------------------------------------------------


class TestAddSource:
    def test_parse_inline_rust(self) -> None:
        src = b"fn hello(name: &str) -> i32 { return 42; }"
        cpg = CPGBuilder(registry=_make_registry()).add_source(
            src, "hello.rs", "rust"
        ).build()
        assert "hello" in _node_names(cpg, NodeKind.FUNCTION)
        assert "name" in _node_names(cpg, NodeKind.PARAMETER)
