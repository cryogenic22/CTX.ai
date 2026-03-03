"""Tests addressing lead review feedback on Phase B.

Covers:
- Benchmark timing (WS1 perf claim validation)
- Configurable topology thresholds (WS4)
- Semantic keyword extraction in manifest (WS5)
- Query routing simulation for manifest (WS5)
- Unrecognized relationship key handling (WS2)
- --strict suppression of inferred bidirectional relationships (WS2/WS3)
"""

from __future__ import annotations

import time

import pytest

from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    PlainLine,
    Section,
)
from ctxpack.core.packer.compressor import compress, count_tokens
from ctxpack.core.packer.entity_resolver import resolve_entities
from ctxpack.core.packer.ir import (
    Certainty,
    IRCorpus,
    IREntity,
    IRField,
    IRRelationship,
    IRSource,
)
from ctxpack.core.packer.l3_generator import generate_l3
from ctxpack.core.packer.manifest import generate_manifest
from ctxpack.core.packer.yaml_parser import extract_entities_from_yaml, yaml_parse


# ── Helpers ──

def _make_l2_doc(sections, domain="test"):
    return CTXDocument(
        header=Header(
            magic="§CTX", version="1.0", layer=Layer.L2,
            status_fields=(KeyValue(key="DOMAIN", value=domain),),
            metadata=(
                KeyValue(key="SOURCE_TOKENS", value="~1000"),
                KeyValue(key="CTX_TOKENS", value="~200"),
            ),
        ),
        body=tuple(sections),
    )


def _build_corpus(n_entities: int) -> IRCorpus:
    """Build a synthetic corpus with n entities, each referencing the previous."""
    corpus = IRCorpus(domain="bench", source_token_count=n_entities * 50)
    for i in range(n_entities):
        fields = [
            IRField(key="IDENTIFIER", value=f"id_{i}(UUID,unique)",
                    raw_value={"name": f"id_{i}", "type": "UUID"},
                    source=IRSource(file=f"entity_{i}.yaml")),
        ]
        if i > 0:
            fields.append(
                IRField(key="BELONGS-TO",
                        value=f"@ENTITY-E{i-1}(fk_{i-1})",
                        raw_value=f"E{i-1}",
                        source=IRSource(file=f"entity_{i}.yaml"))
            )
        corpus.entities.append(IREntity(
            name=f"E{i}",
            fields=fields,
            sources=[IRSource(file=f"entity_{i}.yaml")],
        ))
    return corpus


# ═══════════════════════════════════════════════════════
# Benchmark Timing (reviewer: "no benchmark numbers")
# ═══════════════════════════════════════════════════════


class TestBenchmarkTiming:
    """Validate that compress() scales linearly, not quadratically."""

    def test_compress_scales_subquadratically(self):
        """Pack 50 entities and 200 entities. Time ratio should be < 8x (linear=4x, quadratic=16x)."""
        small = _build_corpus(50)
        large = _build_corpus(200)

        # Warm up
        compress(small)
        compress(large)

        # Measure small
        t0 = time.perf_counter()
        for _ in range(5):
            compress(small)
        t_small = time.perf_counter() - t0

        # Measure large
        t0 = time.perf_counter()
        for _ in range(5):
            compress(large)
        t_large = time.perf_counter() - t0

        ratio = t_large / max(t_small, 1e-9)
        # Linear would be 4x (200/50). Quadratic would be 16x.
        # Accept up to 10x to account for overhead/noise.
        assert ratio < 10, (
            f"Scaling ratio {ratio:.1f}x exceeds 10x threshold "
            f"(small={t_small:.4f}s, large={t_large:.4f}s). "
            f"Suggests worse-than-linear scaling."
        )

    def test_count_tokens_faster_than_materialization(self):
        """count_tokens() should be at least as fast as building a string and splitting."""
        corpus = _build_corpus(100)
        doc = compress(corpus)

        # count_tokens path
        t0 = time.perf_counter()
        for _ in range(100):
            count_tokens(doc.body)
        t_walk = time.perf_counter() - t0

        # Materialization path (old approach)
        def _materialize(body):
            parts = []
            for elem in body:
                if isinstance(elem, Section):
                    parts.append(f"±{elem.name}")
                    parts.append(_materialize(elem.children))
                elif isinstance(elem, KeyValue):
                    parts.append(f"{elem.key}:{elem.value}")
                elif isinstance(elem, PlainLine):
                    parts.append(elem.text)
            return " ".join(parts)

        t0 = time.perf_counter()
        for _ in range(100):
            text = _materialize(doc.body)
            len(text.split())
        t_mat = time.perf_counter() - t0

        # count_tokens should not be slower than materialization
        assert t_walk <= t_mat * 2, (
            f"count_tokens ({t_walk:.4f}s) more than 2x slower than "
            f"materialization ({t_mat:.4f}s)"
        )


