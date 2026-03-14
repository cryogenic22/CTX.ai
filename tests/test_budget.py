"""Tests for WS1: Variable Bitrate — BudgetAllocator.

Written BEFORE implementation (TDD). These tests define the contract.
"""

from __future__ import annotations

import pytest

from ctxpack.core.packer.ir import (
    Certainty,
    IRCorpus,
    IREntity,
    IRField,
    IRSource,
    IRWarning,
)


# ── Helpers ──


def _make_field(key: str, value: str, salience: float = 1.0) -> IRField:
    return IRField(key=key, value=value, salience=salience)


def _make_entity(name: str, fields: list[IRField], salience: float = 1.0) -> IREntity:
    e = IREntity(name=name, fields=fields)
    e.salience = salience
    return e


def _make_corpus(*entities: IREntity, source_tokens: int = 1000) -> IRCorpus:
    corpus = IRCorpus(domain="test", entities=list(entities))
    corpus.source_token_count = source_tokens
    return corpus


# ── Preset Registry ──


class TestPresets:
    def test_preset_registry_has_three_presets(self):
        from ctxpack.core.packer.budget import PRESETS

        assert "conservative" in PRESETS
        assert "balanced" in PRESETS
        assert "aggressive" in PRESETS

    def test_conservative_preset_values(self):
        from ctxpack.core.packer.budget import PRESETS

        p = PRESETS["conservative"]
        assert p.name == "conservative"
        assert p.drop_below_salience == 0.0  # drop nothing
        assert p.abbreviate_values is False

    def test_balanced_preset_values(self):
        from ctxpack.core.packer.budget import PRESETS

        p = PRESETS["balanced"]
        assert p.name == "balanced"
        assert p.drop_below_salience > 0.0  # drops some
        assert p.abbreviate_values is False

    def test_aggressive_preset_values(self):
        from ctxpack.core.packer.budget import PRESETS

        p = PRESETS["aggressive"]
        assert p.name == "aggressive"
        assert p.drop_below_salience > PRESETS["balanced"].drop_below_salience
        assert p.abbreviate_values is True

    def test_unknown_preset_raises_value_error(self):
        from ctxpack.core.packer.budget import allocate

        corpus = _make_corpus()
        with pytest.raises(ValueError, match="Unknown preset"):
            allocate(corpus, preset="nonexistent")


# ── Budget Allocation ──


class TestAllocate:
    def test_allocate_returns_entity_budgets_for_all_entities(self):
        from ctxpack.core.packer.budget import allocate

        e1 = _make_entity("A", [_make_field("F1", "v1")], salience=2.0)
        e2 = _make_entity("B", [_make_field("F2", "v2")], salience=1.0)
        corpus = _make_corpus(e1, e2)

        budgets = allocate(corpus, preset="balanced")
        assert len(budgets) == 2

    def test_higher_salience_entity_gets_more_budget(self):
        from ctxpack.core.packer.budget import allocate

        e_high = _make_entity("HIGH", [_make_field(f"F{i}", f"v{i}") for i in range(5)], salience=10.0)
        e_low = _make_entity("LOW", [_make_field(f"F{i}", f"v{i}") for i in range(5)], salience=1.0)
        corpus = _make_corpus(e_high, e_low)

        budgets = allocate(corpus, preset="balanced")
        budget_map = {b.entity.name: b for b in budgets}
        assert budget_map["HIGH"].token_budget >= budget_map["LOW"].token_budget

    def test_must_preserve_fields_always_included(self):
        from ctxpack.core.packer.budget import allocate

        e = _make_entity("E", [
            _make_field("IDENTIFIER", "uuid", salience=0.1),
            _make_field("NOTES", "some long notes here", salience=0.1),
        ], salience=1.0)
        corpus = _make_corpus(e)

        budgets = allocate(corpus, preset="aggressive",
                           must_preserve={"IDENTIFIER"})
        decisions = {fd.field.key: fd for fd in budgets[0].field_decisions}
        assert decisions["IDENTIFIER"].action == "include"

    def test_must_preserve_overrides_low_salience(self):
        from ctxpack.core.packer.budget import allocate

        e = _make_entity("E", [
            _make_field("CRITICAL", "true", salience=0.01),  # Very low salience
        ], salience=1.0)
        corpus = _make_corpus(e)

        budgets = allocate(corpus, preset="aggressive",
                           must_preserve={"CRITICAL"})
        decisions = {fd.field.key: fd for fd in budgets[0].field_decisions}
        assert decisions["CRITICAL"].action == "include"

    def test_boolean_fields_never_dropped(self):
        """Red team RT-2: boolean flags must survive aggressive compression."""
        from ctxpack.core.packer.budget import allocate

        e = _make_entity("API-ENDPOINT", [
            _make_field("DEPRECATED", "true", salience=0.2),
            _make_field("ACTIVE", "false", salience=0.2),
            _make_field("DESCRIPTION", "a-very-long-description-of-this-endpoint", salience=0.5),
        ], salience=1.0)
        corpus = _make_corpus(e)

        budgets = allocate(corpus, preset="aggressive")
        decisions = {fd.field.key: fd for fd in budgets[0].field_decisions}
        assert decisions["DEPRECATED"].action == "include"
        assert decisions["ACTIVE"].action == "include"

    def test_identifier_fields_never_dropped(self):
        from ctxpack.core.packer.budget import allocate

        e = _make_entity("E", [
            _make_field("IDENTIFIER", "customer_id(UUID)", salience=0.1),
            _make_field("NOTES", "optional-notes", salience=5.0),
        ], salience=1.0)
        corpus = _make_corpus(e)

        budgets = allocate(corpus, preset="aggressive")
        decisions = {fd.field.key: fd for fd in budgets[0].field_decisions}
        assert decisions["IDENTIFIER"].action == "include"

    def test_aggressive_preset_drops_low_salience_fields(self):
        from ctxpack.core.packer.budget import allocate

        e = _make_entity("E", [
            _make_field("IMPORTANT", "critical-value", salience=5.0),
            _make_field("TRIVIAL", "not-important-at-all", salience=0.1),
        ], salience=1.0)
        corpus = _make_corpus(e)

        budgets = allocate(corpus, preset="aggressive")
        decisions = {fd.field.key: fd for fd in budgets[0].field_decisions}
        assert decisions["IMPORTANT"].action == "include"
        assert decisions["TRIVIAL"].action in ("drop", "abbreviate")

    def test_conservative_preset_keeps_all_fields(self):
        from ctxpack.core.packer.budget import allocate

        e = _make_entity("E", [
            _make_field("F1", "v1", salience=0.1),
            _make_field("F2", "v2", salience=0.1),
            _make_field("F3", "v3", salience=0.1),
        ], salience=1.0)
        corpus = _make_corpus(e)

        budgets = allocate(corpus, preset="conservative")
        for fd in budgets[0].field_decisions:
            assert fd.action == "include"

    def test_empty_corpus_returns_empty_list(self):
        from ctxpack.core.packer.budget import allocate

        corpus = _make_corpus()
        budgets = allocate(corpus, preset="balanced")
        assert budgets == []

    def test_single_entity_gets_full_budget(self):
        from ctxpack.core.packer.budget import allocate

        e = _make_entity("ONLY", [_make_field("F1", "v1")], salience=1.0)
        corpus = _make_corpus(e)

        budgets = allocate(corpus, preset="balanced")
        assert len(budgets) == 1
        assert budgets[0].token_budget > 0


