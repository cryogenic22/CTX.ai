"""Phase 1 of the Four-Layer Context Architecture upgrade.

Tests for the foundational typing changes:
- ContextLayer enum
- IREntity / IRField extended with layer/confidence/expires_at/observation_count
- Provenance extended with the same metadata

All defaults must preserve current behavior so existing code keeps working.
"""

from __future__ import annotations

import time

import pytest

from ctxpack.core.layers import ContextLayer
from ctxpack.core.model import Provenance
from ctxpack.core.packer.ir import IRCorpus, IREntity, IRField, IRSource


# ── ContextLayer enum ───────────────────────────────────────────────────


class TestContextLayer:
    def test_four_layers_defined(self):
        assert ContextLayer.RULES.value == "rules"
        assert ContextLayer.INFERRED.value == "inferred"
        assert ContextLayer.ELICITED.value == "elicited"
        assert ContextLayer.AMBIENT.value == "ambient"

    def test_only_four_layers(self):
        assert len(ContextLayer) == 4

    def test_layer_from_string(self):
        assert ContextLayer("rules") is ContextLayer.RULES
        assert ContextLayer("inferred") is ContextLayer.INFERRED

    def test_unknown_layer_rejected(self):
        with pytest.raises(ValueError):
            ContextLayer("speculation")

    def test_layer_ordering_for_trust(self):
        # Higher-trust layers come first when sorted by name; useful for the
        # hydrator's "prefer rules over inferred" tie-breaking.
        order = [layer.value for layer in ContextLayer]
        assert order.index("rules") < order.index("inferred")
        assert order.index("inferred") < order.index("elicited")
        assert order.index("elicited") < order.index("ambient")


# ── IRField layer typing ────────────────────────────────────────────────


class TestIRFieldLayering:
    def test_default_layer_is_rules(self):
        f = IRField(key="status", value="active")
        assert f.layer is ContextLayer.RULES

    def test_default_confidence_is_one(self):
        f = IRField(key="status", value="active")
        assert f.confidence == 1.0

    def test_default_observation_count_is_zero(self):
        # observation_count is meaningful for INFERRED/AMBIENT, not RULES.
        f = IRField(key="status", value="active")
        assert f.observation_count == 0

    def test_default_expires_at_is_none(self):
        f = IRField(key="status", value="active")
        assert f.expires_at is None

    def test_explicit_inferred_field(self):
        f = IRField(
            key="latency_p99",
            value="220ms",
            layer=ContextLayer.INFERRED,
            confidence=0.78,
            observation_count=12,
        )
        assert f.layer is ContextLayer.INFERRED
        assert f.confidence == 0.78
        assert f.observation_count == 12

    def test_ambient_field_has_expiry(self):
        future = time.time() + 3600
        f = IRField(
            key="active_users",
            value="1234",
            layer=ContextLayer.AMBIENT,
            expires_at=future,
        )
        assert f.layer is ContextLayer.AMBIENT
        assert f.expires_at == pytest.approx(future)


# ── IREntity layer typing ───────────────────────────────────────────────


class TestIREntityLayering:
    def test_default_entity_is_rules_with_full_confidence(self):
        e = IREntity(name="CUSTOMER")
        assert e.layer is ContextLayer.RULES
        assert e.confidence == 1.0
        assert e.observation_count == 0
        assert e.expires_at is None

    def test_entity_can_be_inferred(self):
        e = IREntity(
            name="DRIFT_PATTERN_QUERY_LATENCY",
            layer=ContextLayer.INFERRED,
            confidence=0.62,
            observation_count=27,
        )
        assert e.layer is ContextLayer.INFERRED
        assert 0.0 <= e.confidence <= 1.0

    def test_entity_can_be_elicited(self):
        e = IREntity(
            name="TRIBAL_KNOWLEDGE_DEPLOY_WINDOW",
            layer=ContextLayer.ELICITED,
            confidence=0.95,
        )
        assert e.layer is ContextLayer.ELICITED

    def test_entity_can_be_ambient(self):
        e = IREntity(
            name="LIVE_FEATURE_FLAGS",
            layer=ContextLayer.AMBIENT,
            expires_at=time.time() + 60,
        )
        assert e.layer is ContextLayer.AMBIENT


# ── Backward compatibility ──────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_existing_irentity_signature_still_works(self):
        # Construction style used throughout the existing pipeline.
        e = IREntity(
            name="ORDER",
            aliases=["orders"],
            fields=[IRField(key="status", value="pending")],
            salience=0.9,
        )
        assert e.name == "ORDER"
        assert e.aliases == ["orders"]
        assert e.salience == 0.9
        # New fields silently default
        assert e.layer is ContextLayer.RULES
        assert e.confidence == 1.0

    def test_existing_irfield_signature_still_works(self):
        src = IRSource(file="rules.md", line_start=10, line_end=12)
        f = IRField(
            key="amount",
            value="$max(100,2*avg)",
            raw_value={"min": 100},
            source=src,
            salience=1.0,
        )
        assert f.key == "amount"
        assert f.source is src
        assert f.layer is ContextLayer.RULES

    def test_ircorpus_unchanged(self):
        # Smoke test: IRCorpus did not gain layer field — layering lives on
        # entities/fields, not on the whole corpus.
        c = IRCorpus(domain="test", entities=[IREntity(name="X")])
        assert c.domain == "test"
        assert len(c.entities) == 1


# ── Provenance layer metadata ───────────────────────────────────────────


class TestProvenanceLayering:
    def test_existing_provenance_construction_still_works(self):
        p = Provenance(source="rules.md", path="/repo/rules.md", line_range="L10-L12")
        assert p.source == "rules.md"
        assert p.layer is ContextLayer.RULES
        assert p.confidence == 1.0
        assert p.observation_count == 0
        assert p.last_confirmed is None
        assert p.expires_at is None

    def test_inferred_provenance_records_observation(self):
        now = time.time()
        p = Provenance(
            source="telemetry.parquet",
            path="dream-pass-2026-04-29",
            layer=ContextLayer.INFERRED,
            confidence=0.71,
            observation_count=42,
            last_confirmed=now,
        )
        assert p.layer is ContextLayer.INFERRED
        assert p.confidence == 0.71
        assert p.observation_count == 42
        assert p.last_confirmed == pytest.approx(now)

    def test_provenance_is_still_frozen(self):
        p = Provenance(source="rules.md")
        with pytest.raises(Exception):
            # frozen=True dataclass should reject mutation
            p.source = "other.md"  # type: ignore[misc]

    def test_ambient_provenance_has_expiry(self):
        future = time.time() + 300
        p = Provenance(
            source="prod.api/healthz",
            layer=ContextLayer.AMBIENT,
            expires_at=future,
        )
        assert p.layer is ContextLayer.AMBIENT
        assert p.expires_at == pytest.approx(future)


# ── Confidence range invariants ─────────────────────────────────────────


class TestConfidenceRange:
    """Phase 1 stays permissive — Phase 3 will introduce a ConfidenceTracker
    that enforces the [0, 1] range at update time. We only sanity-check the
    type here so callers know what to expect.
    """

    def test_confidence_is_float(self):
        e = IREntity(name="X", confidence=0.5)
        assert isinstance(e.confidence, float)

    def test_confidence_field_accepts_zero(self):
        # A pruned-but-not-yet-deleted entity sits at 0.0 confidence.
        e = IREntity(name="X", confidence=0.0)
        assert e.confidence == 0.0
