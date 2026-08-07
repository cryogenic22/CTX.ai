"""E-6 ingest redaction (Loop 4a, PF-12): secrets are replaced with
TYPE-ONLY markers between transcript normalization and extraction, so
no fact value, literal, gist, or persistent write can carry one.
Fail-closed: a scanner crash aborts the checkpoint — an unscanned
transcript is never persisted."""

import json

import pytest

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.transcript_parser import parse_transcript
from ctxpack.core.redaction import redact, redact_tree, scan


# ── pattern unit coverage: type-only, never a fingerprint ──

@pytest.mark.parametrize("secret,label", [
    ("AKIAIOSFODNN7EXAMPLE", "aws-access-key-id"),
    ("ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345", "github-token"),
    ("xoxb-1234567890-abcdefghijkl", "slack-token"),
    ("sk-proj-abcdefghijklmnopqrstuvwxyz123456", "sk-api-key"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9P", "jwt"),
    ("Bearer abcdefghijklmnopqrstuvwx", "bearer-token"),
])
def test_secret_types_redact_type_only(secret, label):
    out, counts = redact(f"deploy failed with {secret} in the log")
    assert secret not in out
    assert f"[REDACTED:{label}]" in out
    assert counts[label] == 1
    # policy: no hash fingerprints — a low-entropy secret is guessable
    # from a short unsalted hash
    assert ":" not in out.split(f"[REDACTED:{label}]")[0][-1:]
    assert f"{label}:" not in out


def test_private_key_block_redacts_even_unterminated():
    key = ("-----BEGIN RSA PRIVATE KEY-----\n"
           "MIIEowIBAAKCAQEA7bq0\nmore\n"
           "-----END RSA PRIVATE KEY-----")
    out, counts = redact(f"here is the key\n{key}\nafter")
    assert "MIIEowIBAAKCAQEA7bq0" not in out
    assert counts["private-key-block"] == 1
    truncated = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA7bq0"
    out2, _ = redact(truncated)
    assert "MIIEowIBAAKCAQEA7bq0" not in out2


def test_url_credentials_redact_but_keep_the_url_shape():
    out, counts = redact("push to https://kapil:hunter2secret@github.com/x/y")
    assert "hunter2secret" not in out
    assert counts["url-credentials"] == 1
    assert "https://" in out and "@github.com/x/y" in out


def test_secret_assignment_redacts_and_bounds_false_positives():
    out, counts = redact('config: api_key = "Zx9k2mPq8vLw4njR"')
    assert "Zx9k2mPq8vLw4njR" not in out
    assert counts["secret-assignment"] == 1
    # prose, placeholders and env references stay untouched
    for benign in ("auth: optional", "token = $GITHUB_TOKEN",
                   "password: <your-password-here>",
                   "secret: {{template}}", "token = estimator"):
        got, c = redact(benign)
        assert got == benign, benign
        assert c == {}


def test_redact_is_idempotent_and_scan_matches():
    text = "key AKIAIOSFODNN7EXAMPLE and ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345"
    once, _ = redact(text)
    twice, counts2 = redact(once)
    assert twice == once and counts2 == {}
    assert scan(text) == ["aws-access-key-id", "github-token"]
    assert scan(once) == []


def test_redact_tree_walks_values_not_keys():
    obj = {"password": "not-a-value-here",
           "content": [{"type": "text",
                        "text": "token: Zx9k2mPq8vLw4njR"},
                       "AKIAIOSFODNN7EXAMPLE"]}
    out, counts = redact_tree(obj)
    assert "password" in out                      # keys are schema
    assert "Zx9k2mPq8vLw4njR" not in json.dumps(out)
    assert "AKIAIOSFODNN7EXAMPLE" not in json.dumps(out)
    assert counts["secret-assignment"] == 1
    assert counts["aws-access-key-id"] == 1


# ── the boundary: normalization → REDACT → extraction ──

def _secret_transcript(tmp_path, sid="redact11-0000"):
    rows = [
        {"type": "user", "sessionId": sid, "uuid": "u1",
         "message": {"content":
                     "Deploy with AKIAIOSFODNN7EXAMPLE. "
                     "Do not commit the key."}},
        {"type": "assistant", "sessionId": sid, "uuid": "u2",
         "message": {"content": [{"type": "text", "text":
                     "Decision: rotate ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345 "
                     "because it leaked into the log."}]}},
    ]
    path = tmp_path / "secret.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    return str(path)


def test_no_secret_reaches_any_persistent_write(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_secret_transcript(tmp_path), str(out),
                   as_of="2026-08-07")
    for f in out.rglob("*"):
        if f.is_file():
            body = f.read_text(encoding="utf-8", errors="replace")
            assert "AKIAIOSFODNN7EXAMPLE" not in body, f.name
            assert "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345" not in body, f.name
    row = json.loads((out / "checkpoints.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])
    assert row["stats"]["redactions"] >= 2
    assert row["stats"]["redaction_types"]["aws-access-key-id"] == 1


def test_redacted_marker_is_not_banked_as_a_literal(tmp_path):
    parsed = parse_transcript(_secret_transcript(tmp_path))
    values = [f.value for e in parsed.corpus.entities for f in e.fields]
    assert not any("AKIAIOSFODNN7EXAMPLE" in v for v in values)
    assert not any("ghp_AbCdEf" in v for v in values)
    # the decision itself survives, with the token replaced type-only
    decisions = [v for v in values if "rotate" in v]
    assert decisions and "[REDACTED:github-token]" in decisions[0]


def test_scanner_crash_fails_closed_nothing_persisted(tmp_path, monkeypatch):
    def boom(obj, counts=None):
        raise RuntimeError("scanner exploded")

    monkeypatch.setattr("ctxpack.core.redaction.redact_tree", boom)
    out = tmp_path / "ctx"
    with pytest.raises(Exception):
        run_checkpoint(_secret_transcript(tmp_path), str(out),
                       as_of="2026-08-07")
    assert not (out / "checkpoints.jsonl").exists()
    assert not list(out.glob("session-*.ctx")) if out.exists() else True


# ── the egress boundary: outgoing scan before emission (PF-14) ──

def _hook_repo(tmp_path, monkeypatch):
    import json as _json

    from ctxpack.agent.checkpoint import _claude_project_dir_name

    repo = tmp_path / "repo"
    home = tmp_path / "home"
    (home / "projects" / _claude_project_dir_name(str(repo))).mkdir(
        parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    out = repo / ".claude" / "ctx"
    rows = [
        {"type": "user", "sessionId": "cleanpr1-0000", "uuid": "u1",
         "message": {"content": "Ship the release notes."}},
        {"type": "assistant", "sessionId": "cleanpr1-0000", "uuid": "u2",
         "message": {"content": [{"type": "text", "text":
                     "Decision: tag v2 because the fix landed."}]}},
    ]
    path = tmp_path / "clean.jsonl"
    path.write_text("\n".join(_json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    run_checkpoint(str(path), str(out), as_of="2026-08-07")
    return repo, out


def test_outgoing_scan_redacts_a_secret_that_reached_the_ledger(
        tmp_path, monkeypatch, capsys):
    """Defense in depth: old ledgers predate ingest redaction. A secret
    sitting in a banked gist must not reach the model."""
    import io
    import json as _json

    from ctxpack.agent.injection_log import read_injections
    from ctxpack.cli.main import main

    repo, out = _hook_repo(tmp_path, monkeypatch)
    gist_path = out / "latest-gist.md"
    gist_path.write_text(
        gist_path.read_text(encoding="utf-8")
        + "\n- old row with AKIAIOSFODNN7EXAMPLE banked pre-E6\n",
        encoding="utf-8")

    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(
        {"cwd": str(repo), "session_id": "egress11-0000"})))
    assert main(["hook", "session-start", "--out", str(out)]) == 0
    emitted = _json.loads(capsys.readouterr().out)["hookSpecificOutput"][
        "additionalContext"]
    assert "AKIAIOSFODNN7EXAMPLE" not in emitted
    assert "[REDACTED:aws-access-key-id]" in emitted
    row = read_injections(str(out))[-1]
    assert row["outcome"] == "injected"
    assert row["outgoing_redactions"] >= 1


def test_outgoing_scan_crash_emits_nothing_and_records_failed(
        tmp_path, monkeypatch, capsys):
    """A scan crash must never present as a healthy empty result: no
    memory is emitted and the receipt says failed, with the error."""
    import io
    import json as _json

    from ctxpack.agent.injection_log import read_injections
    from ctxpack.cli.main import main

    repo, out = _hook_repo(tmp_path, monkeypatch)

    def boom(text):
        raise RuntimeError("egress scanner exploded")

    monkeypatch.setattr("ctxpack.core.redaction.redact", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(
        {"cwd": str(repo), "session_id": "egress22-0000"})))
    assert main(["hook", "session-start", "--out", str(out)]) == 0
    assert capsys.readouterr().out == ""          # nothing emitted
    row = read_injections(str(out))[-1]
    assert row["outcome"] == "failed"
    assert "outgoing scan failed" in row["error"]
