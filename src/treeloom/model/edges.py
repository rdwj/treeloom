"""Edge types and relationships for the Code Property Graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from treeloom.model.nodes import NodeId


class EdgeKind(str, Enum):
    """The kind of edge in the Code Property Graph."""

    # AST structure
    CONTAINS = "contains"
    HAS_PARAMETER = "has_parameter"
    HAS_RETURN_TYPE = "has_return_type"

    # Control flow
    FLOWS_TO = "flows_to"
    BRANCHES_TO = "branches_to"

    # Data flow
    DATA_FLOWS_TO = "data_flows_to"
    DEFINED_BY = "defined_by"
    USED_BY = "used_by"

    # Call graph
    CALLS = "calls"
    RESOLVES_TO = "resolves_to"

    # Module structure
    IMPORTS = "imports"


@dataclass(frozen=True, slots=True)
class CpgEdge:
    """A directed edge in the Code Property Graph."""

    source: NodeId
    target: NodeId
    kind: EdgeKind
    attrs: dict[str, Any] = field(default_factory=dict)
