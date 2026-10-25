"""Offline deterministic replay benchmark for CTX Legions L1.

Runs over a fixture chain of session transcripts and optional commit logs,
then reports capture recall, supersession correctness, and briefing coverage
at fixed character budgets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any

from ..agent.checkpoint import run_checkpoint
from ..agent.session_reader import _kind_of, _primary_value, _sections, load_session
from ..core.serializer import serialize_section

DEFAULT_BUDGETS = (2000, 4000, 8000, 14000)
_KIND_ORDER = {
    "CONSTRAINT": 0,
    "DECISION": 1,
    "FAILED-APPROACH": 2,
    "LITERAL": 3,
    "USER-REQUEST": 4,
    "TASK": 5,
    "ERROR": 6,
    "FILE": 7,
}


@dataclass(frozen=True)
class Label:
    id: str
    session: str
    kind: str
    source: str
    text: str


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _session_dirs(fixture_dir: str) -> list[str]:
    root = os.path.join(fixture_dir, "sessions")
    if not os.path.isdir(root):
        raise ValueError(f"missing fixture sessions dir: {root}")
    out = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "transcript.jsonl")):
            out.append(path)
    if not out:
        raise ValueError(f"no transcript sessions found under {root}")
    return out


def _load_labels(fixture_dir: str) -> tuple[list[Label], list[dict[str, str]], str]:
    raw = _read_json(os.path.join(fixture_dir, "labels.json"))
    as_of = str(raw.get("as_of", "2026-10-25"))
    labels = [
        Label(
            id=str(row["id"]),
            session=str(row["session"])[:8],
            kind=str(row["kind"]).upper(),
            source=str(row["source"]).lower(),
            text=str(row["text"]),
        )
        for row in raw.get("labels", [])
    ]
    supers = [{"old": str(r["old"]), "new": str(r["new"]), "session": str(r.get("session", ""))[:8]}
              for r in raw.get("supersessions", [])]
    return labels, supers, as_of


def _facts_for_doc(doc) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for section in _sections(doc):
        kind = _kind_of(section).upper()
        text = _primary_value(section)
        if not text:
            continue
        turn = -1
        for child in section.children:
            if getattr(child, "key", "").upper() == "TURN":
                try:
                    turn = int(child.value)
                except ValueError:
                    turn = -1
        facts.append({"kind": kind, "text": text, "turn": turn, "section": section})
    facts.sort(key=lambda f: (f["turn"], f["kind"], f["text"]))
    return facts


def _ledger_bytes_by_kind(facts: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for fact in facts:
        payload = "\n".join(serialize_section(fact["section"]))
        out[fact["kind"]] = out.get(fact["kind"], 0) + len(payload.encode("utf-8"))
    return out


def _briefing_coverage(facts: list[dict[str, Any]], budget: int) -> dict[str, Any]:
    ordered = sorted(
        facts,
        key=lambda f: (_KIND_ORDER.get(f["kind"], 999), f["turn"], f["kind"], f["text"]),
    )
    total_by_kind: dict[str, int] = {}
    for fact in ordered:
        total_by_kind[fact["kind"]] = total_by_kind.get(fact["kind"], 0) + 1
    used = 0
    kept_by_kind: dict[str, int] = {}
    for fact in ordered:
        line = f"{fact['kind']}: {fact['text']}\n"
        cost = len(line)
        if used + cost > budget:
            continue
        used += cost
        kept_by_kind[fact["kind"]] = kept_by_kind.get(fact["kind"], 0) + 1
    dropped_by_kind = {
        kind: total_by_kind[kind] - kept_by_kind.get(kind, 0)
        for kind in sorted(total_by_kind)
    }
    coverage_by_kind = {
        kind: round(kept_by_kind.get(kind, 0) / total_by_kind[kind], 4)
        for kind in sorted(total_by_kind)
    }
    return {
        "budget_chars": budget,
        "used_chars": used,
        "coverage_by_kind": coverage_by_kind,
        "dropped_by_kind": dropped_by_kind,
    }


def _run_once(fixture_dir: str, budgets: tuple[int, ...], as_of: str) -> dict[str, Any]:
    labels, supers, _ = _load_labels(fixture_dir)
    labels_by_id = {label.id: label for label in labels}
    sessions: list[dict[str, Any]] = []
    recall_found = 0
    recall_total = len(labels)
    misses: list[str] = []
    miss_by_source = {"transcript": 0, "commit": 0}
    supersession_total = 0
    supersession_passed = 0
    with tempfile.TemporaryDirectory() as td:
        session_facts: dict[str, list[dict[str, Any]]] = {}
        session_dirs = _session_dirs(fixture_dir)
        for sdir in session_dirs:
            transcript = os.path.join(sdir, "transcript.jsonl")
            result = run_checkpoint(transcript, td, as_of=as_of)
            sid = result.session_id[:8]
            doc, _ = load_session(td, sid)
            facts = _facts_for_doc(doc)
            session_facts[sid] = facts
            label_rows = [x for x in labels if x.session == sid]
            fact_set = {(f["kind"], f["text"]) for f in facts}
            for label in label_rows:
                if (label.kind, label.text) in fact_set:
                    recall_found += 1
                else:
                    misses.append(label.id)
                    miss_by_source[label.source] = miss_by_source.get(label.source, 0) + 1
            sessions.append(
                {
                    "session": sid,
                    "capture": {
                        "found": sum(1 for l in label_rows if (l.kind, l.text) in fact_set),
                        "total": len(label_rows),
                    },
                    "ledger_bytes_by_kind": _ledger_bytes_by_kind(facts),
                    "briefing": {
                        str(b): _briefing_coverage(facts, b) for b in budgets
                    },
                }
            )
        for edge in supers:
            old = labels_by_id[edge["old"]]
            new = labels_by_id[edge["new"]]
            sid = edge["session"] or new.session
            live = {(f["kind"], f["text"]) for f in session_facts.get(sid, [])}
            old_absent = (old.kind, old.text) not in live
            new_present = (new.kind, new.text) in live
            supersession_total += 1
            if old_absent and new_present:
                supersession_passed += 1
        totals_coverage: dict[str, dict[str, int]] = {str(b): {} for b in budgets}
        totals_dropped: dict[str, dict[str, int]] = {str(b): {} for b in budgets}
        totals_ledger_bytes: dict[str, int] = {}
        for row in sessions:
            for kind, n in row["ledger_bytes_by_kind"].items():
                totals_ledger_bytes[kind] = totals_ledger_bytes.get(kind, 0) + n
            for b in budgets:
                entry = row["briefing"][str(b)]
                for kind, n in entry["coverage_by_kind"].items():
                    # session-level coverage ratios are averaged at reporting time
                    totals_coverage[str(b)][kind] = totals_coverage[str(b)].get(kind, 0) + int(n * 10000)
                for kind, n in entry["dropped_by_kind"].items():
                    totals_dropped[str(b)][kind] = totals_dropped[str(b)].get(kind, 0) + n
        totals_cov_ratio = {
            b: {k: round(v / max(1, len(sessions)) / 10000, 4)
                for k, v in sorted(kind_map.items())}
            for b, kind_map in totals_coverage.items()
        }
        return {
            "schema_version": "replay/v1",
            "fixture": os.path.basename(os.path.abspath(fixture_dir)),
            "sessions": sessions,
            "totals": {
                "capture": {
                    "found": recall_found,
                    "total": recall_total,
                    "recall": round(recall_found / recall_total, 4) if recall_total else 1.0,
                    "missing_label_ids": sorted(misses),
                    "misses_by_source": miss_by_source,
                },
                "supersession": {
                    "passed": supersession_passed,
                    "total": supersession_total,
                    "correctness": round(supersession_passed / supersession_total, 4)
                    if supersession_total
                    else 1.0,
                },
                "briefing": {
                    b: {
                        "coverage_by_kind": totals_cov_ratio[b],
                        "dropped_by_kind": totals_dropped[b],
                    }
                    for b in sorted(totals_dropped, key=int)
                },
                "ledger_bytes_by_kind": dict(sorted(totals_ledger_bytes.items())),
            },
        }


def run_replay(
    fixture_dir: str,
    *,
    budgets: tuple[int, ...] = DEFAULT_BUDGETS,
    output_path: str = "",
) -> dict[str, Any]:
    """Run replay benchmark, write one deterministic JSON report, and return it."""
    _, _, as_of = _load_labels(fixture_dir)
    first = _run_once(fixture_dir, budgets, as_of)
    second = _run_once(fixture_dir, budgets, as_of)
    first_json = _canonical_json(first)
    second_json = _canonical_json(second)
    report = dict(first)
    report["determinism"] = {
        "identical": first_json == second_json,
        "first_sha256": _sha256(first_json),
        "second_sha256": _sha256(second_json),
    }
    if output_path:
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(report, indent=2, sort_keys=True))
            f.write("\n")
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python -m ctxpack.benchmarks.replay``."""
    parser = argparse.ArgumentParser(description="Offline deterministic CTX replay benchmark")
    parser.add_argument("--fixture", required=True, help="Fixture directory")
    parser.add_argument("--output", default="", help="Optional output report path")
    parser.add_argument(
        "--budgets",
        default=",".join(str(x) for x in DEFAULT_BUDGETS),
        help="Comma-separated character budgets (default: 2000,4000,8000,14000)",
    )
    args = parser.parse_args(argv)
    budgets = tuple(int(x) for x in args.budgets.split(",") if x.strip())
    report = run_replay(args.fixture, budgets=budgets, output_path=args.output)
    if not args.output:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    # Rebound below by the L1 finalized implementation.
    pass


