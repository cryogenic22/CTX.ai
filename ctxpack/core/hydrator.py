"""Query-adaptive section hydration for .ctx documents.

Provides two hydration paths:
  1. hydrate_by_name() — LLM-directed: the LLM reads L3, decides what to expand
  2. hydrate_by_query() — Keyword fallback for programmatic (non-agentic) use

This module implements WS4 of the v0.4.0 backlog.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from .layers import ContextLayer
from .model import CTXDocument, KeyValue, NumberedItem, PlainLine, Provenance, Section
from .serializer import serialize_section, _serialize_header_iter
from .tokens import ESTIMATOR_CTX, estimate_tokens

if TYPE_CHECKING:
    from .telemetry import TelemetryLog


# ── Data Structures ──


@dataclass
class HydrationResult:
    """Result of hydrating sections from a .ctx document."""

    sections: list[Section] = field(default_factory=list)
    # tokens_injected estimates the raw .ctx serialization (the storage
    # representation) — it drives hydration BUDGET decisions and
    # telemetry, and is labelled ESTIMATOR_CTX. It does NOT describe a
    # consumer's emitted render: a surface that emits prose
    # (natural_language=True) must estimate its own final string with
    # kind="prose" and report that label instead (Q2-1).
    tokens_injected: int = 0
    sections_available: int = 0
    header_text: str = ""
    layer_breakdown: dict[str, int] = field(default_factory=dict)
    token_estimator: str = ESTIMATOR_CTX


# ── Section Index (O(1) lookup) ──


def _build_section_index(doc: CTXDocument) -> dict[str, Section]:
    """Build a case-insensitive name → section index from body elements."""
    index: dict[str, Section] = {}
    for elem in doc.body:
        if isinstance(elem, Section):
            index[elem.name.upper()] = elem
    return index


def _count_section_tokens(section: Section) -> int:
    """Estimate tokens in a serialized section (see core.tokens)."""
    lines = list(serialize_section(section))
    return estimate_tokens("\n".join(lines), kind="ctx")


def _section_provenance(section: Section) -> Optional[Provenance]:
    """Return the section's first Provenance child, or None.

    The compressor injects a Provenance per source, and consumers care
    about the dominant layer, so the first one is sufficient.
    """
    for child in section.children:
        if isinstance(child, Provenance):
            return child
    return None


def _section_layer(section: Section) -> ContextLayer:
    """Return the layer recorded in the section's Provenance.

    Sections without provenance default to RULES so that legacy packs
    (built before the four-layer architecture) keep their existing
    semantics.
    """
    prov = _section_provenance(section)
    return prov.layer if prov is not None else ContextLayer.RULES


def _section_confidence(section: Section) -> float:
    """Return the confidence recorded in the section's Provenance.

    Sections without provenance default to 1.0 (full confidence).
    """
    prov = _section_provenance(section)
    return prov.confidence if prov is not None else 1.0


def _section_expired(section: Section, now: str) -> bool:
    """True when the section's Provenance carries an expires_at in the past.

    AMBIENT facts (live repo/branch/test state) carry expiry; serving one
    past its expires_at re-injects stale state into the agent. Sections
    without provenance or without expires_at never expire.

    ``Provenance.expires_at`` is an epoch-seconds float; ``now`` is an
    ISO-8601 date/datetime string (or a stringified epoch), converted here.
    Unparseable inputs fail open (not expired) — hydration must never
    crash on malformed metadata.
    """
    prov = _section_provenance(section)
    if prov is None:
        return False
    expires = getattr(prov, "expires_at", None)
    if not expires:
        return False
    try:
        now_epoch = float(now)
    except ValueError:
        import datetime
        try:
            # Python 3.10's fromisoformat rejects the Z suffix
            now_epoch = datetime.datetime.fromisoformat(
                now.replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            return False
    return float(expires) < now_epoch


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
    layers: Optional[set[ContextLayer]] = None,
    min_confidence: float = 0.0,
    include_layer_metadata: bool = False,
    drop_expired_as_of: str = "",
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
        layers: Restrict matches to sections whose Provenance layer is in
            this set. ``None`` (default) returns all layers.
        min_confidence: Drop sections whose Provenance confidence is below
            this threshold. Default 0.0 keeps everything.
        include_layer_metadata: When True, populate ``layer_breakdown`` on
            the result with per-layer section counts for telemetry / UI.
        drop_expired_as_of: ISO date/datetime string; when non-empty, skip
            sections whose Provenance expires_at is earlier than this
            (AMBIENT facts past their TTL). Empty string (default) keeps
            expired sections — existing callers are unaffected.

    Returns:
        HydrationResult with matched sections and token counts.
    """
    t0 = time.perf_counter()

    index = _build_section_index(doc)
    all_sections = [elem for elem in doc.body if isinstance(elem, Section)]

    matched: list[Section] = []
    for name in section_names:
        section = index.get(name.upper())
        if section is None:
            continue
        if layers is not None and _section_layer(section) not in layers:
            continue
        if min_confidence > 0.0 and _section_confidence(section) < min_confidence:
            continue
        if drop_expired_as_of and _section_expired(section, drop_expired_as_of):
            continue
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
        total_tokens += estimate_tokens(header_text, kind="ctx")

    breakdown: dict[str, int] = {}
    if include_layer_metadata:
        for section in matched:
            key = _section_layer(section).value
            breakdown[key] = breakdown.get(key, 0) + 1

    result = HydrationResult(
        sections=matched,
        tokens_injected=total_tokens,
        sections_available=len(all_sections),
        header_text=header_text,
        layer_breakdown=breakdown,
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
            token_estimator=ESTIMATOR_CTX,
        )
        telemetry.log_hydration(event)

    return result


