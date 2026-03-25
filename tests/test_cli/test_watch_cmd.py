"""Tests for ``treeloom watch`` command."""

from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

import pytest

from treeloom.cli.watch_cmd import _detect_changes, _scan_mtimes, run_cmd

# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestScanMtimes:
    def test_returns_files_with_mtimes(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1")
        (tmp_path / "b.py").write_text("y = 2")
        result = _scan_mtimes(tmp_path, tmp_path, [])
        assert len(result) == 2
        for path, mtime in result.items():
            assert isinstance(mtime, float)
            assert mtime > 0

    def test_excludes_matching_patterns(self, tmp_path: Path) -> None:
        (tmp_path / "keep.py").write_text("x = 1")
        skip_dir = tmp_path / "__pycache__"
        skip_dir.mkdir()
        (skip_dir / "cached.pyc").write_text("junk")
        result = _scan_mtimes(tmp_path, tmp_path, ["**/__pycache__"])
        paths = list(result.keys())
        assert all("__pycache__" not in str(p) for p in paths)
        assert any("keep.py" in str(p) for p in paths)

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = _scan_mtimes(tmp_path, tmp_path, [])
        assert result == {}

    def test_nested_files_included(self, tmp_path: Path) -> None:
        sub = tmp_path / "pkg"
        sub.mkdir()
        (sub / "mod.py").write_text("pass")
        result = _scan_mtimes(tmp_path, tmp_path, [])
        assert any("mod.py" in str(p) for p in result)


class TestDetectChanges:
    def test_no_changes(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_text("x = 1")
        snap = {f: f.stat().st_mtime}
        assert _detect_changes(snap, snap.copy()) == []

    def test_new_file_detected(self, tmp_path: Path) -> None:
        old: dict[Path, float] = {}
        new_file = tmp_path / "new.py"
        new_file.write_text("x = 1")
        new = {new_file: new_file.stat().st_mtime}
        changed = _detect_changes(old, new)
        assert new_file in changed

    def test_modified_file_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_text("x = 1")
        old = {f: f.stat().st_mtime - 1.0}  # pretend it was older
        new = {f: f.stat().st_mtime}
        changed = _detect_changes(old, new)
        assert f in changed

    def test_deleted_file_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "gone.py"
        old = {f: 1234567890.0}
        new: dict[Path, float] = {}
        changed = _detect_changes(old, new)
        assert f in changed

    def test_multiple_changes(self, tmp_path: Path) -> None:
        existing = tmp_path / "existing.py"
        existing.write_text("pass")
        new_file = tmp_path / "added.py"
        new_file.write_text("x = 1")
        deleted = tmp_path / "deleted.py"

        old = {existing: existing.stat().st_mtime - 1.0, deleted: 1234567890.0}
        new = {existing: existing.stat().st_mtime, new_file: new_file.stat().st_mtime}

        changed = _detect_changes(old, new)
        assert existing in changed
        assert new_file in changed
        assert deleted in changed


# ---------------------------------------------------------------------------
# run_cmd tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def src_dir(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("def foo(): pass\n")
    return src


class TestRunCmd:
    def test_nonexistent_path_returns_1(self, tmp_path: Path) -> None:
        args = argparse.Namespace(
            path=tmp_path / "no_such_dir",
            output=tmp_path / "cpg.json",
            interval=0.1,
            exclude=[],
            quiet=True,
        )
        assert run_cmd(args) == 1

    def test_file_path_not_dir_returns_1(self, tmp_path: Path) -> None:
        f = tmp_path / "file.py"
        f.write_text("x = 1")
        args = argparse.Namespace(
            path=f,
            output=tmp_path / "cpg.json",
            interval=0.1,
            exclude=[],
            quiet=True,
        )
        assert run_cmd(args) == 1

    def test_initial_build_creates_output(self, src_dir: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.json"
        args = argparse.Namespace(
            path=src_dir,
            output=out,
            interval=0.1,
            exclude=[],
            quiet=True,
        )

        result: list[int] = []

        def _run() -> None:
            result.append(run_cmd(args))

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        # Give the initial build time to complete
        t.join(timeout=5.0)

        # Thread is still running (blocked in sleep loop) — that's fine
        assert out.exists(), "Output file should be created by initial build"
        data = json.loads(out.read_text())
        assert "nodes" in data
        assert len(data["nodes"]) > 0

    def test_rebuild_on_change(self, src_dir: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.json"
        args = argparse.Namespace(
            path=src_dir,
            output=out,
            interval=0.1,
            exclude=[],
            quiet=True,
        )

        t = threading.Thread(target=run_cmd, args=(args,), daemon=True)
        t.start()

        # Wait for initial build
        deadline = time.time() + 5.0
        while not out.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert out.exists(), "Initial build did not produce output in time"

        initial_text = out.read_text()

        # Modify the source file to add a new function
        (src_dir / "mod.py").write_text("def foo(): pass\ndef bar(): pass\n")

        old_data = json.loads(initial_text)
        old_node_count = len(old_data["nodes"])

        # Wait for the watch loop to detect the change, rebuild, and flush valid JSON
        new_data: dict = {}
        deadline = time.time() + 8.0
        while time.time() < deadline:
            time.sleep(0.05)
            try:
                candidate = json.loads(out.read_text())
                if len(candidate.get("nodes", [])) > old_node_count:
                    new_data = candidate
                    break
            except (json.JSONDecodeError, OSError):
                # File may be mid-write; retry
                continue

        assert new_data, (
            f"CPG was not rebuilt with more nodes within timeout "
            f"(old node count: {old_node_count})"
        )
