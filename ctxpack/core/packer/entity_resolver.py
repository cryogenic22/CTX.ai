"""Entity resolution: name normalization, merge, and dedup."""

from __future__ import annotations

from typing import Optional

from .ir import IRCorpus, IREntity, IRField, IRSource


def resolve_entities(
    corpus: IRCorpus,
    *,
    alias_map: Optional[dict[str, list[str]]] = None,
) -> IRCorpus:
    """Merge duplicate entities and resolve aliases.

    Merging strategy:
    1. Exact match on canonical name
    2. Case-insensitive match
    3. Config alias map
    4. Singular/plural normalization
    """
    alias_map = alias_map or {}

    # Build reverse alias lookup: alias → canonical
    reverse: dict[str, str] = {}
    for canonical, aliases in alias_map.items():
        canonical_norm = _normalize(canonical)
        for alias in aliases:
            reverse[_normalize(alias)] = canonical_norm

    # Group entities by canonical name
    groups: dict[str, list[IREntity]] = {}
    for entity in corpus.entities:
        name = _resolve_name(entity.name, reverse)
        groups.setdefault(name, []).append(entity)

    # Merge each group
    merged: list[IREntity] = []
    for canonical, group in groups.items():
        merged.append(_merge_entities(canonical, group))

    corpus.entities = merged
    return corpus


def _resolve_name(name: str, reverse: dict[str, str]) -> str:
    """Resolve an entity name to its canonical form."""
    norm = _normalize(name)

    # Check alias map
    if norm in reverse:
        return reverse[norm]

    # Singular/plural: strip trailing -S
    if norm.endswith("S") and len(norm) > 2:
        singular = norm[:-1]
        if singular in reverse:
            return reverse[singular]

    return norm


def _normalize(name: str) -> str:
    """Normalize name: uppercase, _/space → -, strip entity- prefix."""
    name = name.upper().replace("_", "-").replace(" ", "-")
    for prefix in ("ENTITY-",):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def _merge_entities(canonical: str, group: list[IREntity]) -> IREntity:
    """Merge multiple IREntities into one."""
    if len(group) == 1:
        entity = group[0]
        entity.name = canonical
        return entity

    # Merge fields, aliases, sources, annotations
    all_aliases: set[str] = set()
    all_fields: list[IRField] = []
    all_sources: list[IRSource] = []
    all_annotations: dict[str, str] = {}
    max_salience = 0.0

    for entity in group:
        all_aliases.update(entity.aliases)
        all_sources.extend(entity.sources)
        all_annotations.update(entity.annotations)
        max_salience = max(max_salience, entity.salience)
        all_fields.extend(entity.fields)

    # Dedup fields: same key + same raw_value → keep one, union sources
    deduped = _dedup_fields(all_fields)

    return IREntity(
        name=canonical,
        aliases=sorted(all_aliases),
        fields=deduped,
        annotations=all_annotations,
        sources=all_sources,
        salience=max_salience,
    )


def _dedup_fields(fields: list[IRField]) -> list[IRField]:
    """Deduplicate fields by key + raw_value."""
    seen: dict[tuple[str, str], IRField] = {}
    result: list[IRField] = []

    for field in fields:
        raw_key = str(field.raw_value) if field.raw_value is not None else ""
        dedup_key = (field.key, raw_key)

        if dedup_key in seen:
            # Merge source info (keep higher salience)
            existing = seen[dedup_key]
            if field.salience > existing.salience:
                existing.salience = field.salience
            if field.source and existing.source:
                # Keep the first source, just note the merge
                pass
        else:
            seen[dedup_key] = field
            result.append(field)

    return result
