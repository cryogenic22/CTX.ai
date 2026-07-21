"""Capture-coverage reconciliation: make missing memory VISIBLE, then
closable.

Field evidence (setu, 2026-07-21): a whole session was never packed —
crash/kill//clear skipped the hooks — and the gap was invisible until
an agent inspected file mtimes. The hollow guard protects write
integrity; this module protects COVERAGE, the other half:

- ``capture_coverage``  classify every transcript in the project's
  Claude Code transcript dir as packed / stale / unpacked / active
- ``format_gap_warning``  one loud line for SessionStart injection —
  a capture gap self-reports instead of hiding (known-unknowns rule)
- ``run_backfill``  deterministically re-pack unpacked/stale sessions
  from the raw transcripts (idempotent: same transcript → same
  ledger; per-session fail-open so one bad file can't abort a sweep)

Worktree note: a git worktree gets its own ``.claude/ctx`` silo that
dies with the worktree. Coverage flags it (``worktree_local_ledger``);
anchoring worktree sessions to the main repo's ledger is a separate,
undecided design change.

Zero LLM calls; stdlib only. mtime comparisons are telemetry inputs,
never packing inputs — packed artifacts stay byte-deterministic.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

from .checkpoint import (
    HollowTranscriptError,
    _claude_project_dir_name,
    run_checkpoint,
)
from .transcript_adapters import TranscriptFormatError

# A transcript written this recently is treated as a LIVE session and
# left to the hooks (packing a mid-write file is harmless but noisy).
ACTIVE_SLACK_S = 900
# A packed session whose transcript kept growing this much longer than
# its ledger is stale — the tail after the last checkpoint (crash
# window) is worth a re-pack.
STALE_SLACK_S = 1800
_WARN_LIST_CAP = 5


@dataclass
class SessionCoverage:
    session: str          # transcript stem (the Claude Code session id)
    transcript: str       # absolute transcript path
    mtime: float
    status: str           # packed | stale | unpacked | active
    ctx_path: str = ""    # the ledger file the session maps to


@dataclass
class CoverageReport:
    transcript_dir: str = ""
    sessions: "list[SessionCoverage]" = field(default_factory=list)
    worktree_local_ledger: bool = False

    def by_status(self, status: str) -> "list[SessionCoverage]":
        return [s for s in self.sessions if s.status == status]

    def counts(self) -> "dict[str, int]":
        out = {"packed": 0, "stale": 0, "unpacked": 0, "active": 0}
        for s in self.sessions:
            out[s.status] = out.get(s.status, 0) + 1
        return out


def transcript_dir_for(project_dir: str = ".",
                       claude_home: Optional[str] = None) -> str:
    """The Claude Code transcript directory for a project (same
    resolution as find_live_transcript)."""
    home = (claude_home
            or os.environ.get("CLAUDE_CONFIG_DIR")
            or os.path.join(os.path.expanduser("~"), ".claude"))
    return os.path.join(home, "projects",
                        _claude_project_dir_name(project_dir))


def _is_worktree(project_dir: str) -> bool:
    """A git WORKTREE's .git is a file ('gitdir: ...'), not a dir."""
    return os.path.isfile(os.path.join(project_dir, ".git"))


