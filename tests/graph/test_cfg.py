"""Tests for CFG edge generation (FLOWS_TO, BRANCHES_TO) in CPGBuilder."""

from __future__ import annotations

from treeloom.graph.builder import CPGBuilder
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind


def _build_from_source(code: str) -> CPGBuilder:
    """Build a CPG from a Python source string and return the builder's CPG."""
    builder = CPGBuilder()
    builder.add_source(code.encode(), "test.py", language="python")
    return builder


def _edges_of(cpg, kind: EdgeKind):
    return list(cpg.edges(kind=kind))


class TestSequentialFlowsTo:
    """Sequential statements in a function get FLOWS_TO edges."""

    def test_three_assignments(self):
        cpg = _build_from_source(
            "def f():\n"
            "    x = 1\n"
            "    y = 2\n"
            "    z = 3\n"
        ).build()

        flows = _edges_of(cpg, EdgeKind.FLOWS_TO)
        # At minimum, the three VARIABLE children of f should be connected
        func_children = [
            n for n in cpg.nodes(kind=NodeKind.VARIABLE)
            if n.name in ("x", "y", "z")
        ]
        assert len(func_children) == 3

        # There should be at least 2 FLOWS_TO edges connecting the 3 children
        func_node = next(cpg.nodes(kind=NodeKind.FUNCTION))
        direct_children = cpg.children_of(func_node.id)
        child_ids = {str(c.id) for c in direct_children}

        intra_flows = [
            e for e in flows
            if str(e.source) in child_ids and str(e.target) in child_ids
        ]
        assert len(intra_flows) >= 2

    def test_call_then_assignment(self):
        cpg = _build_from_source(
            "def f():\n"
            "    print('hello')\n"
            "    x = 1\n"
        ).build()

        flows = _edges_of(cpg, EdgeKind.FLOWS_TO)
        assert len(flows) >= 1


class TestReturnTerminatesFlow:
    """RETURN nodes have no outgoing FLOWS_TO."""

    def test_return_mid_function(self):
        cpg = _build_from_source(
            "def f():\n"
            "    x = 1\n"
            "    return x\n"
            "    y = 2\n"
        ).build()

        flows = _edges_of(cpg, EdgeKind.FLOWS_TO)

        # The RETURN node should have no outgoing FLOWS_TO edge
        ret_nodes = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(ret_nodes) >= 1
        ret_ids = {str(r.id) for r in ret_nodes}

        outgoing_from_return = [e for e in flows if str(e.source) in ret_ids]
        assert len(outgoing_from_return) == 0

    def test_return_at_end(self):
        cpg = _build_from_source(
            "def f():\n"
            "    x = 1\n"
            "    return x\n"
        ).build()

        flows = _edges_of(cpg, EdgeKind.FLOWS_TO)

        ret_ids = {str(r.id) for r in cpg.nodes(kind=NodeKind.RETURN)}
        outgoing = [e for e in flows if str(e.source) in ret_ids]
        assert len(outgoing) == 0


class TestBranchBranchesTo:
    """BRANCH nodes get BRANCHES_TO edges to their body."""

    def test_if_statement(self):
        cpg = _build_from_source(
            "def f():\n"
            "    if True:\n"
            "        x = 1\n"
        ).build()

        branches = _edges_of(cpg, EdgeKind.BRANCHES_TO)

        # The BRANCH node should have a BRANCHES_TO edge to its first child
        branch_nodes = list(cpg.nodes(kind=NodeKind.BRANCH))
        assert len(branch_nodes) >= 1

        branch_ids = {str(b.id) for b in branch_nodes}
        branch_edges = [e for e in branches if str(e.source) in branch_ids]
        assert len(branch_edges) >= 1

    def test_if_with_assignment_after(self):
        """BRANCH node should also have FLOWS_TO to the next sibling statement."""
        cpg = _build_from_source(
            "def f():\n"
            "    if True:\n"
            "        x = 1\n"
            "    y = 2\n"
        ).build()

        flows = _edges_of(cpg, EdgeKind.FLOWS_TO)
        branches = _edges_of(cpg, EdgeKind.BRANCHES_TO)

        branch_nodes = list(cpg.nodes(kind=NodeKind.BRANCH))
        assert len(branch_nodes) >= 1

        # BRANCHES_TO into body
        branch_ids = {str(b.id) for b in branch_nodes}
        assert any(str(e.source) in branch_ids for e in branches)

        # FLOWS_TO from branch to the next sibling (y = 2)
        assert any(str(e.source) in branch_ids for e in flows)


class TestLoopBranchesTo:
    """LOOP nodes get BRANCHES_TO to body and back-edge from last statement."""

    def test_for_loop(self):
        cpg = _build_from_source(
            "def f():\n"
            "    for i in range(10):\n"
            "        x = i\n"
        ).build()

        branches = _edges_of(cpg, EdgeKind.BRANCHES_TO)
        flows = _edges_of(cpg, EdgeKind.FLOWS_TO)

        loop_nodes = list(cpg.nodes(kind=NodeKind.LOOP))
        assert len(loop_nodes) >= 1

        loop_ids = {str(node.id) for node in loop_nodes}

        # BRANCHES_TO from loop to body
        loop_branches = [e for e in branches if str(e.source) in loop_ids]
        assert len(loop_branches) >= 1

        # Back-edge FLOWS_TO from body back to loop
        back_edges = [e for e in flows if str(e.target) in loop_ids]
        assert len(back_edges) >= 1

    def test_while_loop(self):
        cpg = _build_from_source(
            "def f():\n"
            "    while True:\n"
            "        x = 1\n"
        ).build()

        branches = _edges_of(cpg, EdgeKind.BRANCHES_TO)
        flows = _edges_of(cpg, EdgeKind.FLOWS_TO)

        loop_nodes = list(cpg.nodes(kind=NodeKind.LOOP))
        assert len(loop_nodes) >= 1

        loop_ids = {str(node.id) for node in loop_nodes}

        assert any(str(e.source) in loop_ids for e in branches)
        assert any(str(e.target) in loop_ids for e in flows)

    def test_loop_no_back_edge_after_return(self):
        """If the last statement in a loop body is RETURN, no back-edge."""
        cpg = _build_from_source(
            "def f():\n"
            "    for i in range(10):\n"
            "        return i\n"
        ).build()

        flows = _edges_of(cpg, EdgeKind.FLOWS_TO)

        loop_nodes = list(cpg.nodes(kind=NodeKind.LOOP))
        loop_ids = {str(node.id) for node in loop_nodes}

        # No back-edge to loop
        back_edges = [e for e in flows if str(e.target) in loop_ids]
        assert len(back_edges) == 0


class TestEmptyFunction:
    """Functions with no children produce no CFG edges."""

    def test_empty_function(self):
        cpg = _build_from_source("def f():\n    pass\n").build()

        flows = _edges_of(cpg, EdgeKind.FLOWS_TO)
        branches = _edges_of(cpg, EdgeKind.BRANCHES_TO)

        # A pass-only function may have zero or very few children,
        # but should not crash and should not produce spurious edges
        func_node = next(cpg.nodes(kind=NodeKind.FUNCTION))
        direct_children = cpg.children_of(func_node.id)
        child_ids = {str(c.id) for c in direct_children}

        intra_flows = [
            e for e in flows
            if str(e.source) in child_ids and str(e.target) in child_ids
        ]
        intra_branches = [
            e for e in branches
            if str(e.source) in child_ids
        ]

        # With zero or one child, there should be no sequential flow edges
        if len(direct_children) <= 1:
            assert len(intra_flows) == 0
            assert len(intra_branches) == 0
