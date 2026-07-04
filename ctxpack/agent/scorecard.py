"""Cross-repo scorecard — Layer 1 of the measurement stack.

Aggregates every onboarded repo's checkpoint journal into one report.
Strictly OBSERVATIONAL: these numbers support adoption and token-economics
claims only. Accuracy/quality claims require Layer 2 (resume probes) or
Layer 3 (CompactBench) — conflating the layers is how credibility dies.

No network, no content: only the numeric stats each repo's ledger already
carries. Repos are read in the order given; a repo without checkpoints is
reported as onboarded-but-quiet, not an error.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any, Optional

from .session_reader import LedgerError, session_stats

COHORT_FILE = "cohort.json"


def repo_scorecard(repo_path: str) -> dict[str, Any]:
    """Layer-1 stats for one repo, or a quiet placeholder."""
    name = os.path.basename(os.path.normpath(repo_path))
    ledger = os.path.join(repo_path, ".claude", "ctx")
    onboarded = os.path.isdir(os.path.join(repo_path, ".claude"))
    entry: dict[str, Any] = {"repo": name, "path": repo_path}
    try:
        stats = session_stats(ledger)
    except LedgerError:
        entry["status"] = "onboarded_no_data" if onboarded else "not_onboarded"
        return entry
    entry["status"] = "active"
    entry.update({k: v for k, v in stats.items() if k != "ledger_dir"})
    return entry


def build_scorecard(repo_paths: list[str]) -> dict[str, Any]:
    """One scorecard across the cohort, with an explicit claim boundary."""
    repos = [repo_scorecard(p) for p in repo_paths]
    active = [r for r in repos if r.get("status") == "active"]

    def _sum(getter) -> int:
        return sum(getter(r) or 0 for r in active)

    ledger_reads = _sum(lambda r: r.get("read_path", {}).get("ledger_reads"))
    greps = _sum(lambda r: r.get("read_path", {}).get("transcript_greps"))
    captured_keys = ("decisions", "constraints", "failed_approaches",
                     "errors", "files_changed", "tasks", "requests")
    cohort = {
        "repos_total": len(repos),
        "repos_active": len(active),
        "sessions": _sum(lambda r: r.get("sessions")),
        "checkpoints": _sum(lambda r: r.get("checkpoints")),
        "turns_packed": _sum(lambda r: r.get("turns_packed")),
        "captured": {k: _sum(lambda r, _k=k: r.get("captured", {}).get(_k))
                     for k in captured_keys},
        "read_path": {
            "ledger_reads": ledger_reads,
            "transcript_greps": greps,
            "raw_fallback_rate": (round(greps / (ledger_reads + greps), 3)
                                  if (ledger_reads + greps) else None),
        },
    }
    return {
        "schema": "ctxpack-scorecard/v1",
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "measurement_class": (
            "observational — supports adoption and token-economics claims "
            "only; accuracy/quality claims require resume-probe or "
            "CompactBench results"),
        "cohort": cohort,
        "repos": repos,
    }


def write_scorecard(scorecard: dict[str, Any],
                    out_dir: str = "scorecards") -> tuple[str, str]:
    """Versioned write (never overwrite a prior scorecard) + latest pointer."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = scorecard["generated_at"].replace(":", "").replace("-", "")
    stamp = stamp.replace("+0000", "Z")
    path = os.path.join(out_dir, f"scorecard-{stamp}.json")
    n = 1
    while os.path.exists(path):  # same-second reruns
        n += 1
        path = os.path.join(out_dir, f"scorecard-{stamp}-{n}.json")
    body = json.dumps(scorecard, indent=2)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body + "\n")
    latest = os.path.join(out_dir, "scorecard-latest.json")
    with open(latest, "w", encoding="utf-8", newline="\n") as f:
        f.write(body + "\n")
    return path, latest


def save_cohort(repo_paths: list[str], out_dir: str = "scorecards") -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, COHORT_FILE)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"repos": repo_paths}, f, indent=2)
        f.write("\n")
    return path


def load_cohort(out_dir: str = "scorecards") -> Optional[list[str]]:
    try:
        with open(os.path.join(out_dir, COHORT_FILE), encoding="utf-8") as f:
            repos = json.load(f).get("repos")
        return list(repos) if repos else None
    except (OSError, json.JSONDecodeError):
        return None
