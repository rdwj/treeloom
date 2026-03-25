"""Tests for treeloom.cli.subgraph_cmd."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from treeloom.cli.subgraph_cmd import run_cmd
from treeloom.export.json import to_json
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_loc(file: str, line: int) -> SourceLocation:
    return SourceLocation(file=Path(file), line=line)


def _build_cpg() -> CodePropertyGraph:
    """Three-function CPG: module -> greet -> helper, with greet calling helper."""
    cpg = CodePropertyGraph()

    mod = CpgNode(NodeId("mod:app:1:0:0"), NodeKind.MODULE, "app", _make_loc("app.py", 1))
    greet = CpgNode(
        NodeId("fn:app:3:0:1"), NodeKind.FUNCTION, "greet",
        _make_loc("app.py", 3), scope=mod.id,
    )
    helper = CpgNode(
        NodeId("fn:app:8:0:2"), NodeKind.FUNCTION, "helper",
        _make_loc("app.py", 8), scope=mod.id,
    )
    param = CpgNode(
        NodeId("par:app:3:10:3"), NodeKind.PARAMETER, "name",
        _make_loc("app.py", 3), scope=greet.id,
    )
    call_node = CpgNode(
        NodeId("call:app:5:4:4"), NodeKind.CALL, "helper",
        _make_loc("app.py", 5), scope=greet.id,
    )
    cls = CpgNode(
        NodeId("cls:app:12:0:5"), NodeKind.CLASS, "Greeter",
        _make_loc("app.py", 12), scope=mod.id,
    )

    for node in (mod, greet, helper, param, call_node, cls):
        cpg.add_node(node)

    cpg.add_edge(CpgEdge(mod.id, greet.id, EdgeKind.CONTAINS))
    cpg.add_edge(CpgEdge(mod.id, helper.id, EdgeKind.CONTAINS))
    cpg.add_edge(CpgEdge(mod.id, cls.id, EdgeKind.CONTAINS))
    cpg.add_edge(CpgEdge(greet.id, param.id, EdgeKind.HAS_PARAMETER))
    cpg.add_edge(CpgEdge(greet.id, call_node.id, EdgeKind.CONTAINS))
    cpg.add_edge(CpgEdge(call_node.id, helper.id, EdgeKind.CALLS))
    return cpg


def _args(cpg_file: Path, output: Path, **kwargs) -> Namespace:
    defaults = dict(root=None, function=None, class_name=None, file=None, depth=10)
    defaults.update(kwargs)
    return Namespace(cpg_file=cpg_file, output=output, **defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSubgraphByFunction:
    def test_extracts_smaller_graph(self, tmp_path: Path) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))
        out = tmp_path / "sub.json"

        rc = run_cmd(_args(cpg_file, out, function="greet"))

        assert rc == 0
        assert out.exists()
        data = json.loads(out.read_text())
        node_names = {n["name"] for n in data["nodes"]}
        # greet and its children should be present; helper module-sibling should not
        assert "greet" in node_names
        assert "name" in node_names   # parameter child
        assert "Greeter" not in node_names  # sibling class excluded

    def test_default_output_name(self, tmp_path: Path, monkeypatch) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))
        # Run from tmp_path so the default subgraph.json lands there.
        monkeypatch.chdir(tmp_path)

        rc = run_cmd(_args(cpg_file, Path("subgraph.json"), function="greet"))

        assert rc == 0
        assert (tmp_path / "subgraph.json").exists()


class TestSubgraphByRoot:
    def test_exact_node_id(self, tmp_path: Path) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))
        out = tmp_path / "sub.json"

        # Use the greet function's node ID directly.
        rc = run_cmd(_args(cpg_file, out, root="fn:app:3:0:1"))

        assert rc == 0
        data = json.loads(out.read_text())
        names = {n["name"] for n in data["nodes"]}
        assert "greet" in names

    def test_unknown_root_id_returns_error(self, tmp_path: Path, capsys) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))
        out = tmp_path / "sub.json"

        rc = run_cmd(_args(cpg_file, out, root="no:such:node"))

        assert rc == 1
        assert "no:such:node" in capsys.readouterr().err


class TestSubgraphByClass:
    def test_class_root(self, tmp_path: Path) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))
        out = tmp_path / "sub.json"

        rc = run_cmd(_args(cpg_file, out, class_name="Greeter"))

        assert rc == 0
        data = json.loads(out.read_text())
        names = {n["name"] for n in data["nodes"]}
        assert "Greeter" in names

    def test_unknown_class_returns_error(self, tmp_path: Path, capsys) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        rc = run_cmd(_args(cpg_file, tmp_path / "sub.json", class_name="NoSuch"))

        assert rc == 1
        assert "NoSuch" in capsys.readouterr().err


class TestSubgraphByFile:
    def test_file_substring_match(self, tmp_path: Path) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))
        out = tmp_path / "sub.json"

        rc = run_cmd(_args(cpg_file, out, file="app"))

        assert rc == 0
        data = json.loads(out.read_text())
        # Module "app" is the root; entire graph reachable within depth 10
        assert len(data["nodes"]) > 1

    def test_unmatched_file_returns_error(self, tmp_path: Path, capsys) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        rc = run_cmd(_args(cpg_file, tmp_path / "sub.json", file="nothing.py"))

        assert rc == 1
        assert "nothing.py" in capsys.readouterr().err


class TestDepthLimiting:
    def test_depth_one_limits_results(self, tmp_path: Path) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))
        out_shallow = tmp_path / "shallow.json"
        out_deep = tmp_path / "deep.json"

        run_cmd(_args(cpg_file, out_shallow, function="greet", depth=1))
        run_cmd(_args(cpg_file, out_deep, function="greet", depth=10))

        shallow_count = len(json.loads(out_shallow.read_text())["nodes"])
        deep_count = len(json.loads(out_deep.read_text())["nodes"])
        assert shallow_count <= deep_count


class TestMissingCpgFile:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            run_cmd(_args(tmp_path / "ghost.json", tmp_path / "out.json", function="f"))


class TestNotFoundError:
    def test_missing_function_error_message(self, tmp_path: Path, capsys) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        rc = run_cmd(_args(cpg_file, tmp_path / "sub.json", function="nonexistent"))

        assert rc == 1
        stderr = capsys.readouterr().err
        assert "FUNCTION" in stderr
        assert "nonexistent" in stderr
