"""Serialize a CTXDocument AST back to .ctx text.

Modes:
  - Default: reproduce original formatting
  - canonical=True: reorder header fields, consistent whitespace
  - ascii_mode=True: replace Unicode operators with ASCII fallbacks
  - natural_language=True: emit L1 readable prose (## headings, bullet lists)

Streaming:
  - serialize_iter() yields lines for streaming/MCP use
  - serialize_section() yields lines for per-section hydration
  - serialize() uses serialize_iter() internally (zero regression risk)
"""

from __future__ import annotations

import re
from typing import Iterator, Union

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
    natural_language: bool = False,
    bpe_optimized: bool = False,
) -> str:
    """Serialize a CTXDocument AST to .ctx text."""
    result = "\n".join(
        serialize_iter(
            doc,
            canonical=canonical,
            ascii_mode=ascii_mode,
            natural_language=natural_language,
            bpe_optimized=bpe_optimized,
        )
    )
    # Ensure trailing newline
    if not result.endswith("\n"):
        result += "\n"
    return result


def serialize_iter(
    doc: CTXDocument,
    *,
    canonical: bool = False,
    ascii_mode: bool = False,
    natural_language: bool = False,
    bpe_optimized: bool = False,
) -> Iterator[str]:
    """Yield lines of serialized .ctx text for streaming.

    Each yielded string is one line (without trailing newline).
    """
    if natural_language:
        yield from _serialize_nl_iter(doc)
        return

    # Header
    yield from _serialize_header_iter(doc.header, canonical=canonical, ascii_mode=ascii_mode)
    yield ""  # blank separator

    # Body
    yield from _serialize_body_iter(doc.body, ascii_mode=ascii_mode, bpe_optimized=bpe_optimized)


def serialize_section(
    section: Section,
    *,
    ascii_mode: bool = False,
    natural_language: bool = False,
    bpe_optimized: bool = False,
) -> Iterator[str]:
    """Yield lines for a single section — used for MCP per-section hydration."""
    if natural_language:
        yield from _nl_section(section, depth_offset=1)
        return
    yield from _serialize_section_iter(section, ascii_mode=ascii_mode, bpe_optimized=bpe_optimized)


def _serialize_header_iter(
    header: Header,
    *,
    canonical: bool,
    ascii_mode: bool,
) -> Iterator[str]:
    """Yield header lines."""
    magic = header.magic
    if ascii_mode and magic == "§CTX":
        magic = "$CTX"

    # Status line
    parts = [magic, f"v{header.version}", header.layer.value]
    if canonical:
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
    yield " ".join(parts)

    # Metadata lines
    if canonical:
        all_meta = remaining + list(header.metadata)

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
            yield f"{kv.key}:{val}"
    else:
        if header.metadata:
            line_groups: dict[int, list[KeyValue]] = {}
            for kv in header.metadata:
                lineno = kv.span.line if kv.span else -1
                line_groups.setdefault(lineno, []).append(kv)

            for lineno in sorted(line_groups):
                kvs = line_groups[lineno]
                if len(kvs) > 1:
                    parts = []
                    for kv in kvs:
                        val = _ascii_replace(kv.value) if ascii_mode else kv.value
                        parts.append(f"{kv.key}:{val}")
                    yield " ".join(parts)
                else:
                    kv = kvs[0]
                    val = _ascii_replace(kv.value) if ascii_mode else kv.value
                    yield f"{kv.key}:{val}"


def _serialize_body_iter(
    elements: tuple[Union[Section, BodyElement], ...],
    *,
    ascii_mode: bool,
    bpe_optimized: bool = False,
) -> Iterator[str]:
    """Yield body element lines."""
    for elem in elements:
        if isinstance(elem, Section):
            yield from _serialize_section_iter(elem, ascii_mode=ascii_mode, bpe_optimized=bpe_optimized)
        elif isinstance(elem, KeyValue):
            val = _ascii_replace(elem.value) if ascii_mode else elem.value
            if bpe_optimized:
                val = _dehyphenate_value(val)
            yield f"{elem.key}:{val}"
        elif isinstance(elem, NumberedItem):
            text = _ascii_replace(elem.text) if ascii_mode else elem.text
            yield f"{elem.number}.{text}"
        elif isinstance(elem, QuotedBlock):
            lang_tag = elem.lang if elem.lang else ""
            yield f"```{lang_tag}"
            yield elem.content
            yield "```"
        elif isinstance(elem, Provenance):
            yield f"SRC:{elem.source}"
        elif isinstance(elem, PlainLine):
            text = _ascii_replace(elem.text) if ascii_mode else elem.text
            yield text


