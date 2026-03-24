"""treeloom -- weave syntax trees into code property graphs.

A language-agnostic Code Property Graph (CPG) library that provides
complete codebase coverage for static analysis, taint tracking, and
code understanding.
"""

from treeloom.analysis.reachability import backward_reachable, forward_reachable
from treeloom.analysis.summary import FunctionSummary, compute_summaries
from treeloom.analysis.taint import (
    TaintLabel,
    TaintPath,
    TaintPolicy,
    TaintPropagator,
    TaintResult,
)
from treeloom.graph.builder import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation, SourceRange
from treeloom.model.nodes import CpgNode, NodeId, NodeKind
from treeloom.query.api import GraphQuery
from treeloom.query.pattern import ChainPattern, StepMatcher
from treeloom.version import __version__

__all__ = [
    "__version__",
    "ChainPattern",
    "FunctionSummary",
    "GraphQuery",
    "StepMatcher",
    "backward_reachable",
    "compute_summaries",
    "forward_reachable",
    "CPGBuilder",
    "CodePropertyGraph",
    "CpgEdge",
    "CpgNode",
    "EdgeKind",
    "NodeId",
    "NodeKind",
    "SourceLocation",
    "SourceRange",
    "TaintLabel",
    "TaintPath",
    "TaintPolicy",
    "TaintPropagator",
    "TaintResult",
]
