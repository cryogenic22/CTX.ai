"""Tests for Phase A Trust Layer: certainty tiers, provenance, L3 generation, JSON parser."""

import json
import os
import tempfile

import pytest

from ctxpack.core.model import CTXDocument, Header, KeyValue, Layer, PlainLine, Section
from ctxpack.core.packer import pack, PackResult
from ctxpack.core.packer.ir import Certainty, IRCorpus, IREntity, IRField, IRSource, IRWarning
from ctxpack.core.packer.compressor import compress
from ctxpack.core.packer.yaml_parser import extract_entities_from_yaml, yaml_parse
from ctxpack.core.packer.json_parser import extract_entities_from_json, json_parse
from ctxpack.core.packer.prov_generator import generate_provenance, inject_inline_provenance
from ctxpack.core.packer.l3_generator import generate_l3
from ctxpack.core.packer.manifest import generate_manifest
from ctxpack.core.packer.discovery import discover
from ctxpack.core.serializer import serialize
from ctxpack.core.validator import validate
from ctxpack.core.errors import DiagnosticLevel


FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "sample-corpus"
)


# ═══════════════════════════════════════════════════
# A1: Certainty Tiers
# ═══════════════════════════════════════════════════


class TestCertaintyEnum:
    def test_certainty_values(self):
        assert Certainty.EXPLICIT.value == "explicit"
        assert Certainty.INFERRED.value == "inferred"
        assert Certainty.UNCERTAIN.value == "uncertain"

    def test_irfield_default_certainty(self):
        f = IRField(key="TEST", value="val")
        assert f.certainty == Certainty.EXPLICIT

    def test_irfield_explicit_certainty(self):
        f = IRField(key="TEST", value="val", certainty=Certainty.INFERRED)
        assert f.certainty == Certainty.INFERRED


class TestCertaintyTagging:
    def test_explicit_identifier_not_inferred(self):
        """An identifier without scope inference stays EXPLICIT."""
        data = {
            "entity": "PRODUCT",
            "identifier": {"name": "sku", "type": "string", "unique": True},
        }
        entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
        assert len(entities) == 1
        id_field = next(f for f in entities[0].fields if f.key == "IDENTIFIER")
        assert id_field.certainty == Certainty.EXPLICIT

    def test_inferred_scope_from_description(self):
        """When description mentions 'per merchant', scope inference → INFERRED."""
        data = {
            "entity": "PRODUCT",
            "description": "Product catalog, one per merchant",
            "identifier": {"name": "sku", "type": "string", "unique": True},
        }
        entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
        assert len(entities) == 1
        id_field = next(f for f in entities[0].fields if f.key == "IDENTIFIER")
        assert id_field.certainty == Certainty.INFERRED
        assert "unique-per-merchant" in id_field.value

    def test_inferred_scope_per_tenant(self):
        data = {
            "entity": "USER",
            "description": "User account, scoped per tenant",
            "identifier": {"name": "user_id", "type": "UUID", "unique": True},
        }
        entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
        id_field = next(f for f in entities[0].fields if f.key == "IDENTIFIER")
        assert id_field.certainty == Certainty.INFERRED
        assert "unique-per-tenant" in id_field.value

    def test_no_scope_inference_without_description(self):
        """No description → no inference → EXPLICIT."""
        data = {
            "entity": "ITEM",
            "identifier": {"name": "item_id", "type": "int", "unique": True},
        }
        entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
        id_field = next(f for f in entities[0].fields if f.key == "IDENTIFIER")
        assert id_field.certainty == Certainty.EXPLICIT


