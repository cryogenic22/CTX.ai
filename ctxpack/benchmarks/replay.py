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
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Callable

from ..agent.checkpoint import read_startup_context, run_checkpoint
from ..agent.session_reader import ledger_facts, load_session, session_decisions

DEFAULT_BUDGETS = (2000, 4000, 8000, 14000)
BriefingAdapter = Callable[[str, int | None], dict[str, Any]]
CommitCaptureAdapter = Callable[[str, list[dict[str, Any]]], dict[str, Any]]
REPLAY_TOKENIZER_LIBRARY = "tiktoken"
REPLAY_TOKENIZER_ENCODING = "cl100k_base"

_DROPS_KIND_TERMS = {
    "DECISION": "decision",
    "CONSTRAINT": "constraint",
    "FAILED-APPROACH": "failed approach",
}


@dataclass(frozen=True)
class Label:
    id: str
    session: str
    kind: str
    source: str
    text: str


def _write_report(path: str, report: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=True)
        f.write("\n")


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _session_dirs(fixture_dir: str) -> list[str]:
    root = os.path.join(fixture_dir, "sessions")
    if not os.path.isdir(root):
        raise ValueError(f"missing fixture sessions dir: {root}")
    out = [
        os.path.join(root, name)
        for name in sorted(os.listdir(root))
        if os.path.isdir(os.path.join(root, name))
        and os.path.isfile(os.path.join(root, name, "transcript.jsonl"))
    ]
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


def _briefing_adapter(ledger_dir: str, budget_chars: int | None = None) -> dict[str, Any]:
    """Current CTX adapter: fixed startup context only, no budget knob yet."""
    text = read_startup_context(ledger_dir).strip()
    if budget_chars is None:
        return {"status": "ok", "text": text}
    return {"status": "unsupported", "text": text}


def _commit_capture_adapter(_session_id: str, _commits: list[dict[str, Any]]) -> dict[str, Any]:
    """Current CTX adapter: commit capture is not wired in baseline."""
    return {"status": "unsupported", "facts": []}


def _drops_disclosed(briefing_text: str, dropped_by_kind: dict[str, int]) -> bool:
    if not dropped_by_kind:
        return False
    low = briefing_text.lower()
    if "dropped" not in low:
        return False
    for kind, count in dropped_by_kind.items():
        term = _DROPS_KIND_TERMS.get(kind, kind.lower().replace("-", " "))
        term_pattern = re.escape(term).replace(r"\ ", r"[ -]+")
        if term == "failed approach":
            term_pattern = r"failed[ -]+approach(?:es)?"
        else:
            term_pattern = rf"{term_pattern}s?"
        pattern = rf"\bdropped\s+{count}\s+{term_pattern}\b"
        if re.search(pattern, low) is None:
            return False
    return True


def _require_replay_tokenizer() -> dict[str, Any]:
    ready_file = os.environ.get("CTX_REPLAY_TOKENIZER_READY_FILE", "").strip()
    if ready_file and not os.path.isfile(ready_file):
        raise RuntimeError(
            "replay tokenizer cache marker missing: "
            f"{ready_file} (did the cache warm-up step run?)"
        )
    try:
        import tiktoken
    except Exception as exc:  # noqa: BLE001 - intentional loud failure path
        raise RuntimeError(
            "replay benchmark requires tiktoken with cl100k_base available; "
            "install tiktoken and prewarm tokenizer cache before running replay"
        ) from exc
    try:
        enc = tiktoken.get_encoding(REPLAY_TOKENIZER_ENCODING)
        enc.encode("ctxpack replay tokenizer readiness probe")
    except Exception as exc:  # noqa: BLE001 - intentional loud failure path
        raise RuntimeError(
            f"replay benchmark requires tokenizer encoding {REPLAY_TOKENIZER_ENCODING}; "
            "ensure cache warm-up completed before the replay test step"
        ) from exc
    return {
        "library": REPLAY_TOKENIZER_LIBRARY,
        "encoding": REPLAY_TOKENIZER_ENCODING,
    }


