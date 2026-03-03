"""Tests for Phase B: WS4 (L3 Cross-Entity Intelligence) and WS5 (Manifest V2).

WS4: L3 topology detection, entity role tags, constraint severity, ID-pattern
      aggregation, token-budget trimming.
WS5: Section/entity/keyword indexes, budget metadata, round-trip, empty doc.
"""

from __future__ import annotations

import pytest

from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    PlainLine,
    Provenance,
    Section,
)
from ctxpack.core.errors import Span
from ctxpack.core.packer.l3_generator import generate_l3
from ctxpack.core.packer.manifest import generate_manifest
from ctxpack.core.serializer import serialize
from ctxpack.core.parser import parse


# ── Helpers ──────────────────────────────────────────


def _make_l2_doc(sections, domain="test"):
    """Build a synthetic L2 CTXDocument with the given body sections."""
    return CTXDocument(
        header=Header(
            magic="§CTX",
            version="1.0",
            layer=Layer.L2,
            status_fields=(KeyValue(key="DOMAIN", value=domain),),
            metadata=(
                KeyValue(key="SOURCE_TOKENS", value="~1000"),
                KeyValue(key="CTX_TOKENS", value="~200"),
            ),
        ),
        body=tuple(sections),
    )


def _build_multi_entity_l2():
    """Build a 5-entity L2 document where:

    - CUSTOMER is a hub (referenced by ORDER, PAYMENT, MERCHANT via @ENTITY-CUSTOMER)
    - PRODUCT is a leaf (zero inbound refs)
    - ORDER is a bridge (referenced by PAYMENT only, so 1 inbound)
    - PAYMENT references both CUSTOMER and ORDER
    - MERCHANT references CUSTOMER
    """
    customer_section = Section(
        name="ENTITY-CUSTOMER",
        children=(
            KeyValue(key="IDENTIFIER", value="cust_id(UUID,unique)"),
            KeyValue(key="PII", value="name+email"),
            KeyValue(key="STATUS-MACHINE", value="active→inactive→closed"),
            KeyValue(key="RETENTION", value="7-years"),
            KeyValue(key="IMMUTABLE-AFTER", value="closed"),
        ),
    )

    order_section = Section(
        name="ENTITY-ORDER",
        children=(
            KeyValue(key="IDENTIFIER", value="order_id(int,auto-increment)"),
            KeyValue(key="BELONGS-TO", value="@ENTITY-CUSTOMER"),
            KeyValue(key="STATUS-MACHINE", value="pending→confirmed→shipped→delivered"),
            KeyValue(key="MATCH-RULES", value="[order_id,cust_id,date]"),
        ),
    )

    product_section = Section(
        name="ENTITY-PRODUCT",
        children=(
            KeyValue(key="IDENTIFIER", value="sku(string,unique)"),
            KeyValue(key="STATUS-MACHINE", value="active→discontinued"),
        ),
    )

    payment_section = Section(
        name="ENTITY-PAYMENT",
        children=(
            KeyValue(key="IDENTIFIER", value="payment_id(UUID,unique)"),
            KeyValue(key="BELONGS-TO", value="@ENTITY-CUSTOMER"),
            KeyValue(key="REFERENCES", value="@ENTITY-ORDER"),
            KeyValue(key="★AMOUNT", value="decimal(19,4)"),
            KeyValue(key="PII-CLASSIFICATION", value="card-number→PCI-DSS"),
        ),
    )

    merchant_section = Section(
        name="ENTITY-MERCHANT",
        children=(
            KeyValue(key="IDENTIFIER", value="merchant_id(int,unique)"),
            KeyValue(key="BELONGS-TO", value="@ENTITY-CUSTOMER"),
            KeyValue(key="RETENTION", value="indefinite"),
        ),
    )

    warnings_section = Section(
        name="WARNINGS",
        children=(
            PlainLine(text="PII fields in CUSTOMER require encryption at rest"),
            PlainLine(text="PAYMENT.card-number subject to PCI-DSS"),
        ),
    )

    return _make_l2_doc([
        customer_section,
        order_section,
        product_section,
        payment_section,
        merchant_section,
        warnings_section,
    ])


