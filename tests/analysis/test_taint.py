"""Tests for treeloom.analysis.taint — worklist-based taint propagation."""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.analysis.taint import (
    TaintLabel,
    TaintPolicy,
    TaintResult,
    run_taint,
)
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeId, NodeKind

from .conftest import add_edge, make_node

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _source_policy(
    source_ids: set[str],
    sink_ids: set[str],
    sanitizer_ids: set[str] | None = None,
) -> TaintPolicy:
    """Create a simple policy driven by node ID membership."""
    san = sanitizer_ids or set()
    return TaintPolicy(
        sources=lambda n: (
            TaintLabel(name="taint", origin=n.id)
            if str(n.id) in source_ids else None
        ),
        sinks=lambda n: str(n.id) in sink_ids,
        sanitizers=lambda n: str(n.id) in san,
    )


# ---------------------------------------------------------------------------
# TaintLabel hashability
# ---------------------------------------------------------------------------

class TestTaintLabelHashable:
    def test_label_in_frozenset(self):
        label = TaintLabel(name="a", origin=NodeId("x"))
        fs = frozenset({label})
        assert label in fs

    def test_equal_labels(self):
        a = TaintLabel(name="a", origin=NodeId("x"))
        b = TaintLabel(name="a", origin=NodeId("x"))
        assert a == b
        assert hash(a) == hash(b)

    def test_different_labels(self):
        a = TaintLabel(name="a", origin=NodeId("x"))
        b = TaintLabel(name="b", origin=NodeId("y"))
        assert a != b


# ---------------------------------------------------------------------------
# One-hop: source -> sink
# ---------------------------------------------------------------------------

class TestOneHop:
    def test_direct_source_to_sink(self):
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=2))
        add_edge(cpg, "s1", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}))

        assert len(result.paths) == 1
        path = result.paths[0]
        assert str(path.source.id) == "s1"
        assert str(path.sink.id) == "k1"
        assert not path.is_sanitized

    def test_no_path_when_no_edge(self):
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=2))
        # No DATA_FLOWS_TO edge

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}))
        assert len(result.paths) == 0


# ---------------------------------------------------------------------------
# Two-hop: source -> intermediate -> sink
# ---------------------------------------------------------------------------

class TestTwoHop:
    def test_source_intermediate_sink(self):
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.VARIABLE, "mid", "m1", line=2))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=3))
        add_edge(cpg, "s1", "m1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "m1", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}))

        assert len(result.paths) == 1
        path = result.paths[0]
        assert str(path.source.id) == "s1"
        assert str(path.sink.id) == "k1"
        assert len(path.intermediates) >= 2  # at least source + sink


# ---------------------------------------------------------------------------
# Sanitizer on path
# ---------------------------------------------------------------------------

class TestSanitizer:
    def test_sanitizer_marks_path(self):
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.CALL, "sanitize", "san", line=2))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=3))
        add_edge(cpg, "s1", "san", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "san", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}, {"san"}))

        assert len(result.paths) == 1
        path = result.paths[0]
        assert path.is_sanitized
        assert len(path.sanitizers) == 1

    def test_unsanitized_paths_filter(self):
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.CALL, "sanitize", "san", line=2))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=3))
        add_edge(cpg, "s1", "san", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "san", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}, {"san"}))

        assert len(result.unsanitized_paths()) == 0
        assert len(result.sanitized_paths()) == 1


# ---------------------------------------------------------------------------
# Branching: source -> (branch_a | branch_b) -> sink
# ---------------------------------------------------------------------------

class TestBranching:
    def test_taint_through_both_branches(self):
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.VARIABLE, "left", "b_l", line=2))
        cpg.add_node(make_node(NodeKind.VARIABLE, "right", "b_r", line=3))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=4))

        add_edge(cpg, "s1", "b_l", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "s1", "b_r", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "b_l", "k1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "b_r", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}))

        # One source, one sink => exactly one path
        assert len(result.paths) == 1


# ---------------------------------------------------------------------------
# Convergence: two sources reaching the same sink
# ---------------------------------------------------------------------------

class TestConvergence:
    def test_two_sources_one_sink(self):
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src_a", "s1", line=1))
        cpg.add_node(make_node(NodeKind.VARIABLE, "src_b", "s2", line=2))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=3))
        add_edge(cpg, "s1", "k1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "s2", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1", "s2"}, {"k1"}))

        # Two distinct source->sink paths
        assert len(result.paths) == 2
        sources = {str(p.source.id) for p in result.paths}
        assert sources == {"s1", "s2"}


