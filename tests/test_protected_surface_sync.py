"""Guards for the structural floor: CODEOWNERS must track the protected surface.

Forward guard. These bound new behaviour introduced with
scripts/gen_codeowners.py; they do not pin pre-existing behaviour.

Conservation-gates principle 1 ("you do not edit the bar to pass") is only real
if something mechanical notices when the bar moves. Each check below feeds a
violation and requires rejection — a gate that cannot fail is not a gate.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "gen_codeowners.py"


def load():
    """Load gen_codeowners.py fresh, so monkeypatched constants do not leak."""
    spec = importlib.util.spec_from_file_location("gen_codeowners_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codeowners_is_in_sync_with_protected_surface():
    """The committed CODEOWNERS matches what the source list renders."""
    assert load().main(["--check"]) == 0


def test_check_rejects_a_codeowners_that_drifted(tmp_path, monkeypatch):
    """VIOLATION: someone edits CODEOWNERS directly. --check must reject it."""
    module = load()
    source = tmp_path / "protected-surface.txt"
    source.write_text("/CLAUDE.md\n/scripts/check_claims.py\n", encoding="utf-8")
    target = tmp_path / "CODEOWNERS"
    target.write_text(module.render(source.read_text(encoding="utf-8")), encoding="utf-8")
    monkeypatch.setattr(module, "SOURCE", source)
    monkeypatch.setattr(module, "TARGET", target)
    assert module.main(["--check"]) == 0, "control: an untouched pair is in sync"

    target.write_text(target.read_text(encoding="utf-8").replace(
        "/scripts/check_claims.py @cryogenic22", ""), encoding="utf-8")
    assert module.main(["--check"]) == 1, "a protected path removed from CODEOWNERS must fail"


def test_check_rejects_a_surface_that_grew_without_regeneration(tmp_path, monkeypatch):
    """VIOLATION: the surface gains a path but CODEOWNERS is not regenerated."""
    module = load()
    source = tmp_path / "protected-surface.txt"
    source.write_text("/CLAUDE.md\n", encoding="utf-8")
    target = tmp_path / "CODEOWNERS"
    target.write_text(module.render(source.read_text(encoding="utf-8")), encoding="utf-8")
    monkeypatch.setattr(module, "SOURCE", source)
    monkeypatch.setattr(module, "TARGET", target)

    source.write_text("/CLAUDE.md\n/tests/test_negation_preservation.py\n", encoding="utf-8")
    assert module.main(["--check"]) == 1


def test_empty_surface_is_refused_not_silently_accepted(tmp_path, monkeypatch):
    """VIOLATION: emptying the surface would protect nothing while still passing.

    Absent-vs-zero: an empty protected surface is a missing guarantee, never a
    satisfied one.
    """
    module = load()
    source = tmp_path / "protected-surface.txt"
    source.write_text("# only comments\n\n", encoding="utf-8")
    target = tmp_path / "CODEOWNERS"
    target.write_text("", encoding="utf-8")
    monkeypatch.setattr(module, "SOURCE", source)
    monkeypatch.setattr(module, "TARGET", target)
    assert module.main(["--check"]) == 1


def test_missing_codeowners_fails_loud(tmp_path, monkeypatch):
    """VIOLATION: deleting CODEOWNERS must fail, not report success."""
    module = load()
    source = tmp_path / "protected-surface.txt"
    source.write_text("/CLAUDE.md\n", encoding="utf-8")
    monkeypatch.setattr(module, "SOURCE", source)
    monkeypatch.setattr(module, "TARGET", tmp_path / "does-not-exist")
    assert module.main(["--check"]) == 1


def test_missing_source_fails_loud(tmp_path, monkeypatch):
    """VIOLATION: deleting the source list must fail rather than pass vacuously."""
    module = load()
    monkeypatch.setattr(module, "SOURCE", tmp_path / "absent.txt")
    monkeypatch.setattr(module, "TARGET", tmp_path / "CODEOWNERS")
    assert module.main(["--check"]) == 1


@pytest.mark.parametrize("path", [
    "/CLAUDE.md",
    "/.claude/rules/",
    "/.github/workflows/",
    "/scripts/check_claims.py",
    "/harness/structural-floor/",
    "/tests/test_negation_preservation.py",
    "/tests/test_p0_trust_repairs.py",
])
def test_success_definition_surface_is_actually_covered(path):
    """The doctrine names these as the bar. They must be in the surface.

    Regression pin: catches a future edit that quietly narrows what is protected.
    """
    source = (ROOT / "harness" / "structural-floor" / "protected-surface.txt")
    assert path in load().patterns(source.read_text(encoding="utf-8")), (
        f"{path} is part of the success-definition surface but is not protected")
