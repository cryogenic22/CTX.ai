"""Cross-rule contradiction detection for packed corpora."""

from __future__ import annotations

import re
from typing import Optional

from .ir import CONDITIONAL_RE, IRCorpus, IREntity, IRField, IRWarning, Severity

# Precompiled regex for type extraction from IDENTIFIER values
_IDENTIFIER_TYPE_RE = re.compile(r"\(([^,)]+)")

# Precompiled regex for extracting field:level pairs from PII-CLASSIFICATION
_PII_FIELD_RE = re.compile(r"(\w[\w-]*)→(\w+)")


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
    warnings.extend(_check_null_conflicts(field_index, corpus))
    warnings.extend(_check_type_conflicts(field_index))
    warnings.extend(_check_pii_conflicts(field_index))
    warnings.extend(_check_conditional_conflicts(field_index))
    warnings.extend(_check_version_conflicts(field_index))

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
    corpus: IRCorpus,
) -> list[IRWarning]:
    """Check for contradictory null policies.

    Cross-checks NULL-POLICY fields against IDENTIFIER required flags.
    If same entity has a required identifier + nullable policy on same
    logical field → warning.
    """
    warnings: list[IRWarning] = []

    # Build per-entity required identifiers
    required_fields: dict[str, set[str]] = {}  # entity → set of required field names
    for entity_name, field in field_index.get("IDENTIFIER", []):
        val = field.value.lower()
        if "required" in val:
            # Extract field name (first part before parenthesis)
            fname = field.value.split("(")[0].strip().lower()
            if fname:
                required_fields.setdefault(entity_name, set()).add(fname)

    # Check null policies against required identifiers
    for entity_name, field in field_index.get("NULL-POLICY", []):
        val_lower = field.value.lower()
        # Look for nullable field names
        nullable_fields = set()
        if "nullable" in val_lower:
            # Parse patterns like "field_name(nullable)" or "field→nullable"
            for part in re.split(r"[+|,]", field.value):
                part = part.strip().lower()
                if "nullable" in part:
                    fname = re.split(r"[→(]", part)[0].strip()
                    if fname and fname != "nullable":
                        nullable_fields.add(fname)

        # Cross-check: if entity has required identifier that's also nullable
        if entity_name in required_fields:
            overlap = required_fields[entity_name] & nullable_fields
            for fname in overlap:
                warnings.append(
                    IRWarning(
                        entity=entity_name,
                        message=(
                            f"Null conflict: '{fname}' is marked required "
                            f"in IDENTIFIER but nullable in NULL-POLICY"
                        ),
                        severity=Severity.WARNING,
                    )
                )

    # Also check for internal contradictions: never-null + nullable on same field
    for entity_name, field in field_index.get("NULL-POLICY", []):
        val_lower = field.value.lower()
        if "never-null" in val_lower and "nullable" in val_lower:
            # Extract which fields are never-null and which are nullable
            never_null_fields = set()
            nullable_fields = set()
            for part in re.split(r"[+|,]", field.value):
                part_lower = part.strip().lower()
                fname = re.split(r"[→(]", part_lower)[0].strip()
                if not fname:
                    continue
                if "never-null" in part_lower:
                    never_null_fields.add(fname)
                elif "nullable" in part_lower:
                    nullable_fields.add(fname)
            overlap = never_null_fields & nullable_fields
            for fname in overlap:
                warnings.append(
                    IRWarning(
                        entity=entity_name,
                        message=(
                            f"Null conflict: '{fname}' is both never-null "
                            f"and nullable in NULL-POLICY"
                        ),
                        severity=Severity.WARNING,
                    )
                )

    return warnings


