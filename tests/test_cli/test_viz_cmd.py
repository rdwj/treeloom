"""Tests for treeloom.cli.viz_cmd."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from treeloom.cli.viz_cmd import _LARGE_GRAPH_THRESHOLD, run_cmd
from treeloom.export.json import to_json
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind


def _minimal_cpg() -> CodePropertyGraph:
    cpg = CodePropertyGraph()
    node = CpgNode(
        NodeId("m1"), NodeKind.MODULE, "app",
        SourceLocation(file=Path("app.py"), line=1),
    )
    cpg.add_node(node)
    return cpg


def _cpg_with_import() -> CodePropertyGraph:
    cpg = CodePropertyGraph()
    cpg.add_node(CpgNode(
        NodeId("mod"), NodeKind.MODULE, "app",
        SourceLocation(file=Path("app.py"), line=1),
    ))
    cpg.add_node(CpgNode(
        NodeId("imp"), NodeKind.IMPORT, "os",
        SourceLocation(file=Path("app.py"), line=2),
    ))
    cpg.add_edge(CpgEdge(source=NodeId("mod"), target=NodeId("imp"), kind=EdgeKind.IMPORTS))
    return cpg


class TestVizCmd:
    def test_produces_html(self, tmp_path: Path) -> None:
        cpg = _minimal_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        out_file = tmp_path / "out.html"
        args = Namespace(
            cpg_file=cpg_file, output=out_file,
            title="Test Graph", open_browser=False,
            exclude_kinds=[],
        )
        rc = run_cmd(args)
        assert rc == 0
        assert out_file.exists()

        html = out_file.read_text()
        assert "<html" in html
        assert "cytoscape" in html.lower()

    def test_title_in_output(self, tmp_path: Path) -> None:
        cpg = _minimal_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        out_file = tmp_path / "out.html"
        args = Namespace(
            cpg_file=cpg_file, output=out_file,
            title="My Custom Title", open_browser=False,
            exclude_kinds=[],
        )
        run_cmd(args)

        html = out_file.read_text()
        assert "My Custom Title" in html

    def test_default_output_name(self, tmp_path: Path) -> None:
        cpg = _minimal_cpg()
        cpg_file = tmp_path / "graph.json"
        cpg_file.write_text(to_json(cpg))

        args = Namespace(
            cpg_file=cpg_file, output=None,
            title="Code Property Graph", open_browser=False,
            exclude_kinds=[],
        )
        rc = run_cmd(args)
        assert rc == 0
        assert (tmp_path / "graph.html").exists()

    def test_missing_cpg_file(self, tmp_path: Path) -> None:
        args = Namespace(
            cpg_file=tmp_path / "no.json", output=None,
            title="T", open_browser=False,
            exclude_kinds=[],
        )
        with pytest.raises(FileNotFoundError):
            run_cmd(args)


class TestVizExcludeKind:
    def test_exclude_import_removes_import_nodes(self, tmp_path: Path) -> None:
        cpg = _cpg_with_import()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        out_file = tmp_path / "out.html"
        args = Namespace(
            cpg_file=cpg_file, output=out_file,
            title="T", open_browser=False,
            exclude_kinds=["import"],
        )
        rc = run_cmd(args)
        assert rc == 0
        html = out_file.read_text()
        # The import node id "imp" should not appear as a node element.
        assert '"imp"' not in html
        # The module node should still be present.
        assert '"app"' in html

    def test_invalid_kind_returns_error(self, tmp_path: Path) -> None:
        cpg = _minimal_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        args = Namespace(
            cpg_file=cpg_file, output=tmp_path / "out.html",
            title="T", open_browser=False,
            exclude_kinds=["notakind"],
        )
        rc = run_cmd(args)
        assert rc == 1

    def test_multiple_exclude_kinds(self, tmp_path: Path) -> None:
        cpg = _cpg_with_import()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        out_file = tmp_path / "out.html"
        args = Namespace(
            cpg_file=cpg_file, output=out_file,
            title="T", open_browser=False,
            exclude_kinds=["import", "literal"],
        )
        rc = run_cmd(args)
        assert rc == 0


class TestVizLargeGraphWarning:
    def test_warning_emitted_for_large_graph(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Build a CPG with enough nodes to trigger the warning.
        cpg = CodePropertyGraph()
        for i in range(_LARGE_GRAPH_THRESHOLD + 1):
            cpg.add_node(CpgNode(
                NodeId(f"n{i}"), NodeKind.VARIABLE, f"x{i}",
                SourceLocation(file=Path("f.py"), line=i + 1),
            ))
        cpg_file = tmp_path / "big.json"
        cpg_file.write_text(to_json(cpg))

        args = Namespace(
            cpg_file=cpg_file, output=tmp_path / "out.html",
            title="T", open_browser=False,
            exclude_kinds=[],
        )
        run_cmd(args)
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "nodes" in captured.err

    def test_no_warning_for_small_graph(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cpg = _minimal_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        args = Namespace(
            cpg_file=cpg_file, output=tmp_path / "out.html",
            title="T", open_browser=False,
            exclude_kinds=[],
        )
        run_cmd(args)
        captured = capsys.readouterr()
        assert "Warning" not in captured.err
