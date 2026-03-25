"""CLI subcommand: dot -- export a CPG to Graphviz DOT format."""

from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

from treeloom.export.dot import to_dot
from treeloom.export.json import from_json
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind


def register(subparsers: Any) -> None:
    """Register the ``dot`` subcommand."""
    parser: ArgumentParser = subparsers.add_parser(
        "dot",
        help="Export a CPG to Graphviz DOT format",
    )
    parser.add_argument("cpg_file", type=Path, help="Path to CPG JSON file")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output DOT file (default: stdout)",
    )
    parser.add_argument(
        "--edge-kind", action="append", default=None, dest="edge_kinds",
        help="Filter to specific edge kinds (repeatable, case-insensitive)",
    )
    parser.add_argument(
        "--node-kind", action="append", default=None, dest="node_kinds",
        help="Filter to specific node kinds (repeatable, case-insensitive)",
    )
    parser.set_defaults(func=run_cmd)


def run_cmd(args: Namespace, _cfg: object = None) -> int:
    """Execute the dot subcommand."""
    cpg_path: Path = args.cpg_file

    if not cpg_path.is_file():
        raise FileNotFoundError(cpg_path)

    cpg = from_json(cpg_path.read_text())

    edge_kinds = _parse_kinds(args.edge_kinds, EdgeKind, "edge kind")
    if edge_kinds is None and args.edge_kinds is not None:
        return 1  # _parse_kinds already printed the error

    node_kinds = _parse_kinds(args.node_kinds, NodeKind, "node kind")
    if node_kinds is None and args.node_kinds is not None:
        return 1

    dot_text = to_dot(cpg, edge_kinds=edge_kinds, node_kinds=node_kinds)

    if args.output:
        args.output.write_text(dot_text)
        print(f"Wrote DOT output to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(dot_text)

    return 0


def _parse_kinds(
    values: list[str] | None,
    enum_type: type,
    label: str,
) -> frozenset | None:
    """Parse a list of kind strings into a frozenset of enum values.

    Returns None if *values* is None (no filtering requested) OR if
    any value is invalid (after printing an error).
    """
    if values is None:
        return None

    result = set()
    for v in values:
        try:
            result.add(enum_type(v.lower()))
        except ValueError:
            valid = ", ".join(sorted(m.value for m in enum_type))
            print(
                f"Error: unknown {label} '{v}'. Valid values: {valid}",
                file=sys.stderr,
            )
            return None
    return frozenset(result)