def _check_type_conflicts(
    field_index: dict[str, list[tuple[str, IRField]]],
) -> list[IRWarning]:
    """Check for type mismatches on identically-named fields.

    If entity A's identifier is UUID and entity B references it as int,
    that's a type mismatch.
    """
    warnings: list[IRWarning] = []

    # Build a map of entity_name → identifier field name → type
    entity_id_types: dict[str, dict[str, str]] = {}
    for entity_name, field in field_index.get("IDENTIFIER", []):
        m = _IDENTIFIER_TYPE_RE.search(field.value)
        if m:
            field_name = field.value.split("(")[0].strip().lower()
            field_type = m.group(1).strip().lower()
            entity_id_types.setdefault(entity_name, {})[field_name] = field_type

    # Check BELONGS-TO references: if entity A references entity B's id
    # with a different type annotation, that's a conflict
    for entity_name, field in field_index.get("BELONGS-TO", []):
        # Parse target entity from @ENTITY-X(field) pattern
        ref_match = re.search(r"@ENTITY-(\w[\w-]*)\(([^)]*)\)", field.value)
        if not ref_match:
            continue
        target_entity = ref_match.group(1)
        ref_field = ref_match.group(2).split(",")[0].strip().lower()

        # Check if this entity has the FK field with a type
        for ename, efield in field_index.get("IDENTIFIER", []):
            if ename != entity_name:
                continue
            fk_match = _IDENTIFIER_TYPE_RE.search(efield.value)
            if not fk_match:
                continue
            fk_name = efield.value.split("(")[0].strip().lower()
            fk_type = fk_match.group(1).strip().lower()

            # Compare with target entity's identifier type
            if target_entity in entity_id_types:
                for target_field, target_type in entity_id_types[target_entity].items():
                    if fk_type != target_type and fk_name == ref_field:
                        warnings.append(
                            IRWarning(
                                entity=f"{entity_name}+{target_entity}",
                                message=(
                                    f"Type conflict: {entity_name}.{fk_name} is "
                                    f"{fk_type} but {target_entity}.{target_field} "
                                    f"is {target_type}"
                                ),
                                severity=Severity.WARNING,
                            )
                        )

    # Also check: same field name across entities with different types
    id_entries = field_index.get("IDENTIFIER", [])
    if len(id_entries) >= 2:
        # Group by field name
        name_type_map: dict[str, list[tuple[str, str]]] = {}
        for entity_name, field in id_entries:
            fname = field.value.split("(")[0].strip().lower()
            m = _IDENTIFIER_TYPE_RE.search(field.value)
            if m and fname:
                ftype = m.group(1).strip().lower()
                name_type_map.setdefault(fname, []).append((entity_name, ftype))

        for fname, entries in name_type_map.items():
            types_seen: dict[str, str] = {}  # type → first entity
            for entity_name, ftype in entries:
                if ftype in types_seen:
                    continue  # same type is fine
                for prev_type, prev_entity in types_seen.items():
                    if prev_type != ftype:
                        warnings.append(
                            IRWarning(
                                entity=f"{prev_entity}+{entity_name}",
                                message=(
                                    f"Type conflict: '{fname}' is {prev_type} "
                                    f"in {prev_entity} but {ftype} in {entity_name}"
                                ),
                                severity=Severity.WARNING,
                            )
                        )
                types_seen[ftype] = entity_name

    return warnings


def _check_pii_conflicts(
    field_index: dict[str, list[tuple[str, IRField]]],
) -> list[IRWarning]:
    """Check for conflicting PII classifications.

    If the same field appears with different PII levels across entities
    (e.g., 'email' as RESTRICTED in one, CONFIDENTIAL in another),
    emit a classification conflict warning.
    """
    warnings: list[IRWarning] = []

    pii_entries = field_index.get("PII-CLASSIFICATION", [])
    if len(pii_entries) < 2:
        return warnings

    # Build field → [(entity, level)] map
    field_levels: dict[str, list[tuple[str, str]]] = {}
    for entity_name, field in pii_entries:
        # Parse field→level patterns
        for m in _PII_FIELD_RE.finditer(field.value):
            fname = m.group(1).lower()
            level = m.group(2).upper()
            field_levels.setdefault(fname, []).append((entity_name, level))

        # Also handle simple values like "RESTRICTED" or "email+phone→RESTRICTED"
        if not _PII_FIELD_RE.search(field.value):
            # Whole entity PII level
            level = field.value.strip().upper()
            field_levels.setdefault("_entity", []).append((entity_name, level))

    # Check for conflicts
    for fname, entries in field_levels.items():
        if len(entries) < 2:
            continue
        levels_seen: dict[str, str] = {}  # level → first entity
        for entity_name, level in entries:
            if level in levels_seen:
                continue
            for prev_level, prev_entity in levels_seen.items():
                if prev_level != level:
                    field_desc = f"'{fname}'" if fname != "_entity" else "PII classification"
                    warnings.append(
                        IRWarning(
                            entity=f"{prev_entity}+{entity_name}",
                            message=(
                                f"PII conflict: {field_desc} is {prev_level} "
                                f"in {prev_entity} but {level} in {entity_name}"
                            ),
                            severity=Severity.WARNING,
                        )
                    )
            levels_seen[level] = entity_name

    return warnings


