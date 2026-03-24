"""treeloom CLI entry point with subcommand dispatch."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from treeloom.cli import build, config, dot_cmd, info, query, taint_cmd, viz_cmd
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

    subparsers = parser.add_subparsers(dest="command")
    build.register(subparsers)
    info.register(subparsers)
    query.register(subparsers)
    config.register(subparsers)
    taint_cmd.register(subparsers)
    viz_cmd.register(subparsers)
    dot_cmd.register(subparsers)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")

    cfg = load_config()

    try:
        return args.func(args, cfg)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON — {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


def cli() -> None:
    """Console-script wrapper that calls sys.exit."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