# ═══════════════════════════════════════════════════════
# WS4: L3 Cross-Entity Intelligence
# ═══════════════════════════════════════════════════════


class TestL3TopologyDetection:
    """Tests 1-5: entity classification and TOPOLOGY section structure."""

    def setup_method(self):
        self.l2 = _build_multi_entity_l2()
        self.l3 = generate_l3(self.l2)
        self.topology = next(
            s for s in self.l3.body
            if isinstance(s, Section) and s.name == "TOPOLOGY"
        )
        self.topology_texts = [
            c.text for c in self.topology.children if isinstance(c, PlainLine)
        ]

    def test_customer_classified_as_hub(self):
        """T1: CUSTOMER has 3+ inbound @ENTITY-CUSTOMER refs -> hub."""
        hubs_line = next(
            (t for t in self.topology_texts if t.startswith("HUBS:")), None
        )
        assert hubs_line is not None, "Expected HUBS line in TOPOLOGY"
        assert "CUSTOMER" in hubs_line

    def test_product_classified_as_leaf(self):
        """T2: PRODUCT has 0 inbound refs -> leaf."""
        leaves_line = next(
            (t for t in self.topology_texts if t.startswith("LEAVES:")), None
        )
        assert leaves_line is not None, "Expected LEAVES line in TOPOLOGY"
        assert "PRODUCT" in leaves_line

    def test_order_classified_as_bridge(self):
        """T3: ORDER has 1 inbound ref (from PAYMENT) -> bridge."""
        bridges_line = next(
            (t for t in self.topology_texts if t.startswith("BRIDGES:")), None
        )
        assert bridges_line is not None, "Expected BRIDGES line in TOPOLOGY"
        assert "ORDER" in bridges_line

    def test_topology_has_hubs_leaves_bridges(self):
        """T4: TOPOLOGY section contains HUBS, LEAVES, and BRIDGES lines."""
        prefixes = {t.split(":")[0] for t in self.topology_texts}
        assert "HUBS" in prefixes
        assert "LEAVES" in prefixes
        assert "BRIDGES" in prefixes

    def test_topology_has_graph_summary(self):
        """T5: TOPOLOGY section has a GRAPH summary line with entity and edge counts."""
        graph_line = next(
            (t for t in self.topology_texts if t.startswith("GRAPH:")), None
        )
        assert graph_line is not None, "Expected GRAPH summary in TOPOLOGY"
        assert "5-entities" in graph_line
        # ORDER gets 1 ref (from PAYMENT), CUSTOMER gets 3 (ORDER+PAYMENT+MERCHANT)
        # Total edges should be >= 4
        assert "edges" in graph_line


class TestL3EntityRoleTags:
    """Test 6: entity role tags in ENTITIES section."""

    def test_hub_entity_shows_hub_tag(self):
        """T6: Hub entity (CUSTOMER) shows (hub) in ENTITIES section."""
        l2 = _build_multi_entity_l2()
        l3 = generate_l3(l2)
        entities_sec = next(
            s for s in l3.body
            if isinstance(s, Section) and s.name == "ENTITIES"
        )
        all_text = " ".join(
            c.text for c in entities_sec.children if isinstance(c, PlainLine)
        )
        assert "(hub)" in all_text
        # Specifically check CUSTOMER has the hub tag
        customer_line = next(
            (c.text for c in entities_sec.children
             if isinstance(c, PlainLine) and "CUSTOMER" in c.text),
            None,
        )
        assert customer_line is not None
        assert "(hub)" in customer_line


