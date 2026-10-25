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


# ── TC-1/TC-2 (TM-1): the reviewer's exact bypass probes ──

@pytest.mark.parametrize("probe,gone", [
    ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI_K7MDENG_bPxRfiCYEXAMPLEKEY",
     "wJalrXUtnFEMI_K7MDENG_bPxRfiCYEXAMPLEKEY"),
    ("AWS_SESSION_TOKEN=FwoGZXIvYXdzEBYaDHRlc3R0b2tlbnZhbHVl",
     "FwoGZXIvYXdzEBYaDHRlc3R0b2tlbnZhbHVl"),
    ("GITHUB_FINE_GRAINED=github_pat_11AA22BB33CC44DD55EE66FF77GG88HH99II",
     "github_pat_11AA22BB33CC44DD55EE66FF77GG88HH99II"),
    ('DATABASE_PASSWORD="correct horse battery staple"',
     "correct horse battery staple"),
    ("AccountKey=8fjZk29QmPl3xWv7Tn5RbY1cS6dH4gA0",
     "8fjZk29QmPl3xWv7Tn5RbY1cS6dH4gA0"),
    ("//registry.npmjs.org/:_authToken=npm_9Zk2mPq8vLw4njRt5Yb3",
     "npm_9Zk2mPq8vLw4njRt5Yb3"),
    ("GITLAB_DEPLOY=glpat-Zx9k2mPq8vLw4njR",
     "glpat-Zx9k2mPq8vLw4njR"),
    ("maps_key: AIzaSyD9k2mPq8vLw4njRt5Yb3cS6dH4gA0xWv7",
     "AIzaSyD9k2mPq8vLw4njRt5Yb3cS6dH4gA0xWv7"),
])
def test_tc2_prefixed_and_quoted_whitespace_assignments_redact(probe, gone):
    out, counts = redact(f"deploy config:\n{probe}\ndone")
    assert gone not in out, probe
    assert counts, probe


def test_tc3_segment_matching_does_not_fire_on_substrings():
    """'oauth' contains 'auth' but is not a credential name; segment
    matching keeps the substring class benign."""
    for benign in ("oauth-provider = google-oauth2-service",
                   "authorization_docs = docs/authz-design.md",
                   "sort_key = created_at_desc"):
        got, c = redact(benign)
        assert got == benign, benign
        assert c == {}


def test_tc1_no_corpus_secret_survives_checkpoint_end_to_end(tmp_path):
    """TC-1: corpus secrets planted in user text, assistant text,
    tool_result content and tool_use input — zero occurrences in any
    persisted ledger file."""
    secrets = [
        "wJalrXUtnFEMI_K7MDENG_bPxRfiCYEXAMPLEKEY",
        "github_pat_11AA22BB33CC44DD55EE66FF77GG88HH99II",
        "correct horse battery staple",
        "glpat-Zx9k2mPq8vLw4njR",
    ]
    sid = "tcone111-0000"
    rows = [
        {"type": "user", "sessionId": sid, "uuid": "u1",
         "message": {"content":
                     f"Deploy now. AWS_SECRET_ACCESS_KEY={secrets[0]} "
                     "and do not commit it."}},
        {"type": "assistant", "sessionId": sid, "uuid": "u2",
         "message": {"content": [
             {"type": "text", "text":
              f"Decision: rotate GITHUB_FINE_GRAINED={secrets[1]} "
              "because it leaked."},
             {"type": "tool_use", "id": "t1", "name": "Bash",
              "input": {"command":
                        f'export DATABASE_PASSWORD="{secrets[2]}"'}}]}},
        {"type": "user", "sessionId": sid, "uuid": "u3",
         "message": {"content": [
             {"type": "tool_result", "is_error": True,
              "content": f"auth failed for GITLAB_DEPLOY={secrets[3]}"}]}},
    ]
    path = tmp_path / "corpus.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    out = tmp_path / "ctx"
    run_checkpoint(str(path), str(out), as_of="2026-08-09")
    for f in out.rglob("*"):
        if f.is_file():
            body = f.read_text(encoding="utf-8", errors="replace")
            for secret in secrets:
                assert secret not in body, (f.name, secret)


# ── TC-1 (re-review P1-4): full §6 corpus × content-position matrix ──

