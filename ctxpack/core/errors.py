"""Error and diagnostic types for .ctx parsing and validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class Span:
    """Source position range for error reporting."""

    line: int
    col: int
    end_line: int
    end_col: int

    @classmethod
    def at(cls, line: int, col: int = 0) -> Span:
        return cls(line, col, line, col)

    @classmethod
    def lines(cls, start: int, end: int) -> Span:
        return cls(start, 0, end, 0)


class DiagnosticLevel(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Diagnostic:
    """Non-fatal validation issue."""

    level: DiagnosticLevel
    message: str
    span: Optional[Span]
    code: str  # e.g. "E001", "W002"

    def __str__(self) -> str:
        loc = f"line {self.span.line}" if self.span else "unknown"
        return f"[{self.code}] {self.level.value}: {self.message} ({loc})"


class ParseError(Exception):
    """Fatal parse failure."""

    def __init__(
        self,
        message: str,
        span: Optional[Span] = None,
        filename: Optional[str] = None,
    ):
        self.span = span
        self.filename = filename
        loc_parts = []
        if filename:
            loc_parts.append(filename)
        if span:
            loc_parts.append(f"line {span.line}")
        loc = ":".join(loc_parts)
        super().__init__(f"{loc}: {message}" if loc else message)