# ---- L1 finalized implementation (binding spec-approved amendments) ----

import subprocess
import sys

from ..agent.checkpoint import read_startup_context
from ..agent.session_reader import session_decisions


@dataclass(frozen=True)
class _ReplayLabel:
    id: str
    session: str
    kind: str
    source: str
    text: str


def _bpe_estimate(text: str) -> int:
    try:
        from .metrics.cost import count_bpe_tokens

        return int(count_bpe_tokens(text, model="claude"))
    except Exception:
        return max(1, len(text) // 4)


def _load_replay_fixture(fixture_dir: str) -> tuple[dict[str, Any], list[_ReplayLabel]]:
    payload = _read_json(os.path.join(fixture_dir, "labels.json"))
    labels = [
        _ReplayLabel(
            id=str(row["id"]),
            session=str(row["session"])[:8],
            kind=str(row["kind"]).upper(),
            source=str(row["source"]).lower(),
            text=str(row["text"]),
        )
        for row in payload.get("labels", [])
    ]
    return payload, labels


def _briefing_adapter(ledger_dir: str, budget_chars: int | None = None) -> dict[str, Any]:
    """Current CTX adapter: fixed startup context only (no budget control yet)."""
    text = read_startup_context(ledger_dir).strip()
    status = "ok" if budget_chars is None else "unsupported"
    return {
        "status": status,
        "budget_chars": budget_chars,
        "text": text,
        "chars": len(text),
        "estimated_tokens": _bpe_estimate(text),
    }


def _drops_disclosed(briefing_text: str) -> bool:
    low = briefing_text.lower()
    if "dropped" not in low:
        return False
    return any(k in low for k in (
        "decision",
        "constraint",
        "failed approach",
        "literal",
        "task",
        "error",
        "file",
    ))


def _live_blob(briefing_text: str, decisions_payload: dict[str, Any]) -> str:
    lines = [briefing_text]
    for key in ("decisions", "constraints", "failed_approaches"):
        for row in decisions_payload.get(key, []):
            lines.append(str(row.get("text", "")))
    return "\n".join(lines)


def _one_process_report(
    fixture_dir: str,
    budgets: tuple[int, ...],
) -> dict[str, Any]:
    fixture, labels = _load_replay_fixture(fixture_dir)
    label_by_id = {l.id: l for l in labels}
    as_of = str(fixture.get("as_of", "2026-10-25"))
    supers = fixture.get("supersessions", [])
    contamination_texts = {str(x) for x in fixture.get("contamination_texts", [])}

    sessions_out: list[dict[str, Any]] = []
    capture_found = 0
    capture_total = len(labels)
    missing_ids: list[str] = []
    source_totals: dict[str, int] = {"transcript": 0, "commit": 0}
    source_found: dict[str, int] = {"transcript": 0, "commit": 0}
    contamination_ids: list[str] = []
    contamination_refs: list[str] = []
    supersession_total = 0
    supersession_passed = 0
    stale_present = 0

    session_dirs = _session_dirs(fixture_dir)
    commit_text_by_session: dict[str, set[str]] = {}
    for sdir in session_dirs:
        sid = os.path.basename(sdir).split("-", 1)[-1][:8]
        cpath = os.path.join(sdir, "commits.jsonl")
        if os.path.isfile(cpath):
            commit_text_by_session[sid] = {
                str(row.get("text", "")) for row in _read_jsonl(cpath)
                if str(row.get("text", "")).strip()
            }
    for l in labels:
        if l.source == "commit" and l.text not in commit_text_by_session.get(l.session, set()):
            raise ValueError(f"commit label not present in commits.jsonl: {l.id}")

    with tempfile.TemporaryDirectory() as td:
        session_live: dict[str, str] = {}
        for sdir in session_dirs:
            transcript = os.path.join(sdir, "transcript.jsonl")
            res = run_checkpoint(transcript, td, as_of=as_of)
            sid = res.session_id[:8]
            doc, _ = load_session(td, sid)
            facts = _facts_for_doc(doc)
            facts_set = {(f["kind"], f["text"]) for f in facts}

            labels_here = [l for l in labels if l.session == sid]
            for l in labels_here:
                source_totals[l.source] = source_totals.get(l.source, 0) + 1
                if (l.kind, l.text) in facts_set:
                    capture_found += 1
                    source_found[l.source] = source_found.get(l.source, 0) + 1
                else:
                    missing_ids.append(l.id)

            briefing = _briefing_adapter(td)
            briefing_text = briefing["text"]
            decisions_payload = session_decisions(doc, sid)
            live_blob = _live_blob(briefing_text, decisions_payload)
            session_live[sid] = live_blob

            by_kind_total: dict[str, int] = {}
            by_kind_seen: dict[str, int] = {}
            for l in labels_here:
                by_kind_total[l.kind] = by_kind_total.get(l.kind, 0) + 1
                if l.text in briefing_text:
                    by_kind_seen[l.kind] = by_kind_seen.get(l.kind, 0) + 1
            coverage_by_kind = {
                k: round(by_kind_seen.get(k, 0) / by_kind_total[k], 4)
                for k in sorted(by_kind_total)
            }
            dropped_by_kind = {
                k: by_kind_total[k] - by_kind_seen.get(k, 0)
                for k in sorted(by_kind_total)
            }

            for f in facts:
                if f["text"] in contamination_texts:
                    fid = ""
                    for child in f["section"].children:
                        if getattr(child, "key", "").upper() == "FACT-ID":
                            fid = str(child.value)
                            break
                    contamination_ids.append(fid or f["section"].name)
                    contamination_refs.append(f"{sid}:{f['kind']}")

            sessions_out.append(
                {
                    "session": sid,
                    "capture": {
                        "found": sum(1 for l in labels_here if (l.kind, l.text) in facts_set),
                        "total": len(labels_here),
                    },
                    "briefing": {
                        "chars": briefing["chars"],
                        "estimated_tokens": briefing["estimated_tokens"],
                        "coverage_by_kind": coverage_by_kind,
                        "dropped_by_kind": dropped_by_kind,
                        "drops_disclosed": _drops_disclosed(briefing_text),
                        "budgets": {
                            str(b): {"status": "unsupported"} for b in budgets
                        },
                    },
                    "ledger_bytes_by_kind": _ledger_bytes_by_kind(facts),
                }
            )

        for edge in supers:
            old = label_by_id[str(edge["old"])]
            new = label_by_id[str(edge["new"])]
            sid = str(edge.get("session", "") or new.session)[:8]
            live = session_live.get(sid, "")
            old_absent = old.text not in live
            new_present = new.text in live
            supersession_total += 1
            if old_absent and new_present:
                supersession_passed += 1
            if not old_absent:
                stale_present += 1

    split = {}
    for src in sorted(source_totals):
        total = source_totals[src]
        found = source_found.get(src, 0)
        split[src] = {
            "found": found,
            "total": total,
            "recall": round(found / total, 4) if total else 1.0,
        }

    total_cov_sum: dict[str, dict[str, float]] = {}
    total_drop_sum: dict[str, dict[str, int]] = {}
    total_drop_disclosed = 0
    total_ledger_bytes: dict[str, int] = {}
    for row in sessions_out:
        total_drop_disclosed += 1 if row["briefing"]["drops_disclosed"] else 0
        for k, v in row["ledger_bytes_by_kind"].items():
            total_ledger_bytes[k] = total_ledger_bytes.get(k, 0) + v
        for k, v in row["briefing"]["coverage_by_kind"].items():
            total_cov_sum.setdefault("fixed", {})
            total_cov_sum["fixed"][k] = total_cov_sum["fixed"].get(k, 0.0) + v
        for k, v in row["briefing"]["dropped_by_kind"].items():
            total_drop_sum.setdefault("fixed", {})
            total_drop_sum["fixed"][k] = total_drop_sum["fixed"].get(k, 0) + v

    avg_cov = {
        k: round(v / max(1, len(sessions_out)), 4)
        for k, v in sorted(total_cov_sum.get("fixed", {}).items())
    }
    sum_drop = dict(sorted(total_drop_sum.get("fixed", {}).items()))

    return {
        "schema_version": "replay/v1",
        "fixture": os.path.basename(os.path.abspath(fixture_dir)),
        "as_of": as_of,
        "sessions": sessions_out,
        "totals": {
            "capture": {
                "found": capture_found,
                "total": capture_total,
                "recall": round(capture_found / capture_total, 4) if capture_total else 1.0,
                "split_by_source": split,
                "missing_label_ids": sorted(missing_ids),
            },
            "supersession": {
                "passed": supersession_passed,
                "total": supersession_total,
                "correctness": round(supersession_passed / supersession_total, 4)
                if supersession_total
                else 1.0,
                "stale_items_present": stale_present,
            },
            "contamination_facts": {
                "count": len(contamination_ids),
                "ids": sorted(contamination_ids),
                "refs": sorted(contamination_refs),
            },
            "briefing": {
                "coverage_by_kind": avg_cov,
                "dropped_by_kind": sum_drop,
                "drops_disclosed": total_drop_disclosed == len(sessions_out) and len(sessions_out) > 0,
                "budgets": {str(b): {"status": "unsupported"} for b in budgets},
            },
            "ledger_bytes_by_kind": dict(sorted(total_ledger_bytes.items())),
        },
    }


def _run_single_process_cli(
    fixture_dir: str,
    budgets: tuple[int, ...],
    output_path: str,
) -> dict[str, Any]:
    report = _one_process_report(fixture_dir, budgets)
    if output_path:
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(report, indent=2, sort_keys=True))
            f.write("\n")
    return report


