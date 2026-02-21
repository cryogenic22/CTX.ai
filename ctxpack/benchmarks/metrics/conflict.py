"""Conflict detection precision/recall metrics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConflictMetrics:
    """Conflict detection measurement."""

    planted: int
    found: int
    precision: float
    recall: float

    def to_dict(self) -> dict:
        return {
            "planted": self.planted,
            "found": self.found,
            "precision": round(self.precision, 2),
            "recall": round(self.recall, 2),
        }


def measure_conflicts(
    planted_count: int,
    detected_count: int,
    true_positives: int,
) -> ConflictMetrics:
    """Calculate conflict detection precision and recall."""
    precision = true_positives / detected_count if detected_count > 0 else 0.0
    recall = true_positives / planted_count if planted_count > 0 else 0.0
    return ConflictMetrics(
        planted=planted_count,
        found=detected_count,
        precision=precision,
        recall=recall,
    )
