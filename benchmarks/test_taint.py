"""Benchmarks for taint analysis."""

from __future__ import annotations

from treeloom import TaintPolicy
from treeloom.analysis.taint import TaintResult
from treeloom.graph.cpg import CodePropertyGraph


def test_taint_small_graph(
    benchmark: object, cpg_small: CodePropertyGraph, taint_policy: TaintPolicy
) -> None:
    """Taint analysis on the small (~500 LOC) CPG."""
    result: TaintResult = benchmark(lambda: cpg_small.taint(taint_policy))  # type: ignore[call-arg]
    assert result is not None


def test_taint_medium_graph(
    benchmark: object, cpg_medium: CodePropertyGraph, taint_policy: TaintPolicy
) -> None:
    """Taint analysis on the medium (~2000 LOC) CPG."""
    result: TaintResult = benchmark(lambda: cpg_medium.taint(taint_policy))  # type: ignore[call-arg]
    assert result is not None
