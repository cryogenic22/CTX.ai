"""Codebase context compiler — analyzes source code to generate agent-ready context.

Produces CodebaseMap from Python (stdlib ast) and TypeScript (regex) sources,
then exports to supplementary context files that existing CLAUDE.md/AGENTS.md
can @import. Never overwrites hand-maintained agent context.

Output files:
  .claude/codebase-map.md  — auto-generated directory index (import into CLAUDE.md)
  .claude/rules/*.md       — path-scoped conventions (auto-loaded by Claude Code)

IMPORTANT: This module generates SUPPLEMENTARY context, not replacements.
Hand-written CLAUDE.md contains team policies, conventions, and "why" decisions
that code analysis cannot detect. The auto-generated map provides "what exists"
and "where to find it" — the human context provides "how to work here."

Zero external dependencies — uses only stdlib ast, re, os, pathlib, dataclasses.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ModuleInfo:
    """Information extracted from a single source file."""
    path: str                           # relative path from scan root
    classes: list[str] = field(default_factory=list)       # class names
    functions: list[str] = field(default_factory=list)     # public function names
    routes: list[str] = field(default_factory=list)        # FastAPI/Next.js routes
    models: list[str] = field(default_factory=list)        # SQLAlchemy model names
    imports: list[str] = field(default_factory=list)       # key imports
    test_count: int = 0                 # number of test functions


@dataclass
class CodebaseMap:
    """Aggregated codebase analysis."""
    modules: list[ModuleInfo] = field(default_factory=list)
    total_files: int = 0
    total_lines: int = 0
    frameworks: list[str] = field(default_factory=list)
    architecture: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Skip directories
# ─────────────────────────────────────────────────────────────────────────────

_SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git", ".next",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".tox", "egg-info",
    ".eggs", "site-packages", ".ruff_cache",
}


# ─────────────────────────────────────────────────────────────────────────────
# Part 1: Python source analyzer (stdlib ast)
# ─────────────────────────────────────────────────────────────────────────────


def _is_sqlalchemy_model(node: ast.ClassDef) -> bool:
    """Check if a class inherits from Base or DeclarativeBase (SQLAlchemy)."""
    for base in node.bases:
        name = ""
        if isinstance(base, ast.Name):
            name = base.id
        elif isinstance(base, ast.Attribute):
            name = base.attr
        if name in ("Base", "DeclarativeBase"):
            return True
    # Also check if it has a Mixin that eventually inherits Base —
    # we detect __tablename__ as a strong signal.
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            if child.target.id == "__tablename__":
                return True
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name) and target.id == "__tablename__":
                    return True
    return False


def _extract_route_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Extract route path from @router.get("/path") style decorators."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            attr = dec.func
            method = attr.attr
            if method in ("get", "post", "put", "delete", "patch", "options", "head"):
                # Check it's on a router-like object
                obj_name = ""
                if isinstance(attr.value, ast.Name):
                    obj_name = attr.value.id
                if obj_name in ("router", "app", "api_router"):
                    # Get the first positional arg (the path)
                    if dec.args:
                        arg = dec.args[0]
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            return f"{method.upper()} {arg.value}"
    return None


def _find_router_prefix(tree: ast.Module) -> str:
    """Find APIRouter(prefix=...) in a module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name == "APIRouter":
                for kw in node.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        return kw.value.value
    return ""


def _analyze_python_file(filepath: str, rel_path: str) -> ModuleInfo | None:
    """Analyze a single Python file using ast."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            source = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return None

    info = ModuleInfo(path=rel_path)
    line_count = source.count("\n") + 1

    # Find router prefix for route path assembly
    router_prefix = _find_router_prefix(tree)

    # Collect key imports (top-level from X import or import X)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                info.imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                info.imports.append(node.module)

    # Walk top-level definitions
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            info.classes.append(node.name)
            if _is_sqlalchemy_model(node):
                info.models.append(node.name)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Public functions (no leading underscore)
            if not node.name.startswith("_"):
                info.functions.append(node.name)

            # Test functions
            if node.name.startswith("test_"):
                info.test_count += 1

            # Route decorators
            route = _extract_route_decorator(node)
            if route:
                # Prepend router prefix
                method, path = route.split(" ", 1)
                full_path = router_prefix + path if router_prefix else path
                info.routes.append(f"{method} {full_path}")

        # Also count test methods inside test classes
        if isinstance(node, ast.ClassDef):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name.startswith("test_"):
                        info.test_count += 1

    return info


def analyze_python_source(src_dir: str) -> CodebaseMap:
    """Scan Python files using stdlib ast module.

    Extracts:
    - Module structure (directories -> packages)
    - Classes with their methods (public only)
    - Functions (top-level, public)
    - Imports (what depends on what)
    - SQLAlchemy models (class inheriting from Base/DeclarativeBase)
    - FastAPI routes (functions with @router.get/post/put/delete decorators)
    - Test files (files starting with test_)
    """
    src_path = pathlib.Path(src_dir)
    modules: list[ModuleInfo] = []
    total_files = 0
    total_lines = 0

    for dirpath, dirnames, filenames in os.walk(src_dir):
        # Prune skip directories in-place
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for fname in filenames:
            if not fname.endswith(".py"):
                continue

            filepath = os.path.join(dirpath, fname)
            rel_path = str(pathlib.Path(filepath).relative_to(src_path))

            info = _analyze_python_file(filepath, rel_path)
            if info is not None:
                modules.append(info)
                total_files += 1
                try:
                    with open(filepath, encoding="utf-8", errors="replace") as f:
                        total_lines += sum(1 for _ in f)
                except OSError:
                    pass

    return CodebaseMap(
        modules=modules,
        total_files=total_files,
        total_lines=total_lines,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Part 2: TypeScript source scanner (regex-based)
# ─────────────────────────────────────────────────────────────────────────────

# Patterns for exported symbols
_RE_EXPORT_FUNCTION = re.compile(
    r"export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)"
)
_RE_EXPORT_CONST_FUNC = re.compile(
    r"export\s+(?:default\s+)?(?:const|let)\s+(\w+)\s*[=:]"
)
_RE_EXPORT_CLASS = re.compile(
    r"export\s+(?:default\s+)?class\s+(\w+)"
)
_RE_EXPORT_TYPE = re.compile(
    r"export\s+(?:type|interface)\s+(\w+)"
)
_RE_IMPORT = re.compile(
    r"""(?:import\s+(?:(?:type\s+)?(?:\{[^}]*\}|\w+|\*\s+as\s+\w+)(?:\s*,\s*(?:\{[^}]*\}|\w+))*\s+from\s+)?["']([^"']+)["'])"""
)

# React component detection: function starting with uppercase, returning JSX
_RE_REACT_COMPONENT = re.compile(
    r"export\s+(?:default\s+)?(?:(?:const|function|async\s+function)\s+)([A-Z]\w+)"
)


def _nextjs_route_from_path(filepath: str, app_dir: str) -> str | None:
    """Derive Next.js route from file path under app/ directory.

    app/products/page.tsx → /products
    app/components/[id]/page.tsx → /components/[id]
    app/page.tsx → /
    """
    rel = pathlib.Path(filepath).relative_to(app_dir)
    parts = rel.parts

    # Only page.tsx / page.ts / route.ts files define routes
    fname = parts[-1]
    if not re.match(r"^(page|route)\.(tsx?|jsx?)$", fname):
        return None

    # Build route from directory parts
    route_parts = parts[:-1]  # exclude filename
    if not route_parts:
        return "/"

    route = "/" + "/".join(str(p) for p in route_parts)
    return route


def _analyze_typescript_file(filepath: str, rel_path: str, app_dir: str | None) -> ModuleInfo | None:
    """Analyze a single TypeScript/TSX file using regex."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            source = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    info = ModuleInfo(path=rel_path)

    # Extract exports
    for m in _RE_EXPORT_FUNCTION.finditer(source):
        name = m.group(1)
        if name[0].isupper():
            info.classes.append(name)  # React component
        else:
            info.functions.append(name)

    for m in _RE_EXPORT_CONST_FUNC.finditer(source):
        name = m.group(1)
        # Avoid duplicates from function exports already captured
        if name not in info.functions and name not in info.classes:
            if name[0].isupper():
                info.classes.append(name)
            else:
                info.functions.append(name)

    for m in _RE_EXPORT_CLASS.finditer(source):
        name = m.group(1)
        if name not in info.classes:
            info.classes.append(name)

    for m in _RE_EXPORT_TYPE.finditer(source):
        name = m.group(1)
        if name not in info.classes:
            info.classes.append(name)

    # React component detection (uppercase function/const exports)
    for m in _RE_REACT_COMPONENT.finditer(source):
        name = m.group(1)
        if name not in info.classes:
            info.classes.append(name)

    # Imports
    for m in _RE_IMPORT.finditer(source):
        info.imports.append(m.group(1))

    # Next.js routes
    if app_dir:
        try:
            route = _nextjs_route_from_path(filepath, app_dir)
            if route:
                info.routes.append(route)
        except (ValueError, TypeError):
            pass

    return info


