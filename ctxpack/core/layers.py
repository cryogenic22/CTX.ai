"""Four-layer context architecture.

Every fact in a CtxPack belongs to exactly one trust layer. The hydrator,
guard, and grounding modules read this layer to decide how a fact should
be presented to the LLM and how skeptical the model should be.

Layer semantics:

    RULES     — Authoritative policy: regulations, contracts, validated
                domain definitions. Confidence is fixed at 1.0 and never
                decays. Source is a versioned document or a human-signed
                approval.

    INFERRED  — Patterns mined from telemetry / observed behaviour. The
                "dream" pipeline produces these. Confidence reflects how
                often the pattern was observed and how recently it was
                confirmed; it decays without reinforcement.

    ELICITED  — Tribal knowledge surfaced by an expert in response to a
                targeted question ("why does deploy always fail on
                Tuesdays?"). Confidence is high at write-time but the
                fact still expires unless a second expert reconfirms.

    AMBIENT   — Live state pulled at hydrate-time: feature flags, queue
                depth, on-call rotation. Always carries an ``expires_at``
                because it goes stale fast.

This file defines the enum only. Tracking machinery (decay, observation
counting, pruning) lives in Phase 3's confidence module so the typing
change here stays minimal and reversible.
"""

from __future__ import annotations

from enum import Enum


class ContextLayer(str, Enum):
    """Trust tier for a fact in a CtxPack.

    Inherits from ``str`` so values serialise cleanly into JSON and YAML
    without a custom encoder. Iteration order (RULES → INFERRED →
    ELICITED → AMBIENT) is the trust ordering used by tie-breaking in
    the hydrator.
    """

    RULES = "rules"
    INFERRED = "inferred"
    ELICITED = "elicited"
    AMBIENT = "ambient"