# ---------------------------------------------------------------------------
# Inter-procedural: source -> call -> function -> sink
# ---------------------------------------------------------------------------

class TestInterProcedural:
    def test_taint_through_call_via_summary(self):
        """Taint flows through a function call when the summary says param->return."""
        cpg = CodePropertyGraph()
        # Function: def transform(x): return x
        cpg.add_node(make_node(NodeKind.FUNCTION, "transform", "fn1", line=1))
        cpg.add_node(make_node(NodeKind.PARAMETER, "x", "p1", scope="fn1", line=1,
                               position=0))
        cpg.add_node(make_node(NodeKind.RETURN, "return", "ret1", scope="fn1", line=2))
        add_edge(cpg, "fn1", "p1", EdgeKind.HAS_PARAMETER)
        add_edge(cpg, "p1", "ret1", EdgeKind.DATA_FLOWS_TO)

        # Call site: result = transform(src)
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=5))
        cpg.add_node(make_node(NodeKind.CALL, "transform", "call1", line=6))
        cpg.add_node(make_node(NodeKind.VARIABLE, "result", "v1", line=6))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=7))
        add_edge(cpg, "s1", "call1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "call1", "fn1", EdgeKind.CALLS)
        # Assignment: result is defined by the call (variable -> call)
        add_edge(cpg, "v1", "call1", EdgeKind.DEFINED_BY)
        # Data also flows call -> result (visitor now emits this)
        add_edge(cpg, "call1", "v1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "v1", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}))

        assert len(result.paths) == 1
        path = result.paths[0]
        assert str(path.source.id) == "s1"
        assert str(path.sink.id) == "k1"

    def test_taint_through_call_via_defined_by_fallback(self):
        """Even without DATA_FLOWS_TO from call to var, DEFINED_BY fallback works."""
        cpg = CodePropertyGraph()
        # Function with param->return
        cpg.add_node(make_node(NodeKind.FUNCTION, "transform", "fn1", line=1))
        cpg.add_node(make_node(NodeKind.PARAMETER, "x", "p1", scope="fn1", line=1,
                               position=0))
        cpg.add_node(make_node(NodeKind.RETURN, "return", "ret1", scope="fn1", line=2))
        add_edge(cpg, "fn1", "p1", EdgeKind.HAS_PARAMETER)
        add_edge(cpg, "p1", "ret1", EdgeKind.DATA_FLOWS_TO)

        # Call site: result = transform(src) — NO DATA_FLOWS_TO from call to var
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=5))
        cpg.add_node(make_node(NodeKind.CALL, "transform", "call1", line=6))
        cpg.add_node(make_node(NodeKind.VARIABLE, "result", "v1", line=6))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=7))
        add_edge(cpg, "s1", "call1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "call1", "fn1", EdgeKind.CALLS)
        add_edge(cpg, "v1", "call1", EdgeKind.DEFINED_BY)
        # No call1 -> v1 DATA_FLOWS_TO edge — testing the fallback
        add_edge(cpg, "v1", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}))

        assert len(result.paths) == 1
        assert str(result.paths[0].sink.id) == "k1"


# ---------------------------------------------------------------------------
# Fixed point / termination
# ---------------------------------------------------------------------------

class TestFixedPoint:
    def test_cycle_terminates(self):
        """A cycle in DFG edges must not cause infinite propagation."""
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.VARIABLE, "a", "a1", line=2))
        cpg.add_node(make_node(NodeKind.VARIABLE, "b", "b1", line=3))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=4))

        add_edge(cpg, "s1", "a1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "a1", "b1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "b1", "a1", EdgeKind.DATA_FLOWS_TO)  # cycle
        add_edge(cpg, "b1", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}))

        assert len(result.paths) == 1


# ---------------------------------------------------------------------------
# TaintResult query methods
# ---------------------------------------------------------------------------

