"""Negation preservation — prose compression must never invert rule semantics.

Regression guard for the 2026-07-03 finding: "no"/"not" were in the
filler-word strip list, so "Do not force-push to main" compressed to
"force-push main" — a full semantic inversion of a safety rule.
"""

import re

from ctxpack.core.packer.md_parser import _FILLER_WORDS, _compress_prose

NEGATIONS = [
    "no", "not", "never", "none", "cannot", "don't", "doesn't", "won't",
    "shouldn't", "mustn't", "isn't", "aren't", "can't",
]

_NEG_RE = re.compile(
    r"\b(no|not|never|none|cannot|n't)\b|n't\b", re.IGNORECASE
)


def _count_negations(text: str) -> int:
    return len(_NEG_RE.findall(text))


def test_no_negation_words_in_filler_list():
    for neg in NEGATIONS:
        assert neg not in _FILLER_WORDS, (
            f"negation word {neg!r} is in _FILLER_WORDS — stripping it "
            f"inverts rule semantics"
        )


def test_compress_prose_preserves_negations():
    cases = [
        "Do not force-push to main under any circumstances",
        "The migration must not run before the backup completes",
        "There is no fallback if the vault sidecar is down",
        "Never restart the auth service during business hours",
        "PII fields cannot be logged in plaintext",
    ]
    for text in cases:
        compressed = _compress_prose(text)
        assert _count_negations(compressed) >= _count_negations(text), (
            f"negation lost: {text!r} -> {compressed!r}"
        )


def test_do_not_force_push_regression():
    compressed = _compress_prose("Do not force-push to main")
    assert "not" in compressed.lower().split(), (
        f"'Do not force-push to main' compressed to {compressed!r} — "
        f"the negation was stripped"
    )
