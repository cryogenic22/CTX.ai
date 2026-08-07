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
import hashlib
import json
import os
from typing import Any, Optional

from .session_reader import LedgerError, session_stats

COHORT_FILE = "cohort.json"
SCHEMA = "ctxpack-scorecard/v2"

# statuses folded into each denominator; every status appears in
# exactly one bucket so measured + unmeasured + excluded == total
_MEASURED = ("active",)
_UNMEASURED = ("onboarded_no_data", "external_unmeasured")
_EXCLUDED = ("not_onboarded", "path_missing")


def _sha256_file(path: str) -> "str | None":
    """sha256 of a file's bytes, or ``None`` when it is absent."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def repo_input_fingerprint(repo_path: str) -> dict[str, Any]:
    """Fingerprint of the ledger files this scorecard actually reads.

    Covers ``checkpoints.jsonl`` and ``injections.jsonl``. The capture
    block walks the machine's external transcript directory and is
    deliberately NOT covered — a passing ``--check`` certifies the
    ledger-derived numbers, not the capture numbers. An absent file
    contributes a deterministic ``absent`` marker so missing-vs-changed
    is distinguishable.
    """
    ledger = os.path.join(repo_path, ".claude", "ctx")
    cp = _sha256_file(os.path.join(ledger, "checkpoints.jsonl"))
    inj = _sha256_file(os.path.join(ledger, "injections.jsonl"))
    combined = hashlib.sha256(
        (f"checkpoints:{cp or 'absent'}\n"
         f"injections:{inj or 'absent'}").encode("utf-8")).hexdigest()
    return {"checkpoints_jsonl": cp, "injections_jsonl": inj,
            "fingerprint": combined}


def cohort_config_sha256(out_dir: str = "scorecards") -> "str | None":
    return _sha256_file(os.path.join(out_dir, COHORT_FILE))


def repo_scorecard(repo_path: str) -> dict[str, Any]:
    """Layer-1 stats for one repo, or a quiet placeholder."""
    name = os.path.basename(os.path.normpath(repo_path))
    ledger = os.path.join(repo_path, ".claude", "ctx")
    onboarded = os.path.isdir(os.path.join(repo_path, ".claude"))
    entry: dict[str, Any] = {"repo": name, "path": repo_path,
                             "inputs": repo_input_fingerprint(repo_path)}
    if not os.path.isdir(repo_path):
        entry["status"] = "path_missing"
        return entry
    try:
        stats = session_stats(ledger)
    except LedgerError:
        entry["status"] = "onboarded_no_data" if onboarded else "not_onboarded"
        return entry
    entry["status"] = "active"
    entry.update({k: v for k, v in stats.items() if k != "ledger_dir"})
    # Capture coverage (setu field gap): how much of what the agent
    # actually did ever reached this ledger. Fail-open — a machine
    # without the transcript dir (fresh clone) reports nothing rather
    # than an error; observational like everything else here.
    try:
        from .backfill import capture_coverage
        cov = capture_coverage(repo_path, ledger)
        counts = cov.counts()
        denom = counts["packed"] + counts["stale"] + counts["unpacked"]
        entry["capture"] = {
            **counts,
            "coverage": (round(counts["packed"] / denom, 3)
                         if denom else None),
            "unpacked_sessions": [s.session[:8]
                                  for s in cov.by_status("unpacked")],
            "worktree_local_ledger": cov.worktree_local_ledger,
        }
    except Exception:  # noqa: BLE001 — telemetry must not fail the scorecard
        pass
    return entry


def build_scorecard(repo_paths: list[str],
                    external: "list[dict] | None" = None,
                    cohort_config_sha: "str | None" = None) -> dict[str, Any]:
    """One scorecard across the cohort, with an explicit claim boundary.

    ``external`` — cohort members with no local ledger (e.g. a
    field-report deployment). They appear as ``external_unmeasured``
    rows and count in the unmeasured denominator: the population is
    honest about who is in the cohort without manufacturing data for
    repos we cannot read. ``cohort_config_sha`` is stamped so
    ``--check`` can detect population drift; ``None`` means no cohort
    file existed at generation (direct API use).
    """
    repos = [repo_scorecard(p) for p in repo_paths]
    for e in external or []:
        row: dict[str, Any] = {"repo": str(e.get("name") or "unnamed"),
                               "status": "external_unmeasured"}
        if e.get("note"):
            row["note"] = str(e["note"])
        repos.append(row)
    active = [r for r in repos if r.get("status") == "active"]

    def _count(statuses) -> int:
        return sum(1 for r in repos if r.get("status") in statuses)

    def _sum(getter) -> int:
        return sum(getter(r) or 0 for r in active)

    ledger_reads = _sum(lambda r: r.get("read_path", {}).get("ledger_reads"))
    greps = _sum(lambda r: r.get("read_path", {}).get("transcript_greps"))
    # Session-level adoption of the PULL path. Two field reports (setu
    # 07-21, OntoWiz 07-25) report never querying the ledger; until these
    # counters exist the claim is neither confirmable nor refutable from
    # our own telemetry, because a zero-query session and an untracked
    # session look identical in the rate. The emission split says whether
    # a gist was written to the hook's stdout for that session — NOT that
    # it reached the agent, was read, or was used.
    rp_sessions = {
        k: _sum(lambda r, _k=k: r.get("read_path", {}).get(_k))
        for k in ("sessions_explicit_recall", "sessions_zero_recall",
                  "sessions_no_telemetry", "sessions_transcript_fallback",
                  "sessions_zero_recall_with_emission",
                  "sessions_zero_recall_emission_empty",
                  "sessions_zero_recall_emission_failed",
                  "sessions_zero_recall_emission_unmeasured")
    }
    rp_measured = (rp_sessions["sessions_explicit_recall"]
                   + rp_sessions["sessions_zero_recall"])
    captured_keys = ("decisions", "constraints", "failed_approaches",
                     "errors", "files_changed", "tasks", "requests",
                     "incidents")
    incident_types: dict[str, int] = {}
    for r in active:
        for itype, count in (r.get("incident_types") or {}).items():
            if isinstance(count, int):
                incident_types[itype] = incident_types.get(itype, 0) + count
    cohort = {
        "repos_total": len(repos),
        "repos_active": len(active),
        # separate denominators — measured, unmeasured and excluded must
        # never be pooled: an unmeasured repo is not a zero
        "repos_measured": _count(_MEASURED),
        "repos_unmeasured": _count(_UNMEASURED),
        "repos_excluded": _count(_EXCLUDED),
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
            **rp_sessions,
            "explicit_recall_rate": (
                round(rp_sessions["sessions_explicit_recall"] / rp_measured, 3)
                if rp_measured else None),
        },
        # ctx-incident: telemetry — agent-reported; user-corrected rows
        # are the only externally-anchored type, weigh them accordingly
        "incident_types": incident_types,
        # capture gaps across the cohort (sessions the hooks never
        # packed — each one is recall silently missing somewhere)
        "capture_unpacked": _sum(
            lambda r: r.get("capture", {}).get("unpacked")),
        # push-path emission: what the SessionStart hook wrote to stdout.
        # Repos whose ledgers predate the injection log contribute
        # nothing rather than zeros.
        "startup_injection": {
            k: _sum(lambda r, _k=k: r.get("startup_injection", {}).get(_k))
            for k in ("attempted", "injected", "empty", "failed",
                      "gap_warnings")
        },
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "measurement_class": (
            "observational — supports adoption and token-economics claims "
            "only; accuracy/quality claims require resume-probe or "
            "CompactBench results"),
        "cohort_config_sha256": cohort_config_sha,
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
    """Save the repo list, preserving any ``external`` cohort entries —
    passing ``--repos`` updates the measurable population, it does not
    silently drop the unmeasurable members from the cohort record."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, COHORT_FILE)
    cfg = load_cohort_config(out_dir) or {}
    body: dict[str, Any] = {"repos": repo_paths}
    if cfg.get("external"):
        body["external"] = cfg["external"]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(body, f, indent=2)
        f.write("\n")
    return path


