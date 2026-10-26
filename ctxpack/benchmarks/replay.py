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
from ..core.serializer import serialize_section

DEFAULT_BUDGETS = (2000, 4000, 8000, 14000)
BriefingAdapter = Callable[[str, int | None], dict[str, Any]]
CommitCaptureAdapter = Callable[[str, list[dict[str, Any]]], dict[str, Any]]
REPLAY_TOKENIZER_LIBRARY = "tiktoken"
REPLAY_TOKENIZER_ENCODING = "cl100k_base"

_DROPS_KIND_TERMS = {
    "DECISION": "decision",
    "CONSTRAINT": "constraint",
    "FAILED-APPROACH": "failed approach",
    "LITERAL": "literal",
    "USER-REQUEST": "user request",
    "ERROR": "error",
    "TASK": "task",
    "FILE": "file",
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


def _require_as_of(fixture: dict[str, Any]) -> str:
    if "as_of" not in fixture:
        raise ValueError("fixture labels.json is missing required field: as_of")
    as_of = str(fixture["as_of"]).strip()
    if not as_of:
        raise ValueError("fixture labels.json has empty as_of")
    return as_of


def _parse_contamination_turns(fixture: dict[str, Any]) -> dict[str, set[tuple[str, int]]]:
    raw = fixture.get("contamination_turns") or {}
    turns: dict[str, set[tuple[str, int]]] = {"harness": set(), "probe": set()}
    for kind in ("harness", "probe"):
        rows = raw.get(kind) or []
        parsed: set[tuple[str, int]] = set()
        for row in rows:
            sid = str(row["session"])[:8]
            turn = int(row["turn"])
            parsed.add((sid, turn))
        turns[kind] = parsed
    return turns


def _ledger_bytes_by_kind(facts: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for fact in facts:
        payload = "\n".join(serialize_section(fact["section"]))
        out[fact["kind"]] = out.get(fact["kind"], 0) + len(payload.encode("utf-8"))
    return out


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


def _live_blob(briefing_text: str, decisions_payload: dict[str, Any]) -> str:
    lines = [briefing_text]
    for key in ("decisions", "constraints", "failed_approaches"):
        for row in decisions_payload.get(key, []):
            lines.append(str(row.get("text", "")))
    return "\n".join(lines)


def _score_briefing(
    labels_here: list[Label],
    captured_facts: set[tuple[str, str]],
    briefing_text: str,
) -> tuple[dict[str, int], dict[str, int], dict[str, float], dict[str, int], bool]:
    by_kind_total: dict[str, int] = {}
    by_kind_seen: dict[str, int] = {}
    for label in labels_here:
        if (label.kind, label.text) not in captured_facts:
            continue
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
        key = str(budget)
        payload = adapter(ledger_dir, budget)
        status = str(payload.get("status", "unsupported"))
        row: dict[str, Any] = {"status": status}
        if status == "ok":
            text = str(payload.get("text", ""))
            _, _, coverage_by_kind, dropped_by_kind, drops_disclosed = _score_briefing(
                labels_here, captured_facts, text
            )
            row.update(
                {
                    "chars": len(text),
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "coverage_by_kind": coverage_by_kind,
                    "dropped_by_kind": dropped_by_kind,
                    "drops_disclosed": drops_disclosed,
                }
            )
        out[key] = row
    return out


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
    as_of = _require_as_of(fixture)
    contamination_turns = _parse_contamination_turns(fixture)
    supers = fixture.get("supersessions", [])
    session_dirs = _session_dirs(fixture_dir)
    _validate_commit_labels(labels, session_dirs)

    sessions_out: list[dict[str, Any]] = []
    missing_ids: list[str] = []
    source_totals: dict[str, int] = {"transcript": 0, "commit": 0}
    source_found: dict[str, int] = {"transcript": 0, "commit": 0}
    capture_found = 0
    contamination_ids: dict[str, list[str]] = {"harness": [], "probe": []}
    session_live: dict[str, str] = {}
    session_order: list[str] = []
    micro_seen: dict[str, int] = {}
    micro_total: dict[str, int] = {}
    total_ledger_bytes: dict[str, int] = {}
    total_disclosed = 0
    scored_sessions = 0

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
                cid = fact["fact_id"] or fact["section"].name
                for kind in ("harness", "probe"):
                    if (sid, fact["turn"]) in contamination_turns[kind]:
                        contamination_ids[kind].append(cid)

            base_briefing = briefing_adapter(td, None)
            base_status = str(base_briefing.get("status", "unsupported"))
            if base_status != "ok":
                raise ValueError("briefing adapter must return status=ok for baseline (budget=None)")
            base_text = str(base_briefing.get("text", ""))
            decisions_payload = session_decisions(doc, sid)
            session_live[sid] = _live_blob(base_text, decisions_payload)

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
            if by_kind_total:
                scored_sessions += 1
                total_disclosed += 1 if drops_disclosed else 0

            budget_rows = _budget_rows(td, budgets, labels_here, fact_set, briefing_adapter)

            ledger_bytes = _ledger_bytes_by_kind(facts)
            for kind, value in ledger_bytes.items():
                total_ledger_bytes[kind] = total_ledger_bytes.get(kind, 0) + value

            sessions_out.append(
                {
                    "session": sid,
                    "capture": {
                        "found": sum(1 for l in labels_here if (l.kind, l.text) in fact_set),
                        "total": len(labels_here),
                    },
                    "commit_capture": {"status": commit_status},
                    "briefing": {
                        "chars": len(base_text),
                        "sha256": hashlib.sha256(base_text.encode("utf-8")).hexdigest(),
                        "coverage_by_kind": coverage_by_kind,
                        "dropped_by_kind": dropped_by_kind,
                        "drops_disclosed": drops_disclosed,
                        "budgets": budget_rows,
                    },
                    "ledger_bytes_by_kind": ledger_bytes,
                }
            )

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
        supers_checks.append(
            {
                "old": old.id,
                "new": new.id,
                "start_session": start_sid,
                "last_session_checked": checked_sessions[-1] if checked_sessions else start_sid,
                "passed": edge_passed,
                "stale_sessions": stale_sessions,
            }
        )

    split: dict[str, dict[str, Any]] = {}
    for source in sorted(source_totals):
        total = source_totals[source]
        found = source_found.get(source, 0)
        split[source] = {
            "found": found,
            "total": total,
            "recall": round(found / total, 4) if total else 1.0,
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

    contamination_total_ids = sorted(contamination_ids["harness"] + contamination_ids["probe"])

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
                "count": len(contamination_total_ids),
                "ids": contamination_total_ids,
                "by_kind": {
                    "harness": {
                        "count": len(contamination_ids["harness"]),
                        "ids": sorted(contamination_ids["harness"]),
                    },
                    "probe": {
                        "count": len(contamination_ids["probe"]),
                        "ids": sorted(contamination_ids["probe"]),
                    },
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
                "drops_disclosed": scored_sessions > 0 and total_disclosed == scored_sessions,
                "budgets": total_budget_rows,
            },
            "ledger_bytes_by_kind": dict(sorted(total_ledger_bytes.items())),
        },
    }


def _run_single_process_cli(fixture_dir: str, budgets: tuple[int, ...], output_path: str) -> dict[str, Any]:
    tokenizer = _require_replay_tokenizer()
    report = _one_process_report(
        fixture_dir,
        budgets,
        briefing_adapter=_briefing_adapter,
        commit_capture_adapter=_commit_capture_adapter,
        tokenizer=tokenizer,
    )
    if output_path:
        _write_report(output_path, report)
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
    determinism_check: bool = True,
    briefing_adapter: BriefingAdapter = _briefing_adapter,
    commit_capture_adapter: CommitCaptureAdapter = _commit_capture_adapter,
) -> dict[str, Any]:
    """Run replay benchmark with optional cross-process determinism verification."""
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
            tokenizer={
                "library": "unchecked",
                "encoding": REPLAY_TOKENIZER_ENCODING,
            },
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


def _emit_token_info(report: dict[str, Any]) -> None:
    """Print rough token info to stderr without affecting pinned report bytes."""
    for row in report.get("sessions", []):
        sid = str(row.get("session", ""))
        chars = int(row.get("briefing", {}).get("chars", 0))
        rough_tokens = max(1, chars // 4) if chars else 0
        print(
            f"[replay-token-info] session={sid} chars={chars} rough_tokens={rough_tokens} method=chars_div_4",
            file=sys.stderr,
        )


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
            report = _run_single_process_cli(args.fixture, budgets, args.output)
        else:
            report = run_replay(args.fixture, budgets=budgets, output_path=args.output)
    except Exception as exc:
        print(f"replay failed: {exc}", file=sys.stderr)
        return 1
    _emit_token_info(report)
    if not args.output:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
