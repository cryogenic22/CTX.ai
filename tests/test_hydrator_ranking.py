"""Ranking quality guards for hydrate_by_query.

Forward guards. Before IDF weighting, hydrate_by_query scored a section by raw
term overlap, so a section matching "the" outranked one matching "telemetry".
The existing tests in test_hydrator.py assert membership only and cannot fail
on ranking order, so these feed a violation and require rejection.
"""
from __future__ import annotations

from ctxpack.core.hydrator import hydrate_by_query
from ctxpack.core.model import CTXDocument, Header, Layer, PlainLine, Section


def _doc(*sections: tuple[str, str]) -> CTXDocument:
    return CTXDocument(
        Header("§CTX", "1.0", Layer.L2),
        tuple(Section(name, children=(PlainLine(text),)) for name, text in sections),
    )


COMMON = "the report and the value of the run with the result"


def test_a_distinctive_term_outranks_a_common_one():
    """VIOLATION: raw overlap ranks the stopword match first."""
    doc = _doc(
        ("COMMON-A", COMMON),
        ("COMMON-B", COMMON + " only"),
        ("RARE", "Delivery telemetry must not claim consumption."),
    )
    result = hydrate_by_query(doc, "the report of delivery telemetry", max_sections=1)
    assert [s.name for s in result.sections] == ["RARE"]


def test_rare_term_survives_a_crowded_field_at_k5():
    """VIOLATION: the relevant section is pushed out of the top 5 by stopwords."""
    doc = _doc(*[(f"NOISE-{i}", COMMON) for i in range(8)],
               ("SIGNAL", "Emitting context is not evidence of consumption."))
    result = hydrate_by_query(doc, "the report that emission proves consumption")
    assert "SIGNAL" in {s.name for s in result.sections}


def test_inflectional_variants_match():
    """VIOLATION: without stemming the query shares no term with any section.

    Isolated on purpose - "delivers"/"delivered" is the only overlap in the
    document, so this cannot pass on an unrelated shared word. An earlier
    version of this test claimed to cover "emission"/"emitting" but actually
    passed on "agent"/"benefit"; see test_derivational_pairs_are_not_claimed
    for what the stemmer genuinely does not do.
    """
    doc = _doc(("DECOY", "unrelated alpha beta gamma"),
               ("TARGET", "the system delivered every payload"))
    result = hydrate_by_query(doc, "delivers")
    assert [s.name for s in result.sections] == ["TARGET"]


def test_derivational_pairs_are_not_claimed():
    """Regression pin: the stemmer is inflectional only.

    Pins the limitation so no future change can quietly claim derivational
    coverage without a test that actually shows it.
    """
    from ctxpack.core.hydrator import _stem

    assert _stem("delivers") == _stem("delivered")
    assert _stem("emitting") == _stem("emitted")
    assert _stem("emission") != _stem("emitting")


def test_empty_query_still_returns_nothing():
    """Regression pin: R14 - an empty lexical query selects no sections."""
    result = hydrate_by_query(_doc(("A", COMMON)), "")
    assert result.sections == [] and result.tokens_injected == 0


def test_ties_still_preserve_input_section_order():
    """Regression pin: R15 - equal scores keep the document's section order."""
    doc = _doc(("FIRST", "shared distinctive telemetry"),
               ("SECOND", "shared distinctive telemetry"))
    result = hydrate_by_query(doc, "shared distinctive telemetry")
    assert [s.name for s in result.sections] == ["FIRST", "SECOND"]


def test_ranking_is_deterministic_across_calls():
    """Regression pin: repeated identical queries return identical order."""
    doc = _doc(("A", "alpha telemetry"), ("B", "beta consumption"),
               ("C", "gamma the report"))
    runs = {tuple(s.name for s in hydrate_by_query(doc, "telemetry consumption report").sections)
            for _ in range(5)}
    assert len(runs) == 1


def test_a_section_with_no_overlap_is_never_returned():
    """Regression pin: zero overlap must not be scored in."""
    doc = _doc(("MATCH", "telemetry"), ("NOMATCH", "entirely unrelated wording"))
    result = hydrate_by_query(doc, "telemetry")
    assert [s.name for s in result.sections] == ["MATCH"]
