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
- ``unscanned`` — a committed file that cannot be strictly UTF-8
  decoded cannot be scanned; it must be explicitly allowlisted or it is
  a finding. Unscanned is never silently treated as clean.

The allowlist (``tests/fixture_privacy_allowlist.json``) is part of the
success-definition surface: every entry carries a reviewed ``why``, and
the gate requires an EXACT match in both directions — a new or grown
hit fails, and an allowlist entry whose hit disappeared fails too
(stale entries are how an allowlist rots into a blanket waiver).

Known limitation, stated: entries pin (path, detector, count), not the
matched bytes — a same-count value swap inside an already-allowlisted
file passes this gate. Value-level pinning needs a span-reporting
scanner API and is deliberately out of PF-16's scope.

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

import json
import os
import re
import subprocess

ROOTS = ("tests/fixtures", "tests/code/fixtures", "ctxpack/benchmarks",
         "scorecards")
ALLOWLIST_FILE = os.path.join("tests", "fixture_privacy_allowlist.json")
ALLOWLIST_SCHEMA = "ctx-fixture-privacy-allowlist/v1"

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


def scan_file(path: str) -> "dict[str, int]":
    try:
        with open(path, encoding="utf-8") as f:
            return scan_text(f.read())
    except UnicodeDecodeError:
        return {"unscanned": 1}
    except OSError:
        # a committed file that cannot be read is not provably clean
        return {"unscanned": 1}


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
              roots: "tuple[str, ...]" = ROOTS) -> "dict[str, dict[str, int]]":
    """relpath → detector counts for every committed file with hits."""
    observed: "dict[str, dict[str, int]]" = {}
    for rel in committed_files(repo_root, roots):
        counts = scan_file(os.path.join(repo_root, rel))
        if counts:
            observed[rel] = counts
    return observed


def load_allowlist(path: str) -> "dict[tuple[str, str], int]":
    """(relpath, detector) → allowed count. Malformed → GateError:
    a gate with an unreadable bar must not run at all."""
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
    allowed: "dict[tuple[str, str], int]" = {}
    for e in entries:
        if (not isinstance(e, dict)
                or not isinstance(e.get("path"), str)
                or not isinstance(e.get("detector"), str)
                or not isinstance(e.get("count"), int)
                or not str(e.get("why") or "").strip()):
            raise GateError(f"malformed allowlist entry: {e!r}")
        key = (e["path"], e["detector"])
        if key in allowed:
            raise GateError(f"duplicate allowlist entry: {key}")
        allowed[key] = e["count"]
    return allowed


def gate_findings(observed: "dict[str, dict[str, int]]",
                  allowed: "dict[tuple[str, str], int]") -> "list[str]":
    """Exact-match comparison, both directions. Empty list = pass."""
    findings: "list[str]" = []
    seen: "set[tuple[str, str]]" = set()
    for rel in sorted(observed):
        for detector, count in sorted(observed[rel].items()):
            seen.add((rel, detector))
            want = allowed.get((rel, detector))
            if want is None:
                findings.append(
                    f"NEW hit: {rel} [{detector}] x{count} — not in the "
                    f"reviewed allowlist")
            elif want != count:
                findings.append(
                    f"CHANGED hit: {rel} [{detector}] x{count} "
                    f"(allowlisted x{want}) — re-review required")
    for (rel, detector), want in sorted(allowed.items()):
        if (rel, detector) not in seen:
            findings.append(
                f"STALE allowlist entry: {rel} [{detector}] x{want} — "
                f"hit no longer observed; remove the entry")
    return findings


def run_gate(repo_root: str,
             allowlist_path: "str | None" = None,
             roots: "tuple[str, ...]" = ROOTS) -> "list[str]":
    """Scan + compare. Empty list = pass; GateError = could not run."""
    allowlist_path = allowlist_path or os.path.join(repo_root,
                                                   ALLOWLIST_FILE)
    return gate_findings(scan_tree(repo_root, roots),
                         load_allowlist(allowlist_path))
