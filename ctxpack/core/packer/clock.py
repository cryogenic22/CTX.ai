"""Deterministic date source for pack headers.

Byte-identical repacks are a core product guarantee ("same corpus, same
pack"). Wall-clock dates in headers break that, so every header date goes
through as_of_date(), which resolves in priority order:

1. explicit ``as_of`` argument (from pack(as_of=...) / CLI --as-of)
2. ``CTXPACK_AS_OF`` environment variable (CI determinism gates)
3. today's date (interactive default)
"""

from __future__ import annotations

import datetime
import os


def as_of_date(explicit: str | None = None) -> str:
    """Resolve the header date: explicit arg > CTXPACK_AS_OF env > today."""
    if explicit:
        return explicit
    env = os.environ.get("CTXPACK_AS_OF", "")
    if env:
        return env
    return datetime.date.today().isoformat()
