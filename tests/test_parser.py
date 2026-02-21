"""Tests for the .ctx parser."""

import os
import pytest

from ctxpack.core.parser import parse
from ctxpack.core.errors import ParseError
from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    NumberedItem,
    PlainLine,
    QuotedBlock,
    Section,
)

FIXTURES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── Level 1: Header parsing ──


class TestHeaderParsing:
    def test_magic_section_sign(self):
        doc = parse("§CTX v1.0 L2 DOMAIN:test\n\n", level=1)
        assert doc.header.magic == "§CTX"

    def test_magic_dollar_sign(self):
        doc = parse("$CTX v1.0 L2 DOMAIN:test\n\n", level=1)
        assert doc.header.magic == "$CTX"

    def test_version(self):
        doc = parse("§CTX v1.0 L2 DOMAIN:test\n\n", level=1)
        assert doc.header.version == "1.0"

    def test_layer_l2(self):
        doc = parse("§CTX v1.0 L2 DOMAIN:test\n\n", level=1)
        assert doc.header.layer == Layer.L2

    def test_layer_manifest(self):
        doc = parse("§CTX v1.0 MANIFEST DOMAIN:test\n\n", level=1)
        assert doc.header.layer == Layer.MANIFEST

    def test_status_line_fields(self):
        doc = parse(
            "§CTX v1.0 L2 DOMAIN:test SCOPE:foo AUTHOR:bar\n\n", level=1
        )
        assert doc.header.get("DOMAIN") == "test"
        assert doc.header.get("SCOPE") == "foo"
        assert doc.header.get("AUTHOR") == "bar"

    def test_multi_kv_metadata_line(self):
        text = "§CTX v1.0 L2 DOMAIN:test\nCOMPRESSED:2026-02-21 SOURCE_TOKENS:~40000 TURNS:10\n\n"
        doc = parse(text, level=1)
        assert doc.header.get("COMPRESSED") == "2026-02-21"
        assert doc.header.get("SOURCE_TOKENS") == "~40000"
        assert doc.header.get("TURNS") == "10"

    def test_invalid_magic_raises(self):
        with pytest.raises(ParseError, match="magic"):
            parse("INVALID v1.0 L2\n\n")

    def test_missing_version_raises(self):
        with pytest.raises(ParseError, match="version"):
            parse("§CTX L2\n\n")

    def test_missing_layer_raises(self):
        with pytest.raises(ParseError, match="layer"):
            parse("§CTX v1.0\n\n")

    def test_ctx_mod_header(self):
        text = _read_fixture("ctx_mod.ctx")
        doc = parse(text, level=1)
        assert doc.header.magic == "§CTX"
        assert doc.header.version == "1.0"
        assert doc.header.layer == Layer.L2
        assert doc.header.get("DOMAIN") == "ai-infrastructure"
        assert doc.header.get("SCOPE") == "ctxpack-concept-development"
        assert doc.header.get("AUTHOR") == "kapil-pant(SynaptyX-CEO)"
        assert doc.header.get("COMPRESSED") == "2026-02-21"
        assert doc.header.get("SOURCE_TOKENS") == "~40000"
        assert doc.header.get("TURNS") == "10"

    def test_spec_l2_header(self):
        text = _read_fixture("spec/CTXPACK-SPEC.L2.ctx")
        doc = parse(text, level=1)
        assert doc.header.magic == "§CTX"
        assert doc.header.layer == Layer.L2
        assert doc.header.get("DOMAIN") == "ctxpack-spec"
        assert doc.header.get("CTX_TOKENS") == "~600"
        assert doc.header.get("RATIO") == "~7.5x"


# ── Level 2: Body parsing ──


