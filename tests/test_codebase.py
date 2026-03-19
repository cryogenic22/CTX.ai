"""Tests for ctxpack.modules.codebase — codebase context compiler.

Uses ACTUAL Scriptiva_SCA files at C:/Users/kapil/Scriptiva_SCA.
"""

from __future__ import annotations

import os
import pathlib
import pytest

# The target codebase — must exist for integration tests
SCRIPTIVA_ROOT = pathlib.Path("C:/Users/kapil/Scriptiva_SCA")
PYTHON_SRC = SCRIPTIVA_ROOT / "apps" / "api" / "app"
TS_SRC = SCRIPTIVA_ROOT / "apps" / "web"

# Skip entire module if Scriptiva_SCA is not present
pytestmark = pytest.mark.skipif(
    not SCRIPTIVA_ROOT.exists(),
    reason="Scriptiva_SCA codebase not found at C:/Users/kapil/Scriptiva_SCA",
)

from ctxpack.modules.codebase import (
    ModuleInfo,
    CodebaseMap,
    analyze_python_source,
    analyze_typescript_source,
    analyze_codebase,
    export_claude_md,
    export_agents_md,
    export_rules,
)


# ─────────────────────────────────────────────────────────────────────────────
# Part 1: Python source analyzer
# ─────────────────────────────────────────────────────────────────────────────


class TestPythonAnalyzerFindsFastapiRoutes:
    """The analyzer must discover FastAPI route decorators."""

    def test_finds_auth_routes(self):
        cmap = analyze_python_source(str(PYTHON_SRC))
        # auth.py defines @router.post("/login"), @router.post("/refresh"), etc.
        route_modules = [m for m in cmap.modules if m.routes]
        assert len(route_modules) > 0, "Should find at least one module with routes"

        # Flatten all routes
        all_routes = []
        for m in cmap.modules:
            all_routes.extend(m.routes)
        # The auth route file has POST /login
        assert any("login" in r for r in all_routes), (
            f"Should find /login route, got: {all_routes[:20]}"
        )

    def test_finds_products_routes(self):
        cmap = analyze_python_source(str(PYTHON_SRC))
        all_routes = []
        for m in cmap.modules:
            all_routes.extend(m.routes)
        # products.py has routes under /v1/products
        assert any("product" in r.lower() for r in all_routes), (
            f"Should find products routes, got: {all_routes[:20]}"
        )

    def test_finds_multiple_route_files(self):
        cmap = analyze_python_source(str(PYTHON_SRC))
        route_modules = [m for m in cmap.modules if m.routes]
        # Scriptiva has 70+ route files
        assert len(route_modules) >= 10, (
            f"Should find >=10 route modules, got {len(route_modules)}"
        )


class TestPythonAnalyzerFindsSqlalchemyModels:
    """The analyzer must discover SQLAlchemy model classes."""

    def test_finds_product_model(self):
        cmap = analyze_python_source(str(PYTHON_SRC))
        all_models = []
        for m in cmap.modules:
            all_models.extend(m.models)
        assert "Product" in all_models, (
            f"Should find Product model, got: {all_models[:20]}"
        )

    def test_finds_component_model(self):
        cmap = analyze_python_source(str(PYTHON_SRC))
        all_models = []
        for m in cmap.modules:
            all_models.extend(m.models)
        assert "Component" in all_models, (
            f"Should find Component model, got: {all_models[:20]}"
        )

    def test_finds_multiple_models(self):
        cmap = analyze_python_source(str(PYTHON_SRC))
        all_models = []
        for m in cmap.modules:
            all_models.extend(m.models)
        # Scriptiva has 50+ models across core.py, content.py, authoring.py, etc.
        assert len(all_models) >= 20, (
            f"Should find >=20 models, got {len(all_models)}"
        )


class TestPythonAnalyzerFindsServices:
    """The analyzer must discover service modules and their functions."""

    def test_finds_service_modules(self):
        cmap = analyze_python_source(str(PYTHON_SRC))
        service_modules = [
            m for m in cmap.modules if "services" in m.path
        ]
        assert len(service_modules) >= 5, (
            f"Should find >=5 service modules, got {len(service_modules)}"
        )

    def test_service_modules_have_functions(self):
        cmap = analyze_python_source(str(PYTHON_SRC))
        service_modules = [
            m for m in cmap.modules if "services" in m.path
        ]
        modules_with_funcs = [m for m in service_modules if m.functions]
        assert len(modules_with_funcs) >= 3, (
            f"Should find >=3 service modules with functions, got {len(modules_with_funcs)}"
        )


