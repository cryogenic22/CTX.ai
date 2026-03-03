"""WS3 — Conflict Detection + Provenance tests (~15 tests).

Covers: null conflicts, type conflicts, PII conflicts, source union/dedup,
multi-source provenance, additional_sources default, retention conflict
(existing behavior), and detect_conflicts integration.
"""

from __future__ import annotations

import pytest

from ctxpack.core.packer.ir import (
    Certainty,
    IRCorpus,
    IREntity,
    IRField,
    IRRelationship,
    IRSource,
    IRWarning,
    Severity,
)
from ctxpack.core.packer.conflict import (
    detect_conflicts,
    _check_null_conflicts,
    _check_type_conflicts,
    _check_pii_conflicts,
)
from ctxpack.core.packer.prov_generator import generate_provenance, inject_inline_provenance
from ctxpack.core.packer.entity_resolver import resolve_entities


# ── Helper to build field index (mirrors detect_conflicts internals) ──

def _build_field_index(corpus: IRCorpus) -> dict[str, list[tuple[str, IRField]]]:
    """Build a field index from corpus, same as detect_conflicts does internally."""
    field_index: dict[str, list[tuple[str, IRField]]] = {}
    for entity in corpus.entities:
        for field in entity.fields:
            field_index.setdefault(field.key, []).append((entity.name, field))
    for rule in corpus.standalone_rules:
        field_index.setdefault(rule.key, []).append(("_STANDALONE", rule))
    return field_index


# ── 1. Null conflict: required identifier + nullable NULL-POLICY -> warning ──

def test_null_conflict_required_identifier_nullable():
    """A required IDENTIFIER + nullable NULL-POLICY on same field yields a warning."""
    corpus = IRCorpus(entities=[
        IREntity(
            name="CUSTOMER",
            fields=[
                IRField(key="IDENTIFIER", value="email(string,required)"),
                IRField(key="NULL-POLICY", value="email(nullable)"),
            ],
        ),
    ])
    idx = _build_field_index(corpus)
    warnings = _check_null_conflicts(idx, corpus)
    assert len(warnings) >= 1
    assert any("email" in w.message.lower() and "required" in w.message.lower() for w in warnings)


# ── 2. Null conflict: same field never-null + nullable in same NULL-POLICY -> warning ──

def test_null_conflict_never_null_and_nullable_same_field():
    """A NULL-POLICY with both never-null and nullable on the same field yields a warning."""
    corpus = IRCorpus(entities=[
        IREntity(
            name="ORDER",
            fields=[
                IRField(key="NULL-POLICY", value="amount(never-null)+amount(nullable)"),
            ],
        ),
    ])
    idx = _build_field_index(corpus)
    warnings = _check_null_conflicts(idx, corpus)
    assert len(warnings) >= 1
    assert any("amount" in w.message.lower() for w in warnings)


# ── 3. Null conflict: no warning when fields don't overlap ──

def test_null_conflict_no_overlap_no_warning():
    """No warning when required IDENTIFIER and nullable NULL-POLICY are on different fields."""
    corpus = IRCorpus(entities=[
        IREntity(
            name="PRODUCT",
            fields=[
                IRField(key="IDENTIFIER", value="sku(string,required)"),
                IRField(key="NULL-POLICY", value="description(nullable)"),
            ],
        ),
    ])
    idx = _build_field_index(corpus)
    warnings = _check_null_conflicts(idx, corpus)
    assert len(warnings) == 0


# ── 4. Type conflict: same field name with different types across entities -> warning ──

def test_type_conflict_different_types_across_entities():
    """Same identifier field name with different types across entities yields a warning."""
    corpus = IRCorpus(entities=[
        IREntity(
            name="CUSTOMER",
            fields=[IRField(key="IDENTIFIER", value="id(uuid)")],
        ),
        IREntity(
            name="ORDER",
            fields=[IRField(key="IDENTIFIER", value="id(integer)")],
        ),
    ])
    idx = _build_field_index(corpus)
    warnings = _check_type_conflicts(idx)
    assert len(warnings) >= 1
    assert any("type conflict" in w.message.lower() for w in warnings)


# ── 5. Type conflict: same type across entities -> no warning ──

