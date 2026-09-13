"""Finding 6 (P1, 2026-08-23): final-serialization egress scan on
every agent-facing session-read surface — CLI `session
resume|recall|why|timeline|decisions|literals|stats` and the MCP
twins. A pre-E6 ledger carrying raw secrets must not emit one raw
byte through any of them, benign content must survive untouched, and
a scanner failure must emit NOTHING but the stable code.

All adversarial tests here are RED on `c7f69de`: the parent emitted
the planted secrets verbatim (its own PF-17 gap pin proved it)."""

import io
import json

import pytest

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.cli.main import main

SECRET = "AKIAIOSFODNN7EXAMPLE"
SECRET2 = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345"
BENIGN = "retry with backoff because the cap is 40 req/min"


def _poisoned_ledger(tmp_path):
    """A pre-E6-style ledger: raw corpus secrets sit in the banked
    .ctx (as a literal value), the session gist, and latest-gist.md —
    exactly what ingest redaction now prevents but old ledgers carry."""
    sid = "poisoned-0000"
    rows = [
        {"type": "user", "sessionId": sid, "uuid": "u1",
         "message": {"content": "Ship it. Do not skip the review."}},
        {"type": "assistant", "sessionId": sid, "uuid": "u2",
         "message": {"content": [{"type": "text", "text":
                     f"Decision: {BENIGN}; pin commit plainval99."}]}},
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    out = tmp_path / "ctx"
    run_checkpoint(str(path), str(out), as_of="2026-08-23")
    # simulate the legacy ledger: swap a banked literal for a raw secret
    for name in (f"session-{sid[:8]}.ctx", f"session-{sid[:8]}-gist.md",
                 "latest-gist.md"):
        f = out / name
        f.write_text(f.read_text(encoding="utf-8").replace(
            "plainval99", SECRET), encoding="utf-8")
    gist = out / "latest-gist.md"
    gist.write_text(gist.read_text(encoding="utf-8")
                    + f"\n- legacy row: pat {SECRET2} banked pre-E6\n",
                    encoding="utf-8")
    return out, sid


# ── CLI surfaces ──

@pytest.mark.parametrize("argv", [
    ["resume"],
    ["recall"],
    ["recall", SECRET],
    ["timeline"],
    ["decisions"],
    ["literals"],
    ["why", SECRET],
    ["stats"],
])
def test_cli_session_reads_emit_no_raw_secret(tmp_path, capsys, argv):
    """Finding 6 acceptance (b): every CLI session read on a poisoned
    legacy ledger emits zero raw secret bytes. RED on c7f69de."""
    out, _sid = _poisoned_ledger(tmp_path)
    rc = main(["session", *argv, "--ledger", str(out)])
    printed = capsys.readouterr().out
    assert rc == 0
    assert SECRET not in printed, argv
    assert SECRET2 not in printed, argv


def test_cli_resume_redacts_the_gist_and_keeps_benign_content(
        tmp_path, capsys):
    """The regression test that REPLACES the c7f69de documented-gap
    pin: the gap is closed — resume redacts the legacy secret
    type-only and the benign decision text survives byte-identical
    (no over-redaction)."""
    out, _sid = _poisoned_ledger(tmp_path)
    assert main(["session", "resume", "--ledger", str(out)]) == 0
    printed = capsys.readouterr().out
    assert SECRET not in printed and SECRET2 not in printed
    assert "[REDACTED:" in printed          # scanned, not emptied
    assert BENIGN in printed                # benign control intact


def test_cli_scanner_failure_emits_nothing_but_the_stable_code(
        tmp_path, capsys, monkeypatch):
    """Finding 6 acceptance (a), fail-closed: if the scanner cannot
    run, no payload byte is emitted — stdout is empty and stderr
    carries egress_scan_failed. RED on c7f69de (no scan existed to
    fail)."""
    out, _sid = _poisoned_ledger(tmp_path)

    def boom(text):
        raise RuntimeError("scanner exploded")

    monkeypatch.setattr("ctxpack.core.redaction.redact", boom)
    rc = main(["session", "resume", "--ledger", str(out)])
    printed = capsys.readouterr()
    assert rc == 1
    assert printed.out == ""                        # nothing emitted
    assert "egress_scan_failed" in printed.err
    assert SECRET not in printed.err


# ── MCP twins ──

def test_mcp_session_read_tools_are_all_enrolled():
    """The mandated surface, pinned: removing a tool from the scan set
    fails here."""
    from ctxpack.integrations.mcp_server import SESSION_READ_TOOLS
    assert SESSION_READ_TOOLS == {
        "ctx/session_recall", "ctx/session_timeline",
        "ctx/session_decisions", "ctx/why", "ctx/graph_query",
        "ctx/session_literals", "ctx/resume",
    }


def test_mcp_twins_emit_no_raw_secret_through_the_boundary(tmp_path):
    """Finding 6 acceptance (b), MCP side: each session-read handler's
    RAW output on the poisoned ledger does carry the secret (proving
    the scan at the boundary does real work), and the boundary wrapper
    strips it for every enrolled tool. RED on c7f69de: no boundary
    scan existed."""
    from ctxpack.integrations import mcp_server as m

    out, _sid = _poisoned_ledger(tmp_path)
    args = {"ledger_dir": str(out), "key": SECRET, "query": "",
            "op": "neighbors", "entity": "DECISION"}
    raw_hits = 0
    for name in sorted(m.SESSION_READ_TOOLS):
        raw = m._HANDLERS[name](dict(args))
        if SECRET in raw or SECRET2 in raw:
            raw_hits += 1
        safe = m.scanned_session_result(name, raw)
        assert SECRET not in safe, name
        assert SECRET2 not in safe, name
    assert raw_hits >= 1   # the scan is load-bearing, not decorative


def test_mcp_scanner_failure_returns_stable_code_only(monkeypatch):
    """Fail-closed on the MCP side: scanner crash → the stable code,
    never the unscanned payload."""
    from ctxpack.integrations.mcp_server import scanned_session_result

    def boom(text):
        raise RuntimeError("scanner exploded")

    monkeypatch.setattr("ctxpack.core.redaction.redact", boom)
    got = json.loads(scanned_session_result(
        "ctx/resume", f"payload with {SECRET}"))
    assert got == {"error": "egress_scan_failed", "tool": "ctx/resume"}


# ── the shared choke point itself ──

def test_scan_out_is_fail_closed_and_type_only(monkeypatch):
    from ctxpack.agent.egress import EgressError, scan_out

    safe = scan_out(f"creds {SECRET} in env")
    assert SECRET not in safe and "[REDACTED:" in safe

    def boom(text):
        raise ValueError("no scanner")

    monkeypatch.setattr("ctxpack.core.redaction.redact", boom)
    with pytest.raises(EgressError):
        scan_out("anything")


# ── RF2 (Codex Finding 2): CLI session-read FAILURES are bounded too ──

@pytest.mark.parametrize("action,target", [
    ("stats", "session_stats"),
    ("resume", "session_resume"),
    ("recall", "load_session"),
    ("timeline", "load_session"),
    ("decisions", "load_session"),
    ("literals", "load_session"),
    ("graph", "load_session"),
    ("why", "session_why_across"),
])
def test_rf2_cli_read_failure_emits_bounded_code_no_secret(
        tmp_path, capsys, monkeypatch, action, target):
    """RF2 (P1): a session-read failure whose exception text embeds a
    secret (the reviewer's probe was a `ParseError(secret)` from a
    poisoned legacy .ctx) emits a stable bounded code ONLY — the secret
    reaches neither stdout nor stderr, rc=1. RED on a5f31b8: the error
    escaped `_emit` (success-only) and `_run` printed the raw text."""
    from ctxpack.core.errors import ParseError

    def boom(*a, **k):
        raise ParseError(SECRET)

    monkeypatch.setattr(f"ctxpack.agent.session_reader.{target}", boom)
    out = tmp_path / "ctx"
    out.mkdir()
    # Put the positional (key) directly after the action, BEFORE --ledger:
    # on Python 3.10 argparse cannot match a positional that is split from
    # its sibling by an option-with-value (`session why --ledger X key` ->
    # "unrecognized arguments"), a limitation lifted in 3.11. This order
    # parses identically on all supported Pythons; the RF2 assertions below
    # (bounded code, no secret, rc=1) are unchanged.
    argv = ["session", action]
    if action in ("why", "graph"):
        argv.append("somekey")
    argv += ["--ledger", str(out)]
    rc = main(argv)
    cap = capsys.readouterr()
    assert rc == 1
    assert SECRET not in cap.out and SECRET not in cap.err, (action, cap.err)
    assert "session_read_failed" in cap.err


def test_rf2_scanner_failure_on_success_path_withholds_output(
        tmp_path, capsys, monkeypatch):
    """RF2 (a): a scanner failure on an otherwise-successful read emits
    nothing but the stable code (the _emit fail-closed path)."""
    out, _sid = _poisoned_ledger(tmp_path)

    def boom(text):
        raise RuntimeError("scanner down")

    monkeypatch.setattr("ctxpack.core.redaction.redact", boom)
    rc = main(["session", "resume", "--ledger", str(out)])
    cap = capsys.readouterr()
    assert rc == 1
    assert cap.out == ""
    assert SECRET not in cap.err
    assert "egress_scan_failed" in cap.err


def test_rf2_benign_success_and_exit_codes_unchanged(tmp_path, capsys):
    """RF2 (c): the success path still returns 0 and emits benign
    content; a usage error still returns its controlled code."""
    out, _sid = _poisoned_ledger(tmp_path)
    assert main(["session", "decisions", "--ledger", str(out)]) == 0
    assert capsys.readouterr().out.strip() != ""
    # usage error (missing key) stays a controlled nonzero, no traceback
    assert main(["session", "why", "--ledger", str(out)]) == 1
    assert "needs a key" in capsys.readouterr().err