class TestStrictMode:
    def test_strict_suppresses_inferred_fields(self):
        """In strict mode, inferred fields should not appear in output."""
        corpus = IRCorpus(domain="test", source_token_count=100)
        corpus.entities.append(IREntity(
            name="PRODUCT",
            fields=[
                IRField(key="IDENTIFIER", value="sku(string,unique-per-merchant)",
                        certainty=Certainty.INFERRED),
                IRField(key="STATUS-MACHINE", value="active→inactive",
                        certainty=Certainty.EXPLICIT),
            ],
            sources=[IRSource(file="test.yaml")],
        ))

        doc = compress(corpus, strict=True)
        sections = [e for e in doc.body if isinstance(e, Section)]
        product = next(s for s in sections if s.name == "ENTITY-PRODUCT")
        kvs = [c for c in product.children if isinstance(c, KeyValue)]
        keys = [kv.key for kv in kvs]

        assert "IDENTIFIER" not in keys
        assert "STATUS-MACHINE" in keys

    def test_enriched_mode_annotates_inferred(self):
        """Default mode annotates inferred fields with (inferred)."""
        corpus = IRCorpus(domain="test", source_token_count=100)
        corpus.entities.append(IREntity(
            name="PRODUCT",
            fields=[
                IRField(key="IDENTIFIER", value="sku(string,unique-per-merchant)",
                        certainty=Certainty.INFERRED),
            ],
            sources=[IRSource(file="test.yaml")],
        ))

        doc = compress(corpus, strict=False)
        sections = [e for e in doc.body if isinstance(e, Section)]
        product = next(s for s in sections if s.name == "ENTITY-PRODUCT")
        kvs = [c for c in product.children if isinstance(c, KeyValue)]
        id_kv = next(kv for kv in kvs if kv.key == "IDENTIFIER")
        assert "(inferred)" in id_kv.value

    def test_explicit_fields_not_annotated(self):
        """Explicit fields should NOT have (inferred) annotation."""
        corpus = IRCorpus(domain="test", source_token_count=100)
        corpus.entities.append(IREntity(
            name="PRODUCT",
            fields=[
                IRField(key="STATUS-MACHINE", value="active→inactive",
                        certainty=Certainty.EXPLICIT),
            ],
            sources=[IRSource(file="test.yaml")],
        ))

        doc = compress(corpus, strict=False)
        sections = [e for e in doc.body if isinstance(e, Section)]
        product = next(s for s in sections if s.name == "ENTITY-PRODUCT")
        kvs = [c for c in product.children if isinstance(c, KeyValue)]
        status_kv = next(kv for kv in kvs if kv.key == "STATUS-MACHINE")
        assert "(inferred)" not in status_kv.value

    def test_pack_strict_flag(self):
        """End-to-end: --strict via pack() API."""
        result = pack(FIXTURES_DIR, strict=True)
        text = serialize(result.document)
        assert "(inferred)" not in text

    def test_pack_enriched_default(self):
        """End-to-end: default enriched mode via pack() API."""
        result = pack(FIXTURES_DIR, strict=False)
        # The sample corpus has customer.yaml with no scope markers in description,
        # so no inferred annotations expected. This just verifies it doesn't crash.
        assert result.document is not None


# ═══════════════════════════════════════════════════
# A2: Field-Level Provenance
# ═══════════════════════════════════════════════════


class TestProvenanceCompanion:
    def test_generate_provenance_basic(self):
        corpus = IRCorpus(domain="test")
        corpus.entities.append(IREntity(
            name="CUSTOMER",
            fields=[
                IRField(key="IDENTIFIER", value="cust_id(UUID)",
                        source=IRSource(file="customer.yaml", line_start=5, line_end=9)),
                IRField(key="PII", value="name+email",
                        source=IRSource(file="customer.yaml", line_start=10, line_end=15)),
            ],
            sources=[IRSource(file="customer.yaml")],
        ))

        prov = generate_provenance(corpus, ctx_filename="output.ctx")
        assert "§PROVENANCE FOR:output.ctx" in prov
        assert "±ENTITY-CUSTOMER" in prov
        assert "IDENTIFIER → customer.yaml#L5-L9" in prov
        assert "PII → customer.yaml#L10-L15" in prov

    def test_generate_provenance_standalone_rules(self):
        corpus = IRCorpus(domain="test")
        corpus.standalone_rules.append(
            IRField(key="DATA-QUALITY", value="strict",
                    source=IRSource(file="rules.yaml", line_start=3))
        )

        prov = generate_provenance(corpus)
        assert "±STANDALONE-RULES" in prov
        assert "DATA-QUALITY → rules.yaml#L3" in prov

    def test_provenance_no_source(self):
        corpus = IRCorpus(domain="test")
        corpus.entities.append(IREntity(
            name="ORPHAN",
            fields=[IRField(key="TEST", value="val")],
            sources=[IRSource(file="unknown.yaml")],
        ))

        prov = generate_provenance(corpus)
        assert "TEST → (no source)" in prov

    def test_pack_companion_provenance(self):
        result = pack(FIXTURES_DIR, provenance="companion")
        assert result.provenance_text != ""
        assert "§PROVENANCE FOR:" in result.provenance_text

    def test_pack_no_provenance(self):
        result = pack(FIXTURES_DIR, provenance="none")
        assert result.provenance_text == ""


