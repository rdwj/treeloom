"""treeloom -- weave syntax trees into code property graphs.

A language-agnostic Code Property Graph (CPG) library that provides
complete codebase coverage for static analysis, taint tracking, and
code understanding.
"""

from treeloom.graph.builder import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation, SourceRange
from treeloom.model.nodes import CpgNode, NodeId, NodeKind
from treeloom.version import __version__

__all__ = [
    "__version__",
    "CPGBuilder",
    "CodePropertyGraph",
    "CpgEdge",
    "CpgNode",
    "EdgeKind",
    "NodeId",
    "NodeKind",
    "SourceLocation",
    "SourceRange",
]
