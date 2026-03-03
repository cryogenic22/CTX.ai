"""Tests for L1 natural language serializer."""

from __future__ import annotations

import os
import tempfile

import pytest

from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    NumberedItem,
    PlainLine,
    Provenance,
    Section,
)
from ctxpack.core.serializer import (
    _nl_cardinality,
    _nl_decode_value,
    _nl_key_label,
    _nl_section_name,
    serialize,
    serialize_iter,
    serialize_section,
)


# ── Unit tests for name/value converters ──


class TestNlSectionName:
    def test_entity_prefix(self):
        assert _nl_section_name("ENTITY-DRUG") == "Drug"

    def test_entity_customer(self):
        assert _nl_section_name("ENTITY-CUSTOMER") == "Customer"

    def test_rules_prefix(self):
        result = _nl_section_name("RULES-DATA-QUALITY")
        assert "Data Quality" in result
        assert "Rules" in result

    def test_rule_prefix(self):
        result = _nl_section_name("RULE-RETENTION")
        assert "Retention" in result
        assert "Rules" in result

    def test_warning_prefix(self):
        assert _nl_section_name("⚠WARNINGS") == "Warnings"

    def test_plain_name(self):
        assert _nl_section_name("TOPOLOGY") == "Topology"

    def test_multi_hyphen(self):
        result = _nl_section_name("ENTITY-MY-LONG-NAME")
        assert result == "My Long Name"


class TestNlKeyLabel:
    def test_simple(self):
        assert _nl_key_label("IDENTIFIER") == "Identifier"

    def test_hyphenated(self):
        assert _nl_key_label("PII-CLASSIFICATION") == "Pii Classification"

    def test_underscored(self):
        assert _nl_key_label("GOLDEN_SOURCE") == "Golden Source"


class TestNlDecodeValue:
    def test_operators_replaced(self):
        result = _nl_decode_value("", "¬allowed")
        assert "not " in result
        assert "¬" not in result

    def test_arrow_replaced(self):
        result = _nl_decode_value("", "A→B")
        assert "→" not in result
        assert "leads to" in result

    def test_warning_replaced(self):
        result = _nl_decode_value("", "⚠check this")
        assert "Warning:" in result
        assert "⚠" not in result

    def test_crossref_simple(self):
        result = _nl_decode_value("", "@ENTITY-CUSTOMER")
        assert "Customer" in result
        assert "@ENTITY" not in result

    def test_crossref_with_params(self):
        result = _nl_decode_value("", "@ENTITY-COMPANY(merchant_id,N:1)")
        assert "Company" in result
        assert "merchant_id" in result
        assert "many-to-one" in result

    def test_inline_list_separator(self):
        result = _nl_decode_value("", "name+email+phone")
        assert "name, email, phone" in result


class TestNlCardinality:
    def test_one_to_many(self):
        assert _nl_cardinality("1:N") == "one-to-many"

    def test_many_to_one(self):
        assert _nl_cardinality("N:1") == "many-to-one"

    def test_unknown(self):
        assert _nl_cardinality("X:Y") == "X:Y"


# ── Integration tests with AST ──


def _make_test_doc() -> CTXDocument:
    """Create a minimal test document."""
    header = Header(
        magic="§CTX",
        version="1.0",
        layer=Layer.L2,
        status_fields=(
            KeyValue(key="DOMAIN", value="test-domain"),
        ),
        metadata=(
            KeyValue(key="SOURCE_TOKENS", value="500"),
            KeyValue(key="AUTHOR", value="test-author"),
        ),
    )
    body = (
        Section(
            name="ENTITY-CUSTOMER",
            depth=0,
            children=(
                KeyValue(key="IDENTIFIER", value="customer_id(UUID,immutable)"),
                KeyValue(key="PII-CLASSIFICATION", value="RESTRICTED"),
                KeyValue(key="BELONGS-TO", value="@ENTITY-COMPANY(merchant_id,N:1)"),
                PlainLine(text="★GOLDEN-SOURCE:CRM(Salesforce)"),
                Provenance(source="entities/customer.yaml"),
            ),
        ),
        Section(
            name="RULES-DATA-QUALITY",
            depth=0,
            children=(
                KeyValue(key="NULL-POLICY", value="customer_id→never-null"),
                KeyValue(key="FRESHNESS", value="customer-data→24h-max-stale"),
            ),
        ),
        Section(
            name="⚠WARNINGS",
            depth=0,
            children=(
                PlainLine(text="⚠ Retention conflict detected"),
            ),
        ),
    )
    return CTXDocument(header=header, body=body)


