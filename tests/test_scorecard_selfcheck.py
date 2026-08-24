"""Self-verifying scorecards (Loop 2, preflight backlog PF-02).

A "latest" scorecard must be verifiable against the inputs it was
computed from: cohort-config sha + per-repo ledger fingerprints.
`ctxpack scorecard --check` exits nonzero when latest is stale, missing
or predates self-verification, so a dashboard can never quietly present
an old population as current. All fixtures synthetic.
"""

import json

import pytest

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
    assert card["schema"] == "ctxpack-scorecard/v3"


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


def test_v3_artifact_carries_no_machine_absolute_paths(tmp_path):
    """PF-16b forward guard: no committed artifact byte may identify
    the machine — the repo's absolute path must not appear anywhere in
    the generated scorecard (rows carry the basename alias only)."""
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    out = _generate(tmp_path, [repo])
    body = (out / "scorecard-latest.json").read_text(encoding="utf-8")
    assert str(repo) not in body
    assert str(tmp_path) not in body
    card = json.loads(body)
    assert card["repos"][0]["repo"] == "repo_a"
    assert "path" not in card["repos"][0]
    # cohort.json IS the sanctioned home for the machine paths
    cohort = (out / "cohort.json").read_text(encoding="utf-8")
    assert str(repo).replace("\\", "\\\\") in cohort or str(repo) in cohort


def test_alias_collision_is_a_controlled_failure(tmp_path, capsys):
    """PF-16b: two distinct repos sharing a basename cannot be joined
    by alias — generation refuses rather than producing an artifact
    --check cannot verify."""
    a = _repo(tmp_path / "siteA", "repo_a", "aaaaaaaa-1")
    b = _repo(tmp_path / "siteB", "repo_a", "bbbbbbbb-1")
    rc = main(["scorecard", "--repos", str(a), str(b),
               "--out", str(tmp_path / "cards")])
    assert rc == 1
    assert "alias collision" in capsys.readouterr().err


def test_legacy_v2_artifact_still_verifies_by_its_own_rule(tmp_path):
    """Regression pin (self-identified): the committed pre-PF-16b
    artifacts are immutable and carry machine paths in rows — the v2
    branch of verify_latest keeps checking them exactly as written,
    fresh AND stale both detectable."""
    from ctxpack.agent.scorecard import (
        cohort_config_sha256,
        repo_input_fingerprint,
    )
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    out = tmp_path / "cards"
    out.mkdir()
    save_cohort([str(repo)], str(out))
    artifact = {"schema": "ctxpack-scorecard/v2",
                "cohort_config_sha256": cohort_config_sha256(str(out)),
                "repos": [{"repo": "repo_a", "path": str(repo),
                           "status": "active",
                           "inputs": repo_input_fingerprint(str(repo))}]}
    (out / "scorecard-latest.json").write_text(
        json.dumps(artifact), encoding="utf-8")
    ok, findings = verify_latest(str(out))
    assert ok and findings == []
    with open(repo / ".claude" / "ctx" / "checkpoints.jsonl", "a",
              encoding="utf-8") as f:
        f.write(json.dumps({"session": "new", "stats": {}}) + "\n")
    ok, findings = verify_latest(str(out))
    assert not ok
    assert any("repo_a" in f and "ledger inputs changed" in f
               for f in findings)


def test_v3_without_cohort_config_is_unverifiable_not_fresh(tmp_path):
    """PF-16b can-fail: v3 rows carry aliases only, so with no
    cohort.json the per-repo inputs cannot be re-derived — that must
    read stale, never silently fresh."""
    from ctxpack.agent.scorecard import build_scorecard, write_scorecard
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    out = tmp_path / "cards"
    write_scorecard(build_scorecard([str(repo)]), str(out))
    ok, findings = verify_latest(str(out))
    assert not ok
    assert any("cannot be re-derived" in f for f in findings)


def test_f5_external_note_never_enters_the_artifact(tmp_path):
    """Finding 5 (P2): external[].note is local-config free text — it
    stays in cohort.json and never reaches a publishable row. RED on
    parent: the note (here carrying a machine path) was copied
    verbatim into the v3 artifact."""
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    card = build_scorecard(
        [str(repo)],
        external=[{"name": "OntoWiz",
                   "note": "lives at C:/Users/kapil/private"}])
    rows = {r["repo"]: r for r in card["repos"]}
    assert "note" not in rows["OntoWiz"]
    assert "kapil" not in json.dumps(card)


