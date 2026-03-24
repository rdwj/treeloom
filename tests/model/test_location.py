"""Tests for SourceLocation and SourceRange."""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.model.location import SourceLocation, SourceRange


class TestSourceLocation:
    def test_creation(self):
        loc = SourceLocation(file=Path("foo.py"), line=10, column=5)
        assert loc.file == Path("foo.py")
        assert loc.line == 10
        assert loc.column == 5

    def test_default_column(self):
        loc = SourceLocation(file=Path("foo.py"), line=1)
        assert loc.column == 0

    def test_frozen(self):
        loc = SourceLocation(file=Path("foo.py"), line=1)
        with pytest.raises(AttributeError):
            loc.line = 2  # type: ignore[misc]

    def test_equality(self):
        a = SourceLocation(file=Path("foo.py"), line=1, column=0)
        b = SourceLocation(file=Path("foo.py"), line=1, column=0)
        assert a == b

    def test_inequality(self):
        a = SourceLocation(file=Path("foo.py"), line=1)
        b = SourceLocation(file=Path("foo.py"), line=2)
        assert a != b

    def test_hashable(self):
        a = SourceLocation(file=Path("foo.py"), line=1)
        b = SourceLocation(file=Path("foo.py"), line=1)
        assert hash(a) == hash(b)
        assert len({a, b}) == 1

    @pytest.mark.parametrize(
        "a, b, expected",
        [
            # Same file, different lines
            (
                SourceLocation(Path("a.py"), 1, 0),
                SourceLocation(Path("a.py"), 2, 0),
                True,
            ),
            # Same file and line, different columns
            (
                SourceLocation(Path("a.py"), 1, 0),
                SourceLocation(Path("a.py"), 1, 5),
                True,
            ),
            # Same location
            (
                SourceLocation(Path("a.py"), 1, 0),
                SourceLocation(Path("a.py"), 1, 0),
                False,
            ),
            # Different files (lexicographic)
            (
                SourceLocation(Path("a.py"), 10, 0),
                SourceLocation(Path("b.py"), 1, 0),
                True,
            ),
        ],
    )
    def test_ordering(self, a, b, expected):
        assert (a < b) is expected

    def test_le(self):
        a = SourceLocation(Path("a.py"), 1, 0)
        b = SourceLocation(Path("a.py"), 1, 0)
        c = SourceLocation(Path("a.py"), 2, 0)
        assert a <= b
        assert a <= c
        assert not c <= a


class TestSourceRange:
    def test_creation(self):
        start = SourceLocation(Path("foo.py"), 1, 0)
        end = SourceLocation(Path("foo.py"), 5, 10)
        r = SourceRange(start=start, end=end)
        assert r.start == start
        assert r.end == end

    @pytest.mark.parametrize(
        "loc, expected",
        [
            # Inside the range
            (SourceLocation(Path("foo.py"), 3, 5), True),
            # At start boundary
            (SourceLocation(Path("foo.py"), 1, 0), True),
            # At end boundary
            (SourceLocation(Path("foo.py"), 5, 10), True),
            # Before range
            (SourceLocation(Path("foo.py"), 0, 0), False),
            # After range
            (SourceLocation(Path("foo.py"), 6, 0), False),
            # Different file
            (SourceLocation(Path("bar.py"), 3, 5), False),
        ],
    )
    def test_contains(self, loc, expected):
        r = SourceRange(
            start=SourceLocation(Path("foo.py"), 1, 0),
            end=SourceLocation(Path("foo.py"), 5, 10),
        )
        assert r.contains(loc) is expected

    def test_overlaps_true(self):
        r1 = SourceRange(
            start=SourceLocation(Path("f.py"), 1, 0),
            end=SourceLocation(Path("f.py"), 5, 0),
        )
        r2 = SourceRange(
            start=SourceLocation(Path("f.py"), 3, 0),
            end=SourceLocation(Path("f.py"), 8, 0),
        )
        assert r1.overlaps(r2)
        assert r2.overlaps(r1)

    def test_overlaps_false(self):
        r1 = SourceRange(
            start=SourceLocation(Path("f.py"), 1, 0),
            end=SourceLocation(Path("f.py"), 3, 0),
        )
        r2 = SourceRange(
            start=SourceLocation(Path("f.py"), 5, 0),
            end=SourceLocation(Path("f.py"), 8, 0),
        )
        assert not r1.overlaps(r2)

    def test_overlaps_different_files(self):
        r1 = SourceRange(
            start=SourceLocation(Path("a.py"), 1, 0),
            end=SourceLocation(Path("a.py"), 10, 0),
        )
        r2 = SourceRange(
            start=SourceLocation(Path("b.py"), 1, 0),
            end=SourceLocation(Path("b.py"), 10, 0),
        )
        assert not r1.overlaps(r2)
