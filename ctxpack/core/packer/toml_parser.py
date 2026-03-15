"""TOML entity/rule extraction for domain knowledge.

Zero external dependencies — uses stdlib ``tomllib`` (Python 3.11+) with
a minimal fallback parser for Python 3.10.

Entity detection heuristics:
- Top-level TOML table ``[customer]`` → ENTITY-CUSTOMER (if entity-like)
- Nested ``[entity.customer]`` → explicit entity grouping
- Key-value pairs within tables → IRField objects
- Top-level non-entity keys → standalone rules
"""

from __future__ import annotations

import sys
from typing import Any, Optional

from .ir import Certainty, IREntity, IRField, IRSource, IRWarning, Severity

# ── TOML Parser ──

# Use stdlib tomllib on 3.11+; fallback for older Pythons.
if sys.version_info >= (3, 11):
    import tomllib as _tomllib

    def toml_parse(text: str, *, filename: str = "") -> dict[str, Any]:
        """Parse a TOML string into Python objects."""
        try:
            return _tomllib.loads(text)
        except Exception as e:
            raise ValueError(f"{filename}: TOML parse error: {e}") from e

else:
    # Minimal fallback for Python 3.10 — covers basic key=value and [table] syntax.
    def toml_parse(text: str, *, filename: str = "") -> dict[str, Any]:  # type: ignore[misc]
        """Minimal TOML parser for Python < 3.11."""
        return _fallback_toml_parse(text, filename=filename)


def _fallback_toml_parse(text: str, *, filename: str = "") -> dict[str, Any]:
    """Very basic TOML subset parser for pre-3.11 Pythons.

    Supports: tables ``[name]``, dotted tables ``[a.b]``, basic key=value,
    strings, integers, booleans, arrays. Not a full TOML implementation.
    """
    result: dict[str, Any] = {}
    current_table: dict[str, Any] = result
    current_path: list[str] = []

    for lineno, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Table header: [name] or [a.b.c]
        if stripped.startswith("[") and not stripped.startswith("[["):
            table_name = stripped.strip("[]").strip()
            parts = [p.strip() for p in table_name.split(".")]
            current_path = parts
            # Navigate/create nested path
            current_table = result
            for part in parts:
                if part not in current_table:
                    current_table[part] = {}
                current_table = current_table[part]
            continue

        # Key = value
        if "=" in stripped:
            key, _, val_str = stripped.partition("=")
            key = key.strip().strip('"')
            val_str = val_str.strip()
            # Strip inline comment
            val_str = _strip_inline_comment_toml(val_str)
            current_table[key] = _parse_toml_value(val_str)

    return result


def _strip_inline_comment_toml(text: str) -> str:
    """Strip inline comments respecting quotes."""
    in_quote = None
    for i, ch in enumerate(text):
        if ch in ('"', "'") and in_quote is None:
            in_quote = ch
        elif ch == in_quote:
            in_quote = None
        elif ch == "#" and in_quote is None:
            return text[:i].rstrip()
    return text


def _parse_toml_value(val: str) -> Any:
    """Parse a TOML value string into a Python object."""
    if not val:
        return ""

    # Quoted string
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        return val[1:-1]

    # Boolean
    if val == "true":
        return True
    if val == "false":
        return False

    # Array
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        items = []
        for item in inner.split(","):
            item = item.strip()
            if item:
                items.append(_parse_toml_value(item))
        return items

    # Integer
    try:
        return int(val)
    except ValueError:
        pass

    # Float
    try:
        return float(val)
    except ValueError:
        pass

    return val


# ── Entity Extraction ──


