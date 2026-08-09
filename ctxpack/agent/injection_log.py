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
# v2: the row carries the FULL session id. v1 rows stored an 8-char
# prefix, which collides at team scale — two sessions sharing a prefix
# would both inherit one receipt's outcome. Legacy v1 rows are still
# read, but they join to a session only when the prefix is unambiguous
# among the sessions being classified (see classify_read_path).
SCHEMA = "ctx-injections/v2"

# outcome values
INJECTED = "injected"   # non-empty context handed to the agent
EMPTY = "empty"         # hook ran, had nothing to say (fresh repo, or a gap)
FAILED = "failed"       # hook raised; the session started with no memory

# TM-7: this journal is written where no scanner ever looks, so it must
# never receive free exception text — a message can embed secret bytes
# (a token inside an OSError path). Only these stable codes persist;
# anything else is coerced to "unknown_error", never trusted.
ERROR_CODES = ("startup_read_failed", "egress_scan_failed",
               "emit_failed", "unknown_error")


def record_injection(out_dir: str,
                     *,
                     session_id: str = "",
                     context: str = "",
                     outcome: str = "",
                     error: str = "",
                     error_class: str = "",
                     gap_warning: bool = False,
                     outgoing_redactions: int = 0,
                     source: str = "session-start") -> None:
    """Append one injection row. Never raises.

    ``error`` takes a stable code from :data:`ERROR_CODES`;
    ``error_class`` the raising exception's class name (an identifier,
    or it is dropped). Free text handed to either is never persisted
    (TM-7/TC-13)."""
    try:
        text = context or ""
        if not outcome:
            outcome = INJECTED if text.strip() else EMPTY
        row: dict[str, Any] = {
            "ts": datetime.datetime.now(
                datetime.timezone.utc).isoformat(timespec="seconds"),
            "schema": SCHEMA,
            "session": (session_id or "").strip(),
            "source": source,
            "outcome": outcome,
            "bytes": len(text.encode("utf-8")),
            "sha256": (hashlib.sha256(text.encode("utf-8")).hexdigest()
                       if text else ""),
            "gap_warning": bool(gap_warning),
        }
        if outgoing_redactions:
            # egress scan hits — the emitted bytes were already
            # type-only redacted; the count is the audit trail
            row["outgoing_redactions"] = int(outgoing_redactions)
        if error:
            row["error"] = (error if error in ERROR_CODES
                            else "unknown_error")
        if error_class and str(error_class).isidentifier():
            row["error_class"] = str(error_class)
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, INJECTION_LOG), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:  # noqa: BLE001 — telemetry never breaks session start
        pass


