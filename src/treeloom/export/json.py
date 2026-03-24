"""JSON export for the Code Property Graph."""

from __future__ import annotations

import json

from treeloom.graph.cpg import CodePropertyGraph


def to_json(cpg: CodePropertyGraph, indent: int = 2) -> str:
    """Serialize a CPG to a JSON string.

    Delegates to :meth:`CodePropertyGraph.to_dict` for the heavy lifting.
    ``Path`` objects become POSIX strings; ``NodeId`` objects become their
    string representation.
    """
    return json.dumps(cpg.to_dict(), indent=indent, default=str)


def from_json(data: str) -> CodePropertyGraph:
    """Deserialize a CPG from a JSON string.

    Delegates to :meth:`CodePropertyGraph.from_dict` to reconstruct all
    typed objects (``NodeId``, ``NodeKind``, ``Path``, etc.).
    """
    return CodePropertyGraph.from_dict(json.loads(data))
