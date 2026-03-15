"""CSV entity/rule extraction for domain knowledge.

Zero external dependencies — uses stdlib ``csv`` module.

Supports two CSV layouts:
1. **Entity-per-row**: each row defines a field; an ``entity`` column groups
   rows into entities. Columns: entity, field_name, type, description, nullable, pii.
2. **Entity-per-file**: no ``entity`` column; filename is the entity name;
   each row is a field. Columns: field_name, type, description, nullable, pii.

Layout is auto-detected from column headers.
"""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from .ir import Certainty, IREntity, IRField, IRSource, IRWarning, Severity


# ── CSV Parser ──


@dataclass
class CSVData:
    """Parsed CSV data."""

    headers: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)
    layout: str = ""  # "entity_per_row" or "entity_per_file"


def csv_parse(text: str, *, filename: str = "") -> CSVData:
    """Parse CSV text into structured data with layout detection.

    Returns a CSVData object with headers, rows, and detected layout.
    """
    if not text.strip():
        return CSVData()

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    rows = list(reader)

    # Normalize headers to lowercase for matching
    norm_headers = [h.strip().lower() for h in headers]

    # Auto-detect layout
    layout = "entity_per_file"  # default
    if "entity" in norm_headers or "entity_name" in norm_headers:
        layout = "entity_per_row"

    return CSVData(
        headers=[h.strip() for h in headers],
        rows=rows,
        layout=layout,
    )


# ── Entity Extraction ──


def extract_entities_from_csv(
    data: CSVData,
    *,
    filename: str = "",
) -> tuple[list[IREntity], list[IRField], list[IRWarning]]:
    """Extract IREntities and standalone rules from parsed CSV data.

    Returns (entities, standalone_rules, warnings).
    """
    entities: list[IREntity] = []
    standalone_rules: list[IRField] = []
    warnings: list[IRWarning] = []

    if not data.rows:
        return entities, standalone_rules, warnings

    source = IRSource(file=filename)

    if data.layout == "entity_per_row":
        entities = _extract_entity_per_row(data, source)
    else:
        entities = _extract_entity_per_file(data, source, filename)

    return entities, standalone_rules, warnings


def _extract_entity_per_row(
    data: CSVData, source: IRSource
) -> list[IREntity]:
    """Extract entities from entity-per-row layout.

    Groups rows by the ``entity`` column, creating one IREntity per group.
    """
    # Find the entity column (case-insensitive)
    norm_headers = {h.strip().lower(): h.strip() for h in data.headers}
    entity_col = norm_headers.get("entity", norm_headers.get("entity_name", ""))

    if not entity_col:
        return []

    # Group rows by entity name
    groups: dict[str, list[dict[str, str]]] = {}
    for row in data.rows:
        entity_name = row.get(entity_col, "").strip()
        if not entity_name:
            continue
        if entity_name not in groups:
            groups[entity_name] = []
        groups[entity_name].append(row)

    # Convert each group to an IREntity
    entities: list[IREntity] = []
    for entity_name, rows in groups.items():
        fields = _rows_to_fields(rows, entity_col, source, data.headers)
        entity = IREntity(
            name=_canonicalize_name(entity_name),
            fields=fields,
            sources=[source],
        )
        entities.append(entity)

    return entities


def _extract_entity_per_file(
    data: CSVData, source: IRSource, filename: str
) -> list[IREntity]:
    """Extract a single entity from entity-per-file layout.

    The entity name is derived from the filename.
    """
    entity_name = _entity_name_from_filename(filename)
    fields = _rows_to_fields(data.rows, "", source, data.headers)

    return [
        IREntity(
            name=entity_name,
            fields=fields,
            sources=[source],
        )
    ]


def _rows_to_fields(
    rows: list[dict[str, str]],
    entity_col: str,
    source: IRSource,
    headers: list[str],
) -> list[IRField]:
    """Convert CSV rows into IRField objects.

    Each row becomes one field. The field name comes from the ``field_name``
    or ``name`` column. Type, description, nullable, pii columns are compressed
    into the value.
    """
    norm_headers = {h.strip().lower(): h.strip() for h in headers}
    field_col = norm_headers.get(
        "field_name",
        norm_headers.get("field", norm_headers.get("name", norm_headers.get("column_name", ""))),
    )
    type_col = norm_headers.get("type", norm_headers.get("data_type", ""))
    desc_col = norm_headers.get("description", norm_headers.get("desc", ""))
    nullable_col = norm_headers.get("nullable", norm_headers.get("null", ""))
    pii_col = norm_headers.get("pii", norm_headers.get("pii_classification", ""))

    fields: list[IRField] = []

    for row in rows:
        field_name = row.get(field_col, "").strip() if field_col else ""
        if not field_name:
            # If no field_name column, skip
            continue

        # Build compressed value
        parts: list[str] = []

        field_type = row.get(type_col, "").strip() if type_col else ""
        if field_type:
            parts.append(field_type)

        nullable_val = row.get(nullable_col, "").strip().lower() if nullable_col else ""
        if nullable_val in ("true", "yes", "1"):
            parts.append("nullable")

        pii_val = row.get(pii_col, "").strip().lower() if pii_col else ""
        if pii_val in ("true", "yes", "1"):
            parts.append("pii")

        desc_val = row.get(desc_col, "").strip() if desc_col else ""

        # Compose the compressed field value
        key = _hyphenate(field_name).upper()

        if parts:
            value = f"{field_name}({','.join(parts)})"
        else:
            value = field_name

        if desc_val:
            value += f"  # {desc_val}"

        fields.append(
            IRField(
                key="FIELD",
                value=value,
                raw_value=row,
                source=source,
                certainty=Certainty.EXPLICIT,
            )
        )

    return fields


def _entity_name_from_filename(filename: str) -> str:
    """Derive an entity name from a filename.

    ``customer.csv`` → ``CUSTOMER``
    ``data/order_items.csv`` → ``ORDER-ITEMS``
    """
    basename = os.path.basename(filename)
    name, _ = os.path.splitext(basename)
    return _canonicalize_name(name)


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
