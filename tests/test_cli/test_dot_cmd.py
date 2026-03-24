"""Tests for treeloom.cli.dot_cmd."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from treeloom.cli.dot_cmd import run_cmd
from treeloom.export.json import to_json
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind


def _build_cpg() -> CodePropertyGraph:
    cpg = CodePropertyGraph()
    mod = CpgNode(
        NodeId("m1"), NodeKind.MODULE, "app",
        SourceLocation(file=Path("app.py"), line=1),
    )
    func = CpgNode(
        NodeId("f1"), NodeKind.FUNCTION, "handler",
        SourceLocation(file=Path("app.py"), line=5), scope=mod.id,
    )
    call = CpgNode(
        NodeId("c1"), NodeKind.CALL, "exec",
        SourceLocation(file=Path("app.py"), line=10), scope=func.id,
    )
    for node in (mod, func, call):
        cpg.add_node(node)

    cpg.add_edge(CpgEdge(mod.id, func.id, EdgeKind.CONTAINS))
    cpg.add_edge(CpgEdge(func.id, call.id, EdgeKind.CONTAINS))
    cpg.add_edge(CpgEdge(call.id, func.id, EdgeKind.CALLS))
    return cpg


class TestDotCmd:
    def test_produces_dot(self, tmp_path: Path) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        out_file = tmp_path / "out.dot"
        args = Namespace(
            cpg_file=cpg_file, output=out_file,
            edge_kinds=None, node_kinds=None,
        )
        rc = run_cmd(args)
        assert rc == 0
        assert out_file.exists()

        dot = out_file.read_text()
        assert "digraph CPG" in dot
        assert "handler" in dot

    def test_edge_kind_filter(self, tmp_path: Path) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        out_file = tmp_path / "out.dot"
        args = Namespace(
            cpg_file=cpg_file, output=out_file,
            edge_kinds=["calls"], node_kinds=None,
        )
        rc = run_cmd(args)
        assert rc == 0

        dot = out_file.read_text()
        assert "calls" in dot
        # CONTAINS edges should be filtered out
        assert "contains" not in dot

    def test_stdout_output(self, tmp_path: Path, capsys) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        args = Namespace(
            cpg_file=cpg_file, output=None,
            edge_kinds=None, node_kinds=None,
        )
        rc = run_cmd(args)
        assert rc == 0

        captured = capsys.readouterr()
        assert "digraph CPG" in captured.out

    def test_invalid_edge_kind(self, tmp_path: Path) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        args = Namespace(
            cpg_file=cpg_file, output=None,
            edge_kinds=["bogus"], node_kinds=None,
        )
        rc = run_cmd(args)
        assert rc == 1

    def test_missing_cpg_file(self, tmp_path: Path) -> None:
        args = Namespace(
            cpg_file=tmp_path / "nope.json", output=None,
            edge_kinds=None, node_kinds=None,
        )
        assert run_cmd(args) == 1

    def test_node_kind_filter(self, tmp_path: Path) -> None:
        cpg = _build_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        out_file = tmp_path / "out.dot"
        args = Namespace(
            cpg_file=cpg_file, output=out_file,
            edge_kinds=None, node_kinds=["function"],
        )
        rc = run_cmd(args)
        assert rc == 0

        dot = out_file.read_text()
        assert "handler" in dot
        # Module node should not appear as a node declaration
        assert "module: app" not in dot
