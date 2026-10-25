"""Offline deterministic replay benchmark for CTX Legions L1.

Runs fixture session chains through the real CTX checkpoint/read path and
reports capture recall, supersession correctness, contamination, and briefing
coverage/disclosure signals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

from ..agent.checkpoint import read_startup_context, run_checkpoint
from ..agent.session_reader import _kind_of, _primary_value, _sections, load_session, session_decisions
from ..core.serializer import serialize_section

DEFAULT_BUDGETS = (2000, 4000, 8000, 14000)


@dataclass(frozen=True)
class Label:
    id: str
    session: str
    kind: str
    source: str
    text: str


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


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
    out: list[str] = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "transcript.jsonl")):
            out.append(path)
    if not out:
        raise ValueError(f"no transcript sessions found under {root}")
    return out


def _load_fixture(fixture_dir: str) -> tuple[dict[str, Any], list[Label]]:
    payload = _read_json(os.path.join(fixture_dir, "labels.json"))
    labels = [
        Label(
            id=str(row["id"]),
            session=str(row["session"])[:8],
            kind=str(row["kind"]).upper(),
            source=str(row["source"]).lower(),
            text=str(row["text"]),
        )
        for row in payload.get("labels", [])
    ]
    return payload, labels


def _bpe_estimate(text: str) -> int:
    try:
        from .metrics.cost import count_bpe_tokens

        return int(count_bpe_tokens(text, model="claude"))
    except Exception:
        return max(1, len(text) // 4)


def _facts_for_doc(doc) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for section in _sections(doc):
        kind = _kind_of(section).upper()
        text = _primary_value(section)
        if not text:
            continue
        turn = -1
        fact_id = ""
        for child in section.children:
            key = getattr(child, "key", "").upper()
            if key == "TURN":
                try:
                    turn = int(child.value)
                except ValueError:
                    turn = -1
            if key == "FACT-ID":
                fact_id = str(child.value)
        facts.append(
            {
                "kind": kind,
                "text": text,
                "turn": turn,
                "fact_id": fact_id,
                "section": section,
            }
        )
    facts.sort(key=lambda f: (f["turn"], f["kind"], f["text"]))
    return facts


def _ledger_bytes_by_kind(facts: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for fact in facts:
        payload = "\n".join(serialize_section(fact["section"]))
        out[fact["kind"]] = out.get(fact["kind"], 0) + len(payload.encode("utf-8"))
    return out


def _briefing_adapter(ledger_dir: str, budget_chars: int | None = None) -> dict[str, Any]:
    """Current CTX adapter: fixed startup context only, no budget knob yet."""
    text = read_startup_context(ledger_dir).strip()
    return {
        "status": "ok" if budget_chars is None else "unsupported",
        "text": text,
        "chars": len(text),
        "estimated_tokens": _bpe_estimate(text),
    }


def _drops_disclosed(briefing_text: str) -> bool:
    low = briefing_text.lower()
    if "dropped" not in low:
        return False
    return any(x in low for x in (
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


def _validate_commit_labels(labels: list[Label], session_dirs: list[str]) -> None:
    commit_texts: dict[str, set[str]] = {}
    for sdir in session_dirs:
        sid = os.path.basename(sdir).split("-", 1)[-1][:8]
        cpath = os.path.join(sdir, "commits.jsonl")
        if os.path.isfile(cpath):
            commit_texts[sid] = {
                str(row.get("text", ""))
                for row in _read_jsonl(cpath)
                if str(row.get("text", "")).strip()
            }
    for label in labels:
        if label.source == "commit" and label.text not in commit_texts.get(label.session, set()):
            raise ValueError(f"commit label not present in commits.jsonl: {label.id}")


def _one_process_report(fixture_dir: str, budgets: tuple[int, ...]) -> dict[str, Any]:
    fixture, labels = _load_fixture(fixture_dir)
    label_by_id = {l.id: l for l in labels}
    as_of = str(fixture.get("as_of", "2026-10-25"))
    contamination_texts = {str(x) for x in fixture.get("contamination_texts", [])}
    supers = fixture.get("supersessions", [])
    session_dirs = _session_dirs(fixture_dir)
    _validate_commit_labels(labels, session_dirs)

    sessions_out: list[dict[str, Any]] = []
    missing_ids: list[str] = []
    source_totals: dict[str, int] = {"transcript": 0, "commit": 0}
    source_found: dict[str, int] = {"transcript": 0, "commit": 0}
    capture_found = 0
    contamination_ids: list[str] = []
    contamination_refs: list[str] = []
    session_live: dict[str, str] = {}

    with tempfile.TemporaryDirectory() as td:
        for sdir in session_dirs:
            transcript = os.path.join(sdir, "transcript.jsonl")
            result = run_checkpoint(transcript, td, as_of=as_of)
            sid = result.session_id[:8]
            doc, _ = load_session(td, sid)
            facts = _facts_for_doc(doc)
            fact_set = {(f["kind"], f["text"]) for f in facts}
            labels_here = [l for l in labels if l.session == sid]

            for label in labels_here:
                source_totals[label.source] = source_totals.get(label.source, 0) + 1
                if (label.kind, label.text) in fact_set:
                    capture_found += 1
                    source_found[label.source] = source_found.get(label.source, 0) + 1
                else:
                    missing_ids.append(label.id)

            for fact in facts:
                if fact["text"] in contamination_texts:
                    contamination_ids.append(fact["fact_id"] or fact["section"].name)
                    contamination_refs.append(f"{sid}:{fact['kind']}")

            briefing = _briefing_adapter(td)
            decisions_payload = session_decisions(doc, sid)
            session_live[sid] = _live_blob(briefing["text"], decisions_payload)

            by_kind_total: dict[str, int] = {}
            by_kind_seen: dict[str, int] = {}
            for label in labels_here:
                by_kind_total[label.kind] = by_kind_total.get(label.kind, 0) + 1
                if label.text in briefing["text"]:
                    by_kind_seen[label.kind] = by_kind_seen.get(label.kind, 0) + 1

            sessions_out.append(
                {
                    "session": sid,
                    "capture": {
                        "found": sum(1 for l in labels_here if (l.kind, l.text) in fact_set),
                        "total": len(labels_here),
                    },
                    "briefing": {
                        "chars": briefing["chars"],
                        "estimated_tokens": briefing["estimated_tokens"],
                        "coverage_by_kind": {
                            k: round(by_kind_seen.get(k, 0) / by_kind_total[k], 4)
                            for k in sorted(by_kind_total)
                        },
                        "dropped_by_kind": {
                            k: by_kind_total[k] - by_kind_seen.get(k, 0)
                            for k in sorted(by_kind_total)
                        },
                        "drops_disclosed": _drops_disclosed(briefing["text"]),
                        "budgets": {str(b): {"status": "unsupported"} for b in budgets},
                    },
                    "ledger_bytes_by_kind": _ledger_bytes_by_kind(facts),
                }
            )

    supers_total = 0
    supers_passed = 0
    stale_present = 0
    for row in supers:
        old = label_by_id[str(row["old"])]
        new = label_by_id[str(row["new"])]
        sid = str(row.get("session", "") or new.session)[:8]
        live = session_live.get(sid, "")
        old_absent = old.text not in live
        new_present = new.text in live
        supers_total += 1
        if old_absent and new_present:
            supers_passed += 1
        if not old_absent:
            stale_present += 1

    split = {}
    for source in sorted(source_totals):
        total = source_totals[source]
        found = source_found.get(source, 0)
        split[source] = {
            "found": found,
            "total": total,
            "recall": round(found / total, 4) if total else 1.0,
        }

    total_ledger_bytes: dict[str, int] = {}
    total_cov_sum: dict[str, float] = {}
    total_drop_sum: dict[str, int] = {}
    total_disclosed = 0
    for row in sessions_out:
        total_disclosed += 1 if row["briefing"]["drops_disclosed"] else 0
        for k, v in row["ledger_bytes_by_kind"].items():
            total_ledger_bytes[k] = total_ledger_bytes.get(k, 0) + v
        for k, v in row["briefing"]["coverage_by_kind"].items():
            total_cov_sum[k] = total_cov_sum.get(k, 0.0) + v
        for k, v in row["briefing"]["dropped_by_kind"].items():
            total_drop_sum[k] = total_drop_sum.get(k, 0) + v

    return {
        "schema_version": "replay/v1",
        "fixture": os.path.basename(os.path.abspath(fixture_dir)),
        "as_of": as_of,
        "sessions": sessions_out,
        "totals": {
            "capture": {
                "found": capture_found,
                "total": len(labels),
                "recall": round(capture_found / len(labels), 4) if labels else 1.0,
                "split_by_source": split,
                "missing_label_ids": sorted(missing_ids),
            },
            "supersession": {
                "passed": supers_passed,
                "total": supers_total,
                "correctness": round(supers_passed / supers_total, 4) if supers_total else 1.0,
                "stale_items_present": stale_present,
            },
            "contamination_facts": {
                "count": len(contamination_ids),
                "ids": sorted(contamination_ids),
                "refs": sorted(contamination_refs),
            },
            "briefing": {
                "coverage_by_kind": {
                    k: round(v / max(1, len(sessions_out)), 4)
                    for k, v in sorted(total_cov_sum.items())
                },
                "dropped_by_kind": dict(sorted(total_drop_sum.items())),
                "drops_disclosed": total_disclosed == len(sessions_out) and len(sessions_out) > 0,
                "budgets": {str(b): {"status": "unsupported"} for b in budgets},
            },
            "ledger_bytes_by_kind": dict(sorted(total_ledger_bytes.items())),
        },
    }


def _run_single_process_cli(fixture_dir: str, budgets: tuple[int, ...], output_path: str) -> dict[str, Any]:
    report = _one_process_report(fixture_dir, budgets)
    if output_path:
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_canonical_json(report))
            f.write("\n")
    return report


def _run_subprocess_once(fixture_dir: str, budgets: tuple[int, ...], seed: str) -> bytes:
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
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
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
    first = _run_subprocess_once(fixture_dir, budgets, seed="11")
    second = _run_subprocess_once(fixture_dir, budgets, seed="97")
    report = json.loads(first.decode("utf-8"))
    report["determinism"] = {
        "identical_bytes": first == second,
        "first_sha256": hashlib.sha256(first).hexdigest(),
        "second_sha256": hashlib.sha256(second).hexdigest(),
        "seeds": ["11", "97"],
    }
    if output_path:
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_canonical_json(report))
            f.write("\n")
    return report


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
