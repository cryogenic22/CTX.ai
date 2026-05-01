"""ConfidenceTracker — observation-driven trust updates with time decay.

Models how confidence in a fact should change as agents see it confirmed
or contradicted in real conversations, and how it should fade when no
one has reinforced it for a while.

Math (all defaults tunable on the constructor):

    confirmed observation:  c_new = c + (1 - c) * alpha     (alpha = 0.1)
    contradicted:           c_new = c * beta                (beta  = 0.5)
    decay over time:        c_new = c * gamma^days_elapsed  (gamma = 0.95)
    prune threshold:        drop entries where c < 0.2

Why these numbers:

* alpha = 0.1 makes a single observation weak evidence (0.0 → 0.1) and
  takes ~20 confirmations to reach 0.88 — patterns become "established"
  only after sustained exposure.
* beta = 0.5 makes a single contradiction sharply costly (0.8 → 0.4),
  matching the cost asymmetry: a wrong answer in production hurts more
  than a right answer helps.
* gamma = 0.95/day approximates the Ebbinghaus forgetting curve at the
  granularity dreams need (a week of inactivity drops a fact ~30%, a
  month drops it ~80%).
* prune at 0.2 keeps the working set small without losing recent low-
  confidence patterns that may yet be confirmed.

Persistence is plain JSON with atomic write (tmp + os.replace). No
external dependencies. The store is per-corpus, normally at
``.ctx-cache/confidence.json``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Iterator, Optional, Union

if TYPE_CHECKING:
    from .packer.ir import IREntity


# ── Defaults ────────────────────────────────────────────────────────────

_ALPHA = 0.1   # confirmed-observation gain
_BETA = 0.5    # contradicted-observation discount
_GAMMA = 0.95  # daily decay factor
_PRUNE = 0.2   # drop confidence below this when apply_decay runs
_SECONDS_PER_DAY = 86400.0


# ── Record ──────────────────────────────────────────────────────────────


@dataclass
class ConfidenceRecord:
    """Per-entity tracker state.

    ``confidence`` is the stored value; callers reading via
    ``ConfidenceTracker.get_confidence`` see a decayed view that is not
    written back unless ``apply_decay`` is called.
    """

    name: str
    confidence: float = 0.0
    last_observed: float = 0.0
    observation_count: int = 0
    contradiction_count: int = 0


# ── Tracker ─────────────────────────────────────────────────────────────


class ConfidenceTracker:
    """Mutable per-entity confidence store with decay + persistence.

    Not thread-safe. If multiple processes need to share a tracker,
    serialise updates through a single owner (e.g. the dream CLI) and
    have read-only consumers reload from disk.
    """

    def __init__(
        self,
        *,
        alpha: float = _ALPHA,
        beta: float = _BETA,
        gamma: float = _GAMMA,
        prune_below: float = _PRUNE,
    ) -> None:
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.prune_below = prune_below
        self.records: dict[str, ConfidenceRecord] = {}

    # ── Container protocol ────

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self) -> Iterator[str]:
        return iter(self.records)

    def __contains__(self, name: str) -> bool:
        return name in self.records

    # ── Observation ────

    def observe(
        self,
        name: str,
        *,
        confirmed: bool,
        now: Optional[float] = None,
    ) -> None:
        """Record a single confirmation or contradiction event."""
        ts = time.time() if now is None else now
        rec = self.records.get(name)
        if rec is None:
            rec = ConfidenceRecord(name=name, last_observed=ts)
            self.records[name] = rec

        if confirmed:
            rec.confidence = rec.confidence + (1.0 - rec.confidence) * self.alpha
            rec.observation_count += 1
        else:
            rec.confidence = rec.confidence * self.beta
            rec.contradiction_count += 1
        rec.last_observed = ts

    def observe_many(
        self,
        names: Iterable[str],
        *,
        confirmed: bool,
        now: Optional[float] = None,
    ) -> None:
        """Convenience: record the same outcome for a batch of entities.

        Used by the inline observe-hook after a successful answer where
        every retrieved section counts as confirmation.
        """
        ts = time.time() if now is None else now
        for name in names:
            self.observe(name, confirmed=confirmed, now=ts)

    # ── Reading ────

    def get_confidence(self, name: str, *, now: Optional[float] = None) -> float:
        """Return the time-decayed confidence for ``name``.

        Does NOT mutate the stored record — callers can sample without
        committing the decay. Use ``apply_decay`` to write decay through.
        """
        rec = self.records.get(name)
        if rec is None:
            return 0.0
        ts = time.time() if now is None else now
        days = max(0.0, (ts - rec.last_observed) / _SECONDS_PER_DAY)
        return rec.confidence * (self.gamma ** days)

    # ── Decay & prune ────

    def apply_decay(self, *, now: Optional[float] = None) -> int:
        """Write decay through to storage and prune low-confidence records.

        Returns the number of records pruned. Call this before saving so
        the on-disk store reflects current confidence rather than the
        confidence at the moment each record was last touched.
        """
        ts = time.time() if now is None else now
        pruned = 0
        for name in list(self.records):
            rec = self.records[name]
            days = max(0.0, (ts - rec.last_observed) / _SECONDS_PER_DAY)
            rec.confidence = rec.confidence * (self.gamma ** days)
            rec.last_observed = ts
            if rec.confidence < self.prune_below:
                del self.records[name]
                pruned += 1
        return pruned

    # ── Persistence ────

    def save(self, path: Union[str, Path]) -> None:
        """Atomically write the tracker state to ``path`` as JSON."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "saved_at": time.time(),
            "records": [asdict(rec) for rec in self.records.values()],
        }
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, p)

    @classmethod
    def load(
        cls,
        path: Union[str, Path],
        *,
        alpha: float = _ALPHA,
        beta: float = _BETA,
        gamma: float = _GAMMA,
        prune_below: float = _PRUNE,
    ) -> "ConfidenceTracker":
        """Load tracker state from ``path``.

        Missing file → empty tracker (so first-run code paths just work).
        """
        t = cls(alpha=alpha, beta=beta, gamma=gamma, prune_below=prune_below)
        p = Path(path)
        if not p.exists():
            return t
        data = json.loads(p.read_text(encoding="utf-8"))
        for raw in data.get("records", []):
            rec = ConfidenceRecord(
                name=raw["name"],
                confidence=raw.get("confidence", 0.0),
                last_observed=raw.get("last_observed", 0.0),
                observation_count=raw.get("observation_count", 0),
                contradiction_count=raw.get("contradiction_count", 0),
            )
            t.records[rec.name] = rec
        return t

    # ── Entity integration ────

    def apply_to_entity(
        self,
        entity: "IREntity",
        *,
        now: Optional[float] = None,
    ) -> None:
        """Stamp the tracker's view onto a non-RULES IREntity.

        RULES facts are skipped — their confidence is set by policy, not
        by how often agents cite them.
        """
        # Local import to avoid a circular import at module load.
        from .layers import ContextLayer

        if entity.layer is ContextLayer.RULES:
            return
        rec = self.records.get(f"ENTITY-{entity.name}") or self.records.get(entity.name)
        if rec is None:
            return
        entity.confidence = self.get_confidence(rec.name, now=now)
        entity.observation_count = rec.observation_count
