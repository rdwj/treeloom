"""Tests for EdgeKind and CpgEdge."""

from __future__ import annotations

from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.nodes import NodeId


class TestEdgeKind:
    def test_all_kinds_present(self):
        expected = {
            "contains", "has_parameter", "has_return_type",
            "flows_to", "branches_to",
            "data_flows_to", "defined_by", "used_by",
            "calls", "resolves_to",
            "imports",
        }
        actual = {k.value for k in EdgeKind}
        assert actual == expected

    def test_string_value(self):
        assert EdgeKind.CONTAINS == "contains"
        assert EdgeKind.DATA_FLOWS_TO.value == "data_flows_to"

    def test_from_value(self):
        assert EdgeKind("calls") is EdgeKind.CALLS


class TestCpgEdge:
    def test_creation(self):
        edge = CpgEdge(
            source=NodeId("a"),
            target=NodeId("b"),
            kind=EdgeKind.CONTAINS,
        )
        assert edge.source == NodeId("a")
        assert edge.target == NodeId("b")
        assert edge.kind == EdgeKind.CONTAINS
        assert edge.attrs == {}

    def test_with_attrs(self):
        edge = CpgEdge(
            source=NodeId("a"),
            target=NodeId("b"),
            kind=EdgeKind.DATA_FLOWS_TO,
            attrs={"confidence": 0.95},
        )
        assert edge.attrs["confidence"] == 0.95

    def test_frozen(self):
        edge = CpgEdge(source=NodeId("a"), target=NodeId("b"), kind=EdgeKind.CALLS)
        try:
            edge.kind = EdgeKind.CONTAINS  # type: ignore[misc]
            raise AssertionError("Should have raised")  # noqa: TRY301
        except AttributeError:
            pass

    def test_equality(self):
        e1 = CpgEdge(source=NodeId("a"), target=NodeId("b"), kind=EdgeKind.CALLS)
        e2 = CpgEdge(source=NodeId("a"), target=NodeId("b"), kind=EdgeKind.CALLS)
        assert e1 == e2

    def test_default_attrs_independent(self):
        """Each edge gets its own attrs dict."""
        e1 = CpgEdge(source=NodeId("a"), target=NodeId("b"), kind=EdgeKind.CALLS)
        e2 = CpgEdge(source=NodeId("a"), target=NodeId("b"), kind=EdgeKind.CALLS)
        # Frozen dataclass, but the dict itself is mutable
        e1.attrs["x"] = 1
        assert "x" not in e2.attrs
