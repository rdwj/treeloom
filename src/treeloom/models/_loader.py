"""Load YAML model files and convert them to TaintPropagator objects."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import yaml

from treeloom.model.nodes import CpgNode


def load_model_file(path: Path) -> list:
    """Load a YAML model file and return a list of TaintPropagator objects.

    Args:
        path: Path to a YAML model file.

    Raises:
        ValueError: If the file has an unsupported schema_version or invalid structure.
        FileNotFoundError: If the path does not exist.
    """
    from treeloom.analysis.taint import TaintPropagator  # avoid circular import

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        msg = f"Model file {path} must contain a YAML mapping at the top level"
        raise ValueError(msg)

    version = data.get("schema_version", 1)
    if version != 1:
        msg = f"Unsupported schema_version {version} in {path}; only version 1 is supported"
        raise ValueError(msg)

    functions = data.get("functions", [])
    propagators: list[TaintPropagator] = []

    for func in functions:
        name: str = func["name"]
        aliases: list[str] = func.get("aliases", [])
        propagation: dict = func.get("propagation", {})

        match_names: frozenset[str] = frozenset([name, *aliases])
        matcher = _make_matcher(match_names)

        params_to_return = propagation.get("params_to_return")
        if params_to_return is not None:
            propagators.append(
                TaintPropagator(
                    match=matcher,
                    param_to_return=len(params_to_return) > 0,
                    params_to_return=list(params_to_return),
                )
            )
        else:
            propagators.append(
                TaintPropagator(
                    match=matcher,
                    param_to_return=True,
                )
            )

    return propagators


def _make_matcher(names: frozenset[str]) -> Callable[[CpgNode], bool]:
    """Create a matcher that checks if a node's name is in the given set."""

    def match(node: CpgNode) -> bool:
        return node.name in names

    return match
