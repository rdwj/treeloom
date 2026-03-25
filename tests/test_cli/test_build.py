"""Tests for ``treeloom build`` command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from treeloom.cli.build import run_build
from treeloom.cli.config import Config
from treeloom.export.json import from_json


@pytest.fixture()
def fixture_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "python"


@pytest.fixture()
def default_cfg() -> Config:
    return Config()


class TestBuild:
    def test_build_single_file(
        self, fixture_dir: Path, tmp_path: Path, default_cfg: Config
    ) -> None:
        out = tmp_path / "out.json"
        args = argparse.Namespace(
            path=fixture_dir / "simple_function.py",
            output=out,
            exclude=None,
            quiet=False,
        )
        rc = run_build(args, default_cfg)
        assert rc == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) > 0

    def test_build_directory(self, fixture_dir: Path, tmp_path: Path, default_cfg: Config) -> None:
        out = tmp_path / "out.json"
        args = argparse.Namespace(
            path=fixture_dir,
            output=out,
            exclude=None,
            quiet=False,
        )
        rc = run_build(args, default_cfg)
        assert rc == 0
        data = json.loads(out.read_text())
        assert len(data["nodes"]) > 0

    def test_build_roundtrip(self, fixture_dir: Path, tmp_path: Path, default_cfg: Config) -> None:
        out = tmp_path / "out.json"
        args = argparse.Namespace(
            path=fixture_dir / "simple_function.py",
            output=out,
            exclude=None,
            quiet=True,
        )
        run_build(args, default_cfg)
        cpg = from_json(out.read_text())
        assert cpg.node_count > 0

    def test_build_quiet_suppresses_output(
        self,
        fixture_dir: Path,
        tmp_path: Path,
        default_cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        out = tmp_path / "out.json"
        args = argparse.Namespace(
            path=fixture_dir / "simple_function.py",
            output=out,
            exclude=None,
            quiet=True,
        )
        run_build(args, default_cfg)
        captured = capsys.readouterr()
        assert "Built CPG" not in captured.err

    def test_build_nonexistent_path(self, tmp_path: Path, default_cfg: Config) -> None:
        args = argparse.Namespace(
            path=tmp_path / "does_not_exist",
            output=tmp_path / "out.json",
            exclude=None,
            quiet=False,
        )
        rc = run_build(args, default_cfg)
        assert rc == 1

    def test_build_with_exclude(
        self, fixture_dir: Path, tmp_path: Path, default_cfg: Config
    ) -> None:
        out = tmp_path / "out.json"
        args = argparse.Namespace(
            path=fixture_dir,
            output=out,
            exclude=["**/data_flow*"],
            quiet=True,
            progress=False,
        )
        run_build(args, default_cfg)
        data = json.loads(out.read_text())
        # data_flow.py should be excluded -- no nodes referencing it
        files_in_cpg = {
            n.get("location", {}).get("file", "")
            for n in data["nodes"]
            if n.get("location")
        }
        assert not any("data_flow" in f for f in files_in_cpg)

    def test_progress_prints_to_stderr(
        self,
        fixture_dir: Path,
        tmp_path: Path,
        default_cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        out = tmp_path / "out.json"
        args = argparse.Namespace(
            path=fixture_dir,
            output=out,
            exclude=None,
            quiet=True,
            progress=True,
        )
        rc = run_build(args, default_cfg)
        assert rc == 0
        captured = capsys.readouterr()
        # Should have at least one progress line with the expected format
        assert "[1/" in captured.err
        assert "Parsing" in captured.err

    def test_progress_correct_count(
        self,
        fixture_dir: Path,
        tmp_path: Path,
        default_cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Progress lines should be numbered 1..N where N is the total file count."""
        out = tmp_path / "out.json"
        args = argparse.Namespace(
            path=fixture_dir,
            output=out,
            exclude=None,
            quiet=True,
            progress=True,
        )
        run_build(args, default_cfg)
        captured = capsys.readouterr()
        lines = [ln for ln in captured.err.splitlines() if "Parsing" in ln]
        assert len(lines) > 0
        # Each line should start with [i/N]
        import re
        pattern = re.compile(r"^\[(\d+)/(\d+)\] Parsing")
        for line in lines:
            assert pattern.match(line), f"Unexpected format: {line!r}"
        # The total N should be consistent
        totals = {pattern.match(ln).group(2) for ln in lines}  # type: ignore[union-attr]
        assert len(totals) == 1

    def test_progress_same_cpg_as_without(
        self,
        fixture_dir: Path,
        tmp_path: Path,
        default_cfg: Config,
    ) -> None:
        """--progress should produce the same CPG as without it."""
        out_prog = tmp_path / "with_progress.json"
        out_noprog = tmp_path / "without_progress.json"

        for out, prog in [(out_prog, True), (out_noprog, False)]:
            args = argparse.Namespace(
                path=fixture_dir / "simple_function.py",
                output=out,
                exclude=None,
                quiet=True,
                progress=prog,
            )
            rc = run_build(args, default_cfg)
            assert rc == 0

        data_prog = json.loads(out_prog.read_text())
        data_noprog = json.loads(out_noprog.read_text())
        assert len(data_prog["nodes"]) == len(data_noprog["nodes"])
        assert len(data_prog["edges"]) == len(data_noprog["edges"])
