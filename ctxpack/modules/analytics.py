"""Analytics domain pack compiler.

Parses Bright_Light-style analytics domain packs (YAML) into CtxPack IR,
compiles multiple packs into a unified, deduplicated knowledge base, and
generates an L3 directory index.

Each pack.yaml follows a standard schema:
  version, domain, metadata, vocabulary, fingerprints, ontology,
  experience, guardrails.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Use PyYAML for full YAML support (folded scalars, anchors, etc.)
# These domain packs are standard YAML, not the ctxpack YAML subset.
import yaml

from ctxpack.core.packer.ir import (
    Certainty,
    IRCorpus,
    IREntity,
    IRField,
    IRSource,
    IRWarning,
    Severity,
)


# ── Helpers ──

def _canon(name: str) -> str:
    """Canonicalize a name: uppercase, underscores/spaces to hyphens."""
    return name.upper().replace("_", "-").replace(" ", "-")


def _hyphenate(text: str) -> str:
    return text.replace("_", "-").replace(" ", "-")


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return "+".join(str(v) for v in val)
    if isinstance(val, dict):
        return "+".join(f"{k}({v})" for k, v in val.items())
    return str(val)


# ── Single Pack Parser ──


def parse_domain_pack(
    text: str,
    *,
    filename: str = "",
    domain: str = "",
) -> list[IREntity]:
    """Parse a single analytics domain pack YAML into IREntity objects.

    Extracts:
    - Domain metadata as a top-level entity
    - Each fingerprint column as a field on the domain entity
    - Each metric as a separate entity with definition, grain, formula
    - Each dimension as a separate entity with hierarchy
    - Vocabulary synonyms as aliases
    - Value enums as field constraints
    - Table structures as fields
    - Guardrails (PII, compliance) as fields
    - KBQ templates as fields
    """
    if not text or not text.strip():
        return []

    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        return []

    pack_domain = domain or data.get("domain", "unknown")
    source = IRSource(file=filename)
    entities: list[IREntity] = []

    # ── 1. Domain entity ──
    domain_entity = _build_domain_entity(data, pack_domain, source)
    entities.append(domain_entity)

    # ── 2. Metrics → separate entities ──
    ontology = data.get("ontology", {}) or {}
    for metric in ontology.get("metrics", []) or []:
        entities.append(_build_metric_entity(metric, pack_domain, source))

    # ── 3. Dimensions → separate entities ──
    for dim in ontology.get("dimensions", []) or []:
        entities.append(_build_dimension_entity(dim, pack_domain, source))

    # ── 4. Ontology synonyms → aliases on metric/dimension entities ──
    _apply_ontology_synonyms(ontology.get("synonyms", []) or [], entities)

    return entities


def _build_domain_entity(
    data: dict[str, Any], domain: str, source: IRSource
) -> IREntity:
    """Build the top-level domain entity with metadata, fingerprints, enums, etc."""
    name = _canon(domain)
    aliases: list[str] = []
    fields: list[IRField] = []
    annotations: dict[str, str] = {}

    # Metadata
    meta = data.get("metadata", {}) or {}
    if meta.get("description"):
        annotations["description"] = str(meta["description"])
    if meta.get("title"):
        annotations["title"] = str(meta["title"])
    if meta.get("extends"):
        fields.append(IRField(
            key="EXTENDS",
            value=str(meta["extends"]),
            source=source,
        ))

    # Vocabulary → aliases
    vocab = data.get("vocabulary", {}) or {}
    vocab_entities = vocab.get("entities", {}) or {}
    for generic_term, domain_synonym in vocab_entities.items():
        aliases.append(str(domain_synonym))

    # Agent persona → field
    persona = vocab.get("agent_persona", {}) or {}
    if persona:
        tone = persona.get("tone", "")
        grain = persona.get("preferred_time_grain", "")
        parts = []
        if tone:
            parts.append(f"tone={tone}")
        if grain:
            parts.append(f"grain={grain}")
        if parts:
            fields.append(IRField(
                key="PERSONA",
                value=",".join(parts),
                source=source,
            ))

    # Fingerprint columns → FP-* fields
    fps = data.get("fingerprints", {}) or {}
    for col in fps.get("columns", []) or []:
        col_id = col.get("id", "")
        patterns = col.get("patterns", [])
        desc = col.get("description", "")
        dtypes = col.get("data_types", [])
        confidence = col.get("confidence", "")
        hints = col.get("hints", {}) or {}

        val_parts = []
        if patterns:
            val_parts.append(f"patterns=[{','.join(str(p) for p in patterns)}]")
        if dtypes:
            val_parts.append(f"types=[{','.join(str(t) for t in dtypes)}]")
        if confidence:
            val_parts.append(f"conf={confidence}")
        if hints:
            hint_str = ",".join(f"{k}={v}" for k, v in hints.items())
            val_parts.append(f"hints=({hint_str})")
        if desc:
            val_parts.append(desc)

        fields.append(IRField(
            key=f"FP-{_canon(col_id)}",
            value="; ".join(val_parts),
            raw_value=col,
            source=source,
            salience=float(confidence) if confidence else 0.8,
        ))

    # Value enums → ENUM-* fields
    for val_enum in fps.get("values", []) or []:
        enum_id = val_enum.get("id", "")
        values = val_enum.get("values", [])
        desc = val_enum.get("description", "")
        # Derive a cleaner name: strip "_value" / "_values" suffix
        clean_id = re.sub(r"_?values?$", "", enum_id, flags=re.IGNORECASE)
        if not clean_id:
            clean_id = enum_id

        val_str = ",".join(str(v) for v in values)
        field_val = f"[{val_str}]"
        if desc:
            field_val += f" — {desc}"

        fields.append(IRField(
            key=f"ENUM-{_canon(clean_id)}",
            value=field_val,
            raw_value=val_enum,
            source=source,
        ))

    # Tables → TABLE-* fields
    for table in fps.get("tables", []) or []:
        table_id = table.get("id", "")
        req_cols = table.get("required_columns", [])
        opt_cols = table.get("optional_columns", [])
        desc = table.get("description", "")
        tags = table.get("tags", [])

        parts = []
        if req_cols:
            parts.append(f"required=[{','.join(req_cols)}]")
        if opt_cols:
            parts.append(f"optional=[{','.join(opt_cols)}]")
        if tags:
            parts.append(f"tags=[{','.join(str(t) for t in tags)}]")
        if desc:
            parts.append(desc)

        fields.append(IRField(
            key=f"TABLE-{_canon(table_id)}",
            value="; ".join(parts),
            raw_value=table,
            source=source,
        ))

    # Guardrails → PII and COMPLIANCE fields
    guardrails = data.get("guardrails", {}) or {}
    pii_patterns = guardrails.get("pii_patterns", []) or []
    if pii_patterns:
        pii_parts = []
        for pii in pii_patterns:
            pid = pii.get("id", "")
            pdesc = pii.get("description", "")
            sev = pii.get("severity", "")
            pii_parts.append(f"{pid}({sev}): {pdesc}")
        fields.append(IRField(
            key="PII-PATTERNS",
            value="; ".join(pii_parts),
            raw_value=pii_patterns,
            source=source,
        ))

    compliance_rules = guardrails.get("compliance_rules", []) or []
    if compliance_rules:
        comp_parts = []
        for rule in compliance_rules:
            rid = rule.get("id", "")
            rdesc = rule.get("description", "")
            sev = rule.get("severity", "")
            comp_parts.append(f"{rid}({sev}): {rdesc}")
        fields.append(IRField(
            key="COMPLIANCE-RULES",
            value="; ".join(comp_parts),
            raw_value=compliance_rules,
            source=source,
        ))

    # Experience / KBQ templates → KBQ-* fields
    experience = data.get("experience", {}) or {}
    for kbq in experience.get("kbq_templates", []) or []:
        kbq_id = kbq.get("id", "")
        question = kbq.get("question", "")
        intent = kbq.get("intent", "")
        req_metrics = kbq.get("required_metrics", [])
        req_dims = kbq.get("required_dimensions", [])

        parts = [f"Q: {question}"]
        if intent:
            parts.append(f"intent={intent}")
        if req_metrics:
            parts.append(f"metrics=[{','.join(req_metrics)}]")
        if req_dims:
            parts.append(f"dims=[{','.join(req_dims)}]")

        # Derive short name from kbq_id (e.g. retail.kbq.channel_mix -> CHANNEL-MIX)
        short_name = kbq_id.rsplit(".", 1)[-1] if "." in kbq_id else kbq_id
        fields.append(IRField(
            key=f"KBQ-{_canon(short_name)}",
            value="; ".join(parts),
            raw_value=kbq,
            source=source,
            salience=0.7,
        ))

    return IREntity(
        name=name,
        aliases=aliases,
        fields=fields,
        annotations=annotations,
        sources=[source],
        salience=1.0,
    )


def _build_metric_entity(
    metric: dict[str, Any], domain: str, source: IRSource
) -> IREntity:
    """Build an IREntity for a single ontology metric."""
    metric_id = metric.get("id", "")
    name = metric.get("name", "")

    # Entity name: METRIC-DOMAIN-NAME (e.g. METRIC-RETAIL-GROSS-SALES)
    entity_name = f"METRIC-{_canon(domain)}-{_canon(name)}"

    fields: list[IRField] = []

    if metric.get("description"):
        fields.append(IRField(
            key="DEFINITION",
            value=str(metric["description"]),
            source=source,
        ))
    if metric.get("formula"):
        fields.append(IRField(
            key="FORMULA",
            value=str(metric["formula"]),
            source=source,
            salience=1.0,
        ))
    if metric.get("owner"):
        fields.append(IRField(
            key="OWNER",
            value=str(metric["owner"]),
            source=source,
        ))
    if metric.get("tags"):
        fields.append(IRField(
            key="TAGS",
            value="+".join(str(t) for t in metric["tags"]),
            source=source,
        ))
    if metric.get("sources"):
        fields.append(IRField(
            key="SOURCES",
            value="+".join(str(s) for s in metric["sources"]),
            source=source,
        ))
    if metric.get("dimensions"):
        fields.append(IRField(
            key="DIMENSIONS",
            value="+".join(str(d) for d in metric["dimensions"]),
            source=source,
        ))

    annotations: dict[str, str] = {
        "pack_domain": _canon(domain),
        "entity_type": "metric",
    }
    if metric.get("description"):
        annotations["description"] = str(metric["description"])

    return IREntity(
        name=entity_name,
        aliases=[name] if name else [],
        fields=fields,
        annotations=annotations,
        sources=[source],
        salience=1.0,
    )


def _build_dimension_entity(
    dim: dict[str, Any], domain: str, source: IRSource
) -> IREntity:
    """Build an IREntity for a single ontology dimension."""
    dim_id = dim.get("id", "")
    name = dim.get("name", "")

    entity_name = f"DIM-{_canon(domain)}-{_canon(name)}"

    fields: list[IRField] = []

    if dim.get("description"):
        fields.append(IRField(
            key="DEFINITION",
            value=str(dim["description"]),
            source=source,
        ))
    if dim.get("hierarchy"):
        fields.append(IRField(
            key="HIERARCHY",
            value="->".join(str(h) for h in dim["hierarchy"]),
            source=source,
            salience=1.0,
        ))
    if dim.get("keys"):
        fields.append(IRField(
            key="KEYS",
            value="+".join(str(k) for k in dim["keys"]),
            source=source,
        ))
    if dim.get("attributes"):
        fields.append(IRField(
            key="ATTRIBUTES",
            value="+".join(str(a) for a in dim["attributes"]),
            source=source,
        ))

    annotations: dict[str, str] = {
        "pack_domain": _canon(domain),
        "entity_type": "dimension",
    }
    if dim.get("description"):
        annotations["description"] = str(dim["description"])

    return IREntity(
        name=entity_name,
        aliases=[name] if name else [],
        fields=fields,
        annotations=annotations,
        sources=[source],
        salience=0.9,
    )


def _apply_ontology_synonyms(
    synonyms: list[dict[str, Any]], entities: list[IREntity]
) -> None:
    """Apply ontology synonyms as aliases on metric/dimension entities."""
    if not synonyms:
        return

    # Build lookup: canonical_id -> entity
    entity_by_id: dict[str, IREntity] = {}
    for entity in entities:
        # Match on the last segment of the entity name
        entity_by_id[entity.name] = entity
        # Also match on the full metric/dim id if it's in annotations
        for src in entity.sources:
            pass

    for syn in synonyms:
        term = syn.get("term", "")
        canonical = syn.get("canonical", "")
        if not term or not canonical:
            continue

        # Try to find the entity that matches the canonical id
        # canonical is like "retail.metrics.average_basket_size"
        # entity name is like "METRIC-RETAIL-AVERAGE-BASKET-SIZE"
        parts = canonical.split(".")
        if len(parts) >= 3:
            # Construct expected entity name
            domain_part = _canon(parts[0])
            category = parts[1]  # "metrics" or "dimensions"
            name_part = _canon(".".join(parts[2:]))
            if category == "metrics":
                expected = f"METRIC-{domain_part}-{name_part}"
            elif category == "dimensions":
                expected = f"DIM-{domain_part}-{name_part}"
            else:
                continue

            for entity in entities:
                if entity.name == expected:
                    if term not in entity.aliases:
                        entity.aliases.append(term)
                    break


# ── Multi-Pack Compiler ──


def compile_domain_packs(
    packs_dir: str,
    *,
    deduplicate: bool = True,
) -> IRCorpus:
    """Compile multiple domain packs into a unified IRCorpus.

    Steps:
    1. Discover all pack.yaml files in subdirectories
    2. Parse each into IR entities
    3. Cross-domain entity resolution (customer = shopper = passenger)
    4. Dedup fingerprints that appear in multiple packs
    5. Conflict detection (same metric defined differently across domains)
    6. Return unified corpus
    """
    # 1. Discover packs
    pack_files = _discover_packs(packs_dir)

    corpus = IRCorpus(
        domain="analytics",
        scope="multi-domain",
        author="domain-pack-compiler",
    )

    # 2. Parse each pack
    total_tokens = 0
    for pack_path in pack_files:
        with open(pack_path, encoding="utf-8") as f:
            text = f.read()
        total_tokens += len(text.split())

        # Extract domain name from directory structure
        # e.g. .../packs/retail/v1/pack.yaml -> retail
        parts = os.path.normpath(pack_path).replace("\\", "/").split("/")
        domain = ""
        for i, p in enumerate(parts):
            if p == "v1" and i > 0:
                domain = parts[i - 1]
                break
        if not domain:
            # Fallback: parent of parent
            domain = os.path.basename(os.path.dirname(os.path.dirname(pack_path)))

        entities = parse_domain_pack(
            text, filename=pack_path, domain=domain,
        )
        corpus.entities.extend(entities)
        corpus.source_files.append(
            os.path.relpath(pack_path, packs_dir).replace("\\", "/")
        )

    corpus.source_token_count = total_tokens

    # 3. Cross-domain vocabulary resolution
    _build_cross_domain_vocabulary(corpus)

    # 4. Dedup fingerprints
    if deduplicate:
        _deduplicate_fingerprints(corpus)

    # 5. Conflict detection
    _detect_metric_conflicts(corpus)

    return corpus


def _discover_packs(packs_dir: str) -> list[str]:
    """Find all pack.yaml files in the packs directory."""
    pack_files: list[str] = []
    if not os.path.isdir(packs_dir):
        return pack_files

    for entry in sorted(os.listdir(packs_dir)):
        domain_dir = os.path.join(packs_dir, entry)
        if not os.path.isdir(domain_dir):
            continue
        pack_path = os.path.join(domain_dir, "v1", "pack.yaml")
        if os.path.isfile(pack_path):
            pack_files.append(pack_path)

    return pack_files


def _build_cross_domain_vocabulary(corpus: IRCorpus) -> None:
    """Build cross-domain synonym map from vocabulary entities.

    Each pack has vocabulary.entities mapping generic terms to domain-specific
    synonyms. Collect all of these so they are available for entity resolution.
    """
    # Collect all domain entities and their vocabulary aliases
    # The domain entities already have aliases from vocabulary parsing
    # This is a no-op for now since aliases are already on the domain entities
    pass


def _deduplicate_fingerprints(corpus: IRCorpus) -> None:
    """Deduplicate identical fingerprints across domain entities.

    If the same fingerprint column (same id, same patterns, same data_types)
    appears in multiple domain entities, keep one copy and add provenance
    from all sources via additional_sources.
    """
    # Build fingerprint index: FP key -> list of (entity_idx, field_idx, field)
    fp_index: dict[str, list[tuple[int, int, IRField]]] = {}

    for eidx, entity in enumerate(corpus.entities):
        for fidx, field in enumerate(entity.fields):
            if field.key.startswith("FP-"):
                fp_index.setdefault(field.key, []).append((eidx, fidx, field))

    # For each fingerprint that appears in >1 entity with the same raw value,
    # keep the first occurrence and track additional sources
    for fp_key, occurrences in fp_index.items():
        if len(occurrences) <= 1:
            continue

        # Group by raw value (dict comparison via repr)
        by_value: dict[str, list[tuple[int, int, IRField]]] = {}
        for eidx, fidx, field in occurrences:
            # Use a simplified key: just the field description + patterns
            raw = field.raw_value
            if isinstance(raw, dict):
                # Compare on id + patterns + data_types
                sig = repr(sorted(
                    (k, repr(v)) for k, v in raw.items()
                    if k in ("id", "patterns", "data_types", "description")
                ))
            else:
                sig = repr(raw)
            by_value.setdefault(sig, []).append((eidx, fidx, field))

        for sig, group in by_value.items():
            if len(group) <= 1:
                continue

            # Keep the first, remove duplicates from their entities
            primary_eidx, primary_fidx, primary_field = group[0]
            for eidx, fidx, field in group[1:]:
                if field.source:
                    primary_field.additional_sources.append(field.source)
                # Mark for removal by setting key to empty
                field.key = ""

    # Remove fields with empty keys (marked for removal)
    for entity in corpus.entities:
        entity.fields = [f for f in entity.fields if f.key]


def _detect_metric_conflicts(corpus: IRCorpus) -> None:
    """Detect conflicts: same metric name with different formulas across domains."""
    # Build index: metric short name -> list of (entity, formula_field)
    metric_formulas: dict[str, list[tuple[str, str]]] = {}

    for entity in corpus.entities:
        if not entity.name.startswith("METRIC-"):
            continue
        # Extract short name (after METRIC-DOMAIN-)
        parts = entity.name.split("-", 2)
        if len(parts) >= 3:
            short_name = parts[2]  # e.g. GROSS-SALES
        else:
            short_name = entity.name

        for field in entity.fields:
            if field.key == "FORMULA":
                metric_formulas.setdefault(short_name, []).append(
                    (entity.name, field.value)
                )

    # Check for conflicts
    for short_name, entries in metric_formulas.items():
        if len(entries) <= 1:
            continue

        # Check if formulas differ
        formulas = {formula for _, formula in entries}
        if len(formulas) > 1:
            entity_names = [name for name, _ in entries]
            corpus.warnings.append(IRWarning(
                entity="+".join(entity_names),
                message=(
                    f"Metric conflict on {short_name}: "
                    f"{len(formulas)} different formulas across "
                    f"{len(entries)} domains"
                ),
                severity=Severity.WARNING,
            ))


# ── L3 Directory Index ──


def build_analytics_l3(corpus: IRCorpus) -> str:
    """Build an L3 directory index for analytics use.

    Format:
    ANALYTICS DOMAIN DIRECTORY
    Domains: 17 packs
    ---
    RETAIL: 17 fingerprints, 14 metrics, 6 dimensions
    AIRLINES: 14 fingerprints, 7 metrics, 4 dimensions
    ...
    ---
    Total: N fingerprints, N metrics, N dimensions
    Warnings: N conflicts
    """
    lines: list[str] = []

    # Collect per-domain stats
    domain_stats: dict[str, dict[str, int]] = {}

    for entity in corpus.entities:
        entity_type = entity.annotations.get("entity_type", "")
        pack_domain = entity.annotations.get("pack_domain", "")

        if entity_type == "metric" and pack_domain:
            domain_stats.setdefault(pack_domain, {"fingerprints": 0, "metrics": 0, "dimensions": 0})
            domain_stats[pack_domain]["metrics"] += 1

        elif entity_type == "dimension" and pack_domain:
            domain_stats.setdefault(pack_domain, {"fingerprints": 0, "metrics": 0, "dimensions": 0})
            domain_stats[pack_domain]["dimensions"] += 1

        elif not entity_type:
            # Domain entity — count fingerprints
            fp_count = sum(1 for f in entity.fields if f.key.startswith("FP-"))
            if fp_count > 0:
                domain_stats.setdefault(entity.name, {"fingerprints": 0, "metrics": 0, "dimensions": 0})
                domain_stats[entity.name]["fingerprints"] = fp_count

    # Build output
    num_domains = len(domain_stats)
    lines.append(f"ANALYTICS DOMAIN DIRECTORY")
    lines.append(f"Domains: {num_domains} packs")
    lines.append("---")

    total_fp = 0
    total_metrics = 0
    total_dims = 0

    for domain in sorted(domain_stats.keys()):
        stats = domain_stats[domain]
        fp = stats["fingerprints"]
        m = stats["metrics"]
        d = stats["dimensions"]
        total_fp += fp
        total_metrics += m
        total_dims += d
        lines.append(f"{domain}: {fp} fingerprints, {m} metrics, {d} dimensions")

    lines.append("---")
    lines.append(f"Total: {total_fp} fingerprints, {total_metrics} metrics, {total_dims} dimensions")

    if corpus.warnings:
        lines.append(f"Warnings: {len(corpus.warnings)} conflicts")

    return "\n".join(lines)