def test_rf3_audit_reuses_the_one_strict_matcher():
    """RF3 (Codex Finding 3, P1): the scorecard audit now delegates to
    the SAME strict matcher as the eval-report gate — the weak
    /home+/Users-only copy is gone. Pins the full reviewer control
    corpus: /tmp, /var, /workspace, /root, /guides, Unicode POSIX, both
    UNC styles, drive/MSYS, file://, URL-smuggling, and owner identity
    are all caught; HTTPS paths and benign scorecard content stay
    clean. RED on 6ce11a1: /tmp, /var, /root, /workspace, forward-UNC,
    and owner identity returned []."""
    from ctxpack.agent.scorecard import audit_artifact_bytes as a
    # POSIX roots the weak matcher missed
    for p in ("/tmp/run", "/var/tmp/x", "/workspace/run", "/root/.ssh",
              "/guides/section-1/", "/etc/passwd", "/usr/local/bin"):
        assert "POSIX absolute path" in a(p), p
    assert "POSIX absolute path" in a("/" + "\u6570\u636e" + "/private")
    # both UNC styles, drive (both slashes / MSYS), file://
    assert "UNC path" in a("//server/share/evals")
    assert "UNC path" in a("\\\\fileserver\\share\\x")
    assert "drive-letter path" in a("C:\\Users\\x")
    assert "drive-letter path" in a("d:/scratch/run7")
    assert "file:// URI path" in a("file:///tmp/run")
    # owner identity, even inside an otherwise-URL string
    assert "identity" in a("logged by kapil")
    assert "identity" in a("https://h.example/x?u=kapil")
    # URL-smuggled raw path is caught on the raw string
    assert a(r"https://host.example/upload?path=C:\tmp\work")
    # benign controls stay clean (no over-redaction)
    for ok in ("https://example.com/artifact",
               "https://h.example/home/page", "https://x/tmp/y",
               "generated_at 2026-08-24T05:00:00+00:00",
               "accuracy/quality claims", "sha256 8f3a2b", "repo_a"):
        assert a(ok) == [], ok


def test_rf3_external_name_validated_as_identity(tmp_path, capsys):
    """RF3 (Finding 3b): a path-bearing external name is rejected as an
    identity — build_scorecard refuses at the source and cohort
    validation refuses at the CLI. RED on 6ce11a1: `/tmp/kapil/private`
    persisted into a row and audited clean."""
    from ctxpack.agent.scorecard import ArtifactPrivacyError, build_scorecard
    with pytest.raises(ArtifactPrivacyError):
        build_scorecard([], external=[{"name": "/tmp/kapil/private"}])
    # a plain identity is fine
    card = build_scorecard([], external=[{"name": "OntoWiz"}])
    assert card["repos"][0]["repo"] == "OntoWiz"
    # CLI cohort validation rejects it too
    out = tmp_path / "cards"
    out.mkdir()
    (out / "cohort.json").write_text(json.dumps(
        {"repos": [], "external": [{"name": "//server/share"}]}) + "\n",
        encoding="utf-8")
    assert main(["scorecard", "--out", str(out)]) == 1
    assert "not a plain identity" in capsys.readouterr().err


def test_f5_poisoned_artifact_write_is_refused(tmp_path):
    """Finding 5 defense-in-depth: if a machine path DOES reach the
    serialized card, the write refuses — controlled, nothing written."""
    from ctxpack.agent.scorecard import (
        ArtifactPrivacyError,
        write_scorecard,
    )
    card = {"schema": "ctxpack-scorecard/v3",
            "generated_at": "2026-08-23T00:00:00+00:00",
            "cohort": {}, "repos": [
                {"repo": "x", "status": "active",
                 "stray": "C:/Users/leaked/path"}]}
    out = tmp_path / "cards"
    with pytest.raises(ArtifactPrivacyError):
        write_scorecard(card, str(out))
    assert not list(out.glob("scorecard-*.json"))


def test_f5_local_vs_external_alias_collision_is_rejected(
        tmp_path, capsys):
    """Finding 5 acceptance (b): an external deployment named like a
    local repo alias shadows it — generation refuses. RED on parent:
    LOCAL_EXTERNAL_ALIAS_COLLISION_ACCEPTED=True."""
    repo = _repo(tmp_path, "repo_a", "aaaaaaaa-1")
    out = tmp_path / "cards"
    out.mkdir()
    (out / "cohort.json").write_text(json.dumps(
        {"repos": [str(repo)],
         "external": [{"name": "repo_a"}]}) + "\n", encoding="utf-8")
    assert main(["scorecard", "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert "alias collision" in err and "shadows" in err


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
