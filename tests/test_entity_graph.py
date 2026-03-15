"""Tests for T8: Entity Relationship Graph — Multi-Hop Traversal.

The entity graph enables multi-hop needle-finding: instead of the LLM
guessing which entities are related, the graph traverses relationships
extracted during packing. This addresses the "5 needles in a haystack"
problem for cross-entity questions.

Tests are written BEFORE implementation (TDD).
"""

from __future__ import annotations

import os
import pytest

from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    Section,
)


def _enterprise_corpus_dir() -> str:
    d = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "ctxpack", "benchmarks", "scaling", "enterprise_corpus"
    ))
    if not os.path.isdir(d):
        pytest.skip("Enterprise corpus not found")
    return d


def _make_graph_doc() -> CTXDocument:
    """Doc with clear relationship chain: Customer -> Order -> OrderLine -> Product."""
    return CTXDocument(
        header=Header(
            magic="§CTX", version="1.0", layer=Layer.L2,
            status_fields=(KeyValue(key="DOMAIN", value="test"),),
        ),
        body=(
            Section(name="ENTITY-CUSTOMER", children=(
                KeyValue(key="IDENTIFIER", value="customer_id(UUID)"),
                KeyValue(key="HAS-MANY", value="@ENTITY-ORDER(1:N,mandatory)"),
            )),
            Section(name="ENTITY-ORDER", children=(
                KeyValue(key="IDENTIFIER", value="order_id(UUID)"),
                KeyValue(key="BELONGS-TO", value="@ENTITY-CUSTOMER(mandatory)"),
                KeyValue(key="HAS-MANY", value="@ENTITY-ORDERLINE(1:N)"),
                KeyValue(key="HAS-MANY", value="@ENTITY-SHIPMENT(0:N)"),
            )),
            Section(name="ENTITY-ORDERLINE", children=(
                KeyValue(key="IDENTIFIER", value="line_id(UUID)"),
                KeyValue(key="BELONGS-TO", value="@ENTITY-ORDER(mandatory)"),
                KeyValue(key="REFERENCES", value="@ENTITY-PRODUCT(1:1)"),
            )),
            Section(name="ENTITY-PRODUCT", children=(
                KeyValue(key="IDENTIFIER", value="sku(string)"),
                KeyValue(key="HAS-MANY", value="@ENTITY-INVENTORY(1:N)"),
            )),
            Section(name="ENTITY-SHIPMENT", children=(
                KeyValue(key="IDENTIFIER", value="shipment_id(UUID)"),
                KeyValue(key="BELONGS-TO", value="@ENTITY-ORDER(mandatory)"),
            )),
            Section(name="ENTITY-INVENTORY", children=(
                KeyValue(key="IDENTIFIER", value="sku+warehouse_id(composite)"),
                KeyValue(key="BELONGS-TO", value="@ENTITY-PRODUCT(mandatory)"),
                KeyValue(key="REFERENCES", value="@ENTITY-WAREHOUSE(1:1)"),
            )),
            Section(name="ENTITY-WAREHOUSE", children=(
                KeyValue(key="IDENTIFIER", value="warehouse_id(UUID)"),
            )),
            Section(name="OVERVIEW", children=(
                KeyValue(key="OVERVIEW", value="E-commerce data platform"),
            )),
        ),
    )


# ── Graph Construction ──