# Every entry of the PF-11 §6 normative corpus: (label, planted text,
# the secret bytes that must never survive).
_SIX_CORPUS = [
    ("aws-access-key-id", "creds AKIAIOSFODNN7EXAMPLE in env",
     "AKIAIOSFODNN7EXAMPLE"),
    ("aws-access-key-id-asia", "temp ASIAJQRSTUVWXYZ01234 issued",
     "ASIAJQRSTUVWXYZ01234"),
    ("aws-secret-prefixed",
     "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI_K7MDENG_bPxRfiCYEXAMPLEKEY",
     "wJalrXUtnFEMI_K7MDENG_bPxRfiCYEXAMPLEKEY"),
    ("aws-session-token",
     "AWS_SESSION_TOKEN=FwoGZXIvYXdzEBYaDHRlc3R0b2tlbnZhbHVl",
     "FwoGZXIvYXdzEBYaDHRlc3R0b2tlbnZhbHVl"),
    ("github-ghp", "pat ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345",
     "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345"),
    ("github-gho", "oauth gho_BcDeFgHiJkLmNoPqRsTuVwXyZ0123456",
     "gho_BcDeFgHiJkLmNoPqRsTuVwXyZ0123456"),
    ("github-ghu", "user gh token ghu_CdEfGhIjKlMnOpQrStUvWxYz01234567",
     "ghu_CdEfGhIjKlMnOpQrStUvWxYz01234567"),
    ("github-ghs", "server token ghs_DeFgHiJkLmNoPqRsTuVwXyZ012345678",
     "ghs_DeFgHiJkLmNoPqRsTuVwXyZ012345678"),
    ("github-ghr", "refresh ghr_EfGhIjKlMnOpQrStUvWxYz0123456789",
     "ghr_EfGhIjKlMnOpQrStUvWxYz0123456789"),
    ("github-pat-fine-grained",
     "github_pat_11AA22BB33CC44DD55EE66FF77GG88HH99II",
     "github_pat_11AA22BB33CC44DD55EE66FF77GG88HH99II"),
    ("gitlab-glpat", "deploy glpat-Zx9k2mPq8vLw4njR",
     "glpat-Zx9k2mPq8vLw4njR"),
    ("slack-xoxb", "bot xoxb-1234567890-abcdefghijkl",
     "xoxb-1234567890-abcdefghijkl"),
    ("sk-api-key", "openai sk-proj-abcdefghijklmnopqrstuvwxyz123456",
     "sk-proj-abcdefghijklmnopqrstuvwxyz123456"),
    ("jwt",
     "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
     "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9P",
     "eyJzdWIiOiIxMjM0NTY3ODkwIn0"),
    ("pem-private-key",
     "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA7bq0z9\n"
     "-----END RSA PRIVATE KEY-----",
     "MIIEowIBAAKCAQEA7bq0z9"),
    ("pem-truncated",
     "-----BEGIN RSA PRIVATE KEY-----\nMIIEowTRUNCATEDBYTES99",
     "MIIEowTRUNCATEDBYTES99"),
    ("bearer-token", "Authorization: Bearer abQR7stuvwxyz0123456789mn",
     "abQR7stuvwxyz0123456789mn"),
    ("url-credentials", "push https://kapil:hunter2secretpw@github.com/x/y",
     "hunter2secretpw"),
    ("postgres-connstring",
     "postgres://svcuser:pgSecret99word@db.internal:5432/app",
     "pgSecret99word"),
    ("mongodb-srv-connstring",
     "mongodb+srv://svcuser:moSecret99word@cluster0.example.net/db",
     "moSecret99word"),
    ("azure-accountkey", "AccountKey=8fjZk29QmPl3xWv7Tn5RbY1cS6dH4gA0",
     "8fjZk29QmPl3xWv7Tn5RbY1cS6dH4gA0"),
    ("gcp-aiza", "maps AIzaSyD9k2mPq8vLw4njRt5Yb3cS6dH4gA0xWv7",
     "AIzaSyD9k2mPq8vLw4njRt5Yb3cS6dH4gA0xWv7"),
    ("npm-authtoken",
     "//registry.npmjs.org/:_authToken=npm_9Zk2mPq8vLw4njRt5Yb3",
     "npm_9Zk2mPq8vLw4njRt5Yb3"),
    ("env-bare-uppercase-key", "DATA_KEY=Zx9k2mPq8vLw4njR",
     "Zx9k2mPq8vLw4njR"),
    ("env-prefixed-uppercase-key", "APP_SIGNING_KEY=vLw4njRt5Yb3cS6d",
     "vLw4njRt5Yb3cS6d"),
    ("env-secret-key-quoted-ws", 'X_SECRET_KEY="Zq8vLw4njRt5Yb3c pT7"',
     "Zq8vLw4njRt5Yb3c pT7"),
    ("env-password-quoted-ws",
     'PROD_DB_PASSWORD: "correct horse battery staple"',
     "correct horse battery staple"),
    # standalone bare *_SECRET (regression pin — the "secret" segment
    # already catches it; committed corpus previously covered the
    # class only in combination, reviewer count check 2026-08-09)
    ("env-secret", "APP_SECRET=Yb3cS6dH4gA0xWv7", "Yb3cS6dH4gA0xWv7"),
    ("env-passwd", "SVC_PASSWD=njRt5Yb3cS6dH4gA",
     "njRt5Yb3cS6dH4gA"),
    ("env-pwd", "APP_PWD=t5Yb3cS6dH4gA0xW", "t5Yb3cS6dH4gA0xW"),
    ("env-token", "CI_TOKEN=b3cS6dH4gA0xWv7T", "b3cS6dH4gA0xWv7T"),
    ("env-credential", "DB_CREDENTIAL=cS6dH4gA0xWv7Tn5",
     "cS6dH4gA0xWv7Tn5"),
    ("env-credentials", "SVC_CREDENTIALS=dH4gA0xWv7Tn5Yb3",
     "dH4gA0xWv7Tn5Yb3"),
]

