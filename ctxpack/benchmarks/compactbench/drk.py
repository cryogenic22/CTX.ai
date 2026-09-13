"""DR@K — decision recall at K compactions, plus Wilson CIs.

The metric layer is deliberately tiny and driver-agnostic: the harness
(any arm) produces per-probe boolean grades per compaction cycle; this
module turns them into the survival curve the benchmark reports.
"""

from __future__ import annotations

import math
from typing import Any


def wilson_ci(correct: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = correct / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (round(max(0.0, center - margin), 4),
            round(min(1.0, center + margin), 4))


def recall_at_k(grades: dict[int, list[bool]]) -> dict[int, dict[str, Any]]:
    """Survival curve: {k: [probe grades]} → {k: {recall, ci95, n}}.

    ``grades[k]`` holds one boolean per planted fact probed after the
    k-th compaction cycle, pooled across seeds (pairing for McNemar
    happens upstream, on the raw rows).
    """
    curve: dict[int, dict[str, Any]] = {}
    for k in sorted(grades):
        flags = grades[k]
        n = len(flags)
        correct = sum(flags)
        lo, hi = wilson_ci(correct, n)
        curve[k] = {
            "n": n,
            "correct": correct,
            "recall": round(correct / n, 4) if n else None,
            "ci95": [lo, hi],
        }
    return curve


def mcnemar_b_c(paired: list[tuple[bool, bool]]) -> dict[str, Any]:
    """Discordant-pair counts for McNemar: (arm_a_correct, arm_b_correct)
    per probe. Exact binomial p-value (two-sided) on the discordant pairs
    — no scipy, stdlib only."""
    b = sum(1 for a_ok, b_ok in paired if a_ok and not b_ok)
    c = sum(1 for a_ok, b_ok in paired if not a_ok and b_ok)
    n = b + c
    if n == 0:
        return {"b": 0, "c": 0, "p_value": 1.0}
    # two-sided exact binomial test, p = P(X <= min(b,c)) * 2 under p=0.5
    k = min(b, c)
    cdf = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return {"b": b, "c": c, "p_value": round(min(1.0, 2 * cdf), 6)}
