#!/usr/bin/env python3
"""Render .github/CODEOWNERS from the protected-surface list, or verify it is in sync.

Conservation-gates principle 1 says the success-definition surface must not be
editable by whoever is trying to clear it. That rule is only real if something
mechanical enforces it, so:

    protected-surface.txt  --(this script)-->  .github/CODEOWNERS

`--check` re-renders and compares. CI runs it, and
tests/test_protected_surface_sync.py runs it too, so the two files cannot drift
apart without a failure. CODEOWNERS only has teeth once branch protection
requires CODEOWNERS review and disallows self-approval — that is an owner action
on GitHub, not something this repository can assert for itself.

Usage:
    python scripts/gen_codeowners.py            # write .github/CODEOWNERS
    python scripts/gen_codeowners.py --check    # exit 1 if out of sync
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "harness" / "structural-floor" / "protected-surface.txt"
TARGET = ROOT / ".github" / "CODEOWNERS"

OWNER = "@cryogenic22"

HEADER = """\
# DO NOT EDIT — generated from harness/structural-floor/protected-surface.txt
# by scripts/gen_codeowners.py. Edit the source list, then regenerate:
#
#     python scripts/gen_codeowners.py
#
# CI (.github/workflows/structural-floor.yml) and
# tests/test_protected_surface_sync.py both fail on drift.
#
# This file assigns review of the success-definition surface to the owner.
# It is advisory until branch protection requires CODEOWNERS review and
# disallows self-approval.
"""


def rel(path: Path) -> str:
    """Display path, repo-relative when possible.

    A gate whose failure message raises is worse than no message, so fall back
    to the absolute path instead of letting relative_to() throw.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def patterns(text: str) -> list[str]:
    """Extract glob patterns from the protected-surface source."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def render(text: str) -> str:
    lines = [HEADER]
    for pattern in patterns(text):
        lines.append(f"{pattern} {OWNER}")
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify CODEOWNERS matches the source; do not write")
    args = parser.parse_args(argv)

    if not SOURCE.exists():
        print(f"FAIL: protected-surface source is missing: {SOURCE}", file=sys.stderr)
        return 1

    source_text = SOURCE.read_text(encoding="utf-8")
    if not patterns(source_text):
        # An empty surface would render an empty CODEOWNERS and silently
        # protect nothing. Refuse rather than pass vacuously.
        print("FAIL: protected-surface.txt lists no patterns; refusing to "
              "generate an empty CODEOWNERS", file=sys.stderr)
        return 1

    expected = render(source_text)

    if args.check:
        if not TARGET.exists():
            print(f"FAIL: {rel(TARGET)} does not exist. Run: "
                  "python scripts/gen_codeowners.py", file=sys.stderr)
            return 1
        actual = TARGET.read_text(encoding="utf-8")
        if actual != expected:
            print(f"FAIL: {rel(TARGET)} is out of sync with "
                  f"{rel(SOURCE)}.\n"
                  "The protected surface changed without regenerating CODEOWNERS, "
                  "or CODEOWNERS was edited directly.\n"
                  "Run: python scripts/gen_codeowners.py", file=sys.stderr)
            return 1
        print(f"OK: CODEOWNERS in sync ({len(patterns(source_text))} protected patterns)")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(expected, encoding="utf-8")
    print(f"Wrote {rel(TARGET)} "
          f"({len(patterns(source_text))} protected patterns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
