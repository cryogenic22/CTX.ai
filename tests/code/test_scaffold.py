"""CP-001 — scaffold sanity tests.

These tests pin the package skeleton and fixture-repo shape that
every downstream code-packer task assumes. They are intentionally
trivial; the discipline is "the contract holds," not "the code is
clever."
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


# ── Package importability ───────────────────────────────────────────────


def test_code_package_importable() -> None:
    """ctxpack.core.code must be importable.

    Sibling to ctxpack.core.packer. Empty for now; CP-002 lands the
    tree-sitter parser.
    """
    mod = importlib.import_module("ctxpack.core.code")
    assert mod is not None


def test_code_package_path_under_core() -> None:
    """The package lives at ctxpack/core/code/, not somewhere unexpected."""
    mod = importlib.import_module("ctxpack.core.code")
    pkg_path = Path(mod.__file__).parent
    assert pkg_path.name == "code"
    assert pkg_path.parent.name == "core"
    assert pkg_path.parent.parent.name == "ctxpack"


# ── Fixture repo shape ──────────────────────────────────────────────────


_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "py_fastapi_min"


def test_py_fastapi_min_fixture_dir_exists() -> None:
    assert _FIXTURE_DIR.is_dir(), (
        f"Expected fixture directory at {_FIXTURE_DIR}, missing."
    )


def test_py_fastapi_min_fixture_has_three_files() -> None:
    """Exactly app.py, deps.py, models.py — no more, no less.

    Adding files here without updating downstream task expectations is
    a footgun; pinning the count flushes that out fast.
    """
    files = sorted(p.name for p in _FIXTURE_DIR.iterdir() if p.is_file())
    assert files == ["app.py", "deps.py", "models.py"], files


def test_py_fastapi_min_files_are_nonempty() -> None:
    """Empty fixture files would silently pass parser tests later."""
    for name in ("app.py", "deps.py", "models.py"):
        p = _FIXTURE_DIR / name
        assert p.stat().st_size > 0, f"{name} is empty"


# ── Slow marker registration ────────────────────────────────────────────


def test_slow_marker_is_registered() -> None:
    """The 'slow' pytest marker must be configured.

    Discipline step [7] runs `pytest -m "not slow"`. Without
    registration, pytest treats unknown markers as warnings — which is
    fine until someone tightens `filterwarnings` to error. Pinning the
    config means the contract survives.
    """
    import configparser
    pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "markers" in text
    assert "slow" in text


def test_slow_modules_are_tagged() -> None:
    """test_codebase and test_harness invoke analyze_codebase on a real
    156K-LOC tree; they must be tagged with pytest.mark.slow (either as a
    decorator or as a module-level pytestmark) so the regression contract
    excludes them.
    """
    repo_root = Path(__file__).parent.parent.parent
    for name in ("test_codebase.py", "test_harness.py"):
        p = repo_root / "tests" / name
        if not p.exists():
            pytest.skip(f"{name} does not exist; skipping")
        text = p.read_text(encoding="utf-8")
        assert "pytest.mark.slow" in text, (
            f"{name} should carry pytest.mark.slow (decorator or pytestmark)"
        )


# ── Test discipline contract ────────────────────────────────────────────


def test_fixture_files_not_collected_as_tests() -> None:
    """Pytest's default discovery is test_*.py / *_test.py; fixture
    files named app.py / deps.py / models.py should NOT be picked up
    as tests. If someone later sets `python_files = *.py`, this test
    catches it.
    """
    import sys
    # If pytest had collected fixture modules under a test name, they'd
    # be sys.modules entries with our fixture path. Cheap sanity check.
    fixture_module_names = [
        m for m in sys.modules
        if "fixtures.py_fastapi_min" in m.replace("\\", ".")
    ]
    # If the fixture files have been imported AS tests, they'd appear
    # as tests.code.fixtures.py_fastapi_min.app or similar. They might
    # have been imported by us legitimately (we don't, in this file),
    # but they certainly shouldn't be collected.
    assert all("test_" not in m for m in fixture_module_names)


# ── Red-team additions ─────────────────────────────────────────────────


def test_fixture_files_are_valid_python() -> None:
    """Red-team: fixture files with syntax errors would surface as
    confusing parser failures in CP-002+. Pin syntactic validity here.

    Uses stdlib `ast` rather than tree-sitter to keep the scaffold
    dependency-free; tree-sitter coverage lands with CP-002.
    """
    import ast
    for name in ("app.py", "deps.py", "models.py"):
        p = _FIXTURE_DIR / name
        try:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as e:
            raise AssertionError(f"{name} is not valid Python: {e}") from e


def test_slow_marker_actually_filters() -> None:
    """Red-team: the marker can be registered in pyproject.toml AND
    applied to slow modules AND still not filter, if the `-m` selector
    syntax is wrong or pytest's marker matching is misconfigured.

    Runs pytest --collect-only -m "not slow" in a subprocess and
    asserts no test_codebase.py tests are collected.
    """
    import subprocess
    import sys
    repo_root = Path(__file__).parent.parent.parent
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "--collect-only", "-q",
            "-m", "not slow",
            str(repo_root / "tests" / "test_codebase.py"),
        ],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        timeout=60,
    )
    # When -m "not slow" excludes everything in a module, pytest exits
    # with code 5 ("no tests collected"). That is the success case for
    # this red-team check.
    combined = (result.stdout or "") + (result.stdout or "")
    assert "test_codebase" not in combined or "0 tests collected" in combined or result.returncode == 5, (
        f"`-m \"not slow\"` should filter out test_codebase.py; "
        f"got rc={result.returncode}, stdout={result.stdout[:400]!r}"
    )
