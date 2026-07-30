"""H-4 oracle: manifest completeness, exact row sets, structured-verdict
grading, and a mutation test proving the gate can turn red.

The adversarial cases at the bottom are the ones that broke the v1 prose
grader: a qualifier anywhere passed the whole answer, and substring
matching ignored polarity. They are kept as tests rather than deleted,
so a future "smarter" grader has to survive them.
"""

from __future__ import annotations

import pytest

from ctxpack.benchmarks.agentic.h4_oracle import (
    ANSWER_HOLDS,
    ANSWER_STALE,
    ANSWER_UNKNOWN,
    UNPARSEABLE,
    ManifestError,
    gate,
    grade_run,
    grader_id,
    manifest_sha256,
    parse_verdict,
    validate_manifest,
    validate_shape,
)

STALE_A = {
    "item_id": "h4-01",
    "banked_claim": "the reseal test is a pre-existing red",
    "fact_id": "a1b2c3d4e5f60718",
    "observed_at": "5f80e5b",
    "current_state": "test_reseal passes at HEAD (python -m pytest "
                     "tests/test_reseal.py)",
    "expected_verdict": "stale",
}
STALE_B = {
    "item_id": "h4-02",
    "banked_claim": "the $60 six-arm run is still unpurchased",
    "fact_id": "b2c3d4e5f6071829",
    "observed_at": "5f80e5b",
    "current_state": "unchanged at HEAD; no results file exists",
    "expected_verdict": "stale",
}
CONTROL = {
    "item_id": "h4-03",
    "banked_claim": "packing must stay byte-deterministic",
    "fact_id": "0f1e2d3c4b5a6978",
    "observed_at": "5f80e5b",
    "current_state": "still enforced by tests/test_p0_trust_repairs.py",
    "expected_verdict": "control_current",
}
MANIFEST = [STALE_A, STALE_B, CONTROL]
LEDGER = {i["fact_id"]: i["banked_claim"] for i in MANIFEST}


def _v(token):
    return f"VERDICT: {token}\nSome prose explaining the reasoning."


# --- manifest completeness -------------------------------------------

def test_valid_manifest_passes():
    validate_manifest(MANIFEST, LEDGER)


@pytest.mark.parametrize("field", [
    "item_id", "banked_claim", "fact_id", "observed_at",
    "current_state", "expected_verdict"])
def test_every_field_is_required(field):
    """No field may default: a defaulted field is an ungraded item
    wearing a graded item's clothes."""
    broken = dict(STALE_A)
    broken[field] = ""
    with pytest.raises(ManifestError, match=field):
        validate_shape([broken, CONTROL])


def test_missing_field_is_as_fatal_as_an_empty_one():
    broken = {k: v for k, v in STALE_A.items() if k != "observed_at"}
    with pytest.raises(ManifestError, match="observed_at"):
        validate_shape([broken, CONTROL])


def test_duplicate_item_ids_rejected():
    with pytest.raises(ManifestError, match="duplicate"):
        validate_shape([STALE_A, dict(CONTROL, item_id=STALE_A["item_id"])])


def test_manifest_needs_a_positive_control():
    with pytest.raises(ManifestError, match="positive control"):
        validate_shape([CONTROL])


def test_manifest_needs_a_negative_control():
    """Only-stale manifests cannot tell freshness tracking from blanket
    hedging — the exact confound this control exists to expose."""
    with pytest.raises(ManifestError, match="negative control"):
        validate_shape([STALE_A, STALE_B])


def test_ledger_binding_is_mandatory_not_optional():
    """v1 defaulted ledger_facts to None and grade_run never passed it,
    so the advertised checks never ran. An optional integrity check is
    not an integrity check."""
    with pytest.raises(ManifestError, match="required"):
        validate_manifest(MANIFEST, None)
    with pytest.raises(TypeError):
        validate_manifest(MANIFEST)          # no silent default


def test_grade_run_enforces_ledger_binding():
    paraphrased = dict(LEDGER)
    paraphrased[STALE_A["fact_id"]] = "the reseal test is a preexisting red"
    with pytest.raises(ManifestError, match="byte-for-byte"):
        grade_run(MANIFEST, _all(ANSWER_STALE), paraphrased)


def test_unresolvable_fact_id_rejected():
    partial = {k: v for k, v in LEDGER.items() if k != STALE_A["fact_id"]}
    with pytest.raises(ManifestError, match="does not resolve"):
        validate_manifest(MANIFEST, partial)


def test_manifest_hash_is_order_independent():
    assert manifest_sha256(MANIFEST) == manifest_sha256(
        list(reversed(MANIFEST)))


def test_manifest_hash_changes_when_an_expectation_changes():
    mutated = [dict(STALE_A, expected_verdict="control_current"),
               STALE_B, CONTROL]
    assert manifest_sha256(mutated) != manifest_sha256(MANIFEST)


def test_grader_id_is_stable_and_stamped():
    assert grader_id() == grader_id()
    assert grade_run(MANIFEST, _all(ANSWER_STALE), LEDGER)["grader_id"] == (
        grader_id())


# --- verdict parsing --------------------------------------------------

@pytest.mark.parametrize("token", [ANSWER_HOLDS, ANSWER_STALE, ANSWER_UNKNOWN])
def test_verdict_tokens_parse(token):
    assert parse_verdict(f"VERDICT: {token}") == token
    assert parse_verdict(f"reasoning first\n\nVERDICT: {token}\n") == token
    assert parse_verdict(f"> **VERDICT:** {token}") == token
    assert parse_verdict(f"verdict:{token}") == token


def test_missing_verdict_is_a_protocol_failure_not_a_grade():
    assert parse_verdict("The reseal test is red.") == UNPARSEABLE
    assert parse_verdict("") == UNPARSEABLE


