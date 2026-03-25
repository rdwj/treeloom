"""``treeloom diff`` -- compare two CPGs and report structural changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NamedTuple

from treeloom.cli._util import err, load_cpg
from treeloom.cli.config import Config
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.nodes import NodeKind


class _NodeKey(NamedTuple):
    kind: str
    name: str
    file: str
    line: int


def _node_keys(cpg: CodePropertyGraph, kind: NodeKind) -> set[_NodeKey]:
    keys: set[_NodeKey] = set()
    for node in cpg.nodes(kind=kind):
        loc = node.location
        keys.add(_NodeKey(
            kind=node.kind.value,
            name=node.name,
            file=str(loc.file) if loc else "",
            line=loc.line if loc else 0,
        ))
    return keys


def _fmt_delta(before: int, after: int) -> str:
    delta = after - before
    sign = "+" if delta >= 0 else ""
    return f"{before} -> {after} ({sign}{delta})"


def _node_label(key: _NodeKey) -> str:
    file_part = f"{key.file}:{key.line}" if key.file else "(unknown)"
    return f"  {key.name:<30} {file_part}"


def run_cmd(args: argparse.Namespace, _cfg: Config | None = None) -> int:
    before_path: Path = args.before
    after_path: Path = args.after

    try:
        before = load_cpg(before_path)
    except FileNotFoundError:
        err(f"File not found: {before_path}")
        return 1

    try:
        after = load_cpg(after_path)
    except FileNotFoundError:
        err(f"File not found: {after_path}")
        return 1

    # Build file sets
    before_files = {str(f) for f in before.files}
    after_files = {str(f) for f in after.files}
    new_files = sorted(after_files - before_files)
    removed_files = sorted(before_files - after_files)

    # Build per-kind difference sets
    kinds_of_interest = [
        (NodeKind.FUNCTION, "functions"),
        (NodeKind.CLASS, "classes"),
        (NodeKind.CALL, "calls"),
    ]
    diff_by_kind: dict[str, tuple[list[_NodeKey], list[_NodeKey]]] = {}
    for kind, label in kinds_of_interest:
        bk = _node_keys(before, kind)
        ak = _node_keys(after, kind)
        added = sorted(ak - bk, key=lambda k: (k.file, k.line, k.name))
        removed = sorted(bk - ak, key=lambda k: (k.file, k.line, k.name))
        diff_by_kind[label] = (added, removed)

    # Per-file node counts
    before_file_counts: dict[str, int] = {}
    after_file_counts: dict[str, int] = {}
    for node in before.nodes():
        if node.location:
            key = str(node.location.file)
            before_file_counts[key] = before_file_counts.get(key, 0) + 1
    for node in after.nodes():
        if node.location:
            key = str(node.location.file)
            after_file_counts[key] = after_file_counts.get(key, 0) + 1

    # Files that changed (present in both, different count)
    changed_files: list[tuple[str, int, int]] = []
    for f in sorted(before_files & after_files):
        bc = before_file_counts.get(f, 0)
        ac = after_file_counts.get(f, 0)
        if bc != ac:
            changed_files.append((f, bc, ac))

    if args.as_json:
        data = {
            "before": str(before_path),
            "after": str(after_path),
            "summary": {
                "nodes": {"before": before.node_count, "after": after.node_count},
                "edges": {"before": before.edge_count, "after": after.edge_count},
                "files": {"before": len(before_files), "after": len(after_files)},
            },
            "new_files": new_files,
            "removed_files": removed_files,
            "changed_files": [
                {"file": f, "before": bc, "after": ac}
                for f, bc, ac in changed_files
            ],
        }
        for label, (added, removed) in diff_by_kind.items():
            data[f"new_{label}"] = [
                {"name": k.name, "file": k.file, "line": k.line} for k in added
            ]
            data[f"removed_{label}"] = [
                {"name": k.name, "file": k.file, "line": k.line} for k in removed
            ]
        print(json.dumps(data, indent=2))
        return 0

    # Human-readable output
    print(f"CPG Diff: {before_path} -> {after_path}")
    print()
    print("Summary:")
    print(f"  Nodes: {_fmt_delta(before.node_count, after.node_count)}")
    print(f"  Edges: {_fmt_delta(before.edge_count, after.edge_count)}")
    print(f"  Files: {_fmt_delta(len(before_files), len(after_files))}")

    def _section(title: str, items: list[_NodeKey]) -> None:
        if not items:
            return
        print()
        print(f"{title}:")
        for key in items:
            print(_node_label(key))

    def _file_section(title: str, files: list[str]) -> None:
        if not files:
            return
        print()
        print(f"{title}:")
        for f in files:
            print(f"  {f}")

    _file_section("New files", new_files)
    _file_section("Removed files", removed_files)

    for label, (added, removed) in diff_by_kind.items():
        _section(f"New {label}", added)
        _section(f"Removed {label}", removed)

    if changed_files:
        print()
        print("Changed files (node count):")
        for f, bc, ac in changed_files:
            delta = ac - bc
            sign = "+" if delta >= 0 else ""
            print(f"  {f}: {bc} -> {ac} ({sign}{delta})")

    return 0


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("diff", help="Compare two CPGs and report structural changes")
    p.add_argument("before", type=Path, help="Before CPG JSON file")
    p.add_argument("after", type=Path, help="After CPG JSON file")
    p.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")
    p.set_defaults(func=run_cmd)