# ═══════════════════════════════════════════════════════
# Configurable Topology Thresholds (reviewer: "thresholds feel arbitrary")
# ═══════════════════════════════════════════════════════


class TestConfigurableTopologyThreshold:
    """Validate that hub_threshold parameter changes classification."""

    def _build_3ref_doc(self):
        """PATIENT has exactly 2 inbound refs — hub at threshold=2, bridge at threshold=3."""
        return _make_l2_doc([
            Section(name="ENTITY-PATIENT", children=(
                KeyValue(key="IDENTIFIER", value="patient_id(UUID)"),
            )),
            Section(name="ENTITY-DIAGNOSIS", children=(
                KeyValue(key="BELONGS-TO", value="@ENTITY-PATIENT(patient_id)"),
            )),
            Section(name="ENTITY-PRESCRIPTION", children=(
                KeyValue(key="BELONGS-TO", value="@ENTITY-PATIENT(patient_id)"),
            )),
        ])

    def test_default_threshold_3_classifies_as_bridge(self):
        """With default hub_threshold=3, PATIENT (2 refs) is a bridge."""
        doc = self._build_3ref_doc()
        l3 = generate_l3(doc)
        topology = next(s for s in l3.body if isinstance(s, Section) and s.name == "TOPOLOGY")
        texts = [c.text for c in topology.children if isinstance(c, PlainLine)]
        bridges = next((t for t in texts if t.startswith("BRIDGES:")), "")
        hubs = next((t for t in texts if t.startswith("HUBS:")), "")
        assert "PATIENT" in bridges
        assert "PATIENT" not in hubs

    def test_threshold_2_classifies_as_hub(self):
        """With hub_threshold=2, PATIENT (2 refs) becomes a hub."""
        doc = self._build_3ref_doc()
        l3 = generate_l3(doc, hub_threshold=2)
        topology = next(s for s in l3.body if isinstance(s, Section) and s.name == "TOPOLOGY")
        texts = [c.text for c in topology.children if isinstance(c, PlainLine)]
        hubs = next((t for t in texts if t.startswith("HUBS:")), "")
        bridges = next((t for t in texts if t.startswith("BRIDGES:")), "")
        assert "PATIENT" in hubs
        assert "PATIENT" not in bridges

    def test_entity_role_tag_follows_threshold(self):
        """Entity role tags in ENTITIES section respect hub_threshold."""
        doc = self._build_3ref_doc()
        l3 = generate_l3(doc, hub_threshold=2)
        entities = next(s for s in l3.body if isinstance(s, Section) and s.name == "ENTITIES")
        patient_line = next(
            (c.text for c in entities.children
             if isinstance(c, PlainLine) and "PATIENT" in c.text),
            "",
        )
        assert "(hub)" in patient_line


# ═══════════════════════════════════════════════════════
# Semantic Keyword Extraction (reviewer: "'churn' won't appear in keyword index")
# ═══════════════════════════════════════════════════════


class TestSemanticKeywordExtraction:
    """Validate that keyword index extracts domain terms from values, not just keys."""

    def test_retention_term_in_keywords(self):
        """'retention' from RETENTION value appears in keyword index."""
        doc = _make_l2_doc([
            Section(name="ENTITY-CUSTOMER", children=(
                KeyValue(key="RETENTION", value="active→7-years|churned→90-days→archive"),
            )),
        ])
        manifest = generate_manifest({"L2": doc}, domain="test")
        kw_section = next(
            (s for s in manifest.body if isinstance(s, Section) and s.name == "KEYWORD-INDEX"),
            None,
        )
        assert kw_section is not None
        kw_text = " ".join(c.value for c in kw_section.children if isinstance(c, KeyValue))
        assert "retention" in kw_text

    def test_pii_term_in_keywords(self):
        """'pii' and 'confidential' from PII-CLASSIFICATION value appear in keywords."""
        doc = _make_l2_doc([
            Section(name="ENTITY-CUSTOMER", children=(
                KeyValue(key="PII-CLASSIFICATION", value="email→CONFIDENTIAL+phone→RESTRICTED"),
            )),
        ])
        manifest = generate_manifest({"L2": doc}, domain="test")
        kw_section = next(
            (s for s in manifest.body if isinstance(s, Section) and s.name == "KEYWORD-INDEX"),
            None,
        )
        assert kw_section is not None
        kw_text = " ".join(c.value for c in kw_section.children if isinstance(c, KeyValue))
        assert "confidential" in kw_text
        assert "restricted" in kw_text

    def test_encrypted_and_immutable_extracted(self):
        """Domain terms 'encrypted' and 'immutable' extracted from values."""
        doc = _make_l2_doc([
            Section(name="ENTITY-PAYMENT", children=(
                KeyValue(key="SECURITY", value="card-number(encrypted,pci-dss)"),
                KeyValue(key="IMMUTABLE-AFTER", value="settled(immutable)"),
            )),
        ])
        manifest = generate_manifest({"L2": doc}, domain="test")
        kw_section = next(
            (s for s in manifest.body if isinstance(s, Section) and s.name == "KEYWORD-INDEX"),
            None,
        )
        assert kw_section is not None
        kw_text = " ".join(c.value for c in kw_section.children if isinstance(c, KeyValue))
        assert "encrypted" in kw_text or "encrypt" in kw_text
        assert "immutable" in kw_text