class TestBodyParsing:
    def test_section_basic(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±GENESIS\nfoo\n"
        doc = parse(text)
        assert len(doc.body) == 1
        sec = doc.body[0]
        assert isinstance(sec, Section)
        assert sec.name == "GENESIS"

    def test_section_with_subtitle(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±ARCHITECTURE MULTI-RESOLUTION-CODEC\nfoo\n"
        doc = parse(text)
        sec = doc.body[0]
        assert isinstance(sec, Section)
        assert sec.name == "ARCHITECTURE"
        assert sec.subtitles == ("MULTI-RESOLUTION-CODEC",)

    def test_section_with_star_subtitle(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SALIENCE_SCORER ★HEART-OF-SYSTEM\nfoo\n"
        doc = parse(text)
        sec = doc.body[0]
        assert sec.name == "SALIENCE_SCORER"
        assert sec.subtitles == ("★HEART-OF-SYSTEM",)

    def test_nested_sections(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±ARCHITECTURE\n\n  ±LAYERS\n  L0:raw\n  L1:prose\n"
        doc = parse(text)
        arch = doc.body[0]
        assert isinstance(arch, Section)
        assert arch.name == "ARCHITECTURE"
        # LAYERS should be a child of ARCHITECTURE
        layers = [c for c in arch.children if isinstance(c, Section)]
        assert len(layers) == 1
        assert layers[0].name == "LAYERS"

    def test_kv_pair(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nKEY:value\n"
        doc = parse(text)
        sec = doc.body[0]
        assert isinstance(sec, Section)
        kv = sec.children[0]
        assert isinstance(kv, KeyValue)
        assert kv.key == "KEY"
        assert kv.value == "value"

    def test_kv_colon_in_value(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nURL:https://example.com:8080\n"
        doc = parse(text)
        kv = doc.body[0].children[0]
        assert isinstance(kv, KeyValue)
        assert kv.key == "URL"
        assert kv.value == "https://example.com:8080"

    def test_numbered_item(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\n1.first\n2.second\n"
        doc = parse(text)
        items = doc.body[0].children
        assert len(items) == 2
        assert isinstance(items[0], NumberedItem)
        assert items[0].number == 1
        assert items[0].text == "first"

    def test_multiline_bracket_value(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nSEQUENCE[\n  W1:foo,\n  W2:bar\n]\n"
        doc = parse(text)
        kv = doc.body[0].children[0]
        assert isinstance(kv, KeyValue)
        assert kv.key == "SEQUENCE"
        assert "W1:foo" in kv.value
        assert "W2:bar" in kv.value

    def test_nested_brackets(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nSTRUCT:ctxpack/[core/[a,b],cli/[c]]\n"
        doc = parse(text)
        kv = doc.body[0].children[0]
        assert isinstance(kv, KeyValue)
        assert kv.key == "STRUCT"
        assert "ctxpack/[core/[a,b],cli/[c]]" in kv.value

    def test_quoted_block(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\n```python\ndef foo():\n    pass\n```\n"
        doc = parse(text)
        qb = doc.body[0].children[0]
        assert isinstance(qb, QuotedBlock)
        assert qb.lang == "python"
        assert "def foo():" in qb.content

    def test_plain_line(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\njust some text here\n"
        doc = parse(text)
        pl = doc.body[0].children[0]
        assert isinstance(pl, PlainLine)
        assert pl.text == "just some text here"

    def test_ctx_mod_full_parse(self):
        """Parse ctx_mod.ctx and verify structure."""
        text = _read_fixture("ctx_mod.ctx")
        doc = parse(text)
        # Should have top-level sections
        sections = [e for e in doc.body if isinstance(e, Section)]
        section_names = [s.name for s in sections]
        assert "GENESIS" in section_names
        assert "ARCHITECTURE" in section_names
        assert "SALIENCE_SCORER" in section_names
        assert "CTX-FORMAT-DESIGN" in section_names
        assert "STRATEGY-DECISIONS" in section_names
        assert "REPO-STRUCTURE" in section_names
        assert "KEY-CITATIONS" in section_names
        assert "IMMEDIATE-NEXT-STEPS" in section_names
        # At least 10 top-level sections
        assert len(sections) >= 10

    def test_spec_l2_full_parse(self):
        """Parse CTXPACK-SPEC.L2.ctx and verify structure."""
        text = _read_fixture("spec/CTXPACK-SPEC.L2.ctx")
        doc = parse(text)
        sections = [e for e in doc.body if isinstance(e, Section)]
        section_names = [s.name for s in sections]
        assert "HYDRATION-RULES" in section_names
        assert "POSITION-OPTIMIZATION" in section_names
        assert "MCP-TOOLS" in section_names

    def test_ctx_mod_architecture_subsections(self):
        """Verify ARCHITECTURE has nested subsections."""
        text = _read_fixture("ctx_mod.ctx")
        doc = parse(text)
        arch = next(
            e for e in doc.body if isinstance(e, Section) and e.name == "ARCHITECTURE"
        )
        child_sections = [c for c in arch.children if isinstance(c, Section)]
        child_names = [s.name for s in child_sections]
        assert "LAYERS" in child_names
        assert "PACKER" in child_names
        assert "UNPACKER" in child_names
        assert "VARIABLE-BITRATE" in child_names

    def test_ascii_section_marker(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n##SECTION\nfoo\n"
        doc = parse(text)
        sec = doc.body[0]
        assert isinstance(sec, Section)
        assert sec.name == "SECTION"
