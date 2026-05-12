"""Single source of truth for BPE counting in the code packer.

Pinned encoding: ``cl100k_base`` via ``tiktoken``. See
``docs/adr/0001-tokeniser-choice.md`` for the why.

Every code-packer task that measures or budgets tokens MUST import
``count_bpe`` from this module. Bypassing it (calling ``tiktoken``
directly somewhere else) creates measurement drift and breaks the
§8.6 determinism gate.

Sibling, not replacement, of ``ctxpack/benchmarks/metrics/cost.py``.
``cost.py`` answers "what would this cost on model X?" — multiple
encodings, pricing tables. ``tokens.py`` answers "how many BPE
units, for budgeting?" — one encoding, no pricing.
"""

from __future__ import annotations

from typing import Optional

import tiktoken


_ENCODER_NAME = "cl100k_base"
_ENCODER: Optional[tiktoken.Encoding] = None


def _get_encoder(encoding: Optional[str] = None) -> tiktoken.Encoding:
    """Return the encoder. Caches the default singleton; loads
    overrides per-call (rare path).

    tiktoken encoders are safe to share across threads — their BPE
    tables are loaded once and read-only thereafter.
    """
    global _ENCODER
    if encoding is None or encoding == _ENCODER_NAME:
        if _ENCODER is None:
            _ENCODER = tiktoken.get_encoding(_ENCODER_NAME)
        return _ENCODER
    return tiktoken.get_encoding(encoding)


def count_bpe(s: str, *, encoding: Optional[str] = None) -> int:
    """Return the BPE token count for ``s`` under the pinned encoding.

    Parameters
    ----------
    s : str
        Text to count. Empty string returns 0.
    encoding : str, optional
        Override the default encoding (cl100k_base). Provided as an
        escape hatch for power-user comparisons; every internal
        caller in the code packer omits this kwarg.

    Raises
    ------
    TypeError
        If ``s`` is not a ``str``. Bytes / ints / None / etc. fail
        here rather than producing a confusing tiktoken error
        further down the stack.
    """
    if not isinstance(s, str):
        raise TypeError(
            f"count_bpe expects str, got {type(s).__name__}"
        )
    if s == "":
        return 0
    enc = _get_encoder(encoding)
    return len(enc.encode(s))
