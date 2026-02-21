"""Tests for the .ctx serializer — round-trip and formatting modes."""

import os
import pytest

from ctxpack.core.parser import parse
from ctxpack.core.serializer import serialize
from ctxpack.core.model import Section, KeyValue

FIXTURES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestRoundTrip:
    def test_simple_roundtrip(self):
        text = "§CTX v1.0 L2 DOMAIN:test\nCOMPRESSED:2026-01-01\n\n±SECTION\nKEY:value\n"
        doc = parse(text)
        output = serialize(doc)
        doc2 = parse(output)
        assert doc2.header.magic == doc.header.magic
        assert doc2.header.version == doc.header.version
        assert doc2.header.layer == doc.header.layer
        assert doc2.header.get("DOMAIN") == doc.header.get("DOMAIN")

    def test_roundtrip_preserves_sections(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±ALPHA\nfoo\n±BETA\nbar\n"
        doc = parse(text)
        output = serialize(doc)
        doc2 = parse(output)
        names1 = [e.name for e in doc.body if isinstance(e, Section)]
        names2 = [e.name for e in doc2.body if isinstance(e, Section)]
        assert names1 == names2

    def test_roundtrip_preserves_kv(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nKEY:value with:colons\n"
        doc = parse(text)
        output = serialize(doc)
        doc2 = parse(output)
        sec = doc2.body[0]
        assert isinstance(sec, Section)
        kv = sec.children[0]
        assert isinstance(kv, KeyValue)
        assert kv.key == "KEY"
        assert kv.value == "value with:colons"

    def test_ast_equivalence_ctx_mod(self):
        """Parse → serialize → parse produces equivalent AST for ctx_mod.ctx."""
        text = _read_fixture("ctx_mod.ctx")
        doc1 = parse(text)
        output = serialize(doc1)
        doc2 = parse(output)
        # Same header
        assert doc1.header.magic == doc2.header.magic
        assert doc1.header.version == doc2.header.version
        assert doc1.header.layer == doc2.header.layer
        # Same number of top-level body elements
        secs1 = [e for e in doc1.body if isinstance(e, Section)]
        secs2 = [e for e in doc2.body if isinstance(e, Section)]
        assert len(secs1) == len(secs2)
        # Same section names
        assert [s.name for s in secs1] == [s.name for s in secs2]

    def test_ast_equivalence_spec_l2(self):
        """Parse → serialize → parse produces equivalent AST for CTXPACK-SPEC.L2.ctx."""
        text = _read_fixture("spec/CTXPACK-SPEC.L2.ctx")
        doc1 = parse(text)
        output = serialize(doc1)
        doc2 = parse(output)
        assert doc1.header.magic == doc2.header.magic
        secs1 = [e for e in doc1.body if isinstance(e, Section)]
        secs2 = [e for e in doc2.body if isinstance(e, Section)]
        assert [s.name for s in secs1] == [s.name for s in secs2]


class TestAsciiMode:
    def test_ascii_replaces_section_marker(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SECTION\nfoo\n"
        doc = parse(text)
        output = serialize(doc, ascii_mode=True)
        assert "##SECTION" in output
        assert "±" not in output

    def test_ascii_replaces_magic(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n"
        doc = parse(text)
        output = serialize(doc, ascii_mode=True)
        assert output.startswith("$CTX")

    def test_ascii_replaces_arrows(self):
        text = "§CTX v1.0 L2 DOMAIN:test\n\n±SEC\nKEY:a→b\n"
        doc = parse(text)
        output = serialize(doc, ascii_mode=True)
        assert "a->b" in output
        assert "→" not in output

    def test_ascii_ctx_mod(self):
        """ASCII mode on ctx_mod.ctx produces valid ASCII-only output."""
        text = _read_fixture("ctx_mod.ctx")
        doc = parse(text)
        output = serialize(doc, ascii_mode=True)
        # Should still be parseable
        doc2 = parse(output)
        assert doc2.header.magic == "$CTX"
        # No §, ±, →, ¬, ★, ⚠, ≡, ⊥ in output
        for ch in "§±→¬★⚠≡⊥":
            assert ch not in output, f"Found Unicode char {ch!r} in ASCII output"


class TestCanonicalMode:
    def test_canonical_reorders_fields(self):
        text = "§CTX v1.0 L2 SCOPE:foo DOMAIN:test\nTURNS:5\nCOMPRESSED:2026-01-01\nSOURCE_TOKENS:~1000\n\n"
        doc = parse(text)
        output = serialize(doc, canonical=True)
        lines = output.strip().split("\n")
        # DOMAIN should be on status line in canonical mode
        assert "DOMAIN:test" in lines[0]
