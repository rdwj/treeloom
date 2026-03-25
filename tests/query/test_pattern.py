"""Tests for treeloom.query.pattern (ChainPattern and StepMatcher)."""

from __future__ import annotations

from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeId, NodeKind
from treeloom.query.pattern import ChainPattern, StepMatcher, match_chain

from .conftest import add_edge, make_node


class TestStepMatcherMatches:
    def test_kind_match(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.FUNCTION, "fn", "fn")
        cpg.add_node(node)
        matcher = StepMatcher(kind=NodeKind.FUNCTION)
        assert matcher.matches(node, cpg)

    def test_kind_mismatch(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.VARIABLE, "x", "x")
        cpg.add_node(node)
        matcher = StepMatcher(kind=NodeKind.FUNCTION)
        assert not matcher.matches(node, cpg)

    def test_name_pattern_match(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.CALL, "os.system", "c")
        cpg.add_node(node)
        matcher = StepMatcher(name_pattern=r"os\.system")
        assert matcher.matches(node, cpg)

    def test_name_pattern_mismatch(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.CALL, "print", "c")
        cpg.add_node(node)
        matcher = StepMatcher(name_pattern=r"exec|eval|os\.system")
        assert not matcher.matches(node, cpg)

    def test_annotation_key_match(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.VARIABLE, "x", "x")
        cpg.add_node(node)
        cpg.annotate_node(NodeId("x"), "role", "source")
        matcher = StepMatcher(annotation_key="role")
        assert matcher.matches(node, cpg)

    def test_annotation_key_and_value_match(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.VARIABLE, "x", "x")
        cpg.add_node(node)
        cpg.annotate_node(NodeId("x"), "role", "source")
        matcher = StepMatcher(annotation_key="role", annotation_value="source")
        assert matcher.matches(node, cpg)

    def test_annotation_value_mismatch(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.VARIABLE, "x", "x")
        cpg.add_node(node)
        cpg.annotate_node(NodeId("x"), "role", "sink")
        matcher = StepMatcher(annotation_key="role", annotation_value="source")
        assert not matcher.matches(node, cpg)

    def test_annotation_key_missing(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.VARIABLE, "x", "x")
        cpg.add_node(node)
        matcher = StepMatcher(annotation_key="role")
        assert not matcher.matches(node, cpg)

    def test_wildcard_matches_anything(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.LITERAL, "42", "lit")
        cpg.add_node(node)
        matcher = StepMatcher(wildcard=True)
        assert matcher.matches(node, cpg)

    def test_combined_kind_and_name(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.CALL, "eval", "c")
        cpg.add_node(node)
        matcher = StepMatcher(kind=NodeKind.CALL, name_pattern=r"eval")
        assert matcher.matches(node, cpg)

    def test_combined_kind_mismatch_name_match(self) -> None:
        cpg = CodePropertyGraph()
        node = make_node(NodeKind.FUNCTION, "eval", "f")
        cpg.add_node(node)
        # Kind doesn't match even though name does
        matcher = StepMatcher(kind=NodeKind.CALL, name_pattern=r"eval")
        assert not matcher.matches(node, cpg)


class TestChainPatternExactSteps:
    def test_two_step_direct_hop(self) -> None:
        """A -> B with exact steps (no wildcard)."""
        cpg = CodePropertyGraph()
        a = make_node(NodeKind.PARAMETER, "a", "a", line=1)
        b = make_node(NodeKind.CALL, "exec", "b", line=2)
        cpg.add_node(a)
        cpg.add_node(b)
        add_edge(cpg, "a", "b", EdgeKind.DATA_FLOWS_TO)

        pattern = ChainPattern(
            steps=[
                StepMatcher(kind=NodeKind.PARAMETER),
                StepMatcher(kind=NodeKind.CALL, name_pattern=r"exec"),
            ],
            edge_kind=EdgeKind.DATA_FLOWS_TO,
        )
        matches = match_chain(cpg, pattern)
        assert len(matches) == 1
        assert str(matches[0][0].id) == "a"
        assert str(matches[0][1].id) == "b"

    def test_three_step_chain(self) -> None:
        """A -> B -> C with exact steps."""
        cpg = CodePropertyGraph()
        a = make_node(NodeKind.PARAMETER, "x", "a")
        b = make_node(NodeKind.VARIABLE, "y", "b")
        c = make_node(NodeKind.CALL, "eval", "c")
        cpg.add_node(a)
        cpg.add_node(b)
        cpg.add_node(c)
        add_edge(cpg, "a", "b", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "b", "c", EdgeKind.DATA_FLOWS_TO)

        pattern = ChainPattern(
            steps=[
                StepMatcher(kind=NodeKind.PARAMETER),
                StepMatcher(kind=NodeKind.VARIABLE),
                StepMatcher(kind=NodeKind.CALL),
            ],
            edge_kind=EdgeKind.DATA_FLOWS_TO,
        )
        matches = match_chain(cpg, pattern)
        assert len(matches) == 1
        assert [str(n.id) for n in matches[0]] == ["a", "b", "c"]

    def test_no_match_wrong_kind(self) -> None:
        cpg = CodePropertyGraph()
        a = make_node(NodeKind.PARAMETER, "a", "a")
        b = make_node(NodeKind.VARIABLE, "b", "b")
        cpg.add_node(a)
        cpg.add_node(b)
        add_edge(cpg, "a", "b", EdgeKind.DATA_FLOWS_TO)

        pattern = ChainPattern(
            steps=[
                StepMatcher(kind=NodeKind.PARAMETER),
                StepMatcher(kind=NodeKind.CALL),  # b is VARIABLE, not CALL
            ],
            edge_kind=EdgeKind.DATA_FLOWS_TO,
        )
        assert match_chain(cpg, pattern) == []


