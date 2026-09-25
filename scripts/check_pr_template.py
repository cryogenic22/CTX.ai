#!/usr/bin/env python3
"""Fail when a PR description is missing the sections that make review possible.

Three overclaims reached the owner on 2026-09-20 because an agent's summary was
believed without an artifact-level check: a fabricated re-run, an ignore rule
that protected the wrong directory, and "16/16 green" offered as evidence for a
boundary no test covered. Each was an unstated assumption.

So the template requires Assumptions and Verification, and this gate fails when
they are absent or left as placeholders.

Usage:
    python scripts/check_pr_template.py                 # validate the template itself
    python scripts/check_pr_template.py --body FILE     # validate a PR body
    python scripts/check_pr_template.py --body -        # validate from stdin
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / ".github" / "pull_request_template.md"

REQUIRED_SECTIONS = [
    "Summary",
    "Assumptions",
    "Non-goals",
    "Verification",
    "Self-review",
]

# Words that assert quality instead of showing it. Cheap to type, impossible to
# check, and they crowd out the evidence a reviewer actually needs.
BANNED_WORDS = ["comprehensive", "robust", "production-ready", "bulletproof",
                "fully tested", "battle-tested"]

PLACEHOLDER = re.compile(r"^\s*(\.\.\.|-\s*$|_.*_\s*$|TODO|TBD)\s*$", re.IGNORECASE)


def sections(body: str) -> dict[str, str]:
    """Split a markdown body into {heading: content}."""
    found: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in body.splitlines():
        match = re.match(r"^#{1,4}\s+(.+?)\s*$", line)
        if match:
            if current is not None:
                found[current] = "\n".join(buf)
            current = match.group(1).strip()
            # Normalise "Self-review (Tier 2 red flags)" -> "Self-review"
            current = re.split(r"\s*\(", current)[0].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        found[current] = "\n".join(buf)
    return found


def strip_comments(body: str) -> str:
    return re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)


def check(body: str, *, template_mode: bool) -> list[str]:
    problems: list[str] = []
    visible = strip_comments(body)
    found = sections(visible)

    for name in REQUIRED_SECTIONS:
        if name not in found:
            problems.append(f"missing required section: ## {name}")
        elif not template_mode:
            # In a real PR body the section must actually say something.
            content = [ln for ln in found[name].splitlines()
                       if ln.strip() and not PLACEHOLDER.match(ln)]
            if not content:
                problems.append(f"section '{name}' is empty or still a placeholder")

    lowered = visible.lower()
    for word in BANNED_WORDS:
        if word in lowered:
            problems.append(
                f"unsupported quality claim: '{word}' — state the evidence instead")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body", help="path to a PR body file, or - for stdin")
    args = parser.parse_args(argv)

    if args.body:
        text = sys.stdin.read() if args.body == "-" else Path(args.body).read_text(encoding="utf-8")
        label, template_mode = args.body, False
    else:
        if not TEMPLATE.exists():
            print(f"FAIL: {TEMPLATE.relative_to(ROOT)} does not exist", file=sys.stderr)
            return 1
        text = TEMPLATE.read_text(encoding="utf-8")
        label, template_mode = str(TEMPLATE.relative_to(ROOT)), True

    problems = check(text, template_mode=template_mode)
    if problems:
        print(f"FAIL: {label}", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"OK: {label} has all {len(REQUIRED_SECTIONS)} required sections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