def _run_subprocess_once(
    fixture_dir: str,
    budgets: tuple[int, ...],
    seed: str,
) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "report.json")
        cmd = [
            sys.executable,
            "-m",
            "ctxpack.benchmarks.replay",
            "--fixture",
            fixture_dir,
            "--budgets",
            ",".join(str(x) for x in budgets),
            "--output",
            out,
            "--single-process",
        ]
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"replay subprocess failed ({seed}): {proc.stderr.strip()}")
        with open(out, "rb") as f:
            return f.read()


def run_replay(
    fixture_dir: str,
    *,
    budgets: tuple[int, ...] = DEFAULT_BUDGETS,
    output_path: str = "",
) -> dict[str, Any]:
    """Run replay benchmark with cross-process determinism verification."""
    run1 = _run_subprocess_once(fixture_dir, budgets, seed="11")
    run2 = _run_subprocess_once(fixture_dir, budgets, seed="97")
    base = json.loads(run1.decode("utf-8"))
    base["determinism"] = {
        "identical_bytes": run1 == run2,
        "first_sha256": hashlib.sha256(run1).hexdigest(),
        "second_sha256": hashlib.sha256(run2).hexdigest(),
        "seeds": ["11", "97"],
    }
    if output_path:
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(base, indent=2, sort_keys=True))
            f.write("\n")
    return base


def main(argv: list[str] | None = None) -> int:
    """CLI for ``python -m ctxpack.benchmarks.replay``."""
    parser = argparse.ArgumentParser(description="Offline deterministic CTX replay benchmark")
    parser.add_argument("--fixture", required=True, help="Fixture directory")
    parser.add_argument("--output", default="", help="Optional output report path")
    parser.add_argument(
        "--budgets",
        default=",".join(str(x) for x in DEFAULT_BUDGETS),
        help="Comma-separated character budgets (default: 2000,4000,8000,14000)",
    )
    parser.add_argument("--single-process", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    budgets = tuple(int(x) for x in args.budgets.split(",") if x.strip())
    if args.single_process:
        report = _run_single_process_cli(args.fixture, budgets, args.output)
    else:
        report = run_replay(args.fixture, budgets=budgets, output_path=args.output)
    if not args.output:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
