"""Layer-1 scorecard aggregation + dashboard rendering."""

import json

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.dashboard import render_dashboard, render_markdown
from ctxpack.agent.scorecard import (
    build_scorecard,
    load_cohort,
    save_cohort,
    write_scorecard,
)


def _entry(etype, content, sid):
    return {"type": etype, "sessionId": sid,
            "timestamp": "2026-07-04T10:00:00Z",
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _make_repo(tmp_path, name, decisions=1):
    repo = tmp_path / name
    (repo / ".claude").mkdir(parents=True)
    entries = []
    for i in range(decisions):
        entries.append(_entry("user", f"work on item {i}", f"{name}-session"))
        entries.append(_entry("assistant", [
            {"type": "text", "text": f"Decision: choose approach {i} for "
                                     f"{name}."}], f"{name}-session"))
    t = tmp_path / f"{name}.jsonl"
    t.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    run_checkpoint(str(t), str(repo / ".claude" / "ctx"), as_of="2026-07-04")
    return str(repo)


def test_scorecard_mixes_active_and_quiet_repos(tmp_path):
    active = _make_repo(tmp_path, "repo-a", decisions=3)
    quiet = tmp_path / "repo-b"
    (quiet / ".claude").mkdir(parents=True)
    missing = tmp_path / "repo-c"
    missing.mkdir()

    card = build_scorecard([active, str(quiet), str(missing)])
    by_name = {r["repo"]: r for r in card["repos"]}
    assert by_name["repo-a"]["status"] == "active"
    assert by_name["repo-b"]["status"] == "onboarded_no_data"
    assert by_name["repo-c"]["status"] == "not_onboarded"
    assert card["cohort"]["repos_active"] == 1
    assert card["cohort"]["repos_total"] == 3
    assert card["cohort"]["captured"]["decisions"] == 3
    assert "observational" in card["measurement_class"]


def test_scorecard_versioned_write_never_overwrites(tmp_path):
    repo = _make_repo(tmp_path, "repo-a")
    out = str(tmp_path / "scores")
    card = build_scorecard([repo])
    p1, latest1 = write_scorecard(card, out)
    p2, latest2 = write_scorecard(card, out)
    assert p1 != p2, "second write must not overwrite the first"
    assert latest1 == latest2
    assert json.loads(open(p1, encoding="utf-8").read())["schema"] == \
        "ctxpack-scorecard/v2"


def test_cohort_roundtrip(tmp_path):
    out = str(tmp_path / "scores")
    assert load_cohort(out) is None
    save_cohort(["/x/a", "/x/b"], out)
    assert load_cohort(out) == ["/x/a", "/x/b"]


def test_dashboard_renders_selfcontained(tmp_path):
    active = _make_repo(tmp_path, "repo-a", decisions=2)
    quiet = tmp_path / "repo-b"
    (quiet / ".claude").mkdir(parents=True)
    html = render_dashboard(build_scorecard([active, str(quiet)]))

    assert html.startswith("<!doctype html>")
    assert "repo-a" in html and "repo-b" in html
    assert "no checkpoints yet" in html          # quiet repo guidance
    assert "Measurement class: observational" in html
    assert "prefers-color-scheme: dark" in html  # both modes styled
    for external in ("http://", "https://", "<script src"):
        assert external not in html, f"dashboard must be self-contained: {external}"


def test_dashboard_escapes_repo_names(tmp_path):
    # "&" is legal in a Windows dir name; "<" is not — & suffices to prove
    # escaping happens
    quiet = tmp_path / "repo & b"
    (quiet / ".claude").mkdir(parents=True)
    html = render_dashboard(build_scorecard([str(quiet)]))
    assert "repo &amp; b" in html


def test_markdown_exec_summary_renders(tmp_path):
    active = _make_repo(tmp_path, "repo-a", decisions=2)
    quiet = tmp_path / "repo-b"
    (quiet / ".claude").mkdir(parents=True)
    md = render_markdown(build_scorecard([active, str(quiet)]))

    assert md.startswith("# CtxPack session-memory scorecard")
    assert "Measurement class: observational" in md
    # per-repo read-path split is surfaced (the point of a read-path report)
    assert "Ledger reads | Greps | Fallback" in md
    assert "| repo-a | active |" in md
    # quiet repo renders as a placeholder row, not an active one
    assert "| repo-b | onboarded no data |" in md
    # no reads banked in this synthetic ledger → honest n/a, not a fake 0%
    assert "n/a (no reads yet)" in md


def test_markdown_reports_incident_types(tmp_path):
    active = _make_repo(tmp_path, "repo-a", decisions=1)
    card = build_scorecard([active])
    # inject a couple of incident rows to prove the section aggregates + sorts
    card["cohort"]["incident_types"] = {"saved": 3, "missed": 1}
    md = render_markdown(card)
    assert "### Incidents (agent-reported)" in md
    # sorted by count desc: saved (3) before missed (1)
    assert md.index("- saved: 3") < md.index("- missed: 1")


def test_markdown_escapes_table_pipes():
    # "|" is illegal in a Windows path, so build the scorecard dict directly:
    # a repo name with a pipe must not break the markdown table structure
    card = {
        "schema": "ctxpack-scorecard/v1",
        "generated_at": "2026-07-06T00:00:00+00:00",
        "cohort": {"repos_active": 0, "repos_total": 1, "sessions": 0,
                   "turns_packed": 0, "captured": {}, "read_path": {},
                   "incident_types": {}},
        "repos": [{"repo": "repo|b", "status": "not_onboarded"}],
    }
    md = render_markdown(card)
    assert r"repo\|b" in md  # literal pipe escaped so the table stays intact
