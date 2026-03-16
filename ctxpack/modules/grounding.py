"""Grounding wrapper — sandwich prompt builder for hydrated CTX content.

Wraps L2/L3 context with grounding rules (top) and a verification checklist
(bottom), eliminating 100+ lines of boilerplate per deployment. This is the
production module that converts CTX hydration output into LLM-ready prompts
with built-in hallucination guardrails.

Structure:
  TOP:    persona + grounding rules + few-shot example
  MIDDLE: catalog (L3 index) + hydrated sections (L2)
  BOTTOM: "BEFORE YOU RESPOND" checklist with entity counts
"""

from __future__ import annotations

import re
from typing import Optional


# ── Default grounding rules ──

_DEFAULT_GROUNDING_RULES: list[str] = [
    "ONLY reference entities from the catalog above.",
    "Do NOT invent entity names, IDs, or attributes that are not in the data.",
    "If the requested information is not in the data, say 'not found in the provided catalog'.",
]

_TEMPERATURE_WARNING = (
    "IMPORTANT: Use temperature 0 for grounded retrieval. "
    "Higher temperatures increase hallucination risk."
)

# ── Entity counting ──

_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_NUMBERED_RE = re.compile(r"^\d+\.\s+\S", re.MULTILINE)
_CTX_SECTION_RE = re.compile(r"^\[[\w-]+\]", re.MULTILINE)


def count_catalog_entities(catalog: str) -> int:
    """Count entities in a catalog string.

    Detection priority:
      1. Markdown headings (## ENTITY-...)  — if any found, use heading count
      2. .ctx section headers ([ENTITY-...]) — if any found, use section count
      3. Numbered items (1. Foo, 2. Bar)    — fallback
      4. 0 if nothing detected

    Args:
        catalog: The catalog/index text to scan.

    Returns:
        Number of detected entities.
    """
    if not catalog or not catalog.strip():
        return 0

    # Priority 1: Markdown headings
    headings = _HEADING_RE.findall(catalog)
    if headings:
        return len(headings)

    # Priority 2: .ctx section headers
    ctx_sections = _CTX_SECTION_RE.findall(catalog)
    if ctx_sections:
        return len(ctx_sections)

    # Priority 3: Numbered items
    numbered = _NUMBERED_RE.findall(catalog)
    if numbered:
        return len(numbered)

    return 0


# ── Tail reminder builder ──


def build_tail_reminder(
    *,
    entity_count: int,
    entity_type: str = "entities",
    citation_format: str = "",
    custom_rules: list[str] | None = None,
) -> str:
    """Build the tail-end verification checklist.

    This is the "bottom bread" of the sandwich prompt — a concise checklist
    that reinforces grounding constraints after the LLM has read all context.

    Args:
        entity_count: Exact number of entities in the catalog.
        entity_type: Human-readable entity type name (e.g., "flywheels").
        citation_format: Optional citation format string to remind the LLM.
        custom_rules: Additional rules to include in the checklist.

    Returns:
        Tail reminder text block.
    """
    lines: list[str] = []
    lines.append("---")
    lines.append("BEFORE YOU RESPOND, verify:")
    lines.append(
        f"- The catalog contains exactly {entity_count} {entity_type}. "
        f"List only those."
    )
    lines.append("- Every entity name you mention appears in the catalog above.")
    lines.append("- You have NOT invented any names, IDs, or attributes.")

    if citation_format:
        lines.append(f"- Use this citation format: {citation_format}")

    if custom_rules:
        for rule in custom_rules:
            lines.append(f"- {rule}")

    return "\n".join(lines)


# ── Main prompt builder ──


def build_grounded_prompt(
    *,
    catalog: str,
    hydrated: str = "",
    persona: str = "",
    grounding_rules: list[str] | None = None,
    citation_format: str = "",
    sandwich: bool = True,
    few_shot: bool = True,
    entity_count_reminder: bool = True,
    temperature_warning: bool = True,
) -> str:
    """Build a grounded system prompt with sandwich reinforcement.

    Structure:
      1. TOP:    persona + grounding rules + few-shot example
      2. MIDDLE: catalog (L3) + hydrated sections (L2)
      3. BOTTOM: "BEFORE YOU RESPOND" checklist with entity counts

    Args:
        catalog: L3 index text listing available entities.
        hydrated: L2 hydrated section text (optional).
        persona: Custom persona instruction (optional).
        grounding_rules: Custom rules list; defaults to standard grounding rules.
        citation_format: Citation format string (e.g., "[{title}](/entity/{id})").
        sandwich: If True, add bottom-of-prompt reinforcement checklist.
        few_shot: If True, auto-generate correct/wrong grounding example.
        entity_count_reminder: If True, include entity count in tail reminder.
        temperature_warning: If True, include temperature 0 recommendation.

    Returns:
        Complete system prompt string ready for LLM injection.
    """
    parts: list[str] = []
    entity_count = count_catalog_entities(catalog)
    rules = grounding_rules if grounding_rules is not None else _DEFAULT_GROUNDING_RULES

    # ── TOP: persona + rules + few-shot ──

    if persona:
        parts.append(persona)
        parts.append("")

    if temperature_warning:
        parts.append(_TEMPERATURE_WARNING)
        parts.append("")

    # Grounding rules
    parts.append("GROUNDING RULES:")
    for rule in rules:
        parts.append(f"- {rule}")
    parts.append("")

    # Few-shot example
    if few_shot:
        parts.append("EXAMPLES:")
        parts.append("")
        parts.append("Correct: \"Flywheel Alpha (FW-001) has status Active.\"")
        parts.append("  -> References an entity from the catalog with its real ID.")
        parts.append("")
        parts.append(
            "Wrong (hallucination): \"Flywheel Omega (FW-999) is the most popular.\""
        )
        parts.append(
            "  -> 'Flywheel Omega' and 'FW-999' do not exist in the catalog."
        )
        parts.append("")

    # ── MIDDLE: catalog + hydrated content ──

    parts.append("--- CATALOG ---")
    parts.append(catalog.rstrip())
    parts.append("--- END CATALOG ---")
    parts.append("")

    if hydrated:
        parts.append("--- HYDRATED DETAIL ---")
        parts.append(hydrated.rstrip())
        parts.append("--- END HYDRATED DETAIL ---")
        parts.append("")

    # ── BOTTOM: tail reminder ──

    if sandwich:
        entity_type = _infer_entity_type(catalog)
        reminder = build_tail_reminder(
            entity_count=entity_count,
            entity_type=entity_type,
            citation_format=citation_format,
        )
        parts.append(reminder)

    return "\n".join(parts)


# ── Helpers ──


def _infer_entity_type(catalog: str) -> str:
    """Attempt to infer entity type from catalog content.

    Falls back to 'entities' if nothing specific is found.
    """
    # Look for common patterns like "ENTITY-FLYWHEEL-*" → "entities"
    # This is intentionally simple — callers can override via build_tail_reminder
    return "entities"