def _serialize_section_iter(
    section: Section,
    *,
    ascii_mode: bool,
    bpe_optimized: bool = False,
) -> Iterator[str]:
    """Yield lines for a section and its children."""
    indent = " " * section.indent
    sigil = "##" if ascii_mode else "±"
    subtitle_str = ""
    if section.subtitles:
        subs = section.subtitles
        if ascii_mode:
            subs = tuple(_ascii_replace(s) for s in subs)
        subtitle_str = " " + " ".join(subs)

    name = section.name
    yield f"{indent}{sigil}{name}{subtitle_str}"

    if not section.children:
        return

    yield from _serialize_body_iter(section.children, ascii_mode=ascii_mode, bpe_optimized=bpe_optimized)


def _ascii_replace(text: str) -> str:
    """Replace Unicode operators with ASCII fallbacks."""
    for uni, asc in _UNICODE_TO_ASCII.items():
        if uni in text:
            text = text.replace(uni, asc)
    return text


# Regex to identify word-separator hyphens in values.
# Matches hyphens between lowercase/uppercase letter sequences (word boundaries).
# Preserves hyphens in: technical identifiers (snake_case-like), version numbers,
# operator chains (→, ~>), and bracketed content.
_WORD_HYPHEN_RE = re.compile(r"(?<=[a-zA-Z])(-+)(?=[a-zA-Z])")

# Patterns that indicate a structural/technical identifier — skip dehyphenation
_STRUCTURAL_PATTERNS = re.compile(
    r"^[A-Z][A-Z0-9_-]*$"  # ALL-CAPS identifiers like CRM-Salesforce
    r"|^\(.*\)$"  # parenthesized expressions
    r"|^@"  # cross-references
    r"|^\["  # inline lists
)


def _dehyphenate_value(value: str) -> str:
    """Replace word-separator hyphens with spaces in KV values for BPE efficiency.

    Hyphens between words (e.g., "Customer-matching-critical") tokenize ~40% worse
    in BPE than spaces ("Customer matching critical"). This transform only affects
    prose-like value segments, preserving structural identifiers, cross-references,
    and operator chains.
    """
    # Split on common delimiters to process segments independently
    # Preserves operators (→, ~>, >>), brackets, parentheses
    segments = re.split(r"([→~>|,\[\]()]+)", value)
    result_parts = []
    for seg in segments:
        # Skip empty, single-char, or structural segments
        if not seg or len(seg) <= 1 or _STRUCTURAL_PATTERNS.match(seg.strip()):
            result_parts.append(seg)
            continue
        # Only dehyphenate segments that look like prose (contain lowercase letters)
        if any(c.islower() for c in seg):
            seg = _WORD_HYPHEN_RE.sub(" ", seg)
        result_parts.append(seg)
    return "".join(result_parts)


# ── Natural Language (L1) serializer ──

# Regex for cross-references: @ENTITY-NAME or @ENTITY-NAME(params)
_NL_CROSSREF_RE = re.compile(r"@(ENTITY-[\w-]+)(?:\(([^)]*)\))?")

# Cardinality label mapping
_NL_CARDINALITY = {
    "1:1": "one-to-one",
    "1:N": "one-to-many",
    "N:1": "many-to-one",
    "M:N": "many-to-many",
    "N:M": "many-to-many",
}

# Operator replacements for NL mode
_NL_OPERATORS = {
    "¬": "not ",
    "→": " leads to ",
    "⚠": "Warning: ",
    "★": "",
    "≡": " equals ",
    "⊥": "Conflict: ",
    "~>": " weakly associated with ",
    ">>": " then ",
}

# Section name prefixes to strip
_NL_SECTION_PREFIXES = (
    "ENTITY-", "RULE-", "RULES-", "DOC-", "WARNINGS-", "WARNING-",
    "TOPOLOGY-", "ID-PATTERN-", "CONSTRAINT-",
)


def _serialize_nl_iter(doc: CTXDocument) -> Iterator[str]:
    """Yield natural-language lines for the entire document."""
    yield from _nl_header(doc.header)
    yield ""
    yield from _nl_body(doc.body)


def _nl_header(header: Header) -> Iterator[str]:
    """Render header as a readable Markdown block."""
    version = header.version
    layer = header.layer.value
    yield f"# Context Document (v{version}, {layer})"
    yield ""

    # Collect all header fields
    all_fields = list(header.status_fields) + list(header.metadata)
    for kv in all_fields:
        label = _nl_key_label(kv.key)
        value = _nl_decode_value(kv.key, kv.value)
        yield f"- **{label}**: {value}"


