"""Baseline 1: Raw stuffing — full source text, no compression."""

from __future__ import annotations

import os


def prepare_raw_context(corpus_dir: str) -> str:
    """Concatenate all source files into one text blob."""
    parts: list[str] = []
    for root, _dirs, files in os.walk(corpus_dir):
        for fname in sorted(files):
            if not fname.endswith((".yaml", ".yml", ".md")):
                continue
            path = os.path.join(root, fname)
            rel = os.path.relpath(path, corpus_dir).replace("\\", "/")
            with open(path, encoding="utf-8") as f:
                content = f.read()
            parts.append(f"--- {rel} ---\n{content}")
    return "\n\n".join(parts)