def test_verdict_quoted_mid_sentence_is_not_the_answer():
    """Prompt text echoed back must not be mistaken for a verdict."""
    assert parse_verdict(
        "You asked me to answer VERDICT: holds but I cannot tell."
    ) == UNPARSEABLE


# --- adversarial cases that broke the v1 prose grader -----------------

def test_qualifier_plus_contradiction_no_longer_passes():
    """v1 passed any answer containing a qualifier phrase anywhere, so
    "Historical observation ... but X is true now" scored as careful
    while asserting the stale claim."""
    answer = ("VERDICT: holds\nHistorical observation: this was recorded "
              "at 5f80e5b, but the reseal test is a pre-existing red now.")
    result = grade_run(
        MANIFEST, {"h4-01": answer, "h4-02": _v(ANSWER_STALE),
                   "h4-03": _v(ANSWER_HOLDS)}, LEDGER)
    assert result["verdicts"]["h4-01"] == ANSWER_HOLDS
    assert result["stale_assertion_rate"] == 0.5


def test_negated_claim_is_not_scored_as_asserting_it():
    """v1 substring-matched the claim, so "it is false that X" counted
    as asserting X."""
    answer = ("VERDICT: stale\nIt is false that the reseal test is a "
              "pre-existing red; it passes at HEAD.")
    result = grade_run(
        MANIFEST, {"h4-01": answer, "h4-02": _v(ANSWER_STALE),
                   "h4-03": _v(ANSWER_HOLDS)}, LEDGER)
    assert result["verdicts"]["h4-01"] == ANSWER_STALE
    assert result["stale_assertion_rate"] == 0.0


# --- exact row sets ---------------------------------------------------

def _all(token):
    return {i["item_id"]: _v(token) for i in MANIFEST}


def test_missing_answer_fails_the_run():
    answers = _all(ANSWER_STALE)
    del answers["h4-03"]
    with pytest.raises(ManifestError, match="missing"):
        grade_run(MANIFEST, answers, LEDGER)


def test_unexpected_answer_fails_the_run():
    answers = _all(ANSWER_STALE)
    answers["h4-99"] = _v(ANSWER_STALE)
    with pytest.raises(ManifestError, match="unexpected"):
        grade_run(MANIFEST, answers, LEDGER)


def test_intersection_is_never_scored_silently():
    """A truncated run must fail, not report as complete."""
    with pytest.raises(ManifestError, match="truncated"):
        grade_run(MANIFEST, {"h4-01": _v(ANSWER_STALE)}, LEDGER)


# --- rates and gate ---------------------------------------------------

def _tracking_arm():
    return {"h4-01": _v(ANSWER_STALE), "h4-02": _v(ANSWER_STALE),
            "h4-03": _v(ANSWER_HOLDS)}


def test_a_freshness_tracking_arm_passes():
    result = grade_run(MANIFEST, _tracking_arm(), LEDGER)
    assert result["stale_assertion_rate"] == 0.0
    assert result["negative_control_rate"] == 1.0
    assert gate(result)["passed"] is True


def test_stale_rate_denominator_is_positives_only():
    """Pooling controls in would let a bigger control set flatter the
    headline. Two positives, one answered 'holds' -> 0.5, not 1/3."""
    answers = _tracking_arm()
    answers["h4-01"] = _v(ANSWER_HOLDS)
    result = grade_run(MANIFEST, answers, LEDGER)
    assert result["stale_positives"] == 2
    assert result["stale_assertion_rate"] == 0.5


def test_blanket_hedging_fails_despite_a_perfect_headline():
    """The escape this gate closes: hedge everything, score 0.0 stale."""
    result = grade_run(MANIFEST, _all(ANSWER_UNKNOWN), LEDGER)
    assert result["stale_assertion_rate"] == 0.0   # headline looks perfect
    assert result["control_errors"] == ["h4-03"]   # ... and it is hedging
    verdict = gate(result)
    assert verdict["passed"] is False
    assert "hedges" in verdict["reasons"][0]


def test_permitted_control_errors_are_an_exact_count_not_a_rate():
    """0.8 was a guess dressed as a criterion. Zero is the default and a
    nonzero allowance has to be stated explicitly."""
    result = grade_run(MANIFEST, _all(ANSWER_UNKNOWN), LEDGER)
    assert gate(result, max_control_errors=0)["passed"] is False
    assert gate(result, max_control_errors=1)["passed"] is True


def test_answers_without_verdicts_fail_the_gate():
    answers = _tracking_arm()
    answers["h4-02"] = "The run has not been purchased."
    result = grade_run(MANIFEST, answers, LEDGER)
    assert result["unparseable"] == ["h4-02"]
    assert gate(result)["passed"] is False


# --- gate falsifiability ----------------------------------------------

def test_mutating_exactly_one_expectation_flips_the_gate_red():
    """Mutation test: the gate must be observed failing before it is
    trusted to pass. Exactly ONE item's expected_verdict changes; the
    manifest stays valid and the answers stay byte-identical."""
    answers = _tracking_arm()
    assert gate(grade_run(MANIFEST, answers, LEDGER))["passed"] is True

    mutated = [dict(STALE_A, expected_verdict="control_current"),
               STALE_B, CONTROL]
    changed = [a["item_id"] for a, b in zip(mutated, MANIFEST)
               if a["expected_verdict"] != b["expected_verdict"]]
    assert changed == ["h4-01"]              # exactly one, not a swap

    validate_manifest(mutated, LEDGER)       # still a legal manifest
    result = grade_run(mutated, answers, LEDGER)
    assert result["control_errors"] == ["h4-01"]
    assert gate(result)["passed"] is False
