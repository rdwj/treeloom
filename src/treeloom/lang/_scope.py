"""Scope-aware variable lookup stack for language visitors.

Replaces flat ``dict[str, NodeId]`` to correctly handle nested scopes
(e.g., inner functions that shadow outer variables).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from treeloom.model.nodes import NodeId


class ScopeStack:
    """Scope-aware variable lookup with LEGB-style chaining.

    When entering a function or class scope, call :meth:`push`.
    When leaving, call :meth:`pop`.  Variable definitions write to the
    innermost scope; lookups walk from inner to outer.
    """

    __slots__ = ("_stack",)

    def __init__(self) -> None:
        self._stack: list[dict[str, NodeId]] = [{}]

    def push(self) -> None:
        """Enter a new scope."""
        self._stack.append({})

    def pop(self) -> None:
        """Leave the current scope."""
        if len(self._stack) > 1:
            self._stack.pop()

    def define(self, name: str, node_id: NodeId) -> None:
        """Define a variable in the current (innermost) scope."""
        self._stack[-1][name] = node_id

    def lookup(self, name: str) -> NodeId | None:
        """Look up a variable, searching from inner to outer scope."""
        for scope in reversed(self._stack):
            if name in scope:
                return scope[name]
        return None

    def get(self, name: str, default: NodeId | None = None) -> NodeId | None:
        """Dict-compatible get: look up a variable with an optional default."""
        result = self.lookup(name)
        return result if result is not None else default

    def __contains__(self, name: str) -> bool:
        return self.lookup(name) is not None

    def __getitem__(self, name: str) -> NodeId:
        result = self.lookup(name)
        if result is None:
            raise KeyError(name)
        return result

    def __setitem__(self, name: str, node_id: NodeId) -> None:
        """Alias for :meth:`define` so ``stack[name] = id`` still works."""
        self.define(name, node_id)