_POSITIONS = ("user", "assistant", "tool_result", "tool_use")


def test_tc1_unit_every_corpus_entry_redacts_at_the_scanner():
    """Scanner-level sweep of the FULL §6 corpus. Mostly a regression
    pin for entries the scanner already caught; RED on the parent for
    the uppercase environment-style *_KEY entries (the reviewer's
    DATA_KEY bypass)."""
    for label, planted, secret in _SIX_CORPUS:
        out, counts = redact(planted)
        assert secret not in out, (label, out)
        assert counts, label


def _matrix_rows(sid, position):
    """One transcript per position: EVERY corpus entry planted in that
    position, each in its own turn, embedded in the shape that BANKS
    for that position (marker sentence, error content, described Bash
    command) — so an unredacted byte genuinely reaches the ledger
    rather than being dropped by extraction and passing vacuously."""
    rows = [{"type": "user", "sessionId": sid, "uuid": "u-lead",
             "message": {"content": "Start the security audit."}}]
    for i, (label, planted, _secret) in enumerate(_SIX_CORPUS):
        if position == "user":
            rows.append({"type": "user", "sessionId": sid,
                         "uuid": f"u{i}", "message": {"content":
                         f"Constraint: never commit {planted} "
                         "anywhere."}})
        elif position == "assistant":
            rows.append({"type": "assistant", "sessionId": sid,
                         "uuid": f"a{i}", "message": {"content": [
                             {"type": "text", "text":
                              f"Decision: rotate {planted} because "
                              f"the {label} leaked."}]}})
        elif position == "tool_result":
            rows.append({"type": "user", "sessionId": sid,
                         "uuid": f"t{i}", "message": {"content": [
                             {"type": "tool_result", "is_error": True,
                              "content":
                              f"auth failed for {label}: {planted}"}]}})
        else:  # tool_use input — banks only with a description
            rows.append({"type": "assistant", "sessionId": sid,
                         "uuid": f"c{i}", "message": {"content": [
                             {"type": "tool_use", "id": f"tu{i}",
                              "name": "Bash",
                              "input": {"description": f"plant {label}",
                                        "command": planted}}]}})
    return rows


@pytest.mark.parametrize("position", _POSITIONS)
def test_tc1_matrix_no_corpus_secret_reaches_ledger_or_emission(
        position, tmp_path, monkeypatch, capsys):
    """TC-1 as preregistered: every §6 corpus entry, planted in each
    content position, leaves ZERO secret bytes in any file under the
    ledger AND in the context emitted at session-start (ingest and
    egress share the scanner, so they shared the bypass — RED on the
    parent for the uppercase *_KEY entries)."""
    import io

    from ctxpack.agent.checkpoint import _claude_project_dir_name
    from ctxpack.cli.main import main

    repo = tmp_path / "repo"
    home = tmp_path / "home"
    (home / "projects" / _claude_project_dir_name(str(repo))).mkdir(
        parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    out = repo / ".claude" / "ctx"

    sid = f"tcmx{_POSITIONS.index(position)}000-0000"
    rows = _matrix_rows(sid, position)
    path = tmp_path / f"matrix-{position}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    run_checkpoint(str(path), str(out), as_of="2026-08-09")

    for f in out.rglob("*"):
        if f.is_file():
            body = f.read_text(encoding="utf-8", errors="replace")
            for label, _planted, secret in _SIX_CORPUS:
                assert secret not in body, (position, label, f.name)

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"cwd": str(repo), "session_id": f"emit{position[:4]}-0000"})))
    assert main(["hook", "session-start", "--out", str(out)]) == 0
    emitted = capsys.readouterr().out
    for label, _planted, secret in _SIX_CORPUS:
        assert secret not in emitted, (position, label)