def _read_rows(ledger_dir: str):
    """``(dict_rows, malformed_lines)`` — or ``None`` when the log file
    is absent, which callers must report as unmeasured.

    Only dict rows are returned: a syntactically valid non-object line
    (``[]``, ``"x"``, ``null``, ``42``) is a malformed receipt to be
    counted, never a crash downstream. Bytes are decoded lossily
    (``errors="replace"``) so one invalid byte cannot blind the whole
    log; a line the replacement mangles past JSON is malformed too.
    """
    rows: "list[dict]" = []
    malformed = 0
    try:
        with open(os.path.join(ledger_dir, INJECTION_LOG),
                  encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    malformed += 1
    except OSError:
        return None
    return rows, malformed


def read_injections(ledger_dir: str) -> "list[dict]":
    """Every parseable dict row, oldest first. Missing log → []."""
    got = _read_rows(ledger_dir)
    return got[0] if got is not None else []


# Fold precedence: one success proves an emission happened; a failure
# only proves an attempt broke; only a session whose every receipt says
# "empty" is known to have run clean with nothing to say.
_FOLD_PRECEDENCE = (INJECTED, FAILED, EMPTY)


def _receipt_session_outcome(row: dict):
    """``(session, outcome, kind)`` of a valid receipt, else ``None`` —
    the ONE definition of a valid receipt, shared by
    ``injection_stats`` and the fold so "attempted" and "folded" can
    never disagree about what counts. ``kind`` is the schema route
    (TM-5): ``"full"`` for a declared v2 row, ``"prefix"`` for a
    legacy schemaless v1 row; a row declaring any other schema is not
    a valid receipt."""
    session = str(row.get("session") or "").strip()
    outcome = str(row.get("outcome") or "")
    if not session or outcome not in _FOLD_PRECEDENCE:
        return None
    schema = str(row.get("schema") or "")
    if schema == SCHEMA:
        kind = "full"
    elif not schema:                   # legacy v1: predates the field
        kind = "prefix"
    else:                              # unknown/future schema (TC-11)
        return None
    return session, outcome, kind


def fold_emission_receipts(ledger_dir: str):
    """Deterministic per-session fold of emission receipts.

    ``None`` when the log file is absent — every session's emission is
    unmeasured. Otherwise::

        {"by_full":   {<full session id>: outcome},   # v2 receipts
         "by_prefix": {<8-char prefix>:  outcome},    # legacy v1 rows
         "malformed_rows": <int>,
         "rows": <int>}            # valid receipts that entered a fold

    Fold rule, order-independent: any ``injected`` receipt folds the
    session to ``injected``; otherwise any ``failed`` → ``failed``;
    otherwise ``empty``.

    Routing is by the row's DECLARED ``schema`` (TM-5): a
    ``ctx-injections/v2`` row folds under ``by_full`` no matter how
    short its id — an exactly-8-char v2 session must join exactly, not
    fall into the prefix pool where an unlucky collision makes it
    unmeasured. Rows with no schema field are legacy v1 receipts: they
    stored only an 8-char prefix, which can collide, so they fold
    separately under ``by_prefix``; the join to a session is the
    CALLER's decision and must require the prefix to map to exactly
    one session — an ambiguous prefix is unmeasured, never split or
    duplicated (see ``classify_read_path``). A row declaring any OTHER
    schema is malformed: a future writer's receipts are counted, never
    misread under today's rules.

    A session with no receipt is simply absent and must be reported as
    UNMEASURED: absence of a receipt never proves "no emission", and no
    timestamp is consulted — checkpoint timestamps can be backfilled
    and prove nothing about when a session started.

    ``malformed_rows`` counts everything that cannot enter a fold —
    undecodable lines, non-object JSON, rows without a session, rows
    with an unknown outcome. Reported, never guessed at.
    """
    got = _read_rows(ledger_dir)
    if got is None:
        return None
    rows, malformed = got
    full_seen: "dict[str, set[str]]" = {}
    prefix_seen: "dict[str, set[str]]" = {}
    valid = 0
    for row in rows:
        rec = _receipt_session_outcome(row)
        if rec is None:
            malformed += 1
            continue
        session, outcome, kind = rec
        valid += 1
        bucket = full_seen if kind == "full" else prefix_seen
        bucket.setdefault(session, set()).add(outcome)

    def _fold(seen: "dict[str, set[str]]") -> "dict[str, str]":
        out: "dict[str, str]" = {}
        for key, outcomes in seen.items():
            for outcome in _FOLD_PRECEDENCE:
                if outcome in outcomes:
                    out[key] = outcome
                    break
        return out

    return {"by_full": _fold(full_seen), "by_prefix": _fold(prefix_seen),
            "malformed_rows": malformed, "rows": valid}


def injection_stats(ledger_dir: str) -> dict[str, Any]:
    """Push-path emission record. ``{}`` when nothing was ever logged —
    an absent log means "not measured", never "never injected", and the
    two must not be conflated (that conflation is exactly the bug this
    module exists to fix on the pull side).

    ``attempted`` counts VALID receipts only — the same definition the
    fold uses (``_receipt_session_outcome``) — so a semantically
    invalid object can never count as attempted here while being called
    malformed there."""
    got = _read_rows(ledger_dir)
    if got is None:
        return {}
    rows, malformed = got
    valid_rows: "list[tuple[dict, str]]" = []
    for row in rows:
        rec = _receipt_session_outcome(row)
        if rec is None:
            malformed += 1
        else:
            valid_rows.append((row, rec[1]))
    if not valid_rows and not malformed:
        return {}
    by_outcome: dict[str, int] = {}
    for _, outcome in valid_rows:
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
    sizes = [int(r.get("bytes") or 0) for r, outcome in valid_rows
             if outcome == INJECTED]
    stats: dict[str, Any] = {
        # names the quantity so no reader has to infer it from a label
        "measures": "emitted_to_hook_stdout",
        "attempted": len(valid_rows),
        "injected": by_outcome.get(INJECTED, 0),
        "empty": by_outcome.get(EMPTY, 0),
        "failed": by_outcome.get(FAILED, 0),
        "malformed_rows": malformed,
        "gap_warnings": sum(1 for r, _ in valid_rows
                            if r.get("gap_warning")),
        "emit_success_rate": (round(
            by_outcome.get(INJECTED, 0) / len(valid_rows), 3)
            if valid_rows else None),
        "injected_bytes": ({"min": min(sizes), "max": max(sizes),
                            "mean": round(sum(sizes) / len(sizes), 1)}
                           if sizes else {}),
    }
    if valid_rows:
        latest = valid_rows[-1][0]
        stats["latest"] = {"outcome": latest.get("outcome"),
                           "bytes": latest.get("bytes"),
                           "sha256": str(latest.get("sha256") or "")[:16],
                           "ts": latest.get("ts")}
    return stats
