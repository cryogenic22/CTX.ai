#!/usr/bin/env python
"""CI gate: every ctxpack module is classified in docs/capability-registry.md.

Execution-plan task W1-1 (docs/execution-plan-2026-07.md). Fails when:

  * a ``ctxpack/**/*.py`` file is covered by no registry row
  * a registry row names a path that no longer exists
  * a row uses an unknown class
  * README.md mentions an experimental/legacy ``Aka`` name on a line
    that does not carry its label

Precision-first: rows are exact files or directory prefixes (trailing
``/``), most-specific match wins, no fuzzy matching. Stdlib only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs" / "capability-registry.md"
README = ROOT / "README.md"
CLASSES = {"core", "eval", "experimental", "legacy-deprecation-candidate"}
SKIP_BASENAMES = {"__init__.py", "__main__.py"}

_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([a-z-]+)\s*\|\s*([^|]*)\|")


def load_rows(text: str) -> list[tuple[str, str, list[str]]]:
    rows = []
    for line in text.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        path = m.group(1).strip()
        cls = m.group(2).strip()
        aka_field = m.group(3).strip()
        akas = [a.strip() for a in aka_field.split(",")
                if a.strip() and a.strip() not in {"—", "-"}]
        rows.append((path, cls, akas))
    return rows


def classify(rel: str, rows: list[tuple[str, str, list[str]]]):
    """Most-specific row covering ``rel`` (posix path), or None."""
    best = None
    for path, cls, _ in rows:
        covered = rel == path or (path.endswith("/") and rel.startswith(path))
        if covered and (best is None or len(path) > len(best[0])):
            best = (path, cls)
    return best


def check(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    registry = root / "docs" / "capability-registry.md"
    if not registry.is_file():
        return ["docs/capability-registry.md is missing"]
    rows = load_rows(registry.read_text(encoding="utf-8"))
    if not rows:
        return ["no registry rows parsed from docs/capability-registry.md"]

    for path, cls, _ in rows:
        if cls not in CLASSES:
            errors.append(f"row `{path}` has unknown class {cls!r} "
                          f"(allowed: {', '.join(sorted(CLASSES))})")
        if not (root / path.rstrip("/")).exists():
            errors.append(f"row points at missing path: {path}")

    for f in sorted((root / "ctxpack").rglob("*.py")):
        if f.name in SKIP_BASENAMES:
            continue
        rel = f.relative_to(root).as_posix()
        if classify(rel, rows) is None:
            errors.append(f"unclassified module: {rel} — add a row to "
                          f"docs/capability-registry.md")

    readme = root / "README.md"
    if readme.is_file():
        readme_lines = readme.read_text(encoding="utf-8").splitlines()
        for path, cls, akas in rows:
            if cls not in {"experimental", "legacy-deprecation-candidate"}:
                continue
            for aka in akas:
                for i, line in enumerate(readme_lines, 1):
                    lowered = line.lower()
                    if aka in line and "experimental" not in lowered \
                            and "legacy" not in lowered:
                        errors.append(
                            f"README.md:{i} mentions {aka!r} ({cls}) on a "
                            f"line without its label")
    return errors


def main() -> int:
    errors = check()
    for e in errors:
        print(f"CAPABILITY-REGISTRY: {e}")
    if errors:
        print(f"capability registry gate: {len(errors)} problem(s)")
        return 1
    print("capability registry gate: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
