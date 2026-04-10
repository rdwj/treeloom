"""Tests for inter-procedural data flow edge construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.analysis.summary import compute_summaries
from treeloom.graph.builder import CPGBuilder
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import NodeKind


@pytest.fixture()
def builder() -> CPGBuilder:
    """A builder with no registry (hand-built graph testing)."""
    return CPGBuilder(registry=None)


def _loc(line: int, col: int = 0) -> SourceLocation:
    return SourceLocation(file=Path("test.py"), line=line, column=col)


class TestArgFlowsToParam:
    """Arguments at a call site should flow to the callee's parameters."""

    def test_single_arg_flows_to_single_param(self, builder: CPGBuilder):
        # Build a mini-graph by hand:
        #   caller() { a = "data"; callee(a) }
        #   callee(x) { return x }
        mod_id = builder.emit_module("test", Path("test.py"))

        # callee function with one parameter
        callee_id = builder.emit_function("callee", _loc(1), mod_id)
        param_x = builder.emit_parameter("x", _loc(1, 10), callee_id, position=0)
        ret_id = builder.emit_return(_loc(2), callee_id)
        builder.emit_data_flow(param_x, ret_id)

        # caller function
        caller_id = builder.emit_function("caller", _loc(4), mod_id)
        var_a = builder.emit_variable("a", _loc(5), caller_id)
        call_id = builder.emit_call("callee", _loc(6), caller_id, args=["a"])

        # The visitor would create: var_a -> call_id (argument flows to call)
        builder.emit_data_flow(var_a, call_id)

        # Add CALLS edge (normally done by call resolution)
        builder._cpg.add_edge(
            CpgEdge(source=call_id, target=callee_id, kind=EdgeKind.CALLS)
        )

        # Run inter-procedural DFG
        builder._build_interprocedural_dfg(compute_summaries(builder._cpg))

        # Verify: var_a should now flow to param_x
        dfg_edges = list(builder._cpg.edges(kind=EdgeKind.DATA_FLOWS_TO))
        arg_to_param = [
            e for e in dfg_edges if e.source == var_a and e.target == param_x
        ]
        assert len(arg_to_param) == 1, (
            f"Expected DATA_FLOWS_TO from var_a to param_x, got edges: "
            f"{[(str(e.source), str(e.target)) for e in dfg_edges]}"
        )

    def test_multiple_args_match_by_position(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))

        # callee(x, y)
        callee_id = builder.emit_function("callee", _loc(1), mod_id)
        param_x = builder.emit_parameter("x", _loc(1, 10), callee_id, position=0)
        param_y = builder.emit_parameter("y", _loc(1, 13), callee_id, position=1)

        # caller: a, b -> callee(a, b)
        caller_id = builder.emit_function("caller", _loc(4), mod_id)
        var_a = builder.emit_variable("a", _loc(5, 0), caller_id)
        var_b = builder.emit_variable("b", _loc(5, 5), caller_id)
        call_id = builder.emit_call("callee", _loc(6), caller_id, args=["a", "b"])

        # Arguments flow to call, in source order
        builder.emit_data_flow(var_a, call_id)
        builder.emit_data_flow(var_b, call_id)

        builder._cpg.add_edge(
            CpgEdge(source=call_id, target=callee_id, kind=EdgeKind.CALLS)
        )

        builder._build_interprocedural_dfg(compute_summaries(builder._cpg))

        dfg_edges = list(builder._cpg.edges(kind=EdgeKind.DATA_FLOWS_TO))

        # var_a (earlier in source) -> param_x (position 0)
        assert any(e.source == var_a and e.target == param_x for e in dfg_edges), (
            "Expected var_a to flow to param_x (position 0)"
        )
        # var_b (later in source) -> param_y (position 1)
        assert any(e.source == var_b and e.target == param_y for e in dfg_edges), (
            "Expected var_b to flow to param_y (position 1)"
        )

    def test_fewer_args_than_params(self, builder: CPGBuilder):
        """When fewer arguments than parameters, only wire what's available."""
        mod_id = builder.emit_module("test", Path("test.py"))

        callee_id = builder.emit_function("callee", _loc(1), mod_id)
        param_x = builder.emit_parameter("x", _loc(1, 10), callee_id, position=0)
        builder.emit_parameter("y", _loc(1, 13), callee_id, position=1)

        caller_id = builder.emit_function("caller", _loc(4), mod_id)
        var_a = builder.emit_variable("a", _loc(5), caller_id)
        call_id = builder.emit_call("callee", _loc(6), caller_id, args=["a"])
        builder.emit_data_flow(var_a, call_id)

        builder._cpg.add_edge(
            CpgEdge(source=call_id, target=callee_id, kind=EdgeKind.CALLS)
        )

        builder._build_interprocedural_dfg(compute_summaries(builder._cpg))

        dfg_edges = list(builder._cpg.edges(kind=EdgeKind.DATA_FLOWS_TO))
        # Only first arg wired
        assert any(e.source == var_a and e.target == param_x for e in dfg_edges)


