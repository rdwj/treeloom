"""CLI subcommand: annotate -- apply YAML annotation rules to a CPG."""

from __future__ import annotations

import json
import re
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

import yaml

from treeloom.cli._util import load_cpg
from treeloom.export.json import to_json
from treeloom.model.nodes import CpgNode, NodeKind


def register(subparsers: Any) -> None:
    """Register the ``annotate`` subcommand."""
    parser: ArgumentParser = subparsers.add_parser(
        "annotate",
        help="Apply YAML annotation rules to a serialized CPG",
    )
    parser.add_argument("cpg_file", type=Path, help="Path to CPG JSON file")
    parser.add_argument(
        "--rules", "-r", type=Path, required=True, help="Path to YAML rules file"
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None, help="Write annotated CPG to file"
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", default=False,
        help="Output summary as JSON",
    )
    parser.set_defaults(func=run_cmd)


def run_cmd(args: Namespace, _cfg: object = None) -> int:
    """Execute the annotate subcommand."""
    cpg_path: Path = args.cpg_file
    rules_path: Path = args.rules

    if not cpg_path.is_file():
        print(f"Error: CPG file not found: {cpg_path}", file=sys.stderr)
        return 1
    if not rules_path.is_file():
        print(f"Error: rules file not found: {rules_path}", file=sys.stderr)
        return 1

    try:
        cpg = load_cpg(cpg_path)
    except Exception as exc:
        print(f"Error loading CPG: {exc}", file=sys.stderr)
        return 1

    try:
        rules = _load_rules(rules_path)
    except Exception as exc:
        print(f"Error loading rules: {exc}", file=sys.stderr)
        return 1

    # Apply rules and track per-rule match counts
    rule_stats: list[dict[str, Any]] = []
    total_annotated = 0

    for rule in rules:
        match_criteria = rule.get("match", {})
        set_values: dict[str, Any] = rule.get("set", {})
        matched_ids = []

        for node in cpg.nodes():
            if _matches(node, match_criteria):
                for key, value in set_values.items():
                    cpg.annotate_node(node.id, key, value)
                matched_ids.append(node.id)

        rule_stats.append({
            "match": match_criteria,
            "set": set_values,
            "count": len(matched_ids),
        })
        total_annotated += len(matched_ids)

    # Determine output path for display
    out_path = args.output or Path("annotated.json")
    annotated_json = to_json(cpg)

    if args.output:
        args.output.write_text(annotated_json, encoding="utf-8")
    else:
        # Write CPG JSON to annotated.json by default when no -o given
        out_path.write_text(annotated_json, encoding="utf-8")

    if args.json_output:
        summary = {
            "total_annotated": total_annotated,
            "rule_count": len(rules),
            "output": str(out_path),
            "rules": [
                {
                    "match": s["match"],
                    "set": s["set"],
                    "matches": s["count"],
                }
                for s in rule_stats
            ],
        }
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"Annotated {total_annotated} nodes across {len(rules)} rules"
            f" -> {out_path}"
        )
        for i, stat in enumerate(rule_stats, 1):
            match_desc = ", ".join(
                f"{k}={v}" for k, v in stat["match"].items()
            )
            set_desc = ", ".join(
                f"{k}={v}" for k, v in stat["set"].items()
            )
            print(f"  rule {i} ({match_desc}): {stat['count']} matches -> {set_desc}")

    return 0


# ---------------------------------------------------------------------------
# Rules loading and matching
# ---------------------------------------------------------------------------


def _load_rules(path: Path) -> list[dict[str, Any]]:
    """Parse a YAML rules file and return the list of annotation rules."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"Rules file must be a YAML mapping, got {type(data).__name__}"
        raise ValueError(msg)
    rules = data.get("annotations", [])
    if not isinstance(rules, list):
        msg = "'annotations' must be a list"
        raise ValueError(msg)
    return rules


def _matches(node: CpgNode, criteria: dict[str, Any]) -> bool:
    """Return True if *node* satisfies all criteria in the match dict."""
    if "kind" in criteria:
        try:
            expected = NodeKind(criteria["kind"].lower())
        except ValueError:
            return False
        if node.kind != expected:
            return False
    if "name" in criteria:
        if not re.search(criteria["name"], node.name):
            return False
    if "attr" in criteria:
        for k, v in criteria["attr"].items():
            if node.attrs.get(k) != v:
                return False
    return True
