"""CLI subcommand: taint -- run taint analysis with a YAML policy."""

from __future__ import annotations

import json
import re
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

import yaml

from treeloom.analysis.taint import (
    TaintLabel,
    TaintPolicy,
    TaintPropagator,
    TaintResult,
    run_taint,
)
from treeloom.export.json import from_json, to_json
from treeloom.model.nodes import CpgNode, NodeKind


def register(subparsers: Any) -> None:
    """Register the ``taint`` subcommand."""
    parser: ArgumentParser = subparsers.add_parser(
        "taint",
        help="Run taint analysis on a serialized CPG",
    )
    parser.add_argument("cpg_file", type=Path, help="Path to CPG JSON file")
    parser.add_argument(
        "--policy", "-p", type=Path, action="append", required=True,
        metavar="POLICY_FILE",
        help="Path to YAML policy file (repeatable; rules from all files are merged)",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None, help="Write results to file"
    )
    parser.add_argument(
        "--show-sanitized",
        action="store_true",
        default=False,
        help="Include sanitized paths in output",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", default=False,
        help="Output results as JSON",
    )
    parser.add_argument(
        "--apply", action="store_true", default=False,
        help="Write taint annotations back to the CPG and save to -o (default: tainted-cpg.json)",
    )
    parser.set_defaults(func=run_cmd)


def run_cmd(args: Namespace, _cfg: object = None) -> int:
    """Execute the taint subcommand."""
    cpg_path: Path = args.cpg_file
    policy_paths: list[Path] = args.policy  # list due to action="append"

    if not cpg_path.is_file():
        raise FileNotFoundError(cpg_path)
    for policy_path in policy_paths:
        if not policy_path.is_file():
            raise FileNotFoundError(policy_path)

    cpg = from_json(cpg_path.read_text())
    policy = load_policies(policy_paths, cpg)

    result = run_taint(cpg, policy)

    if getattr(args, "apply", False):
        result.apply_to(cpg)
        out_path = args.output or Path("tainted-cpg.json")
        out_path.write_text(to_json(cpg))
        annotated_nodes = sum(
            1 for nid in cpg._annotations if cpg._annotations[nid].get("tainted")
        )
        print(
            f"Taint analysis: {len(result.paths)} paths found, "
            f"{annotated_nodes} nodes annotated. "
            f"Written to {out_path}"
        )
        return 0

    if args.json_output:
        text = _format_json(result, args.show_sanitized)
    else:
        text = _format_human(result, args.show_sanitized)

    if args.output:
        args.output.write_text(text)
    else:
        print(text)

    return 0


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


def _merge_policy_data(files: list[Path]) -> dict[str, list[Any]]:
    """Load and merge rules from one or more YAML policy files.

    Each file must be a YAML mapping. The ``sources``, ``sinks``,
    ``sanitizers``, and ``propagators`` lists from every file are concatenated
    into a single merged dict.
    """
    merged: dict[str, list[Any]] = {
        "sources": [],
        "sinks": [],
        "sanitizers": [],
        "propagators": [],
    }
    for path in files:
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            msg = f"Policy file {path} must be a YAML mapping, got {type(data).__name__}"
            raise ValueError(msg)
        for key in merged:
            merged[key].extend(data.get(key, []))
    return merged


def load_policies(paths: list[Path], cpg: object = None) -> TaintPolicy:
    """Load and merge multiple YAML policy files into a single TaintPolicy.

    Rules from all files are concatenated; a node is a source/sink/sanitizer
    if it matches any rule from any file.
    """
    data = _merge_policy_data(paths)
    return _compile_policy(data)


def load_policy(path: Path, cpg: object = None) -> TaintPolicy:
    """Parse a YAML policy file and compile into a TaintPolicy.

    The *cpg* parameter is accepted for API symmetry but not currently used.
    For multiple files use :func:`load_policies`.
    """
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        msg = f"Policy file must be a YAML mapping, got {type(data).__name__}"
        raise ValueError(msg)
    return _compile_policy(data)


def _compile_policy(data: dict[str, Any]) -> TaintPolicy:
    """Compile a merged policy data dict into a TaintPolicy."""
    source_rules: list[dict[str, Any]] = data.get("sources", [])
    sink_rules: list[dict[str, Any]] = data.get("sinks", [])
    sanitizer_rules: list[dict[str, Any]] = data.get("sanitizers", [])
    propagator_rules: list[dict[str, Any]] = data.get("propagators", [])

    def sources_fn(node: CpgNode) -> TaintLabel | None:
        for rule in source_rules:
            if _matches(node, rule):
                label_name = rule.get("label", "tainted")
                return TaintLabel(label_name, node.id)
        return None

    def sinks_fn(node: CpgNode) -> bool:
        return any(_matches(node, r) for r in sink_rules)

    def sanitizers_fn(node: CpgNode) -> bool:
        return any(_matches(node, r) for r in sanitizer_rules)

    propagators = [_build_propagator(r) for r in propagator_rules]

    return TaintPolicy(
        sources=sources_fn,
        sinks=sinks_fn,
        sanitizers=sanitizers_fn,
        propagators=propagators,
    )


