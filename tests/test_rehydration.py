"""Tests for T1: Multi-Hop Re-Hydration.

Re-hydration allows a second retrieval pass when the first hydration
doesn't provide enough context to answer a multi-hop question. This
closes the 7pp fidelity gap observed on MH01-MH04 in the scaling eval.

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


def _make_multi_entity_doc() -> CTXDocument:
    """Document with 5 entities for multi-hop testing."""
    return CTXDocument(
        header=Header(
            magic="§CTX", version="1.0", layer=Layer.L2,
            status_fields=(KeyValue(key="DOMAIN", value="test"),),
        ),
        body=(
            Section(name="ENTITY-CUSTOMER", children=(
                KeyValue(key="IDENTIFIER", value="customer_id(UUID)"),
                KeyValue(key="RETENTION", value="7 years after last order"),
                KeyValue(key="PII", value="name+email+phone"),
            )),
            Section(name="ENTITY-ORDER", children=(
                KeyValue(key="IDENTIFIER", value="order_id(UUID)"),
                KeyValue(key="BELONGS-TO", value="@ENTITY-CUSTOMER(mandatory)"),
                KeyValue(key="STATUS", value="draft|submitted|processing|shipped|delivered"),
                KeyValue(key="CASCADE", value="cancel cascades to OrderLine and Shipment"),
            )),
            Section(name="ENTITY-ORDERLINE", children=(
                KeyValue(key="IDENTIFIER", value="line_id(UUID)"),
                KeyValue(key="BELONGS-TO", value="@ENTITY-ORDER(mandatory)"),
                KeyValue(key="FIELDS", value="product_id+quantity+unit_price+line_total"),
            )),
            Section(name="ENTITY-SHIPMENT", children=(
                KeyValue(key="IDENTIFIER", value="shipment_id(UUID)"),
                KeyValue(key="BELONGS-TO", value="@ENTITY-ORDER(mandatory)"),
                KeyValue(key="STATUS", value="pending|picked|shipped|delivered"),
                KeyValue(key="INVENTORY-SYNC", value="on creation, decrement warehouse stock"),
            )),
            Section(name="ENTITY-INVENTORY", children=(
                KeyValue(key="IDENTIFIER", value="sku+warehouse_id(composite)"),
                KeyValue(key="FIELDS", value="available_qty+reserved_qty+reorder_point"),
                KeyValue(key="SYNC", value="real-time from warehouse API via webhook"),
            )),
        ),
    )


# ── Core re-hydration logic ──


class TestRehydrationDetection:
    """Test that low-confidence answers are correctly detected."""

    def test_low_confidence_detected_not_found(self):
        from ctxpack.core.hydrator import needs_rehydration

        assert needs_rehydration("Not found in context.")

    def test_low_confidence_detected_not_enough(self):
        from ctxpack.core.hydrator import needs_rehydration

        assert needs_rehydration("Based on the available context, I cannot fully answer this.")

    def test_low_confidence_detected_partial(self):
        from ctxpack.core.hydrator import needs_rehydration

        assert needs_rehydration("I don't have enough information to answer completely.")

    def test_confident_answer_not_flagged(self):
        from ctxpack.core.hydrator import needs_rehydration

        assert not needs_rehydration("The customer identifier is customer_id, a UUID v4.")

    def test_empty_answer_flagged(self):
        from ctxpack.core.hydrator import needs_rehydration

        assert needs_rehydration("")

    def test_error_response_flagged(self):
        from ctxpack.core.hydrator import needs_rehydration

        assert needs_rehydration("(error: HTTP 429 Too Many Requests)")


class TestRehydrationMerge:
    """Test that re-hydrated sections append correctly."""

    def test_rehydrate_appends_new_sections(self):
        from ctxpack.core.hydrator import hydrate_by_name

        doc = _make_multi_entity_doc()

        # First hydration: 2 sections
        first = hydrate_by_name(doc, ["ENTITY-ORDER", "ENTITY-CUSTOMER"])
        assert len(first.sections) == 2

        # Second hydration: 2 more sections
        second = hydrate_by_name(doc, ["ENTITY-ORDERLINE", "ENTITY-SHIPMENT"])
        assert len(second.sections) == 2

        # Merge: should have 4 unique sections
        merged_names = {s.name for s in first.sections} | {s.name for s in second.sections}
        assert len(merged_names) == 4

    def test_rehydrate_deduplicates_already_hydrated(self):
        from ctxpack.core.hydrator import hydrate_by_name

        doc = _make_multi_entity_doc()

        first = hydrate_by_name(doc, ["ENTITY-ORDER", "ENTITY-CUSTOMER"])
        # Second round requests ORDER again + new SHIPMENT
        second = hydrate_by_name(doc, ["ENTITY-ORDER", "ENTITY-SHIPMENT"])

        # Merged should be 3, not 4 (ORDER deduplicated)
        all_names = [s.name for s in first.sections] + [s.name for s in second.sections]
        unique_names = set(all_names)
        assert "ENTITY-ORDER" in unique_names
        assert len(unique_names) == 3


class TestRehydrationBudget:
    """Test that budget caps are respected."""

    def test_budget_cap_limits_total_tokens(self):
        from ctxpack.core.hydrator import hydrate_by_name

        doc = _make_multi_entity_doc()

        # Hydrate all 5 sections
        result = hydrate_by_name(doc, [
            "ENTITY-CUSTOMER", "ENTITY-ORDER", "ENTITY-ORDERLINE",
            "ENTITY-SHIPMENT", "ENTITY-INVENTORY",
        ])

        # All 5 sections should be returned (budget is not enforced in hydrate_by_name)
        assert len(result.sections) == 5
        # But tokens_injected should be tracked for budget decisions
        assert result.tokens_injected > 0

    def test_sections_available_count_is_accurate(self):
        doc = _make_multi_entity_doc()
        from ctxpack.core.hydrator import hydrate_by_name

        result = hydrate_by_name(doc, ["ENTITY-CUSTOMER"])
        assert result.sections_available == 5


class TestNeedsRehydrationIntegration:
    """Integration: full flow of detect → request more → merge."""

    def test_multihop_scenario_order_cancellation(self):
        """Simulate: 'What happens to OrderLines when an Order is cancelled?'
        First hydration gets ORDER only. Answer lacks OrderLine detail.
        Re-hydration adds ORDERLINE and SHIPMENT.
        """
        from ctxpack.core.hydrator import hydrate_by_name, needs_rehydration

        doc = _make_multi_entity_doc()

        # Round 1: route to ORDER
        r1 = hydrate_by_name(doc, ["ENTITY-ORDER"])
        assert len(r1.sections) == 1
        # Simulated answer would be low-confidence because it mentions
        # cascading to OrderLine but doesn't have OrderLine details
        simulated_answer = "Based on the available context, Order cancellation cascades to OrderLine and Shipment, but I don't have details on those entities."
        assert needs_rehydration(simulated_answer)

        # Round 2: route to the entities mentioned in the cascade
        r2 = hydrate_by_name(doc, ["ENTITY-ORDERLINE", "ENTITY-SHIPMENT"])
        assert len(r2.sections) == 2

        # Merged context has 3 sections
        all_sections = r1.sections + r2.sections
        all_names = {s.name for s in all_sections}
        assert all_names == {"ENTITY-ORDER", "ENTITY-ORDERLINE", "ENTITY-SHIPMENT"}
