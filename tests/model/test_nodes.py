"""Tests for NodeId, NodeKind, and CpgNode."""

from __future__ import annotations

from pathlib import Path

from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind


class TestNodeId:
    def test_str(self):
        nid = NodeId("function:foo.py:1:0:1")
        assert str(nid) == "function:foo.py:1:0:1"

    def test_hash_consistent(self):
        a = NodeId("x")
        b = NodeId("x")
        assert hash(a) == hash(b)

    def test_equality(self):
        assert NodeId("a") == NodeId("a")
        assert NodeId("a") != NodeId("b")

    def test_usable_as_dict_key(self):
        d = {NodeId("a"): 1, NodeId("b"): 2}
        assert d[NodeId("a")] == 1

    def test_usable_in_set(self):
        s = {NodeId("a"), NodeId("a"), NodeId("b")}
        assert len(s) == 2

    def test_inequality_with_other_types(self):
        assert NodeId("a") != "a"
        assert NodeId("a") != 42


class TestNodeKind:
    def test_all_kinds_present(self):
        expected = {
            "module", "class", "function", "parameter", "variable",
            "call", "literal", "return", "import", "branch", "loop", "block",
        }
        actual = {k.value for k in NodeKind}
        assert actual == expected

    def test_string_value(self):
        assert NodeKind.FUNCTION == "function"
        assert NodeKind.MODULE.value == "module"

    def test_from_value(self):
        assert NodeKind("function") is NodeKind.FUNCTION


class TestCpgNode:
    def test_creation(self):
        loc = SourceLocation(file=Path("foo.py"), line=10, column=0)
        node = CpgNode(
            id=NodeId("function:foo.py:10:0:1"),
            kind=NodeKind.FUNCTION,
            name="my_func",
            location=loc,
        )
        assert node.name == "my_func"
        assert node.kind == NodeKind.FUNCTION
        assert node.location == loc
        assert node.scope is None
        assert node.attrs == {}

    def test_attrs(self):
        node = CpgNode(
            id=NodeId("1"),
            kind=NodeKind.FUNCTION,
            name="f",
            location=None,
            attrs={"is_async": True, "decorators": ["staticmethod"]},
        )
        assert node.attrs["is_async"] is True
        assert node.attrs["decorators"] == ["staticmethod"]

    def test_scope(self):
        parent = NodeId("mod")
        node = CpgNode(
            id=NodeId("fn"),
            kind=NodeKind.FUNCTION,
            name="f",
            location=None,
            scope=parent,
        )
        assert node.scope == parent

    def test_tree_node_not_in_repr(self):
        node = CpgNode(
            id=NodeId("1"),
            kind=NodeKind.VARIABLE,
            name="x",
            location=None,
            _tree_node="sentinel",
        )
        assert "sentinel" not in repr(node)

    def test_tree_node_not_in_comparison(self):
        a = CpgNode(
            id=NodeId("1"),
            kind=NodeKind.VARIABLE,
            name="x",
            location=None,
            _tree_node="a",
        )
        b = CpgNode(
            id=NodeId("1"),
            kind=NodeKind.VARIABLE,
            name="x",
            location=None,
            _tree_node="b",
        )
        assert a == b

    def test_default_attrs_independent(self):
        """Each node gets its own attrs dict."""
        a = CpgNode(id=NodeId("1"), kind=NodeKind.VARIABLE, name="x", location=None)
        b = CpgNode(id=NodeId("2"), kind=NodeKind.VARIABLE, name="y", location=None)
        a.attrs["foo"] = "bar"
        assert "foo" not in b.attrs
