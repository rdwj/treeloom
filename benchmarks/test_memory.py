"""Memory usage measurements for CPG build and taint analysis.

These are regular pytest tests (not benchmark fixtures). They measure the
RSS delta during each operation and assert it stays under a generous ceiling.
"""

from __future__ import annotations

import gc

import psutil

from treeloom import CPGBuilder, TaintPolicy
from treeloom.graph.cpg import CodePropertyGraph

_500_MB = 500 * 1024 * 1024  # bytes


def _rss() -> int:
    """Current process RSS in bytes."""
    return psutil.Process().memory_info().rss


def test_memory_build(source_medium: bytes) -> None:
    """Peak RSS growth during medium CPG build must stay under 500 MB."""
    gc.collect()
    before = _rss()

    cpg = CPGBuilder().add_source(source_medium, "bench_mem.py", "python").build()

    gc.collect()
    after = _rss()
    delta = after - before

    print(f"\n  RSS delta (build): {delta / 1024 / 1024:.1f} MB")
    assert cpg.node_count > 0
    assert delta < _500_MB, f"CPG build consumed {delta / 1024 / 1024:.0f} MB RSS (limit 500 MB)"


def test_memory_taint(cpg_medium: CodePropertyGraph, taint_policy: TaintPolicy) -> None:
    """Peak RSS growth during taint analysis must stay under 500 MB."""
    gc.collect()
    before = _rss()

    result = cpg_medium.taint(taint_policy)

    gc.collect()
    after = _rss()
    delta = after - before

    print(f"\n  RSS delta (taint): {delta / 1024 / 1024:.1f} MB")
    assert result is not None
    assert delta < _500_MB, (
        f"Taint analysis consumed {delta / 1024 / 1024:.0f} MB RSS (limit 500 MB)"
    )
