"""Unit tests for the CI quality ratchets (version identity, mypy count)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def version_mod():
    return _load("check_version", "check_version.py")


@pytest.fixture(scope="module")
def mypy_mod():
    return _load("check_mypy_ratchet", "check_mypy_ratchet.py")


def test_project_version_reads_the_project_table(version_mod):
    text = '[project]\nversion = "0.5.0rc1"\n\n[tool.other]\nversion = "9"\n'
    assert version_mod.project_version(text) == "0.5.0rc1"


def test_normalize_version_equates_tag_spellings(version_mod):
    norm = version_mod.normalize_version
    assert norm("0.5.0rc1") == "0.5.0rc1"
    assert norm("v0.5.0rc1") == "0.5.0rc1"
    assert norm("v0.5.0-rc1") == "0.5.0rc1"
    assert norm("0.5.0-rc1") == "0.5.0rc1"
    assert norm("V1.2.3") == "1.2.3"
    assert norm("1.0.0a1") == "1.0.0a1"
    assert norm("1.0.0-alpha1") == "1.0.0a1"
    assert norm("1.0.0b2") == "1.0.0b2"


def test_live_pyproject_matches_runtime(version_mod):
    import ctxpack
    declared = version_mod.project_version(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert declared == ctxpack.__version__


def test_mypy_summary_parser(mypy_mod):
    assert mypy_mod.count_mypy_errors(
        "Found 78 errors in 14 files (checked 90 source files)\n", 1) == 78
    assert mypy_mod.count_mypy_errors(
        "Success: no issues found in 90 source files\n", 0) == 0
    with pytest.raises(ValueError):
        mypy_mod.count_mypy_errors("mypy: invalid syntax\n", 2)


def test_mypy_baseline_is_within_cap(mypy_mod):
    assert mypy_mod.BASELINE <= mypy_mod.CAP
    assert mypy_mod.CAP == 83
