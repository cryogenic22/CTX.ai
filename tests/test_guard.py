"""Tests for Context Guard module (M3).

TDD tests — written before implementation.
Post-response guard that detects hallucination signals and unknown entities.
"""

from __future__ import annotations

import pytest

from ctxpack.modules.guard import ContextGuard, GuardResult


# ── Fixtures ──


def _make_guard(**kwargs) -> ContextGuard:
    return ContextGuard(**kwargs)


KNOWN_ENTITIES = {"ENTITY-CUSTOMER", "ENTITY-ORDER", "ENTITY-PRODUCT"}


# ── Signal detection ──


class TestGuardSignalDetection:
    def test_guard_detects_not_found_signal(self):
        guard = _make_guard()
        result = guard.check("The information was not found in the provided context.")
        assert result.low_confidence is True
        assert any("not found in" in s for s in result.signals_detected)

    def test_guard_detects_from_industry_experience(self):
        guard = _make_guard()
        result = guard.check("From industry experience, this is typically done via REST.")
        assert result.low_confidence is True
        assert any("from industry experience" in s for s in result.signals_detected)

    def test_guard_detects_based_on_my_training(self):
        guard = _make_guard()
        result = guard.check("Based on my training data, the answer is X.")
        assert result.low_confidence is True
        assert any("based on my training" in s for s in result.signals_detected)

    def test_guard_detects_generally_speaking(self):
        guard = _make_guard()
        result = guard.check("Generally speaking, APIs use JSON for data exchange.")
        assert result.low_confidence is True
        assert any("generally speaking" in s for s in result.signals_detected)

    def test_guard_detects_typically_in(self):
        guard = _make_guard()
        result = guard.check("Typically in microservices, each service owns its data.")
        assert result.low_confidence is True
        assert any("typically in" in s for s in result.signals_detected)


# ── Entity name detection ──


class TestGuardEntityDetection:
    def test_guard_detects_unknown_entity_names(self):
        guard = _make_guard(known_entity_names=KNOWN_ENTITIES)
        result = guard.check(
            "ENTITY-CUSTOMER has a relationship with ENTITY-INVOICE."
        )
        assert "ENTITY-INVOICE" in result.unknown_entities
        assert "ENTITY-CUSTOMER" not in result.unknown_entities

    def test_guard_passes_known_entity_names(self):
        guard = _make_guard(known_entity_names=KNOWN_ENTITIES)
        result = guard.check(
            "ENTITY-CUSTOMER places an ENTITY-ORDER for an ENTITY-PRODUCT."
        )
        assert result.unknown_entities == []

    def test_guard_detects_id_pattern_unknown(self):
        """XX-NN patterns not in known set should be flagged."""
        guard = _make_guard(known_entity_names=KNOWN_ENTITIES)
        result = guard.check(
            "The CL-42 client was migrated to MR-99 merchant."
        )
        assert "CL-42" in result.unknown_entities
        assert "MR-99" in result.unknown_entities

    def test_guard_detects_id_pattern_when_no_known_set(self):
        """Without known_entity_names, ID patterns are not flagged."""
        guard = _make_guard()
        result = guard.check("The CL-42 client was migrated.")
        # No known set => no unknown entity detection
        assert result.unknown_entities == []


# ── Clean response ──


class TestGuardCleanResponse:
    def test_guard_passes_clean_response(self):
        guard = _make_guard(known_entity_names=KNOWN_ENTITIES)
        result = guard.check(
            "ENTITY-CUSTOMER has fields: customer_id, name, email, phone."
        )
        assert result.low_confidence is False
        assert result.signals_detected == []
        assert result.unknown_entities == []
        assert result.recommendation == "ok"

    def test_guard_empty_response_flags_low_confidence(self):
        guard = _make_guard()
        result = guard.check("")
        assert result.low_confidence is True

    def test_guard_whitespace_only_response_flags_low_confidence(self):
        guard = _make_guard()
        result = guard.check("   \n  \t  ")
        assert result.low_confidence is True


# ── Recommendation logic ──


class TestGuardRecommendation:
    def test_guard_recommendation_ok_when_clean(self):
        guard = _make_guard(known_entity_names=KNOWN_ENTITIES)
        result = guard.check(
            "ENTITY-CUSTOMER has customer_id as primary key."
        )
        assert result.recommendation == "ok"

    def test_guard_recommendation_warn_on_signal(self):
        guard = _make_guard()
        result = guard.check(
            "Generally speaking, this pattern is common in data engineering."
        )
        assert result.recommendation == "warn"

    def test_guard_recommendation_retry_on_unknown_entities(self):
        guard = _make_guard(known_entity_names=KNOWN_ENTITIES)
        result = guard.check(
            "ENTITY-SHIPMENT tracks delivery status."
        )
        assert result.recommendation == "retry"

    def test_guard_recommendation_new_session_on_multiple_unknowns(self):
        guard = _make_guard(known_entity_names=KNOWN_ENTITIES)
        result = guard.check(
            "ENTITY-SHIPMENT depends on ENTITY-WAREHOUSE and ENTITY-CARRIER."
        )
        assert result.recommendation == "new_session"


# ── Custom signals ──


class TestGuardCustomSignals:
    def test_guard_custom_signals(self):
        guard = _make_guard(custom_signals=["in my opinion"])
        result = guard.check("In my opinion, this is the best approach.")
        assert result.low_confidence is True
        assert any("in my opinion" in s for s in result.signals_detected)

    def test_guard_custom_signals_extend_defaults(self):
        """Custom signals add to defaults, don't replace them."""
        guard = _make_guard(custom_signals=["in my opinion"])
        result = guard.check("This was not found in the provided context.")
        assert result.low_confidence is True
        assert any("not found in" in s for s in result.signals_detected)


# ── Correction message ──


class TestGuardCorrection:
    def test_guard_correction_message_lists_known_entities(self):
        guard = _make_guard(known_entity_names=KNOWN_ENTITIES)
        result = guard.check("ENTITY-SHIPMENT is a new entity.")
        correction = guard.build_correction(result)
        assert "ENTITY-CUSTOMER" in correction
        assert "ENTITY-ORDER" in correction
        assert "ENTITY-PRODUCT" in correction
        assert "ONLY" in correction

    def test_guard_correction_message_empty_when_ok(self):
        guard = _make_guard(known_entity_names=KNOWN_ENTITIES)
        result = GuardResult(
            low_confidence=False,
            signals_detected=[],
            unknown_entities=[],
            recommendation="ok",
        )
        correction = guard.build_correction(result)
        assert correction == ""

    def test_guard_correction_mentions_signals_when_detected(self):
        guard = _make_guard(known_entity_names=KNOWN_ENTITIES)
        result = guard.check("Generally speaking, this is how it works.")
        correction = guard.build_correction(result)
        # Should have some correction text when signals are detected
        assert len(correction) > 0


# ── on_low_confidence modes ──


class TestGuardModes:
    def test_guard_default_mode_is_warn(self):
        guard = _make_guard()
        assert guard._on_low_confidence == "warn"

    def test_guard_retry_mode(self):
        guard = _make_guard(on_low_confidence="retry")
        assert guard._on_low_confidence == "retry"

    def test_guard_inject_correction_mode(self):
        guard = _make_guard(on_low_confidence="inject-correction")
        assert guard._on_low_confidence == "inject-correction"
