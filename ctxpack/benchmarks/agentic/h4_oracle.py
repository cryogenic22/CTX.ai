"""H-4 stale-claim oracle — manifest validation and exact grading.

H-4 asks whether an arm asserts a banked claim that has since become
false. Unlike H-1..H-3 that question cannot be answered from the ledger
alone: it needs a second source of truth (the repository at two
revisions), so the resume-probe generator cannot instantiate it. This
module is that missing oracle.

Protocol: ``PREREGISTRATION-flatfile-arm.md``, section "H-4 oracle
manifest — h4-oracle/v1". Everything here is deterministic and offline —
no LLM judge, no network, stdlib only. Nothing in this module executes a
scored run; it validates a manifest and grades answers already
collected.

**Grading reads a structured verdict, never prose.** v1 scanned the
answer text for qualifier phrases and claim substrings, which was not
trustworthy in two ways a review caught before any run: a qualifier
*anywhere* passed the whole answer, so "Historical observation ... but X
is true now" scored as careful; and substring matching ignored polarity,
so "it is false that X" scored as asserting X. Both are unfixable by
adding phrases — the grader was doing shallow NLP on adversarial text.
v2 requires each answer to carry a ``VERDICT:`` line and grades that
token alone. An answer without one is a protocol failure, disclosed and
gate-failing, never silently graded.

Three design rules carry the weight:

1. **Exact row sets.** Grading an intersection of what was asked and
   what came back lets a truncated run report as a complete one. Any
   difference in either direction is a hard failure.
2. **Ledger-backed validation is mandatory.** Grading is only meaningful
   against text that was actually banked, so the entry point requires
   the ledger facts rather than accepting a default.
3. **Both control classes.** A manifest of only-stale items cannot tell
   an arm that tracks freshness from one that hedges everything, so
   negative controls are mandatory and permitted control errors are an
   exact count (zero by default), not a guessed rate.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "h4-oracle/v1"
GRADER_VERSION = "h4-grader/v2"

REQUIRED_FIELDS = ("item_id", "banked_claim", "fact_id", "observed_at",
                   "current_state", "expected_verdict")

VERDICT_STALE = "stale"                      # positive control
VERDICT_CONTROL_CURRENT = "control_current"  # negative control
VERDICTS = (VERDICT_STALE, VERDICT_CONTROL_CURRENT)

# The answer vocabulary an arm must use. Frozen: adding a token changes
# what is measured, so it changes GRADER_ID and requires an amendment.
ANSWER_HOLDS = "holds"        # the banked claim is true of the repo now
ANSWER_STALE = "stale"        # it was true then, not now
ANSWER_UNKNOWN = "unknown"    # cannot tell from context
ANSWER_TOKENS = (ANSWER_HOLDS, ANSWER_STALE, ANSWER_UNKNOWN)
UNPARSEABLE = "unparseable"   # no verdict line — a protocol failure

# Anchored at line start so a verdict quoted mid-prose ("do not answer
# VERDICT: holds") cannot be mistaken for the answer's own verdict.
_VERDICT_RE = re.compile(
    r"^[\s>*_-]*verdict[\s*_]*:[\s*_]*(" + "|".join(ANSWER_TOKENS) + r")\b",
    re.IGNORECASE | re.MULTILINE,
)


def grader_id() -> str:
    """Stable hash of everything that determines a grade.

    Stamped in every result file. If this changes, results from before
    the change are not comparable to results after it — which is the
    point of stamping it rather than trusting a version string.
    """
    frozen = json.dumps({
        "grader": GRADER_VERSION,
        "answer_tokens": list(ANSWER_TOKENS),
        "verdict_pattern": _VERDICT_RE.pattern,
        "required_fields": list(REQUIRED_FIELDS),
        "expected_verdicts": list(VERDICTS),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(frozen.encode("utf-8")).hexdigest()[:16]


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


def validate_shape(items: "list[dict]") -> None:
    """Structural checks only. NOT sufficient to grade against.

    Public so manifest authoring can be checked before the ledger is
    available, but :func:`grade_run` deliberately does not call it —
    grading requires :func:`validate_manifest` with the ledger.
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

    verdicts = {str(i["expected_verdict"]) for i in items}
    if VERDICT_STALE not in verdicts:
        raise ManifestError("no positive control: an arm that never "
                            "qualifies would pass")
    if VERDICT_CONTROL_CURRENT not in verdicts:
        raise ManifestError("no negative control: an arm that hedges "
                            "everything would pass")


