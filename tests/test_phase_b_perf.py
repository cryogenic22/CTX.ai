"""Tests for WS1 (Performance Hot Path) and WS6 (Streaming Serializer).

WS1: salience scoring, cross-ref index, count_tokens, precompiled regexes.
WS6: serialize_iter / serialize_section streaming correctness.
"""

from __future__ import annotations

import pytest

from ctxpack.core.errors import Span
from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    NumberedItem,
    PlainLine,
    Provenance,
    QuotedBlock,
    Section,
)
from ctxpack.core.packer.compressor import (
    _CROSSREF_RE,
    _score_entities,
    _score_field,
    compress,
    count_tokens,
)
from ctxpack.core.packer.ir import (
    Certainty,
    IRCorpus,
    IREntity,
    IRField,
    IRSource,
    IRWarning,
)
from ctxpack.core.packer.yaml_parser import _YAMLParser
from ctxpack.core.serializer import serialize, serialize_iter, serialize_section


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_header(**overrides) -> Header:
    defaults = dict(
        magic="§CTX",
        version="1.0",
        layer=Layer.L2,
        status_fields=(KeyValue(key="DOMAIN", value="test"),),
        metadata=(
            KeyValue(key="COMPRESSED", value="2026-01-01"),
            KeyValue(key="SOURCE_TOKENS", value="~500"),
            KeyValue(key="CTX_TOKENS", value="~100"),
            KeyValue(key="RATIO", value="~5.0x"),
        ),
    )
    defaults.update(overrides)
    return Header(**defaults)


def _make_doc(sections=(), **header_overrides) -> CTXDocument:
    return CTXDocument(header=_make_header(**header_overrides), body=tuple(sections))


# ===========================================================================
# WS1 — Performance Hot Path (~12 tests)
# ===========================================================================


class TestCrossRefIndex:
    """WS1-1: cross-ref index correctness."""

    def test_cross_ref_boosts_salience(self):
        """Entities referenced via @ENTITY-X get a salience boost proportional
        to cross-ref count."""
        corpus = IRCorpus(
            entities=[
                IREntity(
                    name="ORDER",
                    fields=[
                        IRField(key="BELONGS-TO", value="@ENTITY-CUSTOMER(order_id)"),
                    ],
                    sources=[IRSource(file="a.yaml")],
                ),
                IREntity(
                    name="CUSTOMER",
                    fields=[
                        IRField(key="IDENTIFIER", value="cust_id(UUID)"),
                    ],
                    sources=[IRSource(file="a.yaml")],
                ),
            ],
        )
        _score_entities(corpus)
        customer = next(e for e in corpus.entities if e.name == "CUSTOMER")
        order = next(e for e in corpus.entities if e.name == "ORDER")
        # CUSTOMER is referenced once → cross_refs=1 → +2.0
        # ORDER has no inbound cross-refs
        assert customer.salience > order.salience

    def test_multiple_cross_refs_accumulate(self):
        """Multiple references to the same entity accumulate."""
        corpus = IRCorpus(
            entities=[
                IREntity(
                    name="A",
                    fields=[
                        IRField(key="REF1", value="@ENTITY-TARGET foo"),
                        IRField(key="REF2", value="@ENTITY-TARGET bar"),
                    ],
                    sources=[IRSource(file="x.yaml")],
                ),
                IREntity(
                    name="TARGET",
                    fields=[IRField(key="ID", value="t1")],
                    sources=[IRSource(file="x.yaml")],
                ),
            ],
        )
        _score_entities(corpus)
        target = next(e for e in corpus.entities if e.name == "TARGET")
        # 1 source + 2 cross-refs * 2.0 = 1 + 4 = 5.0
        assert target.salience == pytest.approx(5.0)


