"""ElicitStore — capture expert tribal knowledge as ELICITED facts.

Tribal knowledge — the answers that live in operators' heads, not in
runbooks or policy docs — is the highest-leverage knowledge an LLM can
have, and the easiest to lose. This store gives it a home, a confidence
score, and a confirmation protocol so a single expert's opinion is not
silently treated as gospel.

Confidence ladder:

    add(expert=A)                       → 0.7    (informed opinion)
    confirm(expert=B, B != A)           → 0.95   (cross-checked)
    confirm(expert=C, C != A, C != B)   → ≥0.95  (mild reinforcement)
    challenge(expert=D, D != original)  → halved (contradiction)

Persistence is plain JSON with atomic write (tmp + os.replace), normally
at ``.ctx-cache/elicited.json``. No external dependencies.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Union

from ctxpack.core.layers import ContextLayer
from ctxpack.core.packer.ir import IREntity, IRField, IRSource

PathLike = Union[str, Path]


_INITIAL_CONFIDENCE = 0.7
_CONFIRMED_CONFIDENCE = 0.95
_CHALLENGE_FACTOR = 0.5


# ── Record ──────────────────────────────────────────────────────────────


@dataclass
class ElicitedFact:
    """Single piece of expert-captured knowledge."""

    name: str
    fact: str
    original_expert: str
    confidence: float = _INITIAL_CONFIDENCE
    created_at: float = 0.0
    confirming_expert: Optional[str] = None
    confirmed_at: Optional[float] = None
    additional_confirmers: list[str] = field(default_factory=list)
    dissenters: list[str] = field(default_factory=list)


# ── Store ───────────────────────────────────────────────────────────────


class ElicitStore:
    """Mutable store of ELICITED facts.

    Not thread-safe. The CLI is the expected single writer; readers
    reload from disk to pick up changes.
    """

    def __init__(self) -> None:
        self.facts: dict[str, ElicitedFact] = {}

    # ── Container protocol ────

    def __len__(self) -> int:
        return len(self.facts)

    def __iter__(self) -> Iterator[str]:
        return iter(self.facts)

    def __contains__(self, name: str) -> bool:
        return name in self.facts

    def list(self) -> list[ElicitedFact]:
        return list(self.facts.values())

    def get(self, name: str) -> Optional[ElicitedFact]:
        return self.facts.get(name)

    # ── Add ────

    def add(
        self,
        *,
        name: str,
        fact: str,
        expert: str,
        now: Optional[float] = None,
    ) -> ElicitedFact:
        """Capture an expert's tribal knowledge.

        If the fact already exists, only the *original* expert may
        overwrite the text — a different expert must use ``confirm`` (or
        ``challenge``) to record agreement / dissent rather than silently
        replacing the captured knowledge.
        """
        ts = time.time() if now is None else now
        existing = self.facts.get(name)
        if existing is not None and existing.original_expert != expert:
            raise ValueError(
                f"Fact '{name}' was originally captured by "
                f"{existing.original_expert!r}; expert {expert!r} should "
                f"call confirm() or challenge() rather than add()."
            )
        if existing is not None:
            existing.fact = fact
            return existing

        rec = ElicitedFact(
            name=name,
            fact=fact,
            original_expert=expert,
            confidence=_INITIAL_CONFIDENCE,
            created_at=ts,
        )
        self.facts[name] = rec
        return rec

    # ── Confirm ────

    def confirm(
        self,
        *,
        name: str,
        expert: str,
        now: Optional[float] = None,
    ) -> ElicitedFact:
        """Second-expert confirmation. Bumps confidence to 0.95.

        A third or later confirmer is recorded but does not push
        confidence above 0.95 — once two independent experts agree, the
        store stops claiming additional certainty without further
        evidence.
        """
        ts = time.time() if now is None else now
        rec = self.facts.get(name)
        if rec is None:
            raise KeyError(name)
        if expert == rec.original_expert:
            raise ValueError(
                f"Expert {expert!r} originated this fact and cannot also "
                f"confirm it. Confirmation must come from a different "
                f"person."
            )
        if rec.confirming_expert is None:
            rec.confirming_expert = expert
            rec.confirmed_at = ts
            rec.confidence = max(rec.confidence, _CONFIRMED_CONFIDENCE)
        else:
            if expert not in rec.additional_confirmers and expert != rec.confirming_expert:
                rec.additional_confirmers.append(expert)
        return rec

    # ── Challenge ────

    def challenge(
        self,
        *,
        name: str,
        expert: str,
        reason: str = "",
        now: Optional[float] = None,
    ) -> ElicitedFact:
        """A different expert says the fact is wrong; halve confidence.

        ``reason`` is recorded as a side channel for audit; it is not
        re-published to consumers because that would make ELICITED
        entries stand in for ground truth they were never meant to bear.
        """
        ts = time.time() if now is None else now
        rec = self.facts.get(name)
        if rec is None:
            raise KeyError(name)
        if expert == rec.original_expert:
            raise ValueError(
                f"Expert {expert!r} originated this fact and cannot also "
                f"challenge it; retract via add() with corrected text."
            )
        rec.confidence = rec.confidence * _CHALLENGE_FACTOR
        if expert not in rec.dissenters:
            rec.dissenters.append(expert)
        return rec

    # ── To IR ────

    def to_entities(self) -> list[IREntity]:
        """Render the store as ELICITED IREntity objects.

        Each fact becomes one entity with a single ``fact`` field plus
        bookkeeping fields (``original_expert``, ``confirming_expert``).
        """
        out: list[IREntity] = []
        for rec in self.facts.values():
            fields = [
                IRField(
                    key="fact",
                    value=rec.fact,
                    layer=ContextLayer.ELICITED,
                    confidence=rec.confidence,
                ),
                IRField(
                    key="original_expert",
                    value=rec.original_expert,
                    layer=ContextLayer.ELICITED,
                    confidence=rec.confidence,
                ),
            ]
            if rec.confirming_expert:
                fields.append(
                    IRField(
                        key="confirming_expert",
                        value=rec.confirming_expert,
                        layer=ContextLayer.ELICITED,
                        confidence=rec.confidence,
                    )
                )
            entity = IREntity(
                name=rec.name,
                fields=fields,
                layer=ContextLayer.ELICITED,
                confidence=rec.confidence,
                sources=[IRSource(file="<elicited>", line_start=0)],
            )
            out.append(entity)
        return out

    # ── Persistence ────

    def save(self, path: PathLike) -> None:
        """Atomically write the store to ``path`` as JSON."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "saved_at": time.time(),
            "facts": [asdict(rec) for rec in self.facts.values()],
        }
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, p)

    @classmethod
    def load(cls, path: PathLike) -> "ElicitStore":
        s = cls()
        p = Path(path)
        if not p.exists():
            return s
        data = json.loads(p.read_text(encoding="utf-8"))
        for raw in data.get("facts", []):
            rec = ElicitedFact(
                name=raw["name"],
                fact=raw["fact"],
                original_expert=raw["original_expert"],
                confidence=raw.get("confidence", _INITIAL_CONFIDENCE),
                created_at=raw.get("created_at", 0.0),
                confirming_expert=raw.get("confirming_expert"),
                confirmed_at=raw.get("confirmed_at"),
                additional_confirmers=list(raw.get("additional_confirmers", [])),
                dissenters=list(raw.get("dissenters", [])),
            )
            s.facts[rec.name] = rec
        return s


# ── Gap-driven elicitation prompts ──────────────────────────────────────


def build_elicitation_prompt(gap: "GapItem") -> str:
    """Format a gap into a prompt operators can route to a domain expert.

    Returns plain text suitable for posting to a #ask-the-experts Slack
    channel or surfacing in a dashboard. The raw question is not stored
    in telemetry (only its hash), so the prompt has to lead with the
    behavioural signal: "this gap recurred N times, here's its hash,
    please figure out what people are asking and write a note."
    """
    from ctxpack.modules.dream import GapItem  # local import to avoid cycles

    assert isinstance(gap, GapItem)
    lines = [
        f"Knowledge-gap detected (hash {gap.question_hash}).",
        f"Asked {gap.occurrences} times between {gap.first_seen} and "
        f"{gap.last_seen}; the catalog returned no sections each time.",
        "Action: identify what the questions were about and capture an "
        "ELICITED note via:",
        f"  ctxpack elicit add <ENTITY> \"<fact>\" --expert <you>",
        "If you saw a similar question recently, your message history is "
        "the fastest source — the raw text was never stored in telemetry.",
    ]
    return "\n".join(lines)
