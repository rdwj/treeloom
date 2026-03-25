"""CLI subcommand: pattern -- match structural chains in a CPG using a YAML pattern."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

import yaml

from treeloom.cli._util import load_cpg, node_to_dict
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind
from treeloom.query.pattern import ChainPattern, StepMatcher


def register(subparsers: Any) -> None:
    """Register the ``pattern`` subcommand."""
    parser: ArgumentParser = subparsers.add_parser(
        "pattern",
        help="Match structural node chains in a serialized CPG using a YAML pattern",
    )
    parser.add_argument("cpg_file", type=Path, help="Path to CPG JSON file")
    parser.add_argument(
        "--pattern", "-p", type=Path, required=True, metavar="PATTERN_FILE",
        help="Path to YAML pattern file describing the chain to match",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", default=False,
        help="Output results as JSON",
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=0, metavar="N",
        help="Maximum number of chains to show (0 = unlimited)",
    )
    parser.set_defaults(func=run_cmd)


def run_cmd(args: Namespace, _cfg: object = None) -> int:
    """Execute the pattern subcommand."""
    cpg_path: Path = args.cpg_file
    pattern_path: Path = args.pattern

    if not cpg_path.is_file():
        raise FileNotFoundError(cpg_path)
    if not pattern_path.is_file():
        raise FileNotFoundError(pattern_path)

    cpg = load_cpg(cpg_path)

    raw = yaml.safe_load(pattern_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        print(
            f"Error: pattern file must be a YAML mapping, got {type(raw).__name__}",
            file=sys.stderr,
        )
        return 1

    try:
        pattern = _parse_pattern(raw)
    except ValueError as exc:
        print(f"Error: invalid pattern — {exc}", file=sys.stderr)
        return 1

    chains = cpg.query().match_chain(pattern)

    limit: int = args.limit
    if limit > 0:
        chains = chains[:limit]

    if args.json_output:
        text = _format_json(chains)
    else:
        text = _format_human(chains)

    print(text)
    return 0


# ---------------------------------------------------------------------------
# Pattern parsing
# ---------------------------------------------------------------------------


def _parse_pattern(data: dict[str, Any]) -> ChainPattern:
    """Build a ChainPattern from a YAML-derived dict.

    Expected shape::

        steps:
          - kind: PARAMETER
          - wildcard: true
          - kind: CALL
            name: "exec|eval"
        edge_kind: data_flows_to   # optional
    """
    raw_steps = data.get("steps")
    if not raw_steps or not isinstance(raw_steps, list):
        raise ValueError("pattern must have a non-empty 'steps' list")

    steps: list[StepMatcher] = []
    for i, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise ValueError(f"step {i} must be a YAML mapping, got {type(raw_step).__name__}")
        steps.append(_parse_step(i, raw_step))

    edge_kind: EdgeKind | None = None
    raw_edge_kind = data.get("edge_kind")
    if raw_edge_kind is not None:
        try:
            edge_kind = EdgeKind(str(raw_edge_kind).lower())
        except ValueError:
            valid = ", ".join(e.value for e in EdgeKind)
            raise ValueError(f"unknown edge_kind '{raw_edge_kind}'; valid values: {valid}")

    return ChainPattern(steps=steps, edge_kind=edge_kind)


def _parse_step(index: int, raw: dict[str, Any]) -> StepMatcher:
    """Parse a single step dict into a StepMatcher."""
    wildcard = bool(raw.get("wildcard", False))

    kind: NodeKind | None = None
    raw_kind = raw.get("kind")
    if raw_kind is not None:
        try:
            kind = NodeKind(str(raw_kind).lower())
        except ValueError:
            valid = ", ".join(e.value for e in NodeKind)
            raise ValueError(
                f"step {index}: unknown kind '{raw_kind}'; valid values: {valid}"
            )

    name_pattern: str | None = raw.get("name") or raw.get("name_pattern") or None
    annotation_key: str | None = raw.get("annotation_key") or None
    annotation_value: Any = raw.get("annotation_value")

    return StepMatcher(
        kind=kind,
        name_pattern=str(name_pattern) if name_pattern is not None else None,
        annotation_key=str(annotation_key) if annotation_key is not None else None,
        annotation_value=annotation_value,
        wildcard=wildcard,
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _loc_str(node: Any) -> str:
    """Format a node's source location for display."""
    if node.location is None:
        return "<unknown>"
    return f"{node.location.file}:{node.location.line}"


def _format_human(chains: list[list[Any]]) -> str:
    """Produce human-readable pattern match output."""
    if not chains:
        return "No matching chains found."

    count = len(chains)
    noun = "chain" if count == 1 else "chains"
    lines = [f"Found {count} matching {noun}:", ""]

    for idx, chain in enumerate(chains, start=1):
        lines.append(f"Chain {idx}:")
        for node in chain:
            kind_label = node.kind.value.upper()
            loc = _loc_str(node)
            lines.append(f"  {kind_label:<12s} {node.name:<24s} {loc}")
        lines.append("")

    # Remove trailing blank line
    if lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def _format_json(chains: list[list[Any]]) -> str:
    """Produce JSON pattern match output."""
    data = [[node_to_dict(n) for n in chain] for chain in chains]
    return json.dumps(data, indent=2, default=str)
