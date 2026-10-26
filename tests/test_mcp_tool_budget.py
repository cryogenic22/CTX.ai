"""Default tool surface + description budget gate (execution plan W1-4).

Directive T16: don't advertise twenty tools equally. The default agent
surface is five operations; tool descriptions consume a committed token
budget so the surface can't silently bloat.
"""

from pathlib import Path

from ctxpack.integrations.mcp_server import TOOLS

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SURFACE = {
    "ctx/resume",
    "ctx/session_recall",
    "ctx/why",
    "ctx/session_literals",
    "ctx/checkpoint",
}
ADVANCED_SESSION = {
    "ctx/session_timeline",
    "ctx/session_decisions",
    "ctx/graph_query",
}

# Measured 3,900 chars across 20 tools on 2026-07-11. The cap gives
# ~15% headroom; raising it is a deliberate, reviewed act — not drift.
DESCRIPTION_BUDGET_CHARS = 4_500


def test_default_surface_tools_exist():
    names = {t.name for t in TOOLS}
    missing = DEFAULT_SURFACE - names
    assert not missing, f"default-surface tools missing: {missing}"


def test_descriptions_fit_committed_budget():
    total = sum(len(t.description or "") for t in TOOLS)
    assert total <= DESCRIPTION_BUDGET_CHARS, (
        f"tool descriptions total {total} chars > budget "
        f"{DESCRIPTION_BUDGET_CHARS}; trim descriptions or consciously "
        f"raise the budget in this test with a rationale")
    assert all(t.description for t in TOOLS), "tool with empty description"


def test_docs_lead_with_default_surface():
    for rel in ("README.md", "docs/session-memory-onboarding.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        first_advanced = min(
            (text.index(n) for n in ADVANCED_SESSION if n in text),
            default=len(text))
        for name in sorted(DEFAULT_SURFACE):
            assert name in text, f"{rel} never mentions {name}"
            assert text.index(name) < first_advanced, (
                f"{rel}: {name} first appears after an advanced session "
                f"tool — default surface must lead")
