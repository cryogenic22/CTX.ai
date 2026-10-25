"""Replay benchmark tests for CTX Legions L1."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ctxpack.benchmarks.replay import main, run_replay


def _fixture_path() -> str:
    return str(Path(__file__).parent / "fixtures" / "replay" / "synthetic-l1")


def test_synthetic_fixture_shows_known_main_gaps():
    report = run_replay(_fixture_path())
    totals = report["totals"]
    assert report["determinism"]["identical_bytes"] is True
    assert totals["capture"]["total"] == 7
    assert totals["capture"]["found"] == 5
    assert set(totals["capture"]["missing_label_ids"]) == {
        "l1-commit-only",
        "l1-rejected",
    }
    assert totals["capture"]["split_by_source"]["commit"]["found"] == 0
    assert totals["capture"]["split_by_source"]["commit"]["total"] == 1
    assert totals["supersession"]["total"] == 1
    assert totals["supersession"]["passed"] == 0
    assert totals["supersession"]["stale_items_present"] == 1
    assert totals["contamination_facts"]["count"] >= 1
    assert totals["briefing"]["drops_disclosed"] is False
    assert set(totals["briefing"]["budgets"].keys()) == {
        "2000",
        "4000",
        "8000",
        "14000",
    }
    assert all(v["status"] == "unsupported"
               for v in totals["briefing"]["budgets"].values())


def test_synthetic_fixture_matches_pinned_baseline():
    expected_path = Path(_fixture_path()) / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = run_replay(_fixture_path())
    e_tot = expected["totals"]
    a_tot = actual["totals"]
    assert actual["schema_version"] == expected["schema_version"]
    assert actual["as_of"] == expected["as_of"]
    assert actual["fixture"] == expected["fixture"]
    assert a_tot["capture"] == e_tot["capture"]
    assert a_tot["supersession"] == e_tot["supersession"]
    assert a_tot["contamination_facts"] == e_tot["contamination_facts"]
    assert a_tot["briefing"]["dropped_by_kind"] == e_tot["briefing"]["dropped_by_kind"]
    assert a_tot["briefing"]["coverage_by_kind"] == e_tot["briefing"]["coverage_by_kind"]
    assert a_tot["briefing"]["drops_disclosed"] == e_tot["briefing"]["drops_disclosed"]
    assert a_tot["ledger_bytes_by_kind"] == e_tot["ledger_bytes_by_kind"]


def test_report_schema_and_briefing_fields_present():
    report = run_replay(_fixture_path())
    assert report["schema_version"] == "replay/v1"
    assert report["sessions"], "expected per-session rows"
    row = report["sessions"][0]
    assert {"session", "capture", "ledger_bytes_by_kind", "briefing"} <= set(row)
    assert "chars" in row["briefing"]
    assert "estimated_tokens" in row["briefing"]
    assert "coverage_by_kind" in row["briefing"]
    assert "dropped_by_kind" in row["briefing"]
    assert "drops_disclosed" in row["briefing"]
    for budget in ("2000", "4000", "8000", "14000"):
        assert row["briefing"]["budgets"][budget]["status"] == "unsupported"


def test_hand_made_fixture_reports_exactly_one_miss(tmp_path: Path):
    fixture = tmp_path / "f"
    (fixture / "sessions" / "01-mini").mkdir(parents=True)
    transcript = fixture / "sessions" / "01-mini" / "transcript.jsonl"
    transcript.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": "mini0001-session",
                        "timestamp": "2026-10-25T00:00:00Z",
                        "isSidechain": False,
                        "isMeta": False,
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "Decision: keep 750ms backoff."}
                            ],
                        },
                    }
                ),
            )
        ),
        encoding="utf-8",
    )
    (fixture / "labels.json").write_text(
        json.dumps(
            {
                "as_of": "2026-10-25",
                "labels": [
                    {
                        "id": "ok",
                        "session": "mini0001",
                        "kind": "DECISION",
                        "source": "transcript",
                        "text": "Decision: keep 750ms backoff.",
                    },
                    {
                        "id": "miss",
                        "session": "mini0001",
                        "kind": "FAILED-APPROACH",
                        "source": "transcript",
                        "text": "Rejected: this line is intentionally not captured.",
                    },
                ],
                "supersessions": [],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    report = run_replay(str(fixture))
    assert report["totals"]["capture"]["total"] == 2
    assert report["totals"]["capture"]["found"] == 1
    assert report["totals"]["capture"]["missing_label_ids"] == ["miss"]


def test_cli_main_writes_json_report(tmp_path: Path):
    out = tmp_path / "report.json"
    rc = main(["--fixture", _fixture_path(), "--output", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == "replay/v1"
    assert data["determinism"]["identical_bytes"] is True


def test_replay_runtime_under_one_minute():
    t0 = time.perf_counter()
    run_replay(_fixture_path())
    assert time.perf_counter() - t0 < 60