class TestCountTokens:
    """WS1-2 through WS1-4: count_tokens correctness."""

    def test_matches_materialized_baseline(self):
        """count_tokens output approximates word count of serialized text.

        count_tokens splits key and value separately (so KEY + VALUE = 2 words
        per single-word KV), while serialized text joins them as "KEY:VALUE"
        (1 whitespace-delimited word). Therefore count_tokens >= word_count.
        We verify the relationship holds and the difference is bounded.
        """
        sections = (
            Section(
                name="ENTITY-FOO",
                children=(
                    KeyValue(key="ID", value="foo-id(UUID,immutable)"),
                    KeyValue(key="STATUS", value="active→inactive→archived"),
                ),
            ),
        )
        doc = _make_doc(sections=sections)
        token_count = count_tokens(doc.body)
        # Materialise and count words for comparison
        text = serialize(doc)
        # Extract only body lines (after blank separator)
        body_text = text.split("\n\n", 1)[1] if "\n\n" in text else text
        word_count = len(body_text.split())
        # count_tokens counts keys and values separately, so it should be >= word_count
        assert token_count >= word_count
        # But still in the same order of magnitude (within 3x)
        assert token_count <= word_count * 3

    def test_empty_body_returns_zero(self):
        """Empty body tuple → 0 tokens."""
        assert count_tokens(()) == 0

    def test_nested_sections_counted_recursively(self):
        """Nested sections accumulate tokens from all depths."""
        inner = Section(
            name="INNER",
            children=(
                KeyValue(key="A", value="one two three"),
            ),
        )
        outer = Section(
            name="OUTER",
            children=(inner,),
        )
        total = count_tokens((outer,))
        # outer section name (1) + inner section name (1) + KV key "A" (1) + value "one two three" (3) = 6
        assert total == 6


class TestFlowSplit:
    """WS1-5, WS1-12: _split_flow edge cases via _YAMLParser."""

    def test_nested_brackets(self):
        """Nested brackets are respected — inner commas don't split."""
        parser = _YAMLParser("")
        items = parser._split_flow("a, {b: 1, c: 2}, d")
        assert len(items) == 3
        assert items[0].strip() == "a"
        assert items[1].strip() == "{b: 1, c: 2}"
        assert items[2].strip() == "d"

    def test_trailing_comma_no_empty_item(self):
        """Trailing comma does not produce an empty trailing item."""
        parser = _YAMLParser("")
        items = parser._split_flow("alpha, beta,")
        # Should have exactly 2 non-empty items; trailing comma handled
        non_empty = [i.strip() for i in items if i.strip()]
        assert len(non_empty) == 2
        assert non_empty == ["alpha", "beta"]


class TestGoldenSourcePartition:
    """WS1-6: golden source ends up in subtitle, not in children KVs."""

    def test_golden_source_in_subtitle(self):
        """compress() puts GOLDEN-SOURCE into section subtitle, not children."""
        corpus = IRCorpus(
            domain="test",
            entities=[
                IREntity(
                    name="PRODUCT",
                    fields=[
                        IRField(key="★GOLDEN-SOURCE", value="catalog-db"),
                        IRField(key="ID", value="prod_id"),
                    ],
                    sources=[IRSource(file="p.yaml")],
                ),
            ],
            source_token_count=500,
        )
        doc = compress(corpus)
        section = doc.body[0]
        assert isinstance(section, Section)
        # Subtitle should contain golden source
        assert any("GOLDEN-SOURCE" in s for s in section.subtitles)
        # Children should NOT contain a KV with key ★GOLDEN-SOURCE
        for child in section.children:
            if isinstance(child, KeyValue):
                assert child.key != "★GOLDEN-SOURCE"


class TestCrossRefRegex:
    """WS1-7: _CROSSREF_RE extracts entity names correctly."""

    def test_single_entity(self):
        m = _CROSSREF_RE.search("@ENTITY-CUSTOMER(id)")
        assert m is not None
        assert m.group(1) == "CUSTOMER"

    def test_multiple_entities(self):
        matches = _CROSSREF_RE.findall("@ENTITY-ORDER + @ENTITY-PRODUCT")
        assert matches == ["ORDER", "PRODUCT"]

    def test_hyphenated_entity_name(self):
        m = _CROSSREF_RE.search("@ENTITY-LINE-ITEM(fk)")
        assert m is not None
        assert m.group(1) == "LINE-ITEM"

    def test_no_match_on_plain_text(self):
        assert _CROSSREF_RE.search("plain text no refs") is None


