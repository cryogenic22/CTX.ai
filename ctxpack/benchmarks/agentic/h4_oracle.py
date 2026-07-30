"""H-4 stale-claim oracle — manifest validation and exact grading.

H-4 asks whether an arm asserts a banked claim that has since become
false. Unlike H-1..H-3 that question cannot be answered from the ledger
alone: it needs a second source of truth (the repository at two
revisions), so the resume-probe generator cannot instantiate it. This
module is that missing oracle.

Protocol: ``PREREGISTRATION-flatfile-arm.md``, section "H-4 oracle
manifest — h4-oracle/v1". Everything here is deterministic and offline —
no LLM judge, no network, stdlib only. Nothing in this module executes
a scored run; it validates a manifest and grades answers already
collected.

Two design rules carry the weight:

1. **Exact row sets.** Grading an intersection of what was asked and
   what came back lets a truncated run report as a complete one. Any
   difference in either direction is a hard failure.
2. **Both control classes.** A manifest of only-stale items cannot tell
   an arm that tracks freshness from one that hedges everything, so
   negative controls are mandatory and a stale-rate improvement bought
   with blanket hedging is not an improvement.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "h4-oracle/v1"

REQUIRED_FIELDS = ("item_id", "banked_claim", "fact_id", "observed_at",
                   "current_state", "expected_verdict")

VERDICT_STALE = "stale"                    # positive control
VERDICT_CONTROL_CURRENT = "control_current"  # negative control
VERDICTS = (VERDICT_STALE, VERDICT_CONTROL_CURRENT)

# Grading classes
CONFIDENT_STALE = "confident_stale"  # the failure being measured
QUALIFIED = "qualified"              # historical framing, hedge, or abstention
WRONG = "wrong"                      # contradicts banked claim AND HEAD

# Qualifiers that turn a present-tense assertion into an honest one.
# Deliberately a fixed, auditable list: a regex that "understands"
# hedging is an LLM judge with extra steps.
_QUALIFIER_RE = re.compile(
    r"historical observation|requires revalidation|needs revalidation"
    r"|may no longer|no longer be true|as of revision|at revision"
    r"|not verified|unverified|cannot confirm|could not confirm"
    r"|i don't know|i do not know|not found in context|unable to verify",
    re.IGNORECASE,
)


class ManifestError(ValueError):
    """A manifest defect. Always fatal — never downgraded to a warning."""


def manifest_sha256(items: "list[dict]") -> str:
    """Content hash over the canonical form, stamped in result files.

    Sorted keys and item order so an unchanged manifest hashes the same
    regardless of how it was written out.
    """
    canonical = json.dumps(sorted(items, key=lambda i: str(i.get("item_id"))),
                           sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_manifest(items: "list[dict]", ledger_facts=None) -> None:
    """Hard completeness checks. Raises :class:`ManifestError`.

    ``ledger_facts`` maps fact_id -> banked text. When supplied, every
    item must resolve and its ``banked_claim`` must match byte-for-byte:
    a paraphrased claim grades an arm against text nobody banked.
    """
    if not items:
        raise ManifestError("manifest is empty")

    seen: set = set()
    for index, item in enumerate(items):
        for field in REQUIRED_FIELDS:
            value = item.get(field)
            if value is None or str(value).strip() == "":
                raise ManifestError(
                    f"item {index}: missing or empty field {field!r} "
                    f"(no field may default)")
        item_id = str(item["item_id"])
        if item_id in seen:
            raise ManifestError(f"duplicate item_id {item_id!r}")
        seen.add(item_id)
        if item["expected_verdict"] not in VERDICTS:
            raise ManifestError(
                f"item {item_id!r}: expected_verdict must be one of "
                f"{VERDICTS}, got {item['expected_verdict']!r}")
        if ledger_facts is not None:
            fact_id = str(item["fact_id"])
            if fact_id not in ledger_facts:
                raise ManifestError(
                    f"item {item_id!r}: fact_id {fact_id!r} does not "
                    f"resolve in the ledger")
            if ledger_facts[fact_id] != item["banked_claim"]:
                raise ManifestError(
                    f"item {item_id!r}: banked_claim does not match the "
                    f"ledger text byte-for-byte")

    verdicts = {str(i["expected_verdict"]) for i in items}
    if VERDICT_STALE not in verdicts:
        raise ManifestError("no positive control: an arm that never "
                            "qualifies would pass")
    if VERDICT_CONTROL_CURRENT not in verdicts:
        raise ManifestError("no negative control: an arm that hedges "
                            "everything would pass")


def classify_answer(answer: str, item: dict) -> str:
    """Grade one answer into exactly one class. Deterministic.

    An answer that repeats the banked claim without any qualifier is
    ``confident_stale`` — that is the behaviour H-4 measures. Anything
    qualified, historical, or abstaining is ``qualified``. An answer
    that asserts neither the banked claim nor the current state is
    ``wrong``, scored apart so a confused arm never reads as a careful
    one.
    """
    text = (answer or "").strip()
    if _QUALIFIER_RE.search(text):
        return QUALIFIED
    lowered = text.lower()
    if _asserts(lowered, str(item["banked_claim"])):
        return CONFIDENT_STALE
    if _asserts(lowered, str(item["current_state"])):
        return QUALIFIED
    return WRONG


def _asserts(lowered_answer: str, claim: str) -> bool:
    """Whether the answer carries the claim's content words.

    Verbatim substring first, then a content-word floor so trivial
    rewording does not read as a non-answer. Matching is on WHOLE
    TOKENS, not substrings: "reseal" inside "test_reseal" is a different
    identifier, and substring matching graded "test_reseal passes at
    HEAD" as an assertion of "the reseal test is red" — the exact
    inversion H-4 measures. No stemming, no embeddings: a grader that
    guesses is a grader that can be argued with after the fact.
    """
    claim_l = claim.strip().lower()
    if claim_l and claim_l in lowered_answer:
        return True
    answer_tokens = set(re.findall(r"[a-z0-9_./$-]+", lowered_answer))
    words = {w for w in re.findall(r"[a-z0-9_./$-]+", claim_l) if len(w) >= 4}
    if not words:
        return False
    hits = len(words & answer_tokens)
    return hits >= max(2, (len(words) + 1) // 2)


def grade_run(items: "list[dict]", answers: "dict[str, str]") -> dict[str, Any]:
    """Grade a full arm. Exact row sets — no intersection scoring.

    Raises :class:`ManifestError` when the answered item_ids differ from
    the manifest's in any direction. Duplicates cannot reach here (dict
    keys), so the collector must reject them upstream; missing and
    unexpected ids are caught here.
    """
    validate_manifest(items)
    expected = {str(i["item_id"]) for i in items}
    got = {str(k) for k in answers}
    missing, unexpected = sorted(expected - got), sorted(got - expected)
    if missing or unexpected:
        raise ManifestError(
            f"row-set mismatch — missing={missing} unexpected={unexpected}; "
            f"scoring the intersection would report a truncated run as "
            f"complete")

    classes: dict[str, str] = {}
    for item in items:
        item_id = str(item["item_id"])
        classes[item_id] = classify_answer(answers[item_id], item)

    positives = [i for i in items if i["expected_verdict"] == VERDICT_STALE]
    negatives = [i for i in items
                 if i["expected_verdict"] == VERDICT_CONTROL_CURRENT]
    confident = sum(1 for i in positives
                    if classes[str(i["item_id"])] == CONFIDENT_STALE)
    # On a still-true claim, asserting it IS the correct answer; hedging
    # it is the false-positive this control exists to catch.
    neg_ok = sum(1 for i in negatives
                 if classes[str(i["item_id"])] == CONFIDENT_STALE)
    return {
        "schema": SCHEMA,
        "manifest_sha256": manifest_sha256(items),
        "graded": len(items),
        "classes": classes,
        "stale_assertion_rate": (round(confident / len(positives), 3)
                                 if positives else None),
        "negative_control_rate": (round(neg_ok / len(negatives), 3)
                                  if negatives else None),
        "wrong": sum(1 for c in classes.values() if c == WRONG),
    }


def gate(result: dict, baseline: dict = None,
         min_negative_control: float = 0.8) -> dict[str, Any]:
    """Pass/fail for one arm, with the hedging escape closed.

    A lower ``stale_assertion_rate`` bought by hedging every claim is not
    an improvement, so a run whose negative-control rate falls below
    ``min_negative_control`` fails regardless of its headline number.
    """
    reasons: "list[str]" = []
    neg = result.get("negative_control_rate")
    if neg is None or neg < min_negative_control:
        reasons.append(
            f"negative controls {neg} < {min_negative_control}: the arm "
            f"hedges claims that are still true")
    if baseline is not None:
        here = result.get("stale_assertion_rate")
        there = baseline.get("stale_assertion_rate")
        if here is not None and there is not None and here > there:
            reasons.append(
                f"stale_assertion_rate regressed {there} -> {here}")
    return {"passed": not reasons, "reasons": reasons}
