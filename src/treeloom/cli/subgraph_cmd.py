"""CLI subcommand: subgraph -- extract a CPG subgraph rooted at a node."""

from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

from treeloom.cli._util import load_cpg
from treeloom.export.json import to_json
from treeloom.model.nodes import NodeId, NodeKind


def register(subparsers: Any) -> None:
    """Register the ``subgraph`` subcommand."""
    parser: ArgumentParser = subparsers.add_parser(
        "subgraph",
        help="Extract a subgraph rooted at a specific node",
    )
    parser.add_argument("cpg_file", type=Path, help="Path to CPG JSON file")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("subgraph.json"),
        help="Output JSON file (default: subgraph.json)",
    )
    parser.add_argument(
        "--depth", type=int, default=10,
        help="Maximum BFS depth from root (default: 10)",
    )

    root_group = parser.add_mutually_exclusive_group(required=True)
    root_group.add_argument("--root", help="Exact NodeId string")
    root_group.add_argument("--function", metavar="NAME", help="FUNCTION node name")
    root_group.add_argument("--class", dest="class_name", metavar="NAME", help="CLASS node name")
    root_group.add_argument(
        "--file", metavar="PATH", help="MODULE node for this file (substring match)",
    )

    parser.set_defaults(func=run_cmd)


def run_cmd(args: Namespace, _cfg: object = None) -> int:
    """Execute the subgraph subcommand."""
    cpg_path: Path = args.cpg_file

    if not cpg_path.is_file():
        raise FileNotFoundError(cpg_path)

    cpg = load_cpg(cpg_path)

    # Resolve the root node based on which flag was supplied.
    root_id, root_label = _find_root(cpg, args)
    if root_id is None:
        return 1

    sub = cpg.query().subgraph(root_id, max_depth=args.depth)

    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(to_json(sub), encoding="utf-8")

    print(
        f"Extracted subgraph: {sub.node_count} nodes, {sub.edge_count} edges"
        f" (rooted at {root_label}) -> {output}"
    )
    return 0


def _find_root(cpg: Any, args: Namespace) -> tuple[NodeId | None, str]:
    """Return (NodeId, label) for the root node, or (None, "") on error."""
    if args.root is not None:
        node = cpg.node(NodeId(args.root))
        if node is None:
            print(f"Error: No node with id '{args.root}' found in CPG", file=sys.stderr)
            return None, ""
        return node.id, f"{node.kind.value}:{node.name}"

    if args.function is not None:
        return _find_by_kind(cpg, NodeKind.FUNCTION, args.function)

    if args.class_name is not None:
        return _find_by_kind(cpg, NodeKind.CLASS, args.class_name)

    if args.file is not None:
        return _find_module(cpg, args.file)

    # Unreachable: argparse enforces required mutually-exclusive group.
    print("Error: specify one of --root, --function, --class, or --file", file=sys.stderr)
    return None, ""


def _find_by_kind(cpg: Any, kind: NodeKind, name: str) -> tuple[NodeId | None, str]:
    """Find the first node of *kind* whose name equals *name*."""
    for node in cpg.nodes(kind=kind):
        if node.name == name:
            return node.id, f"{kind.value}:{name}"
    print(
        f"Error: No {kind.value.upper()} node named '{name}' found in CPG",
        file=sys.stderr,
    )
    return None, ""


def _find_module(cpg: Any, path_fragment: str) -> tuple[NodeId | None, str]:
    """Find the MODULE node whose file path contains *path_fragment*."""
    for node in cpg.nodes(kind=NodeKind.MODULE):
        if path_fragment in node.name or (
            node.location and path_fragment in str(node.location.file)
        ):
            return node.id, f"module:{node.name}"
    print(
        f"Error: No MODULE node matching '{path_fragment}' found in CPG",
        file=sys.stderr,
    )
    return None, ""