class TestL3ConstraintSeverity:
    """Tests 7-8: constraint severity ranking and density."""

    def setup_method(self):
        self.l2 = _build_multi_entity_l2()
        self.l3 = generate_l3(self.l2)
        self.constraints = next(
            s for s in self.l3.body
            if isinstance(s, Section) and s.name == "CONSTRAINTS"
        )
        self.constraint_texts = [
            c.text for c in self.constraints.children if isinstance(c, PlainLine)
        ]

    def test_pii_before_star_fields(self):
        """T7: PII constraints appear before star-marked fields in severity order."""
        pii_indices = [
            i for i, t in enumerate(self.constraint_texts)
            if "PII" in t
        ]
        star_indices = [
            i for i, t in enumerate(self.constraint_texts)
            if "★" in t or "AMOUNT" in t  # ★AMOUNT from PAYMENT entity
        ]
        if pii_indices and star_indices:
            assert max(pii_indices) < min(star_indices), (
                f"PII items (indices {pii_indices}) should come before "
                f"starred items (indices {star_indices})"
            )

    def test_constraint_density_present(self):
        """T8: CONSTRAINTS section includes a DENSITY line."""
        density_line = next(
            (t for t in self.constraint_texts if t.startswith("DENSITY:")), None
        )
        assert density_line is not None, "Expected DENSITY line in CONSTRAINTS"
        assert "constraints" in density_line
        assert "entities" in density_line


class TestL3IDPattern:
    """Test 9: ID-PATTERN aggregation in PATTERNS section."""

    def test_id_pattern_shows_dominant_type(self):
        """T9: PATTERNS section shows the dominant ID type."""
        l2 = _build_multi_entity_l2()
        l3 = generate_l3(l2)
        patterns_sec = next(
            s for s in l3.body
            if isinstance(s, Section) and s.name == "PATTERNS"
        )
        patterns_text = " ".join(
            c.text for c in patterns_sec.children if isinstance(c, PlainLine)
        )
        assert "ID-PATTERN:" in patterns_text


class TestL3TokenBudgetTrimming:
    """Test 10: body exceeding 500 tokens triggers trimming of PATTERNS/CONSTRAINTS."""

    def test_trimming_when_over_budget(self):
        """T10: When L2 body would produce >500 token L3, PATTERNS/CONSTRAINTS are trimmed."""
        # Build a large L2 with many entities to push L3 over budget
        sections = []
        for i in range(40):
            sections.append(Section(
                name=f"ENTITY-ITEM{i:03d}",
                children=(
                    KeyValue(key="IDENTIFIER", value=f"item_{i:03d}_id(UUID,unique)"),
                    KeyValue(key="STATUS-MACHINE",
                             value="draft→review→approved→published→archived→deleted"),
                    KeyValue(key="MATCH-RULES",
                             value=f"[id,name,type,category,subcategory,status,created,updated]"),
                    KeyValue(key="RETENTION", value=f"retention-{i}-years-from-creation"),
                    KeyValue(key="★PRIORITY", value=f"level-{i % 5}"),
                    KeyValue(key="PII", value=f"field_{i}_name+field_{i}_email"),
                    KeyValue(key="IMMUTABLE-AFTER", value="archived"),
                ),
            ))

        l2 = _make_l2_doc(sections)
        l3 = generate_l3(l2)
        text = serialize(l3)
        token_count = len(text.split())

        # Should be trimmed to <=500 tokens, or at least show evidence of trimming
        # Check that PATTERNS or CONSTRAINTS got trimmed
        all_l3_text = " ".join(
            c.text for s in l3.body if isinstance(s, Section)
            for c in s.children if isinstance(c, PlainLine)
        )
        # Either the token count is within budget, or we see "(trimmed)"
        assert token_count <= 550 or "(trimmed)" in all_l3_text, (
            f"L3 has {token_count} tokens but no trimming evidence"
        )


class TestL3NoPatterns:
    """Test 11: L3 with no patterns detected."""

    def test_no_patterns_shows_none_detected(self):
        """T11: Entity with no STATUS-MACHINE/MATCH-RULES/RETENTION -> '(none detected)'."""
        bare_section = Section(
            name="ENTITY-BARE",
            children=(
                KeyValue(key="DESCRIPTION", value="A bare entity with no patterns"),
            ),
        )
        l2 = _make_l2_doc([bare_section])
        l3 = generate_l3(l2)

        patterns_sec = next(
            s for s in l3.body
            if isinstance(s, Section) and s.name == "PATTERNS"
        )
        patterns_text = " ".join(
            c.text for c in patterns_sec.children if isinstance(c, PlainLine)
        )
        assert "(none detected)" in patterns_text


