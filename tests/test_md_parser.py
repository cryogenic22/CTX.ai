"""Tests for Markdown entity extraction."""

import os
import pytest
from ctxpack.core.packer.md_parser import extract_entities_from_md


FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "sample-corpus"
)


class TestEntityDetection:
    def test_detects_entity_from_heading(self):
        text = "# Entity: CUSTOMER\n\n## Rules\n\n- Rule one\n"
        entities, _, _ = extract_entities_from_md(text)
        assert len(entities) == 1
        assert entities[0].name == "CUSTOMER"

    def test_detects_entity_from_uppercase_heading(self):
        text = "# CUSTOMER\n\n- A rule\n"
        entities, _, _ = extract_entities_from_md(text)
        assert len(entities) == 1
        assert entities[0].name == "CUSTOMER"

    def test_multiple_entities(self):
        text = "# Entity: CUSTOMER\n\n- Rule A\n\n# Entity: ORDER\n\n- Rule B\n"
        entities, _, _ = extract_entities_from_md(text)
        assert len(entities) == 2
        names = [e.name for e in entities]
        assert "CUSTOMER" in names
        assert "ORDER" in names

    def test_alias_resolution(self):
        text = "# Client\n\n- Some rule\n"
        alias_map = {"CUSTOMER": ["client", "buyer"]}
        entities, _, _ = extract_entities_from_md(text, alias_map=alias_map)
        assert len(entities) == 1
        assert entities[0].name == "CUSTOMER"


class TestFieldExtraction:
    def test_bullets_become_fields(self):
        text = "# Entity: CUSTOMER\n\n## Matching Rules\n\n- Email is matched exactly\n- Phone uses E.164\n"
        entities, _, _ = extract_entities_from_md(text)
        assert len(entities[0].fields) == 2

    def test_field_key_from_heading(self):
        text = "# Entity: CUSTOMER\n\n## Tier System\n\n- Bronze: $0-$999\n"
        entities, _, _ = extract_entities_from_md(text)
        assert entities[0].fields[0].key == "TIER-SYSTEM"

    def test_prose_paragraph_as_field(self):
        text = "# Entity: CUSTOMER\n\n## Rules\n\nAll customers must have at least one communication channel.\n"
        entities, _, _ = extract_entities_from_md(text)
        assert len(entities[0].fields) >= 1


class TestWarnings:
    def test_warning_blockquote(self):
        text = '# Entity: CUSTOMER\n\n> **Warning:** Tier downgrades are not automatic.\n'
        _, _, warnings = extract_entities_from_md(text)
        assert len(warnings) == 1
        assert "downgrade" in warnings[0].message.lower()

    def test_warning_entity_attribution(self):
        text = '# Entity: CUSTOMER\n\n> **Warning:** Some issue.\n'
        _, _, warnings = extract_entities_from_md(text)
        assert warnings[0].entity == "CUSTOMER"


class TestBusinessRulesFixture:
    def test_parse_business_rules(self):
        path = os.path.join(FIXTURES_DIR, "docs", "business-rules.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        entities, _, warnings = extract_entities_from_md(text, filename="business-rules.md")
        names = [e.name for e in entities]
        assert "CUSTOMER" in names
        assert "ORDER" in names
        assert len(warnings) >= 1  # At least the tier downgrade warning

    def test_parse_tribal_knowledge(self):
        path = os.path.join(FIXTURES_DIR, "docs", "tribal-knowledge.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        entities, rules, warnings = extract_entities_from_md(text, filename="tribal-knowledge.md")
        assert len(warnings) >= 1  # Retention gotcha warning


class TestStandaloneRules:
    def test_non_entity_heading_produces_standalone(self):
        text = "# General Notes\n\n- Always validate input\n- Never trust client data\n"
        _, rules, _ = extract_entities_from_md(text)
        # "General Notes" is not all-caps → not entity, but bullets become standalone rules
        assert len(rules) == 2
        assert rules[0].key == "GENERAL-NOTES"

    def test_h2_non_entity_field(self):
        text = "# Entity: CUSTOMER\n\n## Known Issues\n\n- SKU format inconsistency\n"
        entities, _, _ = extract_entities_from_md(text)
        assert any(f.key == "KNOWN-ISSUES" for f in entities[0].fields)
