"""Analysis engines: taint propagation, reachability, summaries."""

from treeloom.analysis.reachability import backward_reachable, forward_reachable
from treeloom.analysis.summary import FunctionSummary, compute_summaries
from treeloom.analysis.taint import (
    TaintLabel,
    TaintPath,
    TaintPolicy,
    TaintPropagator,
    TaintResult,
    run_taint,
)

__all__ = [
    "FunctionSummary",
    "TaintLabel",
    "TaintPath",
    "TaintPolicy",
    "TaintPropagator",
    "TaintResult",
    "backward_reachable",
    "compute_summaries",
    "forward_reachable",
    "run_taint",
]
