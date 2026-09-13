"""One-shot pseudonymizer for the rank/v1 labeled fixture (E-6A).

The fixture rows carry NO prose — only extraction metadata (kind,
basis, literal_kind, marker, turn) and content-addressed fact ids.
The privacy-class content was exactly: the real cohort working
directory stamped as ``cwd`` on every row, the real session UUID, and
the real checkpoint id. This script replaces all three with fixed
synthetic values and touches nothing else, so the rank fold's scores
are unchanged (``cwd`` only feeds the eval-workspace exclusion, which
compares against ``labels.json``'s project_root — rewritten to match).

Deliberately generic: it maps WHATEVER cwd/session/checkpoint values
appear in the input, so no personal path is embedded here. Idempotent.

Usage:  python anonymize_fixture.py <events.jsonl>   (rewrites in place)

Receipt (E-6A, 2026-07-12): applied to the ratified KP_SDLC fixture —
extraction metadata, turns, and fact ids byte-identical; only the
three identifying fields changed. The pre-anonymization file remains
in git history pending the owner call on a history rewrite.
"""

import json
import sys

ANON_ROOT = "C:\\cohort\\sdlc-anon"
ANON_SESSION = "e6a00000-0000-4000-8000-00000000e6a0"
ANON_CHECKPOINT = "e6a0c4ec0001"


def anonymize_rows(rows):
    for r in rows:
        if "cwd" in r:
            r["cwd"] = ANON_ROOT
        if "session" in r:
            r["session"] = ANON_SESSION
        if "checkpoint" in r:
            r["checkpoint"] = ANON_CHECKPOINT
    return rows


def main(path):
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    anonymize_rows(rows)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"pseudonymized {len(rows)} rows in {path}")


if __name__ == "__main__":
    main(sys.argv[1])
