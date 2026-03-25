"""Tests for ``treeloom info`` command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from treeloom.cli.build import run_build
from treeloom.cli.config import Config
from treeloom.cli.info import run_info


@pytest.fixture()
def default_cfg() -> Config:
    return Config()


@pytest.fixture()
def cpg_file(tmp_path: Path, default_cfg: Config) -> Path:
    fixture = Path(__file__).resolve().parent.parent / "fixtures" / "python" / "simple_function.py"
    out = tmp_path / "test.json"
    args = argparse.Namespace(path=fixture, output=out, exclude=None, quiet=True)
    run_build(args, default_cfg)
    return out


class TestInfo:
    def test_info_human_readable(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = argparse.Namespace(cpg_file=cpg_file, as_json=False)
        rc = run_info(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Nodes:" in out
        assert "Edges:" in out

    def test_info_json(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = argparse.Namespace(cpg_file=cpg_file, as_json=True)
        rc = run_info(args, default_cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "node_count" in data
        assert "edge_count" in data
        assert "file_count" in data
        assert isinstance(data["nodes_by_kind"], dict)
        assert isinstance(data["edges_by_kind"], dict)
        assert data["node_count"] > 0

    def test_info_missing_file(self, tmp_path: Path, default_cfg: Config) -> None:
        args = argparse.Namespace(cpg_file=tmp_path / "nope.json", as_json=False)
        with pytest.raises(FileNotFoundError):
            run_info(args, default_cfg)
