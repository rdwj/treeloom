"""Core data model: nodes, edges, locations."""

from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation, SourceRange
from treeloom.model.nodes import CpgNode, NodeId, NodeKind

__all__ = [
    "CpgEdge",
    "CpgNode",
    "EdgeKind",
    "NodeId",
    "NodeKind",
    "SourceLocation",
    "SourceRange",
]
