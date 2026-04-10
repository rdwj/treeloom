"""Base class with shared logic for language visitor implementations."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import tree_sitter

from treeloom.model.location import SourceLocation

# Mapping from language name to its grammar package and function.
# Each entry is (package_name, import_path).
_GRAMMAR_PACKAGES: dict[str, str] = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "go": "tree_sitter_go",
    "java": "tree_sitter_java",
    "c": "tree_sitter_c",
    "cpp": "tree_sitter_cpp",
    "rust": "tree_sitter_rust",
}


class TreeSitterVisitor:
    """Common tree-sitter plumbing that language-specific visitors inherit.

    Subclasses set ``_language_name`` and implement ``visit`` and ``resolve_calls``.
    """

    _language_name: str = ""
    _parser: tree_sitter.Parser | None = None

    def parse(self, source: bytes, filename: str) -> Any:
        """Parse source bytes using the language-specific grammar.

        Returns a ``tree_sitter.Tree`` object.
        """
        parser = self._get_parser()
        return parser.parse(source)

    def _get_parser(self) -> tree_sitter.Parser:
        """Lazily create and cache a parser for this language."""
        if self._parser is not None:
            return self._parser

        package_name = _GRAMMAR_PACKAGES.get(self._language_name)
        if package_name is None:
            raise ImportError(
                f"No known grammar package for language '{self._language_name}'. "
                f"Supported: {', '.join(sorted(_GRAMMAR_PACKAGES))}"
            )

        try:
            mod = importlib.import_module(package_name)
        except ImportError as exc:
            raise ImportError(
                f"tree-sitter-{self._language_name} is required. "
                f"Install with: pip install treeloom[languages]"
            ) from exc

        language_func = getattr(mod, "language", None)
        if language_func is None:
            raise ImportError(
                f"Grammar package '{package_name}' has no language() function"
            )

        lang = tree_sitter.Language(language_func())
        self._parser = tree_sitter.Parser(lang)
        return self._parser

    def _node_text(self, node: tree_sitter.Node, source: bytes) -> str:
        """Extract the source text for a tree-sitter node."""
        return node.text.decode("utf-8", errors="replace")

    def _location(self, node: tree_sitter.Node, file_path: Path) -> SourceLocation:
        """Convert a tree-sitter node position to a SourceLocation.

        tree-sitter rows are 0-based; treeloom lines are 1-based.
        """
        return SourceLocation(
            file=file_path,
            line=node.start_point.row + 1,
            column=node.start_point.column,
        )

    def _end_location(self, node: tree_sitter.Node, file_path: Path) -> SourceLocation:
        """Convert a tree-sitter node end position to a SourceLocation.

        tree-sitter rows are 0-based; treeloom lines are 1-based.
        """
        return SourceLocation(
            file=file_path,
            line=node.end_point.row + 1,
            column=node.end_point.column,
        )
