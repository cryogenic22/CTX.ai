"""Source cross-reference resolver for Markdown documents.

Pre-processing step that resolves "See Section X.Y", "refer to Section X",
and similar cross-references in source text before entity extraction.
"""

from __future__ import annotations

import re
from typing import Optional

# Patterns for section cross-references
_SECTION_REF_RE = re.compile(
    r"(?:see|refer(?:\s+to)?|as\s+(?:described|defined|specified)\s+in)"
    r"\s+(?:Section|§)\s*(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)

# Heading patterns for building the section index
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def build_section_index(text: str) -> dict[str, str]:
    """Build an index mapping section numbers to their heading text.

    Uses markdown heading hierarchy to assign numbering:
    # H1 → 1, 2, 3...
    ## H2 → 1.1, 1.2...
    ### H3 → 1.1.1, 1.1.2...

    Returns:
        Dict mapping section number strings (e.g. "2.3") to heading text.
    """
    index: dict[str, str] = {}
    counters = [0] * 7  # counters[1] = H1 count, counters[2] = H2 count, etc.

    for m in _HEADING_RE.finditer(text):
        level = len(m.group(1))  # number of # chars
        heading = m.group(2).strip()

        # Increment counter at this level, reset deeper levels
        counters[level] += 1
        for i in range(level + 1, 7):
            counters[i] = 0

        # Build section number string
        parts = []
        for i in range(1, level + 1):
            parts.append(str(counters[i]))
        section_num = ".".join(parts)

        index[section_num] = heading

    return index


def resolve_xrefs(text: str, section_index: Optional[dict[str, str]] = None) -> str:
    """Resolve cross-references in source text.

    Replaces patterns like "See Section 2.3" with the actual section heading
    text inline, e.g. "See Section 2.3 (Data Retention Rules)".

    Args:
        text: Source markdown text.
        section_index: Pre-built section index. If None, builds one from text.

    Returns:
        Text with resolved cross-references.
    """
    if section_index is None:
        section_index = build_section_index(text)

    if not section_index:
        return text

    def _replace_ref(m: re.Match) -> str:
        full_match = m.group(0)
        section_num = m.group(1)
        heading = section_index.get(section_num)
        if heading:
            return f"{full_match} ({heading})"
        return full_match

    return _SECTION_REF_RE.sub(_replace_ref, text)
