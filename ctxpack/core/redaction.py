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

# redact/v2 (2026-08-09): TM-1 corpus amendments — uppercase
# environment-style *_KEY names, benign-span rescan, nested quoted
# tails. Scanner output changed, so the version moves with it and is
# stamped into every checkpoint receipt.
REDACTION_VERSION = "redact/v2"

_MARK = "[REDACTED:{}]"

# Order matters: multi-line/private-key first (largest span), then
# specific token formats, then the generic assignment sweep.
_PATTERNS: "tuple[tuple[str, re.Pattern], ...]" = (
    ("private-key-block", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
        r"(?:[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----|[\s\S]*\Z)")),
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{10,}\b")),
    ("gcp-api-key", re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b")),
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

# TM-1 (PF-11 v2.1): the assignment matcher must catch PREFIXED names
# (AWS_SECRET_ACCESS_KEY, DATABASE_PASSWORD, npm's _authToken) and
# QUOTED values containing whitespace. The name is matched loosely and
# then judged by its SEGMENTS (split on _ - . and camelCase) so that
# "oauth" does not trigger on the "auth" substring.
# separator whitespace is SAME-LINE only: with \s* a benign "config:"
# line ending would swallow the secret assignment on the next line as
# its "value", consuming the span so the real match never fires
# the unquoted alternative may carry a quoted TAIL: in
# `SECRETISH_NAME: X_KEY="quoted ws"` the value is the whole nested
# assignment — stopping at the quote redacted `X_KEY=` and left the
# quoted payload behind; the spaced form (`... PASSWORD: "quoted"`)
# only attaches when the run ends in the separator itself, so plain
# prose quotes never get swallowed (TC-1 position matrix, 2026-08-09)
_ASSIGNMENT = re.compile(
    r"""(?x)\b([A-Za-z0-9_.\-]{1,64})[ \t]*[:=][ \t]*
        (?!\[REDACTED)
        ( "[^"\n]{4,256}" | '[^'\n]{4,256}'
        | [^\s"']{8,256}
          (?:(?:(?<=[:=])[ \t]*)?(?:"[^"\n]{0,256}"|'[^'\n]{0,256}'))? )""",
    re.VERBOSE)

_SECRET_SEGMENTS = frozenset({
    "password", "passwd", "pwd", "secret", "token", "apikey",
    "credential", "credentials", "auth"})
# "key" alone is too common ("sort key"); it counts only next to one of
# these qualifying segments (AWS_SECRET_ACCESS_KEY, AccountKey, ...)
_KEY_QUALIFIERS = frozenset({
    "api", "access", "account", "private", "secret", "client", "app"})

_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# TM-1 (2026-08-09 re-review): an UPPERCASE environment-style name
# ending in _KEY (DATA_KEY=..., SIGNING_KEY: ...) is a credential slot
# per the §6 corpus rule `*_(KEY|...)` even without a qualifying
# segment. Uppercase-only on purpose: the lowercase false-positive
# bound stays (sort_key = created_at_desc is code, not a credential).
_ENV_KEY_STYLE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_KEY")


def _name_is_secretlike(name: str) -> bool:
    parts: "list[str]" = []
    for chunk in re.split(r"[_.\-]+", name):
        parts.extend(_CAMEL_SPLIT.split(chunk))
    segments = {p.lower() for p in parts if p}
    if segments & _SECRET_SEGMENTS:
        return True
    if "key" in segments and segments & _KEY_QUALIFIERS:
        return True
    return bool(_ENV_KEY_STYLE.fullmatch(name))


def _assignment_value_is_secretlike(value: str) -> bool:
    """Bound false positives: placeholders, env references and short
    plain words are prose, not credentials. A quoted multi-word value
    (a passphrase) IS secret-like — TM-1's reviewer bypass."""
    if value and value[0] in "$<{%":  # $ENV, <placeholder>, {template}, %VAR%
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
        name, raw_value = m.group(1), m.group(2)
        quote = raw_value[0] if raw_value[0] in "\"'" else ""
        value = raw_value[1:-1] if quote else raw_value
        if not _name_is_secretlike(name):
            # A benign-name match still CONSUMES its value span, which
            # can contain a secret assignment of its own ("auth failed
            # for azure-accountkey: AccountKey=..." — found by the
            # TC-1 position matrix, 2026-08-09). Rescan the value so
            # consumption never shadows a match.
            redone = _ASSIGNMENT.sub(_sub_assignment, value)
            if redone != value:
                head = m.group(0)[: m.start(2) - m.start(0)]
                return f"{head}{quote}{redone}{quote}"
            return m.group(0)
        if not value or not _assignment_value_is_secretlike(value):
            return m.group(0)
        counts["secret-assignment"] = counts.get("secret-assignment", 0) + 1
        return f"{name}={_MARK.format('secret-assignment')}"

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
