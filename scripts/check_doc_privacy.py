#!/usr/bin/env python
"""CI gate: shipped documentation must not embed a machine-specific owner path.

Finding 3 (rc1 review, 2026-09-13): the upgrade guide shipped an editable-
install example embedding ``C:\\Users\\kapil\\Documents\\CTX_mod`` — a machine-
specific owner path, contrary to the program's artifact/privacy hygiene. This
gate scans every shipped doc under ``docs/`` and FAILS (exit 1) on any
machine-USER path leak, so that exact class cannot recur in shipped docs.

Scope: ``docs/**/*.md`` — the externally-distributed documentation tree. The
repo-private ledger (``.claude/ctx/``), frozen test fixtures, research papers,
and benchmark corpora are NOT shipped documentation and are out of scope.

Detection reuses the ONE strict matcher (``ctxpack/core/artifact_privacy``),
never a second copy (see ``.claude/rules/anti-slop.md``). It fails on the
machine-specific path categories — drive-letter paths, UNC paths, ``file://``
URIs, and ``/home``|``/users`` segments — which are exactly the owner-path
class the review caught. Two deliberate non-triggers keep the gate honest
rather than vacuous:

  * the bare owner-*identity* category (e.g. an author byline "Kapil Pant")
    is NOT blocked — attribution in docs is legitimate; a real owner *path*
    is still caught by its drive-letter / home-directory segment;
  * a generic POSIX absolute path (e.g. a neutral example ``/path/to/x``)
    is NOT blocked, so cross-platform placeholder examples are permitted.

Stdlib + the shared matcher only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# import the shared strict matcher whether or not ctxpack is pip-installed
sys.path.insert(0, str(ROOT))
from ctxpack.core.artifact_privacy import scan_artifact_string  # noqa: E402

# Machine-specific path categories from the shared matcher (NOT the bare
# "identity" category, NOT the generic "POSIX absolute path" category).
BLOCKING_CATEGORIES = {
    "drive-letter path",
    "UNC path",
    "file:// URI path",
    "home-directory segment",
}


def scan_doc(path: str) -> "list[tuple[str, str]]":
    """Blocking (category, detail) findings for one doc; [] when clean."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return [(cat, detail) for cat, detail in scan_artifact_string(text)
            if cat in BLOCKING_CATEGORIES]


def _iter_docs(root: str) -> "list[str]":
    docs_dir = os.path.join(root, "docs")
    found: "list[str]" = []
    for dirpath, _dirs, files in os.walk(docs_dir):
        for name in files:
            if name.endswith(".md"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def main(root: str = ".") -> int:
    problems: "list[str]" = []
    for path in _iter_docs(root):
        for cat, detail in scan_doc(path):
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            problems.append(f"{rel}: {cat} - {detail!r}")
    if problems:
        for p in problems:
            print(f"doc-privacy gate FAIL: {p}", file=sys.stderr)
        print(f"doc-privacy gate: {len(problems)} machine-specific owner "
              f"path(s) in shipped docs - use a neutral example",
              file=sys.stderr)
        return 1
    print("doc-privacy gate: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
