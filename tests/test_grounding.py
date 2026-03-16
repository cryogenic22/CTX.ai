"""Tests for the grounding wrapper module.

TDD tests — written before implementation.
"""

from __future__ import annotations

import pytest

from ctxpack.modules.grounding import (
    build_grounded_prompt,
    build_tail_reminder,
    count_catalog_entities,
)


# ── Fixtures ──

SAMPLE_CATALOG = """\
## ENTITY-FLYWHEEL-ALPHA
ID: FW-001
Type: Flywheel

## ENTITY-FLYWHEEL-BETA
ID: FW-002
Type: Flywheel

## ENTITY-FLYWHEEL-GAMMA
ID: FW-003
Type: Flywheel
"""

NUMBERED_CATALOG = """\
1. Flywheel Alpha (FW-001)
2. Flywheel Beta (FW-002)
3. Flywheel Gamma (FW-003)
4. Flywheel Delta (FW-004)
5. Flywheel Epsilon (FW-005)
"""

SAMPLE_HYDRATED = """\
[ENTITY-FLYWHEEL-ALPHA]
  NAME: Flywheel Alpha
  IDENTIFIER: FW-001
  STATUS: Active
"""


# ── Tests ──


class TestBuildGroundedPrompt:
    """Tests for build_grounded_prompt()."""

    def test_grounded_prompt_has_top_rules(self):
        """The prompt must contain grounding rules near the top."""
        result = build_grounded_prompt(catalog=SAMPLE_CATALOG)
        # Default rules should be present
        assert "ONLY reference entities from the catalog" in result
        assert "Do NOT invent entity names" in result
        assert "not found" in result

    def test_grounded_prompt_has_bottom_reminder(self):
        """When sandwich=True, the prompt must have a BEFORE YOU RESPOND section."""
        result = build_grounded_prompt(catalog=SAMPLE_CATALOG)
        assert "BEFORE YOU RESPOND" in result

    def test_grounded_prompt_sandwich_structure(self):
        """Top rules appear before catalog, catalog before bottom reminder."""
        result = build_grounded_prompt(
            catalog=SAMPLE_CATALOG,
            hydrated=SAMPLE_HYDRATED,
        )
        rules_pos = result.index("ONLY reference entities")
        catalog_pos = result.index("ENTITY-FLYWHEEL-ALPHA")
        reminder_pos = result.index("BEFORE YOU RESPOND")
        assert rules_pos < catalog_pos < reminder_pos

    def test_grounded_prompt_entity_count_auto_detected(self):
        """The tail reminder must include the auto-detected entity count."""
        result = build_grounded_prompt(catalog=SAMPLE_CATALOG)
        # 3 headings in SAMPLE_CATALOG
        assert "exactly 3" in result

    def test_grounded_prompt_few_shot_has_correct_and_wrong(self):
        """Few-shot example must include a correct and wrong example."""
        result = build_grounded_prompt(catalog=SAMPLE_CATALOG, few_shot=True)
        # Must have both a correct example marker and a wrong/hallucination marker
        assert "Correct" in result or "CORRECT" in result or "correct" in result.lower()
        assert "Wrong" in result or "WRONG" in result or "hallucination" in result.lower()

    def test_grounded_prompt_without_sandwich_has_no_reminder(self):
        """When sandwich=False, no BEFORE YOU RESPOND section."""
        result = build_grounded_prompt(catalog=SAMPLE_CATALOG, sandwich=False)
        assert "BEFORE YOU RESPOND" not in result

    def test_grounded_prompt_without_few_shot_has_no_examples(self):
        """When few_shot=False, no example section."""
        result = build_grounded_prompt(catalog=SAMPLE_CATALOG, few_shot=False)
        # Should not contain the few-shot markers
        lower = result.lower()
        assert "example" not in lower or ("correct" not in lower and "wrong" not in lower)

    def test_grounded_prompt_custom_rules_included(self):
        """Custom grounding rules replace defaults."""
        custom = ["Always cite page numbers", "Use formal tone"]
        result = build_grounded_prompt(
            catalog=SAMPLE_CATALOG,
            grounding_rules=custom,
        )
        assert "Always cite page numbers" in result
        assert "Use formal tone" in result

    def test_grounded_prompt_custom_persona(self):
        """Custom persona instruction appears in the prompt."""
        result = build_grounded_prompt(
            catalog=SAMPLE_CATALOG,
            persona="You are a pharmaceutical compliance assistant.",
        )
        assert "pharmaceutical compliance assistant" in result

    def test_grounded_prompt_temperature_warning(self):
        """Temperature warning is included when enabled."""
        result = build_grounded_prompt(catalog=SAMPLE_CATALOG, temperature_warning=True)
        assert "temperature" in result.lower() or "Temperature" in result

    def test_grounded_prompt_no_temperature_warning(self):
        """Temperature warning is excluded when disabled."""
        result = build_grounded_prompt(
            catalog=SAMPLE_CATALOG,
            temperature_warning=False,
        )
        # Should not contain temperature warning
        assert "temperature 0" not in result.lower()

    def test_grounded_prompt_citation_format_in_reminder(self):
        """Citation format string appears in the tail reminder."""
        fmt = "[{title}](/entity/{id})"
        result = build_grounded_prompt(
            catalog=SAMPLE_CATALOG,
            citation_format=fmt,
        )
        assert fmt in result


class TestBuildTailReminder:
    """Tests for build_tail_reminder()."""

    def test_tail_reminder_references_exact_count(self):
        """Tail reminder must include the exact entity count."""
        result = build_tail_reminder(entity_count=46, entity_type="flywheels")
        assert "exactly 46 flywheels" in result
        assert "BEFORE YOU RESPOND" in result

    def test_tail_reminder_custom_rules(self):
        """Custom rules appear in the tail reminder."""
        result = build_tail_reminder(
            entity_count=10,
            custom_rules=["Double-check all dates"],
        )
        assert "Double-check all dates" in result

    def test_tail_reminder_citation_format(self):
        """Citation format is mentioned in tail reminder."""
        fmt = "[{name}](#{id})"
        result = build_tail_reminder(entity_count=5, citation_format=fmt)
        assert fmt in result


class TestCountCatalogEntities:
    """Tests for count_catalog_entities()."""

    def test_count_catalog_entities_from_headings(self):
        """Counts ## headings as entities."""
        count = count_catalog_entities(SAMPLE_CATALOG)
        assert count == 3

    def test_count_catalog_entities_from_numbered_list(self):
        """Counts numbered items (1. 2. 3. ...) as entities."""
        count = count_catalog_entities(NUMBERED_CATALOG)
        assert count == 5

    def test_count_catalog_entities_empty(self):
        """Empty catalog returns 0."""
        count = count_catalog_entities("")
        assert count == 0

    def test_count_catalog_entities_mixed(self):
        """Mixed heading and numbered list — headings take priority."""
        mixed = "## Entity A\n1. Sub item\n## Entity B\n2. Sub item\n"
        count = count_catalog_entities(mixed)
        # Should count headings (2), not numbered items
        assert count == 2
