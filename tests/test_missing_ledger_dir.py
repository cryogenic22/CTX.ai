"""Read commands name an explicit ledger directory that is not there.

Write commands (onboard, hook, checkpoint, backfill) still create
directories. The default path is quiet: a fresh checkout has no ledger.
"""

from __future__ import annotations

from pathlib import Path

from ctxpack.cli.main import main


def test_brief_warns_when_explicit_ledger_is_missing(tmp_path: Path, capsys) -> None:
    missing = str(tmp_path / "no-such-ledger")
    rc = main(["brief", "--ledger", missing, "--budget", "100"])
    err = capsys.readouterr().err
    assert rc == 0
    assert f"warning: ledger directory does not exist: {missing}" in err


def test_omitted_ledger_does_not_warn(capsys) -> None:
    main(["brief", "--budget", "40"])
    err = capsys.readouterr().err
    assert "ledger directory does not exist" not in err


def test_session_missing_ledger_warns_and_fails(tmp_path: Path, capsys) -> None:
    missing = str(tmp_path / "no-such-ledger")
    rc = main(["session", "resume", "--ledger", missing])
    err = capsys.readouterr().err
    assert rc == 1
    assert f"warning: ledger directory does not exist: {missing}" in err
    assert "Error" in err


def test_verify_warns_when_explicit_ledger_dir_is_missing(
    tmp_path: Path, capsys,
) -> None:
    missing = str(tmp_path / "no-such-ledger")
    rc = main(["verify", "--range", "not-a-range", "--ledger-dir", missing])
    err = capsys.readouterr().err
    assert rc == 2
    assert f"warning: ledger directory does not exist: {missing}" in err
    assert "range must be A..B" in err