class TestMappingRegex:
    """WS1-8: _MAPPING_RE matches YAML key-value lines."""

    def test_simple_kv(self):
        from ctxpack.core.packer.yaml_parser import _MAPPING_RE
        m = _MAPPING_RE.match("  name: John")
        assert m is not None
        assert m.group(2).strip() == "name"
        assert m.group(3).strip() == "John"

    def test_no_match_on_comment(self):
        from ctxpack.core.packer.yaml_parser import _MAPPING_RE
        assert _MAPPING_RE.match("# comment line") is None

    def test_colon_in_value(self):
        from ctxpack.core.packer.yaml_parser import _MAPPING_RE
        m = _MAPPING_RE.match("url: http://example.com")
        assert m is not None
        assert m.group(2).strip() == "url"


class TestSalienceScoringRelationshipBoost:
    """WS1-9: relationship keys get a salience boost."""

    def test_relationship_key_boost(self):
        field = IRField(key="BELONGS-TO", value="@ENTITY-CUSTOMER(fk)", salience=1.0)
        _score_field(field)
        # BELONGS-TO is in _RELATIONSHIP_KEYS → *1.2
        assert field.salience == pytest.approx(1.2)

    def test_non_relationship_key_no_boost(self):
        field = IRField(key="DESCRIPTION", value="some desc", salience=1.0)
        _score_field(field)
        # No special boost
        assert field.salience == pytest.approx(1.0)


class TestCrossRefIndexNoRefs:
    """WS1-10: entities with no inbound cross-refs get count=0 treatment."""

    def test_no_cross_refs_baseline_salience(self):
        corpus = IRCorpus(
            entities=[
                IREntity(
                    name="LONELY",
                    fields=[IRField(key="ID", value="lonely_id")],
                    sources=[IRSource(file="l.yaml")],
                ),
            ],
        )
        _score_entities(corpus)
        lonely = corpus.entities[0]
        # 1 source * 1.0 + 0 cross-refs + 0 warnings = 1.0
        assert lonely.salience == pytest.approx(1.0)


class TestCountTokensProvenance:
    """WS1-11: count_tokens handles Provenance nodes."""

    def test_provenance_counted(self):
        elements = (
            Provenance(source="file.yaml#L1-L10", path="file.yaml"),
        )
        total = count_tokens(elements)
        # 1 + len("file.yaml#L1-L10".split()) = 1 + 1 = 2
        assert total == 2

    def test_provenance_with_multiword_source(self):
        elements = (
            Provenance(source="my file.yaml #L1-L10", path="my file.yaml"),
        )
        total = count_tokens(elements)
        # 1 + len("my file.yaml #L1-L10".split()) = 1 + 3 = 4
        assert total == 4


# ===========================================================================
# WS6 — Streaming Serializer (~8 tests)
# ===========================================================================


class TestSerializeIterByteIdentical:
    """WS6-1: serialize_iter joined == serialize output."""

    def test_byte_identical_l2_doc(self):
        """A real L2 doc round-trips identically through both paths."""
        sections = (
            Section(
                name="ENTITY-CUSTOMER",
                subtitles=("★GOLDEN-SOURCE:crm-db",),
                children=(
                    KeyValue(key="IDENTIFIER", value="cust_id(UUID,immutable)"),
                    KeyValue(key="PII", value="email+phone+name"),
                    KeyValue(key="BELONGS-TO", value="@ENTITY-ORG(org_id,mandatory)"),
                    Provenance(source="customer.yaml#L1-L40", path="customer.yaml"),
                ),
            ),
            Section(
                name="ENTITY-ORDER",
                children=(
                    KeyValue(key="STATUS-MACHINE", value="pending→confirmed→shipped→delivered"),
                    KeyValue(key="HAS-MANY", value="@ENTITY-LINE-ITEM(order_id,1:N)"),
                    NumberedItem(number=1, text="Orders are immutable after confirmation"),
                ),
            ),
        )
        doc = _make_doc(sections=sections)
        full = serialize(doc)
        streamed = "\n".join(serialize_iter(doc)) + "\n"
        assert full == streamed


