"""``treeloom query`` -- search and filter CPG nodes."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from treeloom.cli._util import (
    OUTPUT_FORMATS,
    err,
    format_output,
    format_table,
    json_dumps,
    load_cpg,
    node_to_dict,
)
from treeloom.cli.config import Config
from treeloom.graph.cpg import CodePropertyGraph
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
    p.add_argument(
        "--output-format", dest="output_format", default="table",
        choices=OUTPUT_FORMATS,
        help="Output format: table (default), json, csv, tsv, jsonl",
    )
    p.add_argument(
        "--json", dest="as_json", action="store_true",
        help="Output as JSON (alias for --output-format json)",
    )
    p.add_argument(
        "--limit", "-l", type=int, default=None,
        help="Max results (0 = no limit, default: no limit)",
    )
    p.add_argument(
        "--offset", type=int, default=0,
        help="Skip the first N matching results (default 0)",
    )
    p.add_argument(
        "--scope", metavar="NAME",
        help="Filter to nodes whose scope chain includes a node with this name",
    )
    p.add_argument("--count", action="store_true", help="Print count only, not the table")
    p.add_argument(
        "--annotation", metavar="KEY",
        help="Filter to nodes that have this annotation key",
    )
    p.add_argument(
        "--annotation-value", metavar="VALUE", dest="annotation_value",
        help="Combined with --annotation: only match when the annotation equals this value",
    )
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


def _scope_matches(cpg: CodePropertyGraph, node: CpgNode, scope_name: str) -> bool:
    """Return True if any ancestor in the scope chain has a name matching *scope_name*."""
    current = node
    while current.scope is not None:
        parent = cpg.scope_of(current.id)
        if parent is None:
            break
        if parent.name == scope_name:
            return True
        current = parent
    return False


def _matches(
    node: CpgNode,
    kinds: list[NodeKind] | None,
    name_re: re.Pattern | None,  # type: ignore[type-arg]
    file_sub: str | None,
    scope_name: str | None = None,
    annotation_key: str | None = None,
    annotation_value: str | None = None,
    cpg: CodePropertyGraph | None = None,
) -> bool:
    if kinds is not None and node.kind not in kinds:
        return False
    if name_re is not None and not name_re.search(node.name):
        return False
    if file_sub is not None:
        if node.location is None:
            return False
        if file_sub not in str(node.location.file):
            return False
    if scope_name is not None and cpg is not None:
        if not _scope_matches(cpg, node, scope_name):
            return False
    if annotation_key is not None and cpg is not None:
        val = cpg.get_annotation(node.id, annotation_key)
        if val is None:
            return False
        if annotation_value is not None and str(val) != annotation_value:
            return False
    return True


def run_query(args: argparse.Namespace, cfg: Config) -> int:
    cpg = load_cpg(args.cpg_file)

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
    offset: int = args.offset
    scope_name: str | None = getattr(args, "scope", None)
    count_only: bool = getattr(args, "count", False)
    annotation_key: str | None = getattr(args, "annotation", None)
    annotation_value: str | None = getattr(args, "annotation_value", None)

    results: list[CpgNode] = []
    skipped = 0
    for node in cpg.nodes():
        if _matches(
            node, kinds, name_re, file_sub,
            scope_name=scope_name,
            annotation_key=annotation_key,
            annotation_value=annotation_value,
            cpg=cpg,
        ):
            if not count_only and skipped < offset:
                skipped += 1
                continue
            results.append(node)
            if not count_only and limit > 0 and len(results) >= limit:
                break

    if count_only:
        print(len(results))
        return 0

    # --json is a legacy alias for --output-format json
    fmt: str = "json" if args.as_json else getattr(args, "output_format", "table")

    if fmt == "json":
        print(json_dumps([node_to_dict(n) for n in results]))
        return 0

    if not results:
        print("No matching nodes.")
        return 0

    headers = ["kind", "name", "location"]
    rows_dicts = []
    for node in results:
        loc = node.location
        loc_str = f"{loc.file}:{loc.line}" if loc else "-"
        rows_dicts.append({"kind": node.kind.value, "name": node.name, "location": loc_str})

    if fmt == "table":
        # Use capitalized headers for the human-readable table
        table_rows = [[r["kind"], r["name"], r["location"]] for r in rows_dicts]
        print(format_table(table_rows, headers=["Kind", "Name", "Location"]))
    else:
        output = format_output(rows_dicts, headers, fmt)
        sys.stdout.write(output)
        if output and not output.endswith("\n"):
            sys.stdout.write("\n")

    if limit > 0 and len(results) >= limit:
        err(f"(showing first {limit} results; use --limit to change)")
    return 0
