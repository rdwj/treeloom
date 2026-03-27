"""Data flow propagation models for library/stdlib functions.

Models describe how data flows through functions whose source code is not
in the CPG — essentially pre-computed function summaries. Consumers load
models and pass them as ``propagators`` to ``TaintPolicy``.
"""

from __future__ import annotations

from treeloom.models._loader import load_model_file
from treeloom.models._registry import BUILTIN_MODELS

__all__ = ["list_builtin_models", "load_model_file", "load_models"]


def load_models(names: list[str]) -> list:
    """Load named built-in models and return a list of TaintPropagator objects.

    Args:
        names: Short names of built-in models (e.g. ``["python-stdlib"]``).

    Raises:
        ValueError: If a name is not a recognized built-in model.
    """
    from treeloom.analysis.taint import TaintPropagator  # avoid circular import

    propagators: list[TaintPropagator] = []
    for name in names:
        path = BUILTIN_MODELS.get(name)
        if path is None:
            valid = sorted(BUILTIN_MODELS.keys())
            msg = f"Unknown model {name!r}. Available: {', '.join(valid)}"
            raise ValueError(msg)
        propagators.extend(load_model_file(path))
    return propagators


def list_builtin_models() -> list[str]:
    """Return the names of available built-in models."""
    return sorted(BUILTIN_MODELS.keys())