class TestProvenanceInline:
    def test_inline_provenance_modifies_values(self):
        corpus = IRCorpus(domain="test")
        entity = IREntity(
            name="ORDER",
            fields=[
                IRField(key="IDENTIFIER", value="order_id(UUID)",
                        source=IRSource(file="order.yaml", line_start=2, line_end=5)),
            ],
            sources=[IRSource(file="order.yaml")],
        )
        corpus.entities.append(entity)

        inject_inline_provenance(corpus)
        assert "SRC:order.yaml#L2-L5" in entity.fields[0].value

    def test_pack_inline_provenance(self):
        result = pack(FIXTURES_DIR, provenance="inline")
        text = serialize(result.document)
        assert "SRC:" in text
        # Companion text should be empty in inline mode
        assert result.provenance_text == ""


# ═══════════════════════════════════════════════════
# A3: L3 Gist Generation
# ═══════════════════════════════════════════════════


class TestL3Generator:
    def _make_l2_doc(self) -> CTXDocument:
        """Create a minimal L2 document for testing."""
        return pack(FIXTURES_DIR).document

    def test_l3_has_required_sections(self):
        l2 = self._make_l2_doc()
        l3 = generate_l3(l2)

        section_names = {
            elem.name for elem in l3.body if isinstance(elem, Section)
        }
        assert "ENTITIES" in section_names
        assert "PATTERNS" in section_names
        assert "CONSTRAINTS" in section_names
        assert "WARNINGS" in section_names

    def test_l3_is_layer_l3(self):
        l2 = self._make_l2_doc()
        l3 = generate_l3(l2)
        assert l3.header.layer == Layer.L3

    def test_l3_entities_section_has_content(self):
        l2 = self._make_l2_doc()
        l3 = generate_l3(l2)

        entities_sec = next(
            e for e in l3.body if isinstance(e, Section) and e.name == "ENTITIES"
        )
        assert len(entities_sec.children) > 0
        # Should mention CUSTOMER
        all_text = " ".join(
            c.text for c in entities_sec.children if isinstance(c, PlainLine)
        )
        assert "CUSTOMER" in all_text

    def test_l3_patterns_section(self):
        l2 = self._make_l2_doc()
        l3 = generate_l3(l2)

        patterns_sec = next(
            e for e in l3.body if isinstance(e, Section) and e.name == "PATTERNS"
        )
        assert len(patterns_sec.children) > 0

    def test_l3_constraints_section(self):
        l2 = self._make_l2_doc()
        l3 = generate_l3(l2)

        constraints_sec = next(
            e for e in l3.body if isinstance(e, Section) and e.name == "CONSTRAINTS"
        )
        assert len(constraints_sec.children) > 0

    def test_l3_token_count_under_500(self):
        l2 = self._make_l2_doc()
        l3 = generate_l3(l2)
        text = serialize(l3)
        tokens = len(text.split())
        assert tokens < 500, f"L3 has {tokens} tokens, expected <500"

    def test_l3_round_trips_through_parser(self):
        from ctxpack.core.parser import parse

        l2 = self._make_l2_doc()
        l3 = generate_l3(l2)
        text = serialize(l3)
        reparsed = parse(text)
        assert reparsed.header.layer == Layer.L3

    def test_l3_validates_e010(self):
        l2 = self._make_l2_doc()
        l3 = generate_l3(l2)
        diags = validate(l3)
        errors = [d for d in diags if d.level == DiagnosticLevel.ERROR]
        assert len(errors) == 0, f"L3 validation errors: {errors}"

    def test_pack_with_l3_flag(self):
        result = pack(FIXTURES_DIR, layers=["L2", "L3"])
        assert result.l3_document is not None
        assert result.l3_document.header.layer == Layer.L3
        assert result.manifest_document is not None

    def test_pack_without_l3_flag(self):
        result = pack(FIXTURES_DIR)
        assert result.l3_document is None
        assert result.manifest_document is None