class TestReturnFlowsToCallSite:
    """Return values should flow back to the call site node."""

    def test_return_value_flows_to_caller(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))

        # transform(data) { cleaned = data; return cleaned }
        func_id = builder.emit_function("transform", _loc(1), mod_id)
        param_data = builder.emit_parameter(
            "data", _loc(1, 15), func_id, position=0
        )
        var_cleaned = builder.emit_variable("cleaned", _loc(2), func_id)
        ret_id = builder.emit_return(_loc(3), func_id)
        builder.emit_data_flow(param_data, var_cleaned)
        builder.emit_data_flow(var_cleaned, ret_id)

        # caller: result = transform("input")
        caller_id = builder.emit_function("caller", _loc(5), mod_id)
        lit_input = builder.emit_literal("input", "str", _loc(6, 20), caller_id)
        call_id = builder.emit_call("transform", _loc(6), caller_id, args=["input"])
        builder.emit_data_flow(lit_input, call_id)

        builder._cpg.add_edge(
            CpgEdge(source=call_id, target=func_id, kind=EdgeKind.CALLS)
        )

        builder._build_interprocedural_dfg(compute_summaries(builder._cpg))

        # The return source (var_cleaned) should flow to the call node
        dfg_edges = list(builder._cpg.edges(kind=EdgeKind.DATA_FLOWS_TO))
        ret_to_call = [
            e
            for e in dfg_edges
            if e.source == var_cleaned and e.target == call_id
        ]
        assert len(ret_to_call) == 1, (
            "Expected DATA_FLOWS_TO from return source (cleaned) to call site"
        )


class TestNoInterproceduralForUnresolved:
    """Unresolved calls (no CALLS edge) should get no inter-procedural edges."""

    def test_unresolved_call_no_extra_edges(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))

        caller_id = builder.emit_function("caller", _loc(1), mod_id)
        var_a = builder.emit_variable("a", _loc(2), caller_id)
        call_id = builder.emit_call("unknown_func", _loc(3), caller_id, args=["a"])
        builder.emit_data_flow(var_a, call_id)

        # No CALLS edge — the call is unresolved.
        edge_count_before = builder._cpg.edge_count

        builder._build_interprocedural_dfg(compute_summaries(builder._cpg))

        # No new edges should be created
        assert builder._cpg.edge_count == edge_count_before, (
            "Unresolved calls should not produce inter-procedural DFG edges"
        )


class TestEndToEndWithParsing:
    """Integration tests that parse real Python source and check
    inter-procedural edges in the resulting CPG."""

    @pytest.fixture()
    def _skip_if_no_grammar(self):
        """Skip if tree-sitter-python is not installed."""
        try:
            import tree_sitter_python  # noqa: F401
        except ImportError:
            pytest.skip("tree-sitter-python not installed")

    @pytest.mark.usefixtures("_skip_if_no_grammar")
    def test_parsed_arg_flows_to_param(self):
        source = b'''\
def callee(x, y):
    return x

def caller():
    a = "data"
    result = callee(a, "other")
'''
        cpg = CPGBuilder().add_source(source, "test.py").build()

        # Find the CALLS edge
        calls_edges = list(cpg.edges(kind=EdgeKind.CALLS))
        assert len(calls_edges) >= 1, "Expected at least one CALLS edge"

        # Find parameter nodes for callee
        params = [
            n for n in cpg.nodes(kind=NodeKind.PARAMETER)
            if n.scope is not None
            and cpg.node(n.scope) is not None
            and cpg.node(n.scope).name == "callee"
        ]
        assert len(params) >= 2, f"Expected 2 params for callee, got {len(params)}"

        # There should be DATA_FLOWS_TO edges reaching the parameters
        # from nodes outside the callee function
        dfg_edges = list(cpg.edges(kind=EdgeKind.DATA_FLOWS_TO))
        param_ids = {p.id for p in params}
        cross_boundary = [
            e for e in dfg_edges
            if e.target in param_ids
            and cpg.node(e.source) is not None
            and cpg.node(e.source).scope != params[0].scope
        ]
        assert len(cross_boundary) >= 1, (
            "Expected at least one cross-boundary DATA_FLOWS_TO edge "
            "from caller argument to callee parameter"
        )

    @pytest.mark.usefixtures("_skip_if_no_grammar")
    def test_parsed_return_flows_back(self):
        source = b'''\
def transform(data):
    cleaned = data
    return cleaned

def caller():
    result = transform("input")
'''
        cpg = CPGBuilder().add_source(source, "test.py").build()

        # Find the call node for transform()
        call_nodes = [
            n for n in cpg.nodes(kind=NodeKind.CALL)
            if n.name == "transform"
        ]
        assert len(call_nodes) >= 1, "Expected a CALL node for transform"
        call_node = call_nodes[0]

        # The call should have DATA_FLOWS_TO edges pointing TO it
        # (from the return value propagation)
        dfg_edges = list(cpg.edges(kind=EdgeKind.DATA_FLOWS_TO))
        incoming = [e for e in dfg_edges if e.target == call_node.id]

        # Should have at least the original argument + return value flow
        # The return flow means something from inside transform() flows
        # to the call site
        transform_funcs = [
            n for n in cpg.nodes(kind=NodeKind.FUNCTION)
            if n.name == "transform"
        ]
        assert len(transform_funcs) == 1
        func_id = transform_funcs[0].id

        # Check that some node scoped inside transform flows to the call
        return_flow = [
            e for e in incoming
            if cpg.node(e.source) is not None
            and cpg.node(e.source).scope == func_id
        ]
        assert len(return_flow) >= 1, (
            "Expected return value to flow from transform() body to call site"
        )
