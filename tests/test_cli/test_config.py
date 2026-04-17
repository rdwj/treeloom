"""Tests for ``treeloom config`` command."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
import yaml

from treeloom.cli.config import Config, load_config, run_config


@pytest.fixture()
def default_cfg() -> Config:
    return Config()


class TestConfigDefaults:
    def test_default_values(self) -> None:
        cfg = Config()
        assert cfg.query_limit == 0
        assert cfg.default_build_output == "cpg.json"
        assert "**/__pycache__" in cfg.exclude_patterns

    def test_load_config_no_files(self, tmp_path: Path) -> None:
        # Point to a directory with no config files
        cfg = load_config(tmp_path)
        assert cfg.query_limit == 0


class TestConfigInit:
    def test_init_creates_file(
        self,
        tmp_path: Path,
        default_cfg: Config,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # Simulate a real project root so no --force is needed.
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        args = argparse.Namespace(
            init=True, set=None, unset=None, use_global=False, show=False, force=False,
        )
        rc = run_config(args, default_cfg)
        assert rc == 0
        created = tmp_path / ".treeloom.yaml"
        assert created.exists()
        data = yaml.safe_load(created.read_text())
        assert "query_limit" in data

    def test_init_refuses_overwrite(
        self,
        tmp_path: Path,
        default_cfg: Config,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".treeloom.yaml").write_text("existing: true\n")
        args = argparse.Namespace(
            init=True, set=None, unset=None, use_global=False, show=False, force=False,
        )
        rc = run_config(args, default_cfg)
        assert rc == 1

    def test_init_aborts_without_force_in_non_project_dir(
        self,
        tmp_path: Path,
        default_cfg: Config,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # tmp_path has no project markers (.git, pyproject.toml, etc.)
        args = argparse.Namespace(
            init=True, set=None, unset=None, use_global=False, show=False, force=False,
        )
        rc = run_config(args, default_cfg)
        assert rc == 1
        assert not (tmp_path / ".treeloom.yaml").exists()

    def test_init_force_succeeds_in_non_project_dir(
        self,
        tmp_path: Path,
        default_cfg: Config,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # tmp_path has no project markers, but --force overrides the check.
        args = argparse.Namespace(
            init=True, set=None, unset=None, use_global=False, show=False, force=True,
        )
        rc = run_config(args, default_cfg)
        assert rc == 0
        created = tmp_path / ".treeloom.yaml"
        assert created.exists()
        data = yaml.safe_load(created.read_text())
        assert "query_limit" in data


class TestConfigShow:
    def test_show_prints_yaml(
        self, default_cfg: Config, capsys: pytest.CaptureFixture[str],
    ) -> None:
        args = argparse.Namespace(
            init=False, set=None, unset=None, use_global=False, show=False,
        )
        rc = run_config(args, default_cfg)
        assert rc == 0
        out = capsys.readouterr().out
        assert "query_limit" in out


class TestLoadConfigMerge:
    def test_project_config_overrides_defaults(self, tmp_path: Path) -> None:
        project_cfg = tmp_path / ".treeloom.yaml"
        project_cfg.write_text("query_limit: 100\n")
        cfg = load_config(tmp_path)
        assert cfg.query_limit == 100
