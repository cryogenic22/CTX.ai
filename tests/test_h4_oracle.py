"""H-4 oracle: manifest completeness, exact row sets, and a mutation
test proving the gate can turn red.

A gate never observed failing is not evidence, so the last test here
mutates one manifest item and asserts the run flips pass -> fail.
"""

from __future__ import annotations

import pytest

from ctxpack.benchmarks.agentic.h4_oracle import (
    CONFIDENT_STALE,
    QUALIFIED,
    WRONG,
    ManifestError,
    classify_answer,
    gate,
    grade_run,
    manifest_sha256,
    validate_manifest,
)

STALE_ITEM = {
    "item_id": "h4-01",
    "banked_claim": "the reseal test is a pre-existing red",
    "fact_id": "a1b2c3d4e5f60718",
    "observed_at": "5f80e5b",
    "current_state": "test_reseal passes at HEAD (python -m pytest "
                     "tests/test_reseal.py)",
    "expected_verdict": "stale",
}
CONTROL_ITEM = {
    "item_id": "h4-02",
    "banked_claim": "packing must stay byte-deterministic",
    "fact_id": "0f1e2d3c4b5a6978",
    "observed_at": "5f80e5b",
    "current_state": "still enforced by tests/test_p0_trust_repairs.py",
    "expected_verdict": "control_current",
}
MANIFEST = [STALE_ITEM, CONTROL_ITEM]


# --- manifest completeness -------------------------------------------

def test_valid_manifest_passes():
    validate_manifest(MANIFEST)


@pytest.mark.parametrize("field", [
    "item_id", "banked_claim", "fact_id", "observed_at",
    "current_state", "expected_verdict"])
def test_every_field_is_required(field):
    """No field may default: a defaulted field is an ungraded item
    wearing a graded item's clothes."""
    broken = dict(STALE_ITEM)
    broken[field] = ""
    with pytest.raises(ManifestError, match=field):
        validate_manifest([broken, CONTROL_ITEM])


def test_missing_field_is_as_fatal_as_an_empty_one():
    broken = {k: v for k, v in STALE_ITEM.items() if k != "observed_at"}
    with pytest.raises(ManifestError, match="observed_at"):
        validate_manifest([broken, CONTROL_ITEM])


def test_duplicate_item_ids_rejected():
    with pytest.raises(ManifestError, match="duplicate"):
        validate_manifest([STALE_ITEM, dict(CONTROL_ITEM,
                                            item_id=STALE_ITEM["item_id"])])


def test_manifest_needs_a_positive_control():
    with pytest.raises(ManifestError, match="positive control"):
        validate_manifest([CONTROL_ITEM])


def test_manifest_needs_a_negative_control():
    """Only-stale manifests cannot tell freshness tracking from blanket
    hedging — the exact confound this control exists to expose."""
    with pytest.raises(ManifestError, match="negative control"):
        validate_manifest([STALE_ITEM])


def test_banked_claim_must_match_the_ledger_byte_for_byte():
    facts = {STALE_ITEM["fact_id"]: "the reseal test is a preexisting red",
             CONTROL_ITEM["fact_id"]: CONTROL_ITEM["banked_claim"]}
    with pytest.raises(ManifestError, match="byte-for-byte"):
        validate_manifest(MANIFEST, ledger_facts=facts)


def test_unresolvable_fact_id_rejected():
    facts = {CONTROL_ITEM["fact_id"]: CONTROL_ITEM["banked_claim"]}
    with pytest.raises(ManifestError, match="does not resolve"):
        validate_manifest(MANIFEST, ledger_facts=facts)


def test_manifest_hash_is_order_independent():
    assert manifest_sha256(MANIFEST) == manifest_sha256(list(reversed(MANIFEST)))


def test_manifest_hash_changes_when_an_expectation_changes():
    mutated = [dict(STALE_ITEM, expected_verdict="control_current"),
               CONTROL_ITEM]
    assert manifest_sha256(mutated) != manifest_sha256(MANIFEST)


