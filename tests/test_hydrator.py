"""Tests for WS4: Progressive Hydration — Section-Level ctx/hydrate.

Written BEFORE implementation (TDD). These tests define the contract.
"""

from __future__ import annotations

import json

import pytest

from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    PlainLine,
    Section,
)
from ctxpack.core.errors import Span


# ── Fixtures ──


def _make_doc(*section_specs: tuple[str, list[tuple[str, str]]]) -> CTXDocument:
    """Build a CTXDocument with named sections containing KV pairs.

    Args:
        section_specs: (section_name, [(key, value), ...]) tuples
    """
    sections = []
    for name, kvs in section_specs:
        children = [KeyValue(key=k, value=v) for k, v in kvs]
        sections.append(Section(name=name, children=tuple(children)))

    header = Header(
        magic="§CTX",
        version="1.0",
        layer=Layer.L2,
        status_fields=(KeyValue(key="DOMAIN", value="test"),),
        metadata=(
            KeyValue(key="COMPRESSED", value="2026-03-13"),
            KeyValue(key="SOURCE_TOKENS", value="~1000"),
        ),
    )
    return CTXDocument(header=header, body=tuple(sections))


SAMPLE_DOC = _make_doc(
    ("ENTITY-CUSTOMER", [
        ("IDENTIFIER", "customer_id(UUID,immutable)"),
        ("PII", "name+email+phone"),
        ("MATCH-RULES", "[email:exact,phone:E.164,name+address:fuzzy(Jaro-Winkler>0.92)]"),
        ("RETENTION", "active→indefinite|churned→36mo→anonymise"),
    ]),
    ("ENTITY-ORDER", [
        ("IDENTIFIER", "order_id(UUID)"),
        ("BELONGS-TO", "@ENTITY-CUSTOMER(customer_id,N:1)"),
        ("STATUS", "pending→confirmed→shipped→delivered|cancelled"),
    ]),
    ("ENTITY-PRODUCT", [
        ("IDENTIFIER", "sku(string)"),
        ("GOLDEN-SOURCE", "PIM-system"),
    ]),
    ("RULES-DATA-QUALITY", [
        ("UNIQUENESS", "customer_id+order_id:unique-per-entity"),
    ]),
)


# ── hydrate_by_name ──


class TestHydrateByName:
    def test_hydrate_single_section_by_name(self):
        from ctxpack.core.hydrator import hydrate_by_name

        result = hydrate_by_name(SAMPLE_DOC, ["ENTITY-CUSTOMER"])
        assert len(result.sections) == 1
        assert result.sections[0].name == "ENTITY-CUSTOMER"

    def test_hydrate_multiple_sections_by_name(self):
        from ctxpack.core.hydrator import hydrate_by_name

        result = hydrate_by_name(SAMPLE_DOC, ["ENTITY-CUSTOMER", "ENTITY-ORDER"])
        assert len(result.sections) == 2
        names = {s.name for s in result.sections}
        assert names == {"ENTITY-CUSTOMER", "ENTITY-ORDER"}

    def test_hydrate_nonexistent_section_returns_empty(self):
        from ctxpack.core.hydrator import hydrate_by_name

        result = hydrate_by_name(SAMPLE_DOC, ["ENTITY-NONEXISTENT"])
        assert len(result.sections) == 0

    def test_hydrate_mixed_existing_and_nonexistent(self):
        from ctxpack.core.hydrator import hydrate_by_name

        result = hydrate_by_name(SAMPLE_DOC, ["ENTITY-CUSTOMER", "ENTITY-GHOST"])
        assert len(result.sections) == 1
        assert result.sections[0].name == "ENTITY-CUSTOMER"

    def test_hydrate_case_insensitive_matching(self):
        from ctxpack.core.hydrator import hydrate_by_name

        result = hydrate_by_name(SAMPLE_DOC, ["entity-customer"])
        assert len(result.sections) == 1
        assert result.sections[0].name == "ENTITY-CUSTOMER"

    def test_hydrate_includes_header_by_default(self):
        from ctxpack.core.hydrator import hydrate_by_name

        result = hydrate_by_name(SAMPLE_DOC, ["ENTITY-CUSTOMER"])
        assert result.header_text  # Non-empty
        assert "§CTX" in result.header_text or "$CTX" in result.header_text

    def test_hydrate_excludes_header_when_false(self):
        from ctxpack.core.hydrator import hydrate_by_name

        result = hydrate_by_name(SAMPLE_DOC, ["ENTITY-CUSTOMER"],
                                  include_header=False)
        assert result.header_text == ""

    def test_hydrate_tokens_count_is_accurate(self):
        from ctxpack.core.hydrator import hydrate_by_name
        from ctxpack.core.serializer import serialize_section

        result = hydrate_by_name(SAMPLE_DOC, ["ENTITY-CUSTOMER"],
                                  include_header=False)
        # Token count should match serialized output
        serialized = "\n".join(serialize_section(result.sections[0]))
        expected_tokens = len(serialized.split())
        assert abs(result.tokens_injected - expected_tokens) <= 2  # Allow small rounding

    def test_hydrate_preserves_section_content(self):
        from ctxpack.core.hydrator import hydrate_by_name

        result = hydrate_by_name(SAMPLE_DOC, ["ENTITY-CUSTOMER"])
        section = result.sections[0]
        keys = [c.key for c in section.children if isinstance(c, KeyValue)]
        assert "IDENTIFIER" in keys
        assert "PII" in keys
        assert "MATCH-RULES" in keys


