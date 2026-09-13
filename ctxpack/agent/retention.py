"""Retention/deletion of per-session ledger artifacts (PF-15, TM-15-bound).

The deletion unit is itself an attack surface (PF-11 §TM-15): path
traversal in candidate lists, symlinks/junctions pointing outside the
ledger, TOCTOU between plan and apply, and a dry-run that diverges from
what apply actually deletes. Every control here is structural, not
advisory:

- **Scope is a closed set.** Only direct children of the ledger dir
  named ``session-<prefix>.ctx`` / ``session-<prefix>-gist.md`` are ever
  candidates. ``latest-gist.md``, ``project-gist.md``, every journal
  (``checkpoints/events/injections/ratifications``.jsonl) and every
  quarantine file are outside the vocabulary — they cannot be selected,
  not merely "are not selected".
- **Ordering comes from the checkpoint journal only.** The keep-window
  is the last N distinct session ids by journal append order — never
  mtime (backfilled timestamps prove nothing, and mtime comparison is
  this repo's recorded IncrementalPacker sin). A journal that cannot be
  read exactly (any malformed row) REFUSES the whole plan: a destructive
  operation does not guess at ordering (fail-closed, TM-3 discipline).
- **Links are never followed and never deleted** (TC-18): any symlink or
  Windows reparse point (junctions included) is skipped and reported, at
  enumeration AND re-checked at unlink time.
- **Containment is re-checked at unlink time**: a candidate must
  realpath-resolve inside the ledger dir both when planned and when
  unlinked.
- **Apply confirms a plan hash** (TC-19): ``apply`` recomputes the plan
  from current state and compares its sha256 (path + size + content
  sha256 of every deletion) against the hash the caller confirms. ANY
  drift — a new session, an added candidate, swapped file bytes —
  aborts with a controlled nonzero before anything is unlinked.
- **Unattributable files are never deleted**: artifacts with no journal
  row (orphans) and prefixes shared by more than one full session id
  (ambiguous) are skipped and reported.

Honesty (PF-15 mandate): deleting ledger artifacts deletes ONLY the
ledger's copy. See :data:`UPSTREAM_NOTE` — no claim is ever made about
the vendor transcript store.

Receipts: ``apply`` appends one row to ``retention.jsonl`` AFTER the
deletions it attests to (same order-of-write rule as the injection log).
Rows carry ledger-relative paths and stable reason codes only — never
exception text, never absolute paths (TM-7/TM-14 discipline). The
receipt is a live journal like ``injections.jsonl``, deliberately
outside the byte-replayable transcript fold.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import stat
from dataclasses import dataclass, field

RETENTION_LOG = "retention.jsonl"
# v2 (Finding 3, 2026-08-23): v1 hashed only the delete entries, so an
# added orphan, a link swap among skipped rows, or a DIFFERENT ledger
# with the same delete set all left the confirmation valid. v2 binds
# the full plan state — see _hash_plan.
# v3 (RF5, 2026-08-24): kept-session artifacts were skipped BEFORE they
# reached the hash, so kept `.ctx`/gist drift was invisible; v3 binds
# every candidate by disposition (delete/kept/skipped).
PLAN_SCHEMA = "ctx-retention-plan/v3"
RECEIPT_SCHEMA = "ctx-retention/v1"

CTX_PREFIX, CTX_SUFFIX = "session-", ".ctx"
GIST_SUFFIX = "-gist.md"

# Fixed reason codes — the only strings that can reach a receipt row
# (TM-7 discipline: a journal must be structurally unable to receive
# free text).
SKIP_LINK = "link"                      # symlink/junction/reparse point
SKIP_OUTSIDE = "outside_ledger"         # realpath escaped the ledger dir
SKIP_NOT_REGULAR = "not_regular"        # directory or special file
SKIP_ORPHAN = "orphan"                  # no journal row claims it
SKIP_AMBIGUOUS = "ambiguous_prefix"     # >1 full id shares the 8-char prefix
SKIP_UNREADABLE = "unreadable"          # lstat/read failed at plan time
SKIP_UNLINK_FAILED = "unlink_failed"    # os.remove failed at apply time
SKIP_REASONS = (SKIP_LINK, SKIP_OUTSIDE, SKIP_NOT_REGULAR, SKIP_ORPHAN,
                SKIP_AMBIGUOUS, SKIP_UNREADABLE, SKIP_UNLINK_FAILED)

# Refusal codes (controlled aborts; the CLI maps every one to a nonzero
# exit, never a traceback)
ERR_INVALID_KEEP = "invalid_keep"
ERR_NO_JOURNAL = "no_journal"
ERR_JOURNAL_DEGRADED = "journal_degraded"
ERR_PLAN_MISMATCH = "plan_mismatch"
ERR_RECEIPT_WRITE_FAILED = "receipt_write_failed"
ERR_ROOT_LINK = "ledger_root_link"
ERR_ROOT_INVALID = "ledger_root_invalid"

UPSTREAM_NOTE = (
    "Note: this deletes artifacts inside the ledger dir ONLY. The vendor "
    "transcript store (e.g. ~/.claude/projects/**) is upstream-controlled "
    "and is not touched; no claim is made about upstream retention.")


class RetentionError(Exception):
    """Controlled refusal. ``code`` is one of the ERR_* constants;
    ``detail`` may carry ledger-relative paths or counts ONLY — never
    exception text (TM-7)."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


