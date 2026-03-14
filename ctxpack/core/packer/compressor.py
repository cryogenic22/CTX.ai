"""IR → CTXDocument AST (L2) compression with salience scoring."""

from __future__ import annotations

import datetime
import re
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
from .ir import CONDITIONAL_RE, WINDOW_RE, Certainty, IRCorpus, IREntity, IRField, IRWarning

# Precompiled regex for cross-reference extraction
_CROSSREF_RE = re.compile(r"@ENTITY-(\w[\w-]*)")

# Relationship keys get salience boost
_RELATIONSHIP_KEYS = {"BELONGS-TO", "HAS-MANY", "HAS-ONE", "REFERENCES", "DEPENDS-ON"}


def compress(
    corpus: IRCorpus,
    *,
    strict: bool = False,
    max_ratio: float = 0,
    min_tokens_per_entity: int = 0,
    randomize_order: bool = False,
    preset: str = "",
) -> CTXDocument:
    """Compress an IRCorpus into a CTXDocument AST (L2).

    Pipeline:
    1. Score salience
    2. Sort entities by descending salience
    3. Build header
    4. Build entity sections
    5. Build standalone rule sections
    6. Add warnings as ⚠ annotations
    7. If over-compressed, hydrate to meet token floor

    Args:
        strict: Suppress INFERRED fields entirely.
        max_ratio: Maximum compression ratio (e.g. 10.0). 0 = no limit.
        min_tokens_per_entity: Minimum token budget per entity. 0 = no limit.
        preset: Named compression preset ("conservative", "balanced", "aggressive").
                If set, overrides max_ratio and min_tokens_per_entity.
    """
    # Apply preset if specified
    budget_map: dict[str, dict[str, str]] | None = None
    if preset:
        from .budget import PRESETS, allocate
        if preset not in PRESETS:
            from .budget import PRESETS as _p
            available = ", ".join(sorted(_p.keys()))
            raise ValueError(f"Unknown preset '{preset}'. Available: {available}")
        config = PRESETS[preset]
        max_ratio = config.max_ratio
        min_tokens_per_entity = config.min_tokens_per_entity

        # Score salience first (needed by allocate)
        _score_entities(corpus)

        # Run budget allocation
        entity_budgets = allocate(corpus, preset=preset)
        # Build lookup: entity_name -> {field_key -> action}
        budget_map = {}
        for eb in entity_budgets:
            field_actions = {fd.field.key: fd.action for fd in eb.field_decisions}
            budget_map[eb.entity.name] = field_actions
    else:
        # Score salience
        _score_entities(corpus)

    # Sort entities by descending salience (or randomize for ablation)
    if randomize_order:
        import random as _rng
        _rng.seed(42)
        _rng.shuffle(corpus.entities)
    else:
        corpus.entities.sort(key=lambda e: e.salience, reverse=True)

    # Build sections
    sections = []
    for entity in corpus.entities:
        field_actions = budget_map.get(entity.name) if budget_map else None
        sections.append(_entity_to_section(entity, strict=strict,
                                            field_actions=field_actions))

    # Standalone rules
    if corpus.standalone_rules:
        rule_sections = _rules_to_sections(corpus.standalone_rules)
        sections.extend(rule_sections)

    # Add warning section if warnings exist
    if corpus.warnings:
        sections.append(_warnings_to_section(corpus.warnings))

    # Check compression floor — hydrate if over-compressed
    # Use serialized token count (whitespace-split) for accurate ratio,
    # since AST count_tokens overcounts (keys and values counted separately
    # but serialize as KEY:VALUE = 1 whitespace token).
    body = tuple(sections)
    ctx_tokens = _serialized_token_count(body)
    source_tokens = corpus.source_token_count or 0
    entity_count = len(corpus.entities)

    needs_hydration = False
    if max_ratio > 0 and ctx_tokens > 0 and source_tokens > 0:
        if source_tokens / ctx_tokens > max_ratio:
            needs_hydration = True
    if min_tokens_per_entity > 0 and entity_count > 0:
        if ctx_tokens / entity_count < min_tokens_per_entity:
            needs_hydration = True

    if needs_hydration:
        sections = _hydrate_sections(sections, corpus, strict=strict,
                                     max_ratio=max_ratio,
                                     min_tokens_per_entity=min_tokens_per_entity)
        body = tuple(sections)
        ctx_tokens = _serialized_token_count(body)

    # Use serialized count for ratio display; AST count for CTX_TOKENS metadata
    ast_tokens = count_tokens(body)
    ratio = f"~{source_tokens / ctx_tokens:.1f}x" if ctx_tokens > 0 and source_tokens > 0 else "~1x"

    today = datetime.date.today().isoformat()
    status_fields = [
        KeyValue(key="DOMAIN", value=corpus.domain or "unknown"),
    ]
    metadata = [
        KeyValue(key="COMPRESSED", value=today),
        KeyValue(key="SOURCE_TOKENS", value=f"~{source_tokens}"),
        KeyValue(key="CTX_TOKENS", value=f"~{ast_tokens}"),
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
    # Single-pass cross-reference index: entity_name → count
    ref_counts: dict[str, int] = {}
    for e in corpus.entities:
        for f in e.fields:
            for m in _CROSSREF_RE.finditer(f.value):
                target = m.group(1)
                ref_counts[target] = ref_counts.get(target, 0) + 1

    for entity in corpus.entities:
        source_count = len(entity.sources)
        cross_refs = ref_counts.get(entity.name, 0)
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
    if field.key in _RELATIONSHIP_KEYS:
        score *= 1.2

    # Window/tolerance patterns get mild boost (operational precision)
    if WINDOW_RE.search(field.value):
        score *= 1.1

    # Conditional guard patterns get salience boost (business logic)
    if CONDITIONAL_RE.search(field.value):
        score *= 1.3

    field.salience = score


# ── Section Building ──


def _entity_to_section(
    entity: IREntity,
    *,
    strict: bool = False,
    field_actions: dict[str, str] | None = None,
) -> Section:
    """Convert an IREntity to a Section node.

    Args:
        entity: The entity to convert.
        strict: Suppress INFERRED fields entirely.
        field_actions: Optional dict of field_key → action ("include", "abbreviate", "drop")
                       from the budget allocator. If None, all fields are included.
    """
    children = []

    # Single-pass partition: extract golden source, then sort remainder
    golden = None
    other_fields: list[IRField] = []
    for f in entity.fields:
        if f.key == "★GOLDEN-SOURCE":
            golden = f
        else:
            other_fields.append(f)

    # Sort non-golden fields by salience (descending)
    other_fields.sort(key=lambda f: f.salience, reverse=True)

    for field in other_fields:
        # In strict mode, suppress inferred fields entirely
        if strict and field.certainty == Certainty.INFERRED:
            continue

        # Budget-based field action
        if field_actions is not None:
            action = field_actions.get(field.key, "include")
            if action == "drop":
                continue
            if action == "abbreviate":
                value = _abbreviate_value(field.value)
                children.append(KeyValue(key=field.key, value=value))
                continue

        # In enriched mode (default), annotate inferred fields
        value = field.value
        if field.certainty == Certainty.INFERRED:
            value = _annotate_inferred(value)
        children.append(
            KeyValue(key=field.key, value=value)
        )

    # Add provenance
    for source in entity.sources:
        children.append(Provenance(source=str(source), path=source.file))

    # Build subtitles from golden source
    subtitles = []
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


def _hydrate_sections(
    sections: list[Section],
    corpus: IRCorpus,
    *,
    strict: bool = False,
    max_ratio: float = 10.0,
    min_tokens_per_entity: int = 25,
) -> list[Section]:
    """Hydrate over-compressed sections to meet token floor.

    Strategy:
    1. Un-hyphenate field values (restore spaces) for readability
    2. Add entity description as a DESCRIPTION plain-text line
    3. Expand raw_value for fields where compressed form is too terse
    """
    entity_map = {e.name: e for e in corpus.entities}
    source_tokens = corpus.source_token_count or 0

    hydrated = []
    for section in sections:
        if not section.name.startswith("ENTITY-"):
            hydrated.append(section)
            continue

        entity_name = section.name[len("ENTITY-"):]
        entity = entity_map.get(entity_name)

        children = list(section.children)

        # Phase 1: Un-hyphenate all KV values (restore spaces)
        new_children = []
        for child in children:
            if isinstance(child, KeyValue):
                new_children.append(
                    KeyValue(key=child.key, value=_dehyphenate(child.value))
                )
            else:
                new_children.append(child)
        children = new_children

        # Phase 2: Add entity description as readable text
        if entity and entity.annotations.get("description"):
            desc = entity.annotations["description"]
            # Insert description at the top
            children.insert(0, PlainLine(text=desc))

        # Phase 3: Expand fields from raw_value where compressed form
        # lost too much detail (raw_value is a dict or list with structure)
        if entity:
            existing_keys = {c.key for c in children if isinstance(c, KeyValue)}
            for field in entity.fields:
                if field.key in existing_keys:
                    continue
                if field.key == "★GOLDEN-SOURCE":
                    continue
                if strict and field.certainty == Certainty.INFERRED:
                    continue
                # Add fields that were not included in the original pass
                value = _dehyphenate(field.value)
                if field.certainty == Certainty.INFERRED:
                    value = _annotate_inferred(value)
                children.append(KeyValue(key=field.key, value=value))

        hydrated.append(Section(
            name=section.name,
            subtitles=section.subtitles,
            indent=section.indent,
            depth=section.depth,
            children=tuple(children),
        ))

    # Check if we've met the floor; if not, do a more aggressive
    # expansion pass using raw values
    body = tuple(hydrated)
    ctx_tokens = count_tokens(body)
    entity_count = len(corpus.entities)

    still_over = False
    if max_ratio > 0 and ctx_tokens > 0 and source_tokens > 0:
        if source_tokens / ctx_tokens > max_ratio:
            still_over = True
    if min_tokens_per_entity > 0 and entity_count > 0:
        if ctx_tokens / entity_count < min_tokens_per_entity:
            still_over = True

    if still_over:
        hydrated = _expand_raw_values(hydrated, corpus, strict=strict)

    return hydrated


def _expand_raw_values(
    sections: list[Section],
    corpus: IRCorpus,
    *,
    strict: bool = False,
) -> list[Section]:
    """Second-pass hydration: expand raw_value dicts as readable lines."""
    entity_map = {e.name: e for e in corpus.entities}

    expanded = []
    for section in sections:
        if not section.name.startswith("ENTITY-"):
            expanded.append(section)
            continue

        entity_name = section.name[len("ENTITY-"):]
        entity = entity_map.get(entity_name)
        if not entity:
            expanded.append(section)
            continue

        children = list(section.children)

        # Add raw values for fields with complex structure
        for field in entity.fields:
            if field.key == "★GOLDEN-SOURCE":
                continue
            if strict and field.certainty == Certainty.INFERRED:
                continue
            raw = field.raw_value
            if isinstance(raw, list) and len(raw) > 0:
                for item in raw:
                    if isinstance(item, dict):
                        parts = []
                        for k, v in item.items():
                            parts.append(f"{k}: {v}")
                        children.append(PlainLine(text=f"  {', '.join(parts)}"))
                    else:
                        children.append(PlainLine(text=f"  {item}"))
            elif isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(v, dict):
                        sub_parts = [f"{sk}: {sv}" for sk, sv in v.items()]
                        children.append(PlainLine(text=f"  {k}: {', '.join(sub_parts)}"))
                    else:
                        children.append(PlainLine(text=f"  {k}: {v}"))

        expanded.append(Section(
            name=section.name,
            subtitles=section.subtitles,
            indent=section.indent,
            depth=section.depth,
            children=tuple(children),
        ))

    return expanded


def _dehyphenate(value: str) -> str:
    """Restore spaces from hyphenated L2 notation.

    Reverses _hyphenate: replaces hyphens with spaces in multi-word tokens.
    Preserves hyphens in known patterns: @ENTITY-X, operator notation,
    key names (UPPER-CASE), and technical identifiers.
    """
    # Don't dehyphenate short values or values without hyphens
    if "-" not in value or len(value) < 5:
        return value

    # Split by known delimiters that should be preserved
    # Process each token individually
    result_parts = []
    # Split on spaces first (already-spaced content)
    for token in value.split():
        if (
            token.startswith("@")           # cross-references
            or token.startswith("★")        # emphasis operator
            or token.startswith("⚠")        # warning operator
            or token.isupper()              # UPPER-CASE-KEYS
            or "(" in token                 # parenthetical notation
            or token.startswith("SRC:")     # provenance
            or ":" in token                 # key:value pairs
        ):
            result_parts.append(token)
        else:
            # Dehyphenate this token: restore spaces
            result_parts.append(token.replace("-", " "))

    return " ".join(result_parts)


def _abbreviate_value(value: str) -> str:
    """Truncate a value to its first clause for aggressive compression.

    Preserves cross-references and key structural tokens.
    Splits on common clause delimiters: |, →, comma-space.
    """
    # Split on clause delimiters, keep first
    for delim in ("|", "→", ","):
        if delim in value:
            first = value.split(delim)[0].strip()
            if first:
                return first + "…"
    # If no delimiter, truncate to ~40 chars
    if len(value) > 40:
        return value[:37] + "…"
    return value


def _annotate_inferred(value: str) -> str:
    """Add (inferred) annotation to a compressed value.

    Inserts inside the last parenthetical if one exists,
    otherwise appends at the end.
    """
    # If value ends with ), insert before closing paren
    if value.endswith(")"):
        return value[:-1] + "(inferred))"
    return value + "(inferred)"


def _serialized_token_count(elements: tuple | list) -> int:
    """Count tokens as they appear in serialized output (whitespace-split).

    In serialized .ctx, KeyValue becomes ``KEY:VALUE`` — one whitespace token
    if neither key nor value contains spaces.  This gives a more accurate
    estimate of the actual token count an LLM will see.
    """
    total = 0
    for elem in elements:
        if isinstance(elem, Section):
            # ±SECTION-NAME = 1 token
            total += 1
            total += _serialized_token_count(elem.children)
        elif isinstance(elem, KeyValue):
            # KEY:VALUE serializes as one string; count its whitespace tokens
            serialized = f"{elem.key}:{elem.value}"
            total += len(serialized.split())
        elif isinstance(elem, PlainLine):
            total += len(elem.text.split())
        elif isinstance(elem, Provenance):
            total += len(f"SRC:{elem.source}".split())
    return total


def count_tokens(elements: tuple | list) -> int:
    """Count tokens by walking AST without string concatenation.

    Counts words (whitespace-split) across all text-bearing nodes.
    Reusable by l3_generator and manifest.
    """
    total = 0
    for elem in elements:
        if isinstance(elem, Section):
            # Section name counts as 1 token (±NAME)
            total += 1
            total += count_tokens(elem.children)
        elif isinstance(elem, KeyValue):
            total += len(elem.key.split()) + len(elem.value.split())
        elif isinstance(elem, PlainLine):
            total += len(elem.text.split())
        elif isinstance(elem, Provenance):
            total += 1 + len(elem.source.split())
    return total