def test_benign_name_span_does_not_swallow_a_secret_assignment():
    """RED on parent — found by the position matrix, not the unit
    sweep: when a benign name matches first (`azure-accountkey: ...`),
    its consumed value span must not swallow a secret assignment
    sitting inside it — the same consumption class as the
    line-boundary rule already documented on _ASSIGNMENT."""
    probe = ("auth failed for azure-accountkey: "
             "AccountKey=8fjZk29QmPl3xWv7Tn5RbY1cS6dH4gA0")
    out, counts = redact(probe)
    assert "8fjZk29QmPl3xWv7Tn5RbY1cS6dH4gA0" not in out
    assert counts["secret-assignment"] == 1
    # two levels of benign nesting rescan all the way down
    out2, c2 = redact("ctx: cfg: DB_PASSWORD=njRt5Yb3cS6dH4gA")
    assert "njRt5Yb3cS6dH4gA" not in out2
    assert c2["secret-assignment"] == 1


def test_secretlike_name_nested_quoted_assignment_fully_consumed():
    """RED on parent — found by the position matrix, not the unit
    sweep: with a secret-like OUTER name, `X: Y_KEY="quoted ws"` used
    to stop the value at the quote, redacting `Y_KEY=` and leaving
    the quoted payload behind."""
    probe = ('auth failed for env-secret-key-quoted-ws: '
             'X_SECRET_KEY="Zq8vLw4njRt5Yb3c pT7"')
    out, counts = redact(probe)
    assert "Zq8vLw4njRt5Yb3c pT7" not in out
    assert counts["secret-assignment"] == 1
    # the spaced nested form: the run ends in the separator itself
    probe2 = ('auth failed for env-password-quoted-ws: '
              'PROD_DB_PASSWORD: "correct horse battery staple"')
    out2, c2 = redact(probe2)
    assert "correct horse battery staple" not in out2
    assert c2["secret-assignment"] == 1
    # prose quotes after a complete value never get swallowed
    probe3 = 'reason: mismatch9 "the quoted excerpt stays"'
    out3, c3 = redact(probe3)
    assert out3 == probe3 and c3 == {}


def test_tc3_uppercase_key_fix_keeps_the_benign_bound():
    """Forward guard on the DATA_KEY fix: lowercase bare-key names and
    env/placeholder values stay untouched."""
    for benign in ("sort_key = created_at_desc",
                   "primary_key = user_id_hash",
                   "DATA_KEY=$VAULT_REF",
                   "KEY_ROTATION_DAYS=30",
                   "data_key = partition_by_day"):
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


