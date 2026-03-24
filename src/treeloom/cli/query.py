"""``treeloom query`` -- search and filter CPG nodes."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from treeloom.cli._util import err, format_table, json_dumps, load_cpg, node_to_dict
from treeloom.cli.config import Config
from treeloom.model.nodes import CpgNode, NodeKind


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("query", help="Search and filter CPG nodes")
    p.add_argument("cpg_file", type=Path, help="CPG JSON file")
    p.add_argument(
        "--kind", "-k", action="append", default=None, metavar="KIND",
        help="Filter by node kind (repeatable, e.g. function, call)",
    )
    p.add_argument("--name", "-n", metavar="PATTERN", help="Filter by name (regex)")
    p.add_argument("--file", "-f", metavar="PATH", help="Filter by file path (substring)")
    p.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")
    p.add_argument("--limit", "-l", type=int, default=None, help="Max results")
    p.set_defaults(func=run_query)


def _parse_kinds(raw: list[str] | None) -> list[NodeKind] | None:
    if raw is None:
        return None
    kinds: list[NodeKind] = []
    valid = {k.value: k for k in NodeKind}
    for name in raw:
        lower = name.lower()
        if lower not in valid:
            err(f"Unknown node kind: {name!r}. Valid kinds: {', '.join(valid)}")
            raise SystemExit(1)
        kinds.append(valid[lower])
    return kinds


def _matches(node: CpgNode, kinds: list[NodeKind] | None, name_re: re.Pattern | None,  # type: ignore[type-arg]
             file_sub: str | None) -> bool:
    if kinds is not None and node.kind not in kinds:
        return False
    if name_re is not None and not name_re.search(node.name):
        return False
    if file_sub is not None:
        if node.location is None:
            return False
        if file_sub not in str(node.location.file):
            return False
    return True


def run_query(args: argparse.Namespace, cfg: Config) -> int:
    try:
        cpg = load_cpg(args.cpg_file)
    except FileNotFoundError:
        err(f"File not found: {args.cpg_file}")
        return 1

    kinds = _parse_kinds(args.kind)

    name_re = None
    if args.name is not None:
        try:
            name_re = re.compile(args.name)
        except re.error as exc:
            err(f"Invalid regex: {exc}")
            return 1

    file_sub = args.file
    limit = args.limit if args.limit is not None else cfg.query_limit

    results: list[CpgNode] = []
    for node in cpg.nodes():
        if _matches(node, kinds, name_re, file_sub):
            results.append(node)
            if len(results) >= limit:
                break

    if args.as_json:
        print(json_dumps([node_to_dict(n) for n in results]))
        return 0

    if not results:
        print("No matching nodes.")
        return 0

    rows: list[list[str]] = []
    for node in results:
        loc = node.location
        loc_str = f"{loc.file}:{loc.line}" if loc else "-"
        rows.append([node.kind.value, node.name, loc_str])

    print(format_table(rows, headers=["Kind", "Name", "Location"]))
    if len(results) >= limit:
        err(f"(showing first {limit} results; use --limit to change)")
    return 0