def test_type_conflict_same_type_no_warning():
    """Same identifier field name with same type across entities yields no warning."""
    corpus = IRCorpus(entities=[
        IREntity(
            name="CUSTOMER",
            fields=[IRField(key="IDENTIFIER", value="id(uuid)")],
        ),
        IREntity(
            name="ORDER",
            fields=[IRField(key="IDENTIFIER", value="id(uuid)")],
        ),
    ])
    idx = _build_field_index(corpus)
    warnings = _check_type_conflicts(idx)
    assert len(warnings) == 0


# ── 6. Type conflict: BELONGS-TO FK type vs target IDENTIFIER type mismatch -> warning ──

def test_type_conflict_fk_vs_identifier_mismatch():
    """BELONGS-TO FK type (int) vs target IDENTIFIER type (uuid) yields a warning."""
    corpus = IRCorpus(entities=[
        IREntity(
            name="CUSTOMER",
            fields=[IRField(key="IDENTIFIER", value="customer_id(uuid)")],
        ),
        IREntity(
            name="ORDER",
            fields=[
                IRField(key="IDENTIFIER", value="customer_id(integer)"),
                IRField(key="BELONGS-TO", value="@ENTITY-CUSTOMER(customer_id)"),
            ],
        ),
    ])
    idx = _build_field_index(corpus)
    warnings = _check_type_conflicts(idx)
    assert len(warnings) >= 1
    assert any("type conflict" in w.message.lower() for w in warnings)


# ── 7. PII conflict: same field different levels across entities -> warning ──

def test_pii_conflict_different_levels():
    """Same PII field with different levels across entities yields a warning."""
    corpus = IRCorpus(entities=[
        IREntity(
            name="CUSTOMER",
            fields=[IRField(key="PII-CLASSIFICATION", value="email\u2192RESTRICTED")],
        ),
        IREntity(
            name="LEAD",
            fields=[IRField(key="PII-CLASSIFICATION", value="email\u2192CONFIDENTIAL")],
        ),
    ])
    idx = _build_field_index(corpus)
    warnings = _check_pii_conflicts(idx)
    assert len(warnings) >= 1
    assert any("pii conflict" in w.message.lower() for w in warnings)


# ── 8. PII conflict: same level -> no warning ──

def test_pii_conflict_same_level_no_warning():
    """Same PII field with same level across entities yields no warning."""
    corpus = IRCorpus(entities=[
        IREntity(
            name="CUSTOMER",
            fields=[IRField(key="PII-CLASSIFICATION", value="email\u2192RESTRICTED")],
        ),
        IREntity(
            name="LEAD",
            fields=[IRField(key="PII-CLASSIFICATION", value="email\u2192RESTRICTED")],
        ),
    ])
    idx = _build_field_index(corpus)
    warnings = _check_pii_conflicts(idx)
    assert len(warnings) == 0


# ── 9. PII conflict: no PII entries -> empty ──

def test_pii_conflict_no_entries_empty():
    """No PII-CLASSIFICATION fields means no PII warnings."""
    corpus = IRCorpus(entities=[
        IREntity(
            name="CUSTOMER",
            fields=[IRField(key="IDENTIFIER", value="id(uuid)")],
        ),
    ])
    idx = _build_field_index(corpus)
    warnings = _check_pii_conflicts(idx)
    assert warnings == []


# ── 10. Source union: dedup preserves additional_sources ──

def test_source_union_dedup_preserves_additional_sources():
    """When entity resolver deduplicates fields, additional_sources accumulate."""
    src_a = IRSource(file="a.yaml", line_start=1)
    src_b = IRSource(file="b.yaml", line_start=5)
    entity_a = IREntity(
        name="CUSTOMER",
        fields=[
            IRField(key="RETENTION", value="24-months", raw_value="24 months", source=src_a),
        ],
        sources=[src_a],
    )
    entity_b = IREntity(
        name="CUSTOMER",
        fields=[
            IRField(key="RETENTION", value="24-months", raw_value="24 months", source=src_b),
        ],
        sources=[src_b],
    )
    corpus = IRCorpus(entities=[entity_a, entity_b])
    resolve_entities(corpus)

    cust = next(e for e in corpus.entities if e.name == "CUSTOMER")
    ret_fields = [f for f in cust.fields if f.key == "RETENTION"]
    assert len(ret_fields) == 1
    assert len(ret_fields[0].additional_sources) >= 1


