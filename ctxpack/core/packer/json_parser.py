"""JSON entity/rule extraction for domain knowledge.

Zero external dependencies — uses stdlib ``json`` module.

Entity detection heuristics:
- Top-level object with ``"entity"`` or ``"name"`` key → entity
- JSON Schema (``"type": "object", "properties": {...}``) → entity with fields
- Arrays of objects with consistent keys → entity per object pattern
- Nested ``"rules"`` or ``"policies"`` keys → standalone rules
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .ir import Certainty, IREntity, IRField, IRSource, IRWarning, Severity


def json_parse(text: str, *, filename: str = "") -> Any:
    """Parse JSON text into Python objects."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{filename}: JSON parse error: {e}") from e


def extract_entities_from_json(
    data: Any,
    *,
    filename: str = "",
) -> tuple[list[IREntity], list[IRField], list[IRWarning]]:
    """Extract IREntities and standalone rules from parsed JSON data.

    Returns (entities, standalone_rules, warnings).
    """
    entities: list[IREntity] = []
    standalone_rules: list[IRField] = []
    warnings: list[IRWarning] = []

    source = IRSource(file=filename)

    if isinstance(data, dict):
        _extract_from_dict(data, source, entities, standalone_rules, warnings)
    elif isinstance(data, list):
        _extract_from_array(data, source, entities, standalone_rules, warnings)

    return entities, standalone_rules, warnings


def _extract_from_dict(
    data: dict,
    source: IRSource,
    entities: list[IREntity],
    standalone_rules: list[IRField],
    warnings: list[IRWarning],
) -> None:
    """Extract entities from a top-level JSON object."""

    # Case 1: Explicit entity definition (has "entity" or "name" + entity-like fields)
    if "entity" in data:
        entity = _extract_single_entity(data, source)
        entities.append(entity)
        return

    # Case 2: JSON Schema object
    if _is_json_schema(data):
        entity = _extract_from_schema(data, source)
        if entity:
            entities.append(entity)
        return

    # Case 3: Rules/policies at top level
    if "rules" in data or "policies" in data:
        rules_data = data.get("rules", data.get("policies", []))
        _extract_rules(rules_data, source, standalone_rules)
        # Process remaining keys for entities
        for k, v in data.items():
            if k in ("rules", "policies"):
                continue
            if isinstance(v, dict) and _looks_like_entity(v):
                entity = _extract_single_entity({"entity": k, **v}, source)
                entities.append(entity)

        return

    # Case 4: Multiple entities (each top-level key is an entity)
    for k, v in data.items():
        if isinstance(v, dict) and _looks_like_entity(v):
            entity = _extract_single_entity({"entity": k, **v}, source)
            entities.append(entity)
        elif isinstance(v, dict) and _is_json_schema(v):
            entity = _extract_from_schema(v, source, name_override=k)
            if entity:
                entities.append(entity)
        elif isinstance(v, list) and v and all(isinstance(item, dict) for item in v):
            # Array of objects with consistent keys → entity pattern
            entity = _extract_from_object_array(k, v, source)
            if entity:
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


def _extract_from_array(
    data: list,
    source: IRSource,
    entities: list[IREntity],
    standalone_rules: list[IRField],
    warnings: list[IRWarning],
) -> None:
    """Extract entities from a top-level JSON array."""
    if not data:
        return

    # Array of entity-like objects
    if all(isinstance(item, dict) for item in data):
        for item in data:
            if "entity" in item or "name" in item:
                entity = _extract_single_entity(item, source)
                entities.append(entity)
            elif _looks_like_entity(item):
                name = item.get("name", item.get("id", "UNKNOWN"))
                entity = _extract_single_entity({"entity": str(name), **item}, source)
                entities.append(entity)


