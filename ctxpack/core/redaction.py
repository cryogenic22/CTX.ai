"""Secret redaction — the E-6 ingest/egress security boundary.

Applied in two places (PF-12/PF-14): between transcript normalization
and extraction, so no secret ever reaches a fact value, a literal, a
gist or a persistent write; and again on the final serialized context
before any emission, as defense in depth.

Replacements are TYPE-ONLY by policy: ``[REDACTED:<type>]``, never
``[REDACTED:type:hash8]`` — low-entropy secrets can be recovered from
short unsalted fingerprints by enumeration. If correlation across
occurrences is ever genuinely required, it must use a repo-scoped keyed
HMAC whose key is never committed; that is deliberately NOT implemented
here so it cannot be reached by accident.

Fail-closed contract: callers must treat an exception from ``scan``/
``redact`` as "do not persist, do not emit" — never as "clean". The
functions themselves are pure and deterministic (stdlib ``re`` only).

Documented limitations (disclosed, not hidden): detection is
pattern-based. Novel token formats, secrets split across lines, and
secrets in encodings we do not decode are not caught. Prose *about* a
secret is not a secret and is deliberately not matched. The
``secret-assignment`` pattern rejects short pure-alphabetic values to
bound false positives ("auth: optional" is prose, not a credential);
the residual risk — a short alphabetic password in an assignment — is
accepted and documented rather than silently over-matched.
"""

from __future__ import annotations

import re

REDACTION_VERSION = "redact/v1"

_MARK = "[REDACTED:{}]"

# Order matters: multi-line/private-key first (largest span), then
# specific token formats, then the generic assignment sweep.
_PATTERNS: "tuple[tuple[str, re.Pattern], ...]" = (
    ("private-key-block", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
        r"(?:[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----|[\s\S]*\Z)")),
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("sk-api-key", re.compile(
        r"\bsk-(?:[A-Za-z0-9_-]+-)?[A-Za-z0-9]{20,}\b")),
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")),
    ("bearer-token", re.compile(
        r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    ("url-credentials", re.compile(
        r"(?<=://)[^/\s:@]{1,64}:[^/\s@]{1,256}(?=@)")),
)

_ASSIGNMENT = re.compile(
    r"""(?ix)\b(password|passwd|pwd|secret|token|api[_-]?key|apikey|
        access[_-]?key|client[_-]?secret|auth)\b\s*[:=]\s*
        (["']?)(?!\[REDACTED)([^\s"']{8,})\2""",
    re.VERBOSE)


def _assignment_value_is_secretlike(value: str) -> bool:
    """Bound false positives: placeholders, env references and short
    plain words are prose, not credentials."""
    if value[0] in "$<{%":          # $ENV, <placeholder>, {template}, %VAR%
        return False
    if value.isalpha() and len(value) < 16:
        return False
    return True


def redact(text: str) -> "tuple[str, dict[str, int]]":
    """Redact ``text``; returns (redacted, counts-by-type). Pure."""
    counts: dict[str, int] = {}
    out = str(text)
    for label, pattern in _PATTERNS:
        out, n = pattern.subn(_MARK.format(label), out)
        if n:
            counts[label] = counts.get(label, 0) + n

    def _sub_assignment(m: "re.Match") -> str:
        if not _assignment_value_is_secretlike(m.group(3)):
            return m.group(0)
        counts["secret-assignment"] = counts.get("secret-assignment", 0) + 1
        return f"{m.group(1)}={_MARK.format('secret-assignment')}"

    out = _ASSIGNMENT.sub(_sub_assignment, out)
    return out, counts


def scan(text: str) -> "list[str]":
    """Sorted type labels present in ``text`` without altering it."""
    _, counts = redact(text)
    return sorted(counts)


def redact_tree(obj, _counts: "dict[str, int] | None" = None):
    """Deep-redact every string in a JSON-shaped structure.

    Returns ``(redacted_obj, counts)``. Dict KEYS are left alone (they
    are schema, not payload); every string value, list element and
    nested structure is covered — this is what makes "between
    normalization and extraction" a single choke point instead of one
    call per extractor.
    """
    counts: dict[str, int] = {} if _counts is None else _counts
    if isinstance(obj, str):
        out, found = redact(obj)
        for k, v in found.items():
            counts[k] = counts.get(k, 0) + v
        return out, counts
    if isinstance(obj, list):
        return [redact_tree(x, counts)[0] for x in obj], counts
    if isinstance(obj, dict):
        return {k: redact_tree(v, counts)[0] for k, v in obj.items()}, counts
    return obj, counts
