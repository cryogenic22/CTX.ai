"""DI-01 exact-literal identity — HELPER-LEVEL tests of the identity primitive.

Scope note (honest labelling per the Loop 1 packet): these exercise
``exact_fact_id`` directly. They do NOT prove the end-to-end user outcome
(case-distinct identifiers surviving parser -> checkpoint -> stored records ->
recall/why); that is a separate, later acceptance set in the functional
routing slice. Red-on-parent for the new API is an ImportError (the symbol
does not exist on the parent commit); the legacy-collision assertion here is a
REPRODUCTION CONTROL of the bug being fixed, not a red-on-parent success.
"""
import hashlib
import re

import pytest

from ctxpack.core.factid import (
    EXACT_IDENTITY_NAMESPACE,
    exact_fact_id,
    fact_id,
    normalize_value,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def test_exact_id_preserves_case_where_legacy_collapses():
    # the DI-01 defect, at the primitive level: case-distinct literals are
    # DISTINCT under exact identity...
    assert exact_fact_id("literal", "CACHE_TTL") != exact_fact_id("literal", "cache_ttl")
    assert exact_fact_id("literal", "getUserId") != exact_fact_id("literal", "getuserid")
    # ...and the legacy id COLLAPSES them (reproduction control — this is the
    # behaviour the exact id exists to avoid, not a red-on-parent success).
    assert fact_id("literal", "CACHE_TTL") == fact_id("literal", "cache_ttl")


def test_exact_id_preserves_whitespace_punctuation_unicode():
    assert exact_fact_id("literal", "a b") != exact_fact_id("literal", "a  b")
    assert exact_fact_id("literal", "café") != exact_fact_id("literal", "cafe")
    assert exact_fact_id("literal", "v1.0") != exact_fact_id("literal", "v10")
    # exact identity is content-addressed on the raw UTF-8 value, so it is NOT
    # the normalized form
    assert exact_fact_id("literal", "  Trim.Me  ") != exact_fact_id(
        "literal", normalize_value("  Trim.Me  "))


def test_exact_id_is_deterministic_full_sha256():
    a = exact_fact_id("constraint", "Never force-push", key="policy", scope="repoX")
    b = exact_fact_id("constraint", "Never force-push", key="policy", scope="repoX")
    assert a == b
    assert _HEX64.match(a), "exact id must be a full 64-hex SHA-256"
    # distinct format + value from a legacy 16-hex id -> never mistaken for one
    legacy = fact_id("constraint", "Never force-push", key="policy", scope="repoX")
    assert len(legacy) == 16 and a != legacy


def test_exact_id_utf8_byte_length_framing_blocks_boundary_forgery():
    # different field splits must not collide (naive concatenation would)
    assert exact_fact_id("literal", "ab", key="c") != exact_fact_id(
        "literal", "a", key="bc")
    # a value containing the framing separator or the unit separator cannot
    # forge a boundary
    assert exact_fact_id("literal", "3:xyz") != exact_fact_id("literal", "xyz", key="3")
    assert exact_fact_id("literal", "a\x1fb") != exact_fact_id("literal", "a", key="b")


def test_exact_id_kind_is_a_schema_tag():
    # kind is a schema tag: stripped + upper-cased (like the legacy enum)
    assert exact_fact_id(" literal ", "X") == exact_fact_id("LITERAL", "X")
    assert exact_fact_id("literal", "X") != exact_fact_id("constraint", "X")


def test_exact_id_rejects_none_and_non_str_literals():
    with pytest.raises(TypeError):
        exact_fact_id(None, "x")
    with pytest.raises(TypeError):
        exact_fact_id("literal", None)
    with pytest.raises(TypeError):
        exact_fact_id("literal", 42)          # no implicit str() coercion
    with pytest.raises(TypeError):
        exact_fact_id("literal", "x", key=None)


def test_exact_id_matches_documented_construction():
    # pin the construction so the namespaced framing cannot silently drift
    def _framed(*fields):
        out = bytearray()
        for f in fields:
            b = f.encode("utf-8")
            out += str(len(b)).encode("ascii") + b":" + b
        return bytes(out)
    expected = hashlib.sha256(_framed(
        EXACT_IDENTITY_NAMESPACE, "", "LITERAL", "", "CACHE_TTL")).hexdigest()
    assert exact_fact_id("literal", "CACHE_TTL") == expected
