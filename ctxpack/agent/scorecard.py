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


def _file_digest(path: str) -> "tuple[str, str | None]":
    """``(state, sha256)`` — state is present / absent / unreadable.

    Absent and unreadable must not be conflated (review 2026-08-07):
    "the file is gone" and "the file exists but could not be read" are
    different claims, and treating them identically lets a permission
    failure impersonate a clean absence.
    """
    try:
        with open(path, "rb") as f:
            return "present", hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return "absent", None
    except OSError:
        return "unreadable", None


def _sha256_file(path: str) -> "str | None":
    """sha256 of a file's bytes, or ``None`` when it cannot be read."""
    return _file_digest(path)[1]


def repo_input_fingerprint(repo_path: str) -> dict[str, Any]:
    """Fingerprint of the ledger files this scorecard actually reads.

    Covers ``checkpoints.jsonl`` and ``injections.jsonl``, each with an
    explicit present/absent/unreadable state folded into the combined
    fingerprint. The capture block walks the machine's external
    transcript directory and is deliberately NOT covered — a passing
    ``--check`` certifies input freshness for the ledger-derived
    numbers, not the capture numbers and not the report arithmetic.
    """
    ledger = os.path.join(repo_path, ".claude", "ctx")
    cp_state, cp = _file_digest(os.path.join(ledger, "checkpoints.jsonl"))
    inj_state, inj = _file_digest(os.path.join(ledger, "injections.jsonl"))
    combined = hashlib.sha256(
        (f"checkpoints:{cp_state}:{cp or '-'}\n"
         f"injections:{inj_state}:{inj or '-'}").encode("utf-8")).hexdigest()
    return {"checkpoints_jsonl": cp, "checkpoints_state": cp_state,
            "injections_jsonl": inj, "injections_state": inj_state,
            "fingerprint": combined}


def cohort_config_sha256(out_dir: str = "scorecards") -> "str | None":
    return _sha256_file(os.path.join(out_dir, COHORT_FILE))


def validate_cohort_config(cfg) -> "list[str]":
    """Strict cohort-schema validation — a malformed population config
    is a controlled failure, never a silently-shaped one.

    Enforces: dict shape; ``repos`` a list of non-empty strings with
    canonical-path uniqueness (Windows case-insensitive, symlink/alias
    resolved — a repo listed twice under two spellings would be counted
    twice); ``external`` a list of dicts with unique non-empty names.
    Returns error strings; empty list = valid.
    """
    errors: list[str] = []
    if not isinstance(cfg, dict):
        return [f"cohort config must be a JSON object, got "
                f"{type(cfg).__name__}"]
    repos = cfg.get("repos")
    if repos is None:
        errors.append("cohort config has no 'repos' list")
        repos = []
    elif not isinstance(repos, list):
        errors.append(f"'repos' must be a list, got "
                      f"{type(repos).__name__}")
        repos = []
    seen_canonical: dict[str, str] = {}
    for entry in repos:
        if not isinstance(entry, str) or not entry.strip():
            errors.append(f"repo entries must be non-empty strings: "
                          f"{entry!r}")
            continue
        canonical = os.path.normcase(
            os.path.realpath(os.path.normpath(entry)))
        if canonical in seen_canonical:
            errors.append(
                f"duplicate repo (canonical-path collision): {entry!r} "
                f"aliases {seen_canonical[canonical]!r}")
        else:
            seen_canonical[canonical] = entry
    external = cfg.get("external", [])
    if not isinstance(external, list):
        errors.append(f"'external' must be a list, got "
                      f"{type(external).__name__}")
        external = []
    seen_names: set[str] = set()
    for e in external:
        if not isinstance(e, dict) or not str(e.get("name") or "").strip():
            errors.append(f"external entries must be objects with a "
                          f"non-empty 'name': {e!r}")
            continue
        name = str(e["name"]).strip()
        if name in seen_names:
            errors.append(f"duplicate external deployment id: {name!r}")
        seen_names.add(name)
    return errors


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
                      "malformed_rows", "gap_warnings")
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
    """INPUT-FRESHNESS check for ``scorecard-latest.json``; report drift.

    Scope, stated precisely (review 2026-08-07): this verifies that the
    cohort config and each repo's fingerprinted ledger files are
    byte-identical to what the artifact was generated from, and that no
    cohort member is missing from the artifact. It does NOT recompute
    the metrics — a hand-edited number in an artifact whose inputs are
    unchanged would pass — and the capture block is outside the
    fingerprints entirely. The honest claim is "inputs unchanged since
    generation", never "numbers verified".

    Malformed artifacts and malformed cohort configs are controlled
    nonzero failures with named findings, never a traceback. Returns
    ``(ok, findings)``.
    """
    findings: list[str] = []
    latest_path = os.path.join(out_dir, "scorecard-latest.json")
    try:
        with open(latest_path, encoding="utf-8") as f:
            latest = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False, [f"no readable scorecard at {latest_path}"]
    if not isinstance(latest, dict):
        return False, [f"scorecard at {latest_path} is not a JSON object"]
    if latest.get("schema") != SCHEMA:
        return False, [
            f"latest has schema {latest.get('schema')!r} — predates "
            f"self-verification ({SCHEMA}); regenerate"]
    rows = latest.get("repos")
    if not isinstance(rows, list) or not all(
            isinstance(r, dict) for r in rows):
        return False, ["latest 'repos' is not a list of objects — "
                       "malformed artifact"]
    cfg = load_cohort_config(out_dir)
    cfg_errors = validate_cohort_config(cfg) if cfg is not None else []
    for err in cfg_errors:
        findings.append(f"cohort config invalid: {err}")
    if latest.get("cohort_config_sha256") != cohort_config_sha256(out_dir):
        findings.append("cohort config changed since generation "
                        f"({out_dir}/{COHORT_FILE})")
    for r in rows:
        path = r.get("path")
        if not path or not isinstance(path, str):
            continue                      # external rows carry no inputs
        stored = (r.get("inputs") or {}).get("fingerprint") \
            if isinstance(r.get("inputs"), dict) else None
        if stored != repo_input_fingerprint(path)["fingerprint"]:
            findings.append(f"{r.get('repo')}: ledger inputs changed "
                            "since generation")
    cfg = cfg or {}
    known_paths = {r.get("path") for r in rows}
    for p in cfg.get("repos") if isinstance(cfg.get("repos"), list) else []:
        if p not in known_paths:
            findings.append(f"cohort repo missing from latest: {p}")
    known_names = {r.get("repo") for r in rows}
    ext = cfg.get("external") if isinstance(cfg.get("external"), list) else []
    for e in ext:
        name = e.get("name") if isinstance(e, dict) else None
        if str(name) not in known_names:
            findings.append("external cohort entry missing from latest: "
                            f"{name}")
    return not findings, findings