class TestNlSerialization:
    def test_header_readable(self):
        doc = _make_test_doc()
        output = serialize(doc, natural_language=True)
        assert output.startswith("# Context Document")
        assert "v1.0" in output
        assert "L2" in output

    def test_no_ctx_operators(self):
        doc = _make_test_doc()
        output = serialize(doc, natural_language=True)
        assert "±" not in output
        assert "§CTX" not in output

    def test_section_headings(self):
        doc = _make_test_doc()
        output = serialize(doc, natural_language=True)
        assert "## Customer" in output

    def test_kv_as_bullets(self):
        doc = _make_test_doc()
        output = serialize(doc, natural_language=True)
        assert "- **Identifier**:" in output

    def test_crossref_expanded(self):
        doc = _make_test_doc()
        output = serialize(doc, natural_language=True)
        assert "Company" in output
        assert "many-to-one" in output

    def test_provenance_readable(self):
        doc = _make_test_doc()
        output = serialize(doc, natural_language=True)
        assert "- Source:" in output
        assert "SRC:" not in output

    def test_warning_readable(self):
        doc = _make_test_doc()
        output = serialize(doc, natural_language=True)
        assert "Warning:" in output

    def test_rules_section_name(self):
        doc = _make_test_doc()
        output = serialize(doc, natural_language=True)
        assert "Data Quality Rules" in output


class TestNlRegression:
    """Ensure natural_language=False is identical to existing serialize()."""

    def test_default_unchanged(self):
        doc = _make_test_doc()
        default = serialize(doc)
        explicit_false = serialize(doc, natural_language=False)
        assert default == explicit_false

    def test_ascii_mode_unchanged(self):
        doc = _make_test_doc()
        default = serialize(doc, ascii_mode=True)
        explicit_false = serialize(doc, ascii_mode=True, natural_language=False)
        assert default == explicit_false


class TestNlSerializeSection:
    def test_section_natural_language(self):
        section = Section(
            name="ENTITY-ORDER",
            depth=0,
            children=(
                KeyValue(key="STATUS-FLOW", value="draft→submitted→shipped→delivered"),
            ),
        )
        lines = list(serialize_section(section, natural_language=True))
        text = "\n".join(lines)
        assert "Order" in text
        assert "±" not in text


class TestNlSerializeIter:
    def test_iter_natural_language(self):
        doc = _make_test_doc()
        lines = list(serialize_iter(doc, natural_language=True))
        text = "\n".join(lines)
        assert "# Context Document" in text
        assert "## Customer" in text


class TestPackWithNl:
    """Test packing a corpus then serializing as NL."""

    def test_pack_then_nl(self):
        from ctxpack.benchmarks.scaling.corpus_generator import generate_corpus
        from ctxpack.core.packer import pack

        with tempfile.TemporaryDirectory() as tmpdir:
            corpus_dir = os.path.join(tmpdir, "corpus")
            generate_corpus(1000, corpus_dir, seed=42)
            result = pack(corpus_dir)

            # L2 output should have ± operators
            l2_text = serialize(result.document)
            assert "±" in l2_text

            # NL output should not
            nl_text = serialize(result.document, natural_language=True)
            assert "±" not in nl_text
            assert "§CTX" not in nl_text
            assert "# Context Document" in nl_text
            assert "##" in nl_text


class TestCLI:
    def test_fmt_natural_language(self):
        from ctxpack.core.parser import parse as ctx_parse

        # Create a temp .ctx file
        doc = _make_test_doc()
        l2_text = serialize(doc)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ctx", delete=False, encoding="utf-8"
        ) as f:
            f.write(l2_text)
            tmp_path = f.name

        try:
            from ctxpack.cli.main import main

            rc = main(["fmt", tmp_path, "--natural-language"])
            assert rc == 0
        finally:
            os.unlink(tmp_path)

    def test_pack_natural_language(self):
        from ctxpack.benchmarks.scaling.corpus_generator import generate_corpus

        with tempfile.TemporaryDirectory() as tmpdir:
            corpus_dir = os.path.join(tmpdir, "corpus")
            generate_corpus(1000, corpus_dir, seed=42)

            from ctxpack.cli.main import main

            rc = main(["pack", corpus_dir, "--natural-language"])
            assert rc == 0
