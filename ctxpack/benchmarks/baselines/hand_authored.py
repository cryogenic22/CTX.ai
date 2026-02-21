"""Baseline 3: Hand-authored .ctx file (human expert baseline)."""

from __future__ import annotations

import os


def prepare_hand_context(ctx_path: str) -> str:
    """Load a hand-authored .ctx file as the human baseline."""
    if not os.path.exists(ctx_path):
        return ""
    with open(ctx_path, encoding="utf-8") as f:
        return f.read()
