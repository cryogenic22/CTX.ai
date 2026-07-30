"""Canonical state algebra: fact lifecycle vs evidence freshness.

Two axes that must never be conflated, plus one delivery axis that must
never be read as evidence of use. Definitions only — nothing in this
module reads the repository, produces states, or changes any rendered
output. Track C implementation stays gated on E-6, the deterministic
spike and the calibration run; this file exists so the vocabulary is
frozen *before* renderers are repaired against it.

Why this file exists: the Track C draft carried three overlapping
vocabularies (a two-axis table, a ``not_applicable`` kind mapping, and a
six-state enum) plus a fourth recipe-status enum. Any of them is
defensible; having four is how a memory system starts describing the
same fact two ways in two places.

Independence is the load-bearing property. A fact's lifecycle is
governed by markers and the supersession DAG. Its evidence freshness is
governed by re-verification against repository state. Neither derives
from the other: a ``banked`` fact whose test has not been re-run is
``not_checked``, and a ``superseded`` fact can still be ``current``
about the revision it described. Collapsing the axes is what let the
OntoWiz incident happen — a perfectly-preserved claim served as though
it were a present-tense truth.
"""

from __future__ import annotations

from enum import Enum

STATES_SCHEMA = "ctx-states/v1"


class Lifecycle(str, Enum):
    """What the ledger asserts about a fact's standing.

    Derived from marker statements and the supersession DAG **only**.
    Repository state never moves a fact along this axis.

    ``expired`` is deliberately absent. An earlier draft listed it here,
    but "the supporting evidence has aged out" is a statement about
    evidence, not about the fact's standing in the ledger — it belongs
    to :class:`Freshness`. Keeping it on this axis was the two-axis
    confusion in miniature.
    """

    DRAFT = "draft"            # extracted in a fold, not yet checkpointed
    BANKED = "banked"          # in the ledger, standing
    SUPERSEDED = "superseded"  # a later fact replaced it (DAG edge)
    RETRACTED = "retracted"    # explicitly withdrawn


class Freshness(str, Enum):
    """Whether repository evidence still supports the fact.

    Derived from verification against current repository state **only**.
    Marker statements never move a fact along this axis.
    """

    NOT_APPLICABLE = "not_applicable"  # kind carries no verifiable support
    UNANCHORED = "unanchored"          # eligible, but no recipe attached
    NOT_CHECKED = "not_checked"        # recipe attached, not evaluated at HEAD
    CURRENT = "current"                # evaluated at HEAD, matches
    STALE = "stale"                    # evaluated at HEAD, does not match
    INVALID = "invalid"                # recipe no longer evaluable


class Delivery(str, Enum):
    """Outcome of handing context to a model. NOT a usage signal.

    Every member describes what the harness *emitted*. None of them —
    ``INJECTED`` least of all — is evidence that the model read the
    bytes, relied on them, or benefited from them. Telemetry built on
    this enum may report delivery rates and must not report consumption,
    use, or value. See :func:`describes_use`.
    """

    ATTEMPTED = "attempted"
    INJECTED = "injected"
    EMPTY = "empty"
    FAILED = "failed"


def describes_use(_outcome: Delivery) -> bool:
    """Always ``False`` — delivery is not use.

    Exists as an executable statement of the non-inference rule rather
    than a comment someone can drift away from. A test asserts it holds
    for every member, so a future member cannot quietly claim otherwise.
    """
    return False


# Lifecycle is forward-only. A ledger never un-retracts and never
# un-supersedes: correcting the record means banking a NEW fact that
# supersedes the wrong one, which is what keeps history auditable.
LIFECYCLE_TRANSITIONS: dict[Lifecycle, frozenset[Lifecycle]] = {
    Lifecycle.DRAFT: frozenset({Lifecycle.BANKED}),
    Lifecycle.BANKED: frozenset({Lifecycle.SUPERSEDED, Lifecycle.RETRACTED}),
    Lifecycle.SUPERSEDED: frozenset({Lifecycle.RETRACTED}),
    Lifecycle.RETRACTED: frozenset(),
}