def _nl_body(
    elements: tuple[Union[Section, BodyElement], ...],
    depth_offset: int = 1,
) -> Iterator[str]:
    """Render body elements as readable prose."""
    for elem in elements:
        if isinstance(elem, Section):
            yield from _nl_section(elem, depth_offset=depth_offset)
        elif isinstance(elem, KeyValue):
            label = _nl_key_label(elem.key)
            value = _nl_decode_value(elem.key, elem.value)
            yield f"- **{label}**: {value}"
        elif isinstance(elem, NumberedItem):
            text = _nl_decode_value("", elem.text)
            yield f"{elem.number}. {text}"
        elif isinstance(elem, QuotedBlock):
            lang_tag = elem.lang if elem.lang else ""
            yield f"```{lang_tag}"
            yield elem.content
            yield "```"
        elif isinstance(elem, Provenance):
            yield f"- Source: {elem.source}"
        elif isinstance(elem, PlainLine):
            text = _nl_decode_value("", elem.text)
            yield text


def _nl_section(
    section: Section,
    depth_offset: int = 1,
) -> Iterator[str]:
    """Render a section as a Markdown heading with readable name."""
    # Map section depth to heading level (##, ###, ####, etc.)
    heading_level = min(section.depth + depth_offset + 1, 6)
    hashes = "#" * heading_level

    name = _nl_section_name(section.name)

    # Subtitles become parenthetical
    subtitle_parts = []
    for sub in section.subtitles:
        subtitle_parts.append(_nl_decode_value("", sub))
    subtitle_str = ""
    if subtitle_parts:
        subtitle_str = " (" + ", ".join(subtitle_parts) + ")"

    yield ""
    yield f"{hashes} {name}{subtitle_str}"
    yield ""

    if section.children:
        yield from _nl_body(section.children, depth_offset=depth_offset)


def _nl_section_name(name: str) -> str:
    """Convert section name to readable form.

    ENTITY-DRUG → Drug
    RULES-DATA-QUALITY → Data Quality Rules
    ⚠WARNINGS → Warnings
    """
    # Strip warning prefix
    clean = name.lstrip("⚠")

    # Strip known prefixes
    upper = clean.upper()
    is_rule = False
    for prefix in _NL_SECTION_PREFIXES:
        if upper.startswith(prefix):
            if prefix.startswith("RULE"):
                is_rule = True
            clean = clean[len(prefix):]
            break

    # Convert hyphens/underscores to spaces, title case
    readable = clean.replace("-", " ").replace("_", " ").strip()
    readable = readable.title()

    if is_rule and not readable.lower().endswith("rules"):
        readable += " Rules"

    return readable if readable else name


def _nl_key_label(key: str) -> str:
    """Convert a key to a readable label.

    PII-CLASSIFICATION → Pii Classification
    GOLDEN-SOURCE → Golden Source
    IDENTIFIER → Identifier
    """
    return key.replace("-", " ").replace("_", " ").title()


def _nl_decode_value(key: str, value: str) -> str:
    """Decode a .ctx value into readable text.

    Expands @ENTITY refs, cardinalities, inline lists, operators.
    """
    result = value

    # Replace operators
    for op, replacement in _NL_OPERATORS.items():
        if op in result:
            result = result.replace(op, replacement)

    # Replace cross-references: @ENTITY-CUSTOMER(field,N:1) → Customer (via field, many-to-one)
    result = _NL_CROSSREF_RE.sub(_nl_crossref_replace, result)

    # Replace inline list separators: + → ", " (only when + is a separator)
    # Be careful not to replace + inside words
    result = re.sub(r"(?<=\w)\+(?=\w)", ", ", result)

    return result.strip()


def _nl_crossref_replace(m: re.Match) -> str:
    """Replace a cross-reference match with readable text."""
    ref_name = _nl_section_name(m.group(1))
    params = m.group(2)
    if not params:
        return ref_name

    # Parse params: field, cardinality
    parts = [p.strip() for p in params.split(",")]
    readable_parts = []
    for part in parts:
        card = _NL_CARDINALITY.get(part)
        if card:
            readable_parts.append(card)
        else:
            readable_parts.append(part)

    return f"{ref_name} (via {', '.join(readable_parts)})"


def _nl_cardinality(cardinality: str) -> str:
    """Convert cardinality notation to readable text."""
    return _NL_CARDINALITY.get(cardinality, cardinality)
