"""Catalog-Wide Query Detection — count/list/overview intent detection.

Detects "how many?", "list all", "overview" intent and provides a grouped
catalog summary for catalog-wide queries instead of selective hydration.

This module implements M4 of the CtxPack module roadmap.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from ..core.model import CTXDocument, Section


# ── Default detection keywords ──

_DEFAULT_KEYWORDS: list[str] = [
    "how many",
    "list all",
    "total",
    "every",
    "all the",
    "overview",
    "full list",
    "complete list",
]

# Pre-built pattern for "what {entity_type} do we have"
_WHAT_HAVE_TEMPLATE = r"what\s+{entity_type}\s+do\s+we\s+have"

# Entity section prefix pattern: ENTITY-XX-NNN → group by "XX"
_ENTITY_PREFIX_RE = re.compile(r"^ENTITY-([A-Z]{2,3})-")


def is_catalog_query(
    query: str,
    *,
    custom_keywords: Optional[list[str]] = None,
    entity_type: str = "entities",
) -> bool:
    """Detect count/list/overview intent in a query.

    Args:
        query: The user's natural-language query.
        custom_keywords: Additional keywords to detect (extends defaults).
        entity_type: Entity type name for "what X do we have" pattern.

    Returns:
        True if the query appears to be a catalog-wide query.
    """
    if not query or not query.strip():
        return False

    lower = query.lower()

    # Build keyword list: defaults + custom
    keywords = list(_DEFAULT_KEYWORDS)
    if custom_keywords:
        keywords.extend(custom_keywords)

    # Check each keyword
    for keyword in keywords:
        if keyword.lower() in lower:
            return True

    # Check "what {entity_type} do we have" pattern
    pattern = _WHAT_HAVE_TEMPLATE.format(entity_type=re.escape(entity_type))
    if re.search(pattern, lower):
        return True

    return False


def build_catalog_summary(
    doc: CTXDocument,
    *,
    group_by: str = "prefix",
    include_counts: bool = True,
    include_total: bool = True,
) -> str:
    """Build a grouped summary with counts for catalog-wide queries.

    Groups entity sections by name prefix (characters before second hyphen,
    e.g. ENTITY-CL-001 → "CL") and produces a structured summary.

    Args:
        doc: Parsed CTXDocument.
        group_by: Grouping strategy ("prefix" is currently the only mode).
        include_counts: Whether to include per-group counts.
        include_total: Whether to include the total line.

    Returns:
        Formatted catalog summary string.
    """
    # Collect entity sections only
    entity_sections: list[Section] = []
    for elem in doc.body:
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-"):
            entity_sections.append(elem)

    if not entity_sections and include_total:
        return "TOTAL: 0 entities across 0 groups"

    if not entity_sections:
        return ""

    # Group by prefix
    groups: dict[str, list[str]] = defaultdict(list)
    ungrouped: list[str] = []

    for section in entity_sections:
        match = _ENTITY_PREFIX_RE.match(section.name)
        if match:
            prefix = match.group(1)
            groups[prefix].append(section.name)
        else:
            ungrouped.append(section.name)

    parts: list[str] = []

    # Total line
    total_entities = len(entity_sections)
    total_groups = len(groups) + (1 if ungrouped else 0)

    if include_total:
        parts.append(f"TOTAL: {total_entities} entities across {total_groups} groups")
        parts.append("")

    # Per-group output
    for prefix in sorted(groups.keys()):
        names = sorted(groups[prefix])
        if include_counts:
            parts.append(f"{prefix} ({len(names)}):")
        else:
            parts.append(f"{prefix}:")
        for name in names:
            parts.append(f"  {name}")
        parts.append("")

    # Ungrouped entities (no matching prefix pattern)
    if ungrouped:
        if include_counts:
            parts.append(f"OTHER ({len(ungrouped)}):")
        else:
            parts.append("OTHER:")
        for name in sorted(ungrouped):
            parts.append(f"  {name}")
        parts.append("")

    return "\n".join(parts).rstrip()
