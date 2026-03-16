"""Tests for KeywordIndex — word-boundary matching with one-to-many resolution.

Written BEFORE implementation (TDD). These tests define the contract.
Production bug fix: substring matching caused "market" to match "marketing",
hydrating wrong value stream. And one-to-many keywords silently dropped
second match.
"""

from __future__ import annotations

import pytest

from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    PlainLine,
    Section,
)


# ── Fixtures ──


def _make_doc(*section_names: str) -> CTXDocument:
    """Build a CTXDocument with named sections (no children needed for keyword tests)."""
    sections = []
    for name in section_names:
        sections.append(Section(name=name, children=()))

    header = Header(
        magic="§CTX",
        version="1.0",
        layer=Layer.L2,
        status_fields=(KeyValue(key="DOMAIN", value="pharma"),),
        metadata=(
            KeyValue(key="COMPRESSED", value="2026-03-16"),
        ),
    )
    return CTXDocument(header=header, body=tuple(sections))


PHARMA_DOC = _make_doc(
    "ENTITY-SUPPLY-CHAIN",
    "ENTITY-MARKET-ACCESS",
    "ENTITY-MARKETING-EXCELLENCE",
    "ENTITY-PATIENT-SERVICES",
    "ENTITY-SUPPLY-CHAIN-AND-PATIENT-SERVICES",
    "ENTITY-PATIENT-SERVICES-REIMAGINATION",
    "ENTITY-CUSTOMER",
    "ENTITY-SALES-REP",
)


# ── Word-boundary matching ──


class TestWordBoundary:
    def test_word_boundary_market_not_matches_marketing(self):
        """The production bug: 'market' must NOT match 'marketing'."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex(word_boundary=True)
        idx.add("market", "ENTITY-MARKET-ACCESS")
        idx.add("marketing", "ENTITY-MARKETING-EXCELLENCE")

        result = idx.match("market access strategy")
        assert "ENTITY-MARKET-ACCESS" in result
        assert "ENTITY-MARKETING-EXCELLENCE" not in result

    def test_word_boundary_market_matches_isolated_market(self):
        """'market' in a query should match when it appears as a whole word."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex(word_boundary=True)
        idx.add("market", "ENTITY-MARKET-ACCESS")

        result = idx.match("the market is growing")
        assert "ENTITY-MARKET-ACCESS" in result

    def test_word_boundary_disabled_allows_substring(self):
        """When word_boundary=False, substring matching is allowed."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex(word_boundary=False)
        idx.add("market", "ENTITY-MARKET-ACCESS")

        result = idx.match("marketing excellence")
        assert "ENTITY-MARKET-ACCESS" in result


# ── One-to-many resolution ──


class TestOneToMany:
    def test_one_to_many_keyword_maps_to_multiple_entities(self):
        """A single keyword can map to multiple entities."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex()
        idx.add("patient", "ENTITY-PATIENT-SERVICES")
        idx.add("patient", "ENTITY-PATIENT-SERVICES-REIMAGINATION")

        result = idx.match("patient services")
        assert "ENTITY-PATIENT-SERVICES" in result
        assert "ENTITY-PATIENT-SERVICES-REIMAGINATION" in result

    def test_one_to_many_does_not_silently_drop(self):
        """The production bug: second mapping must NOT be silently dropped."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex()
        idx.add("services", "ENTITY-SUPPLY-CHAIN-AND-PATIENT-SERVICES")
        idx.add("services", "ENTITY-PATIENT-SERVICES")
        idx.add("services", "ENTITY-PATIENT-SERVICES-REIMAGINATION")

        result = idx.match("services overview")
        assert len(result) >= 3, (
            f"Expected at least 3 entities, got {len(result)}: {result}"
        )


# ── Auto-generation from entity names ──


class TestAutoGenerate:
    def test_auto_generate_from_entity_names(self):
        """from_document() should auto-generate keywords from section names."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex.from_document(PHARMA_DOC)
        mapping = idx.to_dict()
        # "customer" should be a keyword mapping to ENTITY-CUSTOMER
        assert "customer" in mapping
        assert "ENTITY-CUSTOMER" in mapping["customer"]

    def test_auto_generate_splits_on_ampersand(self):
        """Entity names with & or AND should split into component keywords."""
        from ctxpack.modules.keywords import KeywordIndex

        doc = _make_doc("ENTITY-SUPPLY-CHAIN-AND-PATIENT-SERVICES")
        idx = KeywordIndex.from_document(doc)
        mapping = idx.to_dict()
        # "supply" and "patient" and "services" should all be keywords
        assert "supply" in mapping
        assert "patient" in mapping
        assert "services" in mapping

    def test_auto_generate_filters_generic_words(self):
        """Generic words (the, and, or, for) should not become keywords."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex.from_document(PHARMA_DOC)
        mapping = idx.to_dict()
        for generic in ("the", "and", "for"):
            assert generic not in mapping, f"Generic word '{generic}' should be filtered"

    def test_auto_generate_min_length_filter(self):
        """Words shorter than min_keyword_length should be excluded."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex.from_document(PHARMA_DOC, min_keyword_length=5)
        mapping = idx.to_dict()
        for keyword in mapping:
            assert len(keyword) >= 5, (
                f"Keyword '{keyword}' is shorter than min_keyword_length=5"
            )


