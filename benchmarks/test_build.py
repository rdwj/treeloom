"""Benchmarks for CPG construction from Python source."""

from __future__ import annotations

from treeloom import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph


def test_build_small(benchmark: object, source_small: bytes) -> None:
    """Build a CPG from ~500 LOC synthetic source."""
    result: CodePropertyGraph = benchmark(  # type: ignore[call-arg]
        lambda: CPGBuilder().add_source(source_small, "bench_small.py", "python").build()
    )
    assert result.node_count > 0


def test_build_medium(benchmark: object, source_medium: bytes) -> None:
    """Build a CPG from ~2000 LOC synthetic source."""
    result: CodePropertyGraph = benchmark(  # type: ignore[call-arg]
        lambda: CPGBuilder().add_source(source_medium, "bench_medium.py", "python").build()
    )
    assert result.node_count > 0


def test_build_large(benchmark: object, source_large: bytes) -> None:
    """Build a CPG from ~5000 LOC synthetic source."""
    result: CodePropertyGraph = benchmark(  # type: ignore[call-arg]
        lambda: CPGBuilder().add_source(source_large, "bench_large.py", "python").build()
    )
    assert result.node_count > 0
