"""Markdown heading/list → entity extraction for domain knowledge.

Conservative parser: only detects entities from explicit heading patterns
and config alias maps. Extracts rules, warnings, and annotations.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .ir import IREntity, IRField, IRSource, IRWarning, Severity

# ── Heading patterns ──

_H1_RE = re.compile(r"^#\s+(.+)$")
_H2_RE = re.compile(r"^##\s+(.+)$")
_H3_RE = re.compile(r"^###\s+(.+)$")
_H4_RE = re.compile(r"^####\s+(.+)$")
_ENTITY_HEADING_RE = re.compile(
    r"^(?:Entity:\s*)?([A-Z][A-Z0-9_-]+)$", re.IGNORECASE
)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$")
_BLOCKQUOTE_WARNING_RE = re.compile(
    r"^>\s+\*\*(?:Warning|WARN|Caution):\*\*\s*(.+)$", re.IGNORECASE
)
_BLOCKQUOTE_NOTE_RE = re.compile(
    r"^>\s+\*\*(?:Note|INFO):\*\*\s*(.+)$", re.IGNORECASE
)


def extract_entities_from_md(
    text: str,
    *,
    filename: str = "",
    alias_map: Optional[dict[str, list[str]]] = None,
) -> tuple[list[IREntity], list[IRField], list[IRWarning]]:
    """Extract IREntities and standalone rules from Markdown text.

    Returns (entities, standalone_rules, warnings).
    """
    entities: list[IREntity] = []
    standalone_rules: list[IRField] = []
    warnings: list[IRWarning] = []

    # Build reverse alias map: alias → canonical name
    reverse_aliases: dict[str, str] = {}
    if alias_map:
        for canonical, aliases in alias_map.items():
            for alias in aliases:
                reverse_aliases[alias.lower()] = canonical.upper()

    lines = text.split("\n")
    current_entity: Optional[IREntity] = None
    current_field_key: Optional[str] = None
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        lineno = i + 1

        # H1 heading → potential entity boundary
        m = _H1_RE.match(stripped)
        if m:
            heading_text = m.group(1).strip()
            entity_name = _resolve_entity_name(heading_text, reverse_aliases)
            if entity_name:
                if current_entity:
                    entities.append(current_entity)
                current_entity = IREntity(
                    name=entity_name,
                    sources=[IRSource(file=filename, line_start=lineno)],
                )
                current_field_key = None
            else:
                # Non-entity H1 — save current entity and start standalone
                if current_entity:
                    entities.append(current_entity)
                    current_entity = None
                current_field_key = _hyphenate(heading_text).upper()
            i += 1
            continue

        # H2 heading → entity boundary or field within entity
        m = _H2_RE.match(stripped)
        if m:
            heading_text = m.group(1).strip()
            entity_name = _resolve_entity_name(heading_text, reverse_aliases)
            if entity_name:
                if current_entity:
                    entities.append(current_entity)
                current_entity = IREntity(
                    name=entity_name,
                    sources=[IRSource(file=filename, line_start=lineno)],
                )
                current_field_key = None
            else:
                current_field_key = _hyphenate(heading_text).upper()
            i += 1
            continue

        # H3+ heading → field within current entity
        m = _H3_RE.match(stripped) or _H4_RE.match(stripped)
        if m:
            current_field_key = _hyphenate(m.group(1).strip()).upper()
            i += 1
            continue

        # Blockquote warning
        m = _BLOCKQUOTE_WARNING_RE.match(stripped)
        if m:
            warning_text = m.group(1).strip()
            entity_name = current_entity.name if current_entity else ""
            warnings.append(
                IRWarning(
                    entity=entity_name,
                    message=warning_text,
                    severity=Severity.WARNING,
                    source=IRSource(file=filename, line_start=lineno),
                )
            )
            i += 1
            continue

        # Blockquote note
        m = _BLOCKQUOTE_NOTE_RE.match(stripped)
        if m:
            note_text = m.group(1).strip()
            if current_entity and current_field_key:
                current_entity.annotations[current_field_key] = note_text
            i += 1
            continue

        # Bullet list items
        m = _BULLET_RE.match(stripped)
        if m:
            bullet_text = m.group(1).strip()
            compressed = _compress_prose(bullet_text)
            if current_entity:
                current_entity.fields.append(
                    IRField(
                        key=current_field_key or "NOTES",
                        value=compressed,
                        raw_value=bullet_text,
                        source=IRSource(file=filename, line_start=lineno),
                    )
                )
            elif current_field_key:
                standalone_rules.append(
                    IRField(
                        key=current_field_key,
                        value=compressed,
                        raw_value=bullet_text,
                        source=IRSource(file=filename, line_start=lineno),
                    )
                )
            i += 1
            continue

        # Prose paragraph (non-blank, non-heading, non-bullet)
        if stripped and not stripped.startswith(">") and not stripped.startswith("#"):
            compressed = _compress_prose(stripped)
            if current_entity and current_field_key:
                current_entity.fields.append(
                    IRField(
                        key=current_field_key,
                        value=compressed,
                        raw_value=stripped,
                        source=IRSource(file=filename, line_start=lineno),
                    )
                )
            elif current_field_key:
                standalone_rules.append(
                    IRField(
                        key=current_field_key,
                        value=compressed,
                        raw_value=stripped,
                        source=IRSource(file=filename, line_start=lineno),
                    )
                )

        i += 1

    # Don't forget the last entity
    if current_entity:
        entities.append(current_entity)

    return entities, standalone_rules, warnings


def _resolve_entity_name(
    heading: str, reverse_aliases: dict[str, str]
) -> Optional[str]:
    """Try to resolve a heading to a canonical entity name."""
    # Explicit "Entity: NAME" pattern
    m = re.match(r"^Entity:\s*(.+)$", heading, re.IGNORECASE)
    if m:
        return _canonicalize_name(m.group(1).strip())

    # All-caps or mostly-caps name
    clean = heading.strip()
    if re.match(r"^[A-Z][A-Z0-9_\s-]+$", clean):
        return _canonicalize_name(clean)

    # Check alias map
    if clean.lower() in reverse_aliases:
        return reverse_aliases[clean.lower()]

    return None


def _canonicalize_name(name: str) -> str:
    name = name.upper().replace("_", "-").replace(" ", "-")
    for prefix in ("ENTITY-", "ENTITY_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def _hyphenate(text: str) -> str:
    return text.replace(" ", "-").replace("_", "-")


# ── Prose Compression ──

_FILLER_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can",
    "this", "that", "these", "those", "it", "its",
    "for", "of", "in", "to", "and", "or", "but", "with", "by",
    "from", "at", "on", "as", "into", "through", "during",
    "all", "each", "every", "any", "some", "no", "not",
    "very", "just", "also", "then", "so",
}


def _compress_prose(text: str) -> str:
    """Strip filler words, preserving spaces for BPE efficiency.

    Keeps spaces between words instead of hyphenating — hyphens cause
    BPE tokenizers to fragment words, inflating token count by ~40%.
    """
    words = text.split()
    kept = [w for w in words if w.lower().rstrip(".,;:!?") not in _FILLER_WORDS]
    if not kept:
        return text
    return " ".join(kept)