class TestChainPatternWildcard:
    def test_wildcard_skips_intermediates(self) -> None:
        """param -> ... -> exec (wildcard in the middle)."""
        cpg = CodePropertyGraph()
        param = make_node(NodeKind.PARAMETER, "x", "param")
        v1 = make_node(NodeKind.VARIABLE, "a", "v1")
        v2 = make_node(NodeKind.VARIABLE, "b", "v2")
        call = make_node(NodeKind.CALL, "exec", "call")
        cpg.add_node(param)
        cpg.add_node(v1)
        cpg.add_node(v2)
        cpg.add_node(call)
        add_edge(cpg, "param", "v1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "v1", "v2", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "v2", "call", EdgeKind.DATA_FLOWS_TO)

        pattern = ChainPattern(
            steps=[
                StepMatcher(kind=NodeKind.PARAMETER),
                StepMatcher(wildcard=True),
                StepMatcher(kind=NodeKind.CALL, name_pattern=r"exec|eval|os\.system"),
            ],
            edge_kind=EdgeKind.DATA_FLOWS_TO,
        )
        matches = match_chain(cpg, pattern)
        assert len(matches) == 1
        # Chain contains only the concrete steps: param and call
        assert str(matches[0][0].id) == "param"
        assert str(matches[0][1].id) == "call"

    def test_wildcard_zero_intermediates(self) -> None:
        """Wildcard matches zero intermediate nodes (direct hop)."""
        cpg = CodePropertyGraph()
        param = make_node(NodeKind.PARAMETER, "x", "param")
        call = make_node(NodeKind.CALL, "eval", "call")
        cpg.add_node(param)
        cpg.add_node(call)
        add_edge(cpg, "param", "call", EdgeKind.DATA_FLOWS_TO)

        pattern = ChainPattern(
            steps=[
                StepMatcher(kind=NodeKind.PARAMETER),
                StepMatcher(wildcard=True),
                StepMatcher(kind=NodeKind.CALL),
            ],
            edge_kind=EdgeKind.DATA_FLOWS_TO,
        )
        matches = match_chain(cpg, pattern)
        assert len(matches) == 1

    def test_no_path_through_wildcard(self) -> None:
        """No connection between the concrete steps at all."""
        cpg = CodePropertyGraph()
        param = make_node(NodeKind.PARAMETER, "x", "param")
        call = make_node(NodeKind.CALL, "eval", "call")
        cpg.add_node(param)
        cpg.add_node(call)
        # No edges

        pattern = ChainPattern(
            steps=[
                StepMatcher(kind=NodeKind.PARAMETER),
                StepMatcher(wildcard=True),
                StepMatcher(kind=NodeKind.CALL),
            ],
            edge_kind=EdgeKind.DATA_FLOWS_TO,
        )
        assert match_chain(cpg, pattern) == []

    def test_multiple_matches(self) -> None:
        """Two parameters, both flowing to the same exec call."""
        cpg = CodePropertyGraph()
        p1 = make_node(NodeKind.PARAMETER, "a", "p1")
        p2 = make_node(NodeKind.PARAMETER, "b", "p2")
        call = make_node(NodeKind.CALL, "exec", "call")
        cpg.add_node(p1)
        cpg.add_node(p2)
        cpg.add_node(call)
        add_edge(cpg, "p1", "call", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "p2", "call", EdgeKind.DATA_FLOWS_TO)

        pattern = ChainPattern(
            steps=[
                StepMatcher(kind=NodeKind.PARAMETER),
                StepMatcher(wildcard=True),
                StepMatcher(kind=NodeKind.CALL, name_pattern=r"exec"),
            ],
            edge_kind=EdgeKind.DATA_FLOWS_TO,
        )
        matches = match_chain(cpg, pattern)
        assert len(matches) == 2
        source_ids = {str(m[0].id) for m in matches}
        assert source_ids == {"p1", "p2"}


class TestChainPatternEdgeKindRestriction:
    def test_edge_kind_filters(self) -> None:
        """Edges of wrong kind are not followed."""
        cpg = CodePropertyGraph()
        a = make_node(NodeKind.PARAMETER, "a", "a")
        b = make_node(NodeKind.CALL, "exec", "b")
        cpg.add_node(a)
        cpg.add_node(b)
        # Only a CONTAINS edge, no DATA_FLOWS_TO
        add_edge(cpg, "a", "b", EdgeKind.CONTAINS)

        pattern = ChainPattern(
            steps=[
                StepMatcher(kind=NodeKind.PARAMETER),
                StepMatcher(kind=NodeKind.CALL),
            ],
            edge_kind=EdgeKind.DATA_FLOWS_TO,
        )
        assert match_chain(cpg, pattern) == []

    def test_no_edge_kind_follows_all(self) -> None:
        """Without edge_kind restriction, any edge type is followed."""
        cpg = CodePropertyGraph()
        a = make_node(NodeKind.PARAMETER, "a", "a")
        b = make_node(NodeKind.CALL, "exec", "b")
        cpg.add_node(a)
        cpg.add_node(b)
        add_edge(cpg, "a", "b", EdgeKind.CONTAINS)

        pattern = ChainPattern(
            steps=[
                StepMatcher(kind=NodeKind.PARAMETER),
                StepMatcher(kind=NodeKind.CALL),
            ],
            # No edge_kind restriction
        )
        matches = match_chain(cpg, pattern)
        assert len(matches) == 1


class TestChainPatternAnnotation:
    def test_match_by_annotation(self) -> None:
        cpg = CodePropertyGraph()
        a = make_node(NodeKind.VARIABLE, "x", "a")
        b = make_node(NodeKind.VARIABLE, "y", "b")
        cpg.add_node(a)
        cpg.add_node(b)
        cpg.annotate_node(NodeId("a"), "role", "source")
        cpg.annotate_node(NodeId("b"), "role", "sink")
        add_edge(cpg, "a", "b", EdgeKind.DATA_FLOWS_TO)

        pattern = ChainPattern(
            steps=[
                StepMatcher(annotation_key="role", annotation_value="source"),
                StepMatcher(annotation_key="role", annotation_value="sink"),
            ],
            edge_kind=EdgeKind.DATA_FLOWS_TO,
        )
        matches = match_chain(cpg, pattern)
        assert len(matches) == 1
        assert str(matches[0][0].id) == "a"
        assert str(matches[0][1].id) == "b"


class TestEmptyPattern:
    def test_empty_steps(self) -> None:
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.FUNCTION, "f", "f"))
        pattern = ChainPattern(steps=[])
        assert match_chain(cpg, pattern) == []

    def test_all_wildcard_steps(self) -> None:
        """All-wildcard pattern has no concrete steps, returns empty."""
        cpg = CodePropertyGraph()
        cpg.add_node(make_node(NodeKind.FUNCTION, "f", "f"))
        pattern = ChainPattern(steps=[StepMatcher(wildcard=True)])
        assert match_chain(cpg, pattern) == []


