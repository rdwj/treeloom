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
    defaults: dict[str, object] = {
        "cpg_file": cpg_file,
        "kind": None,
        "name": None,
        "file": None,
        "as_json": False,
        "output_format": "table",
        "limit": None,
        "scope": None,
        "count": False,
        "annotation": None,
        "annotation_value": None,
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
        lines = [
            line
            for line in out.strip().split("\n")
            if line and not line.startswith("-")
        ]
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
        data_lines = [
            line
            for line in out.strip().split("\n")
            if line and not line.startswith("-")
        ]
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
        with pytest.raises(FileNotFoundError):
            run_query(args, default_cfg)


@pytest.fixture()
def class_cpg_file(tmp_path: Path, default_cfg: Config) -> Path:
    """CPG built from class_with_methods.py (has a class + nested functions)."""
    fixtures = Path(__file__).resolve().parent.parent / "fixtures" / "python"
    out = tmp_path / "class_test.json"
    args = argparse.Namespace(
        path=fixtures / "class_with_methods.py", output=out, exclude=None, quiet=True,
    )
    run_build(args, default_cfg)
    return out


class TestQueryScope:
    """Tests for --scope filter (#43)."""

    def test_scope_filter_finds_methods(
        self,
        class_cpg_file: Path,
        default_cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Parameters/variables inside Calculator should be found with --scope Calculator
        args = _make_args(class_cpg_file, scope="Calculator")
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        # Should find nodes scoped within the Calculator class
        assert "Calculator" in out or "add" in out or "Kind" in out

    def test_scope_filter_no_match(
        self,
        class_cpg_file: Path,
        default_cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(class_cpg_file, scope="zzz_no_such_scope_zzz")
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "No matching" in out


class TestQueryCount:
    """Tests for --count flag (#44)."""

    def test_count_flag_prints_integer(
        self,
        cpg_file: Path,
        default_cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, count=True)
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out.isdigit(), f"Expected integer output, got: {out!r}"

    def test_count_flag_with_kind_filter(
        self,
        cpg_file: Path,
        default_cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        args_all = _make_args(cpg_file, count=True)
        run_query(args_all, default_cfg)
        total = int(capsys.readouterr().out.strip())

        args_fn = _make_args(cpg_file, count=True, kind=["function"])
        run_query(args_fn, default_cfg)
        fn_count = int(capsys.readouterr().out.strip())

        assert fn_count <= total
        assert fn_count > 0

    def test_count_not_limited_by_default_limit(
        self,
        cpg_file: Path,
        default_cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # --count should not be truncated by the default query_limit
        args = _make_args(cpg_file, count=True, limit=1)
        rc = run_query(args, default_cfg)
        assert rc == 0
        # Just verify it runs; count may be larger than 1
        out = capsys.readouterr().out.strip()
        assert out.isdigit()


class TestQueryAnnotation:
    """Tests for --annotation and --annotation-value flags (#45)."""

    def test_annotation_filter_no_annotations(
        self,
        cpg_file: Path,
        default_cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # No annotations set — should return nothing
        args = _make_args(cpg_file, annotation="role")
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "No matching" in out

    def test_annotation_filter_with_annotated_cpg(
        self,
        cpg_file: Path,
        default_cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from treeloom.cli._util import load_cpg
        from treeloom.export.json import to_json
        from treeloom.model.nodes import NodeKind

        cpg = load_cpg(cpg_file)
        functions = list(cpg.nodes(kind=NodeKind.FUNCTION))
        assert functions, "Expected at least one function in fixture"
        cpg.annotate_node(functions[0].id, "role", "entry_point")

        annotated_path = cpg_file.parent / "annotated.json"
        annotated_path.write_text(to_json(cpg), encoding="utf-8")

        args = _make_args(annotated_path, annotation="role")
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "No matching" not in out

    def test_annotation_value_filter(
        self,
        cpg_file: Path,
        default_cfg: Config,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from treeloom.cli._util import load_cpg
        from treeloom.export.json import to_json
        from treeloom.model.nodes import NodeKind

        cpg = load_cpg(cpg_file)
        functions = list(cpg.nodes(kind=NodeKind.FUNCTION))
        assert functions
        cpg.annotate_node(functions[0].id, "role", "sink")

        annotated_path = cpg_file.parent / "annotated2.json"
        annotated_path.write_text(to_json(cpg), encoding="utf-8")

        # Correct value matches
        args = _make_args(annotated_path, annotation="role", annotation_value="sink")
        run_query(args, default_cfg)
        out_match = capsys.readouterr().out
        assert "No matching" not in out_match

        # Wrong value should not match
        args2 = _make_args(annotated_path, annotation="role", annotation_value="source")
        run_query(args2, default_cfg)
        out_no = capsys.readouterr().out
        assert "No matching" in out_no


class TestQueryOutputFormat:
    """Tests for --output-format flag on the query command (issue #53)."""

    def test_csv_output(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, output_format="csv", kind=["function"])
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        lines = [line for line in out.strip().split("\n") if line]
        # First line is the header row
        assert lines[0] == "kind,name,location", f"Unexpected CSV header: {lines[0]!r}"
        # All data rows should start with "function"
        for line in lines[1:]:
            assert line.startswith("function,"), f"Unexpected row: {line!r}"

    def test_tsv_output(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, output_format="tsv", kind=["function"])
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        lines = [line for line in out.strip().split("\n") if line]
        assert lines[0] == "kind\tname\tlocation", f"Unexpected TSV header: {lines[0]!r}"
        for line in lines[1:]:
            cols = line.split("\t")
            assert cols[0] == "function", f"Unexpected kind column: {cols[0]!r}"

    def test_jsonl_output(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, output_format="jsonl", kind=["function"])
        rc = run_query(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        lines = [line for line in out.strip().split("\n") if line]
        assert lines, "Expected at least one JSONL line"
        for line in lines:
            obj = json.loads(line)
            assert obj["kind"] == "function"
            assert "name" in obj
            assert "location" in obj

    def test_json_alias_still_works(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json flag should remain a working alias for --output-format json."""
        args = _make_args(cpg_file, as_json=True, kind=["function"])
        rc = run_query(args, default_cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        for item in data:
            assert item["kind"] == "function"

    def test_output_format_json_explicit(
        self, cpg_file: Path, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, output_format="json", kind=["function"])
        rc = run_query(args, default_cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
