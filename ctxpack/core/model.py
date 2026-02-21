"""AST node types for .ctx documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union

from .errors import Span


# ── Enums ──


class Layer(Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    MANIFEST = "MANIFEST"


class OperatorKind(Enum):
    ARROW = "→"
    NEGATION = "¬"
    CONJUNCTION = "+"
    DISJUNCTION = "|"
    SEQUENCE = ">>"
    WEAK_ASSOC = "~>"
    EMPHASIS = "★"
    WARNING = "⚠"
    SECTION = "±"
    MAGIC = "§"
    CROSS_REF = "@"
    EQUIVALENCE = "≡"
    CONFLICT = "⊥"
    UNCERTAINTY = "?"
    APPROX = "~"


# ── Leaf nodes ──


@dataclass(frozen=True)
class PlainLine:
    text: str
    span: Optional[Span] = None


@dataclass(frozen=True)
class KeyValue:
    key: str
    value: str
    span: Optional[Span] = None


@dataclass(frozen=True)
class NumberedItem:
    number: int
    text: str
    span: Optional[Span] = None


@dataclass(frozen=True)
class InlineList:
    items: tuple[str, ...]
    span: Optional[Span] = None


@dataclass(frozen=True)
class QuotedBlock:
    content: str
    lang: str = ""
    span: Optional[Span] = None


@dataclass(frozen=True)
class Provenance:
    source: str
    path: str = ""
    line_range: str = ""
    span: Optional[Span] = None


@dataclass(frozen=True)
class Operator:
    kind: OperatorKind
    text: str
    offset: int  # character offset within the containing value string


@dataclass(frozen=True)
class CrossRef:
    target: str  # e.g. "SECTION-NAME" or "file.ctx#SECTION"
    namespace: str = ""
    span: Optional[Span] = None


# ── Body element union type ──

BodyElement = Union[
    PlainLine, KeyValue, NumberedItem, InlineList, QuotedBlock, Provenance
]


# ── Section ──


@dataclass(frozen=True)
class Section:
    name: str
    subtitles: tuple[str, ...] = ()
    indent: int = 0
    depth: int = 0
    children: tuple[Union[Section, BodyElement], ...] = ()
    span: Optional[Span] = None


# ── Header ──


@dataclass(frozen=True)
class Header:
    magic: str  # "§CTX" or "$CTX"
    version: str  # e.g. "1.0"
    layer: Layer
    status_fields: tuple[KeyValue, ...] = ()  # KV pairs on status line
    metadata: tuple[KeyValue, ...] = ()  # KV pairs on subsequent lines
    span: Optional[Span] = None

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Look up a header field by key (case-insensitive)."""
        key_upper = key.upper()
        for kv in self.status_fields:
            if kv.key.upper() == key_upper:
                return kv.value
        for kv in self.metadata:
            if kv.key.upper() == key_upper:
                return kv.value
        return default

    @property
    def all_fields(self) -> tuple[KeyValue, ...]:
        return self.status_fields + self.metadata


# ── Document root ──


@dataclass(frozen=True)
class CTXDocument:
    header: Header
    body: tuple[Union[Section, BodyElement], ...] = ()
    source_text: str = ""
