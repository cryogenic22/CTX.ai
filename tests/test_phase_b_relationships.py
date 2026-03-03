"""WS2 — Relationship Modeling tests (~18 tests).

Covers: has_many/has_one/references/depends_on parsing, bidirectional
inference, IRRelationship dataclass, extended entity detection,
salience boost, and _compress_relationship_extended variants.
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
from ctxpack.core.packer.yaml_parser import (
    _looks_like_entity,
    _compress_relationship_extended,
    extract_entities_from_yaml,
    yaml_parse,
)
from ctxpack.core.packer.json_parser import _looks_like_entity as json_looks_like_entity
from ctxpack.core.packer.entity_resolver import resolve_entities
from ctxpack.core.packer.compressor import _score_field, _RELATIONSHIP_KEYS


# ── 1. Parse has_many dict -> HAS-MANY field with 1:N cardinality ──

def test_has_many_dict_produces_has_many_field():
    """has_many dict input yields a HAS-MANY field with 1:N cardinality."""
    data = {
        "entity": "Customer",
        "has_many": {"entity": "Order", "field": "customer_id"},
    }
    entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
    assert len(entities) == 1
    entity = entities[0]
    has_many_fields = [f for f in entity.fields if f.key == "HAS-MANY"]
    assert len(has_many_fields) == 1
    assert "1:N" in has_many_fields[0].value
    # Also check IRRelationship
    has_many_rels = [r for r in entity.relationships if r.rel_type == "has-many"]
    assert len(has_many_rels) == 1
    assert has_many_rels[0].cardinality == "1:N"
    assert has_many_rels[0].target_entity == "ORDER"


# ── 2. Parse has_one dict -> HAS-ONE field with 1:1 cardinality ──

def test_has_one_dict_produces_has_one_field():
    """has_one dict input yields a HAS-ONE field with 1:1 cardinality."""
    data = {
        "entity": "User",
        "has_one": {"entity": "Profile", "field": "user_id"},
    }
    entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
    entity = entities[0]
    has_one_fields = [f for f in entity.fields if f.key == "HAS-ONE"]
    assert len(has_one_fields) == 1
    assert "1:1" in has_one_fields[0].value
    has_one_rels = [r for r in entity.relationships if r.rel_type == "has-one"]
    assert len(has_one_rels) == 1
    assert has_one_rels[0].cardinality == "1:1"
    assert has_one_rels[0].target_entity == "PROFILE"


# ── 3. Parse references string -> REFERENCES field with @ENTITY ref ──

def test_references_string_produces_references_field():
    """references string input yields a REFERENCES field with @ENTITY-X."""
    data = {
        "entity": "Order",
        "references": "Product",
    }
    entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
    entity = entities[0]
    ref_fields = [f for f in entity.fields if f.key == "REFERENCES"]
    assert len(ref_fields) == 1
    assert "@ENTITY-PRODUCT" in ref_fields[0].value


# ── 4. Parse depends_on -> DEPENDS-ON field ──

def test_depends_on_produces_depends_on_field():
    """depends_on input yields a DEPENDS-ON field."""
    data = {
        "entity": "Invoice",
        "depends_on": "Order",
    }
    entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
    entity = entities[0]
    dep_fields = [f for f in entity.fields if f.key == "DEPENDS-ON"]
    assert len(dep_fields) == 1
    assert "@ENTITY-ORDER" in dep_fields[0].value


# ── 5. Parse has_many with cascade -> >>cascade-delete in output ──

def test_has_many_with_cascade_delete():
    """has_many dict with cascade='delete' includes >>cascade-delete."""
    data = {
        "entity": "Customer",
        "has_many": {
            "entity": "Order",
            "field": "customer_id",
            "cascade": "delete",
        },
    }
    entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
    entity = entities[0]
    has_many_fields = [f for f in entity.fields if f.key == "HAS-MANY"]
    assert len(has_many_fields) == 1
    assert ">>cascade-delete" in has_many_fields[0].value


# ── 6. Parse has_many list of dicts -> multiple HAS-MANY entries ──

def test_has_many_list_of_dicts_multiple_entries():
    """has_many list of dicts yields joined HAS-MANY entries."""
    data = {
        "entity": "Customer",
        "has_many": [
            {"entity": "Order", "field": "customer_id"},
            {"entity": "Address", "field": "customer_id"},
        ],
    }
    entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
    entity = entities[0]
    has_many_fields = [f for f in entity.fields if f.key == "HAS-MANY"]
    assert len(has_many_fields) == 1
    # List is joined with +
    assert "@ENTITY-ORDER" in has_many_fields[0].value
    assert "@ENTITY-ADDRESS" in has_many_fields[0].value
    assert "+" in has_many_fields[0].value
    # Two IRRelationship objects created
    has_many_rels = [r for r in entity.relationships if r.rel_type == "has-many"]
    assert len(has_many_rels) == 2


# ── 7. Bidirectional inference: BELONGS-TO A->B creates HAS-MANY B->A (INFERRED) ──

def test_bidirectional_belongs_to_creates_has_many():
    """BELONGS-TO on ORDER->CUSTOMER infers HAS-MANY on CUSTOMER->ORDER."""
    src = IRSource(file="test.yaml")
    order = IREntity(
        name="ORDER",
        fields=[
            IRField(key="BELONGS-TO", value="@ENTITY-CUSTOMER(customer_id)", source=src),
        ],
        relationships=[
            IRRelationship(
                source_entity="ORDER",
                target_entity="CUSTOMER",
                rel_type="belongs-to",
                via_field="customer_id",
                cardinality="1:1",
                source=src,
            ),
        ],
        sources=[src],
    )
    customer = IREntity(
        name="CUSTOMER",
        fields=[],
        relationships=[],
        sources=[src],
    )
    corpus = IRCorpus(entities=[order, customer])
    resolve_entities(corpus)

    # CUSTOMER should now have an inferred HAS-MANY relationship
    cust = next(e for e in corpus.entities if e.name == "CUSTOMER")
    inferred_rels = [r for r in cust.relationships if r.rel_type == "has-many"]
    assert len(inferred_rels) == 1
    assert inferred_rels[0].target_entity == "ORDER"
    assert inferred_rels[0].certainty == Certainty.INFERRED
    # And an inferred HAS-MANY field
    inferred_fields = [f for f in cust.fields if f.key == "HAS-MANY"]
    assert len(inferred_fields) == 1
    assert inferred_fields[0].certainty == Certainty.INFERRED


# ── 8. Bidirectional inference: HAS-MANY A->B creates BELONGS-TO B->A (INFERRED) ──

def test_bidirectional_has_many_creates_belongs_to():
    """HAS-MANY on CUSTOMER->ORDER infers BELONGS-TO on ORDER->CUSTOMER."""
    src = IRSource(file="test.yaml")
    customer = IREntity(
        name="CUSTOMER",
        fields=[
            IRField(key="HAS-MANY", value="@ENTITY-ORDER(customer_id,1:N)", source=src),
        ],
        relationships=[
            IRRelationship(
                source_entity="CUSTOMER",
                target_entity="ORDER",
                rel_type="has-many",
                via_field="customer_id",
                cardinality="1:N",
                source=src,
            ),
        ],
        sources=[src],
    )
    order = IREntity(
        name="ORDER",
        fields=[],
        relationships=[],
        sources=[src],
    )
    corpus = IRCorpus(entities=[customer, order])
    resolve_entities(corpus)

    ord_entity = next(e for e in corpus.entities if e.name == "ORDER")
    inferred_rels = [r for r in ord_entity.relationships if r.rel_type == "belongs-to"]
    assert len(inferred_rels) == 1
    assert inferred_rels[0].target_entity == "CUSTOMER"
    assert inferred_rels[0].certainty == Certainty.INFERRED
    inferred_fields = [f for f in ord_entity.fields if f.key == "BELONGS-TO"]
    assert len(inferred_fields) == 1
    assert inferred_fields[0].certainty == Certainty.INFERRED


# ── 9. No duplicate inverse when both directions already exist ──

def test_no_duplicate_inverse_when_both_exist():
    """If both BELONGS-TO and HAS-MANY already exist, no extra inverse is added."""
    src = IRSource(file="test.yaml")
    customer = IREntity(
        name="CUSTOMER",
        fields=[
            IRField(key="HAS-MANY", value="@ENTITY-ORDER(customer_id,1:N)", source=src),
        ],
        relationships=[
            IRRelationship(
                source_entity="CUSTOMER",
                target_entity="ORDER",
                rel_type="has-many",
                via_field="customer_id",
                cardinality="1:N",
                source=src,
            ),
        ],
        sources=[src],
    )
    order = IREntity(
        name="ORDER",
        fields=[
            IRField(key="BELONGS-TO", value="@ENTITY-CUSTOMER(customer_id)", source=src),
        ],
        relationships=[
            IRRelationship(
                source_entity="ORDER",
                target_entity="CUSTOMER",
                rel_type="belongs-to",
                via_field="customer_id",
                cardinality="1:1",
                source=src,
            ),
        ],
        sources=[src],
    )
    corpus = IRCorpus(entities=[customer, order])
    resolve_entities(corpus)

    # CUSTOMER should still have exactly one HAS-MANY
    cust = next(e for e in corpus.entities if e.name == "CUSTOMER")
    hm_rels = [r for r in cust.relationships if r.rel_type == "has-many"]
    assert len(hm_rels) == 1

    # ORDER should still have exactly one BELONGS-TO
    ord_entity = next(e for e in corpus.entities if e.name == "ORDER")
    bt_rels = [r for r in ord_entity.relationships if r.rel_type == "belongs-to"]
    assert len(bt_rels) == 1


# ── 10. IRRelationship dataclass fields are correct ──

def test_ir_relationship_dataclass_defaults():
    """IRRelationship has correct default fields and values."""
    rel = IRRelationship(source_entity="A", target_entity="B")
    assert rel.source_entity == "A"
    assert rel.target_entity == "B"
    assert rel.rel_type == "belongs-to"
    assert rel.via_field == ""
    assert rel.cardinality == "1:1"
    assert rel.cascade == ""
    assert rel.required is False
    assert rel.source is None
    assert rel.certainty == Certainty.EXPLICIT


# ── 11. Extended entity detection: has_many key makes dict look like entity ──

def test_looks_like_entity_has_many():
    """A dict with 'has_many' key is detected as entity-like."""
    data = {"has_many": [{"entity": "Order"}], "description": "A customer"}
    assert _looks_like_entity(data) is True


# ── 12. Extended entity detection: id key makes dict look like entity ──

def test_looks_like_entity_id_key():
    """A dict with 'id' key is detected as entity-like."""
    data = {"id": "uuid", "name": "Widget"}
    assert _looks_like_entity(data) is True


# ── 13. Extended entity detection: primary_key key makes dict look like entity ──

def test_looks_like_entity_primary_key():
    """A dict with 'primary_key' key is detected as entity-like."""
    data = {"primary_key": "widget_id", "fields": ["name", "price"]}
    assert _looks_like_entity(data) is True


# ── 14. JSON parser: extended entity keys detection ──

def test_json_looks_like_entity_extended_keys():
    """JSON _looks_like_entity detects has_many, id, uuid, primary_key."""
    assert json_looks_like_entity({"has_many": []}) is True
    assert json_looks_like_entity({"id": "x"}) is True
    assert json_looks_like_entity({"uuid": "abc"}) is True
    assert json_looks_like_entity({"primary_key": "pk"}) is True
    assert json_looks_like_entity({"has_one": "Profile"}) is True
    assert json_looks_like_entity({"references": "X"}) is True
    assert json_looks_like_entity({"depends_on": "Y"}) is True
    # Non-entity dict
    assert json_looks_like_entity({"color": "red", "size": 5}) is False


# ── 15. Relationship field gets salience boost in compressor ──

def test_relationship_field_salience_boost():
    """Fields with relationship keys receive a 1.2x salience boost."""
    for key in _RELATIONSHIP_KEYS:
        field = IRField(key=key, value="@ENTITY-X(fk,1:N)", salience=1.0)
        _score_field(field)
        assert field.salience == pytest.approx(1.2), f"{key} should get 1.2x boost"

    # Non-relationship field should NOT get the boost
    plain = IRField(key="STATUS-MACHINE", value="active->inactive", salience=1.0)
    _score_field(plain)
    assert plain.salience == pytest.approx(1.0)


# ── 16. _compress_relationship_extended with required=True includes mandatory ──

def test_compress_relationship_extended_required():
    """Dict input with required=True includes 'mandatory' in output."""
    val = {"entity": "Customer", "field": "customer_id", "required": True}
    result = _compress_relationship_extended(val, "1:N")
    assert "mandatory" in result
    assert "@ENTITY-CUSTOMER" in result


# ── 17. _compress_relationship_extended with string input wraps in @ENTITY ──

def test_compress_relationship_extended_string():
    """String input is wrapped as @ENTITY-NAME."""
    result = _compress_relationship_extended("Product", "1:1")
    assert result == "@ENTITY-PRODUCT"


# ── 18. _compress_relationship_extended with list input joins with + ──

def test_compress_relationship_extended_list():
    """List of relationships is joined with +."""
    val = [
        {"entity": "Order", "field": "customer_id"},
        {"entity": "Address", "field": "customer_id"},
    ]
    result = _compress_relationship_extended(val, "1:N")
    assert "+" in result
    assert "@ENTITY-ORDER" in result
    assert "@ENTITY-ADDRESS" in result
