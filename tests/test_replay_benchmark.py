"""Replay benchmark tests for CTX Legions L1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ctxpack.benchmarks.replay as replay_mod
from ctxpack.benchmarks.replay import DEFAULT_BUDGETS, main, run_replay


def _fixture_path() -> str:
    return str(Path(__file__).parent / "fixtures" / "replay" / "synthetic-l1")


def test_synthetic_fixture_shows_known_main_gaps():
    report = run_replay(_fixture_path())
    totals = report["totals"]
    assert report["determinism"]["identical_bytes"] is True
    assert totals["capture"]["total"] == 6
    assert totals["capture"]["found"] == 4
    assert set(totals["capture"]["missing_label_ids"]) == {
        "l1-commit-only",
        "l1-rejected",
    }
    assert totals["capture"]["split_by_source"]["commit"]["found"] == 0
    assert totals["capture"]["split_by_source"]["commit"]["total"] == 1
    assert totals["supersession"]["total"] == 1
    assert totals["supersession"]["passed"] == 0
    assert totals["supersession"]["stale_items_present"] == 3
    assert set(totals["contamination_facts"]["ids"]) == {
        "3c3101a88a30f5bc",
        "5058d09a53e320a3",
        "6b926a0e9c157517",
        "7d17221aec3da77d",
        "c4907879de291f6b",
        "d2018dbd19705d43",
    }
    assert set(totals["contamination_facts"]["by_kind"]["harness"]["ids"]) == {
        "3c3101a88a30f5bc",
        "6b926a0e9c157517",
        "d2018dbd19705d43",
    }
    assert set(totals["contamination_facts"]["by_kind"]["probe"]["ids"]) == {
        "5058d09a53e320a3",
        "7d17221aec3da77d",
        "c4907879de291f6b",
    }
    assert totals["briefing"]["drops_disclosed"] is True
    assert set(totals["briefing"]["budgets"].keys()) == {
        "2000",
        "4000",
        "8000",
        "14000",
    }
    assert all(v["status"] == "unsupported"
               for v in totals["briefing"]["budgets"].values())


def test_synthetic_fixture_matches_pinned_baseline():
    out_path = Path(_fixture_path()) / ".tmp-out.json"
    expected_path = Path(_fixture_path()) / "expected.json"
    rc = main(["--fixture", _fixture_path(), "--output", str(out_path)])
    assert rc == 0
    assert out_path.read_bytes() == expected_path.read_bytes()
    out_path.unlink()


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


def test_missing_as_of_raises(tmp_path: Path):
    fixture = tmp_path / "f"
    (fixture / "sessions" / "01-mini").mkdir(parents=True)
    (fixture / "sessions" / "01-mini" / "transcript.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "sessionId": "mini0001-session",
                "timestamp": "2026-10-25T00:00:00Z",
                "isSidechain": False,
                "isMeta": False,
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Decision: test."}]},
            }
        ),
        encoding="utf-8",
    )
    (fixture / "labels.json").write_text(
        json.dumps(
            {
                "labels": [
                    {
                        "id": "ok",
                        "session": "mini0001",
                        "kind": "DECISION",
                        "source": "transcript",
                        "text": "Decision: test.",
                    }
                ],
                "supersessions": [],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="as_of"):
        run_replay(str(fixture), determinism_check=False)


def test_fake_adapter_enables_budget_scoring_and_supersession_pass(monkeypatch: pytest.MonkeyPatch):
    calls: list[int | None] = []

    def fake_briefing_adapter(_ledger_dir: str, budget_chars: int | None = None) -> dict[str, str]:
        calls.append(budget_chars)
        text = (
            "Decision: raise retry backoff to 750ms for vendor calls.\n"
            "Dropped 1 decision.\n"
            "Dropped 1 constraint."
        )
        return {"status": "ok", "text": text}

    original_session_decisions = replay_mod.session_decisions

    def fake_session_decisions(doc, sid):
        payload = original_session_decisions(doc, sid)
        if sid in {"rpl00002", "rpl00003", "rpl00004"}:
            payload["decisions"] = [
                {"text": "Decision: raise retry backoff to 750ms for vendor calls."}
            ]
        return payload

    monkeypatch.setattr(replay_mod, "session_decisions", fake_session_decisions)
    report = run_replay(
        _fixture_path(),
        determinism_check=False,
        briefing_adapter=fake_briefing_adapter,
    )
    assert calls.count(None) == 4
    assert set(x for x in calls if x is not None) == set(DEFAULT_BUDGETS)
    for budget in ("2000", "4000", "8000", "14000"):
        assert report["sessions"][0]["briefing"]["budgets"][budget]["status"] == "ok"
    assert report["totals"]["briefing"]["drops_disclosed"] is True
    assert report["totals"]["supersession"]["passed"] == 1


def test_cli_main_writes_json_report(tmp_path: Path):
    out = tmp_path / "report.json"
    rc = main(["--fixture", _fixture_path(), "--output", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == "replay/v1"
    assert data["determinism"]["identical_bytes"] is True
