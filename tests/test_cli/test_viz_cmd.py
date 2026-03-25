"""Tests for treeloom.cli.viz_cmd."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from treeloom.cli.viz_cmd import run_cmd
from treeloom.export.json import to_json
from treeloom.graph.cpg import CodePropertyGraph
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


class TestVizCmd:
    def test_produces_html(self, tmp_path: Path) -> None:
        cpg = _minimal_cpg()
        cpg_file = tmp_path / "cpg.json"
        cpg_file.write_text(to_json(cpg))

        out_file = tmp_path / "out.html"
        args = Namespace(
            cpg_file=cpg_file, output=out_file,
            title="Test Graph", open_browser=False,
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
        )
        rc = run_cmd(args)
        assert rc == 0
        assert (tmp_path / "graph.html").exists()

    def test_missing_cpg_file(self, tmp_path: Path) -> None:
        args = Namespace(
            cpg_file=tmp_path / "no.json", output=None,
            title="T", open_browser=False,
        )
        with pytest.raises(FileNotFoundError):
            run_cmd(args)
