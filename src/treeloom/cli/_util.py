"""Shared CLI helpers: CPG loading, table formatting, output writing."""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

from treeloom.export.json import from_json
from treeloom.graph.cpg import CodePropertyGraph


def load_cpg(path: Path) -> CodePropertyGraph:
    """Read a JSON file and deserialize it into a CodePropertyGraph.

    Raises FileNotFoundError or json.JSONDecodeError with clear messages.
    """
    text = path.read_text(encoding="utf-8")
    return from_json(text)


def format_table(rows: list[list[str]], headers: list[str] | None = None) -> str:
    """Render *rows* as a simple column-aligned text table.

    If *headers* is provided it is prepended as the first row followed by
    a separator line.  All columns are left-aligned and padded with two
    extra spaces between them.
    """
    if not rows and not headers:
        return ""

    all_rows: list[list[str]] = []
    if headers is not None:
        all_rows.append(headers)
    all_rows.extend(rows)

    # Compute max width per column
    col_count = max(len(r) for r in all_rows)
    widths = [0] * col_count
    for row in all_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    lines: list[str] = []
    for idx, row in enumerate(all_rows):
        parts = [cell.ljust(widths[i]) for i, cell in enumerate(row)]
        lines.append("  ".join(parts).rstrip())
        if headers is not None and idx == 0:
            lines.append("  ".join("-" * w for w in widths))

    return "\n".join(lines)


def write_output(content: str, path: Path | None) -> None:
    """Write *content* to *path* (creating parent dirs) or to stdout."""
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    else:
        sys.stdout.write(content)
        if content and not content.endswith("\n"):
            sys.stdout.write("\n")


def node_to_dict(node: object) -> dict:
    """Serialize a CpgNode to a plain dict for JSON output."""
    from treeloom.model.nodes import CpgNode

    assert isinstance(node, CpgNode)
    loc = node.location
    end = node.end_location
    return {
        "id": str(node.id),
        "kind": node.kind.value,
        "name": node.name,
        "file": str(loc.file) if loc else None,
        "line": loc.line if loc else None,
        "column": loc.column if loc else None,
        "end_line": end.line if end else None,
        "end_column": end.column if end else None,
        "scope": str(node.scope) if node.scope else None,
        "attrs": node.attrs,
    }


def err(msg: str) -> None:
    """Print a message to stderr."""
    print(msg, file=sys.stderr)


def json_dumps(obj: object) -> str:
    """Compact JSON serialization."""
    return json.dumps(obj, indent=2, default=str)


def format_error(code: str, message: str, **extra: Any) -> str:
    """Format an error as JSON for --json-errors output."""
    return json.dumps({"error": code, "message": message, **extra})


# Supported output formats for --output-format
OUTPUT_FORMATS = ("table", "json", "csv", "tsv", "jsonl")


def format_output(
    rows: list[dict[str, Any]],
    headers: list[str],
    fmt: str,
) -> str:
    """Format *rows* (list of dicts) according to *fmt*.

    Supported formats: ``table``, ``json``, ``csv``, ``tsv``, ``jsonl``.

    *headers* determines the column order for tabular formats and the keys
    included in JSON/JSONL output (in the given order).  Dict keys not in
    *headers* are silently ignored.

    Returns the formatted string (no trailing newline for table/json;
    each line already ends with ``\\n`` for csv/tsv/jsonl).
    """
    if fmt == "table":
        table_rows = [[str(r.get(h, "")) for h in headers] for r in rows]
        return format_table(table_rows, headers=headers)

    if fmt == "json":
        ordered = [{h: r.get(h) for h in headers} for r in rows]
        return json.dumps(ordered, indent=2, default=str)

    if fmt in ("csv", "tsv"):
        delimiter = "," if fmt == "csv" else "\t"
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
        writer.writerow(headers)
        for r in rows:
            writer.writerow([str(r.get(h, "")) for h in headers])
        return buf.getvalue()

    if fmt == "jsonl":
        lines = [
            json.dumps({h: r.get(h) for h in headers}, default=str)
            for r in rows
        ]
        return "\n".join(lines) + ("\n" if lines else "")

    raise ValueError(f"Unknown output format: {fmt!r}")
