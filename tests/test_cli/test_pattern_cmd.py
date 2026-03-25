"""Tests for treeloom.cli.pattern_cmd."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

from treeloom.cli.pattern_cmd import _parse_pattern, run_cmd
from treeloom.export.json import to_json
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind

FAKE_FILE = Path("src/api.py")


def _loc(line: int) -> SourceLocation:
    return SourceLocation(file=FAKE_FILE, line=line)


def _build_flow_cpg() -> CodePropertyGraph:
    """Build: PARAMETER -[DATA_FLOWS_TO]-> VARIABLE -[DATA_FLOWS_TO]-> CALL."""
    cpg = CodePropertyGraph()
    param = CpgNode(NodeId("p1"), NodeKind.PARAMETER, "user_data", _loc(12))
    var = CpgNode(NodeId("v1"), NodeKind.VARIABLE, "processed", _loc(15))
    call = CpgNode(NodeId("c1"), NodeKind.CALL, "exec", _loc(18))

    for node in (param, var, call):
        cpg.add_node(node)

    cpg.add_edge(CpgEdge(param.id, var.id, EdgeKind.DATA_FLOWS_TO))
    cpg.add_edge(CpgEdge(var.id, call.id, EdgeKind.DATA_FLOWS_TO))
    return cpg


def _write_cpg(cpg: CodePropertyGraph, path: Path) -> None:
    path.write_text(to_json(cpg), encoding="utf-8")


def _write_pattern(data: dict, path: Path) -> None:
    path.write_text(yaml.dump(data), encoding="utf-8")


def _args(cpg_file: Path, pattern_file: Path, **kwargs) -> Namespace:
    defaults = {"json_output": False, "limit": 0}
    defaults.update(kwargs)
    return Namespace(cpg_file=cpg_file, pattern=pattern_file, **defaults)


# ---------------------------------------------------------------------------
# Pattern parsing unit tests
# ---------------------------------------------------------------------------


def test_parse_pattern_basic():
    data = {
        "steps": [
            {"kind": "PARAMETER"},
            {"wildcard": True},
            {"kind": "CALL", "name": "exec|eval"},
        ],
        "edge_kind": "data_flows_to",
    }
    pattern = _parse_pattern(data)
    assert len(pattern.steps) == 3
    assert pattern.steps[0].kind == NodeKind.PARAMETER
    assert pattern.steps[1].wildcard is True
    assert pattern.steps[2].kind == NodeKind.CALL
    assert pattern.steps[2].name_pattern == "exec|eval"
    assert pattern.edge_kind == EdgeKind.DATA_FLOWS_TO


def test_parse_pattern_no_edge_kind():
    data = {"steps": [{"kind": "FUNCTION"}]}
    pattern = _parse_pattern(data)
    assert pattern.edge_kind is None


def test_parse_pattern_missing_steps_raises():
    with pytest.raises(ValueError, match="steps"):
        _parse_pattern({})


def test_parse_pattern_invalid_kind_raises():
    with pytest.raises(ValueError, match="unknown kind"):
        _parse_pattern({"steps": [{"kind": "NOTANODE"}]})


def test_parse_pattern_invalid_edge_kind_raises():
    with pytest.raises(ValueError, match="unknown edge_kind"):
        _parse_pattern({"steps": [{"kind": "CALL"}], "edge_kind": "bad_edge"})


# ---------------------------------------------------------------------------
# run_cmd integration tests
# ---------------------------------------------------------------------------


def test_run_cmd_finds_chain(tmp_path):
    cpg = _build_flow_cpg()
    cpg_file = tmp_path / "cpg.json"
    pat_file = tmp_path / "pattern.yaml"
    _write_cpg(cpg, cpg_file)
    _write_pattern(
        {
            "steps": [
                {"kind": "PARAMETER"},
                {"wildcard": True},
                {"kind": "CALL"},
            ],
            "edge_kind": "data_flows_to",
        },
        pat_file,
    )
    args = _args(cpg_file, pat_file)
    rc = run_cmd(args)
    assert rc == 0


def test_run_cmd_human_output_contains_node_names(tmp_path, capsys):
    cpg = _build_flow_cpg()
    cpg_file = tmp_path / "cpg.json"
    pat_file = tmp_path / "pattern.yaml"
    _write_cpg(cpg, cpg_file)
    _write_pattern(
        {
            "steps": [
                {"kind": "PARAMETER"},
                {"kind": "VARIABLE"},
                {"kind": "CALL"},
            ],
            "edge_kind": "data_flows_to",
        },
        pat_file,
    )
    run_cmd(_args(cpg_file, pat_file))
    out = capsys.readouterr().out
    assert "user_data" in out
    assert "processed" in out
    assert "exec" in out
    assert "Chain 1" in out


def test_run_cmd_json_output(tmp_path, capsys):
    cpg = _build_flow_cpg()
    cpg_file = tmp_path / "cpg.json"
    pat_file = tmp_path / "pattern.yaml"
    _write_cpg(cpg, cpg_file)
    _write_pattern(
        {"steps": [{"kind": "PARAMETER"}, {"kind": "CALL"}]},
        pat_file,
    )
    # No direct PARAMETER->CALL edge in our CPG, so this finds nothing; verify
    # json output is still valid JSON.
    run_cmd(_args(cpg_file, pat_file, json_output=True))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)


def test_run_cmd_json_output_chain_structure(tmp_path, capsys):
    cpg = _build_flow_cpg()
    cpg_file = tmp_path / "cpg.json"
    pat_file = tmp_path / "pattern.yaml"
    _write_cpg(cpg, cpg_file)
    _write_pattern(
        {
            "steps": [
                {"kind": "PARAMETER"},
                {"kind": "VARIABLE"},
                {"kind": "CALL"},
            ],
            "edge_kind": "data_flows_to",
        },
        pat_file,
    )
    run_cmd(_args(cpg_file, pat_file, json_output=True))
    chains = json.loads(capsys.readouterr().out)
    assert len(chains) == 1
    assert len(chains[0]) == 3
    kinds = [n["kind"] for n in chains[0]]
    assert kinds == ["parameter", "variable", "call"]


def test_run_cmd_no_matches(tmp_path, capsys):
    cpg = _build_flow_cpg()
    cpg_file = tmp_path / "cpg.json"
    pat_file = tmp_path / "pattern.yaml"
    _write_cpg(cpg, cpg_file)
    # Pattern that won't match: LOOP node doesn't exist in our CPG
    _write_pattern({"steps": [{"kind": "LOOP"}]}, pat_file)
    rc = run_cmd(_args(cpg_file, pat_file))
    assert rc == 0
    out = capsys.readouterr().out
    assert "No matching chains" in out


def test_run_cmd_limit(tmp_path, capsys):
    """--limit N caps the number of chains shown."""
    cpg = CodePropertyGraph()
    # Add several PARAMETER nodes with DATA_FLOWS_TO edges to a CALL
    call = CpgNode(NodeId("c1"), NodeKind.CALL, "sink", _loc(10))
    cpg.add_node(call)
    for i in range(5):
        p = CpgNode(NodeId(f"p{i}"), NodeKind.PARAMETER, f"arg{i}", _loc(i + 1))
        cpg.add_node(p)
        cpg.add_edge(CpgEdge(p.id, call.id, EdgeKind.DATA_FLOWS_TO))

    cpg_file = tmp_path / "cpg.json"
    pat_file = tmp_path / "pattern.yaml"
    _write_cpg(cpg, cpg_file)
    _write_pattern(
        {"steps": [{"kind": "PARAMETER"}, {"kind": "CALL"}], "edge_kind": "data_flows_to"},
        pat_file,
    )
    run_cmd(_args(cpg_file, pat_file, limit=2, json_output=True))
    chains = json.loads(capsys.readouterr().out)
    assert len(chains) == 2


def test_run_cmd_missing_cpg_file(tmp_path):
    pat_file = tmp_path / "pattern.yaml"
    pat_file.write_text("steps:\n  - kind: CALL\n")
    args = _args(tmp_path / "nope.json", pat_file)
    with pytest.raises(FileNotFoundError):
        run_cmd(args)


def test_run_cmd_missing_pattern_file(tmp_path):
    cpg = _build_flow_cpg()
    cpg_file = tmp_path / "cpg.json"
    _write_cpg(cpg, cpg_file)
    args = _args(cpg_file, tmp_path / "nope.yaml")
    with pytest.raises(FileNotFoundError):
        run_cmd(args)


def test_run_cmd_invalid_pattern_yaml(tmp_path):
    cpg = _build_flow_cpg()
    cpg_file = tmp_path / "cpg.json"
    pat_file = tmp_path / "bad.yaml"
    _write_cpg(cpg, cpg_file)
    pat_file.write_text("not_steps: 42\n")  # valid YAML, invalid pattern
    rc = run_cmd(_args(cpg_file, pat_file))
    assert rc == 1
