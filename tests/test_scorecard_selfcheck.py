"""Self-verifying scorecards (Loop 2, preflight backlog PF-02).

A "latest" scorecard must be verifiable against the inputs it was
computed from: cohort-config sha + per-repo ledger fingerprints.
`ctxpack scorecard --check` exits nonzero when latest is stale, missing
or predates self-verification, so a dashboard can never quietly present
an old population as current. All fixtures synthetic.
"""

import json

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.scorecard import (
    build_scorecard,
    load_cohort,
    save_cohort,
    verify_latest,
)
from ctxpack.cli.main import main


def _repo(tmp_path, name, sid):
    repo = tmp_path / name
    out = repo / ".claude" / "ctx"
    out.mkdir(parents=True)
    rows = [{"type": "user", "sessionId": sid, "uuid": "u1",
             "message": {"content": "Ship it."}},
            {"type": "assistant", "sessionId": sid, "uuid": "u2",
             "message": {"content": [{"type": "text", "text":
                         "Decision: use backoff because the cap is "
                         "40 req/min."}]}}]
    transcript = tmp_path / f"{name}.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                          encoding="utf-8")
    run_checkpoint(str(transcript), str(out), as_of="2026-08-07")
    return repo


def _generate(tmp_path, repos, out_name="cards"):
    out = tmp_path / out_name
    rc = main(["scorecard", "--repos", *[str(r) for r in repos],
               "--out", str(out)])
    assert rc == 0
    return out


def test_clean_check_passes(tmp_path, capsys):
    out = _generate(tmp_path, [_repo(tmp_path, "repo_a", "aaaaaaaa-1")])
    assert main(["scorecard", "--check", "--out", str(out)]) == 0
    assert "inputs unchanged since generation" in capsys.readouterr().out