class TestSpecExample:
    """The exact example from the CLAUDE.md spec."""

    def test_parameter_to_exec_via_data_flow(self) -> None:
        cpg = CodePropertyGraph()
        fn = make_node(NodeKind.FUNCTION, "handle", "fn", line=1)
        param = make_node(NodeKind.PARAMETER, "user_input", "param", scope="fn", line=2)
        v1 = make_node(NodeKind.VARIABLE, "cmd", "v1", scope="fn", line=3)
        call = make_node(NodeKind.CALL, "os.system", "call", scope="fn", line=4)

        for node in [fn, param, v1, call]:
            cpg.add_node(node)

        add_edge(cpg, "param", "v1", EdgeKind.DATA_FLOWS_TO)
        add_edge(cpg, "v1", "call", EdgeKind.DATA_FLOWS_TO)

        pattern = ChainPattern(
            steps=[
                StepMatcher(kind=NodeKind.PARAMETER),
                StepMatcher(wildcard=True),
                StepMatcher(kind=NodeKind.CALL, name_pattern=r"exec|eval|os\.system"),
            ],
            edge_kind=EdgeKind.DATA_FLOWS_TO,
        )
        matches = cpg.query().match_chain(pattern)
        assert len(matches) == 1
        assert matches[0][0].name == "user_input"
        assert matches[0][1].name == "os.system"
