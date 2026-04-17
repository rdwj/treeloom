"""Configuration loading and management for the treeloom CLI."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from treeloom.cli._util import err

_USER_CONFIG_DIR = Path.home() / ".config" / "treeloom"
_USER_CONFIG_PATH = _USER_CONFIG_DIR / "config.yaml"
_PROJECT_CONFIG_NAME = ".treeloom.yaml"


@dataclass
class Config:
    """Effective CLI configuration, merged from defaults + user + project."""

    exclude_patterns: list[str] = field(default_factory=lambda: [
        "**/__pycache__", "**/node_modules", "**/.git", "**/venv", "**/.venv",
    ])
    default_build_output: str = "cpg.json"
    default_viz_output: str = "cpg.html"
    default_dot_output: str | None = None
    default_policy: str | None = None
    query_limit: int = 0


def _find_project_config(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default cwd) looking for .treeloom.yaml."""
    cur = (start or Path.cwd()).resolve()
    for directory in [cur, *cur.parents]:
        candidate = directory / _PROJECT_CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def _load_yaml_file(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge: overlay values win."""
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], list) and isinstance(value, list):
            merged[key] = value  # replace, don't extend
        else:
            merged[key] = value
    return merged


def load_config(project_dir: Path | None = None) -> Config:
    """Build a Config by merging defaults < user config < project config."""
    cfg = Config()
    base = {f.name: getattr(cfg, f.name) for f in fields(cfg)}

    if _USER_CONFIG_PATH.is_file():
        base = _merge(base, _load_yaml_file(_USER_CONFIG_PATH))

    project_path = _find_project_config(project_dir)
    if project_path is not None:
        base = _merge(base, _load_yaml_file(project_path))

    valid_keys = {f.name for f in fields(Config)}
    filtered = {k: v for k, v in base.items() if k in valid_keys}
    return Config(**filtered)


def _config_to_yaml(cfg: Config) -> str:
    """Render a Config as YAML text."""
    try:
        import yaml
    except ImportError:
        # Fallback: manual YAML
        lines: list[str] = []
        for f in fields(cfg):
            val = getattr(cfg, f.name)
            if isinstance(val, list):
                lines.append(f"{f.name}:")
                for item in val:
                    lines.append(f"  - {item!r}")
            elif val is None:
                lines.append(f"{f.name}: null")
            else:
                lines.append(f"{f.name}: {val!r}")
        return "\n".join(lines) + "\n"
    data = {f.name: getattr(cfg, f.name) for f in fields(cfg)}
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    try:
        import yaml
    except ImportError:
        err("pyyaml is required for config file operations")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")


# -- CLI command --------------------------------------------------------------


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("config", help="View or modify configuration")
    p.add_argument("--show", action="store_true", default=False, help="Display effective config")
    p.add_argument("--init", action="store_true", help="Create .treeloom.yaml in cwd")
    p.add_argument(
        "--force", "-f", action="store_true", default=False,
        help="Override project-root check when using --init",
    )
    p.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="Set a config key")
    p.add_argument("--unset", metavar="KEY", help="Remove a config key")
    p.add_argument(
        "--global", dest="use_global", action="store_true", help="Operate on user config",
    )
    p.set_defaults(func=run_config)


def run_config(args: argparse.Namespace, cfg: Config) -> int:
    if args.init:
        dest = Path.cwd() / _PROJECT_CONFIG_NAME
        if dest.exists():
            err(f"{dest} already exists")
            return 1
        _project_markers = (
            ".git", "pyproject.toml", "setup.py", "Cargo.toml",
            "go.mod", "pom.xml", "package.json",
        )
        if not any((Path.cwd() / marker).exists() for marker in _project_markers):
            if not args.force:
                err(
                    f"{Path.cwd()} does not appear to be a project root"
                    " (no .git, pyproject.toml, etc.)."
                    " Use --force to create the file anyway."
                )
                return 1
            err(
                f"Warning: {Path.cwd()} does not appear to be a project root"
                " (no .git, pyproject.toml, etc.) — proceeding anyway"
            )
        _write_yaml(dest, {f.name: getattr(cfg, f.name) for f in fields(Config)})
        err(f"Created {dest.resolve()}")
        return 0

    if args.set:
        key, raw_value = args.set
        valid_keys = {f.name for f in fields(Config)}
        if key not in valid_keys:
            err(f"Unknown config key: {key}. Valid keys: {', '.join(sorted(valid_keys))}")
            return 1
        # Coerce value
        value: Any = raw_value
        if raw_value.isdigit():
            value = int(raw_value)
        elif raw_value.lower() in ("null", "none"):
            value = None
        target = _USER_CONFIG_PATH if args.use_global else (
            _find_project_config() or Path.cwd() / _PROJECT_CONFIG_NAME
        )
        existing = _load_yaml_file(target) if target.is_file() else {}
        existing[key] = value
        _write_yaml(target, existing)
        err(f"Set {key}={value!r} in {target}")
        return 0

    if args.unset:
        valid_keys = {f.name for f in fields(Config)}
        if args.unset not in valid_keys:
            err(f"Unknown config key: {args.unset}. Valid keys: {', '.join(sorted(valid_keys))}")
            return 1
        target = _USER_CONFIG_PATH if args.use_global else _find_project_config()
        if target is None or not target.is_file():
            err("No config file found")
            return 1
        existing = _load_yaml_file(target)
        existing.pop(args.unset, None)
        _write_yaml(target, existing)
        err(f"Removed {args.unset} from {target}")
        return 0

    # Default: show effective config
    sys.stdout.write(_config_to_yaml(cfg))
    return 0
