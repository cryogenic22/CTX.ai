"""Query-adaptive section hydration for .ctx documents.

Provides two hydration paths:
  1. hydrate_by_name() — LLM-directed: the LLM reads L3, decides what to expand
  2. hydrate_by_query() — Keyword fallback for programmatic (non-agentic) use

This module implements WS4 of the v0.4.0 backlog.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .model import CTXDocument, KeyValue, NumberedItem, PlainLine, Provenance, Section
from .serializer import serialize_section, _serialize_header_iter

if TYPE_CHECKING:
    from .telemetry import TelemetryLog


# ── Data Structures ──


@dataclass
class HydrationResult:
    """Result of hydrating sections from a .ctx document."""

    sections: list[Section] = field(default_factory=list)
    tokens_injected: int = 0
    sections_available: int = 0
    header_text: str = ""


# ── Section Index (O(1) lookup) ──


def _build_section_index(doc: CTXDocument) -> dict[str, Section]:
    """Build a case-insensitive name → section index from body elements."""
    index: dict[str, Section] = {}
    for elem in doc.body:
        if isinstance(elem, Section):
            index[elem.name.upper()] = elem
    return index


def _count_section_tokens(section: Section) -> int:
    """Count tokens in a serialized section (whitespace-split)."""
    lines = list(serialize_section(section))
    return len("\n".join(lines).split())


# ── Public API ──


def hydrate_by_name(
    doc: CTXDocument,
    section_names: list[str],
    *,
    include_header: bool = True,
    telemetry: "TelemetryLog | None" = None,
    question: str = "",
    session_id: str = "",
    rehydration_triggered: bool = False,
) -> HydrationResult:
    """Return specific sections by name. O(1) lookup via index.

    This is the primary hydration path — the LLM decides what to fetch
    by reading L3 and calling ctx/hydrate(section="ENTITY-X").

    Args:
        doc: Parsed CTXDocument.
        section_names: List of section names to hydrate (case-insensitive).
        include_header: Whether to include the document header in output.
        telemetry: Optional TelemetryLog to record the hydration event.
        question: Original question text (will be hashed, not stored raw).
        session_id: Session identifier for grouping events.
        rehydration_triggered: Whether this is a re-hydration attempt.

    Returns:
        HydrationResult with matched sections and token counts.
    """
    t0 = time.perf_counter()

    index = _build_section_index(doc)
    all_sections = [elem for elem in doc.body if isinstance(elem, Section)]

    matched: list[Section] = []
    for name in section_names:
        section = index.get(name.upper())
        if section is not None:
            matched.append(section)

    # Count tokens
    total_tokens = 0
    for section in matched:
        total_tokens += _count_section_tokens(section)

    # Header text
    header_text = ""
    if include_header:
        header_lines = list(_serialize_header_iter(
            doc.header, canonical=False, ascii_mode=False
        ))
        header_text = "\n".join(header_lines)
        total_tokens += len(header_text.split())

    result = HydrationResult(
        sections=matched,
        tokens_injected=total_tokens,
        sections_available=len(all_sections),
        header_text=header_text,
    )

    # Log telemetry if enabled
    if telemetry is not None:
        import datetime
        import uuid as _uuid

        from .telemetry import HydrationEvent

        elapsed_ms = (time.perf_counter() - t0) * 1000
        event = HydrationEvent(
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            session_id=session_id or str(_uuid.uuid4()),
            question_hash=hashlib.sha256(question.encode("utf-8")).hexdigest(),
            sections_requested=list(section_names),
            sections_matched=len(matched),
            tokens_injected=total_tokens,
            rehydration_triggered=rehydration_triggered,
            latency_ms=round(elapsed_ms, 3),
        )
        telemetry.log_hydration(event)

    return result


def hydrate_by_query(
    doc: CTXDocument,
    query: str,
    *,
    max_sections: int = 5,
    include_header: bool = True,
) -> HydrationResult:
    """Keyword-based section retrieval for non-agentic (programmatic) use.

    Scores sections by term overlap with the query. This is the fallback
    path — LLM-as-router (hydrate_by_name) is preferred for agentic use.

    Args:
        doc: Parsed CTXDocument.
        query: Natural language query or keyword string.
        max_sections: Maximum sections to return.
        include_header: Whether to include header in output.

    Returns:
        HydrationResult with top-scoring sections.
    """
    query_terms = set(_tokenize(query))
    if not query_terms:
        return HydrationResult(
            sections=[],
            tokens_injected=0,
            sections_available=0,
            header_text="",
        )

    all_sections = [elem for elem in doc.body if isinstance(elem, Section)]

    # Score each section
    scored: list[tuple[float, int, Section]] = []
    for idx, section in enumerate(all_sections):
        section_text = _extract_section_text(section)
        section_terms = set(_tokenize(section_text))

        overlap = query_terms & section_terms
        if not overlap:
            continue

        score = len(overlap) / len(query_terms)
        scored.append((score, idx, section))

    # Sort by score descending, take top N
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[:max_sections]

    matched = [s for _, _, s in top]

    # Count tokens
    total_tokens = 0
    for section in matched:
        total_tokens += _count_section_tokens(section)

    header_text = ""
    if include_header and matched:
        header_lines = list(_serialize_header_iter(
            doc.header, canonical=False, ascii_mode=False
        ))
        header_text = "\n".join(header_lines)
        total_tokens += len(header_text.split())

    return HydrationResult(
        sections=matched,
        tokens_injected=total_tokens,
        sections_available=len(all_sections),
        header_text=header_text,
    )


def list_sections(doc: CTXDocument) -> list[dict[str, Any]]:
    """Return section names with token counts.

    The LLM reads this list (included in the system prompt or L3)
    to decide which sections to hydrate.
    """
    result: list[dict[str, Any]] = []
    for elem in doc.body:
        if isinstance(elem, Section):
            result.append({
                "name": elem.name,
                "tokens": _count_section_tokens(elem),
            })
    return result


# ── Re-Hydration Detection ──


# Signals that the LLM's answer is low-confidence and may benefit from
# additional context. Detected by substring matching on the answer text.
_LOW_CONFIDENCE_SIGNALS = [
    "not found in context",
    "not enough information",
    "cannot fully answer",
    "don't have enough",
    "do not have enough",
    "based on the available context",
    "not available in the",
    "insufficient context",
    "need more context",
    "no information about",
    "not specified in",
    "cannot determine",
    "unable to determine",
    "(error:",
]


def needs_rehydration(answer: str) -> bool:
    """Detect whether an LLM answer indicates insufficient context.

    Returns True if the answer is empty, contains an error, or includes
    low-confidence signals suggesting the hydrated sections didn't cover
    the question. Used to trigger a second hydration round for multi-hop
    questions.

    This is a heuristic — it errs on the side of triggering re-hydration
    (false positives are cheap, false negatives lose fidelity).
    """
    if not answer or not answer.strip():
        return True

    lower = answer.lower()
    return any(signal in lower for signal in _LOW_CONFIDENCE_SIGNALS)


# ── Helpers ──


_TOKENIZE_RE = re.compile(r"[a-zA-Z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase alpha-numeric tokens (len > 1)."""
    return [t.lower() for t in _TOKENIZE_RE.findall(text) if len(t) > 1]


def _extract_section_text(section: Section) -> str:
    """Recursively collect all text content from a section."""
    parts = [section.name]
    parts.extend(section.subtitles)
    for child in section.children:
        if isinstance(child, KeyValue):
            parts.append(child.key)
            parts.append(child.value)
        elif isinstance(child, PlainLine):
            parts.append(child.text)
        elif isinstance(child, NumberedItem):
            parts.append(child.text)
        elif isinstance(child, Section):
            parts.append(_extract_section_text(child))
    return " ".join(parts)