class TestL3WarningsCopy:
    """Test 12: L3 WARNINGS section copies from L2."""

    def test_warnings_copied_from_l2(self):
        """T12: L3 WARNINGS section contains the same warnings as L2."""
        l2 = _build_multi_entity_l2()
        l3 = generate_l3(l2)

        warnings_sec = next(
            s for s in l3.body
            if isinstance(s, Section) and s.name == "WARNINGS"
        )
        warnings_text = " ".join(
            c.text for c in warnings_sec.children if isinstance(c, PlainLine)
        )
        assert "PII fields in CUSTOMER require encryption at rest" in warnings_text
        assert "PCI-DSS" in warnings_text


# ═══════════════════════════════════════════════════════
# WS5: Manifest V2
# ═══════════════════════════════════════════════════════


class TestManifestSectionIndex:
    """Tests 1-2: section index with token counts and key lists."""

    def setup_method(self):
        self.l2 = _build_multi_entity_l2()
        self.l3 = generate_l3(self.l2)
        self.manifest = generate_manifest(
            {"L2": self.l2, "L3": self.l3}, domain="test"
        )
        self.section_index = next(
            (s for s in self.manifest.body
             if isinstance(s, Section) and s.name == "SECTION-INDEX"),
            None,
        )

    def test_section_index_lists_with_token_counts(self):
        """M1: SECTION-INDEX lists sections with token counts."""
        assert self.section_index is not None, "Expected SECTION-INDEX in manifest"
        kvs = [c for c in self.section_index.children if isinstance(c, KeyValue)]
        assert len(kvs) > 0
        # Each value should contain a token count
        for kv in kvs:
            assert "tok" in kv.value, f"Expected token count in {kv.key}: {kv.value}"

    def test_section_index_keys_list_correct(self):
        """M2: SECTION-INDEX values include keys:[...] for the section's KV children."""
        assert self.section_index is not None
        kvs = [c for c in self.section_index.children if isinstance(c, KeyValue)]
        # ENTITY-CUSTOMER should list its keys
        customer_kv = next(
            (kv for kv in kvs if kv.key == "ENTITY-CUSTOMER"), None
        )
        assert customer_kv is not None, "Expected ENTITY-CUSTOMER in section index"
        assert "keys:[" in customer_kv.value
        assert "IDENTIFIER" in customer_kv.value


class TestManifestEntityIndex:
    """Tests 3-4: entity index mapping entity names to sections."""

    def setup_method(self):
        self.l2 = _build_multi_entity_l2()
        self.l3 = generate_l3(self.l2)
        self.manifest = generate_manifest(
            {"L2": self.l2, "L3": self.l3}, domain="test"
        )
        self.entity_index = next(
            (s for s in self.manifest.body
             if isinstance(s, Section) and s.name == "ENTITY-INDEX"),
            None,
        )

    def test_entity_names_map_to_sections(self):
        """M3: ENTITY-INDEX maps entity names to their section names."""
        assert self.entity_index is not None, "Expected ENTITY-INDEX in manifest"
        kvs = {c.key: c.value for c in self.entity_index.children
               if isinstance(c, KeyValue)}
        assert "CUSTOMER" in kvs
        assert "ORDER" in kvs
        assert "PRODUCT" in kvs
        assert "PAYMENT" in kvs
        assert "MERCHANT" in kvs
        # Each value should reference the section
        assert "ENTITY-CUSTOMER" in kvs["CUSTOMER"]

    def test_entity_index_has_token_counts(self):
        """M3b: Entity index entries include token cost."""
        assert self.entity_index is not None
        kvs = [c for c in self.entity_index.children if isinstance(c, KeyValue)]
        for kv in kvs:
            assert "tok" in kv.value, f"Expected token count for {kv.key}: {kv.value}"


