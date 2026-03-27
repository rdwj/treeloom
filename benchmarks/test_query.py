"""Benchmarks for graph query operations."""

from __future__ import annotations

from treeloom import EdgeKind, NodeKind
from treeloom.graph.cpg import CodePropertyGraph


def test_nodes_by_kind(benchmark: object, cpg_medium: CodePropertyGraph) -> None:
    """Iterate all FUNCTION nodes in the medium CPG."""

    def _run() -> int:
        return sum(1 for _ in cpg_medium.nodes(kind=NodeKind.FUNCTION))

    count: int = benchmark(_run)  # type: ignore[call-arg]
    assert count > 0


def test_paths_between(benchmark: object, cpg_medium: CodePropertyGraph) -> None:
    """Find paths between two function nodes."""
    functions = list(cpg_medium.nodes(kind=NodeKind.FUNCTION))
    if len(functions) < 2:
        return
    src = functions[0].id
    tgt = functions[-1].id

    paths = benchmark(  # type: ignore[call-arg]
        lambda: cpg_medium.query().paths_between(src, tgt, cutoff=5)
    )
    assert isinstance(paths, list)


def test_reachable_from(benchmark: object, cpg_medium: CodePropertyGraph) -> None:
    """Forward reachability from the first FUNCTION node."""
    functions = list(cpg_medium.nodes(kind=NodeKind.FUNCTION))
    if not functions:
        return
    root = functions[0].id

    reachable = benchmark(  # type: ignore[call-arg]
        lambda: cpg_medium.query().reachable_from(
            root, edge_kinds=frozenset({EdgeKind.DATA_FLOWS_TO})
        )
    )
    assert isinstance(reachable, set)
