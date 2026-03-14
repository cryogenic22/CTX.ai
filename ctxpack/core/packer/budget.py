"""Variable bitrate budget allocation for compression presets.

Distributes token budget across entities and fields, supporting
three compression presets (conservative, balanced, aggressive)
with must-preserve contracts for type-safe field protection.

This module implements WS1 of the v0.4.0 backlog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .ir import IRCorpus, IREntity, IRField


# ── Data Structures ──


@dataclass(frozen=True)
class CompressionPreset:
    """Named compression configuration."""

    name: str
    max_ratio: float
    min_tokens_per_entity: int
    drop_below_salience: float
    abbreviate_values: bool


@dataclass
class FieldBudget:
    """Per-field inclusion decision with reasoning."""

    field: IRField
    action: str  # "include", "abbreviate", "drop"
    reason: str  # Human-readable explanation


@dataclass
class EntityBudget:
    """Token allocation for one entity."""

    entity: IREntity
    token_budget: int
    field_decisions: list[FieldBudget] = field(default_factory=list)


# ── Preset Registry ──


PRESETS: dict[str, CompressionPreset] = {
    "conservative": CompressionPreset(
        name="conservative",
        max_ratio=5.0,
        min_tokens_per_entity=30,
        drop_below_salience=0.0,
        abbreviate_values=False,
    ),
    "balanced": CompressionPreset(
        name="balanced",
        max_ratio=10.0,
        min_tokens_per_entity=15,
        drop_below_salience=0.3,
        abbreviate_values=False,
    ),
    "aggressive": CompressionPreset(
        name="aggressive",
        max_ratio=15.0,
        min_tokens_per_entity=5,
        drop_below_salience=0.6,
        abbreviate_values=True,
    ),
}


# ── Must-Preserve Heuristic ──


_BOOLEAN_VALUES = frozenset({
    "true", "false", "yes", "no", "enabled", "disabled",
})

_ALWAYS_PRESERVE_KEYS = frozenset({
    "IDENTIFIER", "★GOLDEN-SOURCE",
})


def _is_must_preserve(field_obj: IRField) -> bool:
    """Type-based must-preserve: booleans, identifiers, enums never dropped.

    Addresses Red Team RT-2 (Static Salience Fallacy): certain field types
    are critical regardless of their salience score.
    """
    if field_obj.key in _ALWAYS_PRESERVE_KEYS:
        return True

    # Boolean patterns
    val = field_obj.value.lower().strip()
    if val in _BOOLEAN_VALUES:
        return True

    # Enum-like: single token, short value (e.g. "active", "deprecated", "Phase-II")
    stripped = field_obj.value.strip()
    if len(stripped.split()) == 1 and len(stripped) < 20:
        return True

    return False


# ── Budget Allocation ──


def allocate(
    corpus: IRCorpus,
    *,
    preset: str = "balanced",
    total_budget: int = 0,
    must_preserve: set[str] | None = None,
) -> list[EntityBudget]:
    """Distribute token budget across entities and decide per-field inclusion.

    Algorithm:
    1. Look up preset configuration
    2. Sort entities by salience (descending)
    3. Allocate budget proportionally to salience
    4. For each entity, classify fields:
       - must-preserve (type-based + explicit) → always "include"
       - above salience threshold → "include"
       - between threshold and floor → "abbreviate" (if preset allows)
       - below floor → "drop"
    5. Return ordered list of EntityBudget

    Args:
        corpus: Parsed corpus with scored entities.
        preset: Named compression preset.
        total_budget: Token budget (0 = auto from source_tokens / max_ratio).
        must_preserve: Additional field keys that must never be dropped.

    Raises:
        ValueError: If preset name is unknown.
    """
    if preset not in PRESETS:
        available = ", ".join(sorted(PRESETS.keys()))
        raise ValueError(
            f"Unknown preset '{preset}'. Available: {available}"
        )

    config = PRESETS[preset]
    preserve_keys = must_preserve or set()

    if not corpus.entities:
        return []

    # Calculate total budget from source tokens and preset ratio
    if total_budget <= 0:
        source_tokens = corpus.source_token_count or 1000
        total_budget = max(int(source_tokens / config.max_ratio), 50)

    # Sort entities by salience descending
    sorted_entities = sorted(corpus.entities, key=lambda e: e.salience, reverse=True)

    # Distribute budget proportionally to salience
    total_salience = sum(e.salience for e in sorted_entities)
    if total_salience <= 0:
        total_salience = len(sorted_entities)

    budgets: list[EntityBudget] = []
    for entity in sorted_entities:
        proportion = entity.salience / total_salience
        entity_budget = max(int(total_budget * proportion), config.min_tokens_per_entity)

        # Classify each field
        field_decisions = _classify_fields(
            entity.fields,
            config=config,
            preserve_keys=preserve_keys,
        )

        budgets.append(EntityBudget(
            entity=entity,
            token_budget=entity_budget,
            field_decisions=field_decisions,
        ))

    return budgets


def _classify_fields(
    fields: list[IRField],
    *,
    config: CompressionPreset,
    preserve_keys: set[str],
) -> list[FieldBudget]:
    """Classify each field as include/abbreviate/drop."""
    decisions: list[FieldBudget] = []

    for f in fields:
        # Must-preserve: type-based heuristic or explicit set
        if _is_must_preserve(f) or f.key in preserve_keys:
            decisions.append(FieldBudget(
                field=f,
                action="include",
                reason=f"must-preserve (key={f.key}, type-protected)",
            ))
            continue

        # Salience-based decision
        if f.salience < config.drop_below_salience:
            if config.abbreviate_values:
                decisions.append(FieldBudget(
                    field=f,
                    action="abbreviate" if f.salience >= config.drop_below_salience * 0.5 else "drop",
                    reason=f"salience {f.salience:.2f} below threshold {config.drop_below_salience}",
                ))
            else:
                decisions.append(FieldBudget(
                    field=f,
                    action="drop",
                    reason=f"salience {f.salience:.2f} below threshold {config.drop_below_salience}",
                ))
        else:
            decisions.append(FieldBudget(
                field=f,
                action="include",
                reason=f"salience {f.salience:.2f} above threshold {config.drop_below_salience}",
            ))

    return decisions
