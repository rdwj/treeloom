"""``treeloom info`` -- display summary statistics for a CPG."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from treeloom.cli._util import format_table, load_cpg
from treeloom.cli.config import Config


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("info", help="Display CPG summary statistics")
    p.add_argument("cpg_file", type=Path, help="CPG JSON file")
    p.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")
    p.set_defaults(func=run_info)


def run_info(args: argparse.Namespace, cfg: Config) -> int:
    cpg = load_cpg(args.cpg_file)

    # Count nodes by kind
    node_counts: Counter[str] = Counter()
    for node in cpg.nodes():
        node_counts[node.kind.value] += 1

    # Count edges by kind
    edge_counts: Counter[str] = Counter()
    for edge in cpg.edges():
        edge_counts[edge.kind.value] += 1

    # Group files by extension
    ext_counts: Counter[str] = Counter()
    for f in cpg.files:
        ext_counts[f.suffix or "(no ext)"] += 1

    if args.as_json:
        data = {
            "node_count": cpg.node_count,
            "edge_count": cpg.edge_count,
            "file_count": len(cpg.files),
            "nodes_by_kind": dict(node_counts.most_common()),
            "edges_by_kind": dict(edge_counts.most_common()),
            "files_by_extension": dict(ext_counts.most_common()),
        }
        print(json.dumps(data, indent=2))
        return 0

    # Human-readable output
    print(f"Nodes: {cpg.node_count}  Edges: {cpg.edge_count}  Files: {len(cpg.files)}")
    print()

    if node_counts:
        print("Nodes by kind:")
        rows = [[kind, str(count)] for kind, count in node_counts.most_common()]
        print(format_table(rows, headers=["Kind", "Count"]))
        print()

    if edge_counts:
        print("Edges by kind:")
        rows = [[kind, str(count)] for kind, count in edge_counts.most_common()]
        print(format_table(rows, headers=["Kind", "Count"]))
        print()

    if ext_counts:
        print("Files by extension:")
        rows = [[ext, str(count)] for ext, count in ext_counts.most_common()]
        print(format_table(rows, headers=["Extension", "Count"]))

    return 0
