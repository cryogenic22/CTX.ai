"""Guards for the PR-template gate.

Forward guard. Bounds new behaviour introduced with
scripts/check_pr_template.py.

On 2026-09-20 three agent summaries were believed without an artifact-level
check. Each was an unstated assumption presented as a result. The template
therefore requires Assumptions and Verification, and this gate must reject a
body that omits them or leaves them as placeholders.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_pr_template.py"

GOOD = """\
## Summary
- Adds the structural-floor gate.

## Assumptions
- Branch protection will be enabled separately; this file cannot assert it.

## Non-goals
- Does not enable CI on push.

## Verification
- [x] red on parent: tests/test_protected_surface_sync.py, 6 failed
```
6 passed
```

## Self-review
- Reuse checked against anti-slop rules.
"""


def load():
    spec = importlib.util.spec_from_file_location("check_pr_template_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_template_has_every_required_section():
    """The shipped template itself passes the gate."""
    assert load().main([]) == 0


def test_a_complete_body_passes():
    """Control: a filled-in body must pass, or the gate is merely obstructive."""
    assert load().check(GOOD, template_mode=False) == []


@pytest.mark.parametrize("dropped", ["Assumptions", "Verification", "Non-goals",
                                     "Self-review", "Summary"])
def test_body_missing_a_required_section_is_rejected(dropped):
    """VIOLATION: each required section, removed one at a time, must fail."""
    body = "\n".join(
        block for block in GOOD.split("\n\n") if not block.startswith(f"## {dropped}"))
    problems = load().check(body, template_mode=False)
    assert any("missing required section" in p and dropped in p for p in problems), (
        f"removing '{dropped}' must be rejected; got {problems}")


def test_placeholder_content_is_rejected():
    """VIOLATION: a section left as the template's own placeholder is not filled in."""
    body = GOOD.replace(
        "- Branch protection will be enabled separately; this file cannot assert it.",
        "-")
    problems = load().check(body, template_mode=False)
    assert any("placeholder" in p for p in problems), problems


@pytest.mark.parametrize("word", ["comprehensive", "robust", "production-ready"])
def test_unsupported_quality_claims_are_rejected(word):
    """VIOLATION: asserting quality instead of showing evidence must fail."""
    body = GOOD.replace("- Adds the structural-floor gate.",
                        f"- Adds a {word} structural-floor gate.")
    problems = load().check(body, template_mode=False)
    assert any(word in p for p in problems), problems


def test_template_mode_tolerates_placeholders_but_not_missing_sections():
    """The template ships with empty bullets by design; a missing heading is still fatal."""
    module = load()
    template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    assert module.check(template, template_mode=True) == []
    gutted = template.replace("## Assumptions", "## Something Else")
    assert any("Assumptions" in p for p in module.check(gutted, template_mode=True))
