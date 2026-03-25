"""``treeloom build`` -- parse source files and emit a CPG JSON file."""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

from treeloom.cli._util import err, write_output
from treeloom.cli.config import Config
from treeloom.export.json import to_json
from treeloom.graph.builder import _DEFAULT_EXCLUDES, CPGBuilder


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("build", help="Build a CPG from source files")
    p.add_argument("path", type=Path, help="File or directory to analyze")
    p.add_argument("-o", "--output", type=Path, default=None, help="Output JSON file")
    p.add_argument(
        "--exclude", action="append", default=None, metavar="PATTERN",
        help="Exclusion glob pattern (repeatable)",
    )
    p.add_argument("--quiet", "-q", action="store_true", help="Suppress summary output")
    p.add_argument(
        "--progress", action="store_true",
        help="Print each file as it is parsed (output to stderr)",
    )
    p.set_defaults(func=run_build)


def run_build(args: argparse.Namespace, cfg: Config) -> int:
    path: Path = args.path.resolve()
    if not path.exists():
        err(f"Path does not exist: {path}")
        return 1

    output: Path = args.output or Path(cfg.default_build_output)
    exclude = (args.exclude or []) + cfg.exclude_patterns
    show_progress: bool = getattr(args, "progress", False)

    builder = CPGBuilder()

    if path.is_file():
        if show_progress:
            print(f"[1/1] Parsing {path}...", file=sys.stderr)
        builder.add_file(path)
    elif show_progress:
        all_patterns = _DEFAULT_EXCLUDES + exclude
        files = sorted(
            f for f in path.rglob("*")
            if f.is_file() and not _should_exclude(f, path, all_patterns)
        )
        total = len(files)
        for i, f in enumerate(files, 1):
            print(f"[{i}/{total}] Parsing {f}...", file=sys.stderr)
            builder.add_file(f)
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


def _should_exclude(file: Path, root: Path, patterns: list[str]) -> bool:
    """Return True if *file* matches any exclusion pattern relative to *root*."""
    try:
        rel = str(file.relative_to(root))
    except ValueError:
        rel = str(file)
    for pattern in patterns:
        if fnmatch.fnmatch(rel, pattern):
            return True
        for part in file.parts:
            if fnmatch.fnmatch(part, pattern.replace("**/", "")):
                return True
    return False
