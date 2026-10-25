"""Explicit ratification events — the LOCAL INTENT MARKER axis.

PF-11 v2.1 (approved 2026-08-09): a ratification event attests exactly
one thing — a local actor invoked the CLI — and the resident agent IS
a local actor, so this axis carries no security standing beyond an
agent candidate. It is bookkeeping ("someone at this machine chose to
keep this"), never approval: there is no user_ratified anywhere, and
the owner-approval axis stays unsatisfiable until a trusted human
channel exists. Ratification remains an explicit event referencing a
fact_id — never inferred from git presence, a marker, or a merge (a
merge may later corroborate exact code/test claims as TOOL_OBSERVED
evidence; evidence, not intent).

Deliberately a separate file from ``events.jsonl``: that log is derived
from a transcript fold ONLY and stays byte-replayable (spec v1.1 §6). A
ratification is a live local-actor action with no transcript record —
same design as ``injections.jsonl``. The ``by`` attribution is
``local-cli``: a label for the unauthenticated local invocation path,
NEVER a claim about who (or what) typed the command — any process that
can run the CLI can mint one, which is exactly why this axis carries
no standing (PF-11 P1-2 ruling).

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

# A fact_id is either a legacy 16-hex id (:func:`ctxpack.core.factid.fact_id`)
# or a DI-01 exact 64-hex id (:func:`ctxpack.core.factid.exact_fact_id`). Both
# are ratifiable — an exact literal you can find via `why` you must be able to
# ratify. Only EXACTLY those two lengths are accepted, never a range: a 40-hex
# git sha or a 17-hex typo stays malformed (no weakening of the strict gate).
_FACT_ID_LENS = (16, 64)


def record_ratification(ledger_dir: str, fact_id: str, *,
                        action: str = RATIFY, note: str = "",
                        by: str = "local-cli") -> dict[str, Any]:
    """Append one ratification event. Raises on a malformed request —
    a ratification that cannot be recorded exactly must not happen."""
    fid = str(fact_id or "").strip().lower()
    if (not fid or len(fid) not in _FACT_ID_LENS
            or any(c not in "0123456789abcdef" for c in fid)):
        raise ValueError(f"not a 16- or 64-hex fact_id: {fact_id!r}")
    if action not in _ACTIONS:
        raise ValueError(f"action must be one of {_ACTIONS}: {action!r}")
    if not isinstance(by, str) or not by.strip():
        # validated BEFORE writing: the public API must not be able to
        # create a row the strict reader rejects (re-re-review)
        raise ValueError(f"by must be a non-empty string: {by!r}")
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
    # Encode BEFORE opening and append the finished bytes in binary —
    # validation and encoding failures cannot partially append a row,
    # and there is no platform newline translation. An interrupted
    # filesystem write can still truncate mid-row; the strict reader
    # detects that and degrades (reviewer wording, 2026-08-10).
    # json.dumps with ensure_ascii keeps the file pure ASCII, so the
    # strict reader can never reject bytes this writer produced.
    row_bytes = (json.dumps(row) + "\n").encode("utf-8")
    os.makedirs(ledger_dir, exist_ok=True)
    with open(os.path.join(ledger_dir, RATIFICATION_LOG), "ab") as f:
        f.write(row_bytes)
    return row


def _row_is_valid(row) -> "tuple[str, str] | None":
    """``(fact_id, action)`` for a complete, schema-correct row; else
    ``None``. Strict by design (TM-3, tightened in the 2026-08-09
    re-review): schema string, 16- or 64-hex id, known action, ISO-8601
    ``ts`` and a non-empty ``by`` actor — a row that cannot be read EXACTLY,
    including WHEN it happened and through WHICH path, confers nothing
    and taints the journal."""
    if not isinstance(row, dict):
        return None
    if row.get("schema") != SCHEMA:
        return None
    fid = str(row.get("fact_id") or "").lower()
    action = str(row.get("action") or "")
    if len(fid) not in _FACT_ID_LENS or any(
            c not in "0123456789abcdef" for c in fid):
        return None
    if action not in _ACTIONS:
        return None
    ts = row.get("ts")
    if not isinstance(ts, str):
        return None
    try:
        datetime.datetime.fromisoformat(ts)
    except ValueError:
        return None
    by = row.get("by")
    if not isinstance(by, str) or not by.strip():
        return None
    return fid, action


def read_ratifications(ledger_dir: str) -> dict:
    """The journal with its integrity state (TM-3/TM-16, fail-closed).

    Returns ``{"state": {fact_id: action}, "malformed_rows": int,
    "degraded": bool, "quarantined": int}``, plus a stable
    non-sensitive ``"error"`` code when the journal could not be read
    at all.

    ANY malformed row degrades the whole journal: ``state`` comes back
    EMPTY, because a truncated rejection could otherwise leave an
    earlier ratification silently active — and the reader cannot know
    which rows are missing. Bytes decode STRICTLY (re-re-review
    2026-08-09): an invalid UTF-8 byte anywhere in a row makes that
    row malformed — ``errors="replace"`` let mojibake land in ``note``
    or ``by`` while the row kept conferring ratify. Only a genuinely
    ABSENT file is a real zero; every other read failure (permissions,
    a directory squatting on the path, I/O) degrades with
    ``journal_read_failed`` — unknown must never present as
    healthy-empty. Recovery is quarantine rotation
    (:func:`quarantine_rotation`) plus fresh events in a new epoch;
    appending to a corrupted journal restores nothing. ``quarantined``
    counts prior epochs so a rotation can never be silent. The
    availability loss under deliberate corruption is the accepted
    TM-16 trade-off: fail-closed integrity outranks availability for
    a signal that is only a local intent marker.
    """
    quarantined = 0
    try:
        for name in os.listdir(ledger_dir):
            if name.startswith(RATIFICATION_LOG + ".quarantine-"):
                quarantined += 1
    except OSError:
        pass
    try:
        with open(os.path.join(ledger_dir, RATIFICATION_LOG), "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return {"state": {}, "malformed_rows": 0, "degraded": False,
                "quarantined": quarantined}
    except OSError:
        return {"state": {}, "malformed_rows": 0, "degraded": True,
                "error": "journal_read_failed",
                "quarantined": quarantined}
    state: dict[str, str] = {}
    malformed = 0
    for rawline in raw.split(b"\n"):
        if not rawline.strip():
            continue
        try:
            line = rawline.decode("utf-8")
        except UnicodeDecodeError:
            malformed += 1
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        rec = _row_is_valid(row)
        if rec is None:
            malformed += 1
            continue
        state[rec[0]] = rec[1]
    degraded = malformed > 0
    return {"state": {} if degraded else state,
            "malformed_rows": malformed, "degraded": degraded,
            "quarantined": quarantined}


def quarantine_rotation(ledger_dir: str) -> str:
    """Rotate the corrupted journal aside and start a fresh epoch.

    The corrupted file is renamed to
    ``ratifications.jsonl.quarantine-<n>`` — preserved verbatim for
    audit, never edited, never read for state. Returns the quarantine
    path. Raises when there is no journal to rotate.
    """
    src = os.path.join(ledger_dir, RATIFICATION_LOG)
    if not os.path.exists(src):
        raise FileNotFoundError(f"no ratification journal at {src}")
    n = 1
    while os.path.exists(f"{src}.quarantine-{n}"):
        n += 1
    dst = f"{src}.quarantine-{n}"
    os.replace(src, dst)
    return dst


def ratification_state(ledger_dir: str) -> dict[str, str]:
    """``{fact_id: "ratify"|"reject"}`` — last valid event per fact
    wins; EMPTY when the journal is degraded (fail-closed) or absent
    (a real zero: ratification only exists through this journal)."""
    return read_ratifications(ledger_dir)["state"]


def is_ratified(ledger_dir: str, fact_id: str) -> bool:
    return ratification_state(ledger_dir).get(
        str(fact_id or "").lower()) == RATIFY
