"""Tests for ctxpack codebase harness generator.

Uses ACTUAL Scriptiva_SCA at C:/Users/kapil/Scriptiva_SCA to validate
that the harness generator produces codebase-specific anti-drift rules.
"""

from __future__ import annotations

import ast
import os
import pathlib
import shutil
import tempfile

import pytest

# The target codebase — must exist for integration tests
SCRIPTIVA_ROOT = pathlib.Path("C:/Users/kapil/Scriptiva_SCA")

# Skip entire module if Scriptiva_SCA is not present
pytestmark = pytest.mark.skipif(
    not SCRIPTIVA_ROOT.exists(),
    reason="Scriptiva_SCA codebase not found at C:/Users/kapil/Scriptiva_SCA",
)

from ctxpack.modules.codebase import generate_harness


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_output(tmp_path):
    """Provide a temporary output directory for harness files."""
    output = tmp_path / ".claude"
    return str(output)


@pytest.fixture
def harness_files(tmp_output):
    """Generate harness once and return (file_list, output_dir)."""
    files = generate_harness(
        str(SCRIPTIVA_ROOT),
        output_dir=tmp_output,
        include_hooks=True,
        include_rules=True,
    )
    return files, tmp_output


# ─────────────────────────────────────────────────────────────────────────────
# Anti-slop rules
# ─────────────────────────────────────────────────────────────────────────────


class TestAntiSlopRules:
    """The anti-slop rules file must reference actual codebase paths."""

    def test_harness_generates_anti_slop_rules(self, harness_files):
        files, output_dir = harness_files
        anti_slop = os.path.join(output_dir, "rules", "anti-slop.md")
        assert anti_slop in files, f"anti-slop.md not in generated files: {files}"
        assert os.path.isfile(anti_slop)

    def test_anti_slop_lists_actual_utilities(self, harness_files):
        files, output_dir = harness_files
        anti_slop = os.path.join(output_dir, "rules", "anti-slop.md")
        content = pathlib.Path(anti_slop).read_text(encoding="utf-8")

        # Scriptiva_SCA has core/ with audit.py, pagination.py, etc.
        assert "core/" in content, "Should list core/ utilities"
        # It also has lib/ in the web app
        assert "lib/" in content, "Should list lib/ utilities"

    def test_anti_slop_includes_route_patterns(self, harness_files):
        files, output_dir = harness_files
        anti_slop = os.path.join(output_dir, "rules", "anti-slop.md")
        content = pathlib.Path(anti_slop).read_text(encoding="utf-8")

        # Must mention route patterns detected from the actual codebase
        assert "APIRouter" in content or "router" in content.lower(), \
            "Should mention FastAPI router pattern"
        assert "prefix" in content.lower(), \
            "Should mention route prefix pattern"

    def test_anti_slop_includes_model_patterns(self, harness_files):
        files, output_dir = harness_files
        anti_slop = os.path.join(output_dir, "rules", "anti-slop.md")
        content = pathlib.Path(anti_slop).read_text(encoding="utf-8")

        # Must mention model patterns from actual codebase
        assert "Base" in content, "Should mention Base class"
        assert "Mapped" in content or "mapped_column" in content, \
            "Should mention Mapped type annotations"
        assert "created_at" in content or "updated_at" in content, \
            "Should mention timestamp columns"

    def test_anti_slop_includes_import_patterns(self, harness_files):
        files, output_dir = harness_files
        anti_slop = os.path.join(output_dir, "rules", "anti-slop.md")
        content = pathlib.Path(anti_slop).read_text(encoding="utf-8")

        # Must list commonly imported modules
        assert "fastapi" in content.lower() or "sqlalchemy" in content.lower(), \
            "Should list common imports"

    def test_anti_slop_under_100_lines(self, harness_files):
        files, output_dir = harness_files
        anti_slop = os.path.join(output_dir, "rules", "anti-slop.md")
        content = pathlib.Path(anti_slop).read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert len(lines) <= 100, f"anti-slop.md has {len(lines)} lines, max 100"


# ─────────────────────────────────────────────────────────────────────────────
# Test requirements rules
# ─────────────────────────────────────────────────────────────────────────────


class TestTestRequirements:
    """Test requirements file must detect actual test frameworks."""

    def test_test_requirements_detects_pytest(self, harness_files):
        files, output_dir = harness_files
        test_req = os.path.join(output_dir, "rules", "test-requirements.md")
        content = pathlib.Path(test_req).read_text(encoding="utf-8")

        assert "pytest" in content.lower(), \
            "Should detect pytest from pyproject.toml"

    def test_test_requirements_detects_vitest(self, harness_files):
        files, output_dir = harness_files
        test_req = os.path.join(output_dir, "rules", "test-requirements.md")
        content = pathlib.Path(test_req).read_text(encoding="utf-8")

        assert "vitest" in content.lower(), \
            "Should detect vitest from vitest.config.ts"

    def test_test_requirements_has_path_scoping(self, harness_files):
        files, output_dir = harness_files
        test_req = os.path.join(output_dir, "rules", "test-requirements.md")
        content = pathlib.Path(test_req).read_text(encoding="utf-8")

        # Must have YAML frontmatter with path scoping
        assert content.startswith("---"), "Should have YAML frontmatter"
        assert "globs:" in content or "paths:" in content, \
            "Should have path scoping in frontmatter"

    def test_test_requirements_detects_coverage(self, harness_files):
        files, output_dir = harness_files
        test_req = os.path.join(output_dir, "rules", "test-requirements.md")
        content = pathlib.Path(test_req).read_text(encoding="utf-8")

        # pyproject.toml has --cov-fail-under=40
        assert "40" in content or "coverage" in content.lower(), \
            "Should detect coverage requirement"

    def test_test_requirements_under_100_lines(self, harness_files):
        files, output_dir = harness_files
        test_req = os.path.join(output_dir, "rules", "test-requirements.md")
        content = pathlib.Path(test_req).read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert len(lines) <= 100, f"test-requirements.md has {len(lines)} lines, max 100"