class TestTaintResultQueries:
    @pytest.fixture()
    def result_with_two_paths(self) -> TaintResult:
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.CALL, "sink_a", "k1", line=2))
        cpg.add_node(make_node(NodeKind.CALL, "sanitize", "san", line=3))
        cpg.add_node(make_node(NodeKind.CALL, "sink_b", "k2", line=4))

        add_edge(cpg, "s1", "k1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "s1", "san", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "san", "k2", EdgeKind.DATA_FLOWS_TO)

        return run_taint(cpg, _source_policy({"s1"}, {"k1", "k2"}, {"san"}))

    def test_paths_to_sink(self, result_with_two_paths: TaintResult):
        assert len(result_with_two_paths.paths_to_sink(NodeId("k1"))) == 1
        assert len(result_with_two_paths.paths_to_sink(NodeId("k2"))) == 1

    def test_paths_from_source(self, result_with_two_paths: TaintResult):
        assert len(result_with_two_paths.paths_from_source(NodeId("s1"))) == 2

    def test_unsanitized_vs_sanitized(self, result_with_two_paths: TaintResult):
        assert len(result_with_two_paths.unsanitized_paths()) == 1
        assert len(result_with_two_paths.sanitized_paths()) == 1

    def test_labels_at_sink(self, result_with_two_paths: TaintResult):
        labels = result_with_two_paths.labels_at(NodeId("k1"))
        assert len(labels) >= 1


# ---------------------------------------------------------------------------
# Convergent paths with mixed sanitization
# ---------------------------------------------------------------------------

class TestConvergentSanitization:
    def test_convergent_paths_mixed_sanitization(self):
        """One sanitized path and one bypass path to the same sink must yield
        an unsanitized result — the bypass path dominates."""
        cpg = CodePropertyGraph()
        # source -> sanitizer -> sink  (sanitized route)
        # source -> direct   -> sink   (bypass route)
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.CALL, "sanitize", "san", line=2))
        cpg.add_node(make_node(NodeKind.VARIABLE, "direct", "d1", line=3))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=4))

        add_edge(cpg, "s1", "san", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "san", "k1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "s1", "d1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "d1", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}, {"san"}))

        assert len(result.paths) == 1
        path = result.paths[0]
        # The bypass path means the sink is reachable unsanitized
        assert not path.is_sanitized, (
            "Expected unsanitized because one path bypasses the sanitizer, "
            f"but got sanitizers={[str(s.id) for s in path.sanitizers]}"
        )

    def test_convergent_paths_all_sanitized(self):
        """When every path to the sink passes through a sanitizer, the result
        should be marked as sanitized."""
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.CALL, "san_a", "san1", line=2))
        cpg.add_node(make_node(NodeKind.CALL, "san_b", "san2", line=3))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=4))

        add_edge(cpg, "s1", "san1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "san1", "k1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "s1", "san2", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "san2", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}, {"san1", "san2"}))

        assert len(result.paths) == 1
        assert result.paths[0].is_sanitized, (
            "Expected sanitized because all paths pass through a sanitizer"
        )

    def test_convergent_different_sanitizers_still_sanitized(self):
        """Two paths through different sanitizers: both are sanitized, so no bypass.

        Even though the sanitizer intersection is empty (no common sanitizer),
        is_sanitized should be True because every route passes through at
        least one sanitizer — no unsanitized bypass path exists.
        """
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.CALL, "san_a", "san1", line=2))
        cpg.add_node(make_node(NodeKind.CALL, "san_b", "san2", line=3))
        cpg.add_node(make_node(NodeKind.VARIABLE, "merge", "m1", line=4))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=5))

        add_edge(cpg, "s1", "san1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "san1", "m1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "s1", "san2", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "san2", "m1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "m1", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}, {"san1", "san2"}))

        assert len(result.paths) == 1
        assert result.paths[0].is_sanitized, (
            "Expected sanitized: both branches pass through a sanitizer, "
            "so no unsanitized bypass path exists"
        )


# ---------------------------------------------------------------------------
# Integration: cpg.taint(policy) entry point
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# apply_to: stamp annotations onto the CPG
# ---------------------------------------------------------------------------

class TestApplyTo:
    def _build_three_hop_cpg(self) -> tuple[CodePropertyGraph, TaintResult]:
        """source -> intermediate -> sink with DATA_FLOWS_TO edges."""
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.VARIABLE, "mid", "m1", line=2))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=3))
        add_edge(cpg, "s1", "m1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "m1", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}))
        return cpg, result

    def test_source_annotated(self):
        cpg, result = self._build_three_hop_cpg()
        result.apply_to(cpg)

        assert cpg.get_annotation(NodeId("s1"), "tainted") is True
        assert cpg.get_annotation(NodeId("s1"), "taint_role") == "source"

    def test_sink_annotated(self):
        cpg, result = self._build_three_hop_cpg()
        result.apply_to(cpg)

        assert cpg.get_annotation(NodeId("k1"), "tainted") is True
        assert cpg.get_annotation(NodeId("k1"), "taint_role") == "sink"
        labels = cpg.get_annotation(NodeId("k1"), "taint_labels")
        assert isinstance(labels, list)
        assert len(labels) >= 1

    def test_intermediate_annotated(self):
        cpg, result = self._build_three_hop_cpg()
        result.apply_to(cpg)

        assert cpg.get_annotation(NodeId("m1"), "tainted") is True
        assert cpg.get_annotation(NodeId("m1"), "taint_role") == "intermediate"

    def test_edges_annotated(self):
        cpg, result = self._build_three_hop_cpg()
        result.apply_to(cpg)

        # At least one edge along the path should be annotated
        assert cpg.get_edge_annotation(NodeId("s1"), NodeId("m1"), "tainted") is True
        assert cpg.get_edge_annotation(NodeId("m1"), NodeId("k1"), "tainted") is True

    def test_sink_unsanitized(self):
        cpg, result = self._build_three_hop_cpg()
        result.apply_to(cpg)

        assert cpg.get_annotation(NodeId("k1"), "taint_sanitized") is False

    def test_sanitizer_role(self):
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.CALL, "sanitize", "san", line=2))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=3))
        add_edge(cpg, "s1", "san", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "san", "k1", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1"}, {"san"}))
        result.apply_to(cpg)

        assert cpg.get_annotation(NodeId("san"), "taint_role") == "sanitizer"
        assert cpg.get_annotation(NodeId("k1"), "taint_sanitized") is True

    def test_mixed_sanitization_unsanitized_wins(self):
        """If one path is sanitized and another is not, sink is unsanitized."""
        cpg = CodePropertyGraph()
        # Use a single source with two paths: one through sanitizer, one direct
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.CALL, "sanitize", "san", line=2))
        cpg.add_node(make_node(NodeKind.CALL, "sink_a", "k1", line=3))
        cpg.add_node(make_node(NodeKind.CALL, "sink_b", "k2", line=4))

        # Sanitized path: s1 -> san -> k1
        add_edge(cpg, "s1", "san", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "san", "k1", EdgeKind.DATA_FLOWS_TO)
        # Unsanitized path: s1 -> k2
        add_edge(cpg, "s1", "k2", EdgeKind.DATA_FLOWS_TO)

        result = run_taint(cpg, _source_policy({"s1"}, {"k1", "k2"}, {"san"}))
        result.apply_to(cpg)

        # Sanitized sink should be marked as sanitized
        assert cpg.get_annotation(NodeId("k1"), "taint_sanitized") is True
        # Unsanitized sink should be marked as unsanitized
        assert cpg.get_annotation(NodeId("k2"), "taint_sanitized") is False

    def test_annotations_survive_serialization(self):
        """Annotations set by apply_to should round-trip through to_dict/from_dict."""
        cpg, result = self._build_three_hop_cpg()
        result.apply_to(cpg)

        restored = CodePropertyGraph.from_dict(cpg.to_dict())

        assert restored.get_annotation(NodeId("s1"), "taint_role") == "source"
        assert restored.get_annotation(NodeId("k1"), "taint_role") == "sink"
        assert restored.get_annotation(NodeId("m1"), "tainted") is True


