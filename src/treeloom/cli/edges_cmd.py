"""``treeloom edges`` -- query and filter CPG edges."""

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
)
from treeloom.cli.config import Config
from treeloom.model.edges import EdgeKind

_DEFAULT_LIMIT = 50


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("edges", help="Query and filter CPG edges")
    p.add_argument("cpg_file", type=Path, help="CPG JSON file")
    p.add_argument(
        "--kind", "-k", action="append", default=None, metavar="KIND",
        help="Filter by edge kind (repeatable, e.g. data_flows_to, calls)",
    )
    p.add_argument(
        "--source", "-s", metavar="PATTERN",
        help="Filter edges where source node name matches (regex)",
    )
    p.add_argument(
        "--target", "-t", metavar="PATTERN",
        help="Filter edges where target node name matches (regex)",
    )
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
        "--limit", "-l", type=int, default=_DEFAULT_LIMIT,
        help=f"Max results (default {_DEFAULT_LIMIT})",
    )
    p.add_argument(
        "--count", "-c", action="store_true",
        help="Print only the matching edge count and exit",
    )
    p.set_defaults(func=run_cmd)


def _loc_str(node: object) -> str:
    """Return 'filename:line' for a node, or '?:?' if location is unavailable."""
    loc = getattr(node, "location", None)
    if loc is None:
        return "?:?"
    return f"{loc.file.name}:{loc.line}"


def _parse_kinds(raw: list[str] | None) -> list[EdgeKind] | None:
    if raw is None:
        return None
    valid = {k.value: k for k in EdgeKind}
    kinds: list[EdgeKind] = []
    for name in raw:
        lower = name.lower()
        if lower not in valid:
            err(f"Unknown edge kind: {name!r}. Valid kinds: {', '.join(valid)}")
            raise SystemExit(1)
        kinds.append(valid[lower])
    return kinds


def run_cmd(args: argparse.Namespace, _cfg: Config | None = None) -> int:
    try:
        cpg = load_cpg(args.cpg_file)
    except FileNotFoundError:
        err(f"File not found: {args.cpg_file}")
        return 1

    kinds = _parse_kinds(args.kind)

    source_re: re.Pattern | None = None  # type: ignore[type-arg]
    if args.source:
        try:
            source_re = re.compile(args.source)
        except re.error as exc:
            err(f"Invalid --source regex: {exc}")
            return 1

    target_re: re.Pattern | None = None  # type: ignore[type-arg]
    if args.target:
        try:
            target_re = re.compile(args.target)
        except re.error as exc:
            err(f"Invalid --target regex: {exc}")
            return 1

    limit: int = args.limit
    count_only: bool = getattr(args, "count", False)

    results = []
    for edge in cpg.edges():
        if kinds is not None and edge.kind not in kinds:
            continue
        src_node = cpg.node(edge.source)
        tgt_node = cpg.node(edge.target)
        if src_node is None or tgt_node is None:
            continue
        if source_re is not None and not source_re.search(src_node.name):
            continue
        if target_re is not None and not target_re.search(tgt_node.name):
            continue
        results.append((edge, src_node, tgt_node))
        # Don't apply the limit when counting — we need the full result set.
        if not count_only and len(results) >= limit:
            break

    if count_only:
        print(len(results))
        return 0

    # --json is a legacy alias for --output-format json
    fmt: str = "json" if args.as_json else getattr(args, "output_format", "table")

    if fmt == "json":
        data = [
            {
                "kind": edge.kind.value,
                "source": {
                    "id": str(edge.source),
                    "name": src.name,
                    "kind": src.kind.value,
                    "file": str(src.location.file.name) if src.location else None,
                    "line": src.location.line if src.location else None,
                },
                "target": {
                    "id": str(edge.target),
                    "name": tgt.name,
                    "kind": tgt.kind.value,
                    "file": str(tgt.location.file.name) if tgt.location else None,
                    "line": tgt.location.line if tgt.location else None,
                },
                "attrs": edge.attrs,
            }
            for edge, src, tgt in results
        ]
        print(json_dumps(data))
        return 0

    if not results:
        print("No matching edges.")
        return 0

    if fmt == "table":
        rows = [
            [
                edge.kind.value,
                f"{src.name} ({src.kind.value} @ {_loc_str(src)})",
                f"{tgt.name} ({tgt.kind.value} @ {_loc_str(tgt)})",
            ]
            for edge, src, tgt in results
        ]
        print(format_table(rows, headers=["Kind", "Source", "Target"]))
    else:
        headers = ["kind", "source", "target"]
        rows_dicts = [
            {
                "kind": edge.kind.value,
                "source": f"{src.name} ({src.kind.value} @ {_loc_str(src)})",
                "target": f"{tgt.name} ({tgt.kind.value} @ {_loc_str(tgt)})",
            }
            for edge, src, tgt in results
        ]
        output = format_output(rows_dicts, headers, fmt)
        sys.stdout.write(output)
        if output and not output.endswith("\n"):
            sys.stdout.write("\n")

    if len(results) >= limit:
        err(f"(showing first {limit} results; use --limit to change)")
    return 0
