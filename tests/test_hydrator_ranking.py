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


def test_morphological_variants_match():
    """VIOLATION: exact-token matching misses emission/emitting."""
    doc = _doc(("OTHER", COMMON),
               ("TARGET", "Emitting context is not evidence an agent benefited."))
    result = hydrate_by_query(doc, "gist emission proves the agent benefits",
                              max_sections=1)
    assert [s.name for s in result.sections] == ["TARGET"]


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