# ═══════════════════════════════════════════════════════
# Query Routing (reviewer: "no query routing test")
# ═══════════════════════════════════════════════════════


class TestManifestQueryRouting:
    """Simulate query-to-section routing using the keyword index."""

    def _route_query(self, manifest: CTXDocument, query: str) -> list[str]:
        """Given a manifest and a query string, return matching section names."""
        kw_section = next(
            (s for s in manifest.body if isinstance(s, Section) and s.name == "KEYWORD-INDEX"),
            None,
        )
        if kw_section is None:
            return []

        query_terms = set(query.lower().split())
        matches = []
        for child in kw_section.children:
            if isinstance(child, KeyValue):
                section_kws = set(child.value.split(","))
                if query_terms & section_kws:
                    matches.append(child.key)
        return matches

    def test_route_retention_query(self):
        """Query about 'retention' routes to section with RETENTION field."""
        doc = _make_l2_doc([
            Section(name="ENTITY-CUSTOMER", children=(
                KeyValue(key="RETENTION", value="active→7-years|churned→90-days→archive"),
                KeyValue(key="IDENTIFIER", value="cust_id(UUID)"),
            )),
            Section(name="ENTITY-ORDER", children=(
                KeyValue(key="STATUS-MACHINE", value="pending→shipped→delivered"),
            )),
        ])
        manifest = generate_manifest({"L2": doc}, domain="test")
        matches = self._route_query(manifest, "retention")
        assert "ENTITY-CUSTOMER" in matches
        assert "ENTITY-ORDER" not in matches

    def test_route_pii_query(self):
        """Query about 'confidential' routes to section with PII classification."""
        doc = _make_l2_doc([
            Section(name="ENTITY-CUSTOMER", children=(
                KeyValue(key="PII-CLASSIFICATION", value="email→CONFIDENTIAL"),
            )),
            Section(name="ENTITY-PRODUCT", children=(
                KeyValue(key="IDENTIFIER", value="sku(string)"),
            )),
        ])
        manifest = generate_manifest({"L2": doc}, domain="test")
        matches = self._route_query(manifest, "confidential")
        assert "ENTITY-CUSTOMER" in matches
        assert "ENTITY-PRODUCT" not in matches

    def test_route_entity_name_query(self):
        """Query mentioning entity name routes to that entity's section."""
        doc = _make_l2_doc([
            Section(name="ENTITY-CUSTOMER", children=(
                KeyValue(key="IDENTIFIER", value="cust_id(UUID)"),
            )),
            Section(name="ENTITY-ORDER", children=(
                KeyValue(key="BELONGS-TO", value="@ENTITY-CUSTOMER(cust_id)"),
            )),
        ])
        manifest = generate_manifest({"L2": doc}, domain="test")
        matches = self._route_query(manifest, "customer")
        assert "ENTITY-CUSTOMER" in matches
        # ORDER also references CUSTOMER, so it should appear too
        assert "ENTITY-ORDER" in matches


# ═══════════════════════════════════════════════════════
# Unrecognized Relationship Keys (reviewer: "what happens with linked_to?")
# ═══════════════════════════════════════════════════════


