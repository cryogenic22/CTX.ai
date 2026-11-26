"""Findings log and deterministic ``ctxpack lessons suggest``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ctxpack.agent.findings_log import (
    FindingsLogError,
    append_findings,
    finding_path,
    finding_pattern,
    propose_contract,
    read_findings,
    render_suggestions,
    suggestions_payload,
)
from ctxpack.agent.verify import Finding, VerifyReport, verify
from ctxpack.cli.main import main

ROOT = Path(__file__).resolve().parents[1]


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


def _range_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    _write(repo, "README.md", "base\n")
    _write(repo, "secrets/key.txt", "old\n")
    _write(repo, "migrations/001.sql", "select 1;\n")
    base = _commit(repo, "base")
    _write(repo, "secrets/key.txt", "new\n")
    _write(repo, "migrations/001.sql", "select 2;\n")
    head = _commit(repo, "touch secrets and migrations")
    return repo, f"{base}..{head}", head


def _finding(
    code: str,
    location: str,
    evidence: str,
    *,
    message: str = "message",
    severity: str = "warning",
) -> Finding:
    return Finding(code, severity, None, location, message, evidence)


def _report(
    findings: list[Finding],
    *,
    head: str = "abc1234",
    base: str = "def5678",
    blocking: tuple[str, ...] = (),
    range_spec: str = "def5678..abc1234",
) -> VerifyReport:
    return VerifyReport(
        range_spec=range_spec,
        base=base,
        head=head,
        findings=tuple(findings),
        blocking=blocking,
        exit_code=1 if blocking else 0,
        contract="demo",
        dropped=0,
    )


def _line(code: str, pattern: str, *, head: str, path: str = "", count: int = 1) -> str:
    rows = []
    for _ in range(count):
        row = {
            "base_sha": "base",
            "blocking": False,
            "code": code,
            "evidence": "evidence",
            "head_sha": head,
            "path": path,
            "pattern": pattern,
            "range": "base..head",
            "schema_version": 1,
            "severity": "warning",
        }
        rows.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
    return "\n".join(rows) + "\n"


def test_pattern_keys_drop_shas_and_keep_globs() -> None:
    assert finding_path("pr-body") == ""
    assert finding_path("abc1234def56789") == ""
    assert finding_path("/etc/passwd") == ""
    assert finding_path("src\\app.py:120") == "src/app.py"
    assert finding_path(".github/workflows/ci.yml") == ".github/workflows/ci.yml"
    assert finding_pattern(
        "ONE_WAY_PATH_TOUCHED",
        ".github/workflows/ci.yml",
        "one_way_paths:.github/**",
    ) == ".github/**"
    assert finding_pattern(
        "FORBIDDEN_PATH_TOUCHED",
        "secrets/key.txt",
        "forbidden_paths:secrets/**",
    ) == "secrets/**"
    assert finding_pattern(
        "CONTRACT_RULE_VIOLATION",
        "secrets/key.txt",
        "forbidden_paths:secrets/**",
    ) == "forbidden_paths:secrets/**"
    assert finding_pattern(
        "CONTRACT_RULE_VIOLATION",
        "docs/index.md",
        "allowed_paths",
    ) == "allowed_paths:docs/**"
    assert finding_pattern(
        "OUT_OF_SCOPE_CHANGE", "README.md", "",
    ) == "README.md"
    assert finding_pattern(
        "STALE_IDENTIFIER", "session-aaaaaaaa.ctx", "widget_cutoff:88",
    ) == "stale_identifier"
    assert finding_pattern(
        "ATTESTATION_SHA_MISMATCH", "", "abcdef1234567890",
    ) == "sha_mismatch"
    assert finding_pattern(
        "UNVERIFIED_CLAIM", "pr-body", "all tests passed",
        message="claim lacks required test evidence",
    ) == "unverified_test_claim"
    assert finding_pattern(
        "VERIFIER_EVIDENCE_MISSING", "", "missing",
        message="verifier evidence is missing",
    ) == "missing_verifier"
    assert finding_pattern(
        "VERIFIER_EVIDENCE_MISSING", "", "abcdef1234567890",
        message="verifier evidence SHA does not match head",
    ) == "sha_mismatch"
    assert finding_pattern(
        "VERIFIER_EVIDENCE_MISSING", "", "pytest",
        message="verifier evidence does not name the contract command",
    ) == "command_mismatch"
    assert "abcdef1234567890" not in finding_pattern(
        "UNRECORDED_MARKER", "abcdef1234567890", "Decision: keep the cutoff",
    )


def test_append_is_sorted_bounded_and_round_trips(tmp_path: Path) -> None:
    evidence = "line one\nline two " + ("x" * 300)
    report = _report(
        [_finding("UNVERIFIED_CLAIM", "pr-body", evidence, severity="warning")],
        blocking=(),
    )
    target = tmp_path / "nested" / "findings.jsonl"
    assert append_findings(report, target) == 1
    assert target.parent.is_dir()
    raw = target.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\n" not in raw[:-1]
    row = json.loads(raw)
    assert list(row) == sorted(row)
    assert set(row) == {
        "base_sha", "blocking", "code", "evidence", "head_sha", "path",
        "pattern", "range", "schema_version", "severity",
    }
    assert row["schema_version"] == 1
    assert row["blocking"] is False
    assert row["path"] == ""
    assert row["pattern"] == "unverified_test_claim"
    assert "\n" not in row["evidence"]
    assert len(row["evidence"]) <= 240
    assert row["head_sha"] == "abc1234"
    assert row["base_sha"] == "def5678"
    assert row["range"] == "def5678..abc1234"
    again = _report(
        [_finding(
            "ONE_WAY_PATH_TOUCHED",
            ".github/workflows/ci.yml",
            "one_way_paths:.github/**",
            severity="error",
        )],
        blocking=("ONE_WAY_PATH_TOUCHED",),
        head="fff9999",
    )
    assert append_findings(again, target, repo_id="cohort-a") == 1
    loaded = read_findings(target)
    assert len(loaded) == 2
    assert loaded[1]["blocking"] is True
    assert loaded[1]["pattern"] == ".github/**"
    assert loaded[1]["path"] == ".github/workflows/ci.yml"
    assert loaded[1]["repo_id"] == "cohort-a"
    assert loaded.corrupt_count == 0
    empty = _report([])
    nowhere = tmp_path / "absent.jsonl"
    assert append_findings(empty, nowhere) == 0
    assert not nowhere.exists()


def test_read_fails_loud_on_corrupt_lines_and_can_count_them(tmp_path: Path) -> None:
    path = tmp_path / "findings.jsonl"
    good = _line("STALE_IDENTIFIER", "stale_identifier", head="aaa", path="src/a.py")
    path.write_bytes(b"[\n" + good.encode("utf-8") + b"{not-json\n")
    with pytest.raises(FindingsLogError) as exc:
        read_findings(path)
    assert exc.value.lines == (1, 3)
    assert "1" in str(exc.value) and "3" in str(exc.value)
    skipped = read_findings(path, skip_corrupt=True)
    assert skipped.corrupt_count == 2
    assert skipped.corrupt_lines == (1, 3)
    assert len(skipped) == 1
    assert skipped[0]["code"] == "STALE_IDENTIFIER"
    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")
    assert read_findings(empty) == []
    blanks = tmp_path / "blanks.jsonl"
    blanks.write_text("\n\n", encoding="utf-8", newline="\n")
    assert read_findings(blanks) == []
    missing = tmp_path / "missing.jsonl"
    with pytest.raises(FileNotFoundError):
        read_findings(missing)
    bad_schema = tmp_path / "schema.jsonl"
    bad_schema.write_text(
        '{"schema_version": 2, "code": "X"}\n', encoding="utf-8", newline="\n")
    with pytest.raises(FindingsLogError) as schema_exc:
        read_findings(bad_schema)
    assert schema_exc.value.lines == (1,)


def test_suggestions_count_heads_paths_and_tie_break() -> None:
    records = []
    for head, path in (
        ("mmm", "z/a.py"),
        ("mmm", "z/b.py"),
        ("", "z/c.py"),
        ("aaa", "m/a.py"),
    ):
        records.append({
            "code": "MMM",
            "pattern": "z",
            "head_sha": head,
            "path": path,
        })
    for path in ("a.py", "b.py", "c.py", "d.py"):
        records.append({
            "code": "AAA",
            "pattern": "z",
            "head_sha": "h1",
            "path": path,
        })
    records.append({
        "code": "AAA",
        "pattern": "a",
        "head_sha": "h1",
        "path": "only.py",
    })
    records.append({
        "code": "AAA",
        "pattern": "a",
        "head_sha": "h2",
        "path": "only.py",
    })
    # Below the default threshold. Inserted first so a hash-ordered
    # grouping would surface it ahead of the tied groups.
    records.insert(0, {
        "code": "ZZZ",
        "pattern": "low",
        "head_sha": "h9",
        "path": "low.py",
    })
    payload = suggestions_payload(records, min_count=3, findings_log="findings.jsonl")
    assert payload["total_findings"] == len(records)
    assert [(row["code"], row["pattern"]) for row in payload["suggestions"]] == [
        ("AAA", "z"),
        ("MMM", "z"),
    ]
    mmm = payload["suggestions"][1]
    assert mmm["count"] == 4
    assert mmm["distinct_heads"] == 2
    assert mmm["sample_paths"] == ["m/a.py", "z/a.py", "z/b.py"]
    low = suggestions_payload(records, min_count=1, findings_log="findings.jsonl")
    assert [row["code"] for row in low["suggestions"]][:1] == ["AAA"]
    assert any(row["code"] == "ZZZ" for row in low["suggestions"])
    with pytest.raises(FindingsLogError):
        suggestions_payload(records, min_count=0)


def test_contract_proposals_are_concrete_and_not_applied(tmp_path: Path) -> None:
    cases = {
        "FORBIDDEN_PATH_TOUCHED": (
            ".github/workflows/**",
            {"forbidden_paths": [".github/workflows/**"]},
            "forbidden_paths",
        ),
        "OUT_OF_SCOPE_CHANGE": (
            "src/**",
            {"allowed_paths": ["src/**"]},
            "allowed_paths",
        ),
        "ONE_WAY_PATH_TOUCHED": (
            "migrations/**",
            {"one_way_paths": ["migrations/**"]},
            "one-way-ack:",
        ),
        "VERIFIER_EVIDENCE_MISSING": (
            "missing_verifier",
            {"require_verifier_evidence": True, "verifier_command": ""},
            "ctxpack onboard",
        ),
        "UNVERIFIED_CLAIM": (
            "unverified_test_claim",
            {"blocking_codes": ["UNVERIFIED_CLAIM"], "require_test_evidence": True},
            "require_test_evidence",
        ),
        "ATTESTATION_SHA_MISMATCH": (
            "sha_mismatch",
            {
                "blocking_codes": ["ATTESTATION_SHA_MISMATCH"],
                "require_attestation_sha": True,
            },
            "verified-sha:",
        ),
        "STALE_IDENTIFIER": (
            "stale_identifier",
            {"blocking_codes": ["STALE_IDENTIFIER"]},
            "rename-completeness",
        ),
        "CONTRACT_RULE_VIOLATION": (
            "flag_off:enable_beta",
            {"blocking_codes": ["CONTRACT_RULE_VIOLATION"]},
            "blocking_codes",
        ),
    }
    for code, (pattern, patch, needle) in cases.items():
        summary, got = propose_contract(code, pattern)
        assert got == patch
        assert needle in summary
        assert "auto" not in summary.lower()
    summary, patch = propose_contract(
        "CONTRACT_RULE_VIOLATION", "forbidden_paths:secrets/**")
    assert patch == {"forbidden_paths": ["secrets/**"]}
    assert "allowed_paths" in summary
    contract = tmp_path / "contract.json"
    contract.write_text("{}\n", encoding="utf-8")
    before = contract.read_bytes()
    suggestions_payload([{
        "code": "ONE_WAY_PATH_TOUCHED",
        "pattern": "migrations/**",
        "head_sha": "h",
        "path": "migrations/001.sql",
    }] * 3)
    assert contract.read_bytes() == before


def test_render_formats_and_missing_status() -> None:
    payload = suggestions_payload(
        [{
            "code": "STALE_IDENTIFIER",
            "pattern": "stale_identifier",
            "head_sha": "h",
            "path": "src/a.py",
        }] * 3,
        min_count=3,
        findings_log="findings.jsonl",
    )
    text = render_suggestions(payload, "text")
    markdown = render_suggestions(payload, "markdown")
    blob = render_suggestions(payload, "json")
    assert "count=3" in text and "distinct_heads=1" in text
    assert "rename-completeness" in text
    assert text.endswith("\n") and "\r" not in text
    assert "## STALE_IDENTIFIER `stale_identifier`" in markdown
    assert "```json" in markdown and "\r" not in markdown
    data = json.loads(blob)
    assert data["suggestions"][0]["sample_paths"] == ["src/a.py"]
    assert list(data) == sorted(data)
    missing = suggestions_payload([], findings_log=".ctx/findings.jsonl", status="missing")
    assert render_suggestions(missing, "text") == (
        "No findings log found at .ctx/findings.jsonl\n")
    assert "No findings log found at" in render_suggestions(missing, "markdown")
    missing_json = json.loads(render_suggestions(missing, "json"))
    assert missing_json["suggestions"] == []
    assert missing_json["total_findings"] == 0


def test_concurrent_appends_keep_every_line(tmp_path: Path) -> None:
    path = tmp_path / "findings.jsonl"
    barrier = threading.Barrier(4)

    def worker(index: int) -> None:
        barrier.wait()
        for nth in range(5):
            report = _report([_finding(
                "STALE_IDENTIFIER", "src/a.py", "name",
            )], head=f"{index:02d}{nth:02d}abcd")
            append_findings(report, path)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    loaded = read_findings(path)
    assert len(loaded) == 20
    assert {row["code"] for row in loaded} == {"STALE_IDENTIFIER"}


def test_verify_cli_records_only_when_asked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, spec, head = _range_repo(tmp_path)
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({
        "name": "bounds",
        "forbidden_paths": ["secrets/**"],
        "one_way_paths": ["migrations/**"],
    }), encoding="utf-8")
    ledger = tmp_path / "no-ledger"
    monkeypatch.chdir(tmp_path)
    silent = main([
        "verify", "--repo", str(repo), "--range", spec,
        "--contract", str(contract), "--ledger-dir", str(ledger),
    ])
    assert silent == 1
    assert not (repo / ".ctx").exists()
    capsys.readouterr()
    nested = repo / "out" / "nested" / "findings.jsonl"
    recorded = main([
        "verify", "--repo", str(repo), "--range", spec,
        "--contract", str(contract), "--ledger-dir", str(ledger),
        "--findings-log", "out/nested/findings.jsonl",
    ])
    assert recorded == 1
    assert nested.is_file()
    first = nested.read_bytes()
    again = main([
        "verify", "--repo", str(repo), "--range", spec,
        "--contract", str(contract), "--ledger-dir", str(ledger),
        "--record-findings",
        "--findings-log", "out/nested/findings.jsonl",
    ])
    assert again == 1
    second = nested.read_bytes()
    assert second.startswith(first)
    assert second.count(b"\n") == first.count(b"\n") * 2
    rows = read_findings(nested)
    codes = {row["code"] for row in rows}
    assert "ONE_WAY_PATH_TOUCHED" in codes
    assert "CONTRACT_RULE_VIOLATION" in codes
    one_way = [row for row in rows if row["code"] == "ONE_WAY_PATH_TOUCHED"]
    forbidden = [row for row in rows if row["pattern"].startswith("forbidden_paths:")]
    assert one_way[0]["blocking"] is True
    assert one_way[0]["pattern"] == "migrations/**"
    assert one_way[0]["path"] == "migrations/001.sql"
    assert one_way[0]["head_sha"] == head
    assert forbidden[0]["blocking"] is False
    assert forbidden[0]["pattern"] == "forbidden_paths:secrets/**"
    direct = verify(spec, repo=repo, contract=contract, ledger_dir=ledger)
    assert direct.exit_code == 1
    assert nested.read_bytes() == second
    default_log = repo / ".ctx" / "findings.jsonl"
    assert not default_log.exists()
    flagged = main([
        "verify", "--repo", str(repo), "--range", spec,
        "--contract", str(contract), "--ledger-dir", str(ledger),
        "--record-findings",
    ])
    assert flagged == 1
    assert default_log.is_file()
    assert read_findings(default_log)


def test_lessons_suggest_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    missing = main(["lessons", "suggest", "--findings-log", "missing.jsonl"])
    out = capsys.readouterr().out
    assert missing == 0
    assert out == "No findings log found at missing.jsonl\n"
    missing_json = main([
        "lessons", "suggest", "--findings-log", "missing.jsonl", "--json",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert missing_json == 0
    assert payload["suggestions"] == []
    assert payload["total_findings"] == 0
    log = tmp_path / "findings.jsonl"
    body = (
        _line("UNVERIFIED_CLAIM", "unverified_test_claim", head="h1", count=2)
        + _line("STALE_IDENTIFIER", "stale_identifier", head="h1", path="src/a.py")
        + _line("STALE_IDENTIFIER", "stale_identifier", head="h1", path="src/b.py")
        + _line("STALE_IDENTIFIER", "stale_identifier", head="h2", path="src/a.py")
        + _line("AAA", "a", head="h", count=3)
        + _line("AAA", "m", head="h", count=3)
        + _line("MMM", "a", head="h", count=3)
    )
    log.write_text(body, encoding="utf-8", newline="\n")
    assert main(["lessons", "suggest", "--findings-log", "findings.jsonl"]) == 0
    text = capsys.readouterr().out
    assert "UNVERIFIED_CLAIM" not in text
    assert "STALE_IDENTIFIER pattern=stale_identifier count=3 distinct_heads=2" in text
    assert text.index("AAA pattern=a") < text.index("AAA pattern=m") < text.index("MMM pattern=a")
    assert main([
        "lessons", "suggest", "--findings-log", "findings.jsonl",
        "--min-count", "2", "--format", "markdown",
    ]) == 0
    markdown = capsys.readouterr().out
    assert "UNVERIFIED_CLAIM" in markdown
    assert "require_test_evidence" in markdown
    assert main([
        "lessons", "suggest", "--findings-log", "findings.jsonl", "--format", "json",
    ]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_findings"] == 14
    assert [row["code"] for row in data["suggestions"]] == ["AAA", "AAA", "MMM", "STALE_IDENTIFIER"]
    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")
    assert main(["lessons", "suggest", "--findings-log", "empty.jsonl"]) == 0
    assert "No pattern reached min count 3." in capsys.readouterr().out
    corrupt = tmp_path / "bad.jsonl"
    corrupt.write_text('{"schema_version": 1, "code": "AAA"}\n{nope\n', encoding="utf-8")
    assert main(["lessons", "suggest", "--findings-log", "bad.jsonl"]) == 2
    err = capsys.readouterr().err
    assert "line 2" in err
    with pytest.raises(SystemExit) as exc:
        main(["lessons", "suggest", "--min-count", "0"])
    assert exc.value.code == 2
    conflict = main([
        "lessons", "suggest", "--findings-log", "findings.jsonl",
        "--format", "markdown", "--json",
    ])
    assert conflict == 2
    assert "conflicts" in capsys.readouterr().err
    assert main(["lessons"]) == 0
    assert "L-001" in capsys.readouterr().out


def test_suggest_bytes_ignore_hash_seed(tmp_path: Path) -> None:
    log = tmp_path / "findings.jsonl"
    # MMM is written first. Sort order is AAA then MMM, independent of
    # dict insertion and of PYTHONHASHSEED.
    log.write_text(
        _line("MMM", "a", head="h1", path="m.py", count=3)
        + _line("AAA", "m", head="h2", path="a.py", count=3)
        + _line("AAA", "a", head="", path="a.py", count=3),
        encoding="utf-8",
        newline="\n",
    )
    script = (
        "import sys\n"
        "from ctxpack.cli.main import main\n"
        "sys.exit(main(sys.argv[1:]))\n"
    )
    outputs: dict[tuple[str, str], bytes] = {}
    for seed in ("1", "42"):
        for fmt in ("json", "text", "markdown"):
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = str(ROOT)
            proc = subprocess.run(
                [
                    sys.executable, "-c", script,
                    "lessons", "suggest",
                    "--findings-log", "findings.jsonl",
                    "--format", fmt,
                ],
                cwd=str(tmp_path),
                env=env,
                capture_output=True,
                check=True,
            )
            assert proc.stderr == b""
            assert b"\r" not in proc.stdout
            outputs[(seed, fmt)] = proc.stdout
    for fmt in ("json", "text", "markdown"):
        assert outputs[("1", fmt)] == outputs[("42", fmt)]
        assert b"AAA" in outputs[("1", fmt)]
    text = outputs[("1", "text")]
    assert text.index(b"AAA pattern=a") < text.index(b"AAA pattern=m")
    assert text.index(b"AAA pattern=m") < text.index(b"MMM pattern=a")