def test_checkpoint_receipt_stamps_extractor_and_redaction_versions(
        tmp_path):
    """Re-review P2 (provenance receipts): extraction and scanning
    behavior changed (TM-1/TM-8/TM-4), so the versions must MOVE and
    the redaction version must be stamped into the checkpoint receipt
    — policy built on receipts has to know which scanner produced
    them. RED on parent: versions unbumped, redaction key absent."""
    from ctxpack.core import factid
    from ctxpack.core.redaction import REDACTION_VERSION

    out = tmp_path / "ctx"
    run_checkpoint(_secret_transcript(tmp_path), str(out),
                   as_of="2026-08-09")
    row = json.loads((out / "checkpoints.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])
    assert factid.EXTRACTOR_VERSION == "tp/1.5"
    assert REDACTION_VERSION == "redact/v2"
    assert row["extractor"] == factid.EXTRACTOR_VERSION
    assert row["redaction"] == REDACTION_VERSION


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
    assert row["error"] == "egress_scan_failed"   # TM-7: code, not text
    assert row["error_class"] == "runtime_error"  # category, not name


def test_tc13_exception_text_with_secret_never_reaches_the_receipt(
        tmp_path, monkeypatch, capsys):
    """TC-13 (TM-7): the injection journal is written where no scanner
    ever looks, so it must never receive free exception text — a
    crash whose message embeds a corpus secret produces a receipt
    carrying the stable code and bounded category ONLY. RED on parent:
    str(e) was persisted into the row."""
    import io
    import json as _json

    from ctxpack.agent.injection_log import read_injections
    from ctxpack.cli.main import main

    repo, out = _hook_repo(tmp_path, monkeypatch)
    secret = "AKIAIOSFODNN7EXAMPLE"

    def boom(text):
        raise RuntimeError(f"vault unreachable at https://u:{secret}@v")

    monkeypatch.setattr("ctxpack.core.redaction.redact", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(
        {"cwd": str(repo), "session_id": "tc13sess-0000"})))
    assert main(["hook", "session-start", "--out", str(out)]) == 0
    capsys.readouterr()
    row = read_injections(str(out))[-1]
    assert row["outcome"] == "failed"
    assert row["error"] == "egress_scan_failed"
    assert row["error_class"] == "runtime_error"
    body = (out / "injections.jsonl").read_text(encoding="utf-8")
    assert secret not in body


def test_tc13b_minted_class_name_with_secret_never_reaches_receipt(
        tmp_path, monkeypatch, capsys):
    """TC-13 companion (TM-7, second finding): a class NAME is
    caller-controlled text — type(secret, ...) mints an exception whose
    __name__ IS the secret and passes an isidentifier() check. The
    receipt must carry only the bounded category of its stdlib base.
    RED on parent: the class name was persisted verbatim."""
    import io
    import json as _json

    from ctxpack.agent.injection_log import read_injections
    from ctxpack.cli.main import main

    repo, out = _hook_repo(tmp_path, monkeypatch)
    secret = "AKIAIOSFODNN7EXAMPLE"
    evil = type(secret, (RuntimeError,), {})

    def boom(text):
        raise evil("scanner exploded")

    monkeypatch.setattr("ctxpack.core.redaction.redact", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(
        {"cwd": str(repo), "session_id": "tc13bses-0000"})))
    assert main(["hook", "session-start", "--out", str(out)]) == 0
    capsys.readouterr()
    row = read_injections(str(out))[-1]
    assert row["outcome"] == "failed"
    assert row["error"] == "egress_scan_failed"
    assert row["error_class"] == "runtime_error"   # base's category
    body = (out / "injections.jsonl").read_text(encoding="utf-8")
    assert secret not in body


def test_free_text_error_is_coerced_never_persisted(tmp_path):
    """TM-7 structural guard: a caller handing record_injection free
    text (here with a secret inside) gets `unknown_error` on the row —
    the journal cannot receive text through this API at all. RED on
    parent: the text landed verbatim."""
    import json as _json

    from ctxpack.agent.injection_log import (
        read_injections,
        record_injection,
    )

    record_injection(str(tmp_path / "ctx"), session_id="freetext-1",
                     context="", outcome="failed",
                     error="boom AKIAIOSFODNN7EXAMPLE happened")
    row = read_injections(str(tmp_path / "ctx"))[-1]
    assert row["error"] == "unknown_error"
    assert "AKIA" not in _json.dumps(row)


def test_tc17_checkpoint_hook_failure_leaks_no_secret_to_stderr(
        tmp_path, monkeypatch, capsys):
    """TC-17 (TM-14): a checkpoint-hook failure whose exception
    message embeds a corpus secret writes no secret bytes to stderr or
    any persisted file — hook stderr carries the stable code and the
    bounded category only. (This hook path creates no temp files, so
    there is nothing to sweep.) RED on parent: the raw exception text
    was printed."""
    import io
    import json as _json

    from ctxpack.cli.main import main

    secret = "AKIAIOSFODNN7EXAMPLE"
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    out = tmp_path / "ctx"

    def boom(*a, **k):
        raise RuntimeError(f"exploded while holding {secret}")

    monkeypatch.setattr("ctxpack.agent.checkpoint.run_checkpoint", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(
        {"cwd": str(tmp_path), "session_id": "tc17sess-0000",
         "transcript_path": str(transcript)})))
    assert main(["hook", "session-end", "--out", str(out)]) == 0
    err = capsys.readouterr().err
    assert secret not in err
    assert "checkpoint_failed" in err
    assert "runtime_error" in err
    if out.exists():
        for f in out.rglob("*"):
            if f.is_file():
                assert secret not in f.read_text(encoding="utf-8",
                                                 errors="replace")


