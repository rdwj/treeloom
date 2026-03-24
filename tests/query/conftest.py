"""Shared fixtures for query tests.

Re-uses the helper functions from analysis/conftest for building hand-crafted
CPGs, and adds query-specific graph builders.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind

FAKE_FILE = Path("test.py")
OTHER_FILE = Path("other.py")


def _loc(line: int = 1, col: int = 0, file: Path = FAKE_FILE) -> SourceLocation:
    return SourceLocation(file=file, line=line, column=col)


def make_node(
    kind: NodeKind,
    name: str,
    nid: str,
    scope: str | None = None,
    line: int = 1,
    file: Path = FAKE_FILE,
    **attrs: object,
) -> CpgNode:
    return CpgNode(
        id=NodeId(nid),
        kind=kind,
        name=name,
        location=_loc(line, file=file),
        scope=NodeId(scope) if scope else None,
        attrs=dict(attrs),
    )


def add_edge(cpg: CodePropertyGraph, src: str, tgt: str, kind: EdgeKind) -> None:
    cpg.add_edge(CpgEdge(source=NodeId(src), target=NodeId(tgt), kind=kind))


@pytest.fixture()
def linear_cpg() -> CodePropertyGraph:
    """A -> B -> C -> D via DATA_FLOWS_TO, all in one function scope.

    Also adds CONTAINS edges from the function to each variable.
    """
    cpg = CodePropertyGraph()
    fn = make_node(NodeKind.FUNCTION, "fn", "fn", line=1)
    a = make_node(NodeKind.PARAMETER, "a", "a", scope="fn", line=2)
    b = make_node(NodeKind.VARIABLE, "b", "b", scope="fn", line=3)
    c = make_node(NodeKind.VARIABLE, "c", "c", scope="fn", line=4)
    d = make_node(NodeKind.CALL, "sink", "d", scope="fn", line=5)

    for node in [fn, a, b, c, d]:
        cpg.add_node(node)

    add_edge(cpg, "fn", "a", EdgeKind.CONTAINS)
    add_edge(cpg, "fn", "b", EdgeKind.CONTAINS)
    add_edge(cpg, "fn", "c", EdgeKind.CONTAINS)
    add_edge(cpg, "fn", "d", EdgeKind.CONTAINS)
    add_edge(cpg, "a", "b", EdgeKind.DATA_FLOWS_TO)
    add_edge(cpg, "b", "c", EdgeKind.DATA_FLOWS_TO)
    add_edge(cpg, "c", "d", EdgeKind.DATA_FLOWS_TO)
    return cpg


@pytest.fixture()
def branching_cpg() -> CodePropertyGraph:
    """A function with a branch:

        param -> branch
        branch -> left -> sink
        branch -> right -> sink

    Edges are DATA_FLOWS_TO for the data path and BRANCHES_TO for control.
    """
    cpg = CodePropertyGraph()
    fn = make_node(NodeKind.FUNCTION, "fn", "fn", line=1)
    param = make_node(NodeKind.PARAMETER, "x", "param", scope="fn", line=2)
    branch = make_node(NodeKind.BRANCH, "if", "branch", scope="fn", line=3)
    left = make_node(NodeKind.VARIABLE, "left", "left", scope="fn", line=4)
    right = make_node(NodeKind.VARIABLE, "right", "right", scope="fn", line=5)
    sink = make_node(NodeKind.CALL, "sink", "sink", scope="fn", line=6)

    for node in [fn, param, branch, left, right, sink]:
        cpg.add_node(node)

    add_edge(cpg, "param", "branch", EdgeKind.DATA_FLOWS_TO)
    add_edge(cpg, "branch", "left", EdgeKind.DATA_FLOWS_TO)
    add_edge(cpg, "branch", "right", EdgeKind.DATA_FLOWS_TO)
    add_edge(cpg, "left", "sink", EdgeKind.DATA_FLOWS_TO)
    add_edge(cpg, "right", "sink", EdgeKind.DATA_FLOWS_TO)
    # Control flow edges
    add_edge(cpg, "branch", "left", EdgeKind.BRANCHES_TO)
    add_edge(cpg, "branch", "right", EdgeKind.BRANCHES_TO)
    return cpg
