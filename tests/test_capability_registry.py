"""CI wrapper for the capability-registry gate (execution plan W1-1)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_capability_registry import (  # noqa: E402
    check,
    classify,
    dependency_errors,
    load_rows,
)


def test_registry_covers_every_module():
    errors = check(ROOT)
    assert not errors, "\n".join(errors)


def test_most_specific_row_wins():
    rows = load_rows(
        "| `ctxpack/modules/` | experimental | — | blanket |\n"
        "| `ctxpack/modules/guard.py` | legacy-deprecation-candidate |"
        " ContextGuard | override |\n"
    )
    assert classify("ctxpack/modules/keywords.py", rows)[1] == "experimental"
    assert classify("ctxpack/modules/guard.py", rows)[1] == (
        "legacy-deprecation-candidate")
    assert classify("ctxpack/agent/checkpoint.py", rows) is None


# ---------------------------------- core→legacy dependency check (Q2-5)


_DEP_ROWS = load_rows(
    "| `ctxpack/agent/` | core | — | product |\n"
    "| `ctxpack/agent/old.py` | legacy-deprecation-candidate | — | dead |\n"
)


def _tree(tmp_path, source: str):
    pkg = tmp_path / "ctxpack" / "agent"
    pkg.mkdir(parents=True)
    (pkg / "old.py").write_text("X = 1\n", encoding="utf-8")
    (pkg / "new.py").write_text(source, encoding="utf-8")
    return tmp_path


def test_module_level_core_to_legacy_import_fails(tmp_path):
    root = _tree(tmp_path, "from .old import X\n")
    errors = dependency_errors(root, _DEP_ROWS)
    assert len(errors) == 1
    assert "ctxpack/agent/old.py" in errors[0]
    assert "lazy" in errors[0]


def test_lazy_in_function_import_is_allowed(tmp_path):
    root = _tree(tmp_path,
                 "def f():\n    from .old import X\n    return X\n")
    assert dependency_errors(root, _DEP_ROWS) == []


def test_absolute_import_of_legacy_also_fails(tmp_path):
    root = _tree(tmp_path, "import ctxpack.agent.old\n")
    assert len(dependency_errors(root, _DEP_ROWS)) == 1


def test_agent_package_import_does_not_load_state_parser():
    # the Q2-5 contradiction itself: importing the core package (as any
    # hook or MCP consumer does) must not execute the eval-tier
    # state_parser; compress_state loads it lazily on first call.
    # Run in a SUBPROCESS: purging sys.modules in-process re-imports
    # ctxpack.agent with new class identities and breaks later tests.
    import subprocess
    code = (
        "import sys; import ctxpack.agent as a; "
        "assert 'ctxpack.agent.state_parser' not in sys.modules, "
        "'state_parser loaded eagerly by the package init'; "
        "r = a.compress_state([{'decision': 'use exponential backoff'}]); "
        "assert 'ctxpack.agent.state_parser' in sys.modules; "
        "assert r.step_count == 1"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
