"""Node types and data structures for the Code Property Graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from treeloom.model.location import SourceLocation


@dataclass(frozen=True, slots=True)
class NodeId:
    """Opaque, hashable node identifier. Never construct directly -- use CPGBuilder."""

    _value: str

    def __str__(self) -> str:
        return self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NodeId):
            return NotImplemented
        return self._value == other._value


class NodeKind(str, Enum):
    """The kind of node in the Code Property Graph."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    PARAMETER = "parameter"
    VARIABLE = "variable"
    CALL = "call"
    LITERAL = "literal"
    RETURN = "return"
    IMPORT = "import"
    BRANCH = "branch"
    LOOP = "loop"
    BLOCK = "block"


@dataclass
class CpgNode:
    """A node in the Code Property Graph."""

    id: NodeId
    kind: NodeKind
    name: str
    location: SourceLocation | None
    end_location: SourceLocation | None = None
    scope: NodeId | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
    _tree_node: Any = field(default=None, repr=False, compare=False)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CpgNode):
            return NotImplemented
        return self.id == other.id
