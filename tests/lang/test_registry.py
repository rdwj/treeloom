"""Tests for LanguageRegistry."""

from __future__ import annotations

from treeloom.lang.builtin.python import PythonVisitor
from treeloom.lang.registry import LanguageRegistry


class TestRegister:
    def test_register_and_lookup_by_extension(self):
        registry = LanguageRegistry()
        visitor = PythonVisitor()
        registry.register(visitor)

        assert registry.get_visitor(".py") is visitor
        assert registry.get_visitor(".pyi") is visitor
        assert registry.get_visitor(".js") is None

    def test_register_and_lookup_by_name(self):
        registry = LanguageRegistry()
        visitor = PythonVisitor()
        registry.register(visitor)

        assert registry.get_visitor_by_name("python") is visitor
        assert registry.get_visitor_by_name("javascript") is None

    def test_supported_extensions(self):
        registry = LanguageRegistry()
        registry.register(PythonVisitor())

        exts = registry.supported_extensions()
        assert ".py" in exts
        assert ".pyi" in exts


class TestDefault:
    def test_default_includes_python(self):
        registry = LanguageRegistry.default()
        visitor = registry.get_visitor(".py")
        assert visitor is not None
        assert visitor.name == "python"

    def test_default_supported_extensions(self):
        registry = LanguageRegistry.default()
        exts = registry.supported_extensions()
        assert ".py" in exts
