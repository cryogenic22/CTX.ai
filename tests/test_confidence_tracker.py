"""Phase 3a — ConfidenceTracker.

Bayesian-style observation updates + Ebbinghaus decay + atomic JSON
persistence. Pure stdlib.

Math:
  confirmed:    c_new = c + (1-c) * 0.1
  contradicted: c_new = c * 0.5
  decay:        c_new = c * 0.95^days_since_last_observed
  prune:        drop entries where c < 0.2
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from ctxpack.core.confidence import ConfidenceRecord, ConfidenceTracker


# ── Construction & defaults ─────────────────────────────────────────────


class TestConstruction:
    def test_empty_tracker_is_empty(self):
        t = ConfidenceTracker()
        assert len(t) == 0
        assert list(t) == []

    def test_get_unknown_returns_zero(self):
        t = ConfidenceTracker()
        assert t.get_confidence("UNKNOWN") == 0.0

    def test_contains(self):
        t = ConfidenceTracker()
        assert "X" not in t
        t.observe("X", confirmed=True)
        assert "X" in t


# ── Observe: confirmed ──────────────────────────────────────────────────


class TestObserveConfirmed:
    def test_first_confirmed_lands_at_alpha(self):
        t = ConfidenceTracker()
        t.observe("X", confirmed=True, now=1000.0)
        assert t.get_confidence("X", now=1000.0) == pytest.approx(0.1)

    def test_two_confirmed_observations_ramp_up(self):
        t = ConfidenceTracker()
        t.observe("X", confirmed=True, now=1000.0)
        t.observe("X", confirmed=True, now=1000.0)
        # 0.1 + 0.9 * 0.1 = 0.19
        assert t.get_confidence("X", now=1000.0) == pytest.approx(0.19)

    def test_confirmed_never_overshoots_one(self):
        t = ConfidenceTracker()
        for _ in range(200):
            t.observe("X", confirmed=True, now=1000.0)
        assert t.get_confidence("X", now=1000.0) <= 1.0
        assert t.get_confidence("X", now=1000.0) > 0.99

    def test_observation_count_increments(self):
        t = ConfidenceTracker()
        t.observe("X", confirmed=True, now=1000.0)
        t.observe("X", confirmed=True, now=1000.0)
        t.observe("X", confirmed=True, now=1000.0)
        rec = t.records["X"]
        assert rec.observation_count == 3


# ── Observe: contradicted ───────────────────────────────────────────────


class TestObserveContradicted:
    def test_contradicted_halves_confidence(self):
        t = ConfidenceTracker()
        t.records["X"] = ConfidenceRecord(
            name="X", confidence=0.8, last_observed=1000.0
        )
        t.observe("X", confirmed=False, now=1000.0)
        assert t.get_confidence("X", now=1000.0) == pytest.approx(0.4)

    def test_contradicted_increments_contradiction_count(self):
        t = ConfidenceTracker()
        t.observe("X", confirmed=True, now=1000.0)
        t.observe("X", confirmed=False, now=1000.0)
        rec = t.records["X"]
        assert rec.contradiction_count == 1

    def test_contradicted_unknown_creates_at_zero(self):
        t = ConfidenceTracker()
        t.observe("Y", confirmed=False, now=1000.0)
        assert t.get_confidence("Y", now=1000.0) == 0.0
        assert "Y" in t


# ── Decay ───────────────────────────────────────────────────────────────


class TestDecay:
    def test_decay_zero_days_unchanged(self):
        t = ConfidenceTracker()
        t.records["X"] = ConfidenceRecord(
            name="X", confidence=0.8, last_observed=1000.0
        )
        assert t.get_confidence("X", now=1000.0) == pytest.approx(0.8)

    def test_decay_one_day_applies_factor(self):
        t = ConfidenceTracker()
        t.records["X"] = ConfidenceRecord(
            name="X", confidence=0.8, last_observed=0.0
        )
        # 1 day = 86400 seconds
        c = t.get_confidence("X", now=86400.0)
        assert c == pytest.approx(0.8 * 0.95)

    def test_decay_seven_days(self):
        t = ConfidenceTracker()
        t.records["X"] = ConfidenceRecord(
            name="X", confidence=1.0, last_observed=0.0
        )
        c = t.get_confidence("X", now=86400.0 * 7)
        assert c == pytest.approx(0.95**7)

    def test_decay_does_not_mutate_record(self):
        # get_confidence should return decayed value but not write back —
        # that lets callers query without committing the decay.
        t = ConfidenceTracker()
        t.records["X"] = ConfidenceRecord(
            name="X", confidence=0.8, last_observed=0.0
        )
        _ = t.get_confidence("X", now=86400.0 * 30)
        # Stored record still at 0.8
        assert t.records["X"].confidence == pytest.approx(0.8)

    def test_explicit_apply_decay_writes_through(self):
        t = ConfidenceTracker()
        t.records["X"] = ConfidenceRecord(
            name="X", confidence=0.8, last_observed=0.0
        )
        t.apply_decay(now=86400.0)
        assert t.records["X"].confidence == pytest.approx(0.8 * 0.95)
        assert t.records["X"].last_observed == 86400.0


# ── Pruning ─────────────────────────────────────────────────────────────


class TestPruning:
    def test_apply_decay_prunes_below_threshold(self):
        t = ConfidenceTracker()
        t.records["LOW"] = ConfidenceRecord(
            name="LOW", confidence=0.15, last_observed=0.0
        )
        t.records["HIGH"] = ConfidenceRecord(
            name="HIGH", confidence=0.8, last_observed=0.0
        )
        t.apply_decay(now=0.0)  # no decay, just prune
        assert "LOW" not in t
        assert "HIGH" in t

    def test_default_prune_threshold_is_two_tenths(self):
        t = ConfidenceTracker()
        assert t.prune_below == pytest.approx(0.2)

    def test_custom_prune_threshold(self):
        t = ConfidenceTracker(prune_below=0.5)
        t.records["MID"] = ConfidenceRecord(
            name="MID", confidence=0.4, last_observed=0.0
        )
        t.apply_decay(now=0.0)
        assert "MID" not in t


# ── Persistence ─────────────────────────────────────────────────────────


class TestPersistence:
    def test_save_load_round_trip(self, tmp_path: Path):
        path = tmp_path / "confidence.json"
        t = ConfidenceTracker()
        t.observe("A", confirmed=True, now=1000.0)
        t.observe("B", confirmed=True, now=1000.0)
        t.observe("B", confirmed=True, now=1000.0)
        t.save(path)

        t2 = ConfidenceTracker.load(path)
        assert t2.get_confidence("A", now=1000.0) == pytest.approx(
            t.get_confidence("A", now=1000.0)
        )
        assert t2.records["B"].observation_count == 2

    def test_load_missing_file_returns_empty(self, tmp_path: Path):
        path = tmp_path / "nonexistent.json"
        t = ConfidenceTracker.load(path)
        assert len(t) == 0

    def test_save_writes_atomically(self, tmp_path: Path):
        # The tmp path used during atomic write should not exist after save.
        path = tmp_path / "confidence.json"
        t = ConfidenceTracker()
        t.observe("X", confirmed=True, now=1000.0)
        t.save(path)
        assert path.exists()
        assert not (tmp_path / "confidence.json.tmp").exists()

    def test_save_creates_parent_dir(self, tmp_path: Path):
        path = tmp_path / "nested" / "dir" / "confidence.json"
        t = ConfidenceTracker()
        t.observe("X", confirmed=True, now=1000.0)
        t.save(path)
        assert path.exists()

    def test_save_format_is_human_readable_json(self, tmp_path: Path):
        path = tmp_path / "confidence.json"
        t = ConfidenceTracker()
        t.observe("X", confirmed=True, now=1000.0)
        t.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert "records" in data
        assert isinstance(data["records"], list)
        assert data["records"][0]["name"] == "X"


# ── Bulk operations ─────────────────────────────────────────────────────


class TestObserveMany:
    def test_observe_many_confirmed(self):
        t = ConfidenceTracker()
        t.observe_many(["A", "B", "C"], confirmed=True, now=1000.0)
        assert t.get_confidence("A", now=1000.0) == pytest.approx(0.1)
        assert t.get_confidence("B", now=1000.0) == pytest.approx(0.1)
        assert t.get_confidence("C", now=1000.0) == pytest.approx(0.1)


# ── Integration with IREntity ───────────────────────────────────────────


class TestEntityIntegration:
    def test_apply_to_entity_overrides_confidence(self):
        from ctxpack.core.layers import ContextLayer
        from ctxpack.core.packer.ir import IREntity

        t = ConfidenceTracker()
        t.observe("ENTITY-X", confirmed=True, now=1000.0)
        for _ in range(5):
            t.observe("ENTITY-X", confirmed=True, now=1000.0)

        e = IREntity(name="X", layer=ContextLayer.INFERRED, confidence=0.0)
        t.apply_to_entity(e, now=1000.0)
        assert e.confidence > 0.0
        assert e.observation_count == 6

    def test_apply_to_entity_skips_rules_layer(self):
        # RULES facts should not have their confidence touched by observation
        # — they're authoritative regardless of how often agents cite them.
        from ctxpack.core.layers import ContextLayer
        from ctxpack.core.packer.ir import IREntity

        t = ConfidenceTracker()
        t.observe("ENTITY-X", confirmed=True, now=1000.0)
        e = IREntity(name="X", layer=ContextLayer.RULES, confidence=1.0)
        t.apply_to_entity(e, now=1000.0)
        assert e.confidence == 1.0
