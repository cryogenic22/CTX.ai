#!/usr/bin/env python3
"""Read-only status of the agent coordination board (AGENT_COORDINATION.md).

Non-blocking by design — it never fails a build. It just makes the board's
open state visible: open reviewer questions, active owner, stale handoffs,
do-not-touch surfaces, and unresolved reviewer notes. This is the
precision-first alternative to a hard CI gate (a gate that cries wolf on
every "relevant" change gets muted, and a muted signal is worse than none).

    python scripts/coordination_check.py [--file AGENT_COORDINATION.md]
                                         [--stale-days 3]

Exit code is always 0 when the board parses (the board's state is the
signal, not the exit code); 1 only if the board file is missing.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _sections(text: str) -> "dict[str, list[str]]":
    """Map each '## Heading' to its body lines (until the next '## ')."""
    out: "dict[str, list[str]]" = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return out


def _field(lines: "list[str]", label: str) -> str:
    """Value of a '- **Label:** value' (or '- Label: value') line.

    Bold is stripped only around the LABEL — never inside the value, so a
    value like ``ctxpack/benchmarks/**/results/`` keeps its ``**``."""
    lab = label.strip().lower()
    for ln in lines:
        s = re.sub(r"^\s*[-*]\s*", "", ln.strip())   # drop the list bullet
        if ":" not in s:
            continue
        left, right = s.split(":", 1)
        if left.replace("**", "").replace("__", "").strip().lower() == lab:
            # the label's closing bold can sit at the value's start; strip
            # only that leading marker, leaving any bold inside the value
            return re.sub(r"^\s*(?:\*\*|__)\s*", "", right).strip()
    return ""


def _open_questions(lines: "list[str]") -> "tuple[list[str], int]":
    """(unchecked question titles, resolved count) from '- [ ]'/'- [x]'."""
    open_q: "list[str]" = []
    resolved = 0
    for ln in lines:
        s = ln.strip()
        if s.startswith("- [ ]"):
            open_q.append(s[5:].strip().strip("*").strip())
        elif s[:5].lower() == "- [x]":
            resolved += 1
    return open_q, resolved


def _handoffs(lines: "list[str]") -> "list[tuple[str, datetime.date | None]]":
    """(heading, parsed date or None) for each '### ' entry, in file order."""
    out = []
    for ln in lines:
        if ln.startswith("### "):
            head = ln[4:].strip()
            m = _DATE_RE.search(head)
            d = None
            if m:
                try:
                    d = datetime.date.fromisoformat(m.group(1))
                except ValueError:
                    d = None
            out.append((head, d))
    return out


_STATUS_MARKER_RE = re.compile(r"(?:\*\*|__)?status(?:\*\*|__)?\s*:",
                               re.IGNORECASE)
_RESOLVED_RE = re.compile(r"\b(?:resolved|closed|done|answered)\b",
                          re.IGNORECASE)


def _status_values(line: str) -> "list[str]":
    """Extract every Status: value from a reviewer-note line."""
    values = []
    for m in _STATUS_MARKER_RE.finditer(line):
        value = line[m.end():]
        # Inline findings usually bold only the status value:
        # ``... **Status: resolved** - more text``. Stop at that delimiter
        # without requiring it for plain ``- Status: resolved`` lines.
        value = re.split(r"(?:\*\*|__)", value, maxsplit=1)[0]
        values.append(value.strip(" \t-—.;:"))
    return values


def _unresolved_notes(lines: "list[str]") -> "list[str]":
    """'### ' reviewer-note entries whose Status: fields are not resolved.

    Matches the Status value with word boundaries, so ``Status: unresolved``
    is NOT counted as resolved (a substring check treats "unresolved" as
    "resolved"). A note with no Status line is treated as unresolved."""
    notes: "list[str]" = []
    cur = None
    statuses: "list[str]" = []

    def _flush() -> None:
        if cur is not None and (
                not statuses
                or any(not _RESOLVED_RE.search(status)
                       for status in statuses)):
            notes.append(cur)

    for ln in lines:
        if ln.startswith("### "):
            _flush()
            cur, statuses = ln[4:].strip(), []
        elif cur is not None:
            statuses.extend(_status_values(ln))
    _flush()
    return notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Coordination board status.")
    ap.add_argument("--file", default="AGENT_COORDINATION.md")
    ap.add_argument("--stale-days", type=int, default=3)
    args = ap.parse_args(argv)

    if not os.path.exists(args.file):
        print(f"coordination: no board at {args.file}", file=sys.stderr)
        return 1
    with open(args.file, encoding="utf-8") as f:
        secs = _sections(f.read())

    state = secs.get("Current Repo State", [])
    open_q, resolved = _open_questions(secs.get("Open Reviewer Questions", []))
    handoffs = _handoffs(secs.get("Handoffs", []))
    unresolved = _unresolved_notes(secs.get("Reviewer Notes", []))

    print(f"Agent coordination board — {args.file}")
    print(f"  branch:       {_field(state, 'Branch') or '(unset)'}")
    print(f"  active owner: {_field(state, 'Active owner') or '(unset)'}")
    print(f"  do not touch: {_field(state, 'Do not touch') or '(none listed)'}")

    print(f"\nOpen reviewer questions: {len(open_q)} ({resolved} resolved)")
    for q in open_q:
        print(f"  [ ] {q}")

    print(f"\nHandoffs: {len(handoffs)}")
    if handoffs:
        head, d = handoffs[-1]
        if d is not None:
            age = (datetime.date.today() - d).days
            flag = f"  <-- STALE (>{args.stale_days}d)" if age > args.stale_days else ""
            print(f"  latest: {head}  ({age}d ago){flag}")
        else:
            print(f"  latest: {head}  (no parseable date)")

    print(f"\nUnresolved reviewer notes: {len(unresolved)}")
    for n in unresolved:
        print(f"  - {n}")

    return 0  # non-blocking: always succeed when the board parses


if __name__ == "__main__":
    sys.exit(main())
