"""Tests for WS7: Hydration Fidelity Experiment."""

from __future__ import annotations

import os
import pytest

from ctxpack.benchmarks.hydration_eval import (
    HydrationEvalMetrics,
    HydrationEvalResult,
    _entity_to_section_name,
    run_hydration_eval,
)


def _golden_corpus_dir() -> str:
    d = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "ctxpack", "benchmarks", "ctxpack_eval", "corpus"
    ))
    if not os.path.isdir(d):
        pytest.skip("Golden set corpus not found")
    return d


class TestEntityMapping:
    def test_plain_entity_gets_prefix(self):
        assert _entity_to_section_name("COMPRESSOR") == "ENTITY-COMPRESSOR"

    def test_already_prefixed_entity_unchanged(self):
        assert _entity_to_section_name("ENTITY-CUSTOMER") == "ENTITY-CUSTOMER"

    def test_hyphenated_entity(self):
        assert _entity_to_section_name("IR-PIPELINE") == "ENTITY-IR-PIPELINE"


class TestHydrationEvalOffline:
    """Tests that work without API keys — section selection + token counting."""

    def test_eval_returns_results_for_all_questions(self):
        corpus = _golden_corpus_dir()
        metrics = run_hydration_eval(corpus, api_key="")
        assert metrics.total == 20  # 20 questions in golden set

    def test_hydrated_tokens_less_than_full_l2(self):
        corpus = _golden_corpus_dir()
        metrics = run_hydration_eval(corpus, api_key="")
        for r in metrics.results:
            if r.entities:  # Only meaningful when sections are specified
                assert r.tokens_hydrated <= r.tokens_full_l2, (
                    f"{r.question_id}: hydrated ({r.tokens_hydrated}) > full ({r.tokens_full_l2})"
                )

    def test_token_savings_positive_when_sections_specified(self):
        corpus = _golden_corpus_dir()
        metrics = run_hydration_eval(corpus, api_key="")
        for r in metrics.results:
            if r.entities:
                assert r.token_savings_pct >= 0, (
                    f"{r.question_id}: negative token savings"
                )

    def test_result_has_all_required_fields(self):
        corpus = _golden_corpus_dir()
        metrics = run_hydration_eval(corpus, api_key="")
        for r in metrics.results:
            assert r.question_id
            assert r.question
            assert r.tokens_full_l2 > 0
            assert isinstance(r.sections_hydrated, list)

    def test_no_fidelity_without_api_key(self):
        corpus = _golden_corpus_dir()
        metrics = run_hydration_eval(corpus, api_key="")
        assert metrics.fidelity_full_rule == 0.0
        assert metrics.fidelity_hydrated_rule == 0.0

    def test_metrics_to_dict_serializable(self):
        corpus = _golden_corpus_dir()
        metrics = run_hydration_eval(corpus, api_key="")
        d = metrics.to_dict()
        assert "total" in d
        assert "avg_token_savings_pct" in d
        assert "details" in d
        assert len(d["details"]) == 20
