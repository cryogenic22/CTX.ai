"""Integration tests for ctxpack self-eval (dogfood corpus)."""

import json
import os

import pytest

from ctxpack.benchmarks.eval_config import EvalConfig
from ctxpack.benchmarks.metrics.compression import count_tokens
from ctxpack.benchmarks.metrics.fidelity import load_questions
from ctxpack.benchmarks.baselines.raw_stuffing import prepare_raw_context
from ctxpack.benchmarks.baselines.naive_summary import prepare_naive_context
from ctxpack.benchmarks.runner import run_eval
from ctxpack.core.packer import pack
from ctxpack.core.serializer import serialize


CTXPACK_EVAL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ctxpack", "benchmarks", "ctxpack_eval",
)

CORPUS_DIR = os.path.join(CTXPACK_EVAL, "corpus")


class TestCorpusPacking:
    """Test that the ctxpack corpus packs without errors."""

    def test_pack_completes(self):
        result = pack(CORPUS_DIR)
        assert result.document is not None
        assert result.entity_count > 0
        assert result.source_file_count > 0

    def test_pack_entity_count(self):
        result = pack(CORPUS_DIR)
        # 8 entity YAML files → at least 8 entities
        assert result.entity_count >= 8

    def test_packed_output_contains_expected_entities(self):
        result = pack(CORPUS_DIR)
        ctx_text = serialize(result.document)
        expected_entities = [
            "IR-PIPELINE", "PARSER", "SERIALIZER", "COMPRESSOR",
            "PACKER-PIPELINE", "CONFLICT-DETECTOR", "L3-GENERATOR", "MANIFEST",
        ]
        for entity in expected_entities:
            assert f"ENTITY-{entity}" in ctx_text, f"Missing entity section: {entity}"

    def test_packed_output_has_compression(self):
        result = pack(CORPUS_DIR)
        ctx_text = serialize(result.document)
        ctx_tokens = count_tokens(ctx_text)
        assert ctx_tokens > 0
        assert result.source_token_count > ctx_tokens, "Expected compression (fewer ctx tokens than source)"

    def test_pack_serializes_without_error(self):
        result = pack(CORPUS_DIR)
        ctx_text = serialize(result.document)
        assert ctx_text.startswith("§CTX")
        assert "DOMAIN:" in ctx_text

    def test_pack_with_l3(self):
        result = pack(CORPUS_DIR, layers=["L2", "L3"])
        assert result.l3_document is not None
        assert result.manifest_document is not None
        l3_text = serialize(result.l3_document)
        assert "ENTITIES" in l3_text
        assert "TOPOLOGY" in l3_text


class TestQuestionsFile:
    """Test that questions.yaml loads and validates."""

    def test_load_questions(self):
        questions_path = os.path.join(CTXPACK_EVAL, "questions.yaml")
        questions = load_questions(questions_path)
        assert len(questions) == 20

    def test_question_schema(self):
        questions_path = os.path.join(CTXPACK_EVAL, "questions.yaml")
        questions = load_questions(questions_path)
        for q in questions:
            assert "id" in q, f"Missing 'id' in question: {q}"
            assert "question" in q, f"Missing 'question' in: {q['id']}"
            assert "expected" in q, f"Missing 'expected' in: {q['id']}"
            assert "difficulty" in q, f"Missing 'difficulty' in: {q['id']}"
            assert "entities" in q, f"Missing 'entities' in: {q['id']}"

    def test_adversarial_questions(self):
        questions_path = os.path.join(CTXPACK_EVAL, "questions.yaml")
        questions = load_questions(questions_path)
        adversarial = [q for q in questions if q.get("adversarial")]
        assert len(adversarial) == 3
        for q in adversarial:
            assert q["expected"] == "NOT_IN_CONTEXT"

    def test_difficulty_distribution(self):
        questions_path = os.path.join(CTXPACK_EVAL, "questions.yaml")
        questions = load_questions(questions_path)
        difficulties = {q["difficulty"] for q in questions}
        assert "easy" in difficulties
        assert "medium" in difficulties
        assert "hard" in difficulties

    def test_question_ids_unique(self):
        questions_path = os.path.join(CTXPACK_EVAL, "questions.yaml")
        questions = load_questions(questions_path)
        ids = [q["id"] for q in questions]
        assert len(ids) == len(set(ids)), "Duplicate question IDs found"


class TestBaselines:
    """Test that baselines work with the ctxpack corpus."""

    def test_raw_stuffing(self):
        raw = prepare_raw_context(CORPUS_DIR)
        assert len(raw) > 0
        assert "IR-PIPELINE" in raw or "ir-pipeline" in raw.lower()

    def test_naive_truncation(self):
        result = pack(CORPUS_DIR)
        ctx_text = serialize(result.document)
        ctx_tokens = count_tokens(ctx_text)
        raw = prepare_raw_context(CORPUS_DIR)
        naive = prepare_naive_context(raw, ctx_tokens)
        naive_tokens = count_tokens(naive)
        assert naive_tokens == ctx_tokens


class TestEvalRunner:
    """Test eval runner with ctxpack corpus (no API key required)."""

    def test_run_eval_no_fidelity(self):
        result = pack(CORPUS_DIR)
        ctx_text = serialize(result.document)

        config = EvalConfig(
            golden_set_path=CTXPACK_EVAL,
            run_fidelity=False,
            run_latency=False,
            run_conflicts=True,
        )

        results = run_eval(config, ctx_text=ctx_text, version="0.3.0-dogfood")
        assert "version" in results
        assert results["version"] == "0.3.0-dogfood"
        assert "baselines" in results
        assert "ctxpack_l2" in results["baselines"]
        assert results["baselines"]["ctxpack_l2"]["tokens"] > 0

    def test_results_json_serializable(self):
        result = pack(CORPUS_DIR)
        ctx_text = serialize(result.document)
        config = EvalConfig(
            golden_set_path=CTXPACK_EVAL,
            run_fidelity=False,
        )
        results = run_eval(config, ctx_text=ctx_text)
        json_str = json.dumps(results, indent=2)
        assert len(json_str) > 0
