"""Tests for Catalog-Wide Query Detection module (M4).

TDD tests — written before implementation.
Detects catalog-wide intent and builds grouped summaries.
"""

from __future__ import annotations

import pytest

from ctxpack.modules.catalog_queries import is_catalog_query, build_catalog_summary
from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    Section,
)


# ── Fixtures ──


def _make_catalog_doc() -> CTXDocument:
    """Build a CTXDocument with multiple entity sections for catalog testing."""
    sections = [
        Section(name="ENTITY-CL-001", children=(
            KeyValue(key="IDENTIFIER", value="cl_001"),
            KeyValue(key="TYPE", value="premium"),
        )),
        Section(name="ENTITY-CL-002", children=(
            KeyValue(key="IDENTIFIER", value="cl_002"),
            KeyValue(key="TYPE", value="standard"),
        )),
        Section(name="ENTITY-CL-003", children=(
            KeyValue(key="IDENTIFIER", value="cl_003"),
            KeyValue(key="TYPE", value="premium"),
        )),
        Section(name="ENTITY-MR-001", children=(
            KeyValue(key="IDENTIFIER", value="mr_001"),
        )),
        Section(name="ENTITY-MR-002", children=(
            KeyValue(key="IDENTIFIER", value="mr_002"),
        )),
        Section(name="ENTITY-IM-001", children=(
            KeyValue(key="IDENTIFIER", value="im_001"),
        )),
        Section(name="RULES-DATA-QUALITY", children=(
            KeyValue(key="UNIQUENESS", value="id:unique-per-entity"),
        )),
    ]
    header = Header(
        magic="§CTX",
        version="1.0",
        layer=Layer.L2,
        status_fields=(KeyValue(key="DOMAIN", value="test-catalog"),),
        metadata=(
            KeyValue(key="COMPRESSED", value="2026-03-16"),
        ),
    )
    return CTXDocument(header=header, body=tuple(sections))


CATALOG_DOC = _make_catalog_doc()


# ── is_catalog_query detection ──


class TestIsCatalogQuery:
    def test_detects_how_many(self):
        assert is_catalog_query("How many entities do we have?") is True

    def test_detects_list_all(self):
        assert is_catalog_query("List all the clients in the catalog") is True

    def test_detects_total_count(self):
        assert is_catalog_query("What is the total count of merchants?") is True

    def test_detects_overview(self):
        assert is_catalog_query("Give me an overview of the system") is True

    def test_detects_every(self):
        assert is_catalog_query("Show me every entity we track") is True

    def test_detects_all_the(self):
        assert is_catalog_query("What are all the products?") is True

    def test_detects_full_list(self):
        assert is_catalog_query("I need a full list of entities") is True

    def test_detects_complete_list(self):
        assert is_catalog_query("Give me the complete list") is True

    def test_detects_what_entities_do_we_have(self):
        assert is_catalog_query(
            "What entities do we have?", entity_type="entities"
        ) is True

    def test_does_not_detect_specific_entity_query(self):
        assert is_catalog_query("What is the retention policy for ENTITY-CUSTOMER?") is False

    def test_does_not_detect_relationship_query(self):
        assert is_catalog_query("How does ENTITY-ORDER relate to ENTITY-CUSTOMER?") is False

    def test_does_not_detect_field_query(self):
        assert is_catalog_query("What fields does ENTITY-PRODUCT have?") is False

    def test_custom_keywords_extend_defaults(self):
        # "enumerate" is not a default keyword
        assert is_catalog_query("Enumerate the items") is False
        # But with custom keyword it should match
        assert is_catalog_query(
            "Enumerate the items", custom_keywords=["enumerate"]
        ) is True

    def test_custom_keywords_dont_replace_defaults(self):
        """Custom keywords extend, not replace."""
        assert is_catalog_query(
            "How many entities?", custom_keywords=["enumerate"]
        ) is True

    def test_empty_query_returns_false(self):
        assert is_catalog_query("") is False

    def test_case_insensitive_detection(self):
        assert is_catalog_query("LIST ALL entities") is True
        assert is_catalog_query("HOW MANY products?") is True


# ── build_catalog_summary ──


class TestBuildCatalogSummary:
    def test_catalog_summary_groups_by_prefix(self):
        summary = build_catalog_summary(CATALOG_DOC)
        # Should group by CL, MR, IM prefixes
        assert "CL" in summary
        assert "MR" in summary
        assert "IM" in summary

    def test_catalog_summary_includes_counts(self):
        summary = build_catalog_summary(CATALOG_DOC)
        # CL has 3 entities
        assert "3" in summary
        # MR has 2 entities
        assert "2" in summary
        # IM has 1 entity
        assert "1" in summary

    def test_catalog_summary_shows_total(self):
        summary = build_catalog_summary(CATALOG_DOC)
        # Total line: 6 ENTITY sections across 3 groups
        assert "6" in summary
        assert "3" in summary

    def test_catalog_summary_lists_entity_ids(self):
        summary = build_catalog_summary(CATALOG_DOC)
        assert "ENTITY-CL-001" in summary
        assert "ENTITY-CL-002" in summary
        assert "ENTITY-MR-001" in summary
        assert "ENTITY-IM-001" in summary

    def test_catalog_summary_excludes_non_entity_sections(self):
        summary = build_catalog_summary(CATALOG_DOC)
        # RULES-DATA-QUALITY is not an entity section, should not appear
        assert "RULES-DATA-QUALITY" not in summary

    def test_catalog_summary_without_counts(self):
        summary = build_catalog_summary(CATALOG_DOC, include_counts=False)
        # Entity names should still be present
        assert "ENTITY-CL-001" in summary
        # But per-group count labels should be absent — we check that
        # the summary is shorter than with counts
        summary_with = build_catalog_summary(CATALOG_DOC, include_counts=True)
        assert len(summary) <= len(summary_with)

    def test_catalog_summary_without_total(self):
        summary = build_catalog_summary(CATALOG_DOC, include_total=False)
        # Should not have "TOTAL:" line
        assert "TOTAL:" not in summary

    def test_catalog_summary_with_total(self):
        summary = build_catalog_summary(CATALOG_DOC, include_total=True)
        assert "TOTAL:" in summary

    def test_catalog_summary_empty_document(self):
        empty = CTXDocument(
            header=Header(
                magic="§CTX", version="1.0", layer=Layer.L2,
                status_fields=(KeyValue(key="DOMAIN", value="test"),),
            ),
            body=(),
        )
        summary = build_catalog_summary(empty)
        assert "0" in summary or summary == "" or "TOTAL: 0" in summary

    def test_catalog_summary_single_group(self):
        """Document with only one prefix group."""
        doc = CTXDocument(
            header=Header(
                magic="§CTX", version="1.0", layer=Layer.L2,
                status_fields=(KeyValue(key="DOMAIN", value="test"),),
            ),
            body=(
                Section(name="ENTITY-CL-001", children=()),
                Section(name="ENTITY-CL-002", children=()),
            ),
        )
        summary = build_catalog_summary(doc)
        assert "CL" in summary
        assert "2" in summary