# ---------------------------------------------------------------------------
# Integration: cpg.taint(policy) entry point
# ---------------------------------------------------------------------------

class TestCpgTaintMethod:
    def test_taint_via_cpg_method(self):
        """Verify CodePropertyGraph.taint() delegates to run_taint."""
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.VARIABLE, "src", "s1", line=1))
        cpg.add_node(make_node(NodeKind.CALL, "sink", "k1", line=2))
        add_edge(cpg, "s1", "k1", EdgeKind.DATA_FLOWS_TO)

        result = cpg.taint(_source_policy({"s1"}, {"k1"}))

        assert len(result.paths) == 1


# ---------------------------------------------------------------------------
# Implicit parameter sources
# ---------------------------------------------------------------------------

class TestImplicitParamSources:
    """Tests for TaintPolicy.implicit_param_sources."""

    def test_param_to_sink_found(self):
        """Parameter flows to sink via DATA_FLOWS_TO — implicit source finds it."""
        cpg = CodePropertyGraph()

        func = make_node(NodeKind.FUNCTION, "search", "func:1")
        param = make_node(NodeKind.PARAMETER, "query", "param:1", scope="func:1", position=0)
        var = make_node(NodeKind.VARIABLE, "query", "var:1", scope="func:1", line=2)
        call = make_node(NodeKind.CALL, "execute", "call:1", scope="func:1", line=3)

        for n in [func, param, var, call]:
            cpg.add_node(n)

        add_edge(cpg, "func:1", "param:1", EdgeKind.HAS_PARAMETER)
        add_edge(cpg, "func:1", "var:1", EdgeKind.CONTAINS)
        add_edge(cpg, "func:1", "call:1", EdgeKind.CONTAINS)
        add_edge(cpg, "param:1", "var:1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "var:1", "call:1", EdgeKind.DATA_FLOWS_TO)

        policy = TaintPolicy(
            sources=lambda _: None,  # No explicit sources
            sinks=lambda n: n.kind == NodeKind.CALL and n.name == "execute",
            sanitizers=lambda _: False,
            implicit_param_sources=True,
        )
        result = run_taint(cpg, policy)

        assert len(result.paths) == 1
        path = result.paths[0]
        assert path.source.id == param.id
        assert path.sink.id == call.id
        assert not path.is_sanitized
        label_names = {lb.name for lb in path.labels}
        assert "param:query" in label_names

    def test_explicit_source_not_overridden(self):
        """When a parameter is already an explicit source, implicit doesn't override."""
        cpg = CodePropertyGraph()

        func = make_node(NodeKind.FUNCTION, "handler", "func:1")
        param = make_node(NodeKind.PARAMETER, "request", "param:1", scope="func:1", position=0)
        call = make_node(NodeKind.CALL, "execute", "call:1", scope="func:1", line=2)

        for n in [func, param, call]:
            cpg.add_node(n)

        add_edge(cpg, "func:1", "param:1", EdgeKind.HAS_PARAMETER)
        add_edge(cpg, "func:1", "call:1", EdgeKind.CONTAINS)
        add_edge(cpg, "param:1", "call:1", EdgeKind.DATA_FLOWS_TO)

        explicit_label = TaintLabel(name="user_input", origin=param.id)
        policy = TaintPolicy(
            sources=lambda n: explicit_label if n.id == param.id else None,
            sinks=lambda n: n.kind == NodeKind.CALL,
            sanitizers=lambda _: False,
            implicit_param_sources=True,
        )
        result = run_taint(cpg, policy)

        assert len(result.paths) == 1
        label_names = {lb.name for lb in result.paths[0].labels}
        assert "user_input" in label_names
        assert "param:request" not in label_names

    def test_disabled_by_default(self):
        """implicit_param_sources defaults to False — no param sources unless opted in."""
        cpg = CodePropertyGraph()

        func = make_node(NodeKind.FUNCTION, "search", "func:1")
        param = make_node(NodeKind.PARAMETER, "query", "param:1", scope="func:1", position=0)
        call = make_node(NodeKind.CALL, "execute", "call:1", scope="func:1", line=2)

        for n in [func, param, call]:
            cpg.add_node(n)

        add_edge(cpg, "func:1", "param:1", EdgeKind.HAS_PARAMETER)
        add_edge(cpg, "func:1", "call:1", EdgeKind.CONTAINS)
        add_edge(cpg, "param:1", "call:1", EdgeKind.DATA_FLOWS_TO)

        policy = TaintPolicy(
            sources=lambda _: None,
            sinks=lambda n: n.kind == NodeKind.CALL,
            sanitizers=lambda _: False,
            # implicit_param_sources defaults to False
        )
        result = run_taint(cpg, policy)
        assert len(result.paths) == 0

    def test_multiple_params_multiple_sinks(self):
        """Each parameter gets its own label; both can reach different sinks."""
        cpg = CodePropertyGraph()

        func = make_node(NodeKind.FUNCTION, "process", "func:1")
        p1 = make_node(NodeKind.PARAMETER, "name", "param:1", scope="func:1", position=0)
        p2 = make_node(NodeKind.PARAMETER, "email", "param:2", scope="func:1", position=1)
        sink1 = make_node(NodeKind.CALL, "log", "call:1", scope="func:1", line=3)
        sink2 = make_node(NodeKind.CALL, "send_email", "call:2", scope="func:1", line=4)

        for n in [func, p1, p2, sink1, sink2]:
            cpg.add_node(n)

        add_edge(cpg, "func:1", "param:1", EdgeKind.HAS_PARAMETER)
        add_edge(cpg, "func:1", "param:2", EdgeKind.HAS_PARAMETER)
        add_edge(cpg, "func:1", "call:1", EdgeKind.CONTAINS)
        add_edge(cpg, "func:1", "call:2", EdgeKind.CONTAINS)
        add_edge(cpg, "param:1", "call:1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "param:2", "call:2", EdgeKind.DATA_FLOWS_TO)

        policy = TaintPolicy(
            sources=lambda _: None,
            sinks=lambda n: n.kind == NodeKind.CALL,
            sanitizers=lambda _: False,
            implicit_param_sources=True,
        )
        result = run_taint(cpg, policy)

        assert len(result.paths) == 2
        all_labels = set()
        for p in result.paths:
            for lb in p.labels:
                all_labels.add(lb.name)
        assert "param:name" in all_labels
        assert "param:email" in all_labels

    def test_param_through_sanitizer(self):
        """Implicit param source flowing through a sanitizer is marked sanitized."""
        cpg = CodePropertyGraph()

        func = make_node(NodeKind.FUNCTION, "handler", "func:1")
        param = make_node(NodeKind.PARAMETER, "input", "param:1", scope="func:1", position=0)
        sanitizer = make_node(NodeKind.CALL, "escape", "san:1", scope="func:1", line=2)
        sink = make_node(NodeKind.CALL, "execute", "call:1", scope="func:1", line=3)

        for n in [func, param, sanitizer, sink]:
            cpg.add_node(n)

        add_edge(cpg, "func:1", "param:1", EdgeKind.HAS_PARAMETER)
        add_edge(cpg, "func:1", "san:1", EdgeKind.CONTAINS)
        add_edge(cpg, "func:1", "call:1", EdgeKind.CONTAINS)
        add_edge(cpg, "param:1", "san:1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "san:1", "call:1", EdgeKind.DATA_FLOWS_TO)

        policy = TaintPolicy(
            sources=lambda _: None,
            sinks=lambda n: n.name == "execute",
            sanitizers=lambda n: n.name == "escape",
            implicit_param_sources=True,
        )
        result = run_taint(cpg, policy)

        assert len(result.paths) == 1
        assert result.paths[0].is_sanitized


# ---------------------------------------------------------------------------
# Per-edge taint label tracking (#56)
# ---------------------------------------------------------------------------

class TestEdgeLabels:
    """Tests for per-edge taint label tracking (#56)."""

    def test_edge_labels_tracked(self):
        """Each edge gets the specific labels that flow through it."""
        cpg = CodePropertyGraph()

        src = make_node(NodeKind.VARIABLE, "user_input", "src:1", line=1)
        mid = make_node(NodeKind.VARIABLE, "temp", "mid:1", line=2)
        sink = make_node(NodeKind.CALL, "execute", "sink:1", line=3)

        for n in [src, mid, sink]:
            cpg.add_node(n)

        add_edge(cpg, "src:1", "mid:1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "mid:1", "sink:1", EdgeKind.DATA_FLOWS_TO)

        label = TaintLabel(name="user_input", origin=src.id)
        policy = TaintPolicy(
            sources=lambda n: label if n.id == src.id else None,
            sinks=lambda n: n.id == sink.id,
            sanitizers=lambda _: False,
        )
        result = run_taint(cpg, policy)

        # Both edges should carry the label
        e1_labels = result.edge_labels(src.id, mid.id)
        e2_labels = result.edge_labels(mid.id, sink.id)
        assert label in e1_labels
        assert label in e2_labels

    def test_distinct_labels_on_different_edges(self):
        """Two sources flow through different edges to the same sink."""
        cpg = CodePropertyGraph()

        src_a = make_node(NodeKind.VARIABLE, "name", "src_a:1", line=1)
        src_b = make_node(NodeKind.VARIABLE, "email", "src_b:1", line=2)
        sink = make_node(NodeKind.CALL, "log", "sink:1", line=3)

        for n in [src_a, src_b, sink]:
            cpg.add_node(n)

        add_edge(cpg, "src_a:1", "sink:1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "src_b:1", "sink:1", EdgeKind.DATA_FLOWS_TO)

        label_a = TaintLabel(name="name_data", origin=src_a.id)
        label_b = TaintLabel(name="email_data", origin=src_b.id)

        policy = TaintPolicy(
            sources=lambda n: label_a if n.id == src_a.id else (
                label_b if n.id == src_b.id else None
            ),
            sinks=lambda n: n.id == sink.id,
            sanitizers=lambda _: False,
        )
        result = run_taint(cpg, policy)

        # Edge A→sink should carry label_a only
        ea = result.edge_labels(src_a.id, sink.id)
        assert label_a in ea
        assert label_b not in ea

        # Edge B→sink should carry label_b only
        eb = result.edge_labels(src_b.id, sink.id)
        assert label_b in eb
        assert label_a not in eb

    def test_convergence_merges_labels(self):
        """When two labeled streams merge at a node, the outgoing edge carries both."""
        cpg = CodePropertyGraph()

        src_a = make_node(NodeKind.VARIABLE, "a", "a:1", line=1)
        src_b = make_node(NodeKind.VARIABLE, "b", "b:1", line=2)
        merge = make_node(NodeKind.VARIABLE, "merged", "merge:1", line=3)
        sink = make_node(NodeKind.CALL, "log", "sink:1", line=4)

        for n in [src_a, src_b, merge, sink]:
            cpg.add_node(n)

        add_edge(cpg, "a:1", "merge:1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "b:1", "merge:1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "merge:1", "sink:1", EdgeKind.DATA_FLOWS_TO)

        label_a = TaintLabel(name="data_a", origin=src_a.id)
        label_b = TaintLabel(name="data_b", origin=src_b.id)

        policy = TaintPolicy(
            sources=lambda n: label_a if n.id == src_a.id else (
                label_b if n.id == src_b.id else None
            ),
            sinks=lambda n: n.id == sink.id,
            sanitizers=lambda _: False,
        )
        result = run_taint(cpg, policy)

        # Edge merge→sink should carry both labels
        e_merge = result.edge_labels(merge.id, sink.id)
        assert label_a in e_merge
        assert label_b in e_merge

    def test_edge_labels_empty_for_non_tainted_edge(self):
        """Querying labels on a non-existent edge returns empty frozenset."""
        cpg = CodePropertyGraph()
        src = make_node(NodeKind.VARIABLE, "x", "x:1")
        cpg.add_node(src)

        policy = TaintPolicy(
            sources=lambda _: None,
            sinks=lambda _: False,
            sanitizers=lambda _: False,
        )
        result = run_taint(cpg, policy)
        assert result.edge_labels(NodeId("x:1"), NodeId("y:1")) == frozenset()

    def test_apply_to_uses_per_edge_labels(self):
        """apply_to() should use per-edge labels, not path-level labels."""
        cpg = CodePropertyGraph()

        src_a = make_node(NodeKind.VARIABLE, "name", "src_a:1", line=1)
        src_b = make_node(NodeKind.VARIABLE, "email", "src_b:1", line=2)
        mid = make_node(NodeKind.VARIABLE, "temp", "mid:1", line=3)
        sink = make_node(NodeKind.CALL, "log", "sink:1", line=4)

        for n in [src_a, src_b, mid, sink]:
            cpg.add_node(n)

        # A → mid → sink, B → sink (direct)
        add_edge(cpg, "src_a:1", "mid:1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "mid:1", "sink:1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "src_b:1", "sink:1", EdgeKind.DATA_FLOWS_TO)

        label_a = TaintLabel(name="name_data", origin=src_a.id)
        label_b = TaintLabel(name="email_data", origin=src_b.id)

        policy = TaintPolicy(
            sources=lambda n: label_a if n.id == src_a.id else (
                label_b if n.id == src_b.id else None
            ),
            sinks=lambda n: n.id == sink.id,
            sanitizers=lambda _: False,
        )
        result = run_taint(cpg, policy)
        result.apply_to(cpg)

        # Edge src_a → mid should only carry "name_data"
        ann = cpg.get_edge_annotation(src_a.id, mid.id, "taint_labels")
        assert ann is not None
        assert "name_data" in ann
        assert "email_data" not in ann


# ---------------------------------------------------------------------------
# Integration: parse real Python code and verify inter-procedural taint
# ---------------------------------------------------------------------------

def _skip_if_no_grammar():
    try:
        import tree_sitter_python  # noqa: F401
    except ImportError:
        pytest.skip("tree-sitter-python not installed")


class TestInterProceduralIntegration:
    """Integration tests: parse real Python code, build CPG, run taint.

    These tests use the ``cross_function_taint.py`` fixture which has a
    3-function call chain: handler → process_query → execute_raw → eval.
    User input from ``handler``'s parameter should taint ``eval()``'s argument
    through the chain.
    """

    @pytest.fixture(autouse=True)
    def _require_grammar(self):
        _skip_if_no_grammar()

    def _build_cpg(self, fixture_name: str) -> CodePropertyGraph:
        from treeloom.graph.builder import CPGBuilder
        fixture_path = (
            Path(__file__).parent.parent / "fixtures" / "python" / fixture_name
        )
        return CPGBuilder().add_file(fixture_path).build()

    def test_direct_call_taint_flow(self):
        """Taint flows from caller argument to callee parameter to callee's sink."""
        cpg = self._build_cpg("cross_function_taint.py")

        policy = TaintPolicy(
            sources=lambda _: None,
            sinks=lambda n: n.kind == NodeKind.CALL and n.name == "eval",
            sanitizers=lambda _: False,
            implicit_param_sources=True,
        )
        result = run_taint(cpg, policy)

        dfg = [
            (str(e.source), str(e.target))
            for e in cpg.edges(kind=EdgeKind.DATA_FLOWS_TO)
        ]
        assert len(result.unsanitized_paths()) > 0, (
            f"Expected taint paths to eval(), got none. "
            f"Nodes: {[(n.kind.value, n.name) for n in cpg.nodes()]}, "
            f"DFG edges: {dfg}"
        )

    def test_transitive_call_chain(self):
        """Taint flows through handler → process_query → execute_raw → eval."""
        cpg = self._build_cpg("cross_function_taint.py")

        handler_params = [
            n for n in cpg.nodes(kind=NodeKind.PARAMETER)
            if n.name == "user_input"
        ]
        assert handler_params, "Expected to find 'user_input' parameter"
        source_param = handler_params[0]

        policy = TaintPolicy(
            sources=lambda n: TaintLabel(name="user_input", origin=n.id)
                if n.id == source_param.id else None,
            sinks=lambda n: n.kind == NodeKind.CALL and n.name == "eval",
            sanitizers=lambda _: False,
        )
        result = run_taint(cpg, policy)

        unsanitized = result.unsanitized_paths()
        calls = [
            (str(e.source), str(e.target))
            for e in cpg.edges(kind=EdgeKind.CALLS)
        ]
        dfg = [
            (str(e.source), str(e.target))
            for e in cpg.edges(kind=EdgeKind.DATA_FLOWS_TO)
        ]
        assert len(unsanitized) > 0, (
            f"Expected transitive taint from user_input to eval(). "
            f"CALLS edges: {calls}, DFG edges: {dfg}"
        )
        # Verify the path traverses all expected functions
        path = unsanitized[0]
        node_names = [n.name for n in path.intermediates]
        assert "user_input" in node_names, f"Expected user_input in path: {node_names}"
        assert "eval" in node_names, f"Expected eval in path: {node_names}"

    def test_intermediate_params_tainted(self):
        """Intermediate parameters (query, sql) should carry taint in the chain."""
        cpg = self._build_cpg("cross_function_taint.py")

        handler_params = [
            n for n in cpg.nodes(kind=NodeKind.PARAMETER)
            if n.name == "user_input"
        ]
        source_param = handler_params[0]

        policy = TaintPolicy(
            sources=lambda n: TaintLabel(name="user_input", origin=n.id)
                if n.id == source_param.id else None,
            sinks=lambda n: n.kind == NodeKind.CALL and n.name == "eval",
            sanitizers=lambda _: False,
        )
        result = run_taint(cpg, policy)

        assert len(result.paths) > 0
        # query and sql parameters should have been tainted in transit
        query_param = next(
            (n for n in cpg.nodes(kind=NodeKind.PARAMETER) if n.name == "query"),
            None,
        )
        sql_param = next(
            (n for n in cpg.nodes(kind=NodeKind.PARAMETER) if n.name == "sql"),
            None,
        )
        assert query_param is not None and sql_param is not None
        assert result.labels_at(query_param.id), (
            "Expected 'query' parameter to carry taint labels"
        )
        assert result.labels_at(sql_param.id), (
            "Expected 'sql' parameter to carry taint labels"
        )
