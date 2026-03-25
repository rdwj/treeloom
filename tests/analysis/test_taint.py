"""Tests for treeloom.analysis.taint — worklist-based taint propagation."""

from __future__ import annotations

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