# Freshness is re-entrant: HEAD moves, so a fact can go current -> stale
# -> current without anything about the fact changing. The one hard rule
# is that NOT_APPLICABLE is isolated in both directions — it is a
# property of the fact's kind, and kinds do not change under
# verification.
_EVIDENCE_BEARING = frozenset(
    {
        Freshness.UNANCHORED,
        Freshness.NOT_CHECKED,
        Freshness.CURRENT,
        Freshness.STALE,
        Freshness.INVALID,
    }
)

FRESHNESS_TRANSITIONS: dict[Freshness, frozenset[Freshness]] = {
    Freshness.NOT_APPLICABLE: frozenset(),
    **{s: _EVIDENCE_BEARING - {s} for s in _EVIDENCE_BEARING},
}

# Worst-first. A fact with several recipes reports its worst result so a
# later healthy observation can never conceal an unhealthy one. STALE
# outranks INVALID because "the evidence contradicts this" is both more
# certain and more actionable than "the evidence could not be read".
_SEVERITY: dict[Freshness, int] = {
    Freshness.STALE: 5,
    Freshness.INVALID: 4,
    Freshness.NOT_CHECKED: 3,
    Freshness.UNANCHORED: 2,
    Freshness.CURRENT: 1,
    Freshness.NOT_APPLICABLE: 0,
}

# Rendered vocabulary. Six internal states carry cause; three rendered
# labels carry what the reader should do about it. UNVERIFIED covers
# four distinct causes that differ in diagnosis, not in action.
RENDERED_VERIFIED = "VERIFIED"
RENDERED_STALE = "STALE"
RENDERED_UNVERIFIED = "UNVERIFIED"

_RENDER: dict[Freshness, str] = {
    Freshness.CURRENT: RENDERED_VERIFIED,
    Freshness.STALE: RENDERED_STALE,
    Freshness.INVALID: RENDERED_UNVERIFIED,
    Freshness.NOT_CHECKED: RENDERED_UNVERIFIED,
    Freshness.UNANCHORED: RENDERED_UNVERIFIED,
    Freshness.NOT_APPLICABLE: RENDERED_UNVERIFIED,
}


def lifecycle_can_move(src: Lifecycle, dst: Lifecycle) -> bool:
    """Whether ``src -> dst`` is a legal lifecycle transition."""
    return dst in LIFECYCLE_TRANSITIONS[src]


def freshness_can_move(src: Freshness, dst: Freshness) -> bool:
    """Whether ``src -> dst`` is a legal freshness transition."""
    return dst in FRESHNESS_TRANSITIONS[src]


def worst(states) -> Freshness:
    """Fold several recipe results into the one a fact reports.

    Raises ``ValueError`` on an empty sequence: a fact with no recipe
    results is :attr:`Freshness.UNANCHORED` or
    :attr:`Freshness.NOT_APPLICABLE`, and which one it is depends on the
    fact's kind — not something this function may guess.
    """
    ranked = sorted(states, key=lambda s: (-_SEVERITY[s], s.value))
    if not ranked:
        raise ValueError("worst() needs at least one state; see docstring")
    return Freshness(ranked[0])


def render(freshness: Freshness) -> str:
    """Collapse an internal state to the three-label rendered vocabulary."""
    return _RENDER[freshness]


def render_claim(claim: str, freshness: Freshness,
                 observed_at: str | None = None) -> str:
    """Phrase a claim so only verified evidence gets the present tense.

    The owner-ratified rule from the OntoWiz stale-test incident: render
    *"Historical observation: <claim> at <revision>. Current state
    requires revalidation."* and never *"<claim>"* as a bare present-tense
    assertion. The historical observation survives even after a newer
    contradicting result — the ledger annotates, it never rewrites.

    Nothing calls this yet, by design: Track C rendering is gated. It is
    defined and tested here so the gate opens onto a settled rule.
    """
    if freshness is Freshness.CURRENT:
        return claim
    where = f" at {observed_at}" if observed_at else ""
    return (f"Historical observation: {claim}{where}. "
            f"Current state requires revalidation.")
