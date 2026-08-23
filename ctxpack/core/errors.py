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


# ── Bounded exception categories (TM-7/TM-14) ──
#
# A diagnostic channel no scanner reads (journals, receipts, hook
# stderr, MCP error results) must never receive free exception text —
# a message can embed secret bytes, and a class NAME is caller-
# controlled text too: "AKIAIOSFODNN7EXAMPLE" is a valid identifier,
# and type(secret, (Exception,), {}) mints a class whose __name__ IS
# the secret. So the exception OBJECT is classified by isinstance
# against stdlib bases only, and exactly one of these fixed categories
# ever reaches such a channel. Lives in core so every layer (core,
# agent, integrations) shares ONE classifier without layering
# violations.

IO_ERROR = "io_error"
RUNTIME_ERROR = "runtime_error"
ENCODING_ERROR = "encoding_error"
UNKNOWN_EXCEPTION = "unknown_exception"
ERROR_CLASSES = (IO_ERROR, RUNTIME_ERROR, ENCODING_ERROR,
                 UNKNOWN_EXCEPTION)

# UnicodeError subclasses ValueError, not OSError, so nothing overlaps
# today — but this stays an ordered tuple, not a dict, so the first
# match is deterministic if a future base ever does.
_EXCEPTION_BASES = ((UnicodeError, ENCODING_ERROR),
                    (OSError, IO_ERROR),
                    (RuntimeError, RUNTIME_ERROR))


def classify_exception(exc: object) -> str:
    """Bounded diagnostic category for an exception object.

    Returns one of :data:`ERROR_CLASSES` — never ``type(exc).__name__``,
    never message text, never any caller-supplied string. Anything that
    is not an instance of a recognized stdlib base (including a
    non-exception handed in by mistake) maps to ``unknown_exception``.
    The input is classified, not serialized: no byte of it can reach
    the channel the category lands in.
    """
    for base, label in _EXCEPTION_BASES:
        if isinstance(exc, base):
            return label
    return UNKNOWN_EXCEPTION
