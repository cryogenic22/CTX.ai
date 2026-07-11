"""CI wrapper for the capability-registry gate (execution plan W1-1)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_capability_registry import check, classify, load_rows  # noqa: E402


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
