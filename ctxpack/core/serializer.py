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


# Patterns that should NEVER be dehyphenated
_PRESERVE_HYPHEN_RE = re.compile(
    r"@ENTITY-[\w-]+"    # cross-references: @ENTITY-CUSTOMER
    r"|@[\w-]+"          # other cross-refs
    r"|\d+-\d+"          # version/number ranges: 1-N, 36-months
    r"|[A-Z][A-Z0-9_]+-[A-Z][A-Z0-9_]+"  # ALL-CAPS identifiers: SOURCE_TOKENS
)


def _dehyphenate_value(value: str) -> str:
    """Replace word-separator hyphens with spaces in KV values for BPE efficiency.

    Hyphens between words (e.g., "Customer-matching-critical") tokenize ~40% worse
    in BPE than spaces ("Customer matching critical"). This is aggressive but safe:
    we protect cross-references (@ENTITY-X), number ranges (1-N), and ALL-CAPS
    identifiers, then replace all other hyphens with spaces.

    Also converts comma-hyphen (,-) to comma-space (, ) since the compressor
    produces this pattern extensively.
    """
    # Step 1: Protect patterns that must keep hyphens
    protected: list[tuple[str, str]] = []
    counter = 0

    def _protect(m: re.Match) -> str:
        nonlocal counter
        placeholder = f"\x00P{counter}\x00"
        protected.append((placeholder, m.group(0)))
        counter += 1
        return placeholder

    result = _PRESERVE_HYPHEN_RE.sub(_protect, value)

    # Step 2: Replace all remaining hyphens with spaces
    result = result.replace("-", " ")

    # Step 3: Clean up double spaces from comma-hyphen patterns
    result = re.sub(r"  +", " ", result)

    # Step 4: Restore protected patterns
    for placeholder, original in protected:
        result = result.replace(placeholder, original)

    return result


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
    """Render body elements as readable prose.

    Consecutive KeyValue pairs with the same key are collapsed:
    the first gets the **Key**: prefix, subsequent ones become
    indented continuation bullets.
    """
    # Collect elements into groups for repeated-key collapsing
    i = 0
    elem_list = list(elements)
    while i < len(elem_list):
        elem = elem_list[i]
        if isinstance(elem, Section):
            yield from _nl_section(elem, depth_offset=depth_offset)
            i += 1
        elif isinstance(elem, KeyValue):
            # Gather consecutive KVs with the same key
            key = elem.key
            group: list[KeyValue] = [elem]
            j = i + 1
            while j < len(elem_list) and isinstance(elem_list[j], KeyValue) and elem_list[j].key == key:
                group.append(elem_list[j])
                j += 1
            yield from _nl_kv_group(group)
            i = j
        elif isinstance(elem, NumberedItem):
            text = _nl_decode_value("", elem.text)
            yield f"{elem.number}. {text}"
            i += 1
        elif isinstance(elem, QuotedBlock):
            lang_tag = elem.lang if elem.lang else ""
            yield f"```{lang_tag}"
            yield elem.content
            yield "```"
            i += 1
        elif isinstance(elem, Provenance):
            yield f"- Source: {elem.source}"
            i += 1
        elif isinstance(elem, PlainLine):
            text = _nl_decode_value("", elem.text)
            yield text
            i += 1
        else:
            i += 1


def _nl_kv_group(group: list[KeyValue]) -> Iterator[str]:
    """Render a group of KeyValue pairs that share the same key.

    Single-item groups: ``- **Label**: value``
    Multi-item groups: first item gets the label, rest become indented bullets.
    """
    label = _nl_key_label(group[0].key)

    if len(group) == 1:
        lines = _nl_decode_value_lines(group[0].key, group[0].value)
        if len(lines) == 1:
            yield from _nl_wrap_line(f"- **{label}**: {lines[0]}")
        else:
            yield f"- **{label}**:"
            for sub in lines:
                yield from _nl_wrap_line(f"  - {sub}")
    else:
        # Multiple KVs with same key → first value as header, rest as bullets
        first_lines = _nl_decode_value_lines(group[0].key, group[0].value)
        if len(first_lines) == 1:
            yield f"- **{label}**: {first_lines[0]}"
        else:
            yield f"- **{label}**:"
            for sub in first_lines:
                yield from _nl_wrap_line(f"  - {sub}")
        for kv in group[1:]:
            sub_lines = _nl_decode_value_lines(kv.key, kv.value)
            for sub in sub_lines:
                yield from _nl_wrap_line(f"  - {sub}")


