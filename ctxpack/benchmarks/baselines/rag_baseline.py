"""RAG baseline: chunk → embed → retrieve → inject.

Standard embedding-based retrieval for competitive comparison with CtxPack
hydration. Uses OpenAI text-embedding-3-small for embeddings and cosine
similarity for retrieval.

Offline mode (no API key): uses keyword_retrieve() instead of embeddings.

This module lives in benchmarks/baselines/ (NOT in core/) because it
requires the openai SDK — preserving core's zero-dep constraint.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any


def chunk_corpus(
    corpus_dir: str,
    *,
    max_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[dict[str, Any]]:
    """Chunk all files in a corpus directory into ~max_tokens chunks.

    Each chunk is a dict with 'text' and 'source' (filename).
    Chunking uses paragraph boundaries (double newlines) when possible,
    falling back to sentence boundaries, then hard word-count splits.
    """
    chunks: list[dict[str, Any]] = []

    for root, _dirs, files in os.walk(corpus_dir):
        for fname in sorted(files):
            if not fname.endswith((".yaml", ".yml", ".md", ".json")):
                continue
            path = os.path.join(root, fname)
            rel_path = os.path.relpath(path, corpus_dir)

            with open(path, encoding="utf-8") as f:
                text = f.read()

            file_chunks = _chunk_text(text, max_tokens=max_tokens,
                                       overlap_tokens=overlap_tokens)
            for chunk_text in file_chunks:
                if chunk_text.strip():
                    chunks.append({
                        "text": chunk_text.strip(),
                        "source": rel_path,
                    })

    return chunks


def _chunk_text(
    text: str,
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """Split text into chunks at paragraph boundaries."""
    if not text.strip():
        return []

    # Split into paragraphs (double newline)
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = len(para.split())

        # If single paragraph exceeds max, split by sentences
        if para_tokens > max_tokens:
            # Flush current
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_tokens = 0

            # Split large paragraph by sentences
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sent_buf: list[str] = []
            sent_tokens = 0
            for sent in sentences:
                st = len(sent.split())
                if sent_tokens + st > max_tokens and sent_buf:
                    chunks.append(" ".join(sent_buf))
                    # Overlap: keep last few tokens
                    overlap_text = " ".join(sent_buf[-2:]) if len(sent_buf) >= 2 else ""
                    sent_buf = [overlap_text, sent] if overlap_text else [sent]
                    sent_tokens = len(" ".join(sent_buf).split())
                else:
                    sent_buf.append(sent)
                    sent_tokens += st
            if sent_buf:
                chunks.append(" ".join(sent_buf))
            continue

        if current_tokens + para_tokens > max_tokens and current:
            chunks.append("\n\n".join(current))
            # Overlap: keep last paragraph
            if overlap_tokens > 0 and current:
                last = current[-1]
                current = [last]
                current_tokens = len(last.split())
            else:
                current = []
                current_tokens = 0

        current.append(para)
        current_tokens += para_tokens

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def keyword_retrieve(
    chunks: list[dict[str, Any]],
    query: str,
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve top-k chunks by keyword overlap (offline, no embeddings).

    Used as fallback when no API key is available. Scores by term overlap
    between query and chunk text.
    """
    query_terms = set(_tokenize(query))
    if not query_terms:
        return []

    scored: list[tuple[float, int, dict]] = []
    for idx, chunk in enumerate(chunks):
        chunk_terms = set(_tokenize(chunk["text"]))
        overlap = query_terms & chunk_terms
        if overlap:
            score = len(overlap) / len(query_terms)
            scored.append((score, idx, chunk))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [chunk for _, _, chunk in scored[:top_k]]


def embedding_retrieve(
    chunks: list[dict[str, Any]],
    query: str,
    *,
    top_k: int = 5,
    api_key: str = "",
    model: str = "text-embedding-3-small",
) -> list[dict[str, Any]]:
    """Retrieve top-k chunks by embedding cosine similarity.

    Requires openai API key. Embeds all chunks + query, returns nearest.
    Caches chunk embeddings for reuse across queries.
    """
    import json
    import urllib.request

    if not api_key:
        # Fallback to keyword retrieval
        return keyword_retrieve(chunks, query, top_k=top_k)

    # Embed all texts (chunks + query) in a single batch
    texts = [c["text"] for c in chunks] + [query]
    embeddings = _embed_batch(texts, api_key=api_key, model=model)

    if not embeddings or len(embeddings) != len(texts):
        return keyword_retrieve(chunks, query, top_k=top_k)

    query_emb = embeddings[-1]
    chunk_embs = embeddings[:-1]

    # Score by cosine similarity
    scored: list[tuple[float, int, dict]] = []
    for idx, (chunk, emb) in enumerate(zip(chunks, chunk_embs)):
        sim = _cosine_similarity(query_emb, emb)
        scored.append((sim, idx, chunk))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [chunk for _, _, chunk in scored[:top_k]]


def assemble_context(chunks: list[dict[str, Any]]) -> str:
    """Join retrieved chunks into a single context string."""
    if not chunks:
        return ""

    parts: list[str] = []
    for chunk in chunks:
        source = chunk.get("source", "")
        text = chunk.get("text", "")
        if source:
            parts.append(f"[Source: {source}]\n{text}")
        else:
            parts.append(text)

    return "\n\n---\n\n".join(parts)


# ── Helpers ──


_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens."""
    return [t.lower() for t in _TOKEN_RE.findall(text) if len(t) > 1]


def _embed_batch(
    texts: list[str],
    *,
    api_key: str,
    model: str,
) -> list[list[float]]:
    """Embed a batch of texts using OpenAI Embeddings API."""
    import json
    import urllib.request

    from ctxpack.benchmarks.metrics.fidelity import _retry_api_call

    def _call() -> str:
        payload = json.dumps({
            "model": model,
            "input": texts,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.openai.com/v1/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Sort by index to maintain order
            items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            return json.dumps([item["embedding"] for item in items])

    result = _retry_api_call(_call)
    if result.startswith("(error:"):
        return []

    try:
        return json.loads(result)
    except (json.JSONDecodeError, ValueError):
        return []


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
