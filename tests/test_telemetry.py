"""Tests for telemetry module — append-only JSONL hydration event logging.

Written BEFORE implementation (TDD). These tests define the contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid

import pytest

from ctxpack.core.telemetry import HydrationEvent, TelemetryLog


# ── Helpers ──


def _make_event(**overrides) -> HydrationEvent:
    """Create a HydrationEvent with sensible defaults, overridable."""
    defaults = dict(
        timestamp="2026-03-15T12:00:00Z",
        session_id=str(uuid.uuid4()),
        question_hash=hashlib.sha256(b"test question").hexdigest(),
        sections_requested=["ENTITY-CUSTOMER"],
        sections_matched=1,
        tokens_injected=42,
        rehydration_triggered=False,
        latency_ms=3.5,
    )
    defaults.update(overrides)
    return HydrationEvent(**defaults)


# ── Tests ──


class TestLogCreatesFile:
    def test_log_creates_file(self, tmp_path):
        """Logging an event should create the JSONL file if it doesn't exist."""
        log_path = str(tmp_path / ".ctxpack" / "telemetry.jsonl")
        tlog = TelemetryLog(path=log_path)
        tlog.log_hydration(_make_event())
        assert os.path.isfile(log_path)


class TestLogAppendsJsonlFormat:
    def test_log_appends_jsonl_format(self, tmp_path):
        """Each log entry should be a single valid JSON line."""
        log_path = str(tmp_path / "telem.jsonl")
        tlog = TelemetryLog(path=log_path)
        tlog.log_hydration(_make_event())

        with open(log_path, encoding="utf-8") as f:
            lines = f.read().strip().split("\n")

        assert len(lines) == 1
        data = json.loads(lines[0])
        assert "timestamp" in data
        assert "session_id" in data
        assert "sections_requested" in data


class TestLogMultipleEvents:
    def test_log_multiple_events(self, tmp_path):
        """Multiple log_hydration calls should append, not overwrite."""
        log_path = str(tmp_path / "telem.jsonl")
        tlog = TelemetryLog(path=log_path)

        for i in range(5):
            tlog.log_hydration(_make_event(tokens_injected=i * 10))

        with open(log_path, encoding="utf-8") as f:
            lines = [l for l in f.read().strip().split("\n") if l]

        assert len(lines) == 5
        # Each line should be valid JSON
        for line in lines:
            data = json.loads(line)
            assert "tokens_injected" in data


class TestSummaryCountsHydrations:
    def test_summary_counts_hydrations(self, tmp_path):
        """summary().total_hydrations should equal number of logged events."""
        log_path = str(tmp_path / "telem.jsonl")
        tlog = TelemetryLog(path=log_path)

        for _ in range(7):
            tlog.log_hydration(_make_event())

        s = tlog.summary()
        assert s["total_hydrations"] == 7


class TestSummaryTopSections:
    def test_summary_top_sections(self, tmp_path):
        """top_sections should rank sections by access count."""
        log_path = str(tmp_path / "telem.jsonl")
        tlog = TelemetryLog(path=log_path)

        # Log ENTITY-CUSTOMER 5 times, ENTITY-ORDER 2 times
        for _ in range(5):
            tlog.log_hydration(_make_event(
                sections_requested=["ENTITY-CUSTOMER"],
            ))
        for _ in range(2):
            tlog.log_hydration(_make_event(
                sections_requested=["ENTITY-ORDER"],
            ))

        s = tlog.summary()
        top = s["top_sections"]
        assert len(top) >= 2
        # First entry should be the most accessed
        assert top[0][0] == "ENTITY-CUSTOMER"
        assert top[0][1] == 5
        assert top[1][0] == "ENTITY-ORDER"
        assert top[1][1] == 2


class TestSummaryRehydrationRate:
    def test_summary_rehydration_rate(self, tmp_path):
        """rehydration_rate should be the fraction of events with rehydration_triggered=True."""
        log_path = str(tmp_path / "telem.jsonl")
        tlog = TelemetryLog(path=log_path)

        # 3 events: 1 rehydration, 2 not
        tlog.log_hydration(_make_event(rehydration_triggered=True))
        tlog.log_hydration(_make_event(rehydration_triggered=False))
        tlog.log_hydration(_make_event(rehydration_triggered=False))

        s = tlog.summary()
        assert abs(s["rehydration_rate"] - 1 / 3) < 0.01


class TestSummaryZeroMatchRate:
    def test_summary_zero_match_rate(self, tmp_path):
        """zero_match_rate should be the fraction where sections_matched == 0."""
        log_path = str(tmp_path / "telem.jsonl")
        tlog = TelemetryLog(path=log_path)

        tlog.log_hydration(_make_event(sections_matched=0))
        tlog.log_hydration(_make_event(sections_matched=0))
        tlog.log_hydration(_make_event(sections_matched=3))
        tlog.log_hydration(_make_event(sections_matched=1))

        s = tlog.summary()
        assert abs(s["zero_match_rate"] - 0.5) < 0.01


class TestSummaryEmptyLog:
    def test_summary_empty_log(self, tmp_path):
        """summary() on a nonexistent or empty log should return zero stats."""
        log_path = str(tmp_path / "nonexistent.jsonl")
        tlog = TelemetryLog(path=log_path)

        s = tlog.summary()
        assert s["total_hydrations"] == 0
        assert s["unique_sessions"] == 0
        assert s["top_sections"] == []
        assert s["avg_tokens_per_hydration"] == 0.0
        assert s["rehydration_rate"] == 0.0
        assert s["avg_latency_ms"] == 0.0
        assert s["zero_match_rate"] == 0.0


class TestQuestionHashIsSha256:
    def test_question_hash_is_sha256(self, tmp_path):
        """question_hash should be a 64-char hex SHA-256 digest."""
        log_path = str(tmp_path / "telem.jsonl")
        tlog = TelemetryLog(path=log_path)

        qhash = hashlib.sha256(b"What is the retention policy?").hexdigest()
        tlog.log_hydration(_make_event(question_hash=qhash))

        with open(log_path, encoding="utf-8") as f:
            data = json.loads(f.readline())

        assert len(data["question_hash"]) == 64
        # Validate it's valid hex
        int(data["question_hash"], 16)


class TestSessionIdIsUuid:
    def test_session_id_is_uuid(self, tmp_path):
        """session_id should be a valid UUID string."""
        log_path = str(tmp_path / "telem.jsonl")
        tlog = TelemetryLog(path=log_path)

        sid = str(uuid.uuid4())
        tlog.log_hydration(_make_event(session_id=sid))

        with open(log_path, encoding="utf-8") as f:
            data = json.loads(f.readline())

        # Should not raise
        parsed = uuid.UUID(data["session_id"])
        assert str(parsed) == sid
