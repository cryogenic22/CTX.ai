"""Q2-2 — CompactBench cost/completion accounting (reviewer finding).

Contract: budget projections use COMPLETED measured cells only, every
dollar of failed/partial spend stays reported, unknown spend is never
silently zero, cache hits never make the llm-memory build look free,
and dry-run rows are never "measured". The invocation ledger records
one row per model call including stalls whose spend is unknowable.
"""

import json
import subprocess

import pytest

from ctxpack.benchmarks.compactbench import driver
from run_compactbench import build_report

PARAMS = {"k_max": 1}


@pytest.fixture(autouse=True)
def _clean_invocations():
    driver.reset_invocations()
    yield
    driver.reset_invocations()


def _probe(seed, arm="ctx", k=1, cost=0.1, **kw):
    return {"seed": seed, "arm": arm, "k": k, "probe_id": f"p{seed}-{k}",
            "kind": "decision_current", "answer": "x", "correct": True,
            "usage": {"input_tokens": 10}, "cost_usd": cost, **kw}


def _cycle(seed, arm="ctx", cost=0.05):
    return {"seed": seed, "arm": arm, "kind": "cycle", "nudge_cost": cost,
            "nudge_usage": {"input_tokens": 5}}


def _err(seed, arm="ctx"):
    return {"seed": seed, "arm": arm, "kind": "cell_error", "error": "boom"}


# ------------------------------------------------- cell status + buckets


def test_partial_cell_is_excluded_from_per_seed_cost_but_spend_kept():
    rows = [
        _cycle(0), _probe(0, cost=0.1), _err(0),      # partial: died at k=1
        _cycle(1, cost=0.05), _probe(1, cost=0.2),    # completed
    ]
    e = build_report(rows, PARAMS)["arms"]["ctx"]
    assert e["cells"] == {"completed": [1], "partial": [0], "failed": []}
    assert e["cost_per_seed_usd"] == 0.25          # completed cell only
    assert e["attempt_cost_usd"] == 0.4            # every dollar reported
    assert e["failed_partial_cost_usd"] == 0.15
    assert e["accounting_complete"] is True
    assert e["n_seeds"] == 1


def test_failed_cell_with_no_graded_rows():
    rows = [_cycle(0), _err(0)]
    e = build_report(rows, PARAMS)["arms"]["ctx"]
    assert e["cells"] == {"completed": [], "partial": [], "failed": [0]}
    assert e["cost_per_seed_usd"] is None
    assert e["attempt_cost_usd"] == 0.05


# ------------------------------------------------------- missing cost


def test_missing_cost_flips_accounting_complete_off():
    report = build_report([_probe(0, cost=None)], PARAMS)
    e = report["arms"]["ctx"]
    assert e["rows_missing_cost"] == 1
    assert e["accounting_complete"] is False
    assert report["accounting_complete"] is False


def test_batched_cost_carry_is_not_missing():
    rows = [_probe(0, cost=0.3),
            _probe(0, k=1, cost=None, cost_carried=True)]
    e = build_report(rows, PARAMS)["arms"]["ctx"]
    assert e["rows_missing_cost"] == 0
    assert e["accounting_complete"] is True


def test_cycle_row_with_unknown_nudge_cost_is_missing():
    rows = [_probe(0), {"seed": 0, "arm": "ctx", "kind": "cycle",
                        "nudge_cost": None, "nudge_usage": {}}]
    e = build_report(rows, PARAMS)["arms"]["ctx"]
    assert e["rows_missing_cost"] == 1
    assert e["accounting_complete"] is False


# --------------------------------------------------------- cache hits


def test_cache_hit_reports_true_build_cost_for_projection():
    rows = [
        {"seed": 0, "arm": "llm-memory", "kind": "memory_build",
         "cache_hit": True, "cost_usd": 0.0, "build_cost_usd": 0.42,
         "usage": {"input_tokens": 900}},
        _probe(0, arm="llm-memory", cost=0.1),
    ]
    report = build_report(rows, PARAMS)
    e = report["arms"]["llm-memory"]
    assert e["memory_build_cost_usd"] == 0.0       # spent this run
    assert report["cost_model"]["llm-memory"][
        "fresh_memory_build_per_seed_usd"] == 0.42  # true fresh-run cost
    assert e["accounting_complete"] is True


def test_legacy_cache_without_sidecar_is_incomplete_accounting():
    rows = [
        {"seed": 0, "arm": "llm-memory", "kind": "memory_build",
         "cache_hit": True, "cost_usd": 0.0, "build_cost_usd": None,
         "usage": {}},
        _probe(0, arm="llm-memory", cost=0.1),
    ]
    report = build_report(rows, PARAMS)
    assert report["arms"]["llm-memory"]["accounting_complete"] is False
    assert report["cost_model"]["llm-memory"][
        "fresh_memory_build_per_seed_usd"] is None
    assert report["accounting_complete"] is False


# ----------------------------------------------------------- dry runs


def test_dry_run_rows_are_never_measured():
    rows = [{"seed": 0, "arm": "ctx", "k": 1, "probe_id": "p", "kind":
             "decision_current", "answer": "(dry-run)", "correct": False,
             "dry_run": True}]
    report = build_report(rows, PARAMS)
    e = report["arms"]["ctx"]
    assert e["n_seeds"] == 0
    assert e["cost_per_seed_usd"] is None
    assert e["attempt_cost_usd"] == 0.0
    assert report["cost_model"]["ctx"]["n_seeds_measured"] == 0


# --------------------------------------------------- invocation ledger


class _Proc:
    def __init__(self, stdout):
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


def test_stalled_call_is_recorded_before_the_exception(tmp_path,
                                                       monkeypatch):
    monkeypatch.setattr(driver, "_claude_exe", lambda: "claude")

    def _stall(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=9)
    monkeypatch.setattr(driver.subprocess, "run", _stall)
    with pytest.raises(subprocess.TimeoutExpired):
        driver.run_claude(str(tmp_path), "hello", timeout=9)
    inv = driver.invocation_records()
    assert len(inv) == 1
    assert inv[0]["status"] == "timeout"
    assert inv[0]["cost_usd"] is None  # spend unknown, never zero


def test_ok_call_is_recorded_with_cost_and_ledger_feeds_the_report(
        tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "_claude_exe", lambda: "claude")
    payload = json.dumps({"result": "ok", "session_id": "s",
                          "usage": {"input_tokens": 7},
                          "total_cost_usd": 0.03, "duration_ms": 5})
    monkeypatch.setattr(driver.subprocess, "run",
                        lambda *a, **kw: _Proc(payload))
    driver.run_claude(str(tmp_path), "hello")
    report = build_report([_probe(0, cost=0.03)], PARAMS)
    assert report["invocations"]["total"] == 1
    assert report["invocations"]["by_status"] == {"ok": 1}
    assert report["invocations"]["unknown_cost"] == 0
    assert report["invocations"]["ledger_cost_usd"] == 0.03
    assert report["accounting_complete"] is True


def test_timeout_in_ledger_flips_run_accounting_off(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "_claude_exe", lambda: "claude")

    def _stall(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=9)
    monkeypatch.setattr(driver.subprocess, "run", _stall)
    with pytest.raises(subprocess.TimeoutExpired):
        driver.run_claude(str(tmp_path), "hello", timeout=9)
    report = build_report([_probe(0, cost=0.1)], PARAMS)
    assert report["invocations"]["unknown_cost"] == 1
    assert report["accounting_complete"] is False