def test_changed_ledger_input_fails_check_and_names_the_repo(
        tmp_path, capsys):
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    out = _generate(tmp_path, [repo])
    with open(repo / ".claude" / "ctx" / "checkpoints.jsonl", "a",
              encoding="utf-8") as f:
        f.write(json.dumps({"session": "new", "stats": {}}) + "\n")
    assert main(["scorecard", "--check", "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert "repo_a" in err and "ledger inputs changed" in err


def test_changed_cohort_config_fails_check(tmp_path, capsys):
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    other = _repo(tmp_path, "repo_b", "bbbbbbbb-1")
    out = _generate(tmp_path, [repo])
    save_cohort([str(repo), str(other)], str(out))   # population changed
    assert main(["scorecard", "--check", "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert "cohort config changed" in err
    assert "repo_b" in err          # the added repo is named as missing


def test_missing_latest_fails_check(tmp_path, capsys):
    assert main(["scorecard", "--check", "--out", str(tmp_path)]) == 1
    assert "no readable scorecard" in capsys.readouterr().err


def test_pre_v2_latest_fails_check_as_stale(tmp_path, capsys):
    (tmp_path / "scorecard-latest.json").write_text(
        json.dumps({"schema": "ctxpack-scorecard/v1", "repos": []}),
        encoding="utf-8")
    assert main(["scorecard", "--check", "--out", str(tmp_path)]) == 1
    assert "predates self-verification" in capsys.readouterr().err


def test_external_cohort_entry_is_unmeasured_not_fabricated(tmp_path):
    """A field-report deployment with no local ledger joins the cohort
    population as external_unmeasured — no fake path, no zeros."""
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    card = build_scorecard(
        [str(repo)],
        external=[{"name": "OntoWiz", "note": "field-report deployment"}])
    rows = {r["repo"]: r for r in card["repos"]}
    assert rows["OntoWiz"]["status"] == "external_unmeasured"
    assert "inputs" not in rows["OntoWiz"]
    assert card["cohort"]["repos_measured"] == 1
    assert card["cohort"]["repos_unmeasured"] == 1
    assert card["cohort"]["repos_excluded"] == 0
    assert card["cohort"]["repos_total"] == 2
    assert card["schema"] == "ctxpack-scorecard/v2"


def test_denominators_partition_all_statuses(tmp_path):
    """measured + unmeasured + excluded == total, with a missing path
    excluded rather than silently dropped."""
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    quiet = tmp_path / "quiet"
    (quiet / ".claude").mkdir(parents=True)       # onboarded, no data
    gone = tmp_path / "not_there"                 # path missing
    card = build_scorecard([str(repo), str(quiet), str(gone)],
                           external=[{"name": "OntoWiz"}])
    c = card["cohort"]
    assert c["repos_measured"] == 1
    assert c["repos_unmeasured"] == 2             # quiet + external
    assert c["repos_excluded"] == 1               # missing path
    assert (c["repos_measured"] + c["repos_unmeasured"]
            + c["repos_excluded"]) == c["repos_total"] == 4
    statuses = {r["repo"]: r["status"] for r in card["repos"]}
    assert statuses["not_there"] == "path_missing"


def test_external_entry_missing_from_latest_fails_check(tmp_path, capsys):
    """Adding OntoWiz to the cohort config makes the previous artifact
    stale — the population change must force a regeneration."""
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    out = _generate(tmp_path, [repo])
    cfg_path = out / "cohort.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["external"] = [{"name": "OntoWiz"}]
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    assert main(["scorecard", "--check", "--out", str(out)]) == 1
    assert "OntoWiz" in capsys.readouterr().err


def test_save_cohort_preserves_external_entries(tmp_path):
    out = tmp_path / "cards"
    out.mkdir()
    (out / "cohort.json").write_text(json.dumps(
        {"repos": ["a"], "external": [{"name": "OntoWiz"}]}) + "\n",
        encoding="utf-8")
    save_cohort(["a", "b"], str(out))
    cfg = json.loads((out / "cohort.json").read_text(encoding="utf-8"))
    assert cfg["repos"] == ["a", "b"]
    assert cfg["external"] == [{"name": "OntoWiz"}]
    assert load_cohort(str(out)) == ["a", "b"]


def test_duplicate_and_aliased_repo_paths_are_a_controlled_failure(
        tmp_path, capsys):
    """A repo listed twice — including under a case-variant spelling on
    Windows — would be double-counted. Generation refuses."""
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    out = tmp_path / "cards"
    rc = main(["scorecard", "--repos", str(repo), str(repo).upper(),
               "--out", str(out)])
    assert rc == 1
    assert "canonical-path collision" in capsys.readouterr().err


def test_malformed_cohort_config_is_a_controlled_failure(
        tmp_path, capsys):
    out = tmp_path / "cards"
    out.mkdir()
    (out / "cohort.json").write_text(
        json.dumps({"repos": "not-a-list",
                    "external": [{"name": "X"}, {"name": "X"}]}) + "\n",
        encoding="utf-8")
    assert main(["scorecard", "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert "'repos' must be a list" in err
    assert "duplicate external deployment id" in err
    # --check on the same malformed config: controlled stale, no crash
    (out / "scorecard-latest.json").write_text(json.dumps(
        {"schema": "ctxpack-scorecard/v2", "repos": [],
         "cohort_config_sha256": None}), encoding="utf-8")
    assert main(["scorecard", "--check", "--out", str(out)]) == 1
    assert "cohort config invalid" in capsys.readouterr().err


def test_malformed_latest_shape_is_a_controlled_failure(tmp_path, capsys):
    (tmp_path / "scorecard-latest.json").write_text(json.dumps(
        {"schema": "ctxpack-scorecard/v2", "repos": "nope"}),
        encoding="utf-8")
    assert main(["scorecard", "--check", "--out", str(tmp_path)]) == 1
    assert "not a list of objects" in capsys.readouterr().err


def test_fingerprints_carry_file_states_not_just_hashes(tmp_path):
    """Absent and unreadable are different claims; a missing ledger
    file is recorded as absent, never conflated into one None."""
    from ctxpack.agent.scorecard import repo_input_fingerprint
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    fp = repo_input_fingerprint(str(repo))
    assert fp["checkpoints_state"] == "present"
    assert fp["injections_state"] == "absent"
    assert fp["injections_jsonl"] is None
    assert len(fp["fingerprint"]) == 64


def test_check_message_claims_freshness_not_verification(tmp_path, capsys):
    """The guarantee is input freshness — metrics are not recomputed
    and the capture block is outside the fingerprints. The success
    message must say exactly that and no more."""
    out = _generate(tmp_path, [_repo(tmp_path, "repo_a", "aaaaaaaa-1")])
    assert main(["scorecard", "--check", "--out", str(out)]) == 0
    msg = capsys.readouterr().out
    assert "inputs unchanged since generation" in msg
    assert "metrics are not recomputed" in msg
    assert "capture-block numbers are outside this check" in msg


def test_verify_latest_covers_regenerated_cohort_flow(tmp_path):
    """The whole loop: generate → verify ok → mutate input → verify
    stale → regenerate → verify ok again."""
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    out = _generate(tmp_path, [repo])
    ok, findings = verify_latest(str(out))
    assert ok and findings == []
    with open(repo / ".claude" / "ctx" / "checkpoints.jsonl", "a",
              encoding="utf-8") as f:
        f.write(json.dumps({"session": "new", "stats": {}}) + "\n")
    ok, findings = verify_latest(str(out))
    assert not ok and findings
    assert main(["scorecard", "--out", str(out)]) == 0   # regenerate
    ok, findings = verify_latest(str(out))
    assert ok and findings == []
