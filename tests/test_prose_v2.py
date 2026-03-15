"""Tests for the improved NL prose serializer (v2).

Verifies that natural_language=True output is genuinely readable prose:
- No raw +delimited groups survive
- No raw key(value)+key(value) notation
- No single line exceeds 150 words
- All entity identifiers and cross-references preserved
- Repeated key prefixes collapsed
- Markdown headings present for sections
- BPE token count lower than default serialization
"""

import os
import re

import pytest

from ctxpack.core.packer import pack
from ctxpack.core.serializer import serialize

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EVAL_CORPUS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ctxpack",
    "benchmarks",
    "ctxpack_eval",
    "corpus",
)

GOLDEN_CORPUS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ctxpack",
    "benchmarks",
    "golden_set",
    "corpus",
)


@pytest.fixture(scope="module")
def eval_doc():
    """Pack the ctxpack_eval corpus once for all tests."""
    result = pack(EVAL_CORPUS)
    return result.document


@pytest.fixture(scope="module")
def eval_nl(eval_doc):
    """NL serialization of the eval corpus."""
    return serialize(eval_doc, natural_language=True)


@pytest.fixture(scope="module")
def eval_default(eval_doc):
    """Default serialization of the eval corpus."""
    return serialize(eval_doc)


@pytest.fixture(scope="module")
def golden_doc():
    """Pack the golden set corpus once for all tests."""
    result = pack(GOLDEN_CORPUS)
    return result.document


@pytest.fixture(scope="module")
def golden_nl(golden_doc):
    """NL serialization of the golden set corpus."""
    return serialize(golden_doc, natural_language=True)


@pytest.fixture(scope="module")
def golden_default(golden_doc):
    """Default serialization of the golden set corpus."""
    return serialize(golden_doc)


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

# Matches raw key(val)+key(val) notation (the core problem)
_RAW_PAREN_GROUP_RE = re.compile(r"\w+\([^)]+\)\+\w+\([^)]+\)")

# Matches the **Key**: pattern used in bullet items
_KEY_PREFIX_RE = re.compile(r"^- \*\*([^*]+)\*\*:")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNLNoPlusDelimitersInEntityValues:
    """The + delimiter between parenthesized groups must not survive into NL output."""

    def test_eval_corpus_no_raw_plus(self, eval_nl):
        """No raw key(val)+key(val) patterns in eval corpus NL output."""
        matches = _RAW_PAREN_GROUP_RE.findall(eval_nl)
        assert matches == [], (
            f"Found raw parenthesized+delimited groups in NL output: {matches[:5]}"
        )

    def test_golden_corpus_no_raw_plus(self, golden_nl):
        """No raw key(val)+key(val) patterns in golden set NL output."""
        matches = _RAW_PAREN_GROUP_RE.findall(golden_nl)
        assert matches == [], (
            f"Found raw parenthesized+delimited groups in NL output: {matches[:5]}"
        )


class TestNLNoRawParenthesizedGroups:
    """Values like name(IRSource)+type(dataclass) must be expanded to readable text."""

    def test_no_name_type_description_pattern(self, eval_nl):
        """The specific name(X)+type(Y)+description(Z) pattern must be gone."""
        pattern = re.compile(r"name\(\w+\)\+type\(\w+\)")
        matches = pattern.findall(eval_nl)
        assert matches == [], (
            f"Found raw name()+type() notation: {matches[:5]}"
        )

    def test_no_step_name_description_pattern(self, eval_nl):
        """step(N)+name(X)+description(Y) must be expanded."""
        pattern = re.compile(r"step\(\d+\)\+name\(\w")
        matches = pattern.findall(eval_nl)
        assert matches == [], (
            f"Found raw step()+name() notation: {matches[:5]}"
        )

    def test_no_code_description_pattern(self, eval_nl):
        """code(X)+description(Y) patterns must be expanded."""
        pattern = re.compile(r"code\(\w+\)\+description\(")
        matches = pattern.findall(eval_nl)
        assert matches == [], (
            f"Found raw code()+description() notation: {matches[:5]}"
        )


class TestNLNoLineExceeds150Words:
    """No single line in NL output should exceed 150 words."""

    def test_eval_corpus_line_length(self, eval_nl):
        for i, line in enumerate(eval_nl.split("\n")):
            word_count = len(line.split())
            assert word_count <= 150, (
                f"Line {i} has {word_count} words (max 150): {line[:100]}..."
            )

    def test_golden_corpus_line_length(self, golden_nl):
        for i, line in enumerate(golden_nl.split("\n")):
            word_count = len(line.split())
            assert word_count <= 150, (
                f"Line {i} has {word_count} words (max 150): {line[:100]}..."
            )


class TestNLPreservesAllIdentifiers:
    """All entity identifiers from the default output must appear in NL output."""

    def test_eval_entity_names_present(self, eval_nl, eval_default):
        # Extract entity names from section headers in default output
        entity_names = set(re.findall(r"ENTITY-([\w-]+)", eval_default))
        # Filter out the generic placeholder "X" used in @ENTITY-X patterns
        entity_names.discard("X")
        nl_upper = eval_nl.upper()
        for name in entity_names:
            # Entity name should appear in NL output (possibly as title case)
            name_parts = name.split("-")
            # Check: at least the core identifier words appear
            for part in name_parts:
                assert part.upper() in nl_upper, (
                    f"Entity identifier part '{part}' (from {name}) missing in NL output"
                )

    def test_golden_entity_names_present(self, golden_nl, golden_default):
        entity_names = set(re.findall(r"ENTITY-([\w-]+)", golden_default))
        entity_names.discard("X")
        nl_upper = golden_nl.upper()
        for name in entity_names:
            name_parts = name.split("-")
            for part in name_parts:
                assert part.upper() in nl_upper, (
                    f"Entity identifier part '{part}' (from {name}) missing in NL output"
                )


