"""Intermediate representation for the packer pipeline.

Mutable dataclasses bridging parsing → compression. These are converted
to frozen CTXDocument AST nodes by the compressor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# ── Value-level micro-syntax patterns ──

# Window/tolerance: ±3d, ±2w, ±1m, ±30m (minutes vs months disambiguated by context)
WINDOW_RE = re.compile(r"±(\d+)([dwm])\b")

# Conditional guards: only-if(...), when(...), if(...)
CONDITIONAL_RE = re.compile(r"\b(?:only-if|when|if)\(([^)]+)\)")


class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Certainty(Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    UNCERTAIN = "uncertain"


@dataclass
class IRSource:
    """Provenance tracking for a parsed element."""

    file: str
    line_start: int = 0
    line_end: int = 0
    version: str = ""

    def __str__(self) -> str:
        if self.line_start and self.line_end:
            return f"{self.file}#L{self.line_start}-L{self.line_end}"
        if self.line_start:
            return f"{self.file}#L{self.line_start}"
        return self.file


@dataclass
class IRRelationship:
    """A typed relationship between two entities."""

    source_entity: str
    target_entity: str
    rel_type: str = "belongs-to"  # belongs-to, has-many, references
    via_field: str = ""
    cardinality: str = "1:1"  # 1:1, 1:N, M:N
    cascade: str = ""  # cascade-delete, cascade-archive, etc.
    required: bool = False
    source: Optional[IRSource] = None
    certainty: Certainty = Certainty.EXPLICIT


@dataclass
class IRField:
    """A single compressed rule or attribute within an entity.

    ``value`` stores already-compressed L2 notation.
    ``raw_value`` retains the original parsed structure for dedup/conflict detection.
    """

    key: str
    value: str
    raw_value: Any = None
    source: Optional[IRSource] = None
    salience: float = 1.0
    certainty: Certainty = Certainty.EXPLICIT
    additional_sources: list[IRSource] = field(default_factory=list)


@dataclass
class IREntity:
    """A resolved domain entity (e.g. CUSTOMER, ORDER)."""

    name: str
    aliases: list[str] = field(default_factory=list)
    fields: list[IRField] = field(default_factory=list)
    annotations: dict[str, str] = field(default_factory=dict)
    sources: list[IRSource] = field(default_factory=list)
    salience: float = 1.0
    relationships: list[IRRelationship] = field(default_factory=list)


@dataclass
class IRWarning:
    """A conflict or issue detected during packing."""

    entity: str
    message: str
    severity: Severity = Severity.WARNING
    source: Optional[IRSource] = None


@dataclass
class IRCorpus:
    """Complete parsed corpus ready for compression."""

    domain: str = ""
    scope: str = ""
    author: str = ""
    entities: list[IREntity] = field(default_factory=list)
    standalone_rules: list[IRField] = field(default_factory=list)
    warnings: list[IRWarning] = field(default_factory=list)
    source_token_count: int = 0
    source_files: list[str] = field(default_factory=list)
