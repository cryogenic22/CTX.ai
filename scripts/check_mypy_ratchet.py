#!/usr/bin/env python
"""CI ratchet: mypy error count on product code may only go down.

Runs the default-mode command::

    mypy ctxpack --exclude ctxpack/benchmarks

and fails when the reported error total is above ``BASELINE``.

Measure with the same environment CI uses, or the count will not match:

    pip install ".[all,test]" "mypy==2.4.1"
    python scripts/check_mypy_ratchet.py

``--exclude`` does not drop modules that product code imports, so errors
inside ``ctxpack/benchmarks`` that are reached by a followed import still
count. That is what this baseline was measured against.

Before the static fixes on this branch, the same command reported 94
errors (mypy 2.4.1, ``.[all,test]`` installed, mcp 2.3.0). After those
fixes it reports 78. The task cap is 83; do not raise ``BASELINE``.
Lower it in the same change that removes errors.
"""
from __future__ import annotations

import re
import subprocess
import sys

# Measured after the static fixes. Must stay <= CAP.
BASELINE = 78
CAP = 83

_FOUND = re.compile(r"Found (\d+) error")


def count_mypy_errors(text: str, returncode: int) -> int:
    """Parse mypy's summary. A clean run is 0. A crash with no summary
    is not a count — the caller should fail closed."""
    match = _FOUND.search(text)
    if match:
        return int(match.group(1))
    if returncode == 0:
        return 0
    raise ValueError(
        f"mypy exited {returncode} without a 'Found N errors' summary"
    )


def main(argv: list[str] | None = None) -> int:
    if BASELINE > CAP:
        print(f"mypy ratchet: baseline {BASELINE} exceeds cap {CAP}",
              file=sys.stderr)
        return 1
    cmd = [
        sys.executable, "-m", "mypy",
        "ctxpack", "--exclude", "ctxpack/benchmarks",
    ]
    if argv:
        cmd.extend(argv)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    text = (proc.stdout or "") + (proc.stderr or "")
    try:
        current = count_mypy_errors(text, proc.returncode)
    except ValueError as exc:
        print(f"mypy ratchet: {exc}", file=sys.stderr)
        if text.strip():
            sys.stderr.write(text if text.endswith("\n") else text + "\n")
        return 1
    relation = "ok" if current <= BASELINE else "FAIL"
    print(f"mypy ratchet: current={current} baseline={BASELINE} ({relation})")
    if current < BASELINE:
        print(f"mypy ratchet: current is below baseline; "
              f"lower BASELINE to {current} in this script to lock the win")
    if current > BASELINE:
        print(text, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
