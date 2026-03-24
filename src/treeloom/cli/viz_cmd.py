"""CLI subcommand: viz -- generate an interactive HTML visualization."""

from __future__ import annotations

import sys
import webbrowser
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

from treeloom.export.html import generate_html
from treeloom.export.json import from_json


def register(subparsers: Any) -> None:
    """Register the ``viz`` subcommand."""
    parser: ArgumentParser = subparsers.add_parser(
        "viz",
        help="Generate interactive HTML visualization of a CPG",
    )
    parser.add_argument("cpg_file", type=Path, help="Path to CPG JSON file")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output HTML file (default: <cpg_file>.html)",
    )
    parser.add_argument(
        "--title", type=str, default="Code Property Graph",
        help="Title for the visualization",
    )
    parser.add_argument(
        "--open", dest="open_browser", action="store_true", default=False,
        help="Open the HTML file in the default browser",
    )
    parser.set_defaults(func=run_cmd)


def run_cmd(args: Namespace, _cfg: object = None) -> int:
    """Execute the viz subcommand."""
    cpg_path: Path = args.cpg_file

    if not cpg_path.is_file():
        print(f"Error: CPG file not found: {cpg_path}", file=sys.stderr)
        return 1

    try:
        cpg = from_json(cpg_path.read_text())
    except Exception as exc:
        print(f"Error loading CPG: {exc}", file=sys.stderr)
        return 1

    output_path: Path = args.output or cpg_path.with_suffix(".html")
    html = generate_html(cpg, title=args.title)
    output_path.write_text(html)

    print(f"Wrote visualization to {output_path}")

    if args.open_browser:
        webbrowser.open(output_path.as_uri())

    return 0
