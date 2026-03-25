"""Unit tests for the ScopeStack variable lookup."""

from __future__ import annotations

from treeloom.lang._scope import ScopeStack
from treeloom.model.nodes import NodeId


def _id(s: str) -> NodeId:
    return NodeId(_value=s)


class TestScopeStack:
    def test_define_and_lookup(self):
        stack = ScopeStack()
        stack.define("x", _id("x1"))
        assert stack.lookup("x") == _id("x1")

    def test_lookup_returns_none_for_missing(self):
        stack = ScopeStack()
        assert stack.lookup("x") is None

    def test_inner_scope_shadows_outer(self):
        stack = ScopeStack()
        stack.define("x", _id("outer"))
        stack.push()
        stack.define("x", _id("inner"))
        assert stack.lookup("x") == _id("inner")

    def test_pop_restores_outer_scope(self):
        stack = ScopeStack()
        stack.define("x", _id("outer"))
        stack.push()
        stack.define("x", _id("inner"))
        stack.pop()
        assert stack.lookup("x") == _id("outer")

    def test_inner_can_see_outer_variable(self):
        stack = ScopeStack()
        stack.define("x", _id("outer"))
        stack.push()
        # Inner scope doesn't define x, but can still see outer's
        assert stack.lookup("x") == _id("outer")

    def test_outer_cannot_see_inner_variable(self):
        stack = ScopeStack()
        stack.push()
        stack.define("y", _id("inner_only"))
        stack.pop()
        assert stack.lookup("y") is None

    def test_contains(self):
        stack = ScopeStack()
        stack.define("x", _id("x1"))
        assert "x" in stack
        assert "y" not in stack

    def test_getitem(self):
        stack = ScopeStack()
        stack.define("x", _id("x1"))
        assert stack["x"] == _id("x1")

    def test_getitem_raises_for_missing(self):
        import pytest

        stack = ScopeStack()
        with pytest.raises(KeyError):
            _ = stack["missing"]

    def test_setitem(self):
        stack = ScopeStack()
        stack["x"] = _id("x1")
        assert stack.lookup("x") == _id("x1")

    def test_get_with_default(self):
        stack = ScopeStack()
        default = _id("default")
        assert stack.get("missing", default) == default
        assert stack.get("missing") is None

    def test_pop_at_bottom_is_noop(self):
        stack = ScopeStack()
        stack.define("x", _id("x1"))
        stack.pop()  # Should not crash
        assert stack.lookup("x") == _id("x1")

    def test_multiple_nested_scopes(self):
        stack = ScopeStack()
        stack.define("x", _id("global"))
        stack.push()
        stack.define("x", _id("func"))
        stack.push()
        stack.define("x", _id("inner"))
        assert stack.lookup("x") == _id("inner")
        stack.pop()
        assert stack.lookup("x") == _id("func")
        stack.pop()
        assert stack.lookup("x") == _id("global")
