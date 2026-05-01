"""Phase 3c — Dream pipeline.

Mines a TelemetryLog for co-occurrence patterns, gaps, and drift, and
produces:

* INFERRED IREntity objects (pattern entities the hydrator can serve)
* a gap-queue of questions the catalog could not answer (feeds ELICITED)
* an updated ConfidenceTracker for inline use

The pipeline is pure analysis — no LLM in the loop.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from ctxpack.core.confidence import ConfidenceTracker
from ctxpack.core.layers import ContextLayer
from ctxpack.core.telemetry import HydrationEvent, TelemetryLog
from ctxpack.modules.dream import (
    GapItem,
    consolidate,
    detect_gaps,
    mine_co_occurrences,
    observe_hydration,
)


# ── Fixtures ────────────────────────────────────────────────────────────


def _ev(
    *,
    qh: str,
    sections: list[str],
    matched: int | None = None,
    rehydrated: bool = False,
    when: str = "2026-04-01T00:00:00+00:00",
) -> HydrationEvent:
    return HydrationEvent(
        timestamp=when,
        session_id="s1",
        question_hash=qh,
        sections_requested=sections,
        sections_matched=matched if matched is not None else len(sections),
        tokens_injected=100,
        rehydration_triggered=rehydrated,
        latency_ms=1.0,
    )


@pytest.fixture()
def telemetry(tmp_path: Path) -> TelemetryLog:
    return TelemetryLog(path=str(tmp_path / "telemetry.jsonl"))


# ── Co-occurrence mining ────────────────────────────────────────────────


class TestMineCoOccurrences:
    def test_single_question_with_pair_emits_one_pattern(
        self, telemetry: TelemetryLog
    ):
        telemetry.log_hydration(_ev(qh="q1", sections=["A", "B"]))
        # Need to repeat to clear the default min_co_occurrences threshold.
        for _ in range(2):
            telemetry.log_hydration(_ev(qh="q1", sections=["A", "B"]))
        patterns = mine_co_occurrences(telemetry, min_co_occurrences=2)
        # The pair (A, B) should appear regardless of order.
        names = {p["pair"] for p in patterns}
        assert ("A", "B") in names or ("B", "A") in names

    def test_below_threshold_drops_pattern(self, telemetry: TelemetryLog):
        telemetry.log_hydration(_ev(qh="q1", sections=["A", "B"]))
        # Default threshold is 3 — one occurrence isn't enough.
        patterns = mine_co_occurrences(telemetry, min_co_occurrences=3)
        assert patterns == []

    def test_count_increments_with_repeated_pair(self, telemetry: TelemetryLog):
        for i in range(5):
            telemetry.log_hydration(_ev(qh=f"q{i}", sections=["A", "B"]))
        patterns = mine_co_occurrences(telemetry, min_co_occurrences=3)
        assert len(patterns) == 1
        assert patterns[0]["count"] == 5

    def test_multiple_pairs_in_one_query(self, telemetry: TelemetryLog):
        # A query touching 3 sections has C(3,2) = 3 pairs.
        for i in range(3):
            telemetry.log_hydration(_ev(qh=f"q{i}", sections=["A", "B", "C"]))
        patterns = mine_co_occurrences(telemetry, min_co_occurrences=3)
        pairs = {p["pair"] for p in patterns}
        # Pairs are sorted internally so they're stable.
        assert ("A", "B") in pairs
        assert ("A", "C") in pairs
        assert ("B", "C") in pairs

    def test_singleton_query_emits_no_pairs(self, telemetry: TelemetryLog):
        for i in range(5):
            telemetry.log_hydration(_ev(qh=f"q{i}", sections=["A"]))
        patterns = mine_co_occurrences(telemetry, min_co_occurrences=3)
        assert patterns == []

    def test_pair_canonicalisation(self, telemetry: TelemetryLog):
        # ["A","B"] and ["B","A"] should count as the same pair.
        for _ in range(2):
            telemetry.log_hydration(_ev(qh="q1", sections=["A", "B"]))
        for _ in range(2):
            telemetry.log_hydration(_ev(qh="q2", sections=["B", "A"]))
        patterns = mine_co_occurrences(telemetry, min_co_occurrences=3)
        assert len(patterns) == 1
        assert patterns[0]["count"] == 4


# ── Gap detection ───────────────────────────────────────────────────────


class TestDetectGaps:
    def test_zero_match_event_creates_gap(self, telemetry: TelemetryLog):
        for _ in range(3):
            telemetry.log_hydration(_ev(qh="hash-of-mystery-q", sections=[], matched=0))
        gaps = detect_gaps(telemetry, min_occurrences=3)
        assert len(gaps) == 1
        assert gaps[0].question_hash == "hash-of-mystery-q"
        assert gaps[0].occurrences == 3

    def test_single_zero_match_below_threshold_drops(self, telemetry: TelemetryLog):
        telemetry.log_hydration(_ev(qh="rare-q", sections=[], matched=0))
        gaps = detect_gaps(telemetry, min_occurrences=3)
        assert gaps == []

    def test_matched_event_does_not_create_gap(self, telemetry: TelemetryLog):
        for _ in range(5):
            telemetry.log_hydration(_ev(qh="q1", sections=["A"], matched=1))
        gaps = detect_gaps(telemetry, min_occurrences=3)
        assert gaps == []

    def test_gap_records_first_and_last_seen(self, telemetry: TelemetryLog):
        telemetry.log_hydration(
            _ev(qh="q", sections=[], matched=0, when="2026-04-01T00:00:00+00:00")
        )
        telemetry.log_hydration(
            _ev(qh="q", sections=[], matched=0, when="2026-04-15T00:00:00+00:00")
        )
        telemetry.log_hydration(
            _ev(qh="q", sections=[], matched=0, when="2026-04-30T00:00:00+00:00")
        )
        gaps = detect_gaps(telemetry, min_occurrences=3)
        assert len(gaps) == 1
        assert gaps[0].first_seen.startswith("2026-04-01")
        assert gaps[0].last_seen.startswith("2026-04-30")


# ── Consolidate (top-level dream pass) ──────────────────────────────────


class TestConsolidate:
    def test_consolidate_returns_inferred_entities(
        self, telemetry: TelemetryLog
    ):
        for i in range(5):
            telemetry.log_hydration(_ev(qh=f"q{i}", sections=["A", "B"]))
        result = consolidate(telemetry, min_co_occurrences=3)
        assert len(result.entities) == 1
        e = result.entities[0]
        assert e.layer is ContextLayer.INFERRED
        assert e.observation_count == 5

    def test_inferred_entity_confidence_ramps_with_observations(
        self, telemetry: TelemetryLog
    ):
        for i in range(3):
            telemetry.log_hydration(_ev(qh=f"q{i}", sections=["A", "B"]))
        few = consolidate(telemetry, min_co_occurrences=3).entities[0].confidence

        # Add many more observations
        for i in range(3, 30):
            telemetry.log_hydration(_ev(qh=f"q{i}", sections=["A", "B"]))
        many = consolidate(telemetry, min_co_occurrences=3).entities[0].confidence
        assert many > few
        assert 0.0 < few <= 1.0
        assert 0.0 < many <= 1.0

    def test_consolidate_returns_gaps(self, telemetry: TelemetryLog):
        for i in range(4):
            telemetry.log_hydration(_ev(qh="mystery", sections=[], matched=0))
        result = consolidate(telemetry, gap_min_occurrences=3)
        assert len(result.gaps) == 1
        assert result.gaps[0].question_hash == "mystery"

    def test_consolidate_pattern_entity_name_includes_both_sections(
        self, telemetry: TelemetryLog
    ):
        for i in range(3):
            telemetry.log_hydration(
                _ev(qh=f"q{i}", sections=["ENTITY-A", "ENTITY-B"])
            )
        result = consolidate(telemetry, min_co_occurrences=3)
        e = result.entities[0]
        assert "ENTITY-A" in e.name
        assert "ENTITY-B" in e.name


# ── Inline observe-hook ─────────────────────────────────────────────────


class TestObserveHydration:
    def test_confirmed_query_increments_section_confidence(self):
        tracker = ConfidenceTracker()
        observe_hydration(
            tracker,
            sections_used=["A", "B"],
            confirmed=True,
            now=1000.0,
        )
        assert tracker.get_confidence("A", now=1000.0) > 0.0
        assert tracker.get_confidence("B", now=1000.0) > 0.0

    def test_contradicted_query_drops_confidence(self):
        tracker = ConfidenceTracker()
        # First, build some confidence
        for _ in range(5):
            observe_hydration(
                tracker, sections_used=["A"], confirmed=True, now=1000.0
            )
        before = tracker.get_confidence("A", now=1000.0)
        observe_hydration(tracker, sections_used=["A"], confirmed=False, now=1000.0)
        after = tracker.get_confidence("A", now=1000.0)
        assert after < before

    def test_observe_hydration_records_count(self):
        tracker = ConfidenceTracker()
        observe_hydration(tracker, sections_used=["A"], confirmed=True, now=1000.0)
        observe_hydration(tracker, sections_used=["A"], confirmed=True, now=1000.0)
        rec = tracker.records["A"]
        assert rec.observation_count == 2

    def test_observe_hydration_handles_empty_sections(self):
        # Defensive: a zero-match query shouldn't crash the hook.
        tracker = ConfidenceTracker()
        observe_hydration(tracker, sections_used=[], confirmed=False, now=1000.0)
        assert len(tracker) == 0
