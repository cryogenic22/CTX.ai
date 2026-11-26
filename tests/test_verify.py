"""Offline fixtures for ctxpack verify. No network."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ctxpack.agent.verify import render_json, render_markdown, verify
from ctxpack.cli.main import main

ROOT = Path(__file__).resolve().parents[1]
DECISION = (
    "Decision: enable the legacy billing bypass flag in production paths today"
)
CONSTRAINT = (
    "Constraint: never enable the legacy billing bypass flag in production paths"
)


def _git(root: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "Ctx Tester",
        "GIT_AUTHOR_EMAIL": "tester@example.com",
        "GIT_COMMITTER_NAME": "Ctx Tester",
        "GIT_COMMITTER_EMAIL": "tester@example.com",
        "GIT_AUTHOR_DATE": "2026-01-15T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-15T00:00:00Z",
    })
    proc = subprocess.run(
        ["git", *args], cwd=str(root), check=True, capture_output=True, env=env)
    return proc.stdout.decode("utf-8").strip()


def _init(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tester@example.com")
    _git(root, "config", "user.name", "Ctx Tester")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "core.autocrlf", "false")


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD")


def _section(name: str, fields: list[tuple[str, str]]) -> str:
    lines = [f"##{name}"]
    lines.extend(f"{key}:{value}" for key, value in fields)
    return "\n".join(lines)


def _ledger(ledger: Path, sections: list[str], events: str = "") -> None:
    ledger.mkdir()
    body = "§CTX v1.0 L2 DOMAIN:session-aaaaaaaa\n\n" + "\n\n".join(sections) + "\n"
    (ledger / "session-aaaaaaaa.ctx").write_text(body, encoding="utf-8", newline="\n")
    (ledger / "checkpoints.jsonl").write_text(
        '{"session": "aaaaaaaa"}\n', encoding="utf-8", newline="\n")
    if events:
        (ledger / "events.jsonl").write_text(events, encoding="utf-8", newline="\n")


def _range_repo(tmp_path: Path, message: str, touch: str = "README.md") -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    _write(repo, touch, "base\n")
    base = _commit(repo, "base")
    _write(repo, touch, "head\n")
    head = _commit(repo, message)
    return repo, f"{base}..{head}"


def _finding(report):
    assert len(report.findings) == 1, [
        (row.code, row.location, row.fact_id, row.message, row.evidence)
        for row in report.findings]
    return report.findings[0]


def test_unrecorded_marker(tmp_path: Path) -> None:
    repo, spec = _range_repo(
        tmp_path,
        "Decision: record the widget cutoff at the ledger boundary")
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    report = verify(spec, repo=repo, ledger_dir=ledger)
    row = _finding(report)
    head = spec.split("..", 1)[1]
    assert row.to_dict() == {
        "code": "UNRECORDED_MARKER",
        "evidence": "Decision: record the widget cutoff at the ledger boundary",
        "fact_id": None,
        "location": head,
        "message": "Decision marker is not recorded in the ledger",
        "severity": "warning",
    }
    assert report.exit_code == 0


def test_stale_identifier(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    _write(repo, "pkg/widget.py", "def widget_render():\n    return 1\n")
    base = _commit(repo, "add widget")
    (repo / "pkg/widget.py").unlink()
    head = _commit(repo, "remove widget")
    ledger = tmp_path / "ledger"
    _ledger(ledger, [_section("ENTITY-DECISION-D0D0D0D0", [
        ("DECISION", "Decision: keep `pkg/widget.py` until the migration finishes cleanly"),
        ("FACT-ID", "d0d0d0d0d0d0d0d0"),
        ("BASIS", "marker_stated"),
        ("STATUS", "current"),
        ("TURN", "2"),
        ("SRC", "session:aaaaaaaa#turn2"),
    ])])
    report = verify(f"{base}..{head}", repo=repo, ledger_dir=ledger)
    row = _finding(report)
    assert row.to_dict() == {
        "code": "STALE_IDENTIFIER",
        "evidence": "pkg/widget.py",
        "fact_id": "d0d0d0d0d0d0d0d0",
        "location": "session-aaaaaaaa.ctx",
        "message": "live fact names an identifier missing at head",
        "severity": "warning",
    }


def test_superseded_still_in_code(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    _write(repo, "src/app.py", "legacy_hook = 1\n")
    base = _commit(repo, "add hook")
    _write(repo, "src/app.py", "legacy_hook = 2\n")
    head = _commit(repo, "edit hook")
    ledger = tmp_path / "ledger"
    _ledger(
        ledger,
        [_section("ENTITY-DECISION-A1A1A1A1", [
            ("DECISION", "Decision: retire `legacy_hook` from the runtime path entirely"),
            ("FACT-ID", "a1a1a1a1a1a1a1a1"),
            ("BASIS", "marker_stated"),
            ("STATUS", "current"),
            ("TURN", "3"),
            ("SRC", "session:aaaaaaaa#turn3"),
        ])],
        events=(
            '{"event":"fact_superseded","fact_id":"a1a1a1a1a1a1a1a1",'
            '"detail":{"by":"b2b2b2b2b2b2b2b2","reason":"replaced"},'
            '"turn":4,"session":"aaaaaaaa"}\n'
        ),
    )
    report = verify(f"{base}..{head}", repo=repo, ledger_dir=ledger)
    row = _finding(report)
    assert row.to_dict() == {
        "code": "SUPERSEDED_STILL_IN_CODE",
        "evidence": "legacy_hook",
        "fact_id": "a1a1a1a1a1a1a1a1",
        "location": "src/app.py",
        "message": "superseded fact identifier still appears in a changed file",
        "severity": "warning",
    }


def test_constraint_conflict(tmp_path: Path) -> None:
    repo, spec = _range_repo(tmp_path, DECISION)
    ledger = tmp_path / "ledger"
    _ledger(ledger, [
        _section("ENTITY-CONSTRAINT-C0FFEE00", [
            ("CONSTRAINT", CONSTRAINT),
            ("FACT-ID", "c0ffee0000000001"),
            ("BASIS", "marker_stated"),
            ("STATUS", "current"),
            ("TURN", "1"),
            ("SRC", "session:aaaaaaaa#turn1"),
        ]),
        _section("ENTITY-DECISION-D1D1D1D1", [
            ("DECISION", DECISION),
            ("FACT-ID", "d1d1d1d1d1d1d1d1"),
            ("BASIS", "marker_stated"),
            ("STATUS", "current"),
            ("TURN", "2"),
            ("SRC", "session:aaaaaaaa#turn2"),
        ]),
    ])
    report = verify(spec, repo=repo, ledger_dir=ledger)
    row = _finding(report)
    head = spec.split("..", 1)[1]
    assert row.to_dict() == {
        "code": "CONSTRAINT_CONFLICT",
        "evidence": "enable the legacy billing bypass",
        "fact_id": "c0ffee0000000001",
        "location": head,
        "message": "decision conflicts with a live constraint",
        "severity": "warning",
    }


def test_clean_fixture_is_empty_and_exits_zero(tmp_path: Path) -> None:
    repo, spec = _range_repo(tmp_path, "edit the readme title")
    ledger = tmp_path / "ledger"
    _ledger(ledger, [_section("ENTITY-DECISION-EEEEEEEE", [
        ("DECISION", "Decision: keep the readme title stable for the release notes"),
        ("FACT-ID", "eeeeeeeeeeeeeeee"),
        ("BASIS", "marker_stated"),
        ("STATUS", "current"),
        ("TURN", "1"),
        ("SRC", "session:aaaaaaaa#turn1"),
    ])])
    report = verify(spec, repo=repo, ledger_dir=ledger)
    assert report.findings == ()
    assert report.exit_code == 0
    assert report.dropped == 0


def test_attestation_sha_mismatch_and_prefix_ok(tmp_path: Path) -> None:
    repo, spec = _range_repo(tmp_path, "edit the readme title")
    head = spec.split("..", 1)[1]
    bad = ("0" if head[-1] != "0" else "1")
    bad_sha = head[:-1] + bad
    mismatch = verify(
        spec, repo=repo, ledger_dir=tmp_path / "missing-ledger",
        pr_body=f"Verified-SHA: {bad_sha}\n", pr_body_label="pr_body.md")
    row = _finding(mismatch)
    assert row.code == "ATTESTATION_SHA_MISMATCH"
    assert row.evidence == bad_sha
    assert row.fact_id is None
    assert row.location == "pr_body.md"
    assert row.message == "attestation SHA does not match head"
    prefix = verify(
        spec, repo=repo, ledger_dir=tmp_path / "missing-ledger",
        pr_body=f"Head-SHA: {head[:12]}\n")
    assert prefix.findings == ()


def test_version_pin_drift(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    _write(repo, "pkg/versions.py", 'MODEL = "1.13.0"\n')
    base = _commit(repo, "pin")
    _write(repo, "pkg/versions.py", 'MODEL = "latest"\n')
    head = _commit(repo, "float")
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({
        "name": "pins",
        "pinned_versions": {"pkg/versions.py": "1.13.0"},
    }), encoding="utf-8")
    report = verify(f"{base}..{head}", repo=repo, contract=contract,
                    ledger_dir=tmp_path / "no-ledger")
    row = _finding(report)
    assert row.to_dict() == {
        "code": "VERSION_PIN_DRIFT",
        "evidence": "pin=1.13.0; floating-alias,missing-exact",
        "fact_id": None,
        "location": "pkg/versions.py",
        "message": "pinned version does not match a changed file",
        "severity": "error",
    }


def test_unverified_claim(tmp_path: Path) -> None:
    repo, spec = _range_repo(tmp_path, "edit the readme title")
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({
        "name": "evidence",
        "require_test_evidence": True,
    }), encoding="utf-8")
    report = verify(
        spec, repo=repo, contract=contract, ledger_dir=tmp_path / "no-ledger",
        pr_body="95% coverage\n", pr_body_label="pr_body.md")
    row = _finding(report)
    assert row.to_dict() == {
        "code": "UNVERIFIED_CLAIM",
        "evidence": "95% coverage",
        "fact_id": None,
        "location": "pr_body.md",
        "message": "claim lacks required test evidence",
        "severity": "warning",
    }
    contradicted = verify(
        spec, repo=repo, ledger_dir=tmp_path / "no-ledger",
        pr_body="all tests passed\ntests were not run\n",
        pr_body_label="pr_body.md")
    row = _finding(contradicted)
    assert row.code == "UNVERIFIED_CLAIM"
    assert row.message == "claim states tests were not run"
    assert row.evidence == "all tests passed"


def test_contract_forbidden_flag_and_vocabulary(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    _write(repo, "src/flags.py", "enable_beta = False\n")
    _write(repo, "src/app.py", "value = 1\n")
    _write(repo, "README.md", "ok\n")
    base = _commit(repo, "base")
    _write(repo, "src/flags.py", "enable_beta = True\n")
    _write(repo, "src/app.py", "legacy_alias = 1\n")
    _write(repo, "secrets/key.txt", "nope\n")
    head = _commit(repo, "bad change")

    forbidden = tmp_path / "forbidden.json"
    forbidden.write_text(json.dumps({
        "name": "bounds",
        "forbidden_paths": ["secrets/**"],
    }), encoding="utf-8")
    report = verify(f"{base}..{head}", repo=repo, contract=forbidden,
                    ledger_dir=tmp_path / "no-ledger")
    # three files changed; only secrets/ is forbidden. flags and app are not.
    forbidden_rows = [row for row in report.findings
                      if row.evidence.startswith("forbidden_paths:")]
    assert len(forbidden_rows) == 1
    assert forbidden_rows[0].to_dict()["code"] == "CONTRACT_RULE_VIOLATION"
    assert forbidden_rows[0].location == "secrets/key.txt"
    assert forbidden_rows[0].evidence == "forbidden_paths:secrets/**"
    assert forbidden_rows[0].message == "changed file matches a forbidden path"

    flags = tmp_path / "flags.json"
    flags.write_text(json.dumps({
        "name": "flags",
        "flag_off_invariants": [{
            "flag": "enable_beta",
            "config_globs": ["src/flags.py"],
            "guarded_globs": ["src/beta/**"],
        }],
    }), encoding="utf-8")
    report = verify(f"{base}..{head}", repo=repo, contract=flags,
                    ledger_dir=tmp_path / "no-ledger")
    row = _finding(report)
    assert row.evidence == "flag_off:enable_beta"
    assert row.location == "src/flags.py"
    assert row.message == "changed file flips a default-off flag on"

    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps({
        "name": "vocab",
        "forbidden_vocabulary": {"src/**/*.py": ["legacy_alias"]},
    }), encoding="utf-8")
    report = verify(f"{base}..{head}", repo=repo, contract=vocab,
                    ledger_dir=tmp_path / "no-ledger")
    rows = [row for row in report.findings if row.evidence.startswith("forbidden_vocabulary:")]
    assert len(rows) == 1
    assert rows[0].location == "src/app.py"
    assert rows[0].evidence == "forbidden_vocabulary:legacy_alias"
    assert rows[0].message == "changed file contains forbidden vocabulary"


def test_flag_guard_bypass_and_allowed_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    _write(repo, "src/beta/worker.py", "if enable_beta:\n    run()\n")
    _write(repo, "docs/index.md", "ctxpack\n")
    base = _commit(repo, "base")
    _write(repo, "src/beta/worker.py", "run()\n")
    _write(repo, "docs/index.md", "notes\n")
    head = _commit(repo, "bypass")
    guard = tmp_path / "guard.json"
    guard.write_text(json.dumps({
        "name": "guard",
        "flag_off_invariants": [{
            "flag": "enable_beta",
            "guarded_globs": ["src/beta/**"],
        }],
    }), encoding="utf-8")
    report = verify(f"{base}..{head}", repo=repo, contract=guard,
                    ledger_dir=tmp_path / "no-ledger")
    guard_rows = [row for row in report.findings if row.evidence.startswith("flag_guard:")]
    assert len(guard_rows) == 1
    assert guard_rows[0].location == "src/beta/worker.py"

    allowed = tmp_path / "allowed.json"
    allowed.write_text(json.dumps({
        "name": "allow",
        "allowed_paths": ["docs/**"],
        "required_vocabulary": {"docs/**": ["ctxpack"]},
    }), encoding="utf-8")
    report = verify(f"{base}..{head}", repo=repo, contract=allowed,
                    ledger_dir=tmp_path / "no-ledger")
    messages = sorted(row.message for row in report.findings)
    assert "changed file is outside allowed paths" in messages
    assert "changed file misses required vocabulary" in messages


def test_blocking_exit_codes(tmp_path: Path) -> None:
    repo, spec = _range_repo(
        tmp_path,
        "Decision: record the widget cutoff at the ledger boundary")
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    quiet = verify(spec, repo=repo, ledger_dir=ledger)
    assert quiet.exit_code == 0
    blocked = verify(spec, repo=repo, ledger_dir=ledger,
                     block=["UNRECORDED_MARKER"])
    assert blocked.exit_code == 1
    other = verify(spec, repo=repo, ledger_dir=ledger,
                   block=["STALE_IDENTIFIER"])
    assert other.exit_code == 0

    _write(repo, "ctxpack.toml", '[verify]\nblock = ["UNRECORDED_MARKER"]\n')
    from_toml = verify(spec, repo=repo, ledger_dir=ledger)
    assert from_toml.exit_code == 1
    assert from_toml.blocking == ("UNRECORDED_MARKER",)

    contract = tmp_path / "block.json"
    contract.write_text(json.dumps({
        "name": "block",
        "blocking_codes": ["UNRECORDED_MARKER"],
    }), encoding="utf-8")
    # toml outranks the contract when --block is omitted
    assert verify(spec, repo=repo, ledger_dir=ledger, contract=contract).exit_code == 1
    (repo / "ctxpack.toml").unlink()
    assert verify(spec, repo=repo, ledger_dir=ledger, contract=contract).exit_code == 1
    # an explicit --block replaces both
    assert verify(
        spec, repo=repo, ledger_dir=ledger, contract=contract,
        block=["STALE_IDENTIFIER"]).exit_code == 0


def test_fenced_marker_is_not_a_finding(tmp_path: Path) -> None:
    repo, spec = _range_repo(tmp_path, "edit the readme title")
    body = "```\nDecision: this example is quoted and must not be banked\n```\n"
    report = verify(spec, repo=repo, ledger_dir=tmp_path / "no-ledger", pr_body=body)
    assert report.findings == ()


def test_json_is_sorted_and_repeatable(tmp_path: Path) -> None:
    repo, spec = _range_repo(
        tmp_path,
        "Decision: record the widget cutoff at the ledger boundary")
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    first = render_json(verify(spec, repo=repo, ledger_dir=ledger))
    second = render_json(verify(spec, repo=repo, ledger_dir=ledger))
    assert first == second
    assert "\r" not in first
    assert first.endswith("\n")
    parsed = json.loads(first)
    assert first == json.dumps(parsed, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    assert parsed["findings"][0]["code"] == "UNRECORDED_MARKER"
    md = render_markdown(verify(spec, repo=repo, ledger_dir=ledger))
    assert "UNRECORDED_MARKER" in md
    assert "\r" not in md


def test_determinism_across_hash_seeds(tmp_path: Path) -> None:
    repo, spec = _range_repo(
        tmp_path,
        "Decision: record the widget cutoff at the ledger boundary")
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    script = (
        "import os, sys\n"
        "from ctxpack.agent.verify import render_json, verify\n"
        "report = verify(os.environ['RANGE'], repo=os.environ['REPO_DIR'], "
        "ledger_dir=os.environ['LEDGER'])\n"
        "sys.stdout.buffer.write(render_json(report).encode('utf-8'))\n"
    )
    outputs = []
    for seed in ("0", "1", "random"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(ROOT)
        env["RANGE"] = spec
        env["REPO_DIR"] = str(repo)
        env["LEDGER"] = str(ledger)
        proc = subprocess.run(
            [sys.executable, "-c", script], cwd=str(ROOT), env=env,
            capture_output=True, check=True)
        outputs.append(proc.stdout)
    assert outputs[0] == outputs[1] == outputs[2]
    assert b"\r" not in outputs[0]


def test_cli_in_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    repo, spec = _range_repo(
        tmp_path,
        "Decision: record the widget cutoff at the ledger boundary")
    monkeypatch.chdir(repo)
    code = main([
        "verify", "--range", spec, "--ledger-dir", str(tmp_path / "ledger"),
        "--format", "md", "--block", "UNRECORDED_MARKER",
    ])
    captured = capsys.readouterr()
    assert code == 1
    assert "UNRECORDED_MARKER" in captured.out
    assert "exit_code: 1" in captured.out
    bad = main(["verify", "--range", "not-a-range", "--ledger-dir", str(tmp_path / "ledger")])
    err = capsys.readouterr().err
    assert bad == 2
    assert "range must be A..B" in err


def test_verify_export_matches_module(tmp_path: Path) -> None:
    import ctxpack
    repo, spec = _range_repo(tmp_path, "edit the readme title")
    left = ctxpack.verify(spec, repo=repo, ledger_dir=tmp_path / "no-ledger")
    right = verify(spec, repo=repo, ledger_dir=tmp_path / "no-ledger")
    assert render_json(left) == render_json(right)


def test_max_findings_discloses_drops(tmp_path: Path) -> None:
    message = "\n".join([
        "Decision: alpha marker one is not in the ledger",
        "Decision: beta marker two is not in the ledger",
        "Decision: gamma marker three is not in the ledger",
    ])
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    _write(repo, "README.md", "base\n")
    base = _commit(repo, "base")
    _write(repo, "README.md", "head\n")
    # commit -m is a single paragraph; pass the markers as the message via a file
    msg = tmp_path / "msg.txt"
    msg.write_text(message + "\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-F", str(msg))
    head = _git(repo, "rev-parse", "HEAD")
    report = verify(
        f"{base}..{head}", repo=repo, ledger_dir=tmp_path / "no-ledger",
        max_findings=1, block=["UNRECORDED_MARKER"])
    assert len(report.findings) == 1
    assert report.dropped == 2
    assert report.exit_code == 1
    assert report.findings[0].evidence.startswith("Decision: alpha")