def load_cohort_config(out_dir: str = "scorecards") -> "dict | None":
    """The full cohort config ({"repos": [...], "external": [...]}),
    or ``None`` when absent/unreadable."""
    try:
        with open(os.path.join(out_dir, COHORT_FILE), encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def load_cohort(out_dir: str = "scorecards") -> Optional[list[str]]:
    cfg = load_cohort_config(out_dir)
    repos = (cfg or {}).get("repos")
    return list(repos) if repos else None


def verify_latest(out_dir: str = "scorecards") -> tuple[bool, list[str]]:
    """Recompute the inputs behind ``scorecard-latest.json``; report drift.

    Verifies the cohort-config sha and every repo's ledger-file
    fingerprints, plus that no cohort member is missing from the
    artifact. The capture block walks external transcript directories
    and is NOT covered — a passing check certifies the ledger-derived
    numbers only. Returns ``(ok, findings)``; a stale "latest" is a
    nonzero exit for the CLI, so dashboards cannot quietly present an
    old population as current.
    """
    findings: list[str] = []
    latest_path = os.path.join(out_dir, "scorecard-latest.json")
    try:
        with open(latest_path, encoding="utf-8") as f:
            latest = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False, [f"no readable scorecard at {latest_path}"]
    if latest.get("schema") != SCHEMA:
        return False, [
            f"latest has schema {latest.get('schema')!r} — predates "
            f"self-verification ({SCHEMA}); regenerate"]
    if latest.get("cohort_config_sha256") != cohort_config_sha256(out_dir):
        findings.append("cohort config changed since generation "
                        f"({out_dir}/{COHORT_FILE})")
    rows = latest.get("repos", [])
    for r in rows:
        path = r.get("path")
        if not path:                      # external rows carry no inputs
            continue
        stored = (r.get("inputs") or {}).get("fingerprint")
        if stored != repo_input_fingerprint(path)["fingerprint"]:
            findings.append(f"{r.get('repo')}: ledger inputs changed "
                            "since generation")
    cfg = load_cohort_config(out_dir) or {}
    known_paths = {r.get("path") for r in rows}
    for p in cfg.get("repos") or []:
        if p not in known_paths:
            findings.append(f"cohort repo missing from latest: {p}")
    known_names = {r.get("repo") for r in rows}
    for e in cfg.get("external") or []:
        if str(e.get("name")) not in known_names:
            findings.append("external cohort entry missing from latest: "
                            f"{e.get('name')}")
    return not findings, findings
