"""Domain template system for reusable pack configurations.

Templates define expected entity types, required fields, salience weights,
and validation rules for a specific domain. Loaded via ``ctxpack.yaml``
``template:`` key or ``--template`` CLI flag.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from .ir import IRCorpus, IRWarning, Severity
from .yaml_parser import yaml_parse


@dataclass
class EntitySchema:
    """Schema for a single entity type within a domain template."""

    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class DomainTemplate:
    """Reusable domain configuration for packing."""

    name: str = ""
    entity_schemas: dict[str, EntitySchema] = field(default_factory=dict)
    salience_weights: dict[str, float] = field(default_factory=dict)
    field_patterns: dict[str, str] = field(default_factory=dict)


# ── Built-in Templates ──

BUILTIN_TEMPLATES: dict[str, DomainTemplate] = {
    "pharma": DomainTemplate(
        name="pharma",
        entity_schemas={
            "DRUG": EntitySchema(
                required_fields=["IDENTIFIER", "ACTIVE-INGREDIENT", "DOSAGE-FORM"],
                optional_fields=["CONTRAINDICATIONS", "INTERACTIONS", "SIDE-EFFECTS",
                                 "STORAGE", "RETENTION"],
                description="Pharmaceutical drug product",
            ),
            "CLINICAL-TRIAL": EntitySchema(
                required_fields=["IDENTIFIER", "PHASE", "STATUS"],
                optional_fields=["ENDPOINTS", "POPULATION", "DURATION", "SPONSOR"],
                description="Clinical trial study",
            ),
            "PATIENT": EntitySchema(
                required_fields=["IDENTIFIER", "PII-CLASSIFICATION"],
                optional_fields=["DEMOGRAPHICS", "CONSENT-STATUS", "RETENTION"],
                description="Patient record (PII-sensitive)",
            ),
            "ADVERSE-EVENT": EntitySchema(
                required_fields=["IDENTIFIER", "SEVERITY", "BELONGS-TO"],
                optional_fields=["OUTCOME", "REPORTER", "REPORT-DATE"],
                description="Adverse event report",
            ),
        },
        salience_weights={
            "CONTRAINDICATIONS": 2.0,
            "INTERACTIONS": 1.8,
            "PII-CLASSIFICATION": 1.5,
            "SEVERITY": 1.5,
            "ACTIVE-INGREDIENT": 1.3,
        },
        field_patterns={
            "DOSAGE": r"\d+\s*(mg|ml|mcg|g|IU)",
            "PHASE": r"Phase\s*[I1-4]+",
        },
    ),
    "data-platform": DomainTemplate(
        name="data-platform",
        entity_schemas={
            "TABLE": EntitySchema(
                required_fields=["IDENTIFIER", "SCHEMA"],
                optional_fields=["PARTITIONING", "RETENTION", "OWNER", "SLA"],
                description="Data warehouse table",
            ),
            "PIPELINE": EntitySchema(
                required_fields=["IDENTIFIER", "SOURCE", "DESTINATION"],
                optional_fields=["SCHEDULE", "SLA", "OWNER", "RETRY-POLICY"],
                description="Data pipeline / ETL job",
            ),
            "METRIC": EntitySchema(
                required_fields=["IDENTIFIER", "FORMULA"],
                optional_fields=["OWNER", "GRANULARITY", "FRESHNESS-SLA"],
                description="Business metric definition",
            ),
            "DASHBOARD": EntitySchema(
                required_fields=["IDENTIFIER"],
                optional_fields=["OWNER", "REFRESH-RATE", "DATA-SOURCES"],
                description="Analytics dashboard",
            ),
        },
        salience_weights={
            "SLA": 1.8,
            "FORMULA": 1.5,
            "PARTITIONING": 1.3,
            "RETRY-POLICY": 1.2,
        },
        field_patterns={
            "SCHEDULE": r"(cron|daily|hourly|@\w+)",
            "SLA": r"\d+\s*(ms|s|min|h)",
        },
    ),
}


def load_template(name_or_path: str) -> DomainTemplate:
    """Load a domain template by built-in name or file path.

    Args:
        name_or_path: Either a built-in template name (e.g. "pharma")
                      or a path to a YAML template file.

    Returns:
        DomainTemplate instance.

    Raises:
        ValueError: If template name is unknown and path doesn't exist.
    """
    # Check built-in templates first
    if name_or_path in BUILTIN_TEMPLATES:
        return BUILTIN_TEMPLATES[name_or_path]

    # Try as file path
    if os.path.isfile(name_or_path):
        return _load_template_file(name_or_path)

    available = ", ".join(sorted(BUILTIN_TEMPLATES.keys()))
    raise ValueError(
        f"Unknown template '{name_or_path}'. "
        f"Built-in templates: {available}. "
        f"Or provide a path to a template YAML file."
    )


def validate_corpus(
    corpus: IRCorpus,
    template: DomainTemplate,
) -> list[IRWarning]:
    """Validate a corpus against a domain template.

    Checks:
    1. Entities match expected types from the template
    2. Required fields are present for each entity type
    3. Salience weights are applied from the template

    Returns list of IRWarning for missing required fields and unknown entity types.
    """
    warnings: list[IRWarning] = []

    for entity in corpus.entities:
        # Find matching schema (case-insensitive prefix match)
        schema = _find_schema(entity.name, template)
        if schema is None:
            # Unknown entity type — info-level, not blocking
            continue

        # Check required fields
        entity_field_keys = {f.key for f in entity.fields}
        for req in schema.required_fields:
            if req not in entity_field_keys:
                warnings.append(
                    IRWarning(
                        entity=entity.name,
                        message=(
                            f"Template '{template.name}': missing required "
                            f"field '{req}'"
                        ),
                        severity=Severity.WARNING,
                    )
                )

        # Apply salience weights from template
        for fld in entity.fields:
            if fld.key in template.salience_weights:
                fld.salience *= template.salience_weights[fld.key]

    return warnings


def _find_schema(
    entity_name: str,
    template: DomainTemplate,
) -> Optional[EntitySchema]:
    """Find the best matching EntitySchema for an entity name."""
    name_upper = entity_name.upper()
    # Exact match
    if name_upper in template.entity_schemas:
        return template.entity_schemas[name_upper]
    # Prefix match (e.g. DRUG-PRODUCT matches DRUG schema)
    for schema_name, schema in template.entity_schemas.items():
        if name_upper.startswith(schema_name):
            return schema
    return None


def _load_template_file(path: str) -> DomainTemplate:
    """Load a DomainTemplate from a YAML file."""
    with open(path, encoding="utf-8") as f:
        data = yaml_parse(f.read(), filename=path)

    if not isinstance(data, dict):
        return DomainTemplate()

    template = DomainTemplate(
        name=str(data.get("name", os.path.splitext(os.path.basename(path))[0])),
    )

    # Parse entity schemas
    schemas = data.get("entity_schemas") or data.get("entities")
    if isinstance(schemas, dict):
        for name, schema_data in schemas.items():
            if isinstance(schema_data, dict):
                template.entity_schemas[name.upper()] = EntitySchema(
                    required_fields=[
                        str(f) for f in (schema_data.get("required_fields") or [])
                    ],
                    optional_fields=[
                        str(f) for f in (schema_data.get("optional_fields") or [])
                    ],
                    description=str(schema_data.get("description", "")),
                )

    # Parse salience weights
    weights = data.get("salience_weights")
    if isinstance(weights, dict):
        for k, v in weights.items():
            try:
                template.salience_weights[str(k).upper()] = float(v)
            except (ValueError, TypeError):
                pass

    # Parse field patterns
    patterns = data.get("field_patterns")
    if isinstance(patterns, dict):
        template.field_patterns = {str(k): str(v) for k, v in patterns.items()}

    return template
