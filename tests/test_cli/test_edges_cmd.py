"""Tests for ``treeloom edges`` command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from treeloom.cli.build import run_build
from treeloom.cli.config import Config
from treeloom.cli.edges_cmd import _loc_str, run_cmd
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind


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
        "output_format": "table",
        "limit": 0,
        "offset": 0,
        "count": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_node(
    node_id: str,
    location: SourceLocation | None,
    kind: NodeKind = NodeKind.FUNCTION,
) -> CpgNode:
    return CpgNode(id=NodeId(node_id), kind=kind, name="n", location=location)


class TestLocStr:
    """Unit tests for the _loc_str display helper."""

    def test_with_location(self) -> None:
        loc = SourceLocation(file=Path("src/foo.py"), line=42, column=0)
        node = _make_node("function:src/foo.py:42:0:17", loc)
        assert _loc_str(node) == "foo.py:42"

    def test_location_uses_basename(self) -> None:
        loc = SourceLocation(file=Path("a/b/c/bar.py"), line=7, column=3)
        node = _make_node("function:a/b/c/bar.py:7:3:1", loc)
        assert _loc_str(node) == "bar.py:7"

    def test_no_location_falls_back_to_id(self) -> None:
        # ID contains file/line info even when node.location is None
        node = _make_node("function:src/foo.py:42:0:17", location=None)
        assert _loc_str(node) == "foo.py:42"

    def test_no_location_no_id_info_returns_question_marks(self) -> None:
        # Synthetic node with no location; ID format is kind::::counter
        node = _make_node("function::::3", location=None)
        assert _loc_str(node) == "?:?"

    def test_unknown_object_without_location_returns_question_marks(self) -> None:
        # Arbitrary object with no location or id attributes at all
        assert _loc_str(object()) == "?:?"

    def test_id_fallback_uses_basename_only(self) -> None:
        # Deep path in ID; basename should be extracted
        node = _make_node("call:a/very/deep/path/mod.py:100:5:99", location=None)
        assert _loc_str(node) == "mod.py:100"


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


class TestEdgesUnlimitedDefault:
    """Tests for unlimited default and --offset (issue #98)."""

    def test_edges_no_limit_by_default(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Default limit=0 returns all edges (issue #98)."""
        args = _make_args(cpg_file, as_json=True, kind=["contains"])
        rc = run_cmd(args, cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        # With no limit, count should match --count output
        args_count = _make_args(cpg_file, count=True, kind=["contains"])
        run_cmd(args_count, cfg)
        count = int(capsys.readouterr().out.strip())
        assert len(data) == count

    def test_edges_offset(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--offset skips the first N results."""
        args_all = _make_args(cpg_file, as_json=True, kind=["contains"])
        run_cmd(args_all, cfg)
        all_data = json.loads(capsys.readouterr().out)

        args_offset = _make_args(cpg_file, as_json=True, kind=["contains"], offset=3)
        run_cmd(args_offset, cfg)
        offset_data = json.loads(capsys.readouterr().out)

        assert len(offset_data) == len(all_data) - 3
        # The offset results should match the tail of the full results
        assert offset_data[0] == all_data[3]

    def test_edges_offset_exceeds_total(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--offset larger than the result set returns empty output."""
        args = _make_args(cpg_file, as_json=True, kind=["contains"], offset=99999)
        rc = run_cmd(args, cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data == []


class TestEdgesCount:
    """Tests for --count flag on the edges command."""

    def test_count_all_edges(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, count=True)
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out.isdigit(), f"Expected a plain integer, got: {out!r}"
        assert int(out) > 0

    def test_count_with_kind_filter(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Count with filter should be <= total count
        args_all = _make_args(cpg_file, count=True)
        run_cmd(args_all, cfg)
        total = int(capsys.readouterr().out.strip())

        args_filtered = _make_args(cpg_file, count=True, kind=["contains"])
        rc = run_cmd(args_filtered, cfg)
        assert rc == 0
        filtered = int(capsys.readouterr().out.strip())
        assert filtered <= total

    def test_count_ignores_limit(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # --count should return the true total, not capped at --limit
        args_count = _make_args(cpg_file, count=True)
        run_cmd(args_count, cfg)
        full_count = int(capsys.readouterr().out.strip())

        args_limited = _make_args(cpg_file, count=True, limit=1)
        run_cmd(args_limited, cfg)
        count_with_limit = int(capsys.readouterr().out.strip())

        assert count_with_limit == full_count, (
            f"--count should ignore --limit: got {count_with_limit} with limit=1, "
            f"expected {full_count}"
        )

    def test_count_ignores_offset(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--count should return the true total, unaffected by --offset."""
        args_count = _make_args(cpg_file, count=True)
        run_cmd(args_count, cfg)
        full_count = int(capsys.readouterr().out.strip())

        args_offset = _make_args(cpg_file, count=True, offset=10)
        run_cmd(args_offset, cfg)
        count_with_offset = int(capsys.readouterr().out.strip())

        assert count_with_offset == full_count, (
            f"--count should ignore --offset: got {count_with_offset} with offset=10, "
            f"expected {full_count}"
        )


class TestEdgesOutputFormat:
    """Tests for --output-format flag on the edges command (issue #53)."""

    def test_csv_output(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, output_format="csv", kind=["contains"], limit=5)
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        lines = [line for line in out.strip().split("\n") if line]
        assert lines[0] == "kind,source,target", f"Unexpected CSV header: {lines[0]!r}"
        for line in lines[1:]:
            assert "contains" in line, f"Unexpected row: {line!r}"

    def test_tsv_output(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, output_format="tsv", kind=["contains"], limit=5)
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        lines = [line for line in out.strip().split("\n") if line]
        assert lines[0] == "kind\tsource\ttarget", f"Unexpected TSV header: {lines[0]!r}"
        for line in lines[1:]:
            cols = line.split("\t")
            assert cols[0] == "contains", f"Unexpected kind: {cols[0]!r}"

    def test_jsonl_output(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = _make_args(cpg_file, output_format="jsonl", kind=["contains"], limit=5)
        rc = run_cmd(args, cfg)
        assert rc == 0
        out = capsys.readouterr().out
        lines = [line for line in out.strip().split("\n") if line]
        assert lines, "Expected at least one JSONL line"
        for line in lines:
            obj = json.loads(line)
            assert obj["kind"] == "contains"
            assert "source" in obj
            assert "target" in obj

    def test_json_alias_still_works(
        self, cpg_file: Path, cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json flag should remain a working alias for --output-format json."""
        args = _make_args(cpg_file, as_json=True, kind=["contains"])
        rc = run_cmd(args, cfg)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        for item in data:
            assert item["kind"] == "contains"