# ── Field Decisions ──


class TestFieldDecisions:
    def test_field_budget_has_action_and_reason(self):
        from ctxpack.core.packer.budget import allocate

        e = _make_entity("E", [_make_field("F1", "v1")], salience=1.0)
        corpus = _make_corpus(e)

        budgets = allocate(corpus, preset="balanced")
        fd = budgets[0].field_decisions[0]
        assert fd.action in ("include", "abbreviate", "drop")
        assert isinstance(fd.reason, str)
        assert len(fd.reason) > 0

    def test_drop_reason_includes_salience_score(self):
        from ctxpack.core.packer.budget import allocate

        e = _make_entity("E", [
            _make_field("HIGH", "v1", salience=10.0),
            _make_field("LOW", "v2", salience=0.01),
        ], salience=1.0)
        corpus = _make_corpus(e)

        budgets = allocate(corpus, preset="aggressive")
        dropped = [fd for fd in budgets[0].field_decisions if fd.action != "include"]
        if dropped:
            assert "salience" in dropped[0].reason.lower() or "0.01" in dropped[0].reason


# ── Compressor Integration ──


class TestCompressorIntegration:
    """Verify that the budget system integrates with the existing compressor."""

    def _pack_golden_set(self, preset: str):
        """Pack golden set at given preset and return token count."""
        import os
        from ctxpack.core.packer import pack
        from ctxpack.core.serializer import serialize

        corpus_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "ctxpack",
            "benchmarks",
            "ctxpack_eval",
            "corpus",
        )
        corpus_dir = os.path.normpath(corpus_dir)
        if not os.path.isdir(corpus_dir):
            pytest.skip("Golden set corpus not found")

        result = pack(corpus_dir, preset=preset)
        text = serialize(result.document)
        return len(text.split())

    def test_compress_preset_conservative_geq_balanced_geq_aggressive_tokens(self):
        """Monotonicity: more conservative = more tokens."""
        conservative = self._pack_golden_set("conservative")
        balanced = self._pack_golden_set("balanced")
        aggressive = self._pack_golden_set("aggressive")

        assert conservative >= balanced >= aggressive, (
            f"Token monotonicity violated: conservative={conservative}, "
            f"balanced={balanced}, aggressive={aggressive}"
        )

    def test_pack_with_preset_parameter_works(self):
        """pack() accepts preset parameter without error."""
        import os
        from ctxpack.core.packer import pack

        corpus_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "ctxpack",
            "benchmarks",
            "ctxpack_eval",
            "corpus",
        )
        corpus_dir = os.path.normpath(corpus_dir)
        if not os.path.isdir(corpus_dir):
            pytest.skip("Golden set corpus not found")

        result = pack(corpus_dir, preset="aggressive")
        assert result.document is not None
        assert result.entity_count > 0
