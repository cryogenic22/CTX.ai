"""Operator extraction for Level 3 parsing.

Post-processes AST value strings to identify .ctx operators.
Operator table is ordered longest-first to avoid prefix conflicts.
Backtick-quoted regions are skipped.
"""

from __future__ import annotations

import re
from typing import Union

from .model import (
    BodyElement,
    CrossRef,
    CTXDocument,
    KeyValue,
    Operator,
    OperatorKind,
    PlainLine,
    Section,
)

# Ordered longest-first for greedy matching
_OPERATOR_TABLE: list[tuple[str, OperatorKind]] = [
    ("CONFLICT:", OperatorKind.CONFLICT),
    ("WARN:", OperatorKind.WARNING),
    ("$CTX", OperatorKind.MAGIC),
    ("===", OperatorKind.EQUIVALENCE),
    ("***", OperatorKind.EMPHASIS),
    ("~>", OperatorKind.WEAK_ASSOC),
    (">>", OperatorKind.SEQUENCE),
    ("->", OperatorKind.ARROW),
    ("##", OperatorKind.SECTION),
    ("→", OperatorKind.ARROW),
    ("¬", OperatorKind.NEGATION),
    ("★", OperatorKind.EMPHASIS),
    ("⚠", OperatorKind.WARNING),
    ("±", OperatorKind.SECTION),
    ("§", OperatorKind.MAGIC),
    ("≡", OperatorKind.EQUIVALENCE),
    ("⊥", OperatorKind.CONFLICT),
    ("+", OperatorKind.CONJUNCTION),
    ("|", OperatorKind.DISJUNCTION),
    ("!", OperatorKind.NEGATION),
    ("~", OperatorKind.APPROX),
    ("?", OperatorKind.UNCERTAINTY),
    ("@", OperatorKind.CROSS_REF),
]

_CROSSREF_RE = re.compile(
    r"@([A-Za-z_][A-Za-z0-9_./-]*(?:#[A-Za-z][A-Za-z0-9_/-]*)?)"
)
_NS_DEF_RE = re.compile(r"@DEF\s+([a-z][a-z0-9-]*):=([A-Za-z0-9_./-]+)")


def extract_operators(text: str) -> list[Operator]:
    """Extract operators from a value string, skipping backtick-quoted regions."""
    ops: list[Operator] = []
    i = 0
    n = len(text)

    while i < n:
        # Skip inline backtick quotes
        if text[i] == "`":
            end = text.find("`", i + 1)
            if end == -1:
                break
            i = end + 1
            continue

        matched = False
        for pattern, kind in _OPERATOR_TABLE:
            if text[i : i + len(pattern)] == pattern:
                ops.append(Operator(kind=kind, text=pattern, offset=i))
                i += len(pattern)
                matched = True
                break

        if not matched:
            i += 1

    return ops


def extract_crossrefs(text: str) -> list[CrossRef]:
    """Extract cross-references from a value string."""
    refs: list[CrossRef] = []
    for m in _CROSSREF_RE.finditer(text):
        target = m.group(1)
        # Skip @DEF declarations
        prefix = text[max(0, m.start() - 4) : m.start()]
        if "DEF" in prefix:
            continue
        refs.append(CrossRef(target=target))
    return refs


def extract_operators_from_doc(doc: CTXDocument) -> dict[str, list[Operator]]:
    """Extract all operators from a document, keyed by location path."""
    result: dict[str, list[Operator]] = {}

    def _walk(
        elements: tuple[Union[Section, BodyElement], ...], path: str
    ) -> None:
        for elem in elements:
            if isinstance(elem, Section):
                sec_path = f"{path}/{elem.name}" if path else elem.name
                for sub in elem.subtitles:
                    ops = extract_operators(sub)
                    if ops:
                        result[f"{sec_path}:subtitle"] = ops
                _walk(elem.children, sec_path)
            elif isinstance(elem, KeyValue):
                ops = extract_operators(elem.value)
                if ops:
                    key_path = f"{path}/{elem.key}" if path else elem.key
                    result[key_path] = ops
            elif isinstance(elem, PlainLine):
                ops = extract_operators(elem.text)
                if ops:
                    loc = f"{path}:line{elem.span.line}" if elem.span else path
                    result[loc] = ops

    _walk(doc.body, "")
    return result
