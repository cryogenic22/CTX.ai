"""Deterministic, zero-dependency BM25 scoring over tokenized documents."""

from __future__ import annotations

from collections import Counter
import math
from collections.abc import Sequence


BM25_K1 = 1.5
BM25_B = 0.75


def score_bm25(query_tokens: Sequence[str], documents: Sequence[Sequence[str]]) -> list[float]:
    """Return one BM25 score per document, preserving input order.

    The caller owns tokenization. Sorting query terms makes floating-point
    accumulation deterministic across processes with hash randomization.
    """
    if not documents:
        return []

    lengths = [len(document) for document in documents]
    average_length = sum(lengths) / len(lengths)
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(set(document))

    terms = sorted(query_tokens)
    unique_terms = set(terms)
    document_count = len(documents)
    inverse_frequency = {
        term: math.log(1 + (document_count - document_frequency[term] + 0.5)
                       / (document_frequency[term] + 0.5))
        for term in unique_terms
    }

    scores: list[float] = []
    for document, length in zip(documents, lengths):
        if not document:
            scores.append(0.0)
            continue
        frequencies = Counter(document)
        length_norm = 1 - BM25_B + BM25_B * (length / average_length)
        score = sum(
            inverse_frequency[term] * frequency * (BM25_K1 + 1)
            / (frequency + BM25_K1 * length_norm)
            for term in terms
            if (frequency := frequencies[term])
        )
        scores.append(score)
    return scores
