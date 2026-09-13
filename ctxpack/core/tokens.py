"""The one token estimator for user-facing telemetry (execution plan W1-3).

BPE != words. Whitespace splits measured -49% to -78% against cl100k on
this repo's real content (README prose, session gists, .ctx ledgers) —
a "token" number built on them is off by 2-5x. The eval stack uses real
BPE (tiktoken, an optional benchmarks-only dependency); the zero-dep core
cannot, so it reports a *labelled* deterministic estimate instead, and
every surface that shows the number must carry the label.

Two content kinds, because one divisor cannot fit both (measured
2026-07-11 against cl100k_base):

  - ``prose``  — markdown/English/code. 4.0 chars/token measured on
    README.md (+0%), 4.44 on Python source (+11%).
  - ``ctx``    — dense .ctx notation (short keys, symbols). 2.85
    chars/token measured on a real session ledger; chars/3 lands -5%.

Calibration is re-measured by ``tests/test_token_accounting.py`` whenever
tiktoken is installed (kill threshold: |error| > 15% fails the gate).
Whitespace word counts remain fine *internally* — they must simply never
be presented as tokens.
"""

from __future__ import annotations

PROSE_DIVISOR = 4.0
CTX_DIVISOR = 3.0

ESTIMATOR_PROSE = "approx-chars/4"
ESTIMATOR_CTX = "approx-chars/3"

_KINDS = {
    "prose": (PROSE_DIVISOR, ESTIMATOR_PROSE),
    "ctx": (CTX_DIVISOR, ESTIMATOR_CTX),
}


def estimator_label(kind: str = "prose") -> str:
    """The label that must accompany any estimate of this kind."""
    return _KINDS[kind][1]


def estimate_tokens(text: str, kind: str = "prose") -> int:
    """Deterministic stdlib token estimate for ``text``.

    ``kind`` is ``"prose"`` for markdown/English/code and ``"ctx"`` for
    serialized .ctx notation. Deterministic: same input, same output —
    no clocks, no environment.
    """
    divisor, _ = _KINDS[kind]
    if not text:
        return 0
    return max(1, round(len(text) / divisor))
