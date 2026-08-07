"""Startup-injection telemetry — did the PUSH path actually deliver?

Two field reports (setu 2026-07-21, OntoWiz 2026-07-25) independently
found that the query tools go uncalled while the SessionStart injection
is the surface those agents report benefiting from. Everything we
measure, though, is downstream of a checkpoint: the checkpoint journal proves
what was WRITTEN, and nothing proved what was READ BACK IN. A hook that
silently emitted an empty gist for a month would look identical to a
healthy one.

This log closes that hole. One append-only row per SessionStart, giving
attempted / injected / empty / failed, plus the size and hash of the
bytes actually handed to the agent.

**What this measures, exactly: bytes successfully written to the
SessionStart hook's stdout.** Not that the harness forwarded them, not
that they entered the model's context, not that the model read them,
and certainly not that they helped. Those are three further steps, all
unmeasured. The name for the quantity is ``emitted_to_hook_stdout``,
and every caller should use it rather than "delivered" — see
``ctxpack.core.states.Delivery``, where the non-inference rule is
executable rather than commented.

The receipt is therefore written AFTER the emission it attests to. An
earlier version recorded first, so a failed stdout flush would have been
banked as a successful emission: a receipt that can be true while the
thing it certifies did not happen is worse than no receipt.

Deliberately a separate file from ``events.jsonl``: that one is derived
at checkpoint from a transcript fold ONLY, so it stays byte-replayable
(spec v1.1 §6). Injection is a live event with no transcript record —
folding it in would make the event log unreproducible.

Every write is fail-open. Telemetry that can break session start is
worse than no telemetry.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from typing import Any

INJECTION_LOG = "injections.jsonl"
SCHEMA = "ctx-injections/v1"

# outcome values
INJECTED = "injected"   # non-empty context handed to the agent
EMPTY = "empty"         # hook ran, had nothing to say (fresh repo, or a gap)
FAILED = "failed"       # hook raised; the session started with no memory


def record_injection(out_dir: str,
                     *,
                     session_id: str = "",
                     context: str = "",
                     outcome: str = "",
                     error: str = "",
                     gap_warning: bool = False,
                     source: str = "session-start") -> None:
    """Append one injection row. Never raises."""
    try:
        text = context or ""
        if not outcome:
            outcome = INJECTED if text.strip() else EMPTY
        row: dict[str, Any] = {
            "ts": datetime.datetime.now(
                datetime.timezone.utc).isoformat(timespec="seconds"),
            "schema": SCHEMA,
            "session": (session_id or "")[:8],
            "source": source,
            "outcome": outcome,
            "bytes": len(text.encode("utf-8")),
            "sha256": (hashlib.sha256(text.encode("utf-8")).hexdigest()
                       if text else ""),
            "gap_warning": bool(gap_warning),
        }
        if error:
            row["error"] = str(error)[:200]
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, INJECTION_LOG), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:  # noqa: BLE001 — telemetry never breaks session start
        pass


def _read_rows(ledger_dir: str):
    """``(rows, malformed_lines)`` — or ``None`` when the log file is
    absent/unreadable, which callers must report as unmeasured."""
    rows: "list[dict]" = []
    malformed = 0
    try:
        with open(os.path.join(ledger_dir, INJECTION_LOG),
                  encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    malformed += 1
    except OSError:
        return None
    return rows, malformed


def read_injections(ledger_dir: str) -> "list[dict]":
    """Every parseable injection row, oldest first. Missing log → []."""
    got = _read_rows(ledger_dir)
    return got[0] if got is not None else []


# Fold precedence: one success proves an emission happened; a failure
# only proves an attempt broke; only a session whose every receipt says
# "empty" is known to have run clean with nothing to say.
_FOLD_PRECEDENCE = (INJECTED, FAILED, EMPTY)


def fold_emission_receipts(ledger_dir: str):
    """Deterministic per-session fold of emission receipts.

    ``None`` when the log file is absent — every session's emission is
    unmeasured. Otherwise::

        {"sessions": {<8-char prefix>: "injected"|"failed"|"empty"},
         "malformed_rows": <int>,
         "rows": <int>}            # receipts that entered the fold

    Fold rule, order-independent: any ``injected`` receipt folds the
    session to ``injected``; otherwise any ``failed`` → ``failed``;
    otherwise ``empty``.

    A session with no receipt is simply absent from ``sessions`` and
    must be reported as UNMEASURED: absence of a receipt never proves
    "no emission", and no timestamp is consulted — checkpoint
    timestamps can be backfilled and prove nothing about when a session
    started. (The retired ``emitted_sessions()`` set API made absence
    look like evidence of non-emission; two review rounds flagged it.)

    ``malformed_rows`` counts lines that cannot enter the fold —
    undecodable JSON, rows without a session prefix, rows with an
    unknown outcome. They are reported, never guessed at.
    """
    got = _read_rows(ledger_dir)
    if got is None:
        return None
    rows, malformed = got
    seen: "dict[str, set[str]]" = {}
    valid = 0
    for row in rows:
        prefix = str(row.get("session") or "")[:8]
        outcome = str(row.get("outcome") or "")
        if not prefix or outcome not in _FOLD_PRECEDENCE:
            malformed += 1
            continue
        valid += 1
        seen.setdefault(prefix, set()).add(outcome)
    folded: "dict[str, str]" = {}
    for prefix, outcomes in seen.items():
        for outcome in _FOLD_PRECEDENCE:
            if outcome in outcomes:
                folded[prefix] = outcome
                break
    return {"sessions": folded, "malformed_rows": malformed, "rows": valid}


def injection_stats(ledger_dir: str) -> dict[str, Any]:
    """Push-path emission record. ``{}`` when nothing was ever logged —
    an absent log means "not measured", never "never injected", and the
    two must not be conflated (that conflation is exactly the bug this
    module exists to fix on the pull side)."""
    got = _read_rows(ledger_dir)
    if got is None:
        return {}
    rows, malformed = got
    if not rows and not malformed:
        return {}
    by_outcome: dict[str, int] = {}
    for row in rows:
        key = str(row.get("outcome") or "unknown")
        by_outcome[key] = by_outcome.get(key, 0) + 1
    sizes = [int(r.get("bytes") or 0) for r in rows
             if str(r.get("outcome")) == INJECTED]
    stats: dict[str, Any] = {
        # names the quantity so no reader has to infer it from a label
        "measures": "emitted_to_hook_stdout",
        "attempted": len(rows),
        "injected": by_outcome.get(INJECTED, 0),
        "empty": by_outcome.get(EMPTY, 0),
        "failed": by_outcome.get(FAILED, 0),
        "malformed_rows": malformed,
        "gap_warnings": sum(1 for r in rows if r.get("gap_warning")),
        "emit_success_rate": (round(
            by_outcome.get(INJECTED, 0) / len(rows), 3) if rows else None),
        "injected_bytes": ({"min": min(sizes), "max": max(sizes),
                            "mean": round(sum(sizes) / len(sizes), 1)}
                           if sizes else {}),
    }
    if rows:
        latest = rows[-1]
        stats["latest"] = {"outcome": latest.get("outcome"),
                           "bytes": latest.get("bytes"),
                           "sha256": str(latest.get("sha256") or "")[:16],
                           "ts": latest.get("ts")}
    return stats
