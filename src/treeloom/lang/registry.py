"""Language registry: discover and manage language visitor plugins."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from treeloom.lang.protocol import LanguageVisitor

logger = logging.getLogger(__name__)


class LanguageRegistry:
    """Maps file extensions and language names to visitor instances."""

    def __init__(self) -> None:
        self._by_extension: dict[str, LanguageVisitor] = {}
        self._by_name: dict[str, LanguageVisitor] = {}

    def register(self, visitor: LanguageVisitor) -> None:
        """Register a visitor for its declared extensions and name."""
        self._by_name[visitor.name] = visitor
        for ext in visitor.extensions:
            self._by_extension[ext] = visitor

    def get_visitor(self, extension: str) -> LanguageVisitor | None:
        """Look up a visitor by file extension (e.g. '.py')."""
        return self._by_extension.get(extension)

    def get_visitor_by_name(self, name: str) -> LanguageVisitor | None:
        """Look up a visitor by language name (e.g. 'python')."""
        return self._by_name.get(name)

    def supported_extensions(self) -> frozenset[str]:
        """Return all registered file extensions."""
        return frozenset(self._by_extension.keys())

    @classmethod
    def default(cls) -> LanguageRegistry:
        """Create a registry with all built-in visitors whose grammars are installed.

        Visitors whose grammar packages are not available are silently skipped.
        """
        registry = cls()
        _register_builtins(registry)
        return registry


def _register_builtins(registry: LanguageRegistry) -> None:
    """Try to register each built-in visitor, skipping those without grammars."""
    # Import each built-in visitor class and try to instantiate it.
    # If the grammar package is missing the visitor's parse() will fail,
    # but we can still register it -- the error surfaces at parse time.
    # However, for default() we do a quick grammar probe so we only register
    # visitors whose grammars are actually importable.
    _try_register(registry, "treeloom.lang.builtin.python", "PythonVisitor", "tree_sitter_python")
    _try_register(
        registry, "treeloom.lang.builtin.javascript",
        "JavaScriptVisitor", "tree_sitter_javascript",
    )
    _try_register(registry, "treeloom.lang.builtin.java", "JavaVisitor", "tree_sitter_java")
    _try_register(registry, "treeloom.lang.builtin.go", "GoVisitor", "tree_sitter_go")
    _try_register(
        registry,
        "treeloom.lang.builtin.typescript",
        "TypeScriptVisitor",
        "tree_sitter_typescript",
    )
    _try_register(
        registry,
        "treeloom.lang.builtin.typescript",
        "TSXVisitor",
        "tree_sitter_typescript",
    )
    _try_register(registry, "treeloom.lang.builtin.cpp", "CppVisitor", "tree_sitter_cpp")
    _try_register(registry, "treeloom.lang.builtin.c", "CVisitor", "tree_sitter_c")
    _try_register(registry, "treeloom.lang.builtin.rust", "RustVisitor", "tree_sitter_rust")


def _try_register(
    registry: LanguageRegistry,
    module_path: str,
    class_name: str,
    grammar_package: str,
) -> None:
    """Attempt to import a grammar and register its visitor."""
    try:
        __import__(grammar_package)
    except ImportError:
        logger.debug(
            "Grammar %s not installed, skipping %s.%s",
            grammar_package,
            module_path,
            class_name,
        )
        return

    import importlib

    try:
        mod = importlib.import_module(module_path)
        visitor_cls = getattr(mod, class_name)
        registry.register(visitor_cls())
    except Exception:
        logger.debug(
            "Failed to register %s.%s", module_path, class_name, exc_info=True
        )
