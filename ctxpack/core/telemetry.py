"""Append-only JSONL telemetry for hydration events.

Logs every hydration call to a local JSONL file for usage analysis.
Zero external dependencies — uses only stdlib (json, datetime, hashlib, uuid, os).

Privacy: questions are SHA-256 hashed; raw text is never stored.
Thread-safety: uses file append mode (atomic on most OS + filesystem combos).
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class HydrationEvent:
    """Single hydration event."""

    timestamp: str  # ISO 8601
    session_id: str  # Random UUID per session
    question_hash: str  # SHA-256 of question (not the question itself -- privacy)
    sections_requested: list[str]
    sections_matched: int
    tokens_injected: int
    rehydration_triggered: bool
    latency_ms: float  # Time to serialize and return


class TelemetryLog:
    """Append-only JSONL telemetry logger.

    Writes one JSON object per line. Never modifies or deletes entries.
    """

    def __init__(self, path: str = ".ctxpack/telemetry.jsonl") -> None:
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    def log_hydration(self, event: HydrationEvent) -> None:
        """Append a HydrationEvent to the JSONL log file.

        Creates parent directories if they don't exist.
        Uses append mode for thread-safety.
        """
        parent = os.path.dirname(self._path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        line = json.dumps(asdict(event), separators=(",", ":"))
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def summary(self) -> dict[str, Any]:
        """Read the log and return aggregate statistics.

        Returns a dict with:
          - total_hydrations: int
          - unique_sessions: int
          - top_sections: list of (section_name, count) sorted descending
          - avg_tokens_per_hydration: float
          - rehydration_rate: float (0.0-1.0)
          - avg_latency_ms: float
          - zero_match_rate: float (0.0-1.0)
        """
        events = self._read_events()

        if not events:
            return {
                "total_hydrations": 0,
                "unique_sessions": 0,
                "top_sections": [],
                "avg_tokens_per_hydration": 0.0,
                "rehydration_rate": 0.0,
                "avg_latency_ms": 0.0,
                "zero_match_rate": 0.0,
            }

        total = len(events)
        sessions: set[str] = set()
        section_counter: Counter[str] = Counter()
        total_tokens = 0
        rehydrations = 0
        total_latency = 0.0
        zero_matches = 0

        for ev in events:
            sessions.add(ev.get("session_id", ""))
            for sec in ev.get("sections_requested", []):
                section_counter[sec] += 1
            total_tokens += ev.get("tokens_injected", 0)
            if ev.get("rehydration_triggered", False):
                rehydrations += 1
            total_latency += ev.get("latency_ms", 0.0)
            if ev.get("sections_matched", 0) == 0:
                zero_matches += 1

        top_sections = section_counter.most_common()

        return {
            "total_hydrations": total,
            "unique_sessions": len(sessions),
            "top_sections": top_sections,
            "avg_tokens_per_hydration": total_tokens / total,
            "rehydration_rate": rehydrations / total,
            "avg_latency_ms": total_latency / total,
            "zero_match_rate": zero_matches / total,
        }

    def _read_events(self) -> list[dict[str, Any]]:
        """Read all events from the JSONL file.

        Returns an empty list if the file doesn't exist or is empty.
        Silently skips malformed lines.
        """
        if not os.path.isfile(self._path):
            return []

        events: list[dict[str, Any]] = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # Skip malformed lines
        return events