def test_tc17b_minted_class_name_with_secret_never_reaches_stderr(
        tmp_path, monkeypatch, capsys):
    """TC-17 companion (TM-14): the stderr diagnostic shares the
    bounded classifier — a minted class whose __name__ embeds a secret
    prints as its base's category, because a class name is
    caller-controlled text exactly like a message. RED on parent:
    stderr carried type(e).__name__ verbatim."""
    import io
    import json as _json

    from ctxpack.cli.main import main

    secret = "AKIAIOSFODNN7EXAMPLE"
    evil = type(secret, (RuntimeError,), {})
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    out = tmp_path / "ctx"

    def boom(*a, **k):
        raise evil("exploded")

    monkeypatch.setattr("ctxpack.agent.checkpoint.run_checkpoint", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(
        {"cwd": str(tmp_path), "session_id": "tc17bses-0000",
         "transcript_path": str(transcript)})))
    assert main(["hook", "session-end", "--out", str(out)]) == 0
    err = capsys.readouterr().err
    assert secret not in err
    assert "checkpoint_failed" in err
    assert "runtime_error" in err


# ── TM-14 Finding 1 (2026-08-23): the remaining diagnostic surfaces
# share the one bounded classifier — backfill report rows, code-pack
# file warnings, and the MCP catch-all error payload ──

def test_backfill_failed_row_note_carries_category_not_exception_text(
        tmp_path, monkeypatch):
    """TM-14 (Finding 1): a backfill pack crash whose exception message
    and minted class name both embed a secret produces a report row
    whose note is the bounded category only. RED on parent: the note
    stored type(e).__name__ + str(e) verbatim."""
    import os as _os
    import time as _time

    from ctxpack.agent.backfill import run_backfill
    from ctxpack.agent.checkpoint import _claude_project_dir_name

    secret = "AKIAIOSFODNN7EXAMPLE"
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    tdir = home / "projects" / _claude_project_dir_name(str(repo))
    tdir.mkdir(parents=True)
    sid = "bfleak11-0000-0000-0000-000000000000"
    rows = [{"type": "user", "sessionId": sid, "uuid": "u1",
             "message": {"content": "Ship it."}}]
    path = tdir / f"{sid}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    when = _time.time() - 86400
    _os.utime(path, (when, when))

    evil = type(secret, (RuntimeError,), {})

    def boom(*a, **k):
        raise evil(f"exploded holding {secret}")

    monkeypatch.setattr("ctxpack.agent.backfill.run_checkpoint", boom)
    report = run_backfill(str(repo), str(repo / ".claude" / "ctx"),
                          as_of="2026-08-23", claude_home=str(home))
    assert [r.outcome for r in report] == ["failed"]
    assert report[0].detail == "runtime_error"
    assert secret not in report[0].detail


def test_code_pack_file_warning_carries_category_not_exception_text(
        tmp_path, monkeypatch):
    """TM-14 (Finding 1): a parser crash steered by a source file (a
    minted exception class named with a secret) produces a FileWarning
    whose message is the bounded category; the file field stays the
    actionable datum. RED on parent: message was class name + text."""
    # Exercises the code-packer, which needs the `code` extra (tree-sitter);
    # skip cleanly in the ordinary CI lane, runs in the `extras` lane.
    pytest.importorskip("tree_sitter")
    from ctxpack.core.code.pack import pack_codebase

    secret = "AKIAIOSFODNN7EXAMPLE"
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    evil = type(secret, (RuntimeError,), {})

    def boom(*a, **k):
        raise evil(f"parser held {secret}")

    monkeypatch.setattr("ctxpack.core.code.pack.parse_python", boom)
    pack = pack_codebase(tmp_path)
    warn = next(w for w in pack.warnings if w.file == "mod.py")
    assert warn.message == "runtime_error"
    assert secret not in json.dumps(
        [w.message for w in pack.warnings])


def test_mcp_catch_all_error_payload_carries_no_exception_text():
    """TM-14 (Finding 1): the MCP catch-all result is injected into
    the CALLING AGENT'S CONTEXT — it carries the stable code and
    bounded category only, never message text or a minted class name.
    RED on parent: the payload was f"{type(e).__name__}: {str(e)}"."""
    from ctxpack.integrations.mcp_server import tool_error_result

    secret = "AKIAIOSFODNN7EXAMPLE"
    evil = type(secret, (RuntimeError,), {})
    payload = json.loads(tool_error_result(
        "ctx_resume", evil(f"crashed with {secret}")))
    assert payload["error"] == "tool_failed"
    assert payload["tool"] == "ctx_resume"
    assert payload["error_class"] == "runtime_error"
    assert secret not in json.dumps(payload)