class TestManifest:
    def test_manifest_has_layer_section(self):
        l2 = pack(FIXTURES_DIR).document
        l3 = generate_l3(l2)
        manifest = generate_manifest({"L2": l2, "L3": l3}, domain="test")

        assert manifest.header.layer == Layer.MANIFEST
        section_names = {
            elem.name for elem in manifest.body if isinstance(elem, Section)
        }
        assert "LAYERS" in section_names

    def test_manifest_lists_layers(self):
        l2 = pack(FIXTURES_DIR).document
        l3 = generate_l3(l2)
        manifest = generate_manifest({"L2": l2, "L3": l3}, domain="test")

        layers_sec = next(
            e for e in manifest.body if isinstance(e, Section) and e.name == "LAYERS"
        )
        kvs = [c for c in layers_sec.children if isinstance(c, KeyValue)]
        keys = [kv.key for kv in kvs]
        assert "L2" in keys
        assert "L3" in keys

    def test_manifest_round_trips(self):
        from ctxpack.core.parser import parse

        l2 = pack(FIXTURES_DIR).document
        l3 = generate_l3(l2)
        manifest = generate_manifest({"L2": l2, "L3": l3}, domain="test")
        text = serialize(manifest)
        reparsed = parse(text)
        assert reparsed.header.layer == Layer.MANIFEST


# ═══════════════════════════════════════════════════
# A4: JSON Source Parser
# ═══════════════════════════════════════════════════


class TestJSONParser:
    def test_parse_valid_json(self):
        data = json_parse('{"key": "value"}')
        assert data == {"key": "value"}

    def test_parse_invalid_json(self):
        with pytest.raises(ValueError, match="JSON parse error"):
            json_parse("{invalid", filename="bad.json")


class TestJSONEntityExtraction:
    def test_explicit_entity(self):
        data = {
            "entity": "PRODUCT",
            "description": "Product entity",
            "identifier": {"name": "sku", "type": "string"},
            "status": ["active", "discontinued"],
        }
        entities, rules, warnings = extract_entities_from_json(data, filename="product.json")
        assert len(entities) == 1
        assert entities[0].name == "PRODUCT"
        assert len(entities[0].fields) >= 2

    def test_json_schema_entity(self):
        data = {
            "type": "object",
            "title": "Customer",
            "properties": {
                "id": {"type": "string", "description": "Customer ID"},
                "name": {"type": "string", "description": "Full name"},
                "email": {"type": "string", "description": "Email address"},
            },
            "required": ["id", "name"],
        }
        entities, _, _ = extract_entities_from_json(data, filename="schema.json")
        assert len(entities) == 1
        assert entities[0].name == "CUSTOMER"
        assert len(entities[0].fields) == 3
        # Check required flag
        id_field = next(f for f in entities[0].fields if "id(" in f.value)
        assert "required" in id_field.value

    def test_multiple_entities(self):
        data = {
            "customer": {
                "identifier": {"name": "cust_id"},
                "status": ["active", "inactive"],
            },
            "order": {
                "identifier": {"name": "order_id"},
                "retention": {"active": "indefinite"},
            },
        }
        entities, _, _ = extract_entities_from_json(data, filename="entities.json")
        assert len(entities) == 2
        names = {e.name for e in entities}
        assert "CUSTOMER" in names
        assert "ORDER" in names

    def test_rules_extraction(self):
        data = {
            "rules": [
                {"data_quality": "strict"},
                {"validation": "required"},
            ]
        }
        _, rules, _ = extract_entities_from_json(data, filename="rules.json")
        assert len(rules) == 2
        keys = {r.key for r in rules}
        assert "DATA-QUALITY" in keys

    def test_policies_extraction(self):
        data = {
            "policies": {
                "retention": "90 days",
                "encryption": "AES-256",
            }
        }
        _, rules, _ = extract_entities_from_json(data, filename="policy.json")
        assert len(rules) == 2

    def test_array_of_entities(self):
        data = [
            {"entity": "PRODUCT", "status": ["active"]},
            {"entity": "CATEGORY", "status": ["visible"]},
        ]
        entities, _, _ = extract_entities_from_json(data, filename="list.json")
        assert len(entities) == 2

    def test_object_array_pattern(self):
        data = {
            "events": [
                {"type": "click", "target": "button", "timestamp": "2025-01-01"},
                {"type": "view", "target": "page", "timestamp": "2025-01-02"},
                {"type": "submit", "target": "form", "timestamp": "2025-01-03"},
            ]
        }
        entities, rules, _ = extract_entities_from_json(data, filename="events.json")
        # Should detect events as an entity pattern
        assert len(entities) >= 1
        event_entity = next((e for e in entities if e.name == "EVENTS"), None)
        assert event_entity is not None
        # Should have COUNT and SCHEMA fields
        field_keys = {f.key for f in event_entity.fields}
        assert "COUNT" in field_keys
        assert "SCHEMA" in field_keys

    def test_standalone_values(self):
        data = {
            "version": "2.0",
            "api_base": "https://api.example.com",
        }
        _, rules, _ = extract_entities_from_json(data, filename="config.json")
        assert len(rules) == 2
        keys = {r.key for r in rules}
        assert "VERSION" in keys
        assert "API-BASE" in keys

    def test_empty_json_object(self):
        entities, rules, warnings = extract_entities_from_json({}, filename="empty.json")
        assert entities == []
        assert rules == []

    def test_empty_json_array(self):
        entities, rules, warnings = extract_entities_from_json([], filename="empty.json")
        assert entities == []
        assert rules == []


