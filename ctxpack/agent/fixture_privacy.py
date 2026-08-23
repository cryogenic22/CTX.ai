"""Committed-fixture privacy gate (PF-16).

Scans every COMMITTED file under the fixture/benchmark/artifact roots
with two detectors and holds the result to a reviewed allowlist:

- ``secret:<type>`` — the ctxpack secret scanner
  (:func:`ctxpack.core.redaction.redact`), one detector per type label,
  count = occurrences in the file.
- ``user_path`` — machine-user path shapes (``<drive>:\\Users\\<name>``,
  ``/home/<name>``, ``/Users/<name>``), count = DISTINCT matched
  strings (occurrence counts of the same path are churn, new distinct
  paths are signal).
Bytes that cannot be strictly UTF-8 decoded are scanned LOSSILY
(``errors="replace"``) — acknowledged-but-unscanned is not a privacy
pass (Finding 4b, 2026-08-23); an ASCII-region secret inside a binary
log is still found. A committed file that cannot be READ at all raises:
the gate never passes by being unable to look.

The allowlist (``tests/fixture_privacy_allowlist.json``) is part of the
success-definition surface: every entry carries a reviewed ``why`` AND
the file's content sha256 (Finding 4a) — an allowance covers the exact
reviewed bytes, so a same-count value swap (replacing a reviewed false
positive with a real secret) fails on the sha, not just growth on the
count. The gate requires an EXACT match in every direction: new hits,
grown/shrunk counts, changed bytes, and stale entries all fail.

Enumeration is ``git ls-files`` (committed files only — an untracked
scratch file is not yet published and gets caught at commit review).
Enumeration failure RAISES: per the gate discipline, a gate that could
not run must never report pass.

The gate's own negative control lives at
``tests/privacy_gate_violation/planted.txt`` — committed OUTSIDE the
scanned roots and fed to the scanner explicitly by the test suite, so
the gate is observably red-capable without dirtying the live tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess

ROOTS = ("tests/fixtures", "tests/code/fixtures", "ctxpack/benchmarks",
         "scorecards")
ALLOWLIST_FILE = os.path.join("tests", "fixture_privacy_allowlist.json")
# v2 (Finding 4): entries bind the reviewed file bytes (sha256), and
# undecodable files are lossily scanned instead of waived.
ALLOWLIST_SCHEMA = "ctx-fixture-privacy-allowlist/v2"

_USER_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}|/home/|/Users/)[^\\/\s\"']+")


class GateError(Exception):
    """The gate could not run (enumeration failed, allowlist malformed).
    Deliberately an exception: a gate that cannot run must fail the
    lane, never report pass."""


def scan_text(text: str) -> "dict[str, int]":
    """Detector → count for one file's text. Empty dict = clean."""
    from ..core.redaction import redact
    _, counts = redact(text)
    out = {f"secret:{label}": n for label, n in sorted(counts.items())}
    distinct_paths = set(_USER_PATH.findall(text))
    if distinct_paths:
        out["user_path"] = len(distinct_paths)
    return out


def scan_file(path: str) -> "tuple[dict[str, int], str]":
    """``(detector counts, content sha256)`` for one committed file.

    A publishable text fixture must be clean UTF-8 TEXT. Lossy decoding
    (the earlier ``errors="replace"`` form) mis-read a wide-encoded
    secret as clean — UTF-16LE ``AKIAIOSFODNN7EXAMPLE`` interleaves the
    ASCII bytes with NULs, so the type-only regexes never match and the
    file passed with an empty detector map (Codex Finding 1, RF1). We
    now REFUSE rather than guess an encoding:

    - a NUL byte means the file is not UTF-8 text (wide encoding or
      binary) → detector ``non_text``;
    - bytes that fail STRICT UTF-8 decode → detector ``non_utf8``.

    Both are findings unless the allowlist carries an explicit,
    sha-bound owner disposition — there is no lossy-clean waiver. The
    sha is over the raw bytes either way. An unreadable committed file
    raises: the gate must never pass by being unable to look."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        from ..core.errors import classify_exception
        raise GateError(f"committed file unreadable "
                        f"({classify_exception(e)}): {path}")
    sha = hashlib.sha256(raw).hexdigest()
    if b"\x00" in raw:
        return {"non_text": 1}, sha
    try:
        text = raw.decode("utf-8")            # STRICT — never guess
    except UnicodeDecodeError:
        return {"non_utf8": 1}, sha
    return scan_text(text), sha


def committed_files(repo_root: str,
                    roots: "tuple[str, ...]" = ROOTS) -> "list[str]":
    """Sorted committed files under ``roots``, or raise GateError."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--", *roots],
            cwd=repo_root, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GateError(f"enumeration failed: {type(e).__name__}")
    if proc.returncode != 0:
        raise GateError(f"git ls-files exited {proc.returncode}")
    names = [n for n in proc.stdout.decode("utf-8").split("\0") if n]
    if not names:
        raise GateError("enumeration returned no committed files — "
                        "wrong repo root?")
    return sorted(names)


