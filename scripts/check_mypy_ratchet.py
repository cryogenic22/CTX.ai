#!/usr/bin/env python
"""Fail if mypy errors on product code exceed the recorded baseline.

Command (default mode, no network, no --strict)::

    mypy ctxpack --exclude ctxpack/benchmarks

``--exclude`` does not apply to modules that product code imports, so
mypy still reports errors under ``ctxpack/benchmarks/``. Those lines are
not part of this ratchet: the contract is that benchmarks stay out of
the count. The baseline is the error count on everything else, measured
with mypy 2.4.1 after the static fixes and after main gained the brief
composer. Lower ``BASELINE`` when the count drops. Raising it is a
reviewed act, not drift. CI pins mypy==2.4.1 so a later release cannot
move the count by itself.

The script prints ``current`` vs ``baseline`` on stdout.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Measured 56 product errors with mypy 2.4.1 and mcp 1.30.0
# (`mcp>=1.0,<2`): 67 raw lines, 11 of them benchmark follow-imports.
# mcp 2.x stubs add one inputSchema error per tool and are not this line.
# Must stay <= 83.
BASELINE = 56

_FOUND = re.compile(r"Found (\d+) error")
_SUCCESS = "Success: no issues found"


def _is_benchmark(path: str) -> bool:
    norm = path.replace("\\", "/")
    return norm == "ctxpack/benchmarks" or "/benchmarks/" in f"/{norm}" or norm.startswith(
        "ctxpack/benchmarks/"
    )


def summary_error_count(text: str) -> "int | None":
    """The count from mypy's own summary, or None when mypy did not finish.

    A missing interpreter prints ``No module named mypy`` and exits 1 with
    no summary. That must not be read as zero errors.
    """
    found = _FOUND.search(text)
    if found:
        return int(found.group(1))
    if _SUCCESS in text:
        return 0
    return None


def assess(text: str, returncode: int, *, baseline: int = BASELINE) -> int:
    """Exit status for one mypy report. 0 only when the summary is real
    and the product-code error count is within ``baseline``."""
    counted: list[str] = []
    excluded: list[str] = []
    for line in text.splitlines():
        if ": error:" not in line:
            continue
        path = line.split(":", 1)[0]
        if _is_benchmark(path):
            excluded.append(line)
        else:
            counted.append(line)
    summary = summary_error_count(text)
    current = len(counted)
    print(
        f"mypy errors: current={current} baseline={baseline} "
        f"(benchmark follow-imports excluded from the count: {len(excluded)})"
    )
    if summary is None or returncode not in (0, 1):
        sys.stderr.write(text)
        print(
            "MYPY RATCHET FAIL: no mypy summary "
            "(expected 'Found N error' or 'Success: no issues found'); "
            f"exit {returncode}",
            file=sys.stderr,
        )
        return 1
    parsed = current + len(excluded)
    if parsed != summary:
        print(
            f"MYPY RATCHET FAIL: summary says {summary} errors "
            f"but {parsed} error lines were parsed",
            file=sys.stderr,
        )
        return 1
    if current > baseline:
        print(
            f"MYPY RATCHET FAIL: {current} errors exceed baseline {baseline}",
            file=sys.stderr,
        )
        sys.stderr.write("\n".join(counted) + "\n")
        return 1
    if current < baseline:
        print(
            f"mypy count dropped ({current} < {baseline}); "
            "lower BASELINE in scripts/check_mypy_ratchet.py"
        )
    print("mypy ratchet OK")
    return 0


def main() -> int:
    cmd = [
        sys.executable, "-m", "mypy", "ctxpack",
        "--exclude", "ctxpack/benchmarks",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    text = (proc.stdout or "") + (proc.stderr or "")
    return assess(text, proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
