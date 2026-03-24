"""``treeloom build`` -- parse source files and emit a CPG JSON file."""

from __future__ import annotations

import argparse
from pathlib import Path

from treeloom.cli._util import err, write_output
from treeloom.cli.config import Config
from treeloom.export.json import to_json
from treeloom.graph.builder import CPGBuilder


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("build", help="Build a CPG from source files")
    p.add_argument("path", type=Path, help="File or directory to analyze")
    p.add_argument("-o", "--output", type=Path, default=None, help="Output JSON file")
    p.add_argument(
        "--exclude", action="append", default=None, metavar="PATTERN",
        help="Exclusion glob pattern (repeatable)",
    )
    p.add_argument("--quiet", "-q", action="store_true", help="Suppress summary output")
    p.set_defaults(func=run_build)


def run_build(args: argparse.Namespace, cfg: Config) -> int:
    path: Path = args.path.resolve()
    if not path.exists():
        err(f"Path does not exist: {path}")
        return 1

    output: Path = args.output or Path(cfg.default_build_output)
    exclude = (args.exclude or []) + cfg.exclude_patterns

    builder = CPGBuilder()
    if path.is_file():
        builder.add_file(path)
    else:
        builder.add_directory(path, exclude=exclude)

    cpg = builder.build()
    json_text = to_json(cpg)
    write_output(json_text, output)

    if not args.quiet:
        err(
            f"Built CPG: {cpg.node_count} nodes, {cpg.edge_count} edges, "
            f"{len(cpg.files)} files -> {output}"
        )

    return 0
