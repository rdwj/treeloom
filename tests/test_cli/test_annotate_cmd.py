"""Tests for treeloom.cli.annotate_cmd."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

from treeloom.cli.annotate_cmd import _load_rules, _matches, run_cmd
from treeloom.export.json import from_json, to_json
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind

FAKE_FILE = Path("app.py")


def _loc(line: int = 1) -> SourceLocation:
    return SourceLocation(file=FAKE_FILE, line=line)


def _build_cpg() -> CodePropertyGraph:
    """Build a small CPG with functions, calls, and a variable."""
    cpg = CodePropertyGraph()
    cpg.add_node(CpgNode(NodeId("f1"), NodeKind.FUNCTION, "handle_request", _loc(1)))
    cpg.add_node(CpgNode(NodeId("f2"), NodeKind.FUNCTION, "internal_fn", _loc(10)))
    cpg.add_node(CpgNode(NodeId("c1"), NodeKind.CALL, "exec", _loc(5)))
    cpg.add_node(CpgNode(NodeId("c2"), NodeKind.CALL, "os.system", _loc(6)))
    cpg.add_node(CpgNode(NodeId("c3"), NodeKind.CALL, "escape", _loc(8)))
    cpg.add_node(CpgNode(NodeId("v1"), NodeKind.VARIABLE, "data", _loc(3)))
    return cpg


def _write_cpg(tmp_path: Path, cpg: CodePropertyGraph) -> Path:
    p = tmp_path / "cpg.json"
    p.write_text(to_json(cpg), encoding="utf-8")
    return p


def _write_rules(tmp_path: Path, rules: dict) -> Path:
    p = tmp_path / "rules.yaml"
    p.write_text(yaml.dump(rules), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Unit tests for _matches
# ---------------------------------------------------------------------------


def test_matches_kind():
    node = CpgNode(NodeId("n1"), NodeKind.FUNCTION, "foo", _loc())
    assert _matches(node, {"kind": "FUNCTION"})
    assert not _matches(node, {"kind": "CALL"})


def test_matches_name_regex():
    node = CpgNode(NodeId("n1"), NodeKind.CALL, "os.system", _loc())
    assert _matches(node, {"name": r"exec|os\.system"})
    assert not _matches(node, {"name": "^escape$"})


def test_matches_kind_and_name():
    node = CpgNode(NodeId("n1"), NodeKind.FUNCTION, "handle_request", _loc())
    assert _matches(node, {"kind": "FUNCTION", "name": "handle_.*"})
    assert not _matches(node, {"kind": "CALL", "name": "handle_.*"})


def test_matches_attr():
    node = CpgNode(NodeId("n1"), NodeKind.VARIABLE, "x", _loc(), attrs={"is_global": True})
    assert _matches(node, {"attr": {"is_global": True}})
    assert not _matches(node, {"attr": {"is_global": False}})


def test_matches_invalid_kind_returns_false():
    node = CpgNode(NodeId("n1"), NodeKind.FUNCTION, "foo", _loc())
    assert not _matches(node, {"kind": "NOTAKIND"})


def test_matches_empty_criteria():
    node = CpgNode(NodeId("n1"), NodeKind.FUNCTION, "foo", _loc())
    assert _matches(node, {})


# ---------------------------------------------------------------------------
# Unit tests for _load_rules
# ---------------------------------------------------------------------------


def test_load_rules_basic(tmp_path: Path):
    rules_data = {
        "annotations": [
            {"match": {"kind": "FUNCTION"}, "set": {"role": "entry_point"}},
        ]
    }
    path = _write_rules(tmp_path, rules_data)
    rules = _load_rules(path)
    assert len(rules) == 1
    assert rules[0]["set"]["role"] == "entry_point"


def test_load_rules_invalid_top_level(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="YAML mapping"):
        _load_rules(path)


# ---------------------------------------------------------------------------
# Integration tests via run_cmd
# ---------------------------------------------------------------------------


def _make_args(
    cpg_file: Path,
    rules: Path,
    output: Path | None = None,
    json_output: bool = False,
) -> Namespace:
    return Namespace(
        cpg_file=cpg_file,
        rules=rules,
        output=output,
        json_output=json_output,
    )


def test_annotate_applies_rules(tmp_path: Path):
    cpg = _build_cpg()
    cpg_path = _write_cpg(tmp_path, cpg)
    rules_path = _write_rules(tmp_path, {
        "annotations": [
            {"match": {"kind": "FUNCTION", "name": "handle_.*"}, "set": {"role": "entry_point"}},
            {
                "match": {"kind": "CALL", "name": r"exec|os\.system"},
                "set": {"role": "sink", "cwe_id": 78},
            },
            {"match": {"kind": "CALL", "name": "escape"}, "set": {"role": "sanitizer"}},
        ]
    })
    out_path = tmp_path / "out.json"
    args = _make_args(cpg_path, rules_path, output=out_path)

    rc = run_cmd(args)
    assert rc == 0
    assert out_path.exists()

    result = from_json(out_path.read_text())
    # handle_request -> entry_point
    fn_nodes = [n for n in result.nodes(kind=NodeKind.FUNCTION) if n.name == "handle_request"]
    assert len(fn_nodes) == 1
    assert result.get_annotation(fn_nodes[0].id, "role") == "entry_point"

    # exec -> sink, cwe_id=78
    exec_nodes = [n for n in result.nodes(kind=NodeKind.CALL) if n.name == "exec"]
    assert len(exec_nodes) == 1
    assert result.get_annotation(exec_nodes[0].id, "role") == "sink"
    assert result.get_annotation(exec_nodes[0].id, "cwe_id") == 78

    # escape -> sanitizer
    esc_nodes = [n for n in result.nodes(kind=NodeKind.CALL) if n.name == "escape"]
    assert len(esc_nodes) == 1
    assert result.get_annotation(esc_nodes[0].id, "role") == "sanitizer"


def test_annotate_no_match_leaves_cpg_unchanged(tmp_path: Path):
    cpg = _build_cpg()
    cpg_path = _write_cpg(tmp_path, cpg)
    rules_path = _write_rules(tmp_path, {
        "annotations": [
            {"match": {"kind": "FUNCTION", "name": "nonexistent_fn"}, "set": {"role": "sink"}},
        ]
    })
    out_path = tmp_path / "out.json"
    rc = run_cmd(_make_args(cpg_path, rules_path, output=out_path))
    assert rc == 0
    result = from_json(out_path.read_text())
    for node in result.nodes():
        assert result.get_annotation(node.id, "role") is None


def test_annotate_json_output(tmp_path: Path, capsys):
    cpg = _build_cpg()
    cpg_path = _write_cpg(tmp_path, cpg)
    rules_path = _write_rules(tmp_path, {
        "annotations": [
            {"match": {"kind": "CALL", "name": "exec"}, "set": {"role": "sink"}},
        ]
    })
    out_path = tmp_path / "out.json"
    args = _make_args(cpg_path, rules_path, output=out_path, json_output=True)
    rc = run_cmd(args)
    assert rc == 0

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["total_annotated"] == 1
    assert summary["rule_count"] == 1
    assert summary["rules"][0]["matches"] == 1
    assert summary["rules"][0]["set"]["role"] == "sink"


def test_annotate_missing_cpg_file(tmp_path: Path):
    rules_path = _write_rules(tmp_path, {"annotations": []})
    args = _make_args(tmp_path / "missing.json", rules_path)
    with pytest.raises(FileNotFoundError):
        run_cmd(args)


def test_annotate_missing_rules_file(tmp_path: Path):
    cpg = _build_cpg()
    cpg_path = _write_cpg(tmp_path, cpg)
    args = _make_args(cpg_path, tmp_path / "missing.yaml")
    with pytest.raises(FileNotFoundError):
        run_cmd(args)


def test_annotate_multiple_rules_count(tmp_path: Path, capsys):
    cpg = _build_cpg()
    cpg_path = _write_cpg(tmp_path, cpg)
    rules_path = _write_rules(tmp_path, {
        "annotations": [
            {"match": {"kind": "FUNCTION"}, "set": {"role": "function"}},
            {"match": {"kind": "CALL"}, "set": {"role": "call_site"}},
        ]
    })
    out_path = tmp_path / "out.json"
    rc = run_cmd(_make_args(cpg_path, rules_path, output=out_path))
    assert rc == 0

    captured = capsys.readouterr()
    # 2 functions + 3 calls = 5 total
    assert "5 nodes" in captured.out
    assert "2 rules" in captured.out
