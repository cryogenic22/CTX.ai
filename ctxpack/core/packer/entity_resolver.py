"""Entity resolution: name normalization, merge, and dedup."""

from __future__ import annotations

from typing import Optional

from .ir import Certainty, IRCorpus, IREntity, IRField, IRRelationship, IRSource


def resolve_entities(
    corpus: IRCorpus,
    *,
    alias_map: Optional[dict[str, list[str]]] = None,
    supersede_by_recency: bool = False,
) -> IRCorpus:
    """Merge duplicate entities and resolve aliases.

    Merging strategy:
    1. Exact match on canonical name
    2. Case-insensitive match
    3. Config alias map
    4. Singular/plural normalization

    Args:
        supersede_by_recency: When True (agent-session path), a field whose
            key repeats with DIFFERENT values is treated as a revision
            chain: the most recent value (by source order) survives as the
            current fact, and the full chain is recorded in a companion
            ``SUPERSEDED-<KEY>`` field. When False (document-corpus
            default), repeated keys are kept verbatim — documents may
            legitimately state multi-valued facts.
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
        merged.append(_merge_entities(
            canonical, group, supersede_by_recency=supersede_by_recency,
        ))

    corpus.entities = merged

    # Cross-entity relationship inference: for each BELONGS-TO on A→B,
    # add synthetic HAS-MANY on B→A (with certainty=INFERRED)
    _infer_bidirectional_relationships(corpus)

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


def _merge_entities(
    canonical: str,
    group: list[IREntity],
    *,
    supersede_by_recency: bool = False,
) -> IREntity:
    """Merge multiple IREntities into one."""
    if len(group) == 1:
        entity = group[0]
        entity.name = canonical
        if supersede_by_recency:
            entity.fields = _supersede_fields(_dedup_fields(entity.fields))
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
    if supersede_by_recency:
        deduped = _supersede_fields(deduped)

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
                # Track additional sources for multi-source provenance
                existing.additional_sources.append(field.source)
        else:
            seen[dedup_key] = field
            result.append(field)

    return result


# Keys that are legitimately multi-valued — never superseded. Includes
# constraint-shaped keys: two different rules are two facts, not a revision.
_MULTI_VALUE_KEYS = {
    "HAS-MANY", "HAS-ONE", "BELONGS-TO", "REFERENCES", "DEPENDS-ON",
    "RELATIONSHIPS", "DECISION", "NOTES",
    "RULE", "CONSTRAINT", "REQUIREMENT", "WARNING",
}


def _field_order(field: IRField, idx: int) -> tuple[int, int]:
    """Recency ordering key: turn (if set) or step/line, then insertion order."""
    if field.source is None:
        return (0, idx)
    if field.source.turn is not None:
        return (field.source.turn, idx)
    return (field.source.line_start, idx)


def _supersede_fields(fields: list[IRField]) -> list[IRField]:
    """Collapse same-key revision chains to the latest value + history.

    For each key that appears with multiple distinct values, the most
    recent value (by source order) becomes the current fact — placed at
    the key's first-occurrence position so field order stays stable — and
    a companion ``SUPERSEDED-<KEY>`` field records the chain, e.g.::

        BACKOFF-BASE-MS:750
        SUPERSEDED-BACKOFF-BASE-MS:250@step-0 -> 500@step-2 -> 750@step-4

    A changed decision is a state update with an auditable history, not a
    silent accumulation of contradictory values (the 2026-07-03 audit's
    defect #2). Relationship keys and already-generated SUPERSEDED-* keys
    are exempt.
    """
    by_key: dict[str, list[tuple[int, IRField]]] = {}
    for idx, field in enumerate(fields):
        by_key.setdefault(field.key, []).append((idx, field))

    # Keys getting a new revision chain this pass. Their existing
    # SUPERSEDED-<KEY> records are absorbed into the new chain rather than
    # emitted — otherwise every re-resolve stacks another history line.
    revised = {
        key for key, entries in by_key.items()
        if len(entries) > 1
        and key not in _MULTI_VALUE_KEYS
        and not key.startswith("SUPERSEDED-")
    }

    out: list[IRField] = []
    emitted: set[str] = set()
    for idx, field in enumerate(fields):
        key = field.key
        if key in emitted:
            continue
        if key.startswith("SUPERSEDED-") and key[len("SUPERSEDED-"):] in revised:
            continue  # absorbed into the regenerated chain below

        entries = by_key[key]
        if key not in revised:
            out.extend(f for _, f in entries)
            emitted.add(key)
            continue

        # Revision chain: order by recency, latest wins
        ordered = sorted(entries, key=lambda e: _field_order(e[1], e[0]))
        current = ordered[-1][1]
        chain = " -> ".join(
            f"{f.value}@{f.source.file if f.source else '?'}"
            for _, f in ordered
        )
        # Absorb prior history from ALL prior SUPERSEDED-<KEY> fields (an
        # alias-map merge can contribute several). Elements already present
        # in the new chain (each prior chain's tail re-appears as a current
        # entry) are dropped; the rest are prefixed in order of appearance.
        # Known limitation: values containing " -> " would misalign the
        # chain — spec v1.1 fact IDs replace this string encoding.
        priors = by_key.get(f"SUPERSEDED-{key}", [])
        if priors:
            new_elems = set(chain.split(" -> "))
            prefix_elems = []
            for _, prior_field in priors:
                for elem in str(prior_field.value).split(" -> "):
                    if elem and elem not in new_elems:
                        prefix_elems.append(elem)
                        new_elems.add(elem)
            if prefix_elems:
                chain = " -> ".join(prefix_elems) + " -> " + chain
        out.append(current)
        out.append(IRField(
            key=f"SUPERSEDED-{key}",
            value=chain,
            raw_value=chain,
            source=current.source,
            salience=max(0.5, current.salience - 0.5),
        ))
        emitted.add(key)

    return out


def _infer_bidirectional_relationships(corpus: IRCorpus) -> None:
    """For each BELONGS-TO on entity A→B, add HAS-MANY on B→A if not already present."""
    entity_map = {e.name: e for e in corpus.entities}

    # Collect all explicit relationships
    existing: set[tuple[str, str, str]] = set()  # (source, target, rel_type)
    for entity in corpus.entities:
        for rel in entity.relationships:
            existing.add((rel.source_entity, rel.target_entity, rel.rel_type))

    # Infer inverse relationships
    for entity in list(corpus.entities):
        for rel in list(entity.relationships):
            if rel.rel_type == "belongs-to":
                inverse_key = (rel.target_entity, rel.source_entity, "has-many")
                if inverse_key not in existing and rel.target_entity in entity_map:
                    target = entity_map[rel.target_entity]
                    inverse_rel = IRRelationship(
                        source_entity=rel.target_entity,
                        target_entity=rel.source_entity,
                        rel_type="has-many",
                        via_field=rel.via_field,
                        cardinality="1:N",
                        cascade=rel.cascade,
                        required=False,
                        source=rel.source,
                        certainty=Certainty.INFERRED,
                    )
                    target.relationships.append(inverse_rel)
                    # Also add as a field
                    target.fields.append(IRField(
                        key="HAS-MANY",
                        value=f"@ENTITY-{rel.source_entity}({rel.via_field},1:N)",
                        raw_value=None,
                        source=rel.source,
                        certainty=Certainty.INFERRED,
                    ))
                    existing.add(inverse_key)
            elif rel.rel_type == "has-many":
                inverse_key = (rel.target_entity, rel.source_entity, "belongs-to")
                if inverse_key not in existing and rel.target_entity in entity_map:
                    target = entity_map[rel.target_entity]
                    inverse_rel = IRRelationship(
                        source_entity=rel.target_entity,
                        target_entity=rel.source_entity,
                        rel_type="belongs-to",
                        via_field=rel.via_field,
                        cardinality="1:1",
                        cascade="",
                        required=False,
                        source=rel.source,
                        certainty=Certainty.INFERRED,
                    )
                    target.relationships.append(inverse_rel)
                    target.fields.append(IRField(
                        key="BELONGS-TO",
                        value=f"@ENTITY-{rel.source_entity}({rel.via_field})",
                        raw_value=None,
                        source=rel.source,
                        certainty=Certainty.INFERRED,
                    ))
                    existing.add(inverse_key)
