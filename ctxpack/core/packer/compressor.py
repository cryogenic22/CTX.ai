"""IR → CTXDocument AST (L2) compression with salience scoring."""

from __future__ import annotations

import datetime
from typing import Optional

from ..errors import Span
from ..model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    PlainLine,
    Provenance,
    Section,
)
from .ir import IRCorpus, IREntity, IRField, IRWarning


def compress(corpus: IRCorpus) -> CTXDocument:
    """Compress an IRCorpus into a CTXDocument AST (L2).

    Pipeline:
    1. Score salience
    2. Sort entities by descending salience
    3. Build header
    4. Build entity sections
    5. Build standalone rule sections
    6. Add warnings as ⚠ annotations
    """
    # Score salience
    _score_entities(corpus)

    # Sort entities by descending salience
    corpus.entities.sort(key=lambda e: e.salience, reverse=True)

    # Build sections
    sections = []
    for entity in corpus.entities:
        sections.append(_entity_to_section(entity))

    # Standalone rules
    if corpus.standalone_rules:
        rule_sections = _rules_to_sections(corpus.standalone_rules)
        sections.extend(rule_sections)

    # Add warning section if warnings exist
    if corpus.warnings:
        sections.append(_warnings_to_section(corpus.warnings))

    # Build header
    body = tuple(sections)
    body_text = _estimate_body_text(body)
    ctx_tokens = len(body_text.split())
    source_tokens = corpus.source_token_count or 0
    ratio = f"~{source_tokens / ctx_tokens:.1f}x" if ctx_tokens > 0 and source_tokens > 0 else "~1x"

    today = datetime.date.today().isoformat()
    status_fields = [
        KeyValue(key="DOMAIN", value=corpus.domain or "unknown"),
    ]
    metadata = [
        KeyValue(key="COMPRESSED", value=today),
        KeyValue(key="SOURCE_TOKENS", value=f"~{source_tokens}"),
        KeyValue(key="CTX_TOKENS", value=f"~{ctx_tokens}"),
        KeyValue(key="RATIO", value=ratio),
    ]
    if corpus.scope:
        metadata.append(KeyValue(key="SCOPE", value=corpus.scope))
    if corpus.author:
        metadata.append(KeyValue(key="AUTHOR", value=corpus.author))

    header = Header(
        magic="§CTX",
        version="1.0",
        layer=Layer.L2,
        status_fields=tuple(status_fields),
        metadata=tuple(metadata),
        span=Span.lines(1, 1 + len(metadata)),
    )

    return CTXDocument(header=header, body=body)


# ── Salience Scoring (Phase 1 heuristic) ──


def _score_entities(corpus: IRCorpus) -> None:
    """Score entities and fields using heuristic salience."""
    # Count cross-references
    all_text = ""
    for e in corpus.entities:
        for f in e.fields:
            all_text += f" {f.value}"

    for entity in corpus.entities:
        source_count = len(entity.sources)
        cross_refs = all_text.count(f"@ENTITY-{entity.name}")
        warning_count = sum(
            1 for w in corpus.warnings if entity.name in w.entity
        )

        score = source_count * 1.0 + cross_refs * 2.0 + warning_count * 1.5

        # Golden source boost
        if any(f.key == "★GOLDEN-SOURCE" for f in entity.fields):
            score *= 1.5

        entity.salience = max(score, 1.0)

        # Score individual fields
        for field in entity.fields:
            _score_field(field)


def _score_field(field: IRField) -> None:
    """Score a field using heuristic salience."""
    score = field.salience

    if field.key.startswith("★"):
        score *= 2.0
    if "⚠" in field.value:
        score *= 1.5
    if field.key in ("IDENTIFIER", "PII", "PII-CLASSIFICATION", "MATCH-RULES"):
        score *= 1.3

    field.salience = score


# ── Section Building ──


def _entity_to_section(entity: IREntity) -> Section:
    """Convert an IREntity to a Section node."""
    children = []

    # Sort fields by salience (descending), skip golden source (it's in subtitle)
    sorted_fields = sorted(entity.fields, key=lambda f: f.salience, reverse=True)

    for field in sorted_fields:
        if field.key == "★GOLDEN-SOURCE":
            continue  # Already in subtitle
        children.append(
            KeyValue(key=field.key, value=field.value)
        )

    # Add provenance
    for source in entity.sources:
        children.append(Provenance(source=str(source), path=source.file))

    # Build subtitles from golden source
    subtitles = []
    golden = next(
        (f for f in entity.fields if f.key == "★GOLDEN-SOURCE"), None
    )
    if golden:
        subtitles.append(f"★GOLDEN-SOURCE:{golden.value}")

    return Section(
        name=f"ENTITY-{entity.name}",
        subtitles=tuple(subtitles),
        indent=0,
        depth=0,
        children=tuple(children),
    )


def _rules_to_sections(rules: list[IRField]) -> list[Section]:
    """Group standalone rules into sections."""
    # Group by key prefix
    groups: dict[str, list[IRField]] = {}
    for rule in rules:
        # Use the key as-is for the section
        groups.setdefault(rule.key, []).append(rule)

    sections = []
    for key, fields in groups.items():
        children = []
        for field in fields:
            if field.key == key:
                # Value is the content
                children.append(
                    KeyValue(key=key, value=field.value)
                )
            else:
                children.append(
                    KeyValue(key=field.key, value=field.value)
                )

        # If there's just one field, make a section with that field as child
        # If multiple, make a containing section
        if len(children) == 1 and isinstance(children[0], KeyValue):
            # Single rule → KV as child of section
            sections.append(
                Section(
                    name=key,
                    children=tuple(children),
                )
            )
        else:
            sections.append(
                Section(
                    name=key,
                    children=tuple(children),
                )
            )

    return sections


def _warnings_to_section(warnings: list[IRWarning]) -> Section:
    """Convert warnings to a ⚠WARNINGS section."""
    children = []
    for w in warnings:
        prefix = f"⚠ {w.entity}: " if w.entity else "⚠ "
        children.append(PlainLine(text=f"{prefix}{w.message}"))

    return Section(
        name="WARNINGS",
        subtitles=("⚠",),
        children=tuple(children),
    )


def _estimate_body_text(body: tuple) -> str:
    """Quick text estimation for token counting."""
    parts = []
    for elem in body:
        if isinstance(elem, Section):
            parts.append(f"±{elem.name}")
            parts.append(_estimate_body_text(elem.children))
        elif isinstance(elem, KeyValue):
            parts.append(f"{elem.key}:{elem.value}")
        elif isinstance(elem, PlainLine):
            parts.append(elem.text)
        elif isinstance(elem, Provenance):
            parts.append(f"SRC:{elem.source}")
    return " ".join(parts)
