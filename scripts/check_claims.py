#!/usr/bin/env python
"""CI gate: public claims must trace to the claims ledger (W1-2 + Q2-3).

Enforcement (owner decision 2026-07-11; widened per reviewer finding
Q2-3):

  FAIL — a README.md line carrying a numerical claim (percentage,
         pp-interval, Nx multiplier, F1 score, p-value, numeric range,
         time comparative, "N out of M", zero-after-compaction phrasing)
         with no covering ledger row or inline claim ID
  FAIL — an inline claim ID ([CL:C1]) that does not exist in the ledger
  FAIL — a measured/directional row whose artifact path does not exist,
         does not resolve into the allowlisted immutable results tree
         (ctxpack/benchmarks/**/results/**), or whose committed sha256
         prefix no longer matches the file
  FAIL — a retracted-claim signature appearing in README.md / paper/*.md /
         docs/*.md outside a retraction context
  WARN — a README.md line with qualitative comparative language
         ("beats", "outperforms", "better than", "wins") and no covering row
  WARN — uncovered numeric lines in paper/*.md and docs/*.md (summary per
         file — line-FAIL stays README-only per the owner decision until
         week-1 false-positive data is in)

Claim IDs: a public claim sentence may carry ``[CL:<row-id>]`` inline —
explicit beats regex; the patterns are the backstop. Precision-first
(the conflict-lint lesson: a gate that cries wolf gets ignored).
Stdlib only. Scope documented in docs/claims-ledger.md.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "claims-ledger.md"

_PCT = re.compile(r"\d+(?:\.\d+)?%")
_PP = re.compile(r"±?\d+(?:(?:–|-)\d+)?(?:\.\d+)?\s*pp\b")
_MULT = re.compile(r"\b~?\d+(?:\.\d+)?\s*[x×]\b")
_F1 = re.compile(r"F1\s*=\s*\d[\d.]*")
# Q2-3 backstop widening — shapes the reviewer showed bypassing the gate
_PVAL = re.compile(r"\bp\s*[=<]\s*0?\.\d+")
_RANGE_UNIT = re.compile(
    r"\b\d+(?:\.\d+)?\s*[–-]\s*\d+(?:\.\d+)?\s*(?:%|pp\b|ms\b|s\b)")
_DECIMAL_RANGE = re.compile(r"\b0\.\d+\s*[–-]\s*0\.\d+\b")
_CMP_TIME = re.compile(r"[<>≤≥]\s*~?\d+(?:\.\d+)?\s*(?:ms|s|sec|seconds)\b")
_N_OUT_OF_M = re.compile(r"\b\d+\s+out\s+of\s+\d+\b")
_ZERO_COMPACTION = re.compile(
    r"\b(?:zero|none)\b[^.]{0,60}\bcompactio", re.IGNORECASE)
NUMERIC_PATTERNS = (_PCT, _PP, _MULT, _F1, _PVAL, _RANGE_UNIT,
                    _DECIMAL_RANGE, _CMP_TIME, _N_OUT_OF_M,
                    _ZERO_COMPACTION)
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
_ARTIFACT_SHA = re.compile(r"sha256:([0-9a-f]{8,64})")
_CLAIM_ID = re.compile(r"\[CL:([A-Za-z0-9_-]+)\]")

# Measured evidence must live in the immutable results tree — versioned
# files that are never overwritten (ground rule). Prose is mutable and
# therefore never evidence (Q2-3: C3/C7 pointed at a paper).
def _allowlisted(path: str, root: Path) -> bool:
    """Resolved — not lexical — containment (Q2-3 re-check): a path with
    traversal segments can satisfy a startswith/substring check while
    resolving outside the results tree, so containment is decided on the
    RESOLVED path relative to the repo root."""
    try:
        rel = (root / path).resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    parts = rel.parts
    return (len(parts) >= 4 and parts[0] == "ctxpack"
            and parts[1] == "benchmarks" and "results" in parts[2:-1])


def parse_ledger(text: str) -> dict:
    ids: set[str] = set()
    covers: list[str] = []
    covers_by_id: dict[str, list[str]] = {}
    artifacts: list[tuple[str, str, str]] = []  # (row id, path, sha-prefix)
    signatures: list[str] = []
    for line in text.splitlines():
        m = _CLAIM_ROW.match(line)
        if m:
            rid, status, cover_field = m.group(1), m.group(3), m.group(4)
            ids.add(rid)
            row_covers = [c.strip() for c in cover_field.split(",")
                          if c.strip() and c.strip() not in {"—", "-"}]
            covers.extend(row_covers)
            covers_by_id[rid] = row_covers
            if status in {"measured", "directional"}:
                rest = line.split("|")[5] if line.count("|") >= 6 else ""
                am = _ARTIFACT.search(rest)
                sha = _ARTIFACT_SHA.search(rest)
                artifacts.append((rid, am.group(1) if am else "",
                                  sha.group(1) if sha else ""))
            continue
        m = _RETRACTED_ROW.match(line)
        if m:
            signatures.extend(s.strip() for s in m.group(1).split(",")
                              if s.strip())
    return {"ids": ids, "covers": covers, "covers_by_id": covers_by_id,
            "artifacts": artifacts, "signatures": signatures}


def _covered(line: str, ledger: dict, errors: list[str],
             where: str) -> bool:
    """Inline claim IDs first (explicit beats regex), cover-string
    containment as the backstop. An unknown ID is itself a failure, and
    so is a known-but-unrelated one (Q2-3 re-check): the CITED row's own
    cover strings must appear in the line — any known ID must not act as
    a universal pass."""
    line_ids = _CLAIM_ID.findall(line)
    covered_by_id = False
    for i in line_ids:
        if i not in ledger["ids"]:
            errors.append(f"{where} carries unknown claim ID [CL:{i}] — "
                          f"no such row in docs/claims-ledger.md")
            continue
        if any(c in line for c in ledger["covers_by_id"].get(i, [])):
            covered_by_id = True
        else:
            errors.append(
                f"{where} cites [CL:{i}] but that row's cover strings do "
                f"not match this line — an unrelated claim ID is not "
                f"evidence")
    if covered_by_id:
        return True
    return any(c in line for c in ledger["covers"])


def check(root: Path = ROOT):
    errors: list[str] = []
    warnings: list[str] = []
    ledger_path = root / "docs" / "claims-ledger.md"
    if not ledger_path.is_file():
        return ["docs/claims-ledger.md is missing"], []
    ledger = parse_ledger(ledger_path.read_text(encoding="utf-8"))
    if not ledger["covers"]:
        return ["no claim rows parsed from docs/claims-ledger.md"], []

    for rid, artifact, sha in ledger["artifacts"]:
        if not artifact:
            errors.append(f"{rid}: measured/directional row has no "
                          f"`artifact` path")
            continue
        if not _allowlisted(artifact, root):
            errors.append(
                f"{rid}: artifact does not resolve into the immutable "
                f"results tree (ctxpack/benchmarks/**/results/**): "
                f"{artifact} — prose is mutable and is not evidence")
        if not (root / artifact).exists():
            errors.append(f"{rid}: artifact does not exist: {artifact}")
        elif sha:
            actual = hashlib.sha256(
                (root / artifact).read_bytes()).hexdigest()
            if not actual.startswith(sha):
                errors.append(
                    f"{rid}: artifact content changed — sha256 committed "
                    f"{sha}, actual {actual[:12]}: {artifact}")

    readme = root / "README.md"
    if readme.is_file():
        for i, line in enumerate(
                readme.read_text(encoding="utf-8").splitlines(), 1):
            where = f"README.md:{i}"
            if any(p.search(line) for p in NUMERIC_PATTERNS):
                if not _covered(line, ledger, errors, where):
                    errors.append(
                        f"{where} carries a numerical claim with no "
                        f"claims-ledger row: {line.strip()[:100]}")
            elif any(w in line.lower() for w in COMPARATIVE_WORDS):
                if not _covered(line, ledger, errors, where):
                    warnings.append(
                        f"{where} qualitative comparative line not "
                        f"in ledger: {line.strip()[:100]}")

    scan_files = [readme] + sorted((root / "paper").glob("*.md")) + [
        p for p in sorted((root / "docs").glob("*.md"))
        if p.name not in {"claims-ledger.md", "notes.md"}]
    for f in scan_files:
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        uncovered_numeric = 0
        first_example = ""
        for i, line in enumerate(
                f.read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.lower()
            in_retraction_ctx = any(ctx in lowered
                                    for ctx in RETRACTION_CONTEXT)
            if not in_retraction_ctx:
                for sig in ledger["signatures"]:
                    if sig in line:
                        errors.append(
                            f"{rel}:{i} retracted claim signature {sig!r} "
                            f"reappears outside a retraction context")
            # Q2-3: numeric coverage beyond README is WARN-only (owner
            # decision: line-FAIL extension waits for false-positive
            # data) — summarized per file so papers can't drown the gate
            if (f != readme and not in_retraction_ctx
                    and any(p.search(line) for p in NUMERIC_PATTERNS)
                    and not _covered(line, ledger, errors, f"{rel}:{i}")):
                uncovered_numeric += 1
                if not first_example:
                    first_example = f"{rel}:{i}: {line.strip()[:80]}"
        if uncovered_numeric:
            warnings.append(
                f"{rel}: {uncovered_numeric} uncovered numeric line(s) "
                f"(warn-only outside README; first: {first_example})")
    return errors, warnings


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