class TestGraphConstruction:
    def test_graph_builds_from_document(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        assert len(graph.entities) >= 7

    def test_graph_extracts_entity_nodes(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        assert "ENTITY-CUSTOMER" in graph.entities
        assert "ENTITY-ORDER" in graph.entities
        assert "ENTITY-PRODUCT" in graph.entities

    def test_graph_ignores_non_entity_sections(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        assert "OVERVIEW" not in graph.entities

    def test_graph_extracts_edges(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        neighbors = graph.neighbors("ENTITY-ORDER")
        assert "ENTITY-CUSTOMER" in neighbors
        assert "ENTITY-ORDERLINE" in neighbors
        assert "ENTITY-SHIPMENT" in neighbors

    def test_graph_edges_are_bidirectional(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        # ORDER -> CUSTOMER and CUSTOMER -> ORDER
        assert "ENTITY-CUSTOMER" in graph.neighbors("ENTITY-ORDER")
        assert "ENTITY-ORDER" in graph.neighbors("ENTITY-CUSTOMER")


# ── Traversal ──


class TestTraversal:
    def test_neighbors_depth_1(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        n = graph.traverse("ENTITY-ORDER", depth=1)
        assert "ENTITY-CUSTOMER" in n
        assert "ENTITY-ORDERLINE" in n
        assert "ENTITY-SHIPMENT" in n
        # Product is 2 hops away (Order -> OrderLine -> Product)
        assert "ENTITY-PRODUCT" not in n

    def test_traverse_depth_2(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        n = graph.traverse("ENTITY-ORDER", depth=2)
        # Depth 2: Order -> OrderLine -> Product, Order -> Shipment
        assert "ENTITY-PRODUCT" in n
        assert "ENTITY-ORDERLINE" in n

    def test_traverse_depth_3_reaches_inventory(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        n = graph.traverse("ENTITY-CUSTOMER", depth=3)
        # Customer -> Order -> OrderLine -> Product
        assert "ENTITY-PRODUCT" in n

    def test_traverse_excludes_start_node(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        n = graph.traverse("ENTITY-ORDER", depth=2)
        assert "ENTITY-ORDER" not in n

    def test_traverse_unknown_entity_returns_empty(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        n = graph.traverse("ENTITY-NONEXISTENT", depth=3)
        assert n == set()

    def test_traverse_handles_cycles(self):
        """Order -> Customer and Customer -> Order should not cause infinite loop."""
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        # Should complete without hanging
        n = graph.traverse("ENTITY-CUSTOMER", depth=10)
        assert isinstance(n, set)
        assert len(n) <= len(graph.entities)


# ── Path Finding ──


class TestPathFinding:
    def test_path_direct_neighbor(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        path = graph.path("ENTITY-CUSTOMER", "ENTITY-ORDER")
        assert path == ["ENTITY-CUSTOMER", "ENTITY-ORDER"]

    def test_path_two_hops(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        path = graph.path("ENTITY-CUSTOMER", "ENTITY-ORDERLINE")
        assert len(path) == 3
        assert path[0] == "ENTITY-CUSTOMER"
        assert path[-1] == "ENTITY-ORDERLINE"

    def test_path_multi_hop(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        path = graph.path("ENTITY-CUSTOMER", "ENTITY-PRODUCT")
        assert len(path) >= 3
        assert path[0] == "ENTITY-CUSTOMER"
        assert path[-1] == "ENTITY-PRODUCT"

    def test_path_unconnected_returns_empty(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        path = graph.path("ENTITY-CUSTOMER", "ENTITY-NONEXISTENT")
        assert path == []

    def test_path_same_entity_returns_single(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)
        path = graph.path("ENTITY-CUSTOMER", "ENTITY-CUSTOMER")
        assert path == ["ENTITY-CUSTOMER"]


# ── Hydration Integration ──


class TestGraphHydration:
    def test_hydrate_include_related_expands(self):
        from ctxpack.core.entity_graph import EntityGraph
        from ctxpack.core.hydrator import hydrate_by_name

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)

        # Get related entities
        related = graph.traverse("ENTITY-ORDER", depth=1)
        all_sections = ["ENTITY-ORDER"] + list(related)

        # Hydrate all of them
        result = hydrate_by_name(doc, all_sections)
        section_names = {s.name for s in result.sections}
        assert "ENTITY-ORDER" in section_names
        assert "ENTITY-CUSTOMER" in section_names
        assert "ENTITY-ORDERLINE" in section_names

    def test_hydrate_include_related_respects_depth(self):
        from ctxpack.core.entity_graph import EntityGraph

        doc = _make_graph_doc()
        graph = EntityGraph.from_document(doc)

        depth1 = graph.traverse("ENTITY-CUSTOMER", depth=1)
        depth2 = graph.traverse("ENTITY-CUSTOMER", depth=2)
        assert len(depth2) >= len(depth1)


# ── Enterprise Corpus ──


class TestEnterpriseCorpusGraph:
    def test_enterprise_graph_has_entities(self):
        from ctxpack.core.entity_graph import EntityGraph
        from ctxpack.core.packer import pack

        corpus = _enterprise_corpus_dir()
        result = pack(corpus)
        graph = EntityGraph.from_document(result.document)
        assert len(graph.entities) >= 20  # 37 entities in corpus

    def test_enterprise_customer_has_relationships(self):
        from ctxpack.core.entity_graph import EntityGraph
        from ctxpack.core.packer import pack

        corpus = _enterprise_corpus_dir()
        result = pack(corpus)
        graph = EntityGraph.from_document(result.document)
        neighbors = graph.neighbors("ENTITY-CUSTOMER")
        # Customer should have at least Order, CustomerAddress
        assert len(neighbors) >= 1

    def test_enterprise_traverse_merchant_depth_2(self):
        """The LinkedIn commenter's exact scenario: merchant suspension cascading."""
        from ctxpack.core.entity_graph import EntityGraph
        from ctxpack.core.packer import pack

        corpus = _enterprise_corpus_dir()
        result = pack(corpus)
        graph = EntityGraph.from_document(result.document)

        related = graph.traverse("ENTITY-MERCHANT", depth=2)
        # Merchant should connect to MerchantStore, Product, Settlement, etc.
        assert len(related) >= 2
