"""Tests for treeloom.analysis.summary — function summary computation."""

from __future__ import annotations

from treeloom.analysis.summary import compute_summaries
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeId, NodeKind

from .conftest import add_edge, make_node


def _build_simple_cpg() -> CodePropertyGraph:
    """Build a CPG with one function whose parameter flows to a return.

    Represents roughly::

        def greet(name):
            msg = name
            return msg
    """
    cpg = CodePropertyGraph()

    cpg.add_node(make_node(NodeKind.MODULE, "test", "mod", line=1))
    cpg.add_node(make_node(NodeKind.FUNCTION, "greet", "fn", scope="mod", line=2))
    cpg.add_node(make_node(
        NodeKind.PARAMETER, "name", "param0", scope="fn", line=2, position=0,
    ))
    cpg.add_node(make_node(NodeKind.VARIABLE, "msg", "var_msg", scope="fn", line=3))
    cpg.add_node(make_node(NodeKind.RETURN, "return", "ret", scope="fn", line=4))

    add_edge(cpg, "mod", "fn", EdgeKind.CONTAINS)
    add_edge(cpg, "fn", "param0", EdgeKind.HAS_PARAMETER)
    add_edge(cpg, "fn", "var_msg", EdgeKind.CONTAINS)
    add_edge(cpg, "fn", "ret", EdgeKind.CONTAINS)

    # Data flow: param0 -> var_msg -> ret
    add_edge(cpg, "param0", "var_msg", EdgeKind.DATA_FLOWS_TO)
    add_edge(cpg, "var_msg", "ret", EdgeKind.DATA_FLOWS_TO)

    return cpg


def test_param_flows_to_return():
    """Parameter that reaches a RETURN is recorded in params_to_return."""
    cpg = _build_simple_cpg()
    summaries = compute_summaries(cpg)

    assert NodeId("fn") in summaries
    summary = summaries[NodeId("fn")]
    assert summary.function_name == "greet"
    assert 0 in summary.params_to_return


def test_param_flows_to_call_sink():
    """Parameter that reaches a CALL node is recorded in params_to_sinks."""
    cpg = CodePropertyGraph()
    cpg.add_node(make_node(NodeKind.MODULE, "test", "mod"))
    cpg.add_node(make_node(NodeKind.FUNCTION, "process", "fn", scope="mod", line=2))
    cpg.add_node(make_node(
        NodeKind.PARAMETER, "data", "p0", scope="fn", line=2, position=0,
    ))
    cpg.add_node(make_node(NodeKind.CALL, "execute", "call1", scope="fn", line=3))

    add_edge(cpg, "mod", "fn", EdgeKind.CONTAINS)
    add_edge(cpg, "fn", "p0", EdgeKind.HAS_PARAMETER)
    add_edge(cpg, "fn", "call1", EdgeKind.CONTAINS)
    add_edge(cpg, "p0", "call1", EdgeKind.DATA_FLOWS_TO)

    summaries = compute_summaries(cpg)
    summary = summaries[NodeId("fn")]
    assert 0 in summary.params_to_sinks
    assert NodeId("call1") in summary.params_to_sinks[0]


def test_no_data_flow_yields_empty_summary():
    """A function with no DFG edges produces an empty summary."""
    cpg = CodePropertyGraph()
    cpg.add_node(make_node(NodeKind.MODULE, "test", "mod"))
    cpg.add_node(make_node(NodeKind.FUNCTION, "noop", "fn", scope="mod", line=2))
    cpg.add_node(make_node(
        NodeKind.PARAMETER, "x", "p0", scope="fn", line=2, position=0,
    ))

    add_edge(cpg, "mod", "fn", EdgeKind.CONTAINS)
    add_edge(cpg, "fn", "p0", EdgeKind.HAS_PARAMETER)

    summaries = compute_summaries(cpg)
    summary = summaries[NodeId("fn")]
    assert summary.params_to_return == []
    assert summary.params_to_sinks == {}


def test_multiple_params():
    """Only the parameter that actually flows to the return is recorded."""
    cpg = CodePropertyGraph()
    cpg.add_node(make_node(NodeKind.MODULE, "test", "mod"))
    cpg.add_node(make_node(NodeKind.FUNCTION, "pick", "fn", scope="mod", line=2))
    cpg.add_node(make_node(
        NodeKind.PARAMETER, "a", "p0", scope="fn", line=2, position=0,
    ))
    cpg.add_node(make_node(
        NodeKind.PARAMETER, "b", "p1", scope="fn", line=2, position=1,
    ))
    cpg.add_node(make_node(NodeKind.RETURN, "return", "ret", scope="fn", line=3))

    add_edge(cpg, "mod", "fn", EdgeKind.CONTAINS)
    add_edge(cpg, "fn", "p0", EdgeKind.HAS_PARAMETER)
    add_edge(cpg, "fn", "p1", EdgeKind.HAS_PARAMETER)
    add_edge(cpg, "fn", "ret", EdgeKind.CONTAINS)

    # Only p1 flows to the return
    add_edge(cpg, "p1", "ret", EdgeKind.DATA_FLOWS_TO)

    summaries = compute_summaries(cpg)
    summary = summaries[NodeId("fn")]
    assert 0 not in summary.params_to_return
    assert 1 in summary.params_to_return