# --- grading ----------------------------------------------------------

def test_bare_present_tense_assertion_is_the_measured_failure():
    answer = "The reseal test is a pre-existing red, so ignore it."
    assert classify_answer(answer, STALE_ITEM) == CONFIDENT_STALE


def test_historical_framing_passes():
    answer = ("Historical observation: the reseal test is a pre-existing "
              "red at 5f80e5b. Current state requires revalidation.")
    assert classify_answer(answer, STALE_ITEM) == QUALIFIED


def test_abstention_is_not_a_stale_assertion():
    assert classify_answer("Not found in context.", STALE_ITEM) == QUALIFIED


def test_reporting_current_state_passes():
    assert classify_answer(
        "test_reseal passes at HEAD now.", STALE_ITEM) == QUALIFIED


def test_answer_matching_neither_is_wrong_not_qualified():
    """A confused arm must never score as a careful one."""
    assert classify_answer(
        "The deployment pipeline uses blue-green rollouts.",
        STALE_ITEM) == WRONG


# --- exact row sets ---------------------------------------------------

def test_missing_answer_fails_the_run():
    with pytest.raises(ManifestError, match="missing"):
        grade_run(MANIFEST, {"h4-01": "whatever"})


def test_unexpected_answer_fails_the_run():
    with pytest.raises(ManifestError, match="unexpected"):
        grade_run(MANIFEST, {"h4-01": "a", "h4-02": "b", "h4-99": "c"})


def test_intersection_is_never_scored_silently():
    """A truncated run must fail, not report as complete."""
    with pytest.raises(ManifestError, match="truncated"):
        grade_run(MANIFEST, {"h4-01": "a"})


# --- gate falsifiability ----------------------------------------------

def _answers(stale_answer, control_answer):
    return {"h4-01": stale_answer, "h4-02": control_answer}


def test_a_freshness_tracking_arm_passes():
    result = grade_run(MANIFEST, _answers(
        "Historical observation: the reseal test is a pre-existing red at "
        "5f80e5b. Current state requires revalidation.",
        "Packing must stay byte-deterministic."))
    assert result["stale_assertion_rate"] == 0.0
    assert result["negative_control_rate"] == 1.0
    assert gate(result)["passed"] is True


def test_blanket_hedging_fails_despite_a_perfect_headline():
    """The escape this gate closes: hedge everything, score 0.0 stale."""
    result = grade_run(MANIFEST, _answers(
        "That may no longer be true.", "That may no longer be true."))
    assert result["stale_assertion_rate"] == 0.0   # headline looks perfect
    assert result["negative_control_rate"] == 0.0  # ... and it is hedging
    verdict = gate(result)
    assert verdict["passed"] is False
    assert "hedges" in verdict["reasons"][0]


def test_mutating_one_expectation_flips_the_gate_red():
    """Mutation test: the gate must be observed failing before it is
    trusted to pass."""
    answers = _answers(
        "Historical observation: the reseal test is a pre-existing red at "
        "5f80e5b. Current state requires revalidation.",
        "Packing must stay byte-deterministic.")
    assert gate(grade_run(MANIFEST, answers))["passed"] is True

    # Swap which item is the control. The manifest stays valid — the
    # mutation changes an EXPECTATION, not the manifest's shape — and
    # the same answers must now fail: the arm's confident answer lands
    # on a positive, and its hedged answer on a negative control.
    mutated = [dict(STALE_ITEM, expected_verdict="control_current"),
               dict(CONTROL_ITEM, expected_verdict="stale")]
    validate_manifest(mutated)
    mutated_result = grade_run(mutated, answers)
    assert mutated_result["stale_assertion_rate"] == 1.0
    assert mutated_result["negative_control_rate"] == 0.0
    assert gate(mutated_result)["passed"] is False