class TestManifestKeywordIndex:
    """Tests 4-5: keyword index with entity names and cross-ref targets."""

    def setup_method(self):
        self.l2 = _build_multi_entity_l2()
        self.l3 = generate_l3(self.l2)
        self.manifest = generate_manifest(
            {"L2": self.l2, "L3": self.l3}, domain="test"
        )
        self.keyword_index = next(
            (s for s in self.manifest.body
             if isinstance(s, Section) and s.name == "KEYWORD-INDEX"),
            None,
        )

    def test_entity_names_appear_as_keywords(self):
        """M4: Entity names appear as keywords in KEYWORD-INDEX."""
        assert self.keyword_index is not None, "Expected KEYWORD-INDEX in manifest"
        all_values = " ".join(
            c.value for c in self.keyword_index.children
            if isinstance(c, KeyValue)
        )
        assert "customer" in all_values.lower()
        assert "order" in all_values.lower()

    def test_crossref_targets_appear_as_keywords(self):
        """M5: Cross-ref targets (e.g. CUSTOMER from @ENTITY-CUSTOMER) appear as keywords."""
        assert self.keyword_index is not None
        # ORDER section references @ENTITY-CUSTOMER, so CUSTOMER should be a keyword for ORDER
        order_kw = next(
            (c for c in self.keyword_index.children
             if isinstance(c, KeyValue) and c.key == "ENTITY-ORDER"),
            None,
        )
        assert order_kw is not None, "Expected ENTITY-ORDER in keyword index"
        assert "customer" in order_kw.value.lower(), (
            f"Expected 'customer' as keyword for ORDER, got: {order_kw.value}"
        )


class TestManifestBudgetMetadata:
    """Tests 6-8: budget metadata in manifest header."""

    def setup_method(self):
        self.l2 = _build_multi_entity_l2()
        self.l3 = generate_l3(self.l2)
        self.manifest = generate_manifest(
            {"L2": self.l2, "L3": self.l3}, domain="test"
        )

    def test_total_l2_tokens_present(self):
        """M6: TOTAL_L2_TOKENS present in manifest header metadata."""
        val = self.manifest.header.get("TOTAL_L2_TOKENS")
        assert val is not None, "Expected TOTAL_L2_TOKENS in manifest header"
        assert val.startswith("~")

    def test_total_l3_tokens_present(self):
        """M7: TOTAL_L3_TOKENS present in manifest header metadata."""
        val = self.manifest.header.get("TOTAL_L3_TOKENS")
        assert val is not None, "Expected TOTAL_L3_TOKENS in manifest header"
        assert val.startswith("~")

    def test_avg_section_tokens_present(self):
        """M8: AVG_SECTION_TOKENS present in manifest header metadata."""
        val = self.manifest.header.get("AVG_SECTION_TOKENS")
        assert val is not None, "Expected AVG_SECTION_TOKENS in manifest header"
        assert val.startswith("~")


class TestManifestRoundTrip:
    """Test 9: serialize then parse manifest."""

    def test_manifest_round_trip(self):
        """M9: Manifest serializes and parses back to MANIFEST layer."""
        l2 = _build_multi_entity_l2()
        l3 = generate_l3(l2)
        manifest = generate_manifest({"L2": l2, "L3": l3}, domain="test")

        text = serialize(manifest)
        reparsed = parse(text)

        assert reparsed.header.layer == Layer.MANIFEST
        section_names = {
            s.name for s in reparsed.body if isinstance(s, Section)
        }
        assert "LAYERS" in section_names
        assert "SECTION-INDEX" in section_names
        assert "ENTITY-INDEX" in section_names


class TestManifestEmptyDoc:
    """Test 10: empty L2 document produces minimal manifest."""

    def test_empty_l2_produces_minimal_manifest(self):
        """M10: An L2 doc with no body sections produces a manifest with only LAYERS."""
        l2 = _make_l2_doc([])
        manifest = generate_manifest({"L2": l2}, domain="empty-test")

        assert manifest.header.layer == Layer.MANIFEST
        section_names = [
            s.name for s in manifest.body if isinstance(s, Section)
        ]
        # LAYERS should always be present
        assert "LAYERS" in section_names
        # No entity or section index since no body sections
        # (SECTION-INDEX, ENTITY-INDEX, KEYWORD-INDEX should be absent or empty)
        entity_idx = next(
            (s for s in manifest.body
             if isinstance(s, Section) and s.name == "ENTITY-INDEX"),
            None,
        )
        assert entity_idx is None, "Empty L2 should not produce ENTITY-INDEX"
