"""Benchmarks for CPG serialization and deserialization."""

from __future__ import annotations

import pytest

from treeloom import CodePropertyGraph, from_json, to_json


@pytest.fixture(scope="module")
def cpg_json(cpg_medium: CodePropertyGraph) -> str:
    return to_json(cpg_medium)


@pytest.fixture(scope="module")
def cpg_dict(cpg_medium: CodePropertyGraph) -> dict:  # type: ignore[type-arg]
    return cpg_medium.to_dict()


def test_to_json(benchmark: object, cpg_medium: CodePropertyGraph) -> None:
    """Serialize a medium CPG to JSON."""
    result: str = benchmark(lambda: to_json(cpg_medium))  # type: ignore[call-arg]
    assert result.startswith("{")


def test_from_json(benchmark: object, cpg_json: str) -> None:
    """Deserialize a medium CPG from JSON."""
    result: CodePropertyGraph = benchmark(lambda: from_json(cpg_json))  # type: ignore[call-arg]
    assert result.node_count > 0


def test_to_dict(benchmark: object, cpg_medium: CodePropertyGraph) -> None:
    """Convert a medium CPG to a plain dict."""
    result: dict = benchmark(lambda: cpg_medium.to_dict())  # type: ignore[call-arg, type-arg]
    assert "nodes" in result


def test_from_dict(benchmark: object, cpg_dict: dict) -> None:  # type: ignore[type-arg]
    """Reconstruct a medium CPG from a plain dict."""
    result: CodePropertyGraph = benchmark(  # type: ignore[call-arg]
        lambda: CodePropertyGraph.from_dict(cpg_dict)
    )
    assert result.node_count > 0
