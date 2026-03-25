"""treeloom CLI entry point with subcommand dispatch."""

from __future__ import annotations

import argparse
import json
import logging
import sys

import yaml

from treeloom.cli import (
    annotate_cmd,
    build,
    completions_cmd,
    config,
    diff_cmd,
    dot_cmd,
    edges_cmd,
    info,
    pattern_cmd,
    query,
    serve_cmd,
    subgraph_cmd,
    taint_cmd,
    viz_cmd,
    watch_cmd,
)
from treeloom.cli._util import format_error
from treeloom.cli.config import load_config
from treeloom.version import __version__


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = argparse.ArgumentParser(
        prog="treeloom",
        description="Code Property Graph toolkit",
    )
    parser.add_argument(
        "--version", action="version", version=f"treeloom {__version__}",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging",
    )
    parser.add_argument(
        "--json-errors",
        action="store_true",
        help="Output errors as JSON objects to stderr instead of plain text",
    )

    subparsers = parser.add_subparsers(dest="command")
    annotate_cmd.register(subparsers)
    build.register(subparsers)
    diff_cmd.register(subparsers)
    edges_cmd.register(subparsers)
    info.register(subparsers)
    pattern_cmd.register(subparsers)
    query.register(subparsers)
    config.register(subparsers)
    serve_cmd.register(subparsers)
    subgraph_cmd.register(subparsers)
    taint_cmd.register(subparsers)
    viz_cmd.register(subparsers)
    dot_cmd.register(subparsers)
    watch_cmd.register(subparsers)
    completions_cmd.register(subparsers)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")

    cfg = load_config()

    use_json = getattr(args, "json_errors", False)

    try:
        return args.func(args, cfg)
    except FileNotFoundError as exc:
        path = str(exc.filename) if exc.filename else ""
        if use_json:
            print(format_error("file_not_found", str(exc), path=path), file=sys.stderr)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        if use_json:
            snippet = exc.doc[:50] if exc.doc else ""
            print(format_error("invalid_json", str(exc), file=snippet), file=sys.stderr)
        else:
            print(f"Error: invalid JSON — {exc}", file=sys.stderr)
        return 1
    except yaml.YAMLError as exc:
        if use_json:
            print(format_error("invalid_yaml", str(exc)), file=sys.stderr)
        else:
            print(f"Error: invalid YAML — {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if use_json:
            print(format_error("interrupted", "Interrupted by user"), file=sys.stderr)
        else:
            print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        if use_json:
            msg = format_error("unexpected_error", str(exc), type=type(exc).__name__)
            print(msg, file=sys.stderr)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1


def cli() -> None:
    """Console-script wrapper that calls sys.exit."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