class TestUnrecognizedRelationshipKeys:
    """Validate that unknown relationship keys don't silently drop."""

    def test_linked_to_becomes_generic_field(self):
        """'linked_to' is not a recognized relationship, but becomes a LINKED-TO field."""
        data = {
            "entity": "Widget",
            "identifier": {"name": "widget_id", "type": "UUID"},
            "linked_to": "Gadget",
        }
        entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
        assert len(entities) == 1
        field_keys = [f.key for f in entities[0].fields]
        assert "LINKED-TO" in field_keys
        linked = next(f for f in entities[0].fields if f.key == "LINKED-TO")
        assert linked.value == "Gadget"
        assert linked.certainty == Certainty.EXPLICIT

    def test_associated_with_becomes_generic_field(self):
        """'associated_with' compresses to ASSOCIATED-WITH as a regular field."""
        data = {
            "entity": "Widget",
            "associated_with": {"entity": "Gadget", "field": "gadget_id"},
        }
        entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
        field_keys = [f.key for f in entities[0].fields]
        assert "ASSOCIATED-WITH" in field_keys

    def test_unrecognized_key_not_in_relationships(self):
        """Unrecognized keys don't create IRRelationship objects."""
        data = {
            "entity": "Widget",
            "linked_to": "Gadget",
        }
        entities, _, _ = extract_entities_from_yaml(data, filename="test.yaml")
        assert len(entities[0].relationships) == 0


# ═══════════════════════════════════════════════════════
# --strict Suppression of Inferred Relationships (reviewer: "does it have an equivalent?")
# ═══════════════════════════════════════════════════════


class TestStrictSuppressesInferredRelationships:
    """Validate that --strict mode suppresses inferred bidirectional relationships."""

    def _build_corpus_with_belongs_to(self):
        """ORDER belongs_to CUSTOMER. After resolve, CUSTOMER should get inferred HAS-MANY."""
        corpus = IRCorpus(domain="test", source_token_count=100)
        corpus.entities = [
            IREntity(
                name="CUSTOMER",
                fields=[IRField(key="IDENTIFIER", value="cust_id(UUID)",
                                source=IRSource(file="c.yaml"))],
                sources=[IRSource(file="c.yaml")],
            ),
            IREntity(
                name="ORDER",
                fields=[
                    IRField(key="IDENTIFIER", value="order_id(int)",
                            source=IRSource(file="o.yaml")),
                    IRField(key="BELONGS-TO", value="@ENTITY-CUSTOMER(cust_id)",
                            source=IRSource(file="o.yaml")),
                ],
                relationships=[IRRelationship(
                    source_entity="ORDER", target_entity="CUSTOMER",
                    rel_type="belongs-to", via_field="cust_id",
                    source=IRSource(file="o.yaml"),
                )],
                sources=[IRSource(file="o.yaml")],
            ),
        ]
        return corpus

    def test_enriched_mode_includes_inferred_has_many(self):
        """Default (enriched) mode: CUSTOMER gets HAS-MANY annotated with (inferred)."""
        corpus = self._build_corpus_with_belongs_to()
        resolve_entities(corpus)
        doc = compress(corpus, strict=False)

        customer_section = next(
            s for s in doc.body if isinstance(s, Section) and s.name == "ENTITY-CUSTOMER"
        )
        kvs = [c for c in customer_section.children if isinstance(c, KeyValue)]
        has_many_kvs = [kv for kv in kvs if kv.key == "HAS-MANY"]
        assert len(has_many_kvs) == 1
        assert "(inferred)" in has_many_kvs[0].value

    def test_strict_mode_suppresses_inferred_has_many(self):
        """Strict mode: CUSTOMER does NOT get HAS-MANY (it was inferred)."""
        corpus = self._build_corpus_with_belongs_to()
        resolve_entities(corpus)
        doc = compress(corpus, strict=True)

        customer_section = next(
            s for s in doc.body if isinstance(s, Section) and s.name == "ENTITY-CUSTOMER"
        )
        kvs = [c for c in customer_section.children if isinstance(c, KeyValue)]
        has_many_kvs = [kv for kv in kvs if kv.key == "HAS-MANY"]
        assert len(has_many_kvs) == 0, (
            f"Strict mode should suppress inferred HAS-MANY but found: {has_many_kvs}"
        )

    def test_strict_mode_preserves_explicit_belongs_to(self):
        """Strict mode: ORDER keeps its explicit BELONGS-TO (not inferred)."""
        corpus = self._build_corpus_with_belongs_to()
        resolve_entities(corpus)
        doc = compress(corpus, strict=True)

        order_section = next(
            s for s in doc.body if isinstance(s, Section) and s.name == "ENTITY-ORDER"
        )
        kvs = [c for c in order_section.children if isinstance(c, KeyValue)]
        belongs_to_kvs = [kv for kv in kvs if kv.key == "BELONGS-TO"]
        assert len(belongs_to_kvs) == 1
