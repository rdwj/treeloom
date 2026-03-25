"""Tests for ``treeloom edges`` command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from treeloom.cli.build import run_build
from treeloom.cli.config import Config
from treeloom.cli.edges_cmd import run_cmd


@pytest.fixture()
def cfg() -> Config:
    return Config()


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "python"


@pytest.fixture()
def cpg_file(tmp_path: Path, cfg: Config) -> Path:
    src = FIXTURES / "function_calls.py"
    out = tmp_path / "edges_test.json"
    args = argparse.Namespace(path=src, output=out, exclude=None, quiet=True)
    run_build(args, cfg)
    return out


def _make_args(cpg_file: Path, **overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "cpg_file": cpg_file,
        "kind": None,
        "source": None,
        "target": None,
        "as_json": False,
        "limit": 50,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestEdgesCommand:
    def test_edges_all(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file)
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Kind" in out  # header

    def test_edges_kind_filter(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, kind=["contains"])
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        if "No matching" not in out:
            # Every data row should have "contains" in the kind column
            lines = [
                line for line in out.strip().split("\n")
                if line and not line.startswith("-")
            ]
            for line in lines[1:]:  # skip header
                assert "contains" in line.lower()

    def test_edges_kind_invalid(
        self, cpg_file: Path, cfg: Config,
    ) -> None:
        args = _make_args(cpg_file, kind=["nonexistent_kind"])
        with pytest.raises(SystemExit) as exc:
            run_cmd(args, cfg)
        assert exc.value.code == 1

    def test_edges_json_output(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, as_json=True, kind=["contains"])
        rc = run_cmd(args, cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        for item in data:
            assert item["kind"] == "contains"
            assert "source" in item
            assert "target" in item

    def test_edges_json_structure(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, as_json=True, limit=5)
        rc = run_cmd(args, cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "kind" in item
            assert "source" in item
            assert "target" in item
            assert "name" in item["source"]
            assert "kind" in item["source"]

    def test_edges_source_filter(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, as_json=True, source=".*")
        rc = run_cmd(args, cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)

    def test_edges_source_invalid_regex(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, source="[invalid")
        rc = run_cmd(args, cfg)
        assert rc == 1

    def test_edges_target_invalid_regex(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, target="[invalid")
        rc = run_cmd(args, cfg)
        assert rc == 1

    def test_edges_limit(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, limit=3)
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        if "No matching" not in out:
            # At most 3 data rows + header + separator
            lines = [
                line for line in out.strip().split("\n")
                if line and not line.startswith("-")
            ]
            assert len(lines) <= 4  # header + up to 3 data rows

    def test_edges_missing_file(self, tmp_path: Path, cfg: Config) -> None:
        args = _make_args(tmp_path / "nope.json")
        rc = run_cmd(args, cfg)
        assert rc == 1

    def test_edges_no_results(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Filter for a non-existent source to get no results
        args = _make_args(cpg_file, source="zzz_no_such_node_zzz")
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "No matching" in out