# ── 11. Multi-source provenance output shows both sources with + ──

def test_multi_source_provenance_output():
    """generate_provenance shows multiple sources joined with ' + '."""
    src_a = IRSource(file="a.yaml", line_start=1)
    src_b = IRSource(file="b.yaml", line_start=5)
    corpus = IRCorpus(entities=[
        IREntity(
            name="CUSTOMER",
            fields=[
                IRField(
                    key="RETENTION",
                    value="24-months",
                    source=src_a,
                    additional_sources=[src_b],
                ),
            ],
            sources=[src_a],
        ),
    ])
    prov_text = generate_provenance(corpus, ctx_filename="out.ctx")
    assert "a.yaml#L1" in prov_text
    assert "b.yaml#L5" in prov_text
    assert " + " in prov_text


# ── 12. Multi-source inline provenance includes both sources ──

def test_multi_source_inline_provenance():
    """inject_inline_provenance appends SRC: with both sources."""
    src_a = IRSource(file="a.yaml", line_start=1)
    src_b = IRSource(file="b.yaml", line_start=5)
    corpus = IRCorpus(entities=[
        IREntity(
            name="CUSTOMER",
            fields=[
                IRField(
                    key="RETENTION",
                    value="24-months",
                    source=src_a,
                    additional_sources=[src_b],
                ),
            ],
            sources=[src_a],
        ),
    ])
    inject_inline_provenance(corpus)
    field = corpus.entities[0].fields[0]
    assert "SRC:" in field.value
    assert "a.yaml#L1" in field.value
    assert "b.yaml#L5" in field.value
    assert " + " in field.value


# ── 13. additional_sources default is empty list ──

def test_additional_sources_default_empty():
    """IRField.additional_sources defaults to an empty list."""
    field = IRField(key="TEST", value="val")
    assert field.additional_sources == []
    assert isinstance(field.additional_sources, list)


# ── 14. Retention conflict still works (existing behavior preserved) ──

def test_retention_conflict_existing_behavior():
    """Different retention periods across entities still produce warnings."""
    corpus = IRCorpus(entities=[
        IREntity(
            name="CUSTOMER",
            fields=[IRField(key="RETENTION", value="active->24-months")],
        ),
        IREntity(
            name="ORDER",
            fields=[IRField(key="RETENTION", value="active->12-months")],
        ),
    ])
    warnings = detect_conflicts(corpus)
    retention_warnings = [w for w in warnings if "retention" in w.message.lower()]
    assert len(retention_warnings) >= 1
    assert any("24" in w.message and "12" in w.message for w in retention_warnings)


# ── 15. detect_conflicts integrates all checkers ──

def test_detect_conflicts_integrates_all():
    """detect_conflicts runs null, type, PII, and retention checks together."""
    corpus = IRCorpus(entities=[
        IREntity(
            name="CUSTOMER",
            fields=[
                IRField(key="IDENTIFIER", value="id(uuid)"),
                IRField(key="PII-CLASSIFICATION", value="email\u2192RESTRICTED"),
                IRField(key="RETENTION", value="active->24-months"),
            ],
        ),
        IREntity(
            name="ORDER",
            fields=[
                IRField(key="IDENTIFIER", value="id(integer)"),
                IRField(key="PII-CLASSIFICATION", value="email\u2192CONFIDENTIAL"),
                IRField(key="RETENTION", value="active->12-months"),
            ],
        ),
    ])
    warnings = detect_conflicts(corpus)
    # Should have at least: type conflict (uuid vs integer), PII conflict,
    # and retention conflict
    types = {w.message.split(":")[0].strip().lower() for w in warnings}
    messages_lower = [w.message.lower() for w in warnings]
    assert any("type conflict" in m for m in messages_lower), "Expected type conflict"
    assert any("pii conflict" in m for m in messages_lower), "Expected PII conflict"
    assert any("retention conflict" in m for m in messages_lower), "Expected retention conflict"
