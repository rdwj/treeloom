"""Tests for TreeSitterVisitor base class."""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.lang.base import TreeSitterVisitor
from treeloom.model.location import SourceLocation


class TestParse:
    def test_parse_returns_tree(self):
        visitor = TreeSitterVisitor()
        visitor._language_name = "python"
        tree = visitor.parse(b"x = 1", "test.py")
        assert tree.root_node is not None
        assert tree.root_node.type == "module"

    def test_parse_caches_parser(self):
        visitor = TreeSitterVisitor()
        visitor._language_name = "python"
        visitor.parse(b"x = 1", "a.py")
        parser1 = visitor._parser
        visitor.parse(b"y = 2", "b.py")
        parser2 = visitor._parser
        assert parser1 is parser2

    def test_parse_unknown_language_raises(self):
        visitor = TreeSitterVisitor()
        visitor._language_name = "brainfuck"
        with pytest.raises(ImportError, match="No known grammar package"):
            visitor.parse(b"+++", "test.bf")

    def test_parse_missing_grammar_raises(self):
        visitor = TreeSitterVisitor()
        visitor._language_name = "rust"  # grammar likely not installed in test env
        try:
            visitor.parse(b"fn main() {}", "test.rs")
        except ImportError as exc:
            assert "tree-sitter-rust is required" in str(exc)


class TestNodeText:
    def test_extracts_text(self):
        visitor = TreeSitterVisitor()
        visitor._language_name = "python"
        tree = visitor.parse(b"foo = 42", "test.py")
        root = tree.root_node
        text = visitor._node_text(root, b"foo = 42")
        assert text == "foo = 42"


class TestLocation:
    def test_location_converts_0_based_to_1_based(self):
        visitor = TreeSitterVisitor()
        visitor._language_name = "python"
        tree = visitor.parse(b"x = 1\ny = 2", "test.py")
        # Second statement is at row 1 (0-based) = line 2 (1-based)
        second_stmt = tree.root_node.children[1]
        loc = visitor._location(second_stmt, Path("test.py"))
        assert loc == SourceLocation(file=Path("test.py"), line=2, column=0)

    def test_location_column(self):
        visitor = TreeSitterVisitor()
        visitor._language_name = "python"
        tree = visitor.parse(b"if True:\n    x = 1", "test.py")
        block = tree.root_node.children[0]  # if_statement
        body = block.child_by_field_name("consequence")
        stmt = body.children[0]  # expression_statement at col 4
        loc = visitor._location(stmt, Path("test.py"))
        assert loc.column == 4
        assert loc.line == 2
