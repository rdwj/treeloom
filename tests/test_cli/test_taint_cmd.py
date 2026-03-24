"""Tests for treeloom.cli.taint_cmd."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

from treeloom.analysis.taint import TaintLabel
from treeloom.cli.taint_cmd import load_policy, run_cmd, _matches
from treeloom.export.json import to_json
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind

FAKE_FILE = Path("app.py")


def _loc(line: int = 1) -> SourceLocation:
    return SourceLocation(file=FAKE_FILE, line=line)


def _build_taint_cpg() -> CodePropertyGraph:
    """Build a small CPG with a source -> intermediate -> sink data flow."""
    cpg = CodePropertyGraph()

    param = CpgNode(NodeId("p1"), NodeKind.PARAMETER, "user_data", _loc(1))
    var = CpgNode(NodeId("v1"), NodeKind.VARIABLE, "processed", _loc(5))
    call_exec = CpgNode(NodeId("c1"), NodeKind.CALL, "exec", _loc(10))
    sanitizer = CpgNode(NodeId("s1"), NodeKind.CALL, "html.escape", _loc(8))

    for node in (param, var, call_exec, sanitizer):
        cpg.add_node(node)

    # Unsanitized path: param -> var -> exec
    cpg.add_edge(CpgEdge(param.id, var.id, EdgeKind.DATA_FLOWS_TO))
    cpg.add_edge(CpgEdge(var.id, call_exec.id, EdgeKind.DATA_FLOWS_TO))

    return cpg


def _build_sanitized_cpg() -> CodePropertyGraph:
    """Build a CPG with a sanitized path: source -> sanitizer -> sink."""
    cpg = CodePropertyGraph()

    param = CpgNode(NodeId("p1"), NodeKind.PARAMETER, "user_data", _loc(1))
    san = CpgNode(NodeId("s1"), NodeKind.CALL, "escape", _loc(5))
    sink = CpgNode(NodeId("c1"), NodeKind.CALL, "exec", _loc(10))

    for node in (param, san, sink):
        cpg.add_node(node)

    cpg.add_edge(CpgEdge(param.id, san.id, EdgeKind.DATA_FLOWS_TO))
    cpg.add_edge(CpgEdge(san.id, sink.id, EdgeKind.DATA_FLOWS_TO))

    return cpg


def _write_cpg(cpg: CodePropertyGraph, path: Path) -> None:
    path.write_text(to_json(cpg))


def _write_policy(policy_dict: dict, path: Path) -> None:
    path.write_text(yaml.dump(policy_dict))


BASIC_POLICY = {
    "sources": [
        {"kind": "PARAMETER", "name": "user_.*", "label": "user_input"},
    ],
    "sinks": [
        {"kind": "CALL", "name": "exec|eval"},
    ],
    "sanitizers": [
        {"kind": "CALL", "name": "escape|sanitize|html\\.escape"},
    ],
}


class TestLoadPolicy:
    def test_basic_parsing(self, tmp_path: Path) -> None:
        policy_file = tmp_path / "policy.yaml"
        _write_policy(BASIC_POLICY, policy_file)

        cpg = _build_taint_cpg()
        policy = load_policy(policy_file, cpg)

        # Source should match the parameter node
        param = cpg.node(NodeId("p1"))
        assert param is not None
        label = policy.sources(param)
        assert label is not None
        assert label.name == "user_input"

        # Sink should match the exec call
        call_node = cpg.node(NodeId("c1"))
        assert call_node is not None
        assert policy.sinks(call_node) is True

        # Variable is not a sink
        var_node = cpg.node(NodeId("v1"))
        assert var_node is not None
        assert policy.sinks(var_node) is False

    def test_sanitizer_matching(self, tmp_path: Path) -> None:
        policy_file = tmp_path / "policy.yaml"
        _write_policy(BASIC_POLICY, policy_file)

        cpg = _build_taint_cpg()
        policy = load_policy(policy_file, cpg)

        san_node = cpg.node(NodeId("s1"))
        assert san_node is not None
        assert policy.sanitizers(san_node) is True

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text("just a string")

        with pytest.raises(ValueError, match="YAML mapping"):
            load_policy(policy_file)

    def test_propagator_parsing(self, tmp_path: Path) -> None:
        policy_dict = {
            "sources": [],
            "sinks": [],
            "propagators": [
                {
                    "match": {"kind": "CALL", "name": "json.loads"},
                    "param_to_return": True,
                },
            ],
        }
        policy_file = tmp_path / "policy.yaml"
        _write_policy(policy_dict, policy_file)

        policy = load_policy(policy_file)
        assert len(policy.propagators) == 1

        # Build a node that should match
        node = CpgNode(NodeId("x"), NodeKind.CALL, "json.loads", _loc(1))
        assert policy.propagators[0].match(node) is True

    def test_attr_matching(self, tmp_path: Path) -> None:
        policy_dict = {
            "sources": [
                {"kind": "CALL", "attr": {"is_method_call": True}},
            ],
            "sinks": [],
        }
        policy_file = tmp_path / "policy.yaml"
        _write_policy(policy_dict, policy_file)

        policy = load_policy(policy_file)

        match_node = CpgNode(
            NodeId("m"), NodeKind.CALL, "foo", _loc(1),
            attrs={"is_method_call": True},
        )
        no_match = CpgNode(
            NodeId("n"), NodeKind.CALL, "bar", _loc(2),
            attrs={"is_method_call": False},
        )
        assert policy.sources(match_node) is not None
        assert policy.sources(no_match) is None


class TestMatches:
    def test_kind_case_insensitive(self) -> None:
        node = CpgNode(NodeId("x"), NodeKind.CALL, "test", _loc())
        assert _matches(node, {"kind": "CALL"}) is True
        assert _matches(node, {"kind": "call"}) is True

    def test_name_regex(self) -> None:
        node = CpgNode(NodeId("x"), NodeKind.CALL, "os.system", _loc())
        assert _matches(node, {"name": "os\\.system"}) is True
        assert _matches(node, {"name": "exec"}) is False

    def test_invalid_kind(self) -> None:
        node = CpgNode(NodeId("x"), NodeKind.CALL, "test", _loc())
        assert _matches(node, {"kind": "NONEXISTENT"}) is False


class TestRunCmd:
    def test_unsanitized_path_found(self, tmp_path: Path) -> None:
        cpg = _build_taint_cpg()
        cpg_file = tmp_path / "cpg.json"
        _write_cpg(cpg, cpg_file)

        policy_file = tmp_path / "policy.yaml"
        _write_policy(BASIC_POLICY, policy_file)

        out_file = tmp_path / "results.txt"
        args = Namespace(
            cpg_file=cpg_file, policy=policy_file, output=out_file,
            show_sanitized=False, json_output=False,
        )
        rc = run_cmd(args)
        assert rc == 0

        text = out_file.read_text()
        assert "UNSANITIZED" in text
        assert "exec" in text

    def test_json_output(self, tmp_path: Path) -> None:
        cpg = _build_taint_cpg()
        cpg_file = tmp_path / "cpg.json"
        _write_cpg(cpg, cpg_file)

        policy_file = tmp_path / "policy.yaml"
        _write_policy(BASIC_POLICY, policy_file)

        out_file = tmp_path / "results.json"
        args = Namespace(
            cpg_file=cpg_file, policy=policy_file, output=out_file,
            show_sanitized=False, json_output=True,
        )
        rc = run_cmd(args)
        assert rc == 0

        data = json.loads(out_file.read_text())
        assert "total_paths" in data
        assert "unsanitized" in data
        assert isinstance(data["paths"], list)

    def test_show_sanitized(self, tmp_path: Path) -> None:
        cpg = _build_sanitized_cpg()
        cpg_file = tmp_path / "cpg.json"
        _write_cpg(cpg, cpg_file)

        policy_file = tmp_path / "policy.yaml"
        _write_policy(BASIC_POLICY, policy_file)

        out_file = tmp_path / "results.txt"
        args = Namespace(
            cpg_file=cpg_file, policy=policy_file, output=out_file,
            show_sanitized=True, json_output=False,
        )
        rc = run_cmd(args)
        assert rc == 0

        text = out_file.read_text()
        assert "SANITIZED" in text

    def test_missing_cpg_file(self, tmp_path: Path) -> None:
        args = Namespace(
            cpg_file=tmp_path / "missing.json",
            policy=tmp_path / "policy.yaml",
            output=None, show_sanitized=False, json_output=False,
        )
        rc = run_cmd(args)
        assert rc == 1

    def test_missing_policy_file(self, tmp_path: Path) -> None:
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text("{}")

        args = Namespace(
            cpg_file=cpg_file,
            policy=tmp_path / "missing.yaml",
            output=None, show_sanitized=False, json_output=False,
        )
        rc = run_cmd(args)
        assert rc == 1
