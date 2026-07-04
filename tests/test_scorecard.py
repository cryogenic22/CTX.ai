"""Layer-1 scorecard aggregation + dashboard rendering."""

import json

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.dashboard import render_dashboard
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
        "ctxpack-scorecard/v1"


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