# ── Manual synonyms ──


class TestSynonyms:
    def test_manual_synonyms_added(self):
        """add_synonyms() should register manual synonym -> entity mappings."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex()
        idx.add("customer", "ENTITY-CUSTOMER")
        idx.add_synonyms({"hcp": "ENTITY-CUSTOMER", "rep": "ENTITY-SALES-REP"})

        result = idx.match("hcp engagement")
        assert "ENTITY-CUSTOMER" in result

        result = idx.match("rep performance")
        assert "ENTITY-SALES-REP" in result


# ── Match scoring ──


class TestMatchScoring:
    def test_match_returns_all_entities_sorted_by_score(self):
        """Entities with more keyword hits should rank higher."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex()
        idx.add("patient", "ENTITY-PATIENT-SERVICES")
        idx.add("services", "ENTITY-PATIENT-SERVICES")
        idx.add("patient", "ENTITY-PATIENT-SERVICES-REIMAGINATION")
        idx.add("reimagination", "ENTITY-PATIENT-SERVICES-REIMAGINATION")
        idx.add("supply", "ENTITY-SUPPLY-CHAIN")
        idx.add("chain", "ENTITY-SUPPLY-CHAIN")

        # Query "patient services" — ENTITY-PATIENT-SERVICES matches 2 keywords,
        # ENTITY-PATIENT-SERVICES-REIMAGINATION matches 1 keyword
        result = idx.match("patient services")
        assert result[0] == "ENTITY-PATIENT-SERVICES"
        assert "ENTITY-PATIENT-SERVICES-REIMAGINATION" in result

    def test_match_empty_query_returns_empty(self):
        """Empty query should return no results."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex()
        idx.add("patient", "ENTITY-PATIENT-SERVICES")

        result = idx.match("")
        assert result == []

    def test_match_no_match_returns_empty(self):
        """Query with no matching keywords should return empty."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex()
        idx.add("patient", "ENTITY-PATIENT-SERVICES")

        result = idx.match("xyzzy nonsense gibberish")
        assert result == []


# ── from_document ──


class TestFromDocument:
    def test_from_document_builds_index(self):
        """from_document() should build a usable index from a CTXDocument."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex.from_document(PHARMA_DOC)

        # Should match "market" to ENTITY-MARKET-ACCESS but not ENTITY-MARKETING-EXCELLENCE
        result = idx.match("market access")
        assert "ENTITY-MARKET-ACCESS" in result
        # "marketing" is a different word — should NOT match on "market"
        marketing_matched = "ENTITY-MARKETING-EXCELLENCE" in result
        # Only if the query literally contains "marketing" should it match
        assert not marketing_matched, (
            "Word-boundary violation: 'market' matched 'marketing'"
        )

    def test_from_document_one_to_many_via_shared_words(self):
        """Entities sharing words should both appear in results."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex.from_document(PHARMA_DOC)

        result = idx.match("patient services reimagination")
        # Both entities containing "patient" + "services" should appear
        assert "ENTITY-PATIENT-SERVICES" in result
        assert "ENTITY-PATIENT-SERVICES-REIMAGINATION" in result


# ── to_dict export ──


class TestToDict:
    def test_to_dict_exports_map(self):
        """to_dict() should return a dict of keyword -> list[entity_name]."""
        from ctxpack.modules.keywords import KeywordIndex

        idx = KeywordIndex()
        idx.add("patient", "ENTITY-PATIENT-SERVICES")
        idx.add("patient", "ENTITY-PATIENT-SERVICES-REIMAGINATION")
        idx.add("supply", "ENTITY-SUPPLY-CHAIN")

        d = idx.to_dict()
        assert isinstance(d, dict)
        assert "patient" in d
        assert isinstance(d["patient"], list)
        assert len(d["patient"]) == 2
        assert "ENTITY-PATIENT-SERVICES" in d["patient"]
        assert "ENTITY-PATIENT-SERVICES-REIMAGINATION" in d["patient"]
        assert "supply" in d
        assert d["supply"] == ["ENTITY-SUPPLY-CHAIN"]