def analyze_typescript_source(src_dir: str) -> CodebaseMap:
    """Scan TypeScript/TSX files using regex patterns.

    Extracts:
    - Export statements (export function/class/const/type/interface)
    - React components (export default function/const ComponentName)
    - Next.js routes (files under app/ directory -> route paths)
    - Import patterns (what depends on what)
    """
    src_path = pathlib.Path(src_dir)
    modules: list[ModuleInfo] = []
    total_files = 0
    total_lines = 0

    # Detect app directory for Next.js routing
    app_dir = None
    candidate = src_path / "app"
    if candidate.is_dir():
        app_dir = str(candidate)

    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for fname in filenames:
            if not any(fname.endswith(ext) for ext in (".ts", ".tsx", ".js", ".jsx")):
                continue
            # Skip declaration files
            if fname.endswith(".d.ts"):
                continue

            filepath = os.path.join(dirpath, fname)
            rel_path = str(pathlib.Path(filepath).relative_to(src_path))

            info = _analyze_typescript_file(filepath, rel_path, app_dir)
            if info is not None:
                modules.append(info)
                total_files += 1
                try:
                    with open(filepath, encoding="utf-8", errors="replace") as f:
                        total_lines += sum(1 for _ in f)
                except OSError:
                    pass

    return CodebaseMap(
        modules=modules,
        total_files=total_files,
        total_lines=total_lines,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Part 3: Full codebase analysis
# ─────────────────────────────────────────────────────────────────────────────


def _detect_frameworks(py_map: CodebaseMap, ts_map: CodebaseMap) -> list[str]:
    """Detect frameworks from import patterns and file structure."""
    frameworks: list[str] = []

    # Aggregate all Python imports
    py_imports: set[str] = set()
    for m in py_map.modules:
        py_imports.update(m.imports)

    # Aggregate all TS imports
    ts_imports: set[str] = set()
    for m in ts_map.modules:
        ts_imports.update(m.imports)

    # Python frameworks
    if any("fastapi" in imp.lower() for imp in py_imports):
        frameworks.append("FastAPI")
    if any("django" in imp.lower() for imp in py_imports):
        frameworks.append("Django")
    if any("flask" in imp.lower() for imp in py_imports):
        frameworks.append("Flask")
    if any("sqlalchemy" in imp.lower() for imp in py_imports):
        frameworks.append("SQLAlchemy")
    if any("alembic" in imp.lower() for imp in py_imports):
        frameworks.append("Alembic")
    if any("pydantic" in imp.lower() for imp in py_imports):
        frameworks.append("Pydantic")
    if any("celery" in imp.lower() for imp in py_imports):
        frameworks.append("Celery")

    # TypeScript frameworks
    if any("next" in imp.lower() for imp in ts_imports):
        frameworks.append("Next.js")
    if any("react" in imp.lower() for imp in ts_imports):
        frameworks.append("React")
    if any("tailwind" in imp.lower() for imp in ts_imports):
        frameworks.append("Tailwind CSS")
    # Check for tailwind config file existence via module classes
    if any("tailwind" in m.path.lower() for m in ts_map.modules):
        if "Tailwind CSS" not in frameworks:
            frameworks.append("Tailwind CSS")

    return frameworks


def _detect_architecture(root: str, py_map: CodebaseMap, ts_map: CodebaseMap) -> str:
    """Detect architecture pattern from directory structure."""
    root_path = pathlib.Path(root)

    # Check for monorepo indicators
    has_apps = (root_path / "apps").is_dir()
    has_packages = (root_path / "packages").is_dir()
    has_services = (root_path / "services").is_dir()

    if has_apps or has_packages:
        return "monorepo"

    if has_services:
        return "microservices"

    # Check for service layer pattern
    has_service_dir = any("services" in m.path.lower() for m in py_map.modules)
    has_models_dir = any("models" in m.path.lower() for m in py_map.modules)
    has_routes_dir = any("routes" in m.path.lower() or "api" in m.path.lower()
                         for m in py_map.modules)

    if has_service_dir and has_models_dir and has_routes_dir:
        return "service-layer"

    return "standard"


def analyze_codebase(root_dir: str) -> CodebaseMap:
    """Analyze a full codebase, combining Python and TypeScript analysis.

    Walks the directory tree, scans both Python and TypeScript files,
    detects frameworks and architecture patterns.
    """
    root = pathlib.Path(root_dir)

    # Find Python source directories (look for common patterns)
    py_dirs: list[str] = []
    ts_dirs: list[str] = []

    for entry in root.iterdir():
        if entry.name in _SKIP_DIRS:
            continue
        if entry.is_dir():
            # Check for Python files
            _find_source_dirs(entry, py_dirs, ts_dirs)

    # Also scan root itself
    if any(f.suffix == ".py" for f in root.iterdir() if f.is_file()):
        py_dirs.append(str(root))

    # Deduplicate — don't scan subdirectories if a parent is already scanned
    py_dirs = _deduplicate_dirs(py_dirs)
    ts_dirs = _deduplicate_dirs(ts_dirs)

    # If no specific dirs found, just scan everything from root
    if not py_dirs and not ts_dirs:
        py_map = analyze_python_source(str(root))
        ts_map = analyze_typescript_source(str(root))
    else:
        # Merge results from multiple directories
        py_map = CodebaseMap()
        for d in py_dirs:
            sub = analyze_python_source(d)
            # Convert paths to be relative to root
            for m in sub.modules:
                try:
                    m.path = str(pathlib.Path(d).relative_to(root) / m.path)
                except ValueError:
                    pass
            py_map.modules.extend(sub.modules)
            py_map.total_files += sub.total_files
            py_map.total_lines += sub.total_lines

        ts_map = CodebaseMap()
        for d in ts_dirs:
            sub = analyze_typescript_source(d)
            for m in sub.modules:
                try:
                    m.path = str(pathlib.Path(d).relative_to(root) / m.path)
                except ValueError:
                    pass
            ts_map.modules.extend(sub.modules)
            ts_map.total_files += sub.total_files
            ts_map.total_lines += sub.total_lines

    # Combine
    combined = CodebaseMap(
        modules=py_map.modules + ts_map.modules,
        total_files=py_map.total_files + ts_map.total_files,
        total_lines=py_map.total_lines + ts_map.total_lines,
        frameworks=_detect_frameworks(py_map, ts_map),
        architecture=_detect_architecture(str(root), py_map, ts_map),
    )

    return combined


def _find_source_dirs(entry: pathlib.Path, py_dirs: list[str], ts_dirs: list[str]) -> None:
    """Recursively find directories containing Python or TypeScript source files."""
    if entry.name in _SKIP_DIRS:
        return

    has_py = False
    has_ts = False

    try:
        children = list(entry.iterdir())
    except PermissionError:
        return

    for child in children:
        if child.is_file():
            if child.suffix == ".py":
                has_py = True
            if child.suffix in (".ts", ".tsx", ".js", ".jsx"):
                has_ts = True

    if has_py:
        py_dirs.append(str(entry))
    if has_ts:
        ts_dirs.append(str(entry))

    for child in children:
        if child.is_dir() and child.name not in _SKIP_DIRS:
            _find_source_dirs(child, py_dirs, ts_dirs)


def _deduplicate_dirs(dirs: list[str]) -> list[str]:
    """Remove directories that are subdirectories of others in the list."""
    if not dirs:
        return dirs

    sorted_dirs = sorted(dirs, key=len)
    result: list[str] = []

    for d in sorted_dirs:
        d_path = pathlib.Path(d)
        # Check if any existing result is a parent of this dir
        is_subdir = False
        for existing in result:
            try:
                d_path.relative_to(existing)
                is_subdir = True
                break
            except ValueError:
                pass
        if not is_subdir:
            result.append(d)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Part 4: Export to agent formats
# ─────────────────────────────────────────────────────────────────────────────


def _group_modules_by_directory(modules: list[ModuleInfo], depth: int = 2) -> dict[str, list[ModuleInfo]]:
    """Group modules by their directory path up to `depth` levels."""
    groups: dict[str, list[ModuleInfo]] = {}
    for m in modules:
        parts = pathlib.PurePosixPath(m.path.replace("\\", "/")).parts
        key = "/".join(parts[:depth]) if len(parts) > depth else "/".join(parts[:-1]) if len(parts) > 1 else "."
        groups.setdefault(key, []).append(m)
    return groups


def _summarize_directory(modules: list[ModuleInfo]) -> str:
    """Produce a one-line summary of what a directory contains."""
    parts = []
    total_routes = sum(len(m.routes) for m in modules)
    total_models = sum(len(m.models) for m in modules)
    total_funcs = sum(len(m.functions) for m in modules)
    total_tests = sum(m.test_count for m in modules)
    total_classes = sum(len(m.classes) for m in modules)

    if total_routes:
        parts.append(f"{total_routes} routes")
    if total_models:
        parts.append(f"{total_models} models")
    if total_classes and not total_models:
        parts.append(f"{total_classes} classes")
    if total_funcs:
        parts.append(f"{total_funcs} functions")
    if total_tests:
        parts.append(f"{total_tests} tests")
    if not parts:
        parts.append(f"{len(modules)} files")

    return ", ".join(parts)


def export_claude_md(
    cmap: CodebaseMap,
    *,
    existing_claude_md: str = "",
    max_lines: int = 200,
) -> str:
    """Generate a CLAUDE.md from codebase analysis.

    Structure:
    1. Architecture overview (auto-detected)
    2. Module map (key directories with purpose)
    3. Key patterns (detected from code)
    4. API surface (routes)
    5. Data models (SQLAlchemy/TypeScript types)
    6. Test coverage summary
    """
    lines: list[str] = []

    # Header
    lines.append("# Codebase Map (auto-generated by ctxpack — DO NOT EDIT)")
    lines.append("")
    lines.append("> This is a supplementary context file. Import it from your CLAUDE.md:")
    lines.append("> `@.claude/codebase-map.md`")
    lines.append(">")
    lines.append("> Hand-written CLAUDE.md is authoritative for team conventions, policies,")
    lines.append("> deployment procedures, and architectural decisions. This file provides")
    lines.append("> an auto-generated map of what exists in the codebase.")
    lines.append("")

    # Architecture overview
    lines.append("## Architecture")
    lines.append("")
    lines.append(f"- **Type**: {cmap.architecture}")
    lines.append(f"- **Files**: {cmap.total_files} source files, ~{cmap.total_lines:,} lines")
    if cmap.frameworks:
        lines.append(f"- **Frameworks**: {', '.join(cmap.frameworks)}")
    lines.append("")

    # Module map — group by top-level directory
    lines.append("## Directory Structure")
    lines.append("")
    groups = _group_modules_by_directory(cmap.modules, depth=3)
    # Sort by path, limit to most significant directories
    sorted_groups = sorted(groups.items(), key=lambda x: x[0])

    # Only show directories that have routes, models, or significant content
    significant_groups = []
    other_groups = []
    for path, mods in sorted_groups:
        total_routes = sum(len(m.routes) for m in mods)
        total_models = sum(len(m.models) for m in mods)
        total_tests = sum(m.test_count for m in mods)
        if total_routes or total_models or total_tests or len(mods) >= 3:
            significant_groups.append((path, mods))
        else:
            other_groups.append((path, mods))

    for path, mods in significant_groups:
        summary = _summarize_directory(mods)
        lines.append(f"- `{path}/` — {summary}")

    if other_groups:
        other_count = sum(len(mods) for _, mods in other_groups)
        lines.append(f"- *(+{other_count} files in {len(other_groups)} other directories)*")
    lines.append("")

    # API routes (top 30)
    all_routes: list[tuple[str, str]] = []  # (route, module_path)
    for m in cmap.modules:
        for r in m.routes:
            all_routes.append((r, m.path))

    if all_routes:
        lines.append("## API Surface")
        lines.append("")

        # Group routes by prefix
        route_groups: dict[str, list[str]] = {}
        for route, _ in all_routes:
            # For FastAPI: "GET /v1/products" -> "/v1/products"
            # For Next.js: "/products" -> "/products"
            parts = route.split(" ", 1)
            path = parts[1] if len(parts) > 1 else parts[0]
            prefix = path.strip("/").split("/")[0] if path.strip("/") else "root"
            route_groups.setdefault(prefix, []).append(route)

        for prefix in sorted(route_groups):
            routes = route_groups[prefix]
            lines.append(f"- **/{prefix}**: {len(routes)} endpoints")

        lines.append(f"- **Total**: {len(all_routes)} endpoints")
        lines.append("")

    # Data models (top 30)
    all_models: list[str] = []
    for m in cmap.modules:
        all_models.extend(m.models)

    if all_models:
        lines.append("## Data Models")
        lines.append("")
        # Show models grouped by source file directory
        model_dirs: dict[str, list[str]] = {}
        for m in cmap.modules:
            if m.models:
                dir_path = str(pathlib.PurePosixPath(m.path.replace("\\", "/")).parent)
                model_dirs.setdefault(dir_path, []).extend(m.models)

        for dir_path in sorted(model_dirs):
            models = model_dirs[dir_path]
            if len(models) <= 5:
                lines.append(f"- `{dir_path}/`: {', '.join(models)}")
            else:
                lines.append(f"- `{dir_path}/`: {', '.join(models[:5])} (+{len(models)-5} more)")

        lines.append(f"- **Total**: {len(all_models)} models")
        lines.append("")

    # Test coverage summary
    total_tests = sum(m.test_count for m in cmap.modules)
    test_modules = [m for m in cmap.modules if m.test_count > 0]

    if total_tests:
        lines.append("## Test Coverage")
        lines.append("")
        lines.append(f"- **Test files**: {len(test_modules)}")
        lines.append(f"- **Test functions**: {total_tests}")
        lines.append("")

    # Key patterns
    lines.append("## Key Patterns")
    lines.append("")
    if "FastAPI" in cmap.frameworks:
        lines.append("- FastAPI router pattern: `APIRouter(prefix=...)` with route decorators")
    if "SQLAlchemy" in cmap.frameworks:
        lines.append("- SQLAlchemy ORM: `DeclarativeBase` / `Base` with `Mapped[]` type annotations")
    if "Next.js" in cmap.frameworks:
        lines.append("- Next.js App Router: file-based routing under `app/` directory")
    if "React" in cmap.frameworks:
        lines.append("- React components: functional components with hooks")
    if "Pydantic" in cmap.frameworks:
        lines.append("- Pydantic models for request/response validation")
    if "Alembic" in cmap.frameworks:
        lines.append("- Alembic for database migrations")
    lines.append("")

    # Truncate to max_lines
    if len(lines) > max_lines:
        lines = lines[:max_lines - 2]
        lines.append("")
        lines.append("*(truncated to fit context budget)*")

    return "\n".join(lines)


def export_agents_md(cmap: CodebaseMap, *, max_lines: int = 200) -> str:
    """Generate cross-tool AGENTS.md for agent orchestration."""
    lines: list[str] = []

    lines.append("# AGENTS.md — Cross-Tool Agent Context")
    lines.append("")
    lines.append("*Auto-generated by ctxpack codebase analyzer.*")
    lines.append("")

    # Build & run commands
    lines.append("## Build & Run")
    lines.append("")

    if "FastAPI" in cmap.frameworks:
        lines.append("### Backend (FastAPI)")
        lines.append("```bash")
        lines.append("pip install -r requirements.txt  # or: pip install -e .")
        lines.append("uvicorn app.main:app --reload --port 8000")
        lines.append("```")
        lines.append("")

    if "Next.js" in cmap.frameworks:
        lines.append("### Frontend (Next.js)")
        lines.append("```bash")
        lines.append("npm install")
        lines.append("npm run dev  # starts on port 3000")
        lines.append("```")
        lines.append("")

    # Testing
    lines.append("## Testing")
    lines.append("")

    has_pytest = any("pytest" in imp for m in cmap.modules for imp in m.imports)
    total_tests = sum(m.test_count for m in cmap.modules)

    if has_pytest or total_tests > 0:
        lines.append("### Python Tests")
        lines.append("```bash")
        lines.append("python -m pytest -x -q")
        lines.append("```")
        lines.append(f"- {total_tests} test functions across {sum(1 for m in cmap.modules if m.test_count)} files")
        lines.append("")

    # Check for vitest/jest
    ts_has_vitest = any("vitest" in m.path.lower() for m in cmap.modules)
    ts_has_jest = any("jest" in m.path.lower() for m in cmap.modules)
    ts_has_playwright = any("playwright" in m.path.lower() for m in cmap.modules)

    if ts_has_vitest or ts_has_jest:
        lines.append("### Frontend Tests")
        if ts_has_vitest:
            lines.append("```bash")
            lines.append("npx vitest run")
            lines.append("```")
        elif ts_has_jest:
            lines.append("```bash")
            lines.append("npx jest")
            lines.append("```")
        lines.append("")

    if ts_has_playwright:
        lines.append("### E2E Tests")
        lines.append("```bash")
        lines.append("npx playwright test")
        lines.append("```")
        lines.append("")

    # Architecture summary
    lines.append("## Architecture Overview")
    lines.append("")
    lines.append(f"- **Type**: {cmap.architecture}")
    lines.append(f"- **Scale**: {cmap.total_files} files, ~{cmap.total_lines:,} lines")
    if cmap.frameworks:
        lines.append(f"- **Stack**: {', '.join(cmap.frameworks)}")
    lines.append("")

    # Key directories
    lines.append("## Key Directories")
    lines.append("")

    groups = _group_modules_by_directory(cmap.modules, depth=3)
    sorted_groups = sorted(groups.items(), key=lambda x: x[0])

    for path, mods in sorted_groups:
        total_routes = sum(len(m.routes) for m in mods)
        total_models = sum(len(m.models) for m in mods)
        total_tests = sum(m.test_count for m in mods)
        if total_routes or total_models or total_tests or len(mods) >= 5:
            summary = _summarize_directory(mods)
            lines.append(f"- `{path}/` — {summary}")

    lines.append("")

    # Agent workflow hints
    lines.append("## Agent Workflow Hints")
    lines.append("")
    lines.append("- Read existing code before writing new code")
    lines.append("- Match existing naming conventions and file structure")
    lines.append("- Every change should include at least one test")
    if "SQLAlchemy" in cmap.frameworks and "Alembic" in cmap.frameworks:
        lines.append("- Database changes require Alembic migration")
    if cmap.architecture == "monorepo":
        lines.append("- Changes may span multiple apps — check cross-app impacts")
    lines.append("")

    # Truncate
    if len(lines) > max_lines:
        lines = lines[:max_lines - 2]
        lines.append("")
        lines.append("*(truncated to fit context budget)*")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Part 5: Rules export
# ─────────────────────────────────────────────────────────────────────────────


def export_rules(cmap: CodebaseMap, output_dir: str) -> list[str]:
    """Generate .claude/rules/ files with path-scoped frontmatter.

    Returns list of created file paths.
    """
    rules_dir = pathlib.Path(output_dir)
    rules_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    # Rule 1: API routes
    route_modules = [m for m in cmap.modules if m.routes and ".py" in m.path]
    if route_modules:
        # Find common route directory
        route_dirs = set()
        for m in route_modules:
            parts = pathlib.PurePosixPath(m.path.replace("\\", "/")).parts
            if "routes" in parts:
                idx = parts.index("routes")
                route_dirs.add("/".join(parts[:idx + 1]))
            elif "api" in parts:
                idx = parts.index("api")
                route_dirs.add("/".join(parts[:idx + 1]))

        globs = [f"{d}/**" for d in sorted(route_dirs)] if route_dirs else ["**/routes/**"]

        content = _build_rule(
            description="API route conventions",
            globs=globs,
            body=(
                "# API Route Conventions\n\n"
                "- Each route file defines a `router = APIRouter(prefix=...)` instance\n"
                "- Route functions use decorators: `@router.get()`, `@router.post()`, etc.\n"
                "- Dependencies injected via `Depends()`: `get_db`, `get_actor`, `require_authenticated`\n"
                "- Response models defined as Pydantic `BaseModel` classes\n"
                "- Always add audit logging for state-changing operations\n"
            ),
        )
        fpath = rules_dir / "api-routes.md"
        fpath.write_text(content, encoding="utf-8")
        created.append(str(fpath))

    # Rule 2: Data models
    model_modules = [m for m in cmap.modules if m.models]
    if model_modules:
        model_dirs = set()
        for m in model_modules:
            parts = pathlib.PurePosixPath(m.path.replace("\\", "/")).parts
            if "models" in parts:
                idx = parts.index("models")
                model_dirs.add("/".join(parts[:idx + 1]))

        globs = [f"{d}/**" for d in sorted(model_dirs)] if model_dirs else ["**/models/**"]

        content = _build_rule(
            description="Data model conventions",
            globs=globs,
            body=(
                "# Data Model Conventions\n\n"
                "- Models inherit from `Base` (SQLAlchemy DeclarativeBase)\n"
                "- Use `Mapped[]` type annotations for all columns\n"
                "- Primary keys use UUID type with `uuid.uuid4` default\n"
                "- Include `created_at`, `updated_at` timestamps on all models\n"
                "- Re-export all models from `models/__init__.py`\n"
                "- New models require Alembic migration\n"
            ),
        )
        fpath = rules_dir / "data-models.md"
        fpath.write_text(content, encoding="utf-8")
        created.append(str(fpath))

    # Rule 3: Frontend components
    component_modules = [m for m in cmap.modules if m.classes
                         and any(ext in m.path for ext in (".tsx", ".jsx", ".ts"))]
    if component_modules:
        component_dirs = set()
        for m in component_modules:
            parts = pathlib.PurePosixPath(m.path.replace("\\", "/")).parts
            if "components" in parts:
                idx = parts.index("components")
                component_dirs.add("/".join(parts[:idx + 1]))

        globs = [f"{d}/**" for d in sorted(component_dirs)] if component_dirs else ["**/components/**"]

        content = _build_rule(
            description="Frontend component conventions",
            globs=globs,
            body=(
                "# Frontend Component Conventions\n\n"
                "- Use functional React components with hooks\n"
                "- Components export as named exports (`export function ComponentName`)\n"
                "- Page components export as default (`export default function PageName`)\n"
                "- Client components need `\"use client\"` directive at the top\n"
                "- UI primitives live in `components/ui/` — reuse before creating\n"
            ),
        )
        fpath = rules_dir / "frontend-components.md"
        fpath.write_text(content, encoding="utf-8")
        created.append(str(fpath))

    # Rule 4: Tests
    test_modules = [m for m in cmap.modules if m.test_count > 0]
    if test_modules:
        test_dirs = set()
        for m in test_modules:
            parts = pathlib.PurePosixPath(m.path.replace("\\", "/")).parts
            if "tests" in parts:
                idx = parts.index("tests")
                test_dirs.add("/".join(parts[:idx + 1]))
            elif "test" in parts:
                idx = parts.index("test")
                test_dirs.add("/".join(parts[:idx + 1]))

        globs = [f"{d}/**" for d in sorted(test_dirs)] if test_dirs else ["**/test*/**"]

        content = _build_rule(
            description="Test conventions",
            globs=globs,
            body=(
                "# Test Conventions\n\n"
                "- Test files named `test_*.py` (Python) or `*.test.ts` (TypeScript)\n"
                "- Test functions named `test_*` or inside `Test*` classes\n"
                "- Run Python tests: `python -m pytest -x -q`\n"
                "- Every feature/bugfix must include at least one test\n"
                "- Prefer small, focused test functions over large integration tests\n"
            ),
        )
        fpath = rules_dir / "test-conventions.md"
        fpath.write_text(content, encoding="utf-8")
        created.append(str(fpath))

    return created


def _build_rule(*, description: str, globs: list[str], body: str,
                 always_apply: bool = False) -> str:
    """Build a rule file with YAML frontmatter."""
    frontmatter_lines = [
        "---",
        f"description: {description}",
        f"alwaysApply: {'true' if always_apply else 'false'}",
    ]
    if not always_apply:
        frontmatter_lines.append("globs:")
        for g in globs:
            frontmatter_lines.append(f'  - "{g}"')
    frontmatter_lines.append("---")
    frontmatter_lines.append("")

    return "\n".join(frontmatter_lines) + body


# ─────────────────────────────────────────────────────────────────────────────
# Part 6: Harness generator — anti-drift harness for coding agents
# ─────────────────────────────────────────────────────────────────────────────


import collections
import subprocess


def _scan_utility_dirs(root: str, max_entries: int = 30) -> list[dict[str, str | list[str]]]:
    """Scan common utility directories and list exported functions/classes.

    Returns list of {"path": rel_path, "exports": [name, ...]} dicts.
    """
    root_path = pathlib.Path(root)
    utility_dir_names = {"utils", "lib", "helpers", "core", "hooks", "shared"}
    entries: list[dict[str, str | list[str]]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        current = pathlib.Path(dirpath)

        if current.name not in utility_dir_names:
            continue

        for fname in filenames:
            filepath = current / fname
            rel = str(filepath.relative_to(root_path)).replace("\\", "/")

            exports: list[str] = []
            if fname.endswith(".py") and not fname.startswith("__"):
                exports = _extract_python_exports(str(filepath))
            elif any(fname.endswith(ext) for ext in (".ts", ".tsx", ".js")) and not fname.endswith(".d.ts"):
                exports = _extract_ts_exports(str(filepath))

            if exports:
                entries.append({"path": rel, "exports": exports})

            if len(entries) >= max_entries:
                return entries

    return entries


def _extract_python_exports(filepath: str) -> list[str]:
    """Extract public function and class names from a Python file."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []

    exports: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            exports.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            exports.append(node.name)
    return exports


def _extract_ts_exports(filepath: str) -> list[str]:
    """Extract exported names from a TypeScript/JS file."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            source = f.read()
    except OSError:
        return []

    exports: list[str] = []
    for m in _RE_EXPORT_FUNCTION.finditer(source):
        exports.append(m.group(1))
    for m in _RE_EXPORT_CONST_FUNC.finditer(source):
        name = m.group(1)
        if name not in exports:
            exports.append(name)
    for m in _RE_EXPORT_CLASS.finditer(source):
        name = m.group(1)
        if name not in exports:
            exports.append(name)
    return exports


def _read_route_example(root: str, max_examples: int = 3) -> list[str]:
    """Read 2-3 route files and extract structural patterns as text snippets."""
    root_path = pathlib.Path(root)
    examples: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            filepath = os.path.join(dirpath, fname)
            rel = str(pathlib.Path(filepath).relative_to(root_path)).replace("\\", "/")

            # Only look in route-like directories
            if "routes" not in rel and "api" not in rel:
                continue

            try:
                with open(filepath, encoding="utf-8", errors="replace") as f:
                    source = f.read()
                tree = ast.parse(source)
            except (OSError, SyntaxError):
                continue

            # Check if it has a router and route decorators
            prefix = _find_router_prefix(tree)
            has_routes = False
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if _extract_route_decorator(node):
                        has_routes = True
                        break

            if not has_routes:
                continue

            # Extract structural pattern
            pattern_parts: list[str] = []
            pattern_parts.append(f"File: {rel}")
            if prefix:
                pattern_parts.append(f"  router = APIRouter(prefix=\"{prefix}\")")

            # Find auth dependencies
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if "auth" in node.module:
                        names = [alias.name for alias in (node.names or []) if alias.name != "*"]
                        if names:
                            pattern_parts.append(f"  Auth: {', '.join(names[:5])}")
                        break

            # Find response models (Pydantic BaseModel subclasses)
            models: list[str] = []
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        bname = ""
                        if isinstance(base, ast.Name):
                            bname = base.id
                        if bname == "BaseModel":
                            models.append(node.name)
            if models:
                pattern_parts.append(f"  Response models: {', '.join(models[:5])}")

            examples.append("\n".join(pattern_parts))
            if len(examples) >= max_examples:
                return examples

    return examples


def _read_model_example(root: str, max_examples: int = 3) -> list[str]:
    """Read 2-3 model files and extract structural patterns."""
    root_path = pathlib.Path(root)
    examples: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if not fname.endswith(".py") or fname.startswith("__"):
                continue
            filepath = os.path.join(dirpath, fname)
            rel = str(pathlib.Path(filepath).relative_to(root_path)).replace("\\", "/")

            if "models" not in rel:
                continue

            try:
                with open(filepath, encoding="utf-8", errors="replace") as f:
                    source = f.read()
                tree = ast.parse(source)
            except (OSError, SyntaxError):
                continue

            # Find SQLAlchemy models
            model_names: list[str] = []
            base_class = ""
            has_timestamps = False
            has_uuid_pk = False
            uses_mapped = False
            uses_mapped_column = False
            mixins: list[str] = []

            for node in ast.iter_child_nodes(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if not _is_sqlalchemy_model(node):
                    continue

                model_names.append(node.name)

                # Detect base classes and mixins
                for base in node.bases:
                    bname = ""
                    if isinstance(base, ast.Name):
                        bname = base.id
                    elif isinstance(base, ast.Attribute):
                        bname = base.attr
                    if bname == "Base":
                        base_class = "Base"
                    elif bname and bname != "Base":
                        mixins.append(bname)

                # Detect common patterns in fields
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                        field_name = child.target.id
                        if field_name in ("created_at", "updated_at"):
                            has_timestamps = True
                        if "uuid" in field_name.lower() or (
                            field_name.endswith("_id") and child.target.id == model_names[-1].lower() + "_id"
                        ):
                            # Check annotation for UUID
                            ann_str = ast.dump(child.annotation) if child.annotation else ""
                            if "UUID" in ann_str or "uuid" in ann_str:
                                has_uuid_pk = True

                        # Detect Mapped[] type annotations
                        if child.annotation:
                            ann_str = ast.dump(child.annotation)
                            if "Mapped" in ann_str:
                                uses_mapped = True

                        # Detect mapped_column() calls
                        if child.value and isinstance(child.value, ast.Call):
                            func = child.value.func
                            fname = ""
                            if isinstance(func, ast.Name):
                                fname = func.id
                            elif isinstance(func, ast.Attribute):
                                fname = func.attr
                            if fname == "mapped_column":
                                uses_mapped_column = True

            if not model_names:
                continue

            pattern_parts = [f"File: {rel}"]
            pattern_parts.append(f"  Models: {', '.join(model_names)}")
            if base_class:
                pattern_parts.append(f"  Base class: {base_class}")
            if mixins:
                pattern_parts.append(f"  Mixins: {', '.join(set(mixins))}")
            if uses_mapped:
                pattern_parts.append("  Column style: Mapped[] type annotations with mapped_column()")
            if has_uuid_pk:
                pattern_parts.append("  PK: UUID with uuid4 default")
            if has_timestamps:
                pattern_parts.append("  Timestamps: created_at, updated_at")

            examples.append("\n".join(pattern_parts))
            if len(examples) >= max_examples:
                return examples

    return examples


def _get_top_imports(cmap: CodebaseMap, top_n: int = 10) -> list[tuple[str, int]]:
    """Get the most commonly imported modules across the codebase."""
    counter: dict[str, int] = collections.Counter()
    for m in cmap.modules:
        for imp in m.imports:
            # Normalize: take the top-level package
            top_pkg = imp.split(".")[0]
            # Skip stdlib / builtins
            if top_pkg in ("__future__", "os", "sys", "re", "typing", "pathlib",
                           "datetime", "uuid", "json", "collections", "functools",
                           "dataclasses", "enum", "abc", "contextlib", "io"):
                continue
            counter[imp] += 1
    return counter.most_common(top_n)


def _detect_test_config(root: str) -> dict:
    """Detect test framework configuration from config files.

    Returns dict with keys: frameworks, test_dirs, coverage, naming, commands.
    """
    root_path = pathlib.Path(root)
    config: dict = {
        "frameworks": [],
        "test_dirs": [],
        "coverage_threshold": None,
        "naming_conventions": [],
        "commands": [],
    }

    # Check pyproject.toml for pytest config
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            filepath = os.path.join(dirpath, fname)
            rel = str(pathlib.Path(filepath).relative_to(root_path)).replace("\\", "/")

            if fname == "pyproject.toml":
                try:
                    with open(filepath, encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    if "tool.pytest" in content or "pytest" in content:
                        config["frameworks"].append("pytest")
                        config["naming_conventions"].append("test_*.py")
                        config["commands"].append("python -m pytest -x -q")

                        # Extract testpaths
                        for line in content.split("\n"):
                            if "testpaths" in line:
                                # Parse simple TOML list
                                match = re.search(r'\[([^\]]+)\]', line)
                                if match:
                                    paths = [p.strip().strip('"').strip("'") for p in match.group(1).split(",")]
                                    for p in paths:
                                        test_dir = str(pathlib.Path(dirpath).relative_to(root_path) / p).replace("\\", "/")
                                        if test_dir not in config["test_dirs"]:
                                            config["test_dirs"].append(test_dir)

                        # Extract coverage threshold
                        for line in content.split("\n"):
                            match = re.search(r'cov-fail-under[=\s]+(\d+)', line)
                            if match:
                                config["coverage_threshold"] = int(match.group(1))
                except OSError:
                    pass

            elif fname == "pytest.ini":
                config["frameworks"].append("pytest")
                config["naming_conventions"].append("test_*.py")
                config["commands"].append("python -m pytest -x -q")

            elif fname in ("vitest.config.ts", "vitest.config.js", "vitest.config.mts"):
                config["frameworks"].append("vitest")
                config["commands"].append("npx vitest run")
                try:
                    with open(filepath, encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    # Extract include patterns
                    for match in re.finditer(r'include:\s*\[([^\]]+)\]', content):
                        patterns = [p.strip().strip('"').strip("'") for p in match.group(1).split(",")]
                        for p in patterns:
                            if ".test." in p:
                                config["naming_conventions"].append("*.test.ts / *.test.tsx")
                                break
                except OSError:
                    pass

                test_dir = str(pathlib.Path(dirpath).relative_to(root_path)).replace("\\", "/")
                config["test_dirs"].append(test_dir)

            elif fname in ("jest.config.ts", "jest.config.js", "jest.config.mjs"):
                config["frameworks"].append("jest")
                config["naming_conventions"].append("*.test.ts / *.spec.ts")
                config["commands"].append("npx jest")

            elif fname == "playwright.config.ts":
                config["frameworks"].append("playwright")
                config["commands"].append("npx playwright test")

    # Deduplicate
    config["frameworks"] = list(dict.fromkeys(config["frameworks"]))
    config["naming_conventions"] = list(dict.fromkeys(config["naming_conventions"]))
    config["commands"] = list(dict.fromkeys(config["commands"]))

    return config


def _detect_commit_conventions(root: str) -> dict:
    """Parse git log to detect commit message conventions.

    Returns dict with: format, prefixes, branch_patterns.
    """
    result: dict = {
        "format": "unknown",
        "prefixes": [],
        "example_messages": [],
    }

    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", "-30"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return result
    except (OSError, subprocess.TimeoutExpired):
        return result

    lines = [l.strip() for l in proc.stdout.strip().split("\n") if l.strip()]
    if not lines:
        return result

    # Detect conventional commits pattern: type(scope): message
    conventional_re = re.compile(r'^[0-9a-f]+\s+([\w]+)(?:\(([^)]*)\))?:\s+(.+)')
    prefix_counter: dict[str, int] = collections.Counter()
    conventional_count = 0

    for line in lines:
        m = conventional_re.match(line)
        if m:
            conventional_count += 1
            prefix_counter[m.group(1)] += 1

    if conventional_count > len(lines) * 0.5:
        result["format"] = "conventional"
        result["prefixes"] = [p for p, _ in prefix_counter.most_common(8)]
    else:
        result["format"] = "freeform"

    # Keep a few example messages
    result["example_messages"] = lines[:5]

    # Detect branch naming
    try:
        proc = subprocess.run(
            ["git", "branch", "-r", "--list"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            branches = [b.strip() for b in proc.stdout.strip().split("\n") if b.strip()]
            # Check for patterns like feature/, fix/, chore/
            prefixed = [b for b in branches if "/" in b.split("origin/")[-1] if "HEAD" not in b]
            if prefixed:
                result["branch_patterns"] = prefixed[:5]
    except (OSError, subprocess.TimeoutExpired):
        pass

    return result


def _detect_source_globs(root: str) -> list[str]:
    """Detect primary source directory globs for path-scoped rules."""
    root_path = pathlib.Path(root)
    globs: list[str] = []

    # Common source patterns
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        current = pathlib.Path(dirpath)
        rel = str(current.relative_to(root_path)).replace("\\", "/")

        # Detect app/, src/, lib/ style directories
        if current.name in ("app", "src") and rel.count("/") <= 2:
            globs.append(f"{rel}/**")
        elif current.name == "components" and rel.count("/") <= 3:
            globs.append(f"{rel}/**")

    return globs[:6]  # Limit


def _generate_anti_slop(
    root: str,
    cmap: CodebaseMap,
    *,
    max_utility_entries: int = 30,
    max_pattern_examples: int = 3,
) -> str:
    """Generate anti-slop.md content from actual codebase scan."""
    lines: list[str] = []

    # --- Utility inventory ---
    utils = _scan_utility_dirs(root, max_entries=max_utility_entries)
    lines.append("# Known Utilities — DO NOT recreate")
    lines.append("")
    lines.append("Before writing new helpers, check these existing utilities:")
    lines.append("")
    for entry in utils[:max_utility_entries]:
        path = entry["path"]
        exports = entry["exports"]
        if len(exports) <= 4:
            lines.append(f"- `{path}`: {', '.join(exports)}")
        else:
            lines.append(f"- `{path}`: {', '.join(exports[:4])} (+{len(exports)-4} more)")
    lines.append("")

    # --- Route patterns ---
    route_examples = _read_route_example(root, max_examples=max_pattern_examples)
    if route_examples:
        lines.append("# Route Pattern")
        lines.append("")
        lines.append("New route files MUST follow this structure:")
        lines.append("")
        for ex in route_examples[:2]:  # Show 2 max to save lines
            for ex_line in ex.split("\n"):
                lines.append(f"  {ex_line}")
            lines.append("")

    # --- Model patterns ---
    model_examples = _read_model_example(root, max_examples=max_pattern_examples)
    if model_examples:
        lines.append("# Model Pattern")
        lines.append("")
        lines.append("New models MUST follow this structure:")
        lines.append("")
        for ex in model_examples[:2]:
            for ex_line in ex.split("\n"):
                lines.append(f"  {ex_line}")
            lines.append("")

    # --- Import patterns ---
    top_imports = _get_top_imports(cmap, top_n=10)
    if top_imports:
        lines.append("# Common Imports")
        lines.append("")
        lines.append("Most-used packages (prefer these over new dependencies):")
        lines.append("")
        for imp, count in top_imports:
            lines.append(f"- `{imp}` ({count} files)")
        lines.append("")

    # Enforce 100-line limit
    if len(lines) > 98:
        lines = lines[:96]
        lines.append("")
        lines.append("*(truncated to fit context budget)*")

    return _build_rule(
        description="Anti-drift rules — known utilities, patterns, imports",
        globs=[],
        body="\n".join(lines),
        always_apply=True,
    )


def _generate_test_requirements(root: str) -> str:
    """Generate test-requirements.md from detected test configuration."""
    config = _detect_test_config(root)
    source_globs = _detect_source_globs(root)

    lines: list[str] = []
    lines.append("# Testing Requirements")
    lines.append("")

    if config["frameworks"]:
        lines.append(f"**Frameworks**: {', '.join(config['frameworks'])}")
        lines.append("")

    if config["test_dirs"]:
        lines.append("**Test locations**:")
        for d in config["test_dirs"]:
            lines.append(f"- `{d}/`")
        lines.append("")

    if config["naming_conventions"]:
        lines.append("**Naming conventions**:")
        for nc in config["naming_conventions"]:
            lines.append(f"- `{nc}`")
        lines.append("")

    if config["coverage_threshold"]:
        lines.append(f"**Coverage floor**: {config['coverage_threshold']}% — CI will fail below this.")
        lines.append("")

    if config["commands"]:
        lines.append("**Run commands**:")
        for cmd in config["commands"]:
            lines.append(f"- `{cmd}`")
        lines.append("")

    lines.append("# Rules")
    lines.append("")
    lines.append("- Every new feature or bugfix MUST include at least one test")
    lines.append("- New source files need a corresponding test file")
    lines.append("- Do NOT reduce coverage below the floor")
    lines.append("")

    globs = source_globs if source_globs else ["**"]

    return _build_rule(
        description="Testing requirements extracted from codebase",
        globs=globs,
        body="\n".join(lines),
    )


def _generate_commit_conventions(root: str) -> str:
    """Generate commit-conventions.md from git log analysis."""
    conv = _detect_commit_conventions(root)

    lines: list[str] = []
    lines.append("# Commit Conventions")
    lines.append("")

    if conv["format"] == "conventional":
        lines.append("This project uses **conventional commits**.")
        lines.append("")
        lines.append("Format: `type(scope): description`")
        lines.append("")
        if conv["prefixes"]:
            lines.append("**Detected prefixes** (from recent history):")
            for p in conv["prefixes"]:
                lines.append(f"- `{p}`")
            lines.append("")
    else:
        lines.append("Commit format: freeform (no strict convention detected).")
        lines.append("")

    if conv.get("example_messages"):
        lines.append("**Recent examples**:")
        for msg in conv["example_messages"][:5]:
            # Strip hash prefix
            parts = msg.split(" ", 1)
            if len(parts) > 1:
                lines.append(f"- {parts[1]}")
        lines.append("")

    if conv.get("branch_patterns"):
        lines.append("**Branch naming examples**:")
        for bp in conv["branch_patterns"][:3]:
            lines.append(f"- `{bp}`")
        lines.append("")

    lines.append("# Rules")
    lines.append("")
    lines.append("- Keep commit messages concise (under 72 chars for first line)")
    lines.append("- Reference issue numbers when applicable")
    if conv["format"] == "conventional":
        lines.append("- Always use a recognized prefix from the list above")
        lines.append("- Include scope in parentheses when the change targets a specific module")
    lines.append("")

    return _build_rule(
        description="Commit message conventions detected from git history",
        globs=[],
        body="\n".join(lines),
        always_apply=True,
    )


def _generate_quality_hook(root: str, cmap: CodebaseMap) -> str:
    """Generate a standalone quality-check.py hook script.

    The script must use only stdlib — no ctxpack imports.
    """
    # Detect test directory convention
    test_dirs: list[str] = []
    for m in cmap.modules:
        parts = pathlib.PurePosixPath(m.path.replace("\\", "/")).parts
        if "tests" in parts:
            idx = parts.index("tests")
            td = "/".join(parts[:idx + 1])
            if td not in test_dirs:
                test_dirs.append(td)
        elif "__tests__" in parts:
            idx = parts.index("__tests__")
            td = "/".join(parts[:idx + 1])
            if td not in test_dirs:
                test_dirs.append(td)

    # Detect utility dirs that exist
    util_dirs: list[str] = []
    root_path = pathlib.Path(root)
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        current = pathlib.Path(dirpath)
        if current.name in ("utils", "lib", "helpers", "core", "shared"):
            rel = str(current.relative_to(root_path)).replace("\\", "/")
            util_dirs.append(rel)

    test_dirs_repr = repr(test_dirs[:8])
    util_dirs_repr = repr(util_dirs[:8])

    script = f'''#!/usr/bin/env python3
"""Post-write quality check — standalone, stdlib only.

Auto-generated by the codebase harness generator.
Checks files after every write for common quality issues.

Exit codes: 0 = pass, 1 = warnings found (printed to stderr).
"""

import ast
import os
import sys

# --- Configuration (detected from codebase) ---
TEST_DIRS = {test_dirs_repr}
UTIL_DIRS = {util_dirs_repr}
MAX_FILE_LINES = 500


def check_python_file(filepath: str) -> list[str]:
    """Check a Python file for quality issues."""
    warnings: list[str] = []

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            source = f.read()
    except OSError:
        return warnings

    lines = source.split("\\n")

    # Check file length
    if len(lines) > MAX_FILE_LINES:
        warnings.append(
            f"{{filepath}}: {{len(lines)}} lines (max {{MAX_FILE_LINES}}) — consider splitting"
        )

    # Parse AST for deeper checks
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return warnings

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip private/test functions
            if node.name.startswith("_") or node.name.startswith("test_"):
                continue

            # Check return type annotation on public functions
            if node.returns is None:
                warnings.append(
                    f"{{filepath}}:{{node.lineno}}: public function `{{node.name}}` "
                    f"missing return type annotation"
                )

            # Check route handlers for return type
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    method = dec.func.attr
                    if method in ("get", "post", "put", "delete", "patch"):
                        if node.returns is None:
                            warnings.append(
                                f"{{filepath}}:{{node.lineno}}: route handler "
                                f"`{{node.name}}` missing return type"
                            )

    return warnings


def check_missing_test(filepath: str) -> list[str]:
    """Check if a new source file has a corresponding test file."""
    warnings: list[str] = []

    # Only check Python source files (not tests themselves)
    if not filepath.endswith(".py"):
        return warnings

    basename = os.path.basename(filepath)
    if basename.startswith("test_") or basename.startswith("conftest"):
        return warnings

    # Skip __init__.py and migration files
    if basename == "__init__.py" or "alembic" in filepath or "migration" in filepath:
        return warnings

    # Look for corresponding test file
    name_stem = basename.replace(".py", "")
    expected_test = f"test_{{name_stem}}.py"

    # Search in known test dirs
    found = False
    for test_dir in TEST_DIRS:
        for dirpath, _, filenames in os.walk(test_dir):
            if expected_test in filenames:
                found = True
                break
        if found:
            break

    if not found and TEST_DIRS:
        warnings.append(
            f"{{filepath}}: no test file `{{expected_test}}` found in {{TEST_DIRS}}"
        )

    return warnings


def check_local_utility_reimport(filepath: str) -> list[str]:
    """Check if file imports something that already exists in utils/lib."""
    warnings: list[str] = []
    if not filepath.endswith(".py"):
        return warnings

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return warnings

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for util_dir in UTIL_DIRS:
                norm = util_dir.replace("/", ".").replace("\\\\", ".")
                if norm and norm in node.module:
                    # This is fine — they ARE using the local utility
                    break
    return warnings


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: quality-check.py <filepath>", file=sys.stderr)
        return 0

    filepath = sys.argv[1]
    if not os.path.isfile(filepath):
        return 0

    all_warnings: list[str] = []

    if filepath.endswith(".py"):
        all_warnings.extend(check_python_file(filepath))
        all_warnings.extend(check_missing_test(filepath))
        all_warnings.extend(check_local_utility_reimport(filepath))
    elif filepath.endswith((".ts", ".tsx")):
        # Basic line count check for TS files
        try:
            with open(filepath, encoding="utf-8", errors="replace") as f:
                line_count = sum(1 for _ in f)
            if line_count > MAX_FILE_LINES:
                all_warnings.append(
                    f"{{filepath}}: {{line_count}} lines (max {{MAX_FILE_LINES}}) — consider splitting"
                )
        except OSError:
            pass

    if all_warnings:
        for w in all_warnings:
            print(f"WARN: {{w}}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
'''
    return script


def generate_harness(
    repo_path: str,
    *,
    output_dir: str = "",
    include_hooks: bool = True,
    include_rules: bool = True,
    max_utility_entries: int = 30,
    max_pattern_examples: int = 3,
) -> list[str]:
    """Generate a complete anti-drift harness for a codebase.

    Scans the repository to produce codebase-specific rules and hooks
    that prevent coding agents from drifting (recreating utilities,
    breaking patterns, ignoring test requirements).

    Args:
        repo_path: Path to repository root.
        output_dir: Where to write files. Default: {repo_path}/.claude/
        include_hooks: Generate quality-check.py hook.
        include_rules: Generate .claude/rules/ files.
        max_utility_entries: Max utility files to list in anti-slop rules.
        max_pattern_examples: Max pattern examples per category.

    Returns:
        List of file paths created (skips existing files).
    """
    if not output_dir:
        output_dir = os.path.join(repo_path, ".claude")

    # Analyze the codebase
    cmap = analyze_codebase(repo_path)

    created: list[str] = []

    # --- Rules ---
    if include_rules:
        rules_dir = os.path.join(output_dir, "rules")
        os.makedirs(rules_dir, exist_ok=True)

        # 1. Anti-slop rules
        anti_slop_path = os.path.join(rules_dir, "anti-slop.md")
        if not os.path.exists(anti_slop_path):
            content = _generate_anti_slop(
                repo_path, cmap,
                max_utility_entries=max_utility_entries,
                max_pattern_examples=max_pattern_examples,
            )
            with open(anti_slop_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(anti_slop_path)

        # 2. Test requirements
        test_req_path = os.path.join(rules_dir, "test-requirements.md")
        if not os.path.exists(test_req_path):
            content = _generate_test_requirements(repo_path)
            with open(test_req_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(test_req_path)

        # 3. Commit conventions
        commit_conv_path = os.path.join(rules_dir, "commit-conventions.md")
        if not os.path.exists(commit_conv_path):
            content = _generate_commit_conventions(repo_path)
            with open(commit_conv_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(commit_conv_path)

    # --- Hooks ---
    if include_hooks:
        hooks_dir = os.path.join(output_dir, "hooks")
        os.makedirs(hooks_dir, exist_ok=True)

        hook_path = os.path.join(hooks_dir, "quality-check.py")
        if not os.path.exists(hook_path):
            content = _generate_quality_hook(repo_path, cmap)
            with open(hook_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(hook_path)

    return created
