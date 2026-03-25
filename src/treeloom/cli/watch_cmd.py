"""``treeloom watch`` -- rebuild CPG on source file changes (polling)."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from treeloom.cli._util import err
from treeloom.cli.build import _should_exclude
from treeloom.cli.config import Config
from treeloom.export.json import to_json
from treeloom.graph.builder import _DEFAULT_EXCLUDES, CPGBuilder


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser(
        "watch",
        help="Watch a directory and rebuild CPG on file changes",
    )
    p.add_argument("path", type=Path, help="Source directory to watch")
    p.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output JSON file (default: cpg.json)",
    )
    p.add_argument(
        "--interval", type=float, default=2.0, metavar="SECONDS",
        help="Poll interval in seconds (default: 2)",
    )
    p.add_argument(
        "--exclude", action="append", default=None, metavar="PATTERN",
        help="Exclusion glob pattern (repeatable)",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="Only print on rebuild, not on each poll",
    )
    p.set_defaults(func=run_cmd)


def _scan_mtimes(path: Path, root: Path, all_excludes: list[str]) -> dict[Path, float]:
    """Return {filepath: mtime} for all non-excluded files under *path*."""
    mtimes: dict[Path, float] = {}
    for f in path.rglob("*"):
        if f.is_file() and not _should_exclude(f, root, all_excludes):
            mtimes[f] = f.stat().st_mtime
    return mtimes


def _detect_changes(old: dict[Path, float], new: dict[Path, float]) -> list[Path]:
    """Return files that are new, modified, or deleted between snapshots."""
    changed: list[Path] = []
    for f, mtime in new.items():
        if f not in old or old[f] != mtime:
            changed.append(f)
    for f in old:
        if f not in new:
            changed.append(f)
    return changed


def _build_cpg(path: Path, exclude: list[str]) -> object:
    """Build a CPG from *path* using the given exclusion patterns."""
    builder = CPGBuilder()
    builder.add_directory(path, exclude=exclude)
    return builder.build()


def run_cmd(args: argparse.Namespace, cfg: Config | None = None) -> int:
    path = Path(args.path).resolve()
    if not path.exists() or not path.is_dir():
        err(f"Path does not exist or is not a directory: {path}")
        return 1

    output = Path(args.output) if args.output else Path("cpg.json")
    interval: float = args.interval
    extra_excludes: list[str] = args.exclude or []
    if cfg is not None:
        extra_excludes = extra_excludes + (cfg.exclude_patterns or [])
    all_excludes = _DEFAULT_EXCLUDES + extra_excludes

    # Initial build
    cpg = _build_cpg(path, extra_excludes)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(to_json(cpg), encoding="utf-8")
    err(f"Initial build: {cpg.node_count} nodes, {cpg.edge_count} edges -> {output}")

    snapshot = _scan_mtimes(path, path, all_excludes)

    try:
        while True:
            time.sleep(interval)
            current = _scan_mtimes(path, path, all_excludes)
            changed = _detect_changes(snapshot, current)
            if changed:
                cpg = _build_cpg(path, extra_excludes)
                output.write_text(to_json(cpg), encoding="utf-8")
                ts = time.strftime("%H:%M:%S")
                err(
                    f"[{ts}] Rebuilt: {cpg.node_count} nodes, {cpg.edge_count} edges "
                    f"({len(changed)} files changed)"
                )
                snapshot = current
    except KeyboardInterrupt:
        err("\nWatch stopped.")
        return 0
