"""CP-021/22/23 — per-turn task scoring + combined ranker.

The §6.2 two-score thesis: centrality_prior (persisted, baked into
the entity at pack time) + task_score (cheap, per-turn, computed
against the agent's working set), rank-normalised, then combined as

    final_score = α · norm(task_score) + (1 − α) · norm(centrality_prior)

with default α = 0.7 (task signal dominates when present) and α
falling back to 0.0 (pure centrality) when the working set is empty.

The §8.5 eval will sweep α ∈ {0, 0.3, 0.5, 0.7, 1.0} to falsify the
two-score architecture (if α=1 or α=0 wins, one of the scores is
decorative). For now we ship a working default.

BM25 implementation is zero-dep: pure-Python tokenisation and scoring
over the catalog-row text. Sub-millisecond on a few-thousand-symbol
catalog.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

from ctxpack.core.packer.ir import IREntity


# ── Tokenisation ───────────────────────────────────────────────────────


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _tokenise(text: str) -> list[str]:
    """Identifier-shape tokens, lowercase. Splits CamelCase and
    snake_case so a query like ``user_create`` matches
    ``createUser``.
    """
    raw = _TOKEN_RE.findall(text)
    out: list[str] = []
    for w in raw:
        out.append(w.lower())
        # CamelCase split
        sub = re.findall(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)|[a-z]+|\d+", w)
        for s in sub:
            sl = s.lower()
            if sl != w.lower():
                out.append(sl)
    return out


# ── BM25 (single-document scoring at query time) ───────────────────────


_BM25_K1 = 1.5
_BM25_B = 0.75


def compute_task_scores(
    entities: list[IREntity],
    context: str,
) -> dict[str, float]:
    """Score every entity against ``context`` using BM25.

    Document text per entity = qualified name + signature + docstring
    1st-line. Returns ``{entity.name: score}``; entities with zero
    overlap get 0.0.
    """
    if not context.strip():
        return {e.name: 0.0 for e in entities}

    query_tokens = _tokenise(context)
    if not query_tokens:
        return {e.name: 0.0 for e in entities}

    # Build per-entity document, deduped tokens-with-count.
    docs: list[tuple[str, list[str]]] = []
    for e in entities:
        fields = {f.key: f.value for f in e.fields}
        text = " ".join([
            e.name,
            fields.get("signature", ""),
            _first_line(fields.get("docstring", "")),
        ])
        docs.append((e.name, _tokenise(text)))

    if not docs:
        return {}

    avg_len = sum(len(d) for _, d in docs) / len(docs)
    # Document frequency
    df: Counter[str] = Counter()
    for _, toks in docs:
        for t in set(toks):
            df[t] += 1
    n_docs = len(docs)

    idf: dict[str, float] = {}
    for term in set(query_tokens):
        n_q = df.get(term, 0)
        # BM25 IDF (with 0.5 smoothing). Clamp to ≥0 so common terms
        # don't subtract.
        val = math.log((n_docs - n_q + 0.5) / (n_q + 0.5) + 1)
        idf[term] = max(0.0, val)

    out: dict[str, float] = {}
    for name, toks in docs:
        if not toks:
            out[name] = 0.0
            continue
        tf = Counter(toks)
        doc_len = len(toks)
        norm = 1 - _BM25_B + _BM25_B * (doc_len / avg_len if avg_len > 0 else 1.0)
        score = 0.0
        for term in query_tokens:
            f = tf.get(term, 0)
            if f == 0:
                continue
            score += idf[term] * f * (_BM25_K1 + 1) / (f + _BM25_K1 * norm)
        out[name] = score
    return out


# ── Rank normalisation (§6.2 critical step) ────────────────────────────


def rank_normalise(scores: dict[str, float]) -> dict[str, float]:
    """Convert raw scores to [0, 1] by rank.

    The highest-scoring item gets 1.0, the lowest gets 0.0, ties share
    the average rank position. This is the load-bearing pre-step
    before linear combination — without it, BM25 and PageRank sit on
    different dynamic ranges and α stops meaning what it reads.
    """
    if not scores:
        return {}
    n = len(scores)
    if n == 1:
        return {next(iter(scores)): 1.0}
    # Sort by score ascending; rank 0 is lowest.
    sorted_items = sorted(scores.items(), key=lambda kv: (kv[1], kv[0]))
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        # Group ties
        while j + 1 < n and sorted_items[j + 1][1] == sorted_items[i][1]:
            j += 1
        avg_rank = (i + j) / 2
        norm = avg_rank / (n - 1)
        for k in range(i, j + 1):
            out[sorted_items[k][0]] = norm
        i = j + 1
    return out


# ── Combined ranker ────────────────────────────────────────────────────


def combined_scores(
    *,
    task_scores: dict[str, float],
    centrality_scores: dict[str, float],
    alpha: float = 0.7,
) -> dict[str, float]:
    """Combine task_score + centrality_prior into a single score per
    entity.

    α=0 → pure centrality (cold-start fallback).
    α=1 → pure task signal.
    Default α=0.7 reflects "task signal dominates when present" but
    is a guess until the §8.5 sweep validates it.

    Both inputs are rank-normalised before combination so α is a real
    knob.
    """
    if not (0.0 <= alpha <= 1.0):
        raise ValueError(f"alpha must be in [0, 1], got {alpha}")
    norm_task = rank_normalise(task_scores) if task_scores else {}
    norm_cent = rank_normalise(centrality_scores) if centrality_scores else {}
    all_keys = set(norm_task) | set(norm_cent)
    if not all_keys:
        return {}
    # If task is empty/zero across the board, fall back to pure centrality.
    has_signal = any(v > 0 for v in norm_task.values())
    effective_alpha = alpha if has_signal else 0.0
    return {
        k: effective_alpha * norm_task.get(k, 0.0)
        + (1 - effective_alpha) * norm_cent.get(k, 0.0)
        for k in all_keys
    }


def _first_line(s: str) -> str:
    if not s:
        return ""
    return s.split("\n", 1)[0]