class TestPythonAnalyzerCountsTests:
    """The analyzer must count test functions in test files."""

    def test_finds_test_files(self):
        # Scan the tests directory
        tests_dir = str(SCRIPTIVA_ROOT / "apps" / "api" / "tests")
        cmap = analyze_python_source(tests_dir)
        test_modules = [m for m in cmap.modules if m.test_count > 0]
        assert len(test_modules) >= 10, (
            f"Should find >=10 test modules, got {len(test_modules)}"
        )

    def test_counts_test_functions(self):
        tests_dir = str(SCRIPTIVA_ROOT / "apps" / "api" / "tests")
        cmap = analyze_python_source(tests_dir)
        total_tests = sum(m.test_count for m in cmap.modules)
        # Scriptiva has 210 test files — should have lots of test functions
        assert total_tests >= 100, (
            f"Should find >=100 test functions, got {total_tests}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Part 2: TypeScript source scanner
# ─────────────────────────────────────────────────────────────────────────────


class TestTypescriptAnalyzerFindsReactComponents:
    """The analyzer must discover React components from exports."""

    def test_finds_components(self):
        cmap = analyze_typescript_source(str(TS_SRC))
        all_classes = []
        for m in cmap.modules:
            all_classes.extend(m.classes)
        # AppShell, SideNav, TopBar, AuthGate etc.
        assert any("AppShell" in c for c in all_classes), (
            f"Should find AppShell component, got: {all_classes[:20]}"
        )

    def test_finds_multiple_components(self):
        cmap = analyze_typescript_source(str(TS_SRC))
        all_classes = []
        for m in cmap.modules:
            all_classes.extend(m.classes)
        assert len(all_classes) >= 10, (
            f"Should find >=10 React components, got {len(all_classes)}"
        )


class TestTypescriptAnalyzerFindsNextjsRoutes:
    """The analyzer must discover Next.js routes from app/ directory structure."""

    def test_finds_routes_from_app_dir(self):
        cmap = analyze_typescript_source(str(TS_SRC))
        all_routes = []
        for m in cmap.modules:
            all_routes.extend(m.routes)
        # app/products/page.tsx → /products
        assert any("products" in r for r in all_routes), (
            f"Should find /products route, got: {all_routes[:20]}"
        )

    def test_finds_multiple_routes(self):
        cmap = analyze_typescript_source(str(TS_SRC))
        all_routes = []
        for m in cmap.modules:
            all_routes.extend(m.routes)
        # dashboard, components, claims, products, etc.
        assert len(all_routes) >= 5, (
            f"Should find >=5 Next.js routes, got {len(all_routes)}"
        )


class TestTypescriptAnalyzerFindsExports:
    """The analyzer must discover exported functions/types/interfaces."""

    def test_finds_exported_functions(self):
        cmap = analyze_typescript_source(str(TS_SRC))
        all_funcs = []
        for m in cmap.modules:
            all_funcs.extend(m.functions)
        assert len(all_funcs) >= 10, (
            f"Should find >=10 exported functions, got {len(all_funcs)}"
        )

    def test_finds_type_exports(self):
        cmap = analyze_typescript_source(str(TS_SRC))
        # Types/interfaces are tracked as classes
        all_classes = []
        for m in cmap.modules:
            all_classes.extend(m.classes)
        assert len(all_classes) >= 10, (
            f"Should find >=10 exported types/components, got {len(all_classes)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Part 3: Full codebase map
# ─────────────────────────────────────────────────────────────────────────────


class TestCodebaseMapHasFrameworkDetection:
    """analyze_codebase() must detect frameworks from imports and file patterns."""

    def test_detects_fastapi(self):
        cmap = analyze_codebase(str(SCRIPTIVA_ROOT))
        assert "FastAPI" in cmap.frameworks, (
            f"Should detect FastAPI, got: {cmap.frameworks}"
        )

    def test_detects_nextjs(self):
        cmap = analyze_codebase(str(SCRIPTIVA_ROOT))
        assert "Next.js" in cmap.frameworks, (
            f"Should detect Next.js, got: {cmap.frameworks}"
        )

    def test_detects_sqlalchemy(self):
        cmap = analyze_codebase(str(SCRIPTIVA_ROOT))
        assert "SQLAlchemy" in cmap.frameworks, (
            f"Should detect SQLAlchemy, got: {cmap.frameworks}"
        )

    def test_detects_monorepo_architecture(self):
        cmap = analyze_codebase(str(SCRIPTIVA_ROOT))
        assert "monorepo" in cmap.architecture.lower(), (
            f"Should detect monorepo architecture, got: {cmap.architecture}"
        )

    def test_total_files_reasonable(self):
        cmap = analyze_codebase(str(SCRIPTIVA_ROOT))
        # 511 Python + 611 TypeScript ≈ 1100+
        assert cmap.total_files >= 100, (
            f"Should find >=100 total files, got {cmap.total_files}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Part 4: Export formats
# ─────────────────────────────────────────────────────────────────────────────


class TestExportClaudeMd:
    """CLAUDE.md export must be concise and structured."""

    @pytest.fixture()
    def cmap(self):
        return analyze_codebase(str(SCRIPTIVA_ROOT))

    def test_under_200_lines(self, cmap):
        md = export_claude_md(cmap, max_lines=200)
        line_count = len(md.strip().splitlines())
        assert line_count <= 200, (
            f"CLAUDE.md must be <=200 lines, got {line_count}"
        )

    def test_has_architecture_section(self, cmap):
        md = export_claude_md(cmap)
        assert "## Architecture" in md or "## architecture" in md.lower(), (
            "CLAUDE.md must have an Architecture section"
        )

    def test_has_module_map(self, cmap):
        md = export_claude_md(cmap)
        lower = md.lower()
        assert "module" in lower or "directory" in lower or "structure" in lower, (
            "CLAUDE.md must have a module/directory map section"
        )

    def test_has_routes(self, cmap):
        md = export_claude_md(cmap)
        lower = md.lower()
        assert "route" in lower or "api" in lower or "endpoint" in lower, (
            "CLAUDE.md must mention API routes/endpoints"
        )

    def test_has_models(self, cmap):
        md = export_claude_md(cmap)
        lower = md.lower()
        assert "model" in lower or "schema" in lower, (
            "CLAUDE.md must mention data models"
        )

    def test_merge_with_existing(self, cmap):
        existing = "# Existing CLAUDE.md\n\nSome hand-written content.\n"
        md = export_claude_md(cmap, existing_claude_md=existing)
        # Should reference or preserve existing content
        assert len(md.strip()) > 0

    def test_nonempty_output(self, cmap):
        md = export_claude_md(cmap)
        assert len(md.strip()) > 100, "CLAUDE.md should have substantial content"


class TestExportAgentsMd:
    """AGENTS.md export must include build/run commands."""

    @pytest.fixture()
    def cmap(self):
        return analyze_codebase(str(SCRIPTIVA_ROOT))

    def test_has_build_commands(self, cmap):
        md = export_agents_md(cmap)
        lower = md.lower()
        assert any(kw in lower for kw in ["build", "run", "start", "install", "npm", "pip"]), (
            "AGENTS.md must mention build/run commands"
        )

    def test_under_200_lines(self, cmap):
        md = export_agents_md(cmap, max_lines=200)
        line_count = len(md.strip().splitlines())
        assert line_count <= 200, (
            f"AGENTS.md must be <=200 lines, got {line_count}"
        )

    def test_has_structure(self, cmap):
        md = export_agents_md(cmap)
        # Should have markdown headers
        assert "##" in md, "AGENTS.md must have section headers"

    def test_nonempty_output(self, cmap):
        md = export_agents_md(cmap)
        assert len(md.strip()) > 50, "AGENTS.md should have substantial content"


# ─────────────────────────────────────────────────────────────────────────────
# Part 5: Rules export
# ─────────────────────────────────────────────────────────────────────────────


class TestExportRules:
    """export_rules() must generate path-scoped rule files."""

    @pytest.fixture()
    def cmap(self):
        return analyze_codebase(str(SCRIPTIVA_ROOT))

    def test_generates_rule_files(self, cmap, tmp_path):
        files = export_rules(cmap, str(tmp_path))
        assert len(files) >= 1, "Should generate at least one rule file"

    def test_rule_files_have_frontmatter(self, cmap, tmp_path):
        files = export_rules(cmap, str(tmp_path))
        for fpath in files:
            content = pathlib.Path(fpath).read_text(encoding="utf-8")
            assert content.startswith("---"), (
                f"Rule file {fpath} must start with YAML frontmatter"
            )
            assert "alwaysApply:" in content or "globs:" in content, (
                f"Rule file {fpath} must have frontmatter fields"
            )

    def test_rule_files_have_content(self, cmap, tmp_path):
        files = export_rules(cmap, str(tmp_path))
        for fpath in files:
            content = pathlib.Path(fpath).read_text(encoding="utf-8")
            # After frontmatter, there should be actual content
            parts = content.split("---", 2)
            assert len(parts) >= 3, f"Rule file {fpath} must have frontmatter delimiters"
            body = parts[2].strip()
            assert len(body) > 10, f"Rule file {fpath} must have body content"