def _matches(node: CpgNode, rule: dict[str, Any]) -> bool:
    """Check whether *node* matches a single rule dict."""
    if "kind" in rule:
        try:
            expected = NodeKind(rule["kind"].lower())
        except ValueError:
            return False
        if node.kind != expected:
            return False
    if "name" in rule:
        if not re.search(rule["name"], node.name):
            return False
    if "attr" in rule:
        for k, v in rule["attr"].items():
            if node.attrs.get(k) != v:
                return False
    return True


def _build_propagator(rule: dict[str, Any]) -> TaintPropagator:
    """Build a TaintPropagator from a YAML rule dict."""
    match_rule = rule.get("match", {})

    def match_fn(node: CpgNode) -> bool:
        return _matches(node, match_rule)

    return TaintPropagator(
        match=match_fn,
        param_to_return=rule.get("param_to_return", True),
        param_to_param=rule.get("param_to_param"),
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _format_human(result: TaintResult, show_sanitized: bool) -> str:
    """Produce human-readable taint output."""
    unsanitized = result.unsanitized_paths()
    sanitized = result.sanitized_paths()
    total = len(result.paths)

    lines = [
        f"Taint analysis: {total} paths found "
        f"({len(unsanitized)} unsanitized, {len(sanitized)} sanitized)",
    ]

    for path in unsanitized:
        lines.append("")
        label_names = ", ".join(sorted(lb.name for lb in path.labels))
        lines.append(f"[UNSANITIZED] {label_names} -> {path.sink.name}")
        for node in path.intermediates:
            tag = _node_tag(node, path)
            loc = _loc_str(node)
            lines.append(f"  {loc}  {node.kind.value:<10s} {node.name:<20s} {tag}")

    if show_sanitized:
        for path in sanitized:
            lines.append("")
            label_names = ", ".join(sorted(lb.name for lb in path.labels))
            san_names = ", ".join(n.name for n in path.sanitizers)
            lines.append(
                f"[SANITIZED] {label_names} -> {path.sink.name} "
                f"(via {san_names})"
            )
            for node in path.intermediates:
                tag = _node_tag(node, path)
                loc = _loc_str(node)
                lines.append(
                    f"  {loc}  {node.kind.value:<10s} {node.name:<20s} {tag}"
                )

    return "\n".join(lines)


def _node_tag(node: CpgNode, path: Any) -> str:
    """Return a parenthetical tag for a node on a path."""
    if node == path.source:
        label_names = ", ".join(sorted(lb.name for lb in path.labels))
        return f"(source: {label_names})"
    if node == path.sink:
        return "(sink)"
    if node in path.sanitizers:
        return "(sanitizer)"
    return ""


def _loc_str(node: CpgNode) -> str:
    """Format a node's source location for display."""
    if node.location is None:
        return "<unknown>:0  "
    return f"{node.location.file}:{node.location.line:<5d}"


def _format_json(result: TaintResult, show_sanitized: bool) -> str:
    """Produce JSON taint output."""
    unsanitized = result.unsanitized_paths()
    sanitized = result.sanitized_paths()

    paths_data = []
    for path in unsanitized:
        paths_data.append(_path_to_dict(path))
    if show_sanitized:
        for path in sanitized:
            paths_data.append(_path_to_dict(path))

    output = {
        "total_paths": len(result.paths),
        "unsanitized": len(unsanitized),
        "sanitized": len(sanitized),
        "paths": paths_data,
    }
    return json.dumps(output, indent=2, default=str)


def _path_to_dict(path: Any) -> dict[str, Any]:
    """Serialize a TaintPath to a dict."""
    return {
        "source": path.source.name,
        "sink": path.sink.name,
        "is_sanitized": path.is_sanitized,
        "labels": sorted(lb.name for lb in path.labels),
        "sanitizers": [n.name for n in path.sanitizers],
        "intermediates": [
            {
                "name": n.name,
                "kind": n.kind.value,
                "location": (
                    f"{n.location.file}:{n.location.line}"
                    if n.location else None
                ),
            }
            for n in path.intermediates
        ],
    }
