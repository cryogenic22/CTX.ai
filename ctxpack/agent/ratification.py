"""Explicit ratification events — the ONLY path to USER_RATIFIED.

The reviewer's rule (2026-08-07, binding): ratification is an explicit
event referencing a fact_id — never inferred from git presence, a
marker, or a merge. A merge may later corroborate exact code/test
claims as TOOL_OBSERVED evidence; it must never silently become
USER_RATIFIED. The low-friction path for the cold-start problem is a
batched queue of AGENT_CANDIDATE facts the owner accepts or rejects
one command at a time — not an implicit escalation.

Deliberately a separate file from ``events.jsonl``: that log is derived
from a transcript fold ONLY and stays byte-replayable (spec v1.1 §6). A
ratification is a live owner action with no transcript record — same
design as ``injections.jsonl``.

Rejection is not an authority level: a rejected fact keeps its derived
authority and is excluded by eligibility policy (stable code, Loop 5).
The journal is append-only; the LAST event per fact_id wins, so a
mistaken ratification is corrected by appending a rejection — history
stays auditable, nothing is rewritten.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any

RATIFICATION_LOG = "ratifications.jsonl"
SCHEMA = "ctx-ratifications/v1"

RATIFY = "ratify"
REJECT = "reject"
_ACTIONS = (RATIFY, REJECT)


def record_ratification(ledger_dir: str, fact_id: str, *,
                        action: str = RATIFY, note: str = "",
                        by: str = "owner-cli") -> dict[str, Any]:
    """Append one ratification event. Raises on a malformed request —
    a ratification that cannot be recorded exactly must not happen."""
    fid = str(fact_id or "").strip().lower()
    if not fid or len(fid) != 16 or any(c not in "0123456789abcdef"
                                        for c in fid):
        raise ValueError(f"not a 16-hex fact_id: {fact_id!r}")
    if action not in _ACTIONS:
        raise ValueError(f"action must be one of {_ACTIONS}: {action!r}")
    row: dict[str, Any] = {
        "ts": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "schema": SCHEMA,
        "fact_id": fid,
        "action": action,
        "by": by,
    }
    if note:
        row["note"] = str(note)[:300]
    os.makedirs(ledger_dir, exist_ok=True)
    with open(os.path.join(ledger_dir, RATIFICATION_LOG), "a",
              encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def ratification_state(ledger_dir: str) -> dict[str, str]:
    """``{fact_id: "ratify"|"reject"}`` — last event per fact wins.
    Missing log → {} (nothing was ever ratified; that is a real zero,
    not an unmeasured: ratification only exists through this journal).
    Malformed rows are skipped — a ratification that cannot be read
    exactly confers nothing."""
    state: dict[str, str] = {}
    try:
        with open(os.path.join(ledger_dir, RATIFICATION_LOG),
                  encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                fid = str(row.get("fact_id") or "").lower()
                action = str(row.get("action") or "")
                if len(fid) == 16 and action in _ACTIONS:
                    state[fid] = action
    except OSError:
        return {}
    return state


def is_ratified(ledger_dir: str, fact_id: str) -> bool:
    return ratification_state(ledger_dir).get(
        str(fact_id or "").lower()) == RATIFY
