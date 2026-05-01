"""Phase 3c — ELICITED producer.

Captures expert tribal knowledge as IRField/IREntity at the ELICITED
trust layer. One expert lands at 0.7 (informed opinion); a second
expert confirming bumps to 0.95 (cross-checked). A challenge by a third
expert drops it back via the same ConfidenceTracker contradiction path.

JSON persistence at ``.ctx-cache/elicited.json``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ctxpack.core.layers import ContextLayer
from ctxpack.modules.elicit import ElicitedFact, ElicitStore


# ── Construction ────────────────────────────────────────────────────────


class TestConstruction:
    def test_empty_store(self):
        s = ElicitStore()
        assert len(s) == 0
        assert s.list() == []


# ── Add ─────────────────────────────────────────────────────────────────


class TestAdd:
    def test_first_expert_lands_at_seven_tenths(self):
        s = ElicitStore()
        s.add(
            name="ENTITY-DEPLOY",
            fact="Deploys fail on Tuesdays because the audit cron locks the build agent for 30 min at 09:00 UTC.",
            expert="alice",
            now=1000.0,
        )
        f = s.get("ENTITY-DEPLOY")
        assert f is not None
        assert f.confidence == pytest.approx(0.7)
        assert f.original_expert == "alice"
        assert f.confirming_expert is None

    def test_add_records_timestamp(self):
        s = ElicitStore()
        s.add(name="X", fact="text", expert="alice", now=1234.5)
        f = s.get("X")
        assert f.created_at == pytest.approx(1234.5)

    def test_re_add_by_same_expert_overwrites_fact(self):
        s = ElicitStore()
        s.add(name="X", fact="v1", expert="alice", now=1000.0)
        s.add(name="X", fact="v2", expert="alice", now=2000.0)
        f = s.get("X")
        assert f.fact == "v2"
        # Re-stating doesn't promote to confirmed
        assert f.confirming_expert is None
        assert f.confidence == pytest.approx(0.7)

    def test_re_add_by_different_expert_does_not_silently_promote(self):
        # A second expert calling .add() (not .confirm()) replaces the
        # original — explicit confirmation is required for the bump.
        s = ElicitStore()
        s.add(name="X", fact="v1", expert="alice", now=1000.0)
        with pytest.raises(ValueError):
            s.add(name="X", fact="v2", expert="bob", now=2000.0)


# ── Confirm ─────────────────────────────────────────────────────────────


class TestConfirm:
    def test_second_expert_bumps_to_high_confidence(self):
        s = ElicitStore()
        s.add(name="X", fact="text", expert="alice", now=1000.0)
        s.confirm(name="X", expert="bob", now=2000.0)
        f = s.get("X")
        assert f.confidence == pytest.approx(0.95)
        assert f.confirming_expert == "bob"

    def test_confirm_by_same_expert_is_rejected(self):
        s = ElicitStore()
        s.add(name="X", fact="text", expert="alice", now=1000.0)
        with pytest.raises(ValueError):
            s.confirm(name="X", expert="alice", now=2000.0)

    def test_confirm_unknown_name_raises(self):
        s = ElicitStore()
        with pytest.raises(KeyError):
            s.confirm(name="UNKNOWN", expert="bob", now=1000.0)

    def test_confirm_already_confirmed_is_idempotent(self):
        # A third expert confirming a fact that's already at 0.95 should
        # be a no-op (or slight bump), but never crash.
        s = ElicitStore()
        s.add(name="X", fact="text", expert="alice", now=1000.0)
        s.confirm(name="X", expert="bob", now=2000.0)
        s.confirm(name="X", expert="carol", now=3000.0)
        f = s.get("X")
        assert f.confidence >= 0.95


# ── Challenge (contradiction) ───────────────────────────────────────────


class TestChallenge:
    def test_challenge_drops_confidence(self):
        s = ElicitStore()
        s.add(name="X", fact="text", expert="alice", now=1000.0)
        s.confirm(name="X", expert="bob", now=2000.0)
        s.challenge(name="X", expert="carol", reason="seen otherwise", now=3000.0)
        f = s.get("X")
        assert f.confidence < 0.95

    def test_challenge_records_dissenter(self):
        s = ElicitStore()
        s.add(name="X", fact="text", expert="alice", now=1000.0)
        s.challenge(name="X", expert="bob", reason="wrong", now=2000.0)
        f = s.get("X")
        assert "bob" in f.dissenters


# ── to_entities ─────────────────────────────────────────────────────────


class TestToEntities:
    def test_emits_elicited_layer(self):
        s = ElicitStore()
        s.add(name="ENTITY-DEPLOY", fact="text", expert="alice", now=1000.0)
        entities = s.to_entities()
        assert len(entities) == 1
        e = entities[0]
        assert e.layer is ContextLayer.ELICITED
        assert e.name == "ENTITY-DEPLOY"
        assert e.confidence == pytest.approx(0.7)

    def test_entity_contains_fact_field(self):
        s = ElicitStore()
        s.add(name="X", fact="some tribal knowledge", expert="alice", now=1000.0)
        entity = s.to_entities()[0]
        keys = {f.key for f in entity.fields}
        assert "fact" in keys
        fact_field = next(f for f in entity.fields if f.key == "fact")
        assert fact_field.value == "some tribal knowledge"
        assert fact_field.layer is ContextLayer.ELICITED


# ── Persistence ─────────────────────────────────────────────────────────


class TestPersistence:
    def test_save_load_round_trip(self, tmp_path: Path):
        path = tmp_path / "elicited.json"
        s = ElicitStore()
        s.add(name="X", fact="text", expert="alice", now=1000.0)
        s.confirm(name="X", expert="bob", now=2000.0)
        s.save(path)

        s2 = ElicitStore.load(path)
        f = s2.get("X")
        assert f.fact == "text"
        assert f.original_expert == "alice"
        assert f.confirming_expert == "bob"
        assert f.confidence == pytest.approx(0.95)

    def test_load_missing_file_returns_empty(self, tmp_path: Path):
        s = ElicitStore.load(tmp_path / "no.json")
        assert len(s) == 0


# ── Gap queue integration ───────────────────────────────────────────────


class TestGapQueueGeneration:
    def test_pending_for_gap_emits_prompt(self):
        # Given a gap (a question_hash with N occurrences and no answer
        # in the catalog), build_elicitation_prompt should produce the
        # text to ask an expert.
        from ctxpack.modules.dream import GapItem
        from ctxpack.modules.elicit import build_elicitation_prompt

        gap = GapItem(
            question_hash="abc123",
            occurrences=7,
            first_seen="2026-04-01T00:00:00+00:00",
            last_seen="2026-04-29T00:00:00+00:00",
        )
        prompt = build_elicitation_prompt(gap)
        assert "7" in prompt  # mentions occurrence count
        assert "abc123" in prompt  # references the gap by hash
