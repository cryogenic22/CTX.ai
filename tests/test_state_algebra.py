"""Property tests for the canonical state algebra.

These lock the two invariants the Track C draft kept losing: the axes
are independent, and delivery is never use. They are property tests
rather than examples because the failure mode is a future member added
without updating a table — an example test passes right through that.
"""

from __future__ import annotations

import itertools

import pytest

from ctxpack.core.states import (
    FRESHNESS_TRANSITIONS,
    LIFECYCLE_TRANSITIONS,
    RENDERED_STALE,
    RENDERED_UNVERIFIED,
    RENDERED_VERIFIED,
    Delivery,
    Freshness,
    Lifecycle,
    describes_use,
    freshness_can_move,
    lifecycle_can_move,
    render,
    render_claim,
    worst,
)


# --- exhaustiveness: a new member cannot slip past the tables ---------

def test_every_state_has_a_transition_entry():
    assert set(LIFECYCLE_TRANSITIONS) == set(Lifecycle)
    assert set(FRESHNESS_TRANSITIONS) == set(Freshness)


def test_every_freshness_state_renders_and_ranks():
    for state in Freshness:
        assert render(state) in {
            RENDERED_VERIFIED, RENDERED_STALE, RENDERED_UNVERIFIED}
        assert worst([state]) is state       # exercises the severity table


def test_transition_targets_are_declared_states():
    for src, targets in LIFECYCLE_TRANSITIONS.items():
        assert targets <= set(Lifecycle), src
    for src, targets in FRESHNESS_TRANSITIONS.items():
        assert targets <= set(Freshness), src


# --- axis independence -----------------------------------------------

def test_the_two_axes_share_no_vocabulary():
    """A label must name exactly one axis, or 'current' means two things.

    The draft used 'current' for a lifecycle value AND the intended
    meaning of verified evidence. Whichever axis owns a word, the other
    may not reuse it.
    """
    assert {m.value for m in Lifecycle}.isdisjoint({m.value for m in Freshness})


def test_every_lifecycle_freshness_pair_is_legal():
    """Neither axis constrains the other — that is the whole point.

    Notably a BANKED fact may be STALE (the OntoWiz incident) and a
    SUPERSEDED fact may be CURRENT (still true of the revision it
    described).
    """
    pairs = list(itertools.product(Lifecycle, Freshness))
    assert len(pairs) == len(Lifecycle) * len(Freshness)
    assert (Lifecycle.BANKED, Freshness.STALE) in pairs
    assert (Lifecycle.SUPERSEDED, Freshness.CURRENT) in pairs


def test_not_applicable_is_isolated_in_both_directions():
    """Kind decides it, so verification can never move a fact in or out."""
    assert FRESHNESS_TRANSITIONS[Freshness.NOT_APPLICABLE] == frozenset()
    for src in Freshness:
        assert not freshness_can_move(src, Freshness.NOT_APPLICABLE)


def test_lifecycle_is_forward_only():
    """No path back to DRAFT or BANKED: you bank a new fact instead."""
    for src in Lifecycle:
        assert not lifecycle_can_move(src, Lifecycle.DRAFT)
        assert not lifecycle_can_move(src, src)
    assert not lifecycle_can_move(Lifecycle.RETRACTED, Lifecycle.BANKED)
    assert not lifecycle_can_move(Lifecycle.SUPERSEDED, Lifecycle.BANKED)
    assert LIFECYCLE_TRANSITIONS[Lifecycle.RETRACTED] == frozenset()


def test_freshness_is_re_entrant_because_head_moves():
    """current -> stale -> current with the fact itself unchanged."""
    assert freshness_can_move(Freshness.CURRENT, Freshness.STALE)
    assert freshness_can_move(Freshness.STALE, Freshness.CURRENT)
    assert freshness_can_move(Freshness.UNANCHORED, Freshness.NOT_CHECKED)


# --- worst(): deterministic, worst-first ------------------------------

@pytest.mark.parametrize("size", [1, 2, 3])
def test_worst_is_order_independent(size):
    """Packing is byte-deterministic, so the fold must not depend on
    recipe evaluation order."""
    for combo in itertools.combinations(list(Freshness), size):
        results = {worst(p) for p in itertools.permutations(combo)}
        assert len(results) == 1, combo


def test_worst_is_idempotent_and_absorbing():
    for state in Freshness:
        assert worst([state, state]) is state
    assert worst([Freshness.CURRENT, Freshness.CURRENT]) is Freshness.CURRENT


def test_a_healthy_observation_never_conceals_an_unhealthy_one():
    assert worst([Freshness.CURRENT, Freshness.STALE]) is Freshness.STALE
    assert worst([Freshness.CURRENT, Freshness.INVALID]) is Freshness.INVALID
    assert worst([Freshness.CURRENT, Freshness.NOT_CHECKED]) is (
        Freshness.NOT_CHECKED)


def test_stale_outranks_invalid():
    """'The evidence contradicts this' beats 'the evidence was unreadable':
    both block assertion, only one tells the reader what to do."""
    assert worst([Freshness.INVALID, Freshness.STALE]) is Freshness.STALE


def test_worst_of_nothing_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        worst([])


# --- rendering: only verified evidence gets the present tense ---------

def test_only_current_renders_verified():
    for state in Freshness:
        if state is Freshness.CURRENT:
            assert render(state) == RENDERED_VERIFIED
        else:
            assert render(state) != RENDERED_VERIFIED


def test_not_applicable_never_renders_as_verified():
    """A constraint carries no repository evidence; absence of evidence
    must not be rendered as verification."""
    assert render(Freshness.NOT_APPLICABLE) == RENDERED_UNVERIFIED


def test_only_current_gets_a_bare_present_tense_claim():
    claim = "test_reseal fails"
    assert render_claim(claim, Freshness.CURRENT) == claim
    for state in Freshness:
        if state is Freshness.CURRENT:
            continue
        rendered = render_claim(claim, state)
        assert rendered != claim
        assert "Historical observation" in rendered
        assert "requires revalidation" in rendered


def test_stale_claim_keeps_the_historical_observation():
    """The owner-ratified phrasing from the OntoWiz incident: annotate,
    never rewrite — the observation survives a newer passing result."""
    rendered = render_claim(
        "test_reseal failed", Freshness.STALE, observed_at="revision A")
    assert rendered == (
        "Historical observation: test_reseal failed at revision A. "
        "Current state requires revalidation.")
    assert "test_reseal failed" in rendered


# --- delivery is not use ----------------------------------------------

def test_no_delivery_outcome_describes_use():
    """Injection receipts prove bytes were emitted, never that a model
    read or benefited from them. Holds for every member, including any
    added later."""
    for outcome in Delivery:
        assert describes_use(outcome) is False


def test_delivery_vocabulary_avoids_usage_words():
    banned = {"used", "consumed", "read", "applied", "benefited"}
    for outcome in Delivery:
        assert outcome.value not in banned
