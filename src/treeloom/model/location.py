"""Source location tracking for mapping graph elements back to code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """A specific position in a source file.

    Lines are 1-based (matching editor display). Columns are 0-based.
    """

    file: Path
    line: int
    column: int = 0

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SourceLocation):
            return NotImplemented
        if self.file != other.file:
            return str(self.file) < str(other.file)
        if self.line != other.line:
            return self.line < other.line
        return self.column < other.column

    def __le__(self, other: object) -> bool:
        if not isinstance(other, SourceLocation):
            return NotImplemented
        return self == other or self < other


@dataclass(frozen=True, slots=True)
class SourceRange:
    """A contiguous range in a source file, from start to end (inclusive)."""

    start: SourceLocation
    end: SourceLocation

    def contains(self, location: SourceLocation) -> bool:
        """Check whether a location falls within this range."""
        if location.file != self.start.file:
            return False
        return self.start <= location <= self.end

    def overlaps(self, other: SourceRange) -> bool:
        """Check whether two ranges overlap."""
        if self.start.file != other.start.file:
            return False
        return self.start <= other.end and other.start <= self.end
