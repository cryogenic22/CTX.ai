"""Tests for .ctx validation."""

import os
import pytest

from ctxpack.core.parser import parse
from ctxpack.core.validator import validate
from ctxpack.core.errors import DiagnosticLevel

FIXTURES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestHeaderValidation:
    def test_valid_minimal(self):
        text = "§CTX v1.0 L2 DOMAIN:test\nCOMPRESSED:2026-01-01\nSOURCE_TOKENS:~1000\n\n"
        doc = parse(text, level=1)
        diags = validate(doc, level=1)
        errors = [d for d in diags if d.level == DiagnosticLevel.ERROR]
        assert len(errors) == 0

    def test_e001_missing_domain(self):
        text = "§CTX v1.0 L2\nCOMPRESSED:2026-01-01\nSOURCE_TOKENS:~1000\n\n"
        doc = parse(text, level=1)
        diags = validate(doc, level=1)
        e001s = [d for d in diags if d.code == "E001"]
        assert any("DOMAIN" in d.message for d in e001s)

    def test_e001_missing_compressed(self):
        text = "§CTX v1.0 L2 DOMAIN:test\nSOURCE_TOKENS:~1000\n\n"
        doc = parse(text, level=1)
        diags = validate(doc, level=1)
        e001s = [d for d in diags if d.code == "E001"]
        assert any("COMPRESSED" in d.message for d in e001s)

    def test_e001_missing_source_tokens(self):
        text = "§CTX v1.0 L2 DOMAIN:test\nCOMPRESSED:2026-01-01\n\n"
        doc = parse(text, level=1)
        diags = validate(doc, level=1)
        e001s = [d for d in diags if d.code == "E001"]
        assert any("SOURCE_TOKENS" in d.message for d in e001s)

    def test_w001_unknown_field(self):
        text = "§CTX v1.0 L2 DOMAIN:test\nCOMPRESSED:2026-01-01\nSOURCE_TOKENS:~1000\nCUSTOM_FIELD:xyz\n\n"
        doc = parse(text, level=1)
        diags = validate(doc, level=1)
        w001s = [d for d in diags if d.code == "W001"]
        assert len(w001s) >= 1


class TestBodyValidation:
    def test_w002_underscore_in_section_name(self):
        text = "§CTX v1.0 L2 DOMAIN:test\nCOMPRESSED:2026-01-01\nSOURCE_TOKENS:~1000\n\n±SOME_SECTION\nfoo\n"
        doc = parse(text)
        diags = validate(doc)
        w002s = [d for d in diags if d.code == "W002"]
        assert len(w002s) >= 1
        assert "SOME_SECTION" in w002s[0].message

    def test_w003_non_canonical_order(self):
        text = "§CTX v1.0 L2 SCOPE:foo DOMAIN:test\nCOMPRESSED:2026-01-01\nSOURCE_TOKENS:~1000\n\n"
        doc = parse(text)
        diags = validate(doc)
        w003s = [d for d in diags if d.code == "W003"]
        assert len(w003s) >= 1


class TestFixtureValidation:
    def test_ctx_mod_no_errors(self):
        """ctx_mod.ctx should have zero errors (warnings OK)."""
        text = _read_fixture("ctx_mod.ctx")
        doc = parse(text)
        diags = validate(doc)
        errors = [d for d in diags if d.level == DiagnosticLevel.ERROR]
        assert len(errors) == 0

    def test_ctx_mod_has_underscore_warnings(self):
        """ctx_mod.ctx uses SALIENCE_SCORER — should trigger W002."""
        text = _read_fixture("ctx_mod.ctx")
        doc = parse(text)
        diags = validate(doc)
        w002s = [d for d in diags if d.code == "W002"]
        assert any("SALIENCE_SCORER" in d.message for d in w002s)

    def test_spec_l2_no_errors(self):
        """CTXPACK-SPEC.L2.ctx should have zero errors."""
        text = _read_fixture("spec/CTXPACK-SPEC.L2.ctx")
        doc = parse(text)
        diags = validate(doc)
        errors = [d for d in diags if d.level == DiagnosticLevel.ERROR]
        assert len(errors) == 0


class TestL3Validation:
    def test_e010_missing_l3_sections(self):
        text = "§CTX v1.0 L3 DOMAIN:test\nCOMPRESSED:2026-01-01\nSOURCE_TOKENS:~100\n\n±ENTITIES\nfoo\n"
        doc = parse(text)
        diags = validate(doc)
        e010s = [d for d in diags if d.code == "E010"]
        # Missing PATTERNS, CONSTRAINTS, WARNINGS
        assert len(e010s) == 3
        missing_names = {d.message.split("±")[1] for d in e010s}
        assert missing_names == {"PATTERNS", "CONSTRAINTS", "WARNINGS"}

    def test_l3_complete(self):
        text = (
            "§CTX v1.0 L3 DOMAIN:test\nCOMPRESSED:2026-01-01\nSOURCE_TOKENS:~100\n\n"
            "±ENTITIES\ne1\n±PATTERNS\np1\n±CONSTRAINTS\nc1\n±WARNINGS\nw1\n"
        )
        doc = parse(text)
        diags = validate(doc)
        e010s = [d for d in diags if d.code == "E010"]
        assert len(e010s) == 0