def validate_manifest(items: "list[dict]", ledger_facts: dict) -> None:
    """Shape plus ledger binding. ``ledger_facts`` is REQUIRED.

    Maps fact_id -> banked text. Every item must resolve and its
    ``banked_claim`` must match byte-for-byte: a paraphrased claim grades
    an arm against text nobody banked. An earlier version defaulted this
    to ``None`` and the grading entry point never passed it, so the
    advertised checks never ran — an optional integrity check is not an
    integrity check.
    """
    validate_shape(items)
    if ledger_facts is None:
        raise ManifestError(
            "ledger_facts is required: grading against unbound claims "
            "would score arms on text nobody banked")
    for item in items:
        item_id, fact_id = str(item["item_id"]), str(item["fact_id"])
        if fact_id not in ledger_facts:
            raise ManifestError(
                f"item {item_id!r}: fact_id {fact_id!r} does not resolve "
                f"in the ledger")
        if ledger_facts[fact_id] != item["banked_claim"]:
            raise ManifestError(
                f"item {item_id!r}: banked_claim does not match the "
                f"ledger text byte-for-byte")


def parse_verdict(answer: str) -> str:
    """Extract the answer's verdict token, or ``UNPARSEABLE``.

    First line-anchored match wins. No prose inspection: polarity,
    clause scope and hedging are the arm's problem to express in the
    token, not the grader's to infer.
    """
    match = _VERDICT_RE.search(answer or "")
    return match.group(1).lower() if match else UNPARSEABLE


def grade_run(items: "list[dict]", answers: "dict[str, str]",
              ledger_facts: dict) -> dict[str, Any]:
    """Grade a full arm. Exact row sets, ledger-backed, no prose rules.

    Raises :class:`ManifestError` when the answered item_ids differ from
    the manifest's in any direction. Duplicates cannot reach here (dict
    keys), so the collector must reject them upstream; missing and
    unexpected ids are caught here.
    """
    validate_manifest(items, ledger_facts)
    expected = {str(i["item_id"]) for i in items}
    got = {str(k) for k in answers}
    missing, unexpected = sorted(expected - got), sorted(got - expected)
    if missing or unexpected:
        raise ManifestError(
            f"row-set mismatch — missing={missing} unexpected={unexpected}; "
            f"scoring the intersection would report a truncated run as "
            f"complete")

    verdicts = {str(i["item_id"]): parse_verdict(answers[str(i["item_id"])])
                for i in items}

    positives = [str(i["item_id"]) for i in items
                 if i["expected_verdict"] == VERDICT_STALE]
    negatives = [str(i["item_id"]) for i in items
                 if i["expected_verdict"] == VERDICT_CONTROL_CURRENT]
    # Denominator is stale-positive items ONLY. A claim that is still
    # true cannot be "confidently asserted stale", so pooling controls
    # into this rate would let a bigger control set flatter the headline.
    # The negative controls have their own rate; the two never merge.
    confident = sum(1 for k in positives if verdicts[k] == ANSWER_HOLDS)
    control_ok = sum(1 for k in negatives if verdicts[k] == ANSWER_HOLDS)
    control_errors = [k for k in negatives if verdicts[k] != ANSWER_HOLDS]
    unparseable = sorted(k for k, v in verdicts.items() if v == UNPARSEABLE)
    return {
        "schema": SCHEMA,
        "grader_id": grader_id(),
        "manifest_sha256": manifest_sha256(items),
        "graded": len(items),
        "verdicts": verdicts,
        "stale_assertion_rate": (round(confident / len(positives), 3)
                                 if positives else None),
        "stale_positives": len(positives),
        "negative_control_rate": (round(control_ok / len(negatives), 3)
                                  if negatives else None),
        "control_errors": sorted(control_errors),
        "unparseable": unparseable,
    }


def gate(result: dict, baseline: dict = None,
         max_control_errors: int = 0,
         max_unparseable: int = 0) -> dict[str, Any]:
    """Pass/fail for one arm, with the hedging escape closed.

    Permitted errors are exact COUNTS, not rates. On a manifest this
    small a rate threshold is a guess dressed as a criterion — an
    earlier version used 0.8, which was never derived from anything.
    Zero is the default because a deterministic oracle has no noise to
    absorb; a nonzero allowance must be pre-registered with its
    justification.
    """
    reasons: "list[str]" = []
    bad = list(result.get("unparseable") or [])
    if len(bad) > max_unparseable:
        reasons.append(
            f"{len(bad)} answers carried no VERDICT line "
            f"(max {max_unparseable}): {bad[:5]}")
    errors = list(result.get("control_errors") or [])
    if len(errors) > max_control_errors:
        reasons.append(
            f"{len(errors)} negative-control errors (max "
            f"{max_control_errors}): the arm hedges or falsely marks "
            f"stale claims that are still true: {errors[:5]}")
    if baseline is not None:
        here = result.get("stale_assertion_rate")
        there = baseline.get("stale_assertion_rate")
        if here is not None and there is not None and here > there:
            reasons.append(
                f"stale_assertion_rate regressed {there} -> {here}")
    return {"passed": not reasons, "reasons": reasons}
