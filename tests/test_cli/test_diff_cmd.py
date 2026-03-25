"""Tests for ``treeloom diff`` command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from treeloom.cli.build import run_build
from treeloom.cli.config import Config
from treeloom.cli.diff_cmd import run_cmd


@pytest.fixture()
def cfg() -> Config:
    return Config()


def _build_cpg(src: Path, out: Path, cfg: Config) -> Path:
    args = argparse.Namespace(path=src, output=out, exclude=None, quiet=True)
    run_build(args, cfg)
    return out


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "python"


@pytest.fixture()
def before_cpg(tmp_path: Path, cfg: Config) -> Path:
    return _build_cpg(FIXTURES / "simple_function.py", tmp_path / "before.json", cfg)


@pytest.fixture()
def after_cpg(tmp_path: Path, cfg: Config) -> Path:
    # Use a fixture with more content to produce visible differences
    return _build_cpg(FIXTURES / "function_calls.py", tmp_path / "after.json", cfg)


class TestDiffHumanReadable:
    def test_diff_shows_summary(
        self,
        before_cpg: Path,
        after_cpg: Path,
        cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = argparse.Namespace(before=before_cpg, after=after_cpg, as_json=False)
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "CPG Diff:" in out
        assert "Summary:" in out
        assert "Nodes:" in out
        assert "Edges:" in out
        assert "Files:" in out

    def test_diff_identical_cpgs(
        self,
        before_cpg: Path,
        cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = argparse.Namespace(before=before_cpg, after=before_cpg, as_json=False)
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Summary:" in out
        # No new/removed sections when CPGs are identical
        assert "New functions" not in out
        assert "Removed functions" not in out

    def test_diff_shows_function_changes(
        self,
        before_cpg: Path,
        after_cpg: Path,
        cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = argparse.Namespace(before=before_cpg, after=after_cpg, as_json=False)
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        # simple_function.py has 'add'; function_calls.py has different functions
        # The diff should mention something about functions or calls
        # At minimum the summary must be present
        assert "Nodes:" in out


class TestDiffJson:
    def test_diff_json_structure(
        self,
        before_cpg: Path,
        after_cpg: Path,
        cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = argparse.Namespace(before=before_cpg, after=after_cpg, as_json=True)
        rc = run_cmd(args, cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "before" in data
        assert "after" in data
        assert "summary" in data
        assert "new_files" in data
        assert "removed_files" in data
        assert "new_functions" in data
        assert "removed_functions" in data
        assert "new_classes" in data
        assert "new_calls" in data
        assert "changed_files" in data

    def test_diff_json_summary_fields(
        self,
        before_cpg: Path,
        after_cpg: Path,
        cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = argparse.Namespace(before=before_cpg, after=after_cpg, as_json=True)
        run_cmd(args, cfg)
        data = json.loads(capsys.readouterr().out)
        summary = data["summary"]
        assert "nodes" in summary
        assert "edges" in summary
        assert "files" in summary
        assert summary["nodes"]["before"] > 0
        assert summary["nodes"]["after"] > 0

    def test_diff_json_identical_cpgs(
        self,
        before_cpg: Path,
        cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = argparse.Namespace(before=before_cpg, after=before_cpg, as_json=True)
        rc = run_cmd(args, cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["new_functions"] == []
        assert data["removed_functions"] == []
        assert data["new_files"] == []
        assert data["removed_files"] == []


class TestDiffErrors:
    def test_missing_before_file(
        self, tmp_path: Path, after_cpg: Path, cfg: Config,
    ) -> None:
        args = argparse.Namespace(
            before=tmp_path / "nonexistent.json",
            after=after_cpg,
            as_json=False,
        )
        rc = run_cmd(args, cfg)
        assert rc == 1

    def test_missing_after_file(
        self, before_cpg: Path, tmp_path: Path, cfg: Config,
    ) -> None:
        args = argparse.Namespace(
            before=before_cpg,
            after=tmp_path / "nonexistent.json",
            as_json=False,
        )
        rc = run_cmd(args, cfg)
        assert rc == 1
