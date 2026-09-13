"""One strict matcher for machine-local paths and owner identity in
committed/publishable artifacts (Codex RF3, 2026-08-24).

The scored-eval report gate (`benchmarks/agentic/fork_cluster.py`) and
the cohort scorecard both publish release-surface artifacts that must
never embed a machine-local path or the owner's identity. They had
DIVERGED — fork_cluster carried the reviewed, URL-aware, denylist-free
strict form; scorecard grew a weaker `/home`+`/Users`-only copy that
reopened the bypass class (forward-UNC, `/tmp`, `/var`, `/root`, owner
identity, path-bearing external names all passed). This module is the
single reviewed matcher both call.

Strict semantics (round-3/4 residuals, preserved verbatim from
fork_cluster): ANY absolute filesystem path of ANY form is a leak —
drive-letter (either slash), MSYS drive-root, UNC (both slash styles),
`file://` URIs, and EVERY POSIX absolute path including innocuous roots
(`/guides/x` is rejected, not just `/tmp`). The single allowance:
http(s) URL spans are masked out BEFORE the POSIX/forward-UNC scan (a
URL's own `/home/` segment is not a filesystem path); drive-letter,
backslash-UNC, `file://`, and owner-identity are checked on the RAW
string, URLs included, so nothing can be smuggled inside a URL.

Stdlib only (core rule): just ``re``.
"""

from __future__ import annotations

import re

# Owner identity + machine temp roots — checked on the raw lowercased
# string, URLs included.
FORBIDDEN_IDENTITY_SUBSTRINGS = (
    "kapil", "c--users-kapil",
    "appdata\\local\\temp", "appdata/local/temp",
)

_HTTP_URL_SPAN_RE = re.compile(r"https?://[^\s\"'`<>)\]]+", re.IGNORECASE)

# Checked on the RAW string (never legitimate inside an http(s) URL on
# these artifact surfaces).
_RAW_PATH_RES = (
    ("drive-letter path", re.compile(r"\b[a-z]:[\\/]", re.IGNORECASE)),
    ("UNC path", re.compile(r"\\\\[a-z0-9._$-]+\\", re.IGNORECASE)),
    ("file:// URI path", re.compile(r"\bfile://", re.IGNORECASE)),
)

# Checked AFTER http(s) URL spans are masked out. Token boundary is a
# generic NEGATIVE class (any non-word, non-slash char delimits — ':',
# ',', '{', '-' all count), never an allowlist; the path start is any
# non-whitespace non-slash char, so Unicode paths match too.
_MASKED_PATH_RES = (
    ("UNC path", re.compile(
        r"(?:^|(?<=[^\w\\/]))//[^\s/\\]+[\\/]", re.IGNORECASE)),
    ("POSIX absolute path", re.compile(
        r"(?:^|(?<=[^\w\\/]))/(?=[^\s/])")),
    ("home-directory segment", re.compile(
        r"[\\/](?:users|home)[\\/]", re.IGNORECASE)),
)

# The category label used for an owner-identity hit.
IDENTITY = "identity"


def scan_artifact_string(s: str) -> "list[tuple[str, str]]":
    """``[(category, detail), …]`` for one string; empty = clean.

    Order is identity → raw-path → masked-path, matching the reviewed
    fork_cluster priority; a caller that raises on the first finding
    reproduces the original precedence exactly. ``detail`` is the
    matched substring (identity) or a context snippet (paths).
    """
    findings: "list[tuple[str, str]]" = []
    low = s.lower()
    for pat in FORBIDDEN_IDENTITY_SUBSTRINGS:
        if pat in low:
            findings.append((IDENTITY, pat))
    for kind, rx in _RAW_PATH_RES:
        m = rx.search(s)
        if m:
            findings.append((kind, s[max(0, m.start() - 20):m.end() + 30]))
    scan = _HTTP_URL_SPAN_RE.sub(" ", s)
    for kind, rx in _MASKED_PATH_RES:
        m = rx.search(scan)
        if m:
            findings.append(
                (kind, scan[max(0, m.start() - 20):m.end() + 30]))
    return findings


def artifact_categories(text: str) -> "list[str]":
    """Sorted unique categories present in ``text`` (labels only) —
    empty = clean. Convenience for gates that report labels, not spans."""
    return sorted({cat for cat, _ in scan_artifact_string(text)})


def is_safe_identity(name: str) -> bool:
    """True when ``name`` is a plain artifact identity, not path-bearing
    text: no path separators or scheme, and no machine-path/identity
    match. Used to validate cohort/artifact names AS identities."""
    if not isinstance(name, str) or not name.strip():
        return False
    if any(c in name for c in "/\\") or ":" in name:
        return False
    return not scan_artifact_string(name)
