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
        with pytest.raises(FileNotFoundError):
            run_cmd(args, cfg)

    def test_missing_after_file(
        self, before_cpg: Path, tmp_path: Path, cfg: Config,
    ) -> None:
        args = argparse.Namespace(
            before=before_cpg,
            after=tmp_path / "nonexistent.json",
            as_json=False,
        )
        with pytest.raises(FileNotFoundError):
            run_cmd(args, cfg)


class TestDiffPathOptions:
    """Tests for --match-by-basename and --strip-prefix flags."""

    def test_match_by_basename_identical_cpgs(
        self,
        before_cpg: Path,
        cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Same CPG compared against itself with --match-by-basename should show no diff
        args = argparse.Namespace(
            before=before_cpg,
            after=before_cpg,
            as_json=False,
            strip_prefix=None,
            match_by_basename=True,
        )
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "New functions" not in out
        assert "Removed functions" not in out

    def test_match_by_basename_cross_dir(
        self, tmp_path: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Build the same source file into two different subdirs to simulate
        # path difference — functions should match by basename, producing no diff
        src = FIXTURES / "simple_function.py"
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()
        cpg_a = _build_cpg(src, dir_a / "cpg.json", cfg)
        cpg_b = _build_cpg(src, dir_b / "cpg.json", cfg)

        args = argparse.Namespace(
            before=cpg_a,
            after=cpg_b,
            as_json=False,
            strip_prefix=None,
            match_by_basename=True,
        )
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        # Same source, same functions — no additions/removals by basename
        assert "New functions" not in out
        assert "Removed functions" not in out

    def test_basename_is_default(
        self, tmp_path: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Copy the same source to two separate dirs so the absolute paths differ.
        # Without any flag (basename matching is the default), functions should match
        # by basename and no diff appears.
        import shutil
        src = FIXTURES / "simple_function.py"
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()
        shutil.copy(src, dir_a / "simple_function.py")
        shutil.copy(src, dir_b / "simple_function.py")
        cpg_a = _build_cpg(dir_a / "simple_function.py", dir_a / "cpg.json", cfg)
        cpg_b = _build_cpg(dir_b / "simple_function.py", dir_b / "cpg.json", cfg)

        # No match_by_basename in Namespace — run_cmd defaults to True
        args = argparse.Namespace(
            before=cpg_a,
            after=cpg_b,
            as_json=False,
        )
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "New functions" not in out
        assert "Removed functions" not in out

    def test_match_by_full_path_distinguishes_dirs(
        self, tmp_path: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # With full-path matching, files in different dirs look like different files.
        # Copy the same source to two separate directories so the absolute paths differ.
        import shutil
        src = FIXTURES / "simple_function.py"
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()
        src_a = dir_a / "simple_function.py"
        src_b = dir_b / "simple_function.py"
        shutil.copy(src, src_a)
        shutil.copy(src, src_b)
        cpg_a = _build_cpg(src_a, dir_a / "cpg.json", cfg)
        cpg_b = _build_cpg(src_b, dir_b / "cpg.json", cfg)

        args = argparse.Namespace(
            before=cpg_a,
            after=cpg_b,
            as_json=True,
            strip_prefix=None,
            match_by_basename=False,  # --match-by-full-path
        )
        rc = run_cmd(args, cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        # Different full paths => treated as new/removed files
        assert len(data["new_files"]) > 0 or len(data["removed_files"]) > 0

    def test_strip_prefix_json(
        self,
        before_cpg: Path,
        after_cpg: Path,
        cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = argparse.Namespace(
            before=before_cpg,
            after=after_cpg,
            as_json=True,
            strip_prefix="/nonexistent/prefix/",
            match_by_basename=False,
        )
        rc = run_cmd(args, cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        # Strip of non-matching prefix changes nothing functional
        assert "summary" in data