def _check_conditional_conflicts(
    field_index: dict[str, list[tuple[str, IRField]]],
) -> list[IRWarning]:
    """Check for contradictory conditional guards on same field.

    If the same entity+key has two conditional guards with opposing conditions
    (e.g., only-if(active) vs only-if(inactive)), emit a warning.
    """
    warnings: list[IRWarning] = []

    # Group fields by (entity, key) that contain conditionals
    cond_fields: dict[tuple[str, str], list[tuple[str, IRField]]] = {}
    for key, entries in field_index.items():
        for entity_name, fld in entries:
            if CONDITIONAL_RE.search(fld.value):
                cond_fields.setdefault((entity_name, key), []).append(
                    (entity_name, fld)
                )

    # Check for contradictions within same (entity, key)
    for (entity_name, key), entries in cond_fields.items():
        if len(entries) < 2:
            continue
        conditions: list[str] = []
        for _, fld in entries:
            for m in CONDITIONAL_RE.finditer(fld.value):
                conditions.append(m.group(1).strip().lower())

        # Detect negation pairs: "active" vs "not active", "active" vs "inactive"
        for i, cond_a in enumerate(conditions):
            for cond_b in conditions[i + 1:]:
                if _are_opposing_conditions(cond_a, cond_b):
                    warnings.append(
                        IRWarning(
                            entity=entity_name,
                            message=(
                                f"Conditional conflict on {key}: "
                                f"'{cond_a}' vs '{cond_b}'"
                            ),
                            severity=Severity.WARNING,
                        )
                    )

    return warnings


def _are_opposing_conditions(a: str, b: str) -> bool:
    """Heuristic check for opposing conditions."""
    # "X" vs "not X"
    if a == f"not {b}" or b == f"not {a}":
        return True
    # "X" vs "!X"
    if a == f"!{b}" or b == f"!{a}":
        return True
    # "active" vs "inactive", "valid" vs "invalid"
    if a.startswith("in") and a[2:] == b:
        return True
    if b.startswith("in") and b[2:] == a:
        return True
    return False


def _check_version_conflicts(
    field_index: dict[str, list[tuple[str, IRField]]],
) -> list[IRWarning]:
    """Check for same field with different values from different source versions.

    If entity A's FIELD has value X from source v1 and value Y from source v2,
    emit a version conflict warning.
    """
    warnings: list[IRWarning] = []

    for key, entries in field_index.items():
        # Group by entity
        by_entity: dict[str, list[IRField]] = {}
        for entity_name, fld in entries:
            by_entity.setdefault(entity_name, []).append(fld)

        for entity_name, fields in by_entity.items():
            # Only check fields that have version info on their sources
            versioned: list[tuple[str, str]] = []  # (version, value)
            for fld in fields:
                src = fld.source
                if src and src.version:
                    versioned.append((src.version, fld.value))
                for extra in fld.additional_sources:
                    if extra.version:
                        versioned.append((extra.version, fld.value))

            if len(versioned) < 2:
                continue

            # Check for differing values across versions
            version_values: dict[str, str] = {}
            for ver, val in versioned:
                if ver in version_values:
                    if version_values[ver] != val:
                        # Same version, different values — already caught by other checks
                        pass
                else:
                    version_values[ver] = val

            # Compare across versions
            ver_list = list(version_values.items())
            for i, (ver_a, val_a) in enumerate(ver_list):
                for ver_b, val_b in ver_list[i + 1:]:
                    if val_a != val_b:
                        warnings.append(
                            IRWarning(
                                entity=entity_name,
                                message=(
                                    f"Version conflict on {key}: "
                                    f"'{val_a}' (v{ver_a}) vs "
                                    f"'{val_b}' (v{ver_b})"
                                ),
                                severity=Severity.WARNING,
                            )
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
