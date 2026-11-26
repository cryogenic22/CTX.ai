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

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# mypy 2.4.1, `.[all,test]` installed. 78 after the static fixes; 79 once
# main's brief composer (one new Tool inputSchema error) is in the tree.
# Benchmark follow-import errors are excluded. Must stay <= 83.
BASELINE = 79


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