@dataclass
class PlanEntry:
    path: str       # ledger-relative (a direct-child filename)
    size: int
    sha256: str


@dataclass
class RetentionPlan:
    keep: int
    sessions_total: int                      # distinct ids in the journal
    kept_sessions: "list[str]"               # full ids, newest last
    delete: "list[PlanEntry]" = field(default_factory=list)
    skipped: "list[tuple[str, str]]" = field(default_factory=list)
    # kept-session artifacts (RF5): recorded with their content digest
    # so adding/removing/replacing a kept .ctx/gist invalidates the
    # confirmation too — the "WHOLE plan" contract, not just deletions.
    kept: "list[PlanEntry]" = field(default_factory=list)
    rows_unattributed: int = 0               # journal rows with no session id
    plan_hash: str = ""


@dataclass
class RetentionResult:
    plan: RetentionPlan
    deleted: "list[str]" = field(default_factory=list)
    skipped: "list[tuple[str, str]]" = field(default_factory=list)
    receipt_written: bool = False


def _is_link(path: str) -> bool:
    """True for anything that must never be followed or deleted: POSIX
    symlinks and every Windows reparse point (junctions included —
    ``islink`` alone misses those)."""
    if os.path.islink(path):
        return True
    try:
        st = os.lstat(path)
    except OSError:
        return False        # enumeration reports lstat failures separately
    attrs = getattr(st, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attrs & reparse)


def _root_reason(ledger_dir: str):
    """Refusal code when the ledger root itself cannot be trusted as a
    deletion root, else ``None`` (Finding 2, 2026-08-23): a root that
    is a symlink/junction/reparse point makes every "inside the
    ledger" claim actually mean "inside the link's TARGET" — journal
    reads, enumeration, and containment would all follow it. Checked
    BEFORE the journal is read, again at apply (which replans), and
    immediately before every unlink."""
    try:
        st = os.lstat(ledger_dir)
    except OSError:
        return ERR_ROOT_INVALID
    if _is_link(ledger_dir):
        return ERR_ROOT_LINK
    if not stat.S_ISDIR(st.st_mode):
        return ERR_ROOT_INVALID
    return None


def _contained(path: str, root: str) -> bool:
    rp = os.path.normcase(os.path.realpath(path))
    root_rp = os.path.normcase(os.path.realpath(root))
    return rp.startswith(root_rp + os.sep)


def _unsafe_reason(path: str, root: str):
    """The last-line guard shared by plan and unlink: reason code when
    ``path`` must not be deleted, else ``None``. Checked at plan time
    AND again immediately before every ``os.remove`` — the plan hash
    should catch all drift first, but the unlink guard does not trust
    that it did."""
    if _is_link(path):
        return SKIP_LINK
    try:
        st = os.lstat(path)
    except OSError:
        return SKIP_UNREADABLE
    if not stat.S_ISREG(st.st_mode):
        return SKIP_NOT_REGULAR
    if not _contained(path, root):
        return SKIP_OUTSIDE
    return None