def scan_tree(repo_root: str,
              roots: "tuple[str, ...]" = ROOTS):
    """relpath → ``{"detectors": {...}, "sha256": hex}`` for every
    committed file WITH hits."""
    observed: "dict[str, dict]" = {}
    for rel in committed_files(repo_root, roots):
        counts, sha = scan_file(os.path.join(repo_root, rel))
        if counts:
            observed[rel] = {"detectors": counts, "sha256": sha}
    return observed


def load_allowlist(path: str):
    """(relpath, detector) → ``(count, file sha256)``. Malformed →
    GateError: a gate with an unreadable bar must not run at all.
    Entries for the same path must agree on the sha — a split bar is a
    malformed bar."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise GateError(f"allowlist unreadable: {type(e).__name__}")
    if not isinstance(data, dict) or data.get("schema") != ALLOWLIST_SCHEMA:
        raise GateError("allowlist schema mismatch")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise GateError("allowlist 'entries' must be a list")
    allowed: "dict[tuple[str, str], tuple[int, str]]" = {}
    sha_by_path: "dict[str, str]" = {}
    for e in entries:
        if (not isinstance(e, dict)
                or not isinstance(e.get("path"), str)
                or not isinstance(e.get("detector"), str)
                or not isinstance(e.get("count"), int)
                or not re.fullmatch(r"[0-9a-f]{64}",
                                    str(e.get("sha256") or ""))
                or not str(e.get("why") or "").strip()):
            raise GateError(f"malformed allowlist entry: {e!r}")
        key = (e["path"], e["detector"])
        if key in allowed:
            raise GateError(f"duplicate allowlist entry: {key}")
        prior = sha_by_path.setdefault(e["path"], e["sha256"])
        if prior != e["sha256"]:
            raise GateError(f"conflicting sha256 for {e['path']!r}")
        allowed[key] = (e["count"], e["sha256"])
    return allowed


def gate_findings(observed: "dict[str, dict]",
                  allowed: "dict[tuple[str, str], tuple[int, str]]"
                  ) -> "list[str]":
    """Exact-match comparison, every direction. Empty list = pass.

    An allowance is valid only for the exact reviewed bytes: matching
    detector counts with a different file sha256 is a CHANGED-BYTES
    finding (Finding 4a — the same-count swap)."""
    findings: "list[str]" = []
    seen: "set[tuple[str, str]]" = set()
    for rel in sorted(observed):
        sha = observed[rel]["sha256"]
        for detector, count in sorted(observed[rel]["detectors"].items()):
            seen.add((rel, detector))
            entry = allowed.get((rel, detector))
            if entry is None:
                findings.append(
                    f"NEW hit: {rel} [{detector}] x{count} — not in the "
                    f"reviewed allowlist")
                continue
            want_count, want_sha = entry
            if want_count != count:
                findings.append(
                    f"CHANGED hit: {rel} [{detector}] x{count} "
                    f"(allowlisted x{want_count}) — re-review required")
            elif want_sha != sha:
                findings.append(
                    f"CHANGED BYTES: {rel} [{detector}] — counts match "
                    f"but the file is not the reviewed one "
                    f"(sha {sha[:12]}… vs reviewed {want_sha[:12]}…); "
                    f"re-review required")
    for (rel, detector), (want_count, _sha) in sorted(allowed.items()):
        if (rel, detector) not in seen:
            findings.append(
                f"STALE allowlist entry: {rel} [{detector}] "
                f"x{want_count} — hit no longer observed; remove the "
                f"entry")
    return findings


def run_gate(repo_root: str,
             allowlist_path: "str | None" = None,
             roots: "tuple[str, ...]" = ROOTS) -> "list[str]":
    """Scan + compare. Empty list = pass; GateError = could not run."""
    allowlist_path = allowlist_path or os.path.join(repo_root,
                                                   ALLOWLIST_FILE)
    return gate_findings(scan_tree(repo_root, roots),
                         load_allowlist(allowlist_path))