def _extract_single_entity(data: dict, source: IRSource) -> IREntity:
    """Extract one IREntity from a JSON object with an ``entity`` key."""
    name = _canonicalize_name(str(data.get("entity", data.get("name", "UNKNOWN"))))
    aliases: list[str] = []
    fields: list[IRField] = []
    annotations: dict[str, str] = {}

    description = str(data.get("description", ""))

    for key, val in data.items():
        if key in ("entity", "name"):
            continue
        if key == "aliases":
            if isinstance(val, list):
                aliases = [str(a) for a in val]
            continue
        if key == "description":
            annotations["description"] = description
            continue

        comp_key, comp_val = _compress_field(key, val)
        fields.append(
            IRField(
                key=comp_key,
                value=comp_val,
                raw_value=val,
                source=source,
            )
        )

    return IREntity(
        name=name,
        aliases=aliases,
        fields=fields,
        annotations=annotations,
        sources=[source],
    )


def _extract_from_schema(
    data: dict,
    source: IRSource,
    *,
    name_override: Optional[str] = None,
) -> Optional[IREntity]:
    """Extract an entity from a JSON Schema object definition."""
    title = name_override or data.get("title", data.get("$id", ""))
    if not title:
        return None

    name = _canonicalize_name(str(title))
    fields: list[IRField] = []
    annotations: dict[str, str] = {}

    if "description" in data:
        annotations["description"] = str(data["description"])

    properties = data.get("properties", {})
    required_fields = set(data.get("required", []))

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue

        prop_type = prop_schema.get("type", "")
        prop_desc = prop_schema.get("description", "")
        flags = []

        if prop_name in required_fields:
            flags.append("required")
        if prop_schema.get("readOnly"):
            flags.append("immutable")
        if prop_schema.get("uniqueItems"):
            flags.append("unique")

        parts = []
        if prop_type:
            parts.append(str(prop_type))
        parts.extend(flags)

        if parts:
            value = f"{prop_name}({','.join(parts)})"
        else:
            value = prop_name

        if prop_desc:
            value += f"  # {prop_desc}"

        fields.append(
            IRField(
                key="FIELD",
                value=value,
                raw_value=prop_schema,
                source=source,
            )
        )

    return IREntity(
        name=name,
        fields=fields,
        annotations=annotations,
        sources=[source],
    )


def _extract_from_object_array(
    key: str,
    items: list[dict],
    source: IRSource,
) -> Optional[IREntity]:
    """Extract an entity pattern from an array of similar objects."""
    if len(items) < 2:
        return None

    # Find common keys across all items
    common_keys = set(items[0].keys())
    for item in items[1:]:
        common_keys &= set(item.keys())

    if not common_keys:
        return None

    name = _canonicalize_name(key)
    fields: list[IRField] = []

    # Summarize the pattern rather than listing all items
    fields.append(
        IRField(
            key="COUNT",
            value=str(len(items)),
            raw_value=len(items),
            source=source,
        )
    )
    fields.append(
        IRField(
            key="SCHEMA",
            value="[" + ",".join(sorted(common_keys)) + "]",
            raw_value=list(common_keys),
            source=source,
        )
    )

    return IREntity(
        name=name,
        fields=fields,
        sources=[source],
    )


def _extract_rules(
    data: Any,
    source: IRSource,
    standalone_rules: list[IRField],
) -> None:
    """Extract standalone rules from a rules/policies structure."""
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for k, v in item.items():
                    standalone_rules.append(
                        IRField(
                            key=_hyphenate(k).upper(),
                            value=_compress_value(v),
                            raw_value=v,
                            source=source,
                        )
                    )
    elif isinstance(data, dict):
        for k, v in data.items():
            standalone_rules.append(
                IRField(
                    key=_hyphenate(k).upper(),
                    value=_compress_value(v),
                    raw_value=v,
                    source=source,
                )
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


def _is_json_schema(data: dict) -> bool:
    """Check if this looks like a JSON Schema object definition."""
    return (
        data.get("type") == "object"
        and isinstance(data.get("properties"), dict)
    )


# ── Compression helpers ──


def _compress_field(key: str, val: Any) -> tuple[str, str]:
    """Compress a JSON field to L2 key:value notation."""
    return _hyphenate(key).upper(), _compress_value(val)


def _compress_value(val: Any) -> str:
    """Compress any Python value to L2 notation."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        if " " in val:
            return val.replace(" ", "-").replace("_", "-")
        return val
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