# ─────────────────────────────────────────────────────────────────────────────
# Commit conventions rules
# ─────────────────────────────────────────────────────────────────────────────


class TestCommitConventions:
    """Commit conventions must detect patterns from git log."""

    def test_commit_conventions_detects_format(self, harness_files):
        files, output_dir = harness_files
        commit_conv = os.path.join(output_dir, "rules", "commit-conventions.md")
        assert commit_conv in files
        content = pathlib.Path(commit_conv).read_text(encoding="utf-8")

        # Scriptiva_SCA uses conventional commits: feat, fix, chore, docs
        assert "feat" in content.lower() or "fix" in content.lower(), \
            "Should detect conventional commit prefixes"

    def test_commit_conventions_under_100_lines(self, harness_files):
        files, output_dir = harness_files
        commit_conv = os.path.join(output_dir, "rules", "commit-conventions.md")
        content = pathlib.Path(commit_conv).read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert len(lines) <= 100, f"commit-conventions.md has {len(lines)} lines, max 100"


# ─────────────────────────────────────────────────────────────────────────────
# Quality hook
# ─────────────────────────────────────────────────────────────────────────────


class TestQualityHook:
    """Quality hook must be a standalone, valid Python script."""

    def test_quality_hook_is_valid_python(self, harness_files):
        files, output_dir = harness_files
        hook = os.path.join(output_dir, "hooks", "quality-check.py")
        assert hook in files, f"quality-check.py not in generated files: {files}"

        source = pathlib.Path(hook).read_text(encoding="utf-8")
        # Must parse without errors
        tree = ast.parse(source)
        assert tree is not None

    def test_quality_hook_has_no_ctxpack_imports(self, harness_files):
        files, output_dir = harness_files
        hook = os.path.join(output_dir, "hooks", "quality-check.py")
        source = pathlib.Path(hook).read_text(encoding="utf-8")

        # Must not import ctxpack
        assert "ctxpack" not in source, \
            "quality-check.py must be standalone — no ctxpack imports"

    def test_quality_hook_checks_type_annotations(self, harness_files):
        files, output_dir = harness_files
        hook = os.path.join(output_dir, "hooks", "quality-check.py")
        source = pathlib.Path(hook).read_text(encoding="utf-8")

        assert "annotation" in source.lower() or "type" in source.lower(), \
            "Hook should check for type annotations"

    def test_quality_hook_checks_file_length(self, harness_files):
        files, output_dir = harness_files
        hook = os.path.join(output_dir, "hooks", "quality-check.py")
        source = pathlib.Path(hook).read_text(encoding="utf-8")

        assert "500" in source, \
            "Hook should check for 500-line file limit"


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests
# ─────────────────────────────────────────────────────────────────────────────


class TestHarnessIntegration:
    """End-to-end integration for the harness generator."""

    def test_harness_creates_files_in_output_dir(self, harness_files):
        files, output_dir = harness_files

        # All returned paths must exist and be under output_dir
        for f in files:
            assert os.path.isfile(f), f"Generated file does not exist: {f}"
            assert f.startswith(output_dir), \
                f"File {f} is not under output dir {output_dir}"

    def test_harness_does_not_overwrite_existing_rules(self, tmp_path):
        """If a rules file already exists, don't overwrite it."""
        output_dir = str(tmp_path / ".claude")
        rules_dir = os.path.join(output_dir, "rules")
        os.makedirs(rules_dir, exist_ok=True)

        # Create an existing rule file with custom content
        existing_file = os.path.join(rules_dir, "anti-slop.md")
        original_content = "# My custom anti-slop rules\nDo not touch!"
        with open(existing_file, "w", encoding="utf-8") as f:
            f.write(original_content)

        # Generate harness
        files = generate_harness(
            str(SCRIPTIVA_ROOT),
            output_dir=output_dir,
        )

        # The existing file should NOT be overwritten
        with open(existing_file, encoding="utf-8") as f:
            content = f.read()
        assert content == original_content, \
            "Existing rule file was overwritten!"

        # The file should NOT be in the returned list (it was skipped)
        assert existing_file not in files, \
            "Existing file should not appear in generated files list"

    def test_harness_returns_expected_file_count(self, harness_files):
        files, _ = harness_files
        # 3 rules + 1 hook = 4 files minimum
        assert len(files) >= 4, \
            f"Expected at least 4 files, got {len(files)}: {files}"

    def test_harness_respects_include_hooks_false(self, tmp_output):
        files = generate_harness(
            str(SCRIPTIVA_ROOT),
            output_dir=tmp_output,
            include_hooks=False,
            include_rules=True,
        )
        hook_files = [f for f in files if "hooks" in f]
        assert len(hook_files) == 0, \
            f"Should not generate hooks when include_hooks=False: {hook_files}"

    def test_harness_respects_include_rules_false(self, tmp_output):
        files = generate_harness(
            str(SCRIPTIVA_ROOT),
            output_dir=tmp_output,
            include_hooks=True,
            include_rules=False,
        )
        rule_files = [f for f in files if "rules" in f]
        assert len(rule_files) == 0, \
            f"Should not generate rules when include_rules=False: {rule_files}"