def capture_coverage(project_dir: str = ".",
                     out_dir: str = ".claude/ctx",
                     *,
                     claude_home: Optional[str] = None,
                     exclude_session: str = "",
                     now: Optional[float] = None,
                     active_slack_s: int = ACTIVE_SLACK_S,
                     stale_slack_s: int = STALE_SLACK_S,
                     ) -> CoverageReport:
    """Classify every session transcript against the ledger.

    ``exclude_session`` marks that session id active regardless of
    mtime (SessionStart passes the just-started session: its own
    transcript must never be reported as a gap)."""
    tdir = transcript_dir_for(project_dir, claude_home)
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(project_dir, out_dir)
    report = CoverageReport(
        transcript_dir=tdir,
        worktree_local_ledger=_is_worktree(project_dir),
    )
    try:
        names = sorted(n for n in os.listdir(tdir) if n.endswith(".jsonl"))
    except OSError:
        return report  # no transcript dir: nothing to report on
    ref_now = time.time() if now is None else now
    for name in names:
        stem = name[:-6]
        tpath = os.path.join(tdir, name)
        try:
            mtime = os.path.getmtime(tpath)
        except OSError:
            continue
        ctx_path = os.path.join(out_dir, f"session-{stem[:8]}.ctx")
        if (exclude_session and stem.startswith(exclude_session[:8])) or (
                ref_now - mtime < active_slack_s):
            status = "active"
        elif not os.path.exists(ctx_path):
            status = "unpacked"
        else:
            try:
                ctx_mtime = os.path.getmtime(ctx_path)
            except OSError:
                ctx_mtime = 0.0
            status = ("stale" if mtime - ctx_mtime > stale_slack_s
                      else "packed")
        report.sessions.append(SessionCoverage(
            session=stem, transcript=tpath, mtime=mtime,
            status=status, ctx_path=ctx_path))
    report.sessions.sort(key=lambda s: (s.mtime, s.session))
    return report


def format_gap_warning(report: CoverageReport) -> str:
    """One loud line when sessions were never packed; '' when covered.
    Precision-first: only UNPACKED sessions warn (stale is the normal
    debounce tail; the coverage report still carries it)."""
    gaps = report.by_status("unpacked")
    if not gaps:
        return ""
    shown = ", ".join(
        f"{s.session[:8]} ({time.strftime('%Y-%m-%d', time.localtime(s.mtime))})"
        for s in gaps[:_WARN_LIST_CAP])
    more = f" and {len(gaps) - _WARN_LIST_CAP} more" if (
        len(gaps) > _WARN_LIST_CAP) else ""
    return (f"[ctx capture gap] {len(gaps)} session transcript(s) were "
            f"never packed into this ledger: {shown}{more}. The raw "
            f"transcripts are intact — run `ctxpack backfill` to "
            f"reconcile before trusting cross-session recall.")


@dataclass
class BackfillRow:
    session: str
    status_before: str    # unpacked | stale | active
    outcome: str          # packed | planned | skipped_hollow | skipped_format | failed
    detail: str = ""


def run_backfill(project_dir: str = ".",
                 out_dir: str = ".claude/ctx",
                 *,
                 as_of: Optional[str] = None,
                 include_active: bool = False,
                 dry_run: bool = False,
                 claude_home: Optional[str] = None,
                 ) -> "list[BackfillRow]":
    """Re-pack every unpacked/stale session from its raw transcript.

    Idempotent (full deterministic re-pack, same rule as the hooks)
    and per-session fail-open: a hollow or corrupt transcript becomes
    a skipped/failed row, never an aborted sweep — but each skip is
    REPORTED, not silent (no-silent-caps rule).

    Every backfill packs in ARCHIVE mode: the session's artifacts and
    journal row land, but latest-gist.md and the default-session
    resolution stay pointed at the live session — a Jul-15 backfill
    must never become "latest" on Jul-21."""
    report = capture_coverage(project_dir, out_dir,
                              claude_home=claude_home)
    todo = report.by_status("unpacked") + report.by_status("stale")
    if include_active:
        todo += report.by_status("active")
    rows: "list[BackfillRow]" = []
    for s in sorted(todo, key=lambda s: (s.mtime, s.session)):
        if dry_run:
            rows.append(BackfillRow(s.session, s.status, "planned",
                                    s.transcript))
            continue
        try:
            result = run_checkpoint(s.transcript, out_dir, as_of=as_of,
                                    archive=True)
            rows.append(BackfillRow(
                s.session, s.status, "packed",
                f"{result.entities} entities, {result.turns} turns"))
        except HollowTranscriptError as e:
            rows.append(BackfillRow(s.session, s.status,
                                    "skipped_hollow", str(e)[:160]))
        except TranscriptFormatError as e:
            rows.append(BackfillRow(s.session, s.status,
                                    "skipped_format", str(e)[:160]))
        except Exception as e:  # noqa: BLE001 — one bad file must not kill the sweep
            rows.append(BackfillRow(
                s.session, s.status, "failed",
                f"{type(e).__name__}: {e}"[:160]))
    return rows
