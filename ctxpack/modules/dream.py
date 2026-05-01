"""Dream pipeline — turn telemetry into INFERRED knowledge.

Two cooperating tiers:

* ``observe_hydration`` — inline hook, called after each query, updates a
  ``ConfidenceTracker`` for sections retrieved during a successful (or
  unsuccessful) answer. Microsecond cost; mirrors wakefulness.

* ``consolidate`` — periodic CLI pass, reads accumulated telemetry, mines
  co-occurrence patterns and gaps, emits ``IREntity[layer=INFERRED]``
  pattern entities and a gap queue for ELICITED prompts. Mirrors sleep:
  heavier, auditable, produces artifacts that humans can review before
  they reach prod prompts.

No LLM in either path. Pure aggregation over the local JSONL telemetry
log; safe to run on the host that owns the data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Iterable, Optional

from ctxpack.core.confidence import ConfidenceTracker
from ctxpack.core.layers import ContextLayer
from ctxpack.core.packer.ir import IREntity, IRField, IRSource
from ctxpack.core.telemetry import TelemetryLog


# ── Defaults ────────────────────────────────────────────────────────────

# A pair of sections must be co-retrieved at least this many times before
# the dream pipeline is willing to emit a pattern entity. Set high enough
# that random co-occurrence in a small log doesn't generate noise.
_DEFAULT_MIN_CO_OCCURRENCES = 3

# Confidence at the threshold count, scaling linearly to 1.0. Twenty
# observations are needed to fully trust a pattern.
_FULL_CONFIDENCE_OBSERVATIONS = 20


# ── Public data ─────────────────────────────────────────────────────────


@dataclass
class GapItem:
    """A question the catalog could not answer.

    ``question_hash`` is SHA-256 — the raw question is never stored — so
    operators triaging the queue see only how often the gap occurred and
    when, not the question text itself.
    """

    question_hash: str
    occurrences: int
    first_seen: str
    last_seen: str


@dataclass
class DreamResult:
    """Output of one consolidation pass."""

    entities: list[IREntity] = field(default_factory=list)
    gaps: list[GapItem] = field(default_factory=list)


# ── Inline observe-hook ─────────────────────────────────────────────────


def observe_hydration(
    tracker: ConfidenceTracker,
    *,
    sections_used: Iterable[str],
    confirmed: bool,
    now: Optional[float] = None,
) -> None:
    """Update tracker confidence for every section a query touched.

    Called from the hot path after ``ContextGuard.check`` decides whether
    the answer was good. ``confirmed=True`` ramps confidence; ``False``
    halves it.
    """
    sections = list(sections_used)
    if not sections:
        return
    tracker.observe_many(sections, confirmed=confirmed, now=now)


# ── Co-occurrence mining ────────────────────────────────────────────────


def mine_co_occurrences(
    telemetry: TelemetryLog,
    *,
    min_co_occurrences: int = _DEFAULT_MIN_CO_OCCURRENCES,
) -> list[dict[str, Any]]:
    """Mine section pairs that appear together in the same query.

    Returns a list of dicts ``{"pair": (a, b), "count": n,
    "questions": k}`` for pairs above the threshold. The pair tuple is
    sorted so ``(A, B)`` and ``(B, A)`` collapse.
    """
    events = _read(telemetry)
    pair_counter: Counter[tuple[str, str]] = Counter()
    pair_questions: defaultdict[tuple[str, str], set[str]] = defaultdict(set)

    for ev in events:
        sections = ev.get("sections_requested") or []
        if len(sections) < 2:
            continue
        # Dedupe within an event so [A, A, B] doesn't double-count (A, B).
        unique = sorted(set(sections))
        qh = ev.get("question_hash", "")
        for a, b in combinations(unique, 2):
            pair = (a, b)
            pair_counter[pair] += 1
            if qh:
                pair_questions[pair].add(qh)

    out: list[dict[str, Any]] = []
    for pair, count in pair_counter.items():
        if count < min_co_occurrences:
            continue
        out.append(
            {
                "pair": pair,
                "count": count,
                "questions": len(pair_questions[pair]),
            }
        )
    out.sort(key=lambda d: (-d["count"], d["pair"]))
    return out


# ── Gap detection ───────────────────────────────────────────────────────


def detect_gaps(
    telemetry: TelemetryLog,
    *,
    min_occurrences: int = _DEFAULT_MIN_CO_OCCURRENCES,
) -> list[GapItem]:
    """Find questions that consistently miss the catalog (matched=0).

    Returns one ``GapItem`` per question_hash above the threshold,
    ordered by occurrence count descending.
    """
    events = _read(telemetry)
    by_hash: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        if ev.get("sections_matched", 0) != 0:
            continue
        qh = ev.get("question_hash") or ""
        if not qh:
            continue
        by_hash[qh].append(ev)

    gaps: list[GapItem] = []
    for qh, evs in by_hash.items():
        if len(evs) < min_occurrences:
            continue
        timestamps = sorted(ev.get("timestamp", "") for ev in evs)
        gaps.append(
            GapItem(
                question_hash=qh,
                occurrences=len(evs),
                first_seen=timestamps[0],
                last_seen=timestamps[-1],
            )
        )
    gaps.sort(key=lambda g: (-g.occurrences, g.question_hash))
    return gaps


# ── Consolidate (top-level dream pass) ──────────────────────────────────


def consolidate(
    telemetry: TelemetryLog,
    *,
    min_co_occurrences: int = _DEFAULT_MIN_CO_OCCURRENCES,
    gap_min_occurrences: int = _DEFAULT_MIN_CO_OCCURRENCES,
) -> DreamResult:
    """Run one full consolidation pass over the telemetry log.

    Yields pattern entities (INFERRED layer) ready to be merged into a
    pack and a gap queue ready to drive elicitation prompts.
    """
    patterns = mine_co_occurrences(
        telemetry, min_co_occurrences=min_co_occurrences
    )
    gaps = detect_gaps(telemetry, min_occurrences=gap_min_occurrences)

    entities: list[IREntity] = []
    for p in patterns:
        a, b = p["pair"]
        confidence = min(1.0, p["count"] / _FULL_CONFIDENCE_OBSERVATIONS)
        entities.append(
            IREntity(
                name=f"PATTERN-{a}-AND-{b}",
                layer=ContextLayer.INFERRED,
                confidence=confidence,
                observation_count=p["count"],
                fields=[
                    IRField(
                        key="pattern",
                        value="co-retrieved",
                        layer=ContextLayer.INFERRED,
                        confidence=confidence,
                        observation_count=p["count"],
                    ),
                    IRField(
                        key="section_a",
                        value=a,
                        layer=ContextLayer.INFERRED,
                        confidence=confidence,
                    ),
                    IRField(
                        key="section_b",
                        value=b,
                        layer=ContextLayer.INFERRED,
                        confidence=confidence,
                    ),
                    IRField(
                        key="observed_in_questions",
                        value=str(p["questions"]),
                        layer=ContextLayer.INFERRED,
                        confidence=confidence,
                    ),
                ],
                sources=[IRSource(file="<dream-pass>", line_start=0)],
            )
        )

    return DreamResult(entities=entities, gaps=gaps)


# ── Helpers ─────────────────────────────────────────────────────────────


def _read(telemetry: TelemetryLog) -> list[dict[str, Any]]:
    """Re-use TelemetryLog's private reader without going through summary()."""
    # ``_read_events`` is module-private but stable; the alternative is
    # parsing JSONL ourselves which would duplicate logic.
    return telemetry._read_events()  # type: ignore[attr-defined]
