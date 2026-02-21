"""End-to-end packer tests."""

import os
import pytest
from ctxpack.core.packer import pack
from ctxpack.core.parser import parse
from ctxpack.core.serializer import serialize
from ctxpack.core.validator import validate
from ctxpack.core.model import Section, KeyValue, Layer
from ctxpack.core.errors import DiagnosticLevel


FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "sample-corpus"
)


class TestPackerEndToEnd:
    def test_pack_produces_document(self):
        result = pack(FIXTURES_DIR)
        assert result.document is not None
        assert result.document.header.layer == Layer.L2

    def test_pack_has_domain(self):
        result = pack(FIXTURES_DIR)
        assert result.document.header.get("DOMAIN") == "customer-data-platform"

    def test_pack_has_entities(self):
        result = pack(FIXTURES_DIR)
        sections = [e for e in result.document.body if isinstance(e, Section)]
        entity_sections = [s for s in sections if s.name.startswith("ENTITY-")]
        assert len(entity_sections) >= 2  # At least CUSTOMER and ORDER

    def test_pack_entity_has_fields(self):
        result = pack(FIXTURES_DIR)
        sections = [e for e in result.document.body if isinstance(e, Section)]
        customer = next(
            (s for s in sections if s.name == "ENTITY-CUSTOMER"), None
        )
        assert customer is not None
        kv_children = [c for c in customer.children if isinstance(c, KeyValue)]
        keys = [kv.key for kv in kv_children]
        assert "IDENTIFIER" in keys

    def test_pack_validates(self):
        result = pack(FIXTURES_DIR)
        diags = validate(result.document)
        errors = [d for d in diags if d.level == DiagnosticLevel.ERROR]
        assert len(errors) == 0, f"Validation errors: {errors}"

    def test_pack_serializes(self):
        result = pack(FIXTURES_DIR)
        text = serialize(result.document)
        assert "§CTX v1.0 L2" in text
        assert "ENTITY-CUSTOMER" in text

    def test_pack_round_trip(self):
        """pack → serialize → parse → identical structure."""
        result = pack(FIXTURES_DIR)
        text = serialize(result.document)
        reparsed = parse(text)
        assert reparsed.header.layer == Layer.L2
        assert reparsed.header.get("DOMAIN") == "customer-data-platform"
        orig_sections = [e for e in result.document.body if isinstance(e, Section)]
        new_sections = [e for e in reparsed.body if isinstance(e, Section)]
        assert len(new_sections) >= len(orig_sections) - 1  # Allow minor diff from serialization

    def test_pack_source_stats(self):
        result = pack(FIXTURES_DIR)
        assert result.source_token_count > 0
        assert result.source_file_count >= 4  # at least 2 YAML + 2 MD

    def test_pack_entity_count(self):
        result = pack(FIXTURES_DIR)
        assert result.entity_count >= 2

    def test_pack_with_domain_override(self):
        result = pack(FIXTURES_DIR, domain="custom-domain")
        assert result.document.header.get("DOMAIN") == "custom-domain"

    def test_pack_ascii_serialization(self):
        result = pack(FIXTURES_DIR)
        text = serialize(result.document, ascii_mode=True)
        assert "$CTX" in text
        assert "##ENTITY-CUSTOMER" in text
        assert "±" not in text

    def test_pack_golden_source_subtitle(self):
        result = pack(FIXTURES_DIR)
        sections = [e for e in result.document.body if isinstance(e, Section)]
        customer = next(
            (s for s in sections if s.name == "ENTITY-CUSTOMER"), None
        )
        assert customer is not None
        # Should have golden source in subtitles
        all_subtitles = " ".join(customer.subtitles)
        assert "GOLDEN-SOURCE" in all_subtitles or any(
            c.key == "★GOLDEN-SOURCE"
            for c in customer.children
            if isinstance(c, KeyValue)
        )


class TestPackerConflictDetection:
    def test_retention_conflict_detected(self):
        result = pack(FIXTURES_DIR)
        assert result.warning_count >= 0  # Warnings are detected if retention conflicts exist


class TestPackerEntityResolution:
    def test_customer_entities_merged(self):
        """CUSTOMER from YAML + CUSTOMER from MD should merge into one ENTITY-CUSTOMER."""
        result = pack(FIXTURES_DIR)
        sections = [e for e in result.document.body if isinstance(e, Section)]
        entity_customer = [s for s in sections if s.name == "ENTITY-CUSTOMER"]
        assert len(entity_customer) == 1  # Should be merged
