#!/usr/bin/env python
"""CI gate: public claims must trace to the claims ledger (W1-2).

Enforcement (owner decision 2026-07-11):

  FAIL — a README.md line carrying a numerical claim (percentage,
         pp-interval, Nx multiplier, F1 score) with no covering ledger row
  FAIL — a retracted-claim signature appearing in README.md / paper/*.md /
         docs/*.md outside a retraction context
  FAIL — a measured/directional row whose artifact path does not exist
  WARN — a README.md line with qualitative comparative language
         ("beats", "outperforms", "better than", "wins") and no covering row

Precision-first (the conflict-lint lesson: a gate that cries wolf gets
ignored). Stdlib only. Scope documented in docs/claims-ledger.md.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "claims-ledger.md"

_PCT = re.compile(r"\d+(?:\.\d+)?%")
_PP = re.compile(r"±?\d+(?:(?:–|-)\d+)?(?:\.\d+)?\s*pp\b")
_MULT = re.compile(r"\b~?\d+(?:\.\d+)?\s*[x×]\b")
_F1 = re.compile(r"F1\s*=\s*\d[\d.]*")
NUMERIC_PATTERNS = (_PCT, _PP, _MULT, _F1)
COMPARATIVE_WORDS = ("beats", "outperforms", "better than", "wins")

# Lines mentioning a retracted signature in one of these contexts are the
# retraction itself, not a reappearance.
RETRACTION_CONTEXT = ("retract", "corrected", "wrong direction", "do not cite",
                      "never reappear", "must not reappear")

_CLAIM_ROW = re.compile(
    r"^\|\s*(C\d+|E\d+)\s*\|(.+?)\|\s*"
    r"(measured|directional|external|unmeasured)\s*\|([^|]*)\|")
_RETRACTED_ROW = re.compile(r"^\|\s*R\d+\s*\|[^|]*\|([^|]*)\|")
_ARTIFACT = re.compile(r"`([^`]+)`")


def parse_ledger(text: str):
    covers: list[str] = []
    artifacts: list[tuple[str, str]] = []  # (row id, path)
    signatures: list[str] = []
    for line in text.splitlines():
        m = _CLAIM_ROW.match(line)
        if m:
            rid, status, cover_field = m.group(1), m.group(3), m.group(4)
            covers.extend(c.strip() for c in cover_field.split(",")
                          if c.strip() and c.strip() not in {"—", "-"})
            if status in {"measured", "directional"}:
                rest = line.split("|")[5] if line.count("|") >= 6 else ""
                am = _ARTIFACT.search(rest)
                if am:
                    artifacts.append((rid, am.group(1)))
                else:
                    artifacts.append((rid, ""))
            continue
        m = _RETRACTED_ROW.match(line)
        if m:
            signatures.extend(s.strip() for s in m.group(1).split(",")
                              if s.strip())
    return covers, artifacts, signatures


def _covered(line: str, covers: list[str]) -> bool:
    return any(c in line for c in covers)


def check(root: Path = ROOT):
    errors: list[str] = []
    warnings: list[str] = []
    ledger_path = root / "docs" / "claims-ledger.md"
    if not ledger_path.is_file():
        return ["docs/claims-ledger.md is missing"], []
    covers, artifacts, signatures = parse_ledger(
        ledger_path.read_text(encoding="utf-8"))
    if not covers:
        return ["no claim rows parsed from docs/claims-ledger.md"], []

    for rid, artifact in artifacts:
        if not artifact:
            errors.append(f"{rid}: measured/directional row has no "
                          f"`artifact` path")
        elif not (root / artifact).exists():
            errors.append(f"{rid}: artifact does not exist: {artifact}")

    readme = root / "README.md"
    if readme.is_file():
        for i, line in enumerate(
                readme.read_text(encoding="utf-8").splitlines(), 1):
            if any(p.search(line) for p in NUMERIC_PATTERNS):
                if not _covered(line, covers):
                    errors.append(
                        f"README.md:{i} carries a numerical claim with no "
                        f"claims-ledger row: {line.strip()[:100]}")
            elif any(w in line.lower() for w in COMPARATIVE_WORDS):
                if not _covered(line, covers):
                    warnings.append(
                        f"README.md:{i} qualitative comparative line not "
                        f"in ledger: {line.strip()[:100]}")

    scan_files = [readme] + sorted((root / "paper").glob("*.md")) + [
        p for p in sorted((root / "docs").glob("*.md"))
        if p.name not in {"claims-ledger.md", "notes.md"}]
    for f in scan_files:
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        for i, line in enumerate(
                f.read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.lower()
            if any(ctx in lowered for ctx in RETRACTION_CONTEXT):
                continue
            for sig in signatures:
                if sig in line:
                    errors.append(
                        f"{rel}:{i} retracted claim signature {sig!r} "
                        f"reappears outside a retraction context")
    return errors, warnings


def main() -> int:
    errors, warnings = check()
    for w in warnings:
        print(f"CLAIMS-GATE WARN: {w}")
    for e in errors:
        print(f"CLAIMS-GATE FAIL: {e}")
    if errors:
        print(f"claims gate: {len(errors)} failure(s), "
              f"{len(warnings)} warning(s)")
        return 1
    print(f"claims gate: OK ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