class TestJSONDiscovery:
    def test_json_files_discovered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a JSON file
            json_path = os.path.join(tmpdir, "schema.json")
            with open(json_path, "w") as f:
                json.dump({"entity": "TEST"}, f)

            result = discover(tmpdir)
            assert len(result.json_files) == 1
            assert result.json_files[0].endswith("schema.json")

    def test_json_files_excluded_by_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create ctxpack.yaml with exclude
            config_path = os.path.join(tmpdir, "ctxpack.yaml")
            with open(config_path, "w") as f:
                f.write("domain: test\nexclude:\n  - '*.json'\n")

            json_path = os.path.join(tmpdir, "schema.json")
            with open(json_path, "w") as f:
                json.dump({"entity": "TEST"}, f)

            result = discover(tmpdir)
            assert len(result.json_files) == 0


class TestJSONEndToEnd:
    def test_pack_with_json_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create ctxpack.yaml
            config_path = os.path.join(tmpdir, "ctxpack.yaml")
            with open(config_path, "w") as f:
                f.write("domain: json-test\n")

            # Create a JSON entity file
            json_path = os.path.join(tmpdir, "product.json")
            with open(json_path, "w") as f:
                json.dump({
                    "entity": "PRODUCT",
                    "identifier": {"name": "sku", "type": "string"},
                    "status": ["active", "discontinued"],
                }, f)

            result = pack(tmpdir)
            assert result.entity_count >= 1
            text = serialize(result.document)
            assert "PRODUCT" in text

    def test_pack_mixed_yaml_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "ctxpack.yaml")
            with open(config_path, "w") as f:
                f.write("domain: mixed-test\n")

            # YAML entity
            yaml_path = os.path.join(tmpdir, "customer.yaml")
            with open(yaml_path, "w") as f:
                f.write("entity: CUSTOMER\nidentifier:\n  name: cust_id\n  type: UUID\n")

            # JSON entity
            json_path = os.path.join(tmpdir, "order.json")
            with open(json_path, "w") as f:
                json.dump({
                    "entity": "ORDER",
                    "identifier": {"name": "order_id", "type": "int"},
                }, f)

            result = pack(tmpdir)
            text = serialize(result.document)
            assert "CUSTOMER" in text
            assert "ORDER" in text
            assert result.entity_count >= 2
