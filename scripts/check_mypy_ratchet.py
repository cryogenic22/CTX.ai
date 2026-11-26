#!/usr/bin/env python
"""Fail if mypy errors on product code exceed the recorded baseline.

Command (default mode, no network, no --strict)::

    mypy ctxpack --exclude ctxpack/benchmarks

``--exclude`` does not apply to modules that product code imports, so
mypy still reports errors under ``ctxpack/benchmarks/``. Those lines are
not part of this ratchet: the contract is that benchmarks stay out of
the count. The baseline is the error count on everything else, measured
on this branch after the static fixes. Lower ``BASELINE`` when the count
drops. Raising it is a reviewed act, not drift.

The script prints ``current`` vs ``baseline`` on stdout.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Measured with `.[all,test]` installed (optional imports resolved) after
# the static fixes on this branch. Benchmark follow-import errors are
# excluded from the count. Must stay <= 83.
BASELINE = 78


def _is_benchmark(path: str) -> bool:
    norm = path.replace("\\", "/")
    return norm == "ctxpack/benchmarks" or "/benchmarks/" in f"/{norm}" or norm.startswith(
        "ctxpack/benchmarks/"
    )


def main() -> int:
    cmd = [
        sys.executable, "-m", "mypy", "ctxpack",
        "--exclude", "ctxpack/benchmarks",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    text = (proc.stdout or "") + (proc.stderr or "")
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
    current = len(counted)
    print(
        f"mypy errors: current={current} baseline={BASELINE} "
        f"(benchmark follow-imports excluded from the count: {len(excluded)})"
    )
    # mypy exits 1 when it found errors, 2 when it crashed. A crash is
    # never a pass, even if the parsed count is within the baseline.
    if proc.returncode not in (0, 1):
        sys.stderr.write(text)
        print(f"mypy failed to run (exit {proc.returncode})", file=sys.stderr)
        return 1
    if current > BASELINE:
        print(
            f"MYPY RATCHET FAIL: {current} errors exceed baseline {BASELINE}",
            file=sys.stderr,
        )
        sys.stderr.write("\n".join(counted) + "\n")
        return 1
    if current < BASELINE:
        print(
            f"mypy count dropped ({current} < {BASELINE}); "
            "lower BASELINE in scripts/check_mypy_ratchet.py"
        )
    print("mypy ratchet OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