def _session_prefix(name: str):
    """The 8-char-prefix key of a session artifact filename, else None.
    Only these two shapes exist in retention's vocabulary."""
    if not name.startswith(CTX_PREFIX):
        return None
    if name.endswith(GIST_SUFFIX):
        stem = name[len(CTX_PREFIX):-len(GIST_SUFFIX)]
    elif name.endswith(CTX_SUFFIX):
        stem = name[len(CTX_PREFIX):-len(CTX_SUFFIX)]
    else:
        return None
    return stem or None


def _journal_order(ledger_dir: str):
    """``(ordered distinct full ids, rows_unattributed)`` from
    ``checkpoints.jsonl`` append order (last appearance wins).

    Fail-closed: a missing journal or ANY malformed row refuses the
    plan — deletion ordering is never guessed from a journal that
    cannot be read exactly."""
    path = os.path.join(ledger_dir, "checkpoints.jsonl")
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        raise RetentionError(ERR_NO_JOURNAL)
    except OSError:
        # an unreadable journal is not a missing one (TM-3): refuse,
        # never treat as empty
        raise RetentionError(ERR_JOURNAL_DEGRADED, "journal unreadable")
    ordered: "list[str]" = []
    unattributed = 0
    for i, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RetentionError(ERR_JOURNAL_DEGRADED, f"row {i}")
        if not isinstance(row, dict) or not isinstance(
                row.get("session", ""), str):
            raise RetentionError(ERR_JOURNAL_DEGRADED, f"row {i}")
        sid = row.get("session", "")
        if not sid:
            unattributed += 1
            continue
        if sid in ordered:
            ordered.remove(sid)     # last appearance decides recency
        ordered.append(sid)
    return ordered, unattributed