def _nl_wrap_line(line: str, max_words: int = 150) -> Iterator[str]:
    """Yield a line, splitting it if it exceeds *max_words* words."""
    words = line.split()
    if len(words) <= max_words:
        yield line
        return
    # Find the indent prefix for continuation lines
    stripped = line.lstrip()
    indent = line[: len(line) - len(stripped)]
    # First chunk keeps original indent; continuations get extra indent
    cont_indent = indent + "  "
    while words:
        chunk = words[:max_words]
        words = words[max_words:]
        if chunk is not words:
            yield " ".join(chunk)
        if words:
            words = [cont_indent + words[0]] + words[1:]


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
    """Decode a .ctx value into readable text (single-line).

    Expands @ENTITY refs, cardinalities, inline lists, operators.
    For structured notation, falls back to a one-line summary.
    """
    lines = _nl_decode_value_lines(key, value)
    return "; ".join(lines).strip()


# ── Structured notation parsing ──

# Regex: top-level key(value) groups separated by +
# Matches: name(IRSource)+type(dataclass)+description(...)
_NL_STRUCTURED_RE = re.compile(
    r"^(?:\w[\w-]*\([^)]*(?:\([^)]*\)[^)]*)*\)"
    r"(?:\+\w[\w-]*\([^)]*(?:\([^)]*\)[^)]*)*\))+)$"
)

# Individual key(value) token — handles one level of nested parens
_NL_KV_TOKEN_RE = re.compile(
    r"(\w[\w-]*)\(([^)]*(?:\([^)]*\)[^)]*)*)\)"
)


def _nl_decode_value_lines(key: str, value: str) -> list[str]:
    """Decode a .ctx value into one or more readable text lines.

    If the value contains structured notation (key(val)+key(val)+...),
    it is parsed into individual readable items. Otherwise, a single
    decoded line is returned.
    """
    stripped = value.strip()

    # First: replace operators and cross-references in the raw value
    result = stripped
    for op, replacement in _NL_OPERATORS.items():
        if op in result:
            result = result.replace(op, replacement)
    result = _NL_CROSSREF_RE.sub(_nl_crossref_replace, result)

    # Check if value is structured notation: key(val)+key(val)+...
    # We detect this by looking for the pattern of word(...)+word(...)
    if _nl_is_structured(result):
        items = _nl_parse_structured(result)
        if items:
            return items

    # Not structured — simple + replacement for plain inline lists
    result = re.sub(r"(?<=\w)\+(?=\w)", ", ", result)
    return [result.strip()] if result.strip() else []


def _nl_is_structured(value: str) -> bool:
    """Check if a value uses structured key(val)+key(val) notation.

    This detects the pattern even with nested parentheses and complex values.
    """
    # Quick check: must contain )+ to have structured groups
    if ")+(" not in value and ")+\\" not in value:
        # More general: check for )+word( pattern
        if not re.search(r"\)\+\w", value):
            return False
    return True


def _nl_parse_structured(value: str) -> list[str]:
    """Parse structured notation into readable prose lines.

    Input:  name(IRSource)+type(dataclass)+description(Source location...)
    Output: ["IRSource (dataclass): Source location..."]

    Handles multiple record patterns:
    - name/type/description groups → "Name (type): description"
    - step/name/description groups → "Step N. Name: description"
    - code/description groups → "Code: description"
    - key/value groups → "Key: value"
    - Single-key groups → "key: value"
    """
    # Split on top-level + (not inside parentheses)
    tokens = _nl_split_plus(value)
    if not tokens:
        return []

    # Parse each token into (key, value) pairs
    parsed: list[tuple[str, str]] = []
    for token in tokens:
        m = _NL_KV_TOKEN_RE.match(token.strip())
        if m:
            parsed.append((m.group(1).lower(), m.group(2)))
        else:
            # Not a key(value) token — treat as plain text
            parsed.append(("_text", token.strip()))

    # Group tokens into logical records
    return _nl_group_records(parsed)


def _nl_split_plus(value: str) -> list[str]:
    """Split a value on + that is outside parentheses."""
    tokens: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(value):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "+" and depth == 0:
            token = value[start:i]
            if token.strip():
                tokens.append(token)
            start = i + 1
    tail = value[start:]
    if tail.strip():
        tokens.append(tail)
    return tokens