def extract_entities_from_toml(
    data: dict[str, Any],
    *,
    filename: str = "",
) -> tuple[list[IREntity], list[IRField], list[IRWarning]]:
    """Extract IREntities and standalone rules from parsed TOML data.

    Returns (entities, standalone_rules, warnings).
    """
    entities: list[IREntity] = []
    standalone_rules: list[IRField] = []
    warnings: list[IRWarning] = []

    if not data:
        return entities, standalone_rules, warnings

    source = IRSource(file=filename)

    # Case 1: Explicit ``[entity.X]`` grouping — ``data["entity"]`` is a dict of entities
    if "entity" in data and isinstance(data["entity"], dict):
        entity_group = data["entity"]
        for ent_name, ent_data in entity_group.items():
            if isinstance(ent_data, dict):
                entity = _extract_single_entity(ent_name, ent_data, source)
                entities.append(entity)
        # Process remaining top-level keys as standalone rules
        for k, v in data.items():
            if k == "entity":
                continue
            if isinstance(v, dict) and _looks_like_entity(v):
                entity = _extract_single_entity(k, v, source)
                entities.append(entity)
            else:
                standalone_rules.append(
                    IRField(
                        key=_hyphenate(k).upper(),
                        value=_compress_value(v),
                        raw_value=v,
                        source=source,
                    )
                )
        return entities, standalone_rules, warnings

    # Case 2: Each top-level table is an entity (if it looks entity-like)
    for k, v in data.items():
        if isinstance(v, dict) and _looks_like_entity(v):
            entity = _extract_single_entity(k, v, source)
            entities.append(entity)
        elif isinstance(v, dict):
            # Even non-entity-like dicts with multiple keys are likely entities in TOML
            # TOML tables are structural — treat any table with fields as an entity
            entity = _extract_single_entity(k, v, source)
            entities.append(entity)
        else:
            # Bare top-level key=value → standalone rule
            standalone_rules.append(
                IRField(
                    key=_hyphenate(k).upper(),
                    value=_compress_value(v),
                    raw_value=v,
                    source=source,
                )
            )

    return entities, standalone_rules, warnings


def _extract_single_entity(
    name: str, data: dict[str, Any], source: IRSource
) -> IREntity:
    """Extract one IREntity from a TOML table."""
    canon_name = _canonicalize_name(name)
    fields: list[IRField] = []
    aliases: list[str] = []
    annotations: dict[str, str] = {}

    for key, val in data.items():
        if key == "aliases":
            if isinstance(val, list):
                aliases = [str(a) for a in val]
            continue
        if key == "description":
            annotations["description"] = str(val)
            continue

        comp_key = _hyphenate(key).upper()
        comp_val = _compress_value(val)
        fields.append(
            IRField(
                key=comp_key,
                value=comp_val,
                raw_value=val,
                source=source,
                certainty=Certainty.EXPLICIT,
            )
        )

    return IREntity(
        name=canon_name,
        aliases=aliases,
        fields=fields,
        annotations=annotations,
        sources=[source],
    )


# ── Heuristics ──


def _looks_like_entity(data: dict) -> bool:
    """Heuristic: does this dict look like an entity definition?"""
    entity_keys = {
        "identifier", "golden_source", "match_rules", "pii",
        "pii_classification", "retention", "fields", "attributes",
        "status", "relationships", "constraints", "properties",
        "type", "schema", "id", "uuid", "has_many", "has_one",
        "references", "depends_on", "primary_key",
    }
    return bool(set(data.keys()) & entity_keys)


# ── Compression helpers ──


def _compress_value(val: Any) -> str:
    """Compress any Python value to L2 notation."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return val.replace("_", "-")
    if isinstance(val, list):
        items = [_compress_value(v) for v in val]
        return "+".join(items)
    if isinstance(val, dict):
        parts = []
        for k, v in val.items():
            cv = _compress_value(v)
            parts.append(f"{_hyphenate(k)}({cv})")
        return "+".join(parts)
    return str(val)


def _hyphenate(text: str) -> str:
    return text.replace(" ", "-").replace("_", "-")


def _canonicalize_name(name: str) -> str:
    name = name.upper().replace("_", "-").replace(" ", "-")
    for prefix in ("ENTITY-", "ENTITY_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name
