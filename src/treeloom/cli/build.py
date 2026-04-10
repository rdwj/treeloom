"""``treeloom build`` -- parse source files and emit a CPG JSON file."""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

from treeloom.cli._util import err, write_output
from treeloom.cli.config import Config
from treeloom.export.json import to_json
from treeloom.graph.builder import (
    _DEFAULT_EXCLUDES,
    BuildProgressCallback,
    BuildTimeoutError,
    CPGBuilder,
)
from treeloom.lang.registry import LanguageRegistry


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
    p.add_argument(
        "--language", action="append", default=None, metavar="LANG", dest="languages",
        help="Only process files for this language (repeatable, e.g. python, javascript)",
    )
    p.add_argument(
        "--timeout", type=float, default=None, metavar="SECONDS",
        help="Abort build if it exceeds this many seconds",
    )
    p.add_argument(
        "--include-source", action="store_true",
        help="Include source text in CPG nodes (increases output size)",
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
    languages: list[str] | None = getattr(args, "languages", None)
    timeout: float | None = getattr(args, "timeout", None)
    include_source: bool = getattr(args, "include_source", False)

    registry = LanguageRegistry.default()

    # Resolve the set of extensions to process when --language is specified.
    lang_extensions: frozenset[str] | None = None
    if languages:
        exts: set[str] = set()
        for lang in languages:
            visitor = registry.get_visitor_by_name(lang.lower())
            if visitor is None:
                supported = ", ".join(sorted(registry._by_name))
                err(f"Unknown language: {lang!r}. Supported: {supported}")
                return 1
            exts.update(visitor.extensions)
        lang_extensions = frozenset(exts)

    # Progress callback for --progress
    progress_cb: BuildProgressCallback | None = None
    if show_progress:
        def progress_cb(phase: str, detail: str) -> None:
            if not detail:
                # Start message — skip empty detail lines
                return
            print(f"{phase}... {detail}", file=sys.stderr)

    builder = CPGBuilder(
        registry=registry, progress=progress_cb, timeout=timeout,
        include_source=include_source,
    )

    if path.is_file():
        if show_progress:
            print(f"[1/1] Parsing {path}...", file=sys.stderr)
        builder.add_file(path)
    elif show_progress or lang_extensions is not None:
        # For --progress and/or --language we enumerate files explicitly so we
        # can apply supported-extension and language filters before parsing.
        supported_exts = registry.supported_extensions()
        all_patterns = _DEFAULT_EXCLUDES + exclude
        files = sorted(
            f for f in path.rglob("*")
            if f.is_file()
            and not _should_exclude(f, path, all_patterns)
            and f.suffix in supported_exts
            and (lang_extensions is None or f.suffix in lang_extensions)
        )
        total = len(files)
        for i, f in enumerate(files, 1):
            if show_progress:
                print(f"[{i}/{total}] Parsing {f}...", file=sys.stderr)
            builder.add_file(f)
    else:
        builder.add_directory(path, exclude=exclude)

    try:
        cpg = builder.build()
    except BuildTimeoutError as exc:
        err(str(exc))
        err("Hint: try building per-directory or increase --timeout.")
        return 1
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