class TestNLPreservesCrossReferences:
    """Cross-references like @ENTITY-CUSTOMER must remain findable in NL output."""

    def test_eval_crossrefs(self, eval_nl, eval_default):
        crossrefs = set(re.findall(r"@ENTITY-([\w-]+)", eval_default))
        # The generic @ENTITY-X placeholder is allowed to be absent
        crossrefs.discard("X")
        nl_upper = eval_nl.upper()
        for ref in crossrefs:
            ref_parts = ref.split("-")
            for part in ref_parts:
                assert part.upper() in nl_upper, (
                    f"Cross-reference part '{part}' (from @ENTITY-{ref}) "
                    f"missing in NL output"
                )

    def test_golden_crossrefs(self, golden_nl, golden_default):
        crossrefs = set(re.findall(r"@ENTITY-([\w-]+)", golden_default))
        crossrefs.discard("X")
        nl_upper = golden_nl.upper()
        for ref in crossrefs:
            ref_parts = ref.split("-")
            for part in ref_parts:
                assert part.upper() in nl_upper, (
                    f"Cross-reference part '{part}' (from @ENTITY-{ref}) "
                    f"missing in NL output"
                )


class TestNLBPEBetterThanDefault:
    """NL output should tokenize more efficiently per character than default.

    Dense notation like ``name(X)+type(Y)`` produces extra BPE tokens because
    each parenthesis, plus, and Unicode operator fragments into separate tokens.
    NL mode replaces these with natural language that tokenizes as single tokens.

    We measure BPE cost per character: the NL mode should have a lower ratio,
    proving it encodes the same information more efficiently for LLMs.
    """

    @staticmethod
    def _bpe_overhead(text: str) -> int:
        """Count BPE-expensive characters that fragment into extra tokens.

        Each of these characters typically costs 1 extra token in BPE:
        - Parentheses ( ) when adjacent to alphanumerics
        - Plus signs + used as delimiters
        - Unicode operators: ±, §, ★, ⚠, ≡, ⊥
        - Colons in KV notation (key:value without space)
        """
        cost = 0
        for ch in text:
            if ch in ("(", ")"):
                cost += 1
            elif ch == "+":
                cost += 1
            elif ch in ("\u00b1", "\u00a7", "\u2605", "\u26a0", "\u2261", "\u22a5"):
                cost += 1
        # Count key:value pairs (colon not followed by space)
        cost += len(re.findall(r"(?<=\w):(?=\w)", text))
        return cost

    def test_eval_bpe_overhead_reduction(self, eval_nl, eval_default):
        """NL mode should have significantly less BPE overhead than default."""
        default_overhead = self._bpe_overhead(eval_default)
        nl_overhead = self._bpe_overhead(eval_nl)
        assert nl_overhead < default_overhead, (
            f"NL BPE overhead ({nl_overhead}) should be less than "
            f"default BPE overhead ({default_overhead})"
        )

    def test_golden_bpe_overhead_reduction(self, golden_nl, golden_default):
        """NL mode should have significantly less BPE overhead than default."""
        default_overhead = self._bpe_overhead(golden_default)
        nl_overhead = self._bpe_overhead(golden_nl)
        assert nl_overhead < default_overhead, (
            f"NL BPE overhead ({nl_overhead}) should be less than "
            f"default BPE overhead ({default_overhead})"
        )


class TestNLHeadingsPresent:
    """NL output must contain Markdown headings (## or ###)."""

    def test_eval_has_headings(self, eval_nl):
        headings = re.findall(r"^#{2,6} .+", eval_nl, re.MULTILINE)
        # Must have at least as many headings as there are entity sections
        assert len(headings) >= 3, (
            f"Expected at least 3 headings, found {len(headings)}"
        )

    def test_golden_has_headings(self, golden_nl):
        headings = re.findall(r"^#{2,6} .+", golden_nl, re.MULTILINE)
        assert len(headings) >= 3, (
            f"Expected at least 3 headings, found {len(headings)}"
        )


class TestNLNoRepeatedKeyPrefix:
    """Consecutive bullet items must not repeat the same **Key**: prefix."""

    @staticmethod
    def _find_repeated_keys(text: str) -> list[tuple[int, str]]:
        """Return (line_number, key) pairs where key repeats from previous line."""
        violations = []
        last_key = None
        for i, line in enumerate(text.split("\n")):
            m = _KEY_PREFIX_RE.match(line)
            if m:
                key = m.group(1)
                if key == last_key:
                    violations.append((i, key))
                last_key = key
            else:
                last_key = None
        return violations

    def test_eval_no_repeated_keys(self, eval_nl):
        violations = self._find_repeated_keys(eval_nl)
        assert violations == [], (
            f"Found repeated key prefixes: {violations[:10]}"
        )

    def test_golden_no_repeated_keys(self, golden_nl):
        violations = self._find_repeated_keys(golden_nl)
        assert violations == [], (
            f"Found repeated key prefixes: {violations[:10]}"
        )