def _score_briefing(
    labels_here: list[Label],
    captured_facts: set[tuple[str, str]],
    briefing_text: str,
) -> tuple[dict[str, int], dict[str, int], dict[str, float], dict[str, int], bool]:
    by_kind_total: dict[str, int] = {}
    by_kind_seen: dict[str, int] = {}
    for label in labels_here:
        if (label.kind, label.text) in captured_facts:
            by_kind_total[label.kind] = by_kind_total.get(label.kind, 0) + 1
            if label.text in briefing_text:
                by_kind_seen[label.kind] = by_kind_seen.get(label.kind, 0) + 1
    coverage_by_kind = {
        kind: round(by_kind_seen.get(kind, 0) / total, 4)
        for kind, total in sorted(by_kind_total.items())
    }
    dropped_by_kind = {
        kind: total - by_kind_seen.get(kind, 0)
        for kind, total in sorted(by_kind_total.items())
    }
    return (
        by_kind_total,
        by_kind_seen,
        coverage_by_kind,
        dropped_by_kind,
        _drops_disclosed(briefing_text, dropped_by_kind),
    )


def _budget_rows(
    ledger_dir: str,
    budgets: tuple[int, ...],
    labels_here: list[Label],
    captured_facts: set[tuple[str, str]],
    adapter: BriefingAdapter,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for budget in budgets:
        payload = adapter(ledger_dir, budget)
        status = str(payload.get("status", "unsupported"))
        row: dict[str, Any] = {"status": status}
        if status == "ok":
            text = str(payload.get("text", ""))
            _, _, coverage_by_kind, dropped_by_kind, drops_disclosed = _score_briefing(
                labels_here, captured_facts, text
            )
            row.update({
                "chars": len(text),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "coverage_by_kind": coverage_by_kind,
                "dropped_by_kind": dropped_by_kind,
                "drops_disclosed": drops_disclosed,
            })
        out[str(budget)] = row
    return out


def _one_process_report(
    fixture_dir: str,
    budgets: tuple[int, ...],
    *,
    briefing_adapter: BriefingAdapter,
    commit_capture_adapter: CommitCaptureAdapter,
    tokenizer: dict[str, Any],
) -> dict[str, Any]:
    fixture, labels = _load_fixture(fixture_dir)
    label_by_id = {l.id: l for l in labels}
    as_of = str(fixture.get("as_of", "")).strip()
    if not as_of:
        raise ValueError("fixture labels.json is missing required field: as_of")
    contamination_turns = {
        kind: {(str(row["session"])[:8], int(row["turn"])) for row in (fixture.get("contamination_turns", {}) or {}).get(kind, [])}
        for kind in ("harness", "probe")
    }
    supers = fixture.get("supersessions", [])
    session_dirs = _session_dirs(fixture_dir)

    sessions_out: list[dict[str, Any]] = []
    missing_ids: list[str] = []
    source_totals: dict[str, int] = {"transcript": 0, "commit": 0}
    source_found: dict[str, int] = {"transcript": 0, "commit": 0}
    capture_found = 0
    contamination_counts: dict[str, int] = {"harness": 0, "probe": 0}
    session_live: dict[str, str] = {}
    session_order: list[str] = []
    micro_seen: dict[str, int] = {}
    micro_total: dict[str, int] = {}

    with tempfile.TemporaryDirectory() as td:
        for sdir in session_dirs:
            transcript = os.path.join(sdir, "transcript.jsonl")
            result = run_checkpoint(transcript, td, as_of=as_of)
            sid = result.session_id[:8]
            session_order.append(sid)
            doc, _ = load_session(td, sid)
            facts = ledger_facts(doc)
            fact_set = {(f["kind"], f["text"]) for f in facts}
            labels_here = [l for l in labels if l.session == sid]

            commits_path = os.path.join(sdir, "commits.jsonl")
            commit_rows = _read_jsonl(commits_path) if os.path.isfile(commits_path) else []
            commit_capture = commit_capture_adapter(sid, commit_rows)
            commit_status = str(commit_capture.get("status", "unsupported"))
            if commit_status == "ok":
                for row in commit_capture.get("facts", []):
                    kind = str(row.get("kind", "")).upper()
                    text = str(row.get("text", ""))
                    if kind and text:
                        fact_set.add((kind, text))

            for label in labels_here:
                source_totals[label.source] = source_totals.get(label.source, 0) + 1
                if (label.kind, label.text) in fact_set:
                    capture_found += 1
                    source_found[label.source] = source_found.get(label.source, 0) + 1
                else:
                    missing_ids.append(label.id)

            for fact in facts:
                for kind in ("harness", "probe"):
                    if (sid, fact["turn"]) in contamination_turns[kind]:
                        contamination_counts[kind] += 1

            base_briefing = briefing_adapter(td, None)
            base_status = str(base_briefing.get("status", "unsupported"))
            if base_status != "ok":
                raise ValueError("briefing adapter must return status=ok for baseline (budget=None)")
            base_text = str(base_briefing.get("text", ""))
            decisions_payload = session_decisions(doc, sid)
            session_live[sid] = "\n".join(
                [base_text]
                + [
                    str(row.get("text", ""))
                    for key in ("decisions", "constraints", "failed_approaches")
                    for row in decisions_payload.get(key, [])
                ]
            )

            (
                by_kind_total,
                by_kind_seen,
                coverage_by_kind,
                dropped_by_kind,
                drops_disclosed,
            ) = _score_briefing(labels_here, fact_set, base_text)

            for kind, total in by_kind_total.items():
                micro_total[kind] = micro_total.get(kind, 0) + total
                micro_seen[kind] = micro_seen.get(kind, 0) + by_kind_seen.get(kind, 0)

            budget_rows = _budget_rows(td, budgets, labels_here, fact_set, briefing_adapter)

            sessions_out.append({
                "session": sid,
                "capture": {"found": sum(1 for l in labels_here if (l.kind, l.text) in fact_set), "total": len(labels_here)},
                "commit_capture": {"status": commit_status},
                "briefing": {
                    "chars": len(base_text),
                    "sha256": hashlib.sha256(base_text.encode("utf-8")).hexdigest(),
                    "coverage_by_kind": coverage_by_kind,
                    "dropped_by_kind": dropped_by_kind,
                    "drops_disclosed": drops_disclosed,
                    "budgets": budget_rows,
                },
            })

    supers_total = 0
    supers_passed = 0
    stale_present = 0
    supers_checks: list[dict[str, Any]] = []
    sid_to_index = {sid: i for i, sid in enumerate(session_order)}
    for row in supers:
        old = label_by_id[str(row["old"])]
        new = label_by_id[str(row["new"])]
        start_sid = str(row.get("session", "") or new.session)[:8]
        if start_sid not in sid_to_index:
            raise ValueError(f"supersession session not found in fixture run: {start_sid}")
        checked_sessions = session_order[sid_to_index[start_sid]:]
        stale_sessions: list[str] = []
        edge_passed = True
        for sid in checked_sessions:
            live = session_live.get(sid, "")
            old_absent = old.text not in live
            new_present = new.text in live
            if not old_absent:
                stale_sessions.append(sid)
                stale_present += 1
            if not (old_absent and new_present):
                edge_passed = False
        supers_total += 1
        if edge_passed:
            supers_passed += 1
        supers_checks.append({
            "old": old.id,
            "new": new.id,
            "start_session": start_sid,
            "last_session_checked": checked_sessions[-1] if checked_sessions else start_sid,
            "passed": edge_passed,
            "stale_sessions": stale_sessions,
        })

    split = {
        source: {
            "found": source_found.get(source, 0),
            "total": source_totals[source],
            "recall": round(source_found.get(source, 0) / source_totals[source], 4) if source_totals[source] else 1.0,
        }
        for source in sorted(source_totals)
    }

    total_budget_rows: dict[str, dict[str, Any]] = {}
    for budget in budgets:
        key = str(budget)
        statuses = [row["briefing"]["budgets"][key]["status"] for row in sessions_out]
        if statuses and all(s == "unsupported" for s in statuses):
            total_budget_rows[key] = {"status": "unsupported"}
        elif statuses and all(s == "ok" for s in statuses):
            total_budget_rows[key] = {"status": "ok"}
        else:
            total_budget_rows[key] = {"status": "mixed"}

    scored_sessions = [row for row in sessions_out if row["briefing"]["coverage_by_kind"]]

    return {
        "schema_version": "replay/v1",
        "fixture": os.path.basename(os.path.abspath(fixture_dir)),
        "as_of": as_of,
        "tokenizer": tokenizer,
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
                "checks": supers_checks,
            },
            "contamination_facts": {
                "count": contamination_counts["harness"] + contamination_counts["probe"],
                "by_kind": {
                    "harness": {"count": contamination_counts["harness"]},
                    "probe": {"count": contamination_counts["probe"]},
                },
            },
            "briefing": {
                "coverage_by_kind": {
                    kind: round(micro_seen.get(kind, 0) / total, 4)
                    for kind, total in sorted(micro_total.items())
                    if total > 0
                },
                "dropped_by_kind": {
                    kind: micro_total[kind] - micro_seen.get(kind, 0)
                    for kind in sorted(micro_total)
                },
                "drops_disclosed": bool(scored_sessions) and all(
                    row["briefing"]["drops_disclosed"] for row in scored_sessions
                ),
                "budgets": total_budget_rows,
            },
        },
    }


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
    determinism_check: bool = True,
    briefing_adapter: BriefingAdapter = _briefing_adapter,
    commit_capture_adapter: CommitCaptureAdapter = _commit_capture_adapter,
) -> dict[str, Any]:
    if determinism_check and (
        briefing_adapter is not _briefing_adapter
        or commit_capture_adapter is not _commit_capture_adapter
    ):
        raise ValueError("custom adapters require determinism_check=False")

    if not determinism_check:
        report = _one_process_report(
            fixture_dir,
            budgets,
            briefing_adapter=briefing_adapter,
            commit_capture_adapter=commit_capture_adapter,
            tokenizer={"library": "unchecked", "encoding": REPLAY_TOKENIZER_ENCODING},
        )
        report["determinism"] = {
            "identical_bytes": True,
            "first_sha256": "",
            "second_sha256": "",
            "seeds": [],
            "status": "skipped",
        }
    else:
        first = _run_subprocess_once(fixture_dir, budgets, seed="11")
        second = _run_subprocess_once(fixture_dir, budgets, seed="97")
        first_sha = hashlib.sha256(first).hexdigest()
        second_sha = hashlib.sha256(second).hexdigest()
        if first != second:
            raise RuntimeError(
                "replay determinism mismatch: subprocess bytes differ "
                f"(seed 11 sha256={first_sha}, seed 97 sha256={second_sha})"
            )
        report = json.loads(first.decode("utf-8"))
        report["determinism"] = {
            "identical_bytes": True,
            "first_sha256": first_sha,
            "second_sha256": second_sha,
            "seeds": ["11", "97"],
        }
    if output_path:
        _write_report(output_path, report)
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
    try:
        if args.single_process:
            report = _one_process_report(
                args.fixture,
                budgets,
                briefing_adapter=_briefing_adapter,
                commit_capture_adapter=_commit_capture_adapter,
                tokenizer=_require_replay_tokenizer(),
            )
            if args.output:
                _write_report(args.output, report)
        else:
            report = run_replay(args.fixture, budgets=budgets, output_path=args.output)
    except Exception as exc:
        print(f"replay failed: {exc}", file=sys.stderr)
        return 1
    if not args.output:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
