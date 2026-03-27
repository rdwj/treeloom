"""Shared fixtures for analysis tests.

Provides helper functions for building hand-crafted CPGs without needing
a language parser. This lets us test analysis logic in isolation.
"""

from __future__ import annotations

from pathlib import Path

from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind

FAKE_FILE = Path("test.py")


def _loc(line: int = 1, col: int = 0) -> SourceLocation:
    return SourceLocation(file=FAKE_FILE, line=line, column=col)


def make_node(
    kind: NodeKind,
    name: str,
    nid: str,
    scope: str | None = None,
    line: int = 1,
    **attrs: object,
) -> CpgNode:
    """Shorthand for creating a CpgNode with a readable ID."""
    return CpgNode(
        id=NodeId(nid),
        kind=kind,
        name=name,
        location=_loc(line),
        scope=NodeId(scope) if scope else None,
        attrs=dict(attrs),
    )


def add_edge(cpg: CodePropertyGraph, src: str, tgt: str, kind: EdgeKind, **attrs: object) -> None:
    """Add an edge between two nodes identified by their string IDs."""
    cpg.add_edge(CpgEdge(source=NodeId(src), target=NodeId(tgt), kind=kind, attrs=dict(attrs)))