# Suffix order matters: longest first, so "ization" wins over "ion".
_STEM_SUFFIXES = ("ization", "isation", "ations", "ation", "ingly", "ing",
                  "edly", "ed", "ies", "ily", "ly", "es", "s")


def _stem(token: str) -> str:
    """Strip a common English suffix, leaving at least a 4-character root.

    Inflectional only: plural -s, past -ed, gerund -ing and similar, so
    "delivers" matches "delivered". Derivational pairs are NOT normalised -
    "emission" and "emitting" keep different stems - and over-stemming is
    possible ("proves" -> "prov" while "prove" is left alone). It is a
    cheap recall aid, not a linguistics engine.
    """
    for suffix in _STEM_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            root = token[: -len(suffix)]
            return root + "y" if suffix == "ies" else root
    return token


def _idf(n_sections: int, doc_freq: int) -> float:
    """Inverse document frequency over the sections of one document.

    A term present in every section scores near zero, so common words stop
    outranking distinctive ones without needing a hard-coded stopword list.
    """
    return math.log(1 + (n_sections - doc_freq + 0.5) / (doc_freq + 0.5))


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
    query_terms = {_stem(term) for term in _tokenize(query)}
    if not query_terms:
        return HydrationResult(
            sections=[],
            tokens_injected=0,
            sections_available=0,
            header_text="",
        )

    all_sections = [elem for elem in doc.body if isinstance(elem, Section)]

    # Term sets per section, then document frequency for IDF weighting.
    # Without IDF a section matching "the" outranks one matching "telemetry".
    section_terms = [
        {_stem(term) for term in _tokenize(_extract_section_text(section))}
        for section in all_sections
    ]
    doc_freq: dict[str, int] = {}
    for terms in section_terms:
        for term in terms:
            doc_freq[term] = doc_freq.get(term, 0) + 1

    # Score each section
    scored: list[tuple[float, int, Section]] = []
    for idx, section in enumerate(all_sections):
        overlap = query_terms & section_terms[idx]
        if not overlap:
            continue

        score = sum(_idf(len(all_sections), doc_freq[term]) for term in overlap)
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
        total_tokens += estimate_tokens(header_text, kind="ctx")

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
