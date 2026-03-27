"""Registry mapping short model names to their YAML file paths."""

from __future__ import annotations

from pathlib import Path

_BUILTIN_DIR = Path(__file__).parent / "builtin"

BUILTIN_MODELS: dict[str, Path] = (
    {p.stem: p for p in _BUILTIN_DIR.glob("*.yaml")} if _BUILTIN_DIR.is_dir() else {}
)
