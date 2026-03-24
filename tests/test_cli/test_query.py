"""Tests for ``treeloom query`` command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from treeloom.cli.build import run_build
from treeloom.cli.config import Config
from treeloom.cli.query import run_query


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


def _make_args(cpg_file: Path, **overrides: object) -> argparse.Namespace:
    defaults = {
        "cpg_file": cpg_file,
        "kind": None,
        "name": None,
        "file": None,
        "as_json": False,
        "limit": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestQuery:
    def test_query_all(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file)
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Kind" in out  # header

    def test_query_kind_filter(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, kind=["function"])
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        # Every data line should be a function
        lines = [l for l in out.strip().split("\n") if l and not l.startswith("-")]
        for line in lines[1:]:  # skip header
            assert line.strip().startswith("function")

    def test_query_name_regex(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, name="add")
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "add" in out

    def test_query_file_filter(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, file="simple_function")
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "simple_function" in out

    def test_query_limit(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, limit=2)
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        # Header + separator + at most 2 data lines
        data_lines = [l for l in out.strip().split("\n") if l and not l.startswith("-")]
        assert len(data_lines) <= 3  # header + 2 data

    def test_query_json_output(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, as_json=True, kind=["function"])
        rc = run_query(args, default_cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        for item in data:
            assert item["kind"] == "function"

    def test_query_no_results(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, name="zzz_nonexistent_zzz")
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "No matching" in out

    def test_query_missing_file(self, tmp_path: Path, default_cfg: Config) -> None:
        args = _make_args(tmp_path / "nope.json")
        rc = run_query(args, default_cfg)
        assert rc == 1