def _nl_group_records(
    parsed: list[tuple[str, str]],
) -> list[str]:
    """Group (key, value) pairs into logical records and render as prose.

    Recognizes patterns like:
    - name+type+description → "Name (type): description"
    - step+name+description → "Step N. Name: description"
    - code+description → "Code: description"
    - type+description+method → "Type: description (method)"
    - key+description → "Key: description"
    - format+parser+description → "Format (parser): description"
    """
    lines: list[str] = []
    i = 0

    while i < len(parsed):
        # Try to match known multi-key record patterns
        remaining = parsed[i:]

        # Pattern: name + type + description (+ optional extras)
        record, consumed = _nl_try_record(remaining, ["name", "type", "description"])
        if record:
            name = record.get("name", "")
            typ = record.get("type", "")
            desc = record.get("description", "")
            line = f"{name} ({typ})" if typ else name
            if desc:
                line += f": {desc}"
            lines.append(line)
            i += consumed
            continue

        # Pattern: name + type (without description)
        record, consumed = _nl_try_record(remaining, ["name", "type"])
        if record and consumed == 2:
            lines.append(f"{record['name']} ({record['type']})")
            i += consumed
            continue

        # Pattern: step + name + description
        record, consumed = _nl_try_record(remaining, ["step", "name", "description"])
        if record:
            step = record.get("step", "")
            name = record.get("name", "")
            desc = record.get("description", "")
            line = f"{step}. {name}"
            if desc:
                line += f": {desc}"
            lines.append(line)
            i += consumed
            continue

        # Pattern: step + name (without description)
        record, consumed = _nl_try_record(remaining, ["step", "name"])
        if record and consumed == 2:
            lines.append(f"{record['step']}. {record['name']}")
            i += consumed
            continue

        # Pattern: code + description
        record, consumed = _nl_try_record(remaining, ["code", "description"])
        if record and consumed == 2:
            lines.append(f"{record['code']}: {record['description']}")
            i += consumed
            continue

        # Pattern: format + parser + description
        record, consumed = _nl_try_record(remaining, ["format", "parser", "description"])
        if record:
            fmt = record.get("format", "")
            parser = record.get("parser", "")
            desc = record.get("description", "")
            line = f"{fmt} ({parser})"
            if desc:
                line += f": {desc}"
            lines.append(line)
            i += consumed
            continue

        # Pattern: type + description + method (conflict detectors, etc.)
        record, consumed = _nl_try_record(remaining, ["type", "description", "method"])
        if record:
            typ = record.get("type", "")
            desc = record.get("description", "")
            method = record.get("method", "")
            line = f"{typ}: {desc}"
            if method:
                line += f" (method: {method})"
            lines.append(line)
            i += consumed
            continue

        # Pattern: type + description (without method)
        record, consumed = _nl_try_record(remaining, ["type", "description"])
        if record and consumed == 2:
            lines.append(f"{record['type']}: {record['description']}")
            i += consumed
            continue

        # Pattern: name + description
        record, consumed = _nl_try_record(remaining, ["name", "description"])
        if record and consumed == 2:
            lines.append(f"{record['name']}: {record['description']}")
            i += consumed
            continue

        # Pattern: key + description
        record, consumed = _nl_try_record(remaining, ["key", "description"])
        if record and consumed == 2:
            lines.append(f"{record['key']}: {record['description']}")
            i += consumed
            continue

        # Pattern: level + description
        record, consumed = _nl_try_record(remaining, ["level", "description"])
        if record and consumed == 2:
            lines.append(f"Level {record['level']}: {record['description']}")
            i += consumed
            continue

        # Single key(value) — render as "key: value" or just inline
        k, v = parsed[i]
        if k == "_text":
            lines.append(v)
        else:
            readable_key = k.replace("-", " ").replace("_", " ").title()
            # Recursively decode the value in case it has nested structured notation
            if _nl_is_structured(v):
                sub_items = _nl_parse_structured(v)
                if sub_items:
                    lines.append(f"{readable_key}: {'; '.join(sub_items)}")
                else:
                    lines.append(f"{readable_key}: {v}")
            else:
                lines.append(f"{readable_key}: {v}")
        i += 1

    return lines


def _nl_try_record(
    tokens: list[tuple[str, str]],
    keys: list[str],
) -> tuple[dict[str, str] | None, int]:
    """Try to match a sequence of tokens against expected keys.

    Returns (dict of key→value, count consumed) or (None, 0).
    Matching is greedy: consumes all consecutive tokens that match
    the expected key sequence.
    """
    if len(tokens) < len(keys):
        return None, 0

    record: dict[str, str] = {}
    ki = 0  # key index
    ti = 0  # token index

    while ki < len(keys) and ti < len(tokens):
        tk, tv = tokens[ti]
        if tk == keys[ki]:
            record[keys[ki]] = tv
            ki += 1
            ti += 1
        else:
            break

    if ki == len(keys):
        return record, ti
    return None, 0


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