# ── hydrate_by_query ──


class TestHydrateByQuery:
    def test_hydrate_by_query_returns_relevant_sections(self):
        from ctxpack.core.hydrator import hydrate_by_query

        result = hydrate_by_query(SAMPLE_DOC, "customer matching rules")
        section_names = {s.name for s in result.sections}
        assert "ENTITY-CUSTOMER" in section_names

    def test_hydrate_by_query_empty_returns_empty(self):
        from ctxpack.core.hydrator import hydrate_by_query

        result = hydrate_by_query(SAMPLE_DOC, "")
        assert len(result.sections) == 0

    def test_hydrate_by_query_max_sections_respected(self):
        from ctxpack.core.hydrator import hydrate_by_query

        result = hydrate_by_query(SAMPLE_DOC, "entity identifier",
                                   max_sections=2)
        assert len(result.sections) <= 2

    def test_hydrate_by_query_no_match_returns_empty(self):
        from ctxpack.core.hydrator import hydrate_by_query

        result = hydrate_by_query(SAMPLE_DOC, "xyzzy nonsense gibberish")
        assert len(result.sections) == 0

    def test_hydrate_by_query_scores_multiple(self):
        """Query mentioning order and product should return both."""
        from ctxpack.core.hydrator import hydrate_by_query

        result = hydrate_by_query(SAMPLE_DOC, "order status product sku")
        section_names = {s.name for s in result.sections}
        assert "ENTITY-ORDER" in section_names or "ENTITY-PRODUCT" in section_names


# ── list_sections ──


class TestListSections:
    def test_list_sections_returns_all_section_names(self):
        from ctxpack.core.hydrator import list_sections

        sections = list_sections(SAMPLE_DOC)
        names = {s["name"] for s in sections}
        assert names == {"ENTITY-CUSTOMER", "ENTITY-ORDER", "ENTITY-PRODUCT",
                         "RULES-DATA-QUALITY"}

    def test_list_sections_includes_token_counts(self):
        from ctxpack.core.hydrator import list_sections

        sections = list_sections(SAMPLE_DOC)
        for s in sections:
            assert "tokens" in s
            assert isinstance(s["tokens"], int)
            assert s["tokens"] > 0

    def test_list_sections_empty_document(self):
        from ctxpack.core.hydrator import list_sections

        empty = CTXDocument(
            header=Header(
                magic="§CTX", version="1.0", layer=Layer.L2,
                status_fields=(KeyValue(key="DOMAIN", value="test"),),
            ),
            body=(),
        )
        sections = list_sections(empty)
        assert sections == []

    def test_list_sections_has_name_and_tokens_keys(self):
        from ctxpack.core.hydrator import list_sections

        sections = list_sections(SAMPLE_DOC)
        for s in sections:
            assert "name" in s
            assert "tokens" in s


# ── Round-trip verification ──


class TestRoundTrip:
    def test_hydrated_output_parses_back(self):
        """Hydrated .ctx text must be parseable."""
        from ctxpack.core.hydrator import hydrate_by_name
        from ctxpack.core.parser import parse

        result = hydrate_by_name(SAMPLE_DOC, ["ENTITY-CUSTOMER"])
        # Reconstruct full .ctx text from header + section
        text = result.header_text
        if text and not text.endswith("\n"):
            text += "\n"
        from ctxpack.core.serializer import serialize_section
        for section in result.sections:
            text += "\n".join(serialize_section(section)) + "\n"

        # Should parse without error
        doc = parse(text, level=2)
        assert doc.header.layer == Layer.L2

    def test_sections_available_count_is_correct(self):
        from ctxpack.core.hydrator import hydrate_by_name

        result = hydrate_by_name(SAMPLE_DOC, ["ENTITY-CUSTOMER"])
        assert result.sections_available == 4  # 4 total sections in SAMPLE_DOC


# ── MCP Integration ──


class TestMCPIntegration:
    def test_mcp_hydrate_with_section_param(self):
        """ctx/hydrate with explicit section name returns that section."""
        from ctxpack.integrations.mcp_server import handle_hydrate
        from ctxpack.core.serializer import serialize

        ctx_text = serialize(SAMPLE_DOC)
        result_json = handle_hydrate({
            "text": ctx_text,
            "query": "",
            "section": "ENTITY-ORDER",
        })
        result = json.loads(result_json)
        assert "ENTITY-ORDER" in result["ctx_text"]

    def test_mcp_hydrate_with_query_param(self):
        """ctx/hydrate with query returns relevant sections."""
        from ctxpack.integrations.mcp_server import handle_hydrate
        from ctxpack.core.serializer import serialize

        ctx_text = serialize(SAMPLE_DOC)
        result_json = handle_hydrate({
            "text": ctx_text,
            "query": "customer matching",
        })
        result = json.loads(result_json)
        assert result["sections_matched"] > 0
