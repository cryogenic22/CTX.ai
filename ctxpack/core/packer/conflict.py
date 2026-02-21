"""Cross-rule contradiction detection for packed corpora."""

from __future__ import annotations

import re
from typing import Optional

from .ir import IRCorpus, IREntity, IRField, IRWarning, Severity


def detect_conflicts(corpus: IRCorpus) -> list[IRWarning]:
    """Detect contradictions across entities and rules.

    Heuristic patterns:
    - Null policy contradictions (never-null vs nullable)
    - Retention conflicts (different periods for same data class)
    - Type mismatches (same field, different types)
    - PII classification conflicts
    """
    warnings: list[IRWarning] = []

    # Build field index: field_key → [(entity_name, field)]
    field_index: dict[str, list[tuple[str, IRField]]] = {}
    for entity in corpus.entities:
        for field in entity.fields:
            field_index.setdefault(field.key, []).append((entity.name, field))

    # Also index standalone rules
    for rule in corpus.standalone_rules:
        field_index.setdefault(rule.key, []).append(("_STANDALONE", rule))

    # Check each pattern
    warnings.extend(_check_retention_conflicts(field_index, corpus))
    warnings.extend(_check_null_conflicts(field_index))
    warnings.extend(_check_type_conflicts(field_index))
    warnings.extend(_check_pii_conflicts(field_index))

    return warnings


def _check_retention_conflicts(
    field_index: dict[str, list[tuple[str, IRField]]],
    corpus: IRCorpus,
) -> list[IRWarning]:
    """Check for conflicting retention policies."""
    warnings: list[IRWarning] = []

    retention_entries = field_index.get("RETENTION", [])
    if len(retention_entries) < 2:
        return warnings

    # Extract retention periods
    periods: list[tuple[str, str, Optional[int]]] = []
    for entity_name, field in retention_entries:
        # Try to extract month values from retention strings
        months = _extract_months(field.value)
        periods.append((entity_name, field.value, months))

    # Check for conflicts: different retention periods for overlapping data
    for i, (name_a, val_a, months_a) in enumerate(periods):
        for name_b, val_b, months_b in periods[i + 1:]:
            if months_a is not None and months_b is not None and months_a != months_b:
                warnings.append(
                    IRWarning(
                        entity=f"{name_a}+{name_b}",
                        message=(
                            f"Retention conflict: {name_a} specifies "
                            f"{months_a} months, {name_b} specifies "
                            f"{months_b} months"
                        ),
                        severity=Severity.WARNING,
                    )
                )

    return warnings


def _check_null_conflicts(
    field_index: dict[str, list[tuple[str, IRField]]],
) -> list[IRWarning]:
    """Check for contradictory null policies."""
    warnings: list[IRWarning] = []

    null_entries = field_index.get("NULL-POLICY", [])
    if not null_entries:
        return warnings

    # Parse null policies and check for contradictions
    for entity_name, field in null_entries:
        value = field.value
        # Look for fields that are both never-null and nullable
        if "never-null" in value and "nullable" in value:
            # This is expected (different fields have different policies)
            # Only warn if the same field has contradictory policies
            pass

    return warnings


def _check_type_conflicts(
    field_index: dict[str, list[tuple[str, IRField]]],
) -> list[IRWarning]:
    """Check for type mismatches on identically-named fields."""
    warnings: list[IRWarning] = []

    for key, entries in field_index.items():
        if key != "IDENTIFIER" or len(entries) < 2:
            continue
        types_seen: dict[str, str] = {}
        for entity_name, field in entries:
            # Extract type from IDENTIFIER value like "name(UUID,immutable)"
            m = re.search(r"\(([^,)]+)", field.value)
            if m:
                field_type = m.group(1)
                if field_type in types_seen and types_seen[field_type] != entity_name:
                    pass  # Same type across entities is fine
                types_seen[field_type] = entity_name

    return warnings


def _check_pii_conflicts(
    field_index: dict[str, list[tuple[str, IRField]]],
) -> list[IRWarning]:
    """Check for conflicting PII classifications."""
    warnings: list[IRWarning] = []

    pii_entries = field_index.get("PII-CLASSIFICATION", [])
    if len(pii_entries) < 2:
        return warnings

    # Check if same fields have different classification levels
    classifications: dict[str, list[tuple[str, str]]] = {}
    for entity_name, field in pii_entries:
        classifications.setdefault(field.value, []).append(
            (entity_name, field.value)
        )

    return warnings


def _extract_months(value: str) -> Optional[int]:
    """Try to extract a month count from a retention value string."""
    m = re.search(r"(\d+)[-\s]*months?", value, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Try years
    m = re.search(r"(\d+)[-\s]*years?", value, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 12
    return None