def _hash_plan(ledger_dir: str, keep: int, ordered: "list[str]",
               unattributed: int, delete: "list[PlanEntry]",
               skipped: "list[tuple[str, str]]",
               kept: "list[PlanEntry]") -> str:
    """The confirmation binds the WHOLE plan state (Findings 3 + 5),
    every candidate artifact by disposition — not just the delete set:

    - ledger identity (canonical realpath) — a hash produced against
      ledger A can never authorize the same delete set in ledger B;
      the path enters only this preimage, never any persisted output;
    - the full ordered journal session list + unattributed row count —
      any window shift or journal growth invalidates;
    - every DELETE artifact's path + size + content sha256;
    - every KEPT artifact's path + size + content sha256 (RF5) — adding,
      removing, or replacing a kept `.ctx`/gist between plan and apply
      invalidates the confirmation, so the "WHOLE plan" contract is real
      and not just deletion-affecting drift;
    - every candidate-shaped SKIPPED row (path, reason) — an orphan
      appearing, a link swap, or an ambiguity change invalidates even
      though the delete set is unchanged.
    """
    def _entries(es):
        return [{"path": e.path, "size": e.size, "sha256": e.sha256}
                for e in sorted(es, key=lambda e: e.path)]

    payload = {
        "schema": PLAN_SCHEMA,
        "ledger": os.path.normcase(os.path.realpath(ledger_dir)),
        "keep": keep,
        "sessions": list(ordered),
        "rows_unattributed": unattributed,
        "delete": _entries(delete),
        "kept": _entries(kept),
        "skipped": [{"path": p, "reason": r}
                    for p, r in sorted(skipped)],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def plan_retention(ledger_dir: str, keep: int) -> RetentionPlan:
    """Deterministic deletion plan: same ledger bytes ⇒ same plan and
    same ``plan_hash`` (sorted enumeration, journal-order window, no
    wall-clock anywhere in the plan)."""
    if not isinstance(keep, int) or keep < 1:
        raise RetentionError(ERR_INVALID_KEEP, str(keep))
    root_bad = _root_reason(ledger_dir)     # before ANY read (Finding 2)
    if root_bad:
        raise RetentionError(root_bad)
    ordered, unattributed = _journal_order(ledger_dir)
    kept = ordered[-keep:]
    prefix_ids: "dict[str, set[str]]" = {}
    for sid in ordered:
        prefix_ids.setdefault(sid[:8], set()).add(sid)

    plan = RetentionPlan(keep=keep, sessions_total=len(ordered),
                         kept_sessions=list(kept),
                         rows_unattributed=unattributed)
    try:
        names = sorted(os.listdir(ledger_dir))
    except OSError:
        raise RetentionError(ERR_JOURNAL_DEGRADED, "ledger dir unreadable")
    for name in names:
        prefix = _session_prefix(name)
        if prefix is None:
            continue                      # outside retention's vocabulary
        full = os.path.join(ledger_dir, name)
        reason = _unsafe_reason(full, ledger_dir)
        if reason:
            plan.skipped.append((name, reason))
            continue
        ids = prefix_ids.get(prefix)
        if not ids:
            plan.skipped.append((name, SKIP_ORPHAN))
            continue
        if len(ids) > 1:
            plan.skipped.append((name, SKIP_AMBIGUOUS))
            continue
        try:
            with open(full, "rb") as f:
                blob = f.read()
        except OSError:
            plan.skipped.append((name, SKIP_UNREADABLE))
            continue
        entry = PlanEntry(path=name, size=len(blob),
                          sha256=hashlib.sha256(blob).hexdigest())
        if next(iter(ids)) in kept:
            # RF5: a kept artifact is not deleted, but it IS bound into
            # the hash — its drift (add/remove/replace) invalidates the
            # confirmation, so the plan the caller confirmed is the
            # ledger state apply acts on.
            plan.kept.append(entry)
        else:
            plan.delete.append(entry)
    plan.plan_hash = _hash_plan(ledger_dir, keep, ordered, unattributed,
                                plan.delete, plan.skipped, plan.kept)
    return plan


def apply_retention(ledger_dir: str, keep: int,
                    confirmed_hash: str) -> RetentionResult:
    """Delete exactly what a prior plan confirmed, or nothing at all.

    The plan is recomputed from CURRENT state; any difference from the
    confirmed hash — file added, removed, or swapped between plan and
    apply — raises ``plan_mismatch`` before a single unlink (TC-19).
    Each surviving deletion re-runs the unsafe-path guard immediately
    before ``os.remove`` (TC-18 defense in depth)."""
    plan = plan_retention(ledger_dir, keep)
    if not confirmed_hash or plan.plan_hash != confirmed_hash:
        raise RetentionError(ERR_PLAN_MISMATCH,
                             f"{len(plan.delete)} candidate(s) at apply time")
    result = RetentionResult(plan=plan, skipped=list(plan.skipped))
    for i, entry in enumerate(plan.delete):
        # root re-validated immediately before EVERY unlink (Finding
        # 2): a root swapped for a link mid-apply stops all remaining
        # deletions — they would land inside the link's target
        root_bad = _root_reason(ledger_dir)
        if root_bad:
            result.skipped.extend((e.path, root_bad)
                                  for e in plan.delete[i:])
            break
        full = os.path.join(ledger_dir, entry.path)
        reason = _unsafe_reason(full, ledger_dir)
        if reason:
            result.skipped.append((entry.path, reason))
            continue
        try:
            os.remove(full)
        except OSError:
            result.skipped.append((entry.path, SKIP_UNLINK_FAILED))
            continue
        result.deleted.append(entry.path)

    # Receipt AFTER the deletions it attests to — a receipt that can be
    # true while the thing it certifies did not happen is worse than no
    # receipt. Reason codes and relative paths only.
    row = {
        "ts": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "schema": RECEIPT_SCHEMA,
        "keep": keep,
        "plan_hash": plan.plan_hash,
        "deleted": sorted(result.deleted),
        "skipped": [{"path": p, "reason": r} for p, r in result.skipped],
    }
    try:
        with open(os.path.join(ledger_dir, RETENTION_LOG), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        result.receipt_written = True
    except OSError:
        result.receipt_written = False
    return result
