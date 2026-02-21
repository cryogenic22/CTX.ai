"""Tests for parser hardening H1-H5."""

import pytest
from ctxpack.core.parser import parse
from ctxpack.core.model import (
    InlineList,
    KeyValue,
    PlainLine,
    QuotedBlock,
    Section,
)
from ctxpack.core.validator import validate
from ctxpack.core.errors import DiagnosticLevel


class TestH1ExplicitDepth:
    """H1: Explicit depth markers ±N SECTION-NAME."""

    def test_depth_marker_parsed(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±2 SUBSECTION\nfoo\n"
        doc = parse(text)
        sec = doc.body[0]
        assert isinstance(sec, Section)
        assert sec.name == "SUBSECTION"
        assert sec.depth == 2

    def test_depth_marker_with_subtitle(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±1 SECTION SUBTITLE\nfoo\n"
        doc = parse(text)
        sec = doc.body[0]
        assert sec.depth == 1
        assert sec.subtitles == ("SUBTITLE",)

    def test_no_depth_marker_uses_indent(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SECTION\nfoo\n"
        doc = parse(text)
        sec = doc.body[0]
        assert sec.depth == 0  # indent=0, depth = 0//2 = 0

    def test_ascii_with_depth_marker(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n##3 DEEP-SECTION\nfoo\n"
        doc = parse(text)
        sec = doc.body[0]
        assert sec.name == "DEEP-SECTION"
        assert sec.depth == 3


class TestH2InlineList:
    """H2: InlineList detection in _classify_line."""

    def test_inline_list_detected(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\n[alpha, beta, gamma]\n"
        doc = parse(text)
        item = doc.body[0].children[0]
        assert isinstance(item, InlineList)
        assert item.items == ("alpha", "beta", "gamma")

    def test_inline_list_single_item(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\n[only]\n"
        doc = parse(text)
        item = doc.body[0].children[0]
        assert isinstance(item, InlineList)
        assert item.items == ("only",)

    def test_kv_with_brackets_not_inline_list(self):
        """KEY:[a,b] should still be a KeyValue, not InlineList."""
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nKEY:[a,b]\n"
        doc = parse(text)
        item = doc.body[0].children[0]
        assert isinstance(item, KeyValue)
        assert item.key == "KEY"


class TestH3UnclosedBrackets:
    """H3: Unclosed bracket handling → W004 diagnostic."""

    def test_unclosed_bracket_produces_warning(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nKEY:[unclosed\n"
        doc = parse(text)
        diags = validate(doc)
        w004 = [d for d in diags if d.code == "W004"]
        assert len(w004) >= 1

    def test_closed_brackets_no_warning(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nKEY:[closed]\n"
        doc = parse(text)
        diags = validate(doc)
        w004 = [d for d in diags if d.code == "W004"]
        assert len(w004) == 0


class TestH4QuotationEdgeCases:
    """H4: Unclosed triple-backtick and empty quoted blocks."""

    def test_unclosed_backtick_consumed_to_eof(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\n```python\ndef foo():\n    pass\n"
        doc = parse(text)
        item = doc.body[0].children[0]
        assert isinstance(item, QuotedBlock)
        assert "def foo():" in item.content

    def test_unclosed_backtick_warning(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\n```python\ndef foo():\n"
        doc = parse(text)
        diags = validate(doc)
        w005 = [d for d in diags if d.code == "W005"]
        assert len(w005) >= 1

    def test_empty_quoted_block(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\n```\n```\n"
        doc = parse(text)
        item = doc.body[0].children[0]
        assert isinstance(item, QuotedBlock)
        assert item.content == ""

    def test_closed_backtick_no_warning(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\n```\ncode\n```\n"
        doc = parse(text)
        diags = validate(doc)
        w005 = [d for d in diags if d.code == "W005"]
        assert len(w005) == 0


class TestH5ASCIIFallback:
    """H5: ASCII fallback tests for negation, WARN, ===, CONFLICT, mixed."""

    def test_negation_operator(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nTYPE:DECIMAL(19,4)¬FLOAT\n"
        doc = parse(text)
        kv = doc.body[0].children[0]
        assert isinstance(kv, KeyValue)
        assert "¬FLOAT" in kv.value

    def test_ascii_negation(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nTYPE:DECIMAL(19,4)!FLOAT\n"
        doc = parse(text)
        kv = doc.body[0].children[0]
        assert "!FLOAT" in kv.value

    def test_warn_prefix(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nWARN:SKU-format-inconsistency\n"
        doc = parse(text)
        kv = doc.body[0].children[0]
        assert kv.key == "WARN"

    def test_equivalence_operator(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nMAPPING:client≡customer\n"
        doc = parse(text)
        kv = doc.body[0].children[0]
        assert "≡" in kv.value

    def test_ascii_equivalence(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nMAPPING:client===customer\n"
        doc = parse(text)
        kv = doc.body[0].children[0]
        assert "===" in kv.value

    def test_conflict_operator(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nPOLICY:36-months⊥7-years\n"
        doc = parse(text)
        kv = doc.body[0].children[0]
        assert "⊥" in kv.value

    def test_ascii_conflict(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nCONFLICT:retention-mismatch\n"
        doc = parse(text)
        kv = doc.body[0].children[0]
        assert kv.key == "CONFLICT"

    def test_mixed_unicode_ascii(self):
        """File with both Unicode and ASCII operators."""
        text = (
            "§CTX v1.0 L2 DOMAIN:test\n\n"
            "±SEC\n"
            "ARROW:a→b\n"
            "ASCII-ARROW:a->b\n"
            "STAR:★important\n"
            "ASCII-STAR:***important\n"
        )
        doc = parse(text)
        children = doc.body[0].children
        assert len(children) == 4
        keys = [c.key for c in children if isinstance(c, KeyValue)]
        assert "ARROW" in keys
        assert "ASCII-ARROW" in keys
