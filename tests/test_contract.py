"""Task contract schema: fail closed, JSON and TOML, 3.10 subset."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctxpack.agent.contract import (
    FINDING_CODES,
    ContractError,
    TaskContract,
    _fallback_toml,
    load_contract,
    load_toml_mapping,
)

SAMPLE = """\
name = "demo"
require_attestation_sha = true
require_test_evidence = false
allowed_paths = ["ctxpack/**", "docs/**"]
forbidden_paths = ["secrets/**"]
blocking_codes = ["CONTRACT_RULE_VIOLATION", "UNRECORDED_MARKER"]
attestation_sha_patterns = ["(?im)^Ticket-SHA: ([0-9a-fA-F]{7,40})"]

[pinned_versions]
model = "jev-1.13.0"

[forbidden_vocabulary]
"src/**/*.py" = ["legacy_alias"]

[required_vocabulary]
"docs/**/*.md" = ["ctxpack"]

[[flag_off_invariants]]
flag = "enable_beta"
config_globs = ["src/flags.py"]
guarded_globs = ["src/beta/**"]
"""


def test_toml_matches_fallback_and_loads(tmp_path: Path) -> None:
    path = tmp_path / "task.toml"
    path.write_text(SAMPLE, encoding="utf-8", newline="\n")
    loaded = load_toml_mapping(SAMPLE)
    assert loaded == _fallback_toml(SAMPLE)
    contract = load_contract(path)
    assert contract.name == "demo"
    assert contract.require_attestation_sha is True
    assert contract.allowed_paths == ("ctxpack/**", "docs/**")
    assert contract.pinned_versions == (("model", "jev-1.13.0"),)
    assert contract.forbidden_vocabulary == (
        ("src/**/*.py", ("legacy_alias",)),)
    assert contract.flag_off_invariants[0].flag == "enable_beta"
    assert contract.blocking_codes == ("CONTRACT_RULE_VIOLATION", "UNRECORDED_MARKER")
    assert contract.attestation_sha_patterns[0].startswith("(?im)")


def test_json_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "task.json"
    path.write_text(json.dumps({
        "name": "json",
        "pinned_versions": {"pkg/versions.py": "1.13.0"},
        "require_test_evidence": True,
    }), encoding="utf-8")
    contract = load_contract(path)
    assert isinstance(contract, TaskContract)
    assert contract.pinned_versions == (("pkg/versions.py", "1.13.0"),)
    assert contract.require_test_evidence is True
    assert contract.blocking_codes == ()


def test_malformed_contracts_fail_closed(tmp_path: Path) -> None:
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{", encoding="utf-8")
    with pytest.raises(ContractError):
        load_contract(bad_json)
    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({"name": "x", "extra": 1}), encoding="utf-8")
    with pytest.raises(ContractError, match="unknown contract field"):
        load_contract(unknown)
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"blocking_codes": ["NOT_A_CODE"]}), encoding="utf-8")
    with pytest.raises(ContractError, match="unknown blocking code"):
        load_contract(wrong)
    pattern = tmp_path / "pattern.json"
    pattern.write_text(json.dumps({
        "attestation_sha_patterns": ["Verified-SHA: [0-9a-f]+"],
    }), encoding="utf-8")
    with pytest.raises(ContractError, match="capture group"):
        load_contract(pattern)
    other = tmp_path / "note.txt"
    other.write_text("name = 'x'\n", encoding="utf-8")
    with pytest.raises(ContractError, match="json or .toml"):
        load_contract(other)
    assert "UNRECORDED_MARKER" in FINDING_CODES


def test_pyproject_jev_extra_is_empty_and_not_in_all() -> None:
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "\njev = []\n" in text
    all_block = text.split("all = [", 1)[1].split("]", 1)[0]
    assert "jev" not in all_block
