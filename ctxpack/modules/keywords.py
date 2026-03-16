"""Word-boundary keyword matching with one-to-many entity resolution.

Production bug fix: substring matching caused "market" to match "marketing",
hydrating the wrong value stream. And one-to-many keywords silently dropped
the second match.

This module provides a KeywordIndex that:
  1. Uses word-boundary regex to prevent substring false positives
  2. Supports one-to-many keyword -> entity mappings (no silent drops)
  3. Auto-generates keywords from CTXDocument entity/section names
  4. Accepts manual synonym mappings for domain-specific aliases
  5. Ranks results by number of keyword hits (more hits = higher rank)
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.model import CTXDocument, Section


# ── Constants ──

# Common words excluded from auto-generated keyword indices.
# These are too generic to be useful for entity resolution.
_GENERIC_WORDS: set[str] = {
    "the", "and", "for", "with", "from", "that", "this",
    "are", "was", "were", "been", "being", "have", "has",
    "had", "but", "not", "you", "all", "can", "her", "his",
    "how", "its", "may", "our", "out", "who", "oil", "did",
    "get", "got", "him", "let", "say", "she", "too", "use",
    "entity",  # meta-prefix, not meaningful as keyword
}


class KeywordIndex:
    """Word-boundary keyword matching with one-to-many resolution.

    Fixes two production bugs:
      1. Substring matching: ``\\bmarket\\b`` matches "market" but NOT "marketing"
      2. Silent drop: one keyword can map to multiple entities — all are returned
    """

    GENERIC_WORDS: set[str] = _GENERIC_WORDS

    def __init__(self, *, word_boundary: bool = True, min_keyword_length: int = 4):
        self._word_boundary = word_boundary
        self._min_keyword_length = min_keyword_length
        # keyword (lowercase) -> list of entity names (preserves insertion order)
        self._index: dict[str, list[str]] = defaultdict(list)
        # Compiled regex cache: keyword -> compiled pattern
        self._pattern_cache: dict[str, re.Pattern[str]] = {}

    @classmethod
    def from_document(cls, doc: "CTXDocument", **kwargs) -> "KeywordIndex":
        """Auto-generate keywords from entity/section names.

        Splits section names on hyphens, ampersands, and 'AND'. Filters out
        generic words and words shorter than min_keyword_length.

        Args:
            doc: Parsed CTXDocument whose body sections become keyword sources.
            **kwargs: Passed through to KeywordIndex.__init__.

        Returns:
            A populated KeywordIndex ready for match() calls.
        """
        from ..core.model import Section

        idx = cls(**kwargs)

        for elem in doc.body:
            if isinstance(elem, Section):
                idx._auto_add_section(elem)

        return idx

    def _auto_add_section(self, section: "Section") -> None:
        """Extract keywords from a section name and register them."""
        name = section.name  # e.g. "ENTITY-SUPPLY-CHAIN-AND-PATIENT-SERVICES"

        # Split on hyphens to get tokens
        raw_tokens = name.split("-")

        # Rejoin tokens that were split from multi-word phrases, but also
        # treat AND / & as phrase separators to get component word groups.
        # We want individual words, lowercased.
        words: list[str] = []
        for token in raw_tokens:
            lower = token.lower()
            # Skip 'and' as a separator (like &)
            if lower in ("and", "&"):
                continue
            words.append(lower)

        # Register each word that passes filters
        for word in words:
            if len(word) < self._min_keyword_length:
                continue
            if word in self.GENERIC_WORDS:
                continue
            self.add(word, name)

    def add(self, keyword: str, entity_name: str) -> None:
        """Add a keyword -> entity mapping. Supports one-to-many.

        If the same (keyword, entity_name) pair is added twice, the duplicate
        is silently ignored to keep match results clean.

        Args:
            keyword: The keyword string (will be lowercased for matching).
            entity_name: The entity/section name this keyword maps to.
        """
        key = keyword.lower()
        entities = self._index[key]
        if entity_name not in entities:
            entities.append(entity_name)
        # Invalidate cached pattern if it exists
        self._pattern_cache.pop(key, None)

    def add_synonyms(self, synonyms: dict[str, str]) -> None:
        """Add manual synonym -> entity mappings.

        Args:
            synonyms: Dict of {synonym: entity_name}. Example:
                {"hcp": "ENTITY-CUSTOMER", "rep": "ENTITY-SALES-REP"}
        """
        for synonym, entity_name in synonyms.items():
            self.add(synonym, entity_name)

    def match(self, query: str) -> list[str]:
        """Return all matching entity names for a query.

        Uses word-boundary regex when word_boundary=True. Results are ordered
        by match score (number of keyword hits per entity, descending).

        Args:
            query: Natural language query string.

        Returns:
            List of unique entity names, sorted by descending match score.
        """
        if not query or not query.strip():
            return []

        query_lower = query.lower()

        # Score: entity_name -> number of keyword hits
        scores: dict[str, int] = defaultdict(int)

        for keyword, entity_names in self._index.items():
            if self._keyword_matches(keyword, query_lower):
                for entity_name in entity_names:
                    scores[entity_name] += 1

        if not scores:
            return []

        # Sort by score descending, then alphabetically for stability
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return [entity_name for entity_name, _score in ranked]

    def _keyword_matches(self, keyword: str, query_lower: str) -> bool:
        """Check if keyword appears in query, respecting word_boundary setting."""
        if self._word_boundary:
            pattern = self._get_pattern(keyword)
            return pattern.search(query_lower) is not None
        else:
            return keyword in query_lower

    def _get_pattern(self, keyword: str) -> re.Pattern[str]:
        """Get or compile a word-boundary regex pattern for a keyword."""
        if keyword not in self._pattern_cache:
            # Escape the keyword in case it contains regex special chars
            escaped = re.escape(keyword)
            self._pattern_cache[keyword] = re.compile(
                r"\b" + escaped + r"\b", re.IGNORECASE
            )
        return self._pattern_cache[keyword]

    def to_dict(self) -> dict[str, list[str]]:
        """Export keyword map for inspection/debugging.

        Returns:
            Dict of {keyword: [entity_name, ...]} with regular dict (not defaultdict).
        """
        return {k: list(v) for k, v in self._index.items()}
