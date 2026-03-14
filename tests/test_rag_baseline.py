"""Tests for T2: RAG Baseline Comparison.

RAG baseline: chunk corpus into ~500-token chunks, embed with
text-embedding-3-small, retrieve top-5 chunks per question via
cosine similarity. This is CtxPack's actual competitor.

Tests are written BEFORE implementation (TDD).
"""

from __future__ import annotations

import os
import pytest


def _golden_corpus_dir() -> str:
    """Use the smaller golden set for offline tests (fast, no API needed)."""
    d = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "ctxpack", "benchmarks", "ctxpack_eval", "corpus"
    ))
    if not os.path.isdir(d):
        pytest.skip("Golden set corpus not found")
    return d


# ── Chunking ──


class TestChunker:
    def test_chunks_are_under_max_tokens(self):
        from ctxpack.benchmarks.baselines.rag_baseline import chunk_corpus

        corpus = _golden_corpus_dir()
        chunks = chunk_corpus(corpus, max_tokens=500)
        for chunk in chunks:
            words = len(chunk["text"].split())
            assert words <= 600, (  # Allow 20% overshoot for paragraph boundaries
                f"Chunk has {words} words, expected <=600"
            )

    def test_chunks_have_source_metadata(self):
        from ctxpack.benchmarks.baselines.rag_baseline import chunk_corpus

        corpus = _golden_corpus_dir()
        chunks = chunk_corpus(corpus, max_tokens=500)
        for chunk in chunks:
            assert "source" in chunk, "Each chunk must have source file info"
            assert "text" in chunk
            assert len(chunk["text"].strip()) > 0

    def test_chunks_cover_all_files(self):
        from ctxpack.benchmarks.baselines.rag_baseline import chunk_corpus

        corpus = _golden_corpus_dir()
        chunks = chunk_corpus(corpus, max_tokens=500)
        sources = {c["source"] for c in chunks}
        # Should have chunks from multiple files
        assert len(sources) >= 2

    def test_chunks_total_covers_corpus(self):
        from ctxpack.benchmarks.baselines.rag_baseline import chunk_corpus
        from ctxpack.benchmarks.baselines.raw_stuffing import prepare_raw_context

        corpus = _golden_corpus_dir()
        chunks = chunk_corpus(corpus, max_tokens=500)
        raw = prepare_raw_context(corpus)

        # Total chunk text should cover most of the corpus (some overlap OK)
        chunk_words = sum(len(c["text"].split()) for c in chunks)
        raw_words = len(raw.split())
        coverage = chunk_words / raw_words if raw_words > 0 else 0
        assert coverage >= 0.8, f"Chunks cover only {coverage:.0%} of corpus"

    def test_empty_corpus_returns_empty(self):
        from ctxpack.benchmarks.baselines.rag_baseline import chunk_corpus
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            chunks = chunk_corpus(d, max_tokens=500)
            assert chunks == []


# ── Retrieval (offline, no embeddings) ──


class TestRetrieverOffline:
    """Test retrieval logic using simple keyword matching (no API needed)."""

    def test_keyword_retrieve_returns_top_k(self):
        from ctxpack.benchmarks.baselines.rag_baseline import keyword_retrieve

        chunks = [
            {"text": "Customer identifier is customer_id UUID", "source": "a.yaml"},
            {"text": "Order status can be draft submitted shipped", "source": "b.yaml"},
            {"text": "Payment uses credit card or bank transfer", "source": "c.yaml"},
        ]
        results = keyword_retrieve(chunks, "customer identifier", top_k=2)
        assert len(results) <= 2
        # Customer chunk should rank highest
        assert "customer" in results[0]["text"].lower()

    def test_keyword_retrieve_empty_query(self):
        from ctxpack.benchmarks.baselines.rag_baseline import keyword_retrieve

        chunks = [{"text": "Some text", "source": "a.yaml"}]
        results = keyword_retrieve(chunks, "", top_k=5)
        assert results == []

    def test_keyword_retrieve_no_match(self):
        from ctxpack.benchmarks.baselines.rag_baseline import keyword_retrieve

        chunks = [{"text": "Customer data", "source": "a.yaml"}]
        results = keyword_retrieve(chunks, "zzznonexistent", top_k=5)
        assert results == []


# ── Context Assembly ──


class TestContextAssembly:
    def test_assemble_context_joins_chunks(self):
        from ctxpack.benchmarks.baselines.rag_baseline import assemble_context

        chunks = [
            {"text": "First chunk content", "source": "a.yaml"},
            {"text": "Second chunk content", "source": "b.yaml"},
        ]
        context = assemble_context(chunks)
        assert "First chunk content" in context
        assert "Second chunk content" in context

    def test_assemble_context_empty(self):
        from ctxpack.benchmarks.baselines.rag_baseline import assemble_context

        context = assemble_context([])
        assert context == "" or context.strip() == ""