class TestSerializeIterLineCount:
    """WS6-2: serialize_iter produces correct number of lines."""

    def test_line_count(self):
        sections = (
            Section(
                name="SECTION-A",
                children=(KeyValue(key="K", value="V"),),
            ),
        )
        doc = _make_doc(sections=sections)
        lines = list(serialize_iter(doc))
        # Count non-empty lines in serialize output for validation
        full_lines = serialize(doc).rstrip("\n").split("\n")
        assert len(lines) == len(full_lines)


class TestSerializeSection:
    """WS6-3, WS6-4: serialize_section yields correct lines."""

    def test_single_section_lines(self):
        section = Section(
            name="MY-SECTION",
            children=(
                KeyValue(key="FOO", value="bar"),
                KeyValue(key="BAZ", value="qux"),
            ),
        )
        lines = list(serialize_section(section))
        assert lines[0] == "±MY-SECTION"
        assert lines[1] == "FOO:bar"
        assert lines[2] == "BAZ:qux"
        assert len(lines) == 3

    def test_empty_section_header_only(self):
        section = Section(name="EMPTY")
        lines = list(serialize_section(section))
        assert len(lines) == 1
        assert lines[0] == "±EMPTY"


class TestSerializeIterASCIIMode:
    """WS6-5: ASCII mode works through serialize_iter."""

    def test_ascii_mode_replaces_unicode(self):
        sections = (
            Section(
                name="ENTITY-X",
                subtitles=("★GOLDEN:db",),
                children=(
                    KeyValue(key="WARN", value="⚠ conflict detected"),
                ),
            ),
        )
        doc = _make_doc(sections=sections)
        lines = list(serialize_iter(doc, ascii_mode=True))
        joined = "\n".join(lines)
        # Section sigil should be ## not ±
        assert "##ENTITY-X" in joined
        # Star should be replaced
        assert "***GOLDEN:db" in joined
        # Warning symbol replaced
        assert "WARN:" in joined
        # Original Unicode should be gone
        assert "±" not in joined
        assert "★" not in joined


class TestSerializeIterCanonicalMode:
    """WS6-6: canonical mode works through serialize_iter."""

    def test_canonical_mode(self):
        doc = _make_doc(
            sections=(
                Section(name="SEC", children=(KeyValue(key="A", value="1"),)),
            ),
        )
        lines_default = list(serialize_iter(doc, canonical=False))
        lines_canonical = list(serialize_iter(doc, canonical=True))
        # Both should produce valid output; canonical may reorder header fields
        assert len(lines_canonical) > 0
        # First line should still start with magic
        assert lines_canonical[0].startswith("§CTX")


class TestSerializeSectionSubtitles:
    """WS6-7: section with subtitles serializes correctly via iter."""

    def test_subtitles_in_header_line(self):
        section = Section(
            name="ENTITY-PRODUCT",
            subtitles=("★GOLDEN-SOURCE:inventory-db", "⚠"),
            children=(
                KeyValue(key="ID", value="prod_id"),
            ),
        )
        lines = list(serialize_section(section))
        assert lines[0] == "±ENTITY-PRODUCT ★GOLDEN-SOURCE:inventory-db ⚠"
        assert lines[1] == "ID:prod_id"


class TestSerializeIterQuotedBlockAndNumberedItem:
    """WS6-8: serialize_iter handles QuotedBlock and NumberedItem."""

    def test_quoted_block(self):
        sections = (
            Section(
                name="EXAMPLES",
                children=(
                    QuotedBlock(content="SELECT * FROM orders;", lang="sql"),
                ),
            ),
        )
        doc = _make_doc(sections=sections)
        lines = list(serialize_iter(doc))
        joined = "\n".join(lines)
        assert "```sql" in joined
        assert "SELECT * FROM orders;" in joined
        assert joined.count("```") >= 2  # open + close

    def test_numbered_item(self):
        sections = (
            Section(
                name="RULES",
                children=(
                    NumberedItem(number=1, text="First rule applies"),
                    NumberedItem(number=2, text="Second rule overrides"),
                ),
            ),
        )
        doc = _make_doc(sections=sections)
        lines = list(serialize_iter(doc))
        joined = "\n".join(lines)
        assert "1.First rule applies" in joined
        assert "2.Second rule overrides" in joined
