"""Serialize a CTXDocument AST back to .ctx text.

Modes:
  - Default: reproduce original formatting
  - canonical=True: reorder header fields, consistent whitespace
  - ascii_mode=True: replace Unicode operators with ASCII fallbacks
"""

from __future__ import annotations

from typing import Union

from .model import (
    BodyElement,
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    NumberedItem,
    PlainLine,
    Provenance,
    QuotedBlock,
    Section,
)

# Unicode → ASCII replacement table
_UNICODE_TO_ASCII = {
    "§CTX": "$CTX",
    "§": "$CTX",
    "±": "##",
    "→": "->",
    "¬": "!",
    "★": "***",
    "⚠": "WARN:",
    "≡": "===",
    "⊥": "CONFLICT:",
    "~>": "~>",  # already ASCII
}

# Required fields come first, then recommended, then custom
_REQUIRED_FIELDS = {"DOMAIN", "COMPRESSED", "SOURCE_TOKENS"}
_RECOMMENDED_FIELDS = {
    "SCOPE",
    "AUTHOR",
    "CTX_TOKENS",
    "SOURCE",
    "RATIO",
    "GEN",
    "HASH",
    "PROVENANCE",
    "SCHEMA",
    "TURNS",
}


def serialize(
    doc: CTXDocument,
    *,
    canonical: bool = False,
    ascii_mode: bool = False,
) -> str:
    """Serialize a CTXDocument AST to .ctx text."""
    lines: list[str] = []

    # Header
    _serialize_header(doc.header, lines, canonical=canonical, ascii_mode=ascii_mode)
    lines.append("")  # blank separator

    # Body
    _serialize_body(doc.body, lines, ascii_mode=ascii_mode)

    result = "\n".join(lines)
    # Ensure trailing newline
    if not result.endswith("\n"):
        result += "\n"
    return result


def _serialize_header(
    header: Header,
    lines: list[str],
    *,
    canonical: bool,
    ascii_mode: bool,
) -> None:
    """Serialize header to lines."""
    magic = header.magic
    if ascii_mode and magic == "§CTX":
        magic = "$CTX"

    # Status line
    parts = [magic, f"v{header.version}", header.layer.value]
    if canonical:
        # In canonical mode, put all fields on separate lines
        # Only required fields on status line
        status_kvs = [
            kv
            for kv in header.status_fields
            if kv.key.upper() in _REQUIRED_FIELDS
        ]
        remaining = [
            kv
            for kv in header.status_fields
            if kv.key.upper() not in _REQUIRED_FIELDS
        ]
    else:
        status_kvs = list(header.status_fields)
        remaining = []

    for kv in status_kvs:
        val = _ascii_replace(kv.value) if ascii_mode else kv.value
        parts.append(f"{kv.key}:{val}")
    lines.append(" ".join(parts))

    # Metadata lines
    if canonical:
        all_meta = remaining + list(header.metadata)
        # Sort: required first, then recommended, then custom
        def _sort_key(kv: KeyValue) -> tuple[int, str]:
            k = kv.key.upper()
            if k in _REQUIRED_FIELDS:
                return (0, k)
            if k in _RECOMMENDED_FIELDS:
                return (1, k)
            return (2, k)

        all_meta.sort(key=_sort_key)
        for kv in all_meta:
            val = _ascii_replace(kv.value) if ascii_mode else kv.value
            lines.append(f"{kv.key}:{val}")
    else:
        # Group metadata by original line if they share the same span
        if header.metadata:
            # Check if multiple KVs share the same line
            line_groups: dict[int, list[KeyValue]] = {}
            for kv in header.metadata:
                lineno = kv.span.line if kv.span else -1
                line_groups.setdefault(lineno, []).append(kv)

            for lineno in sorted(line_groups):
                kvs = line_groups[lineno]
                if len(kvs) > 1:
                    # Multiple KV pairs on same line — space-separated
                    parts = []
                    for kv in kvs:
                        val = _ascii_replace(kv.value) if ascii_mode else kv.value
                        parts.append(f"{kv.key}:{val}")
                    lines.append(" ".join(parts))
                else:
                    kv = kvs[0]
                    val = _ascii_replace(kv.value) if ascii_mode else kv.value
                    lines.append(f"{kv.key}:{val}")


def _serialize_body(
    elements: tuple[Union[Section, BodyElement], ...],
    lines: list[str],
    *,
    ascii_mode: bool,
) -> None:
    """Serialize body elements."""
    for i, elem in enumerate(elements):
        if isinstance(elem, Section):
            _serialize_section(elem, lines, ascii_mode=ascii_mode)
        elif isinstance(elem, KeyValue):
            val = _ascii_replace(elem.value) if ascii_mode else elem.value
            lines.append(f"{elem.key}:{val}")
        elif isinstance(elem, NumberedItem):
            text = _ascii_replace(elem.text) if ascii_mode else elem.text
            lines.append(f"{elem.number}.{text}")
        elif isinstance(elem, QuotedBlock):
            lang_tag = elem.lang if elem.lang else ""
            lines.append(f"```{lang_tag}")
            lines.append(elem.content)
            lines.append("```")
        elif isinstance(elem, Provenance):
            lines.append(f"SRC:{elem.source}")
        elif isinstance(elem, PlainLine):
            text = _ascii_replace(elem.text) if ascii_mode else elem.text
            lines.append(text)


def _serialize_section(
    section: Section,
    lines: list[str],
    *,
    ascii_mode: bool,
) -> None:
    """Serialize a section and its children."""
    indent = " " * section.indent
    sigil = "##" if ascii_mode else "±"
    subtitle_str = ""
    if section.subtitles:
        subs = section.subtitles
        if ascii_mode:
            subs = tuple(_ascii_replace(s) for s in subs)
        subtitle_str = " " + " ".join(subs)

    name = section.name
    lines.append(f"{indent}{sigil}{name}{subtitle_str}")

    # Blank line after section marker if section has no immediate content
    # (but children may start with a subsection)
    if not section.children:
        return

    _serialize_body(section.children, lines, ascii_mode=ascii_mode)


def _ascii_replace(text: str) -> str:
    """Replace Unicode operators with ASCII fallbacks."""
    for uni, asc in _UNICODE_TO_ASCII.items():
        if uni in text:
            text = text.replace(uni, asc)
    return text
