"""Cross-repo lessons registry (continuous-improvement loop v0):
curated, evidence-linked, distributed to cohort repos (KP_SDLC etc.)
through the versioned onboard CLAUDE.md block. Promotion stays manual
(scope firewall — the ratified learning-layer design requires >=2-repo
incident evidence before anything auto-promotes)."""

import pytest

from ctxpack.agent import lessons as L
from ctxpack.cli.main import (_CLAUDE_MD_BLOCK, _CLAUDE_MD_MARKER, main)


def test_registry_is_valid():
    assert L.validate_lessons() == []


def test_registry_has_the_seed_lessons():
    ids = [r["id"] for r in L.LESSONS]
    assert len(ids) == len(set(ids))
    # the two artifact-review lessons that seeded this registry
    assert "L-001" in ids and "L-002" in ids


def test_every_active_lesson_is_distributed():
    section = L.render_claude_md_section()
    for row in L.active_lessons():
        assert row["id"] in section
    assert f"v{L.LESSONS_VERSION}" in section


def test_distributed_text_carries_no_owner_identity():
    text = (L.render_claude_md_section()
            + L.render_cli_listing()).lower()
    for pat in ("kapil", "c--users-kapil"):
        assert pat not in text


def test_onboard_block_embeds_lessons_and_versioned_marker():
    # the onboard block is what cohort repos (KP_SDLC) actually receive
    # (marker bumped v5 -> v6 with the honest prior-state/verify-live wording)
    assert f"v6.L{L.LESSONS_VERSION} -->" in _CLAUDE_MD_MARKER
    assert _CLAUDE_MD_MARKER in _CLAUDE_MD_BLOCK
    for row in L.active_lessons():
        assert row["id"] in _CLAUDE_MD_BLOCK


def test_lint_catches_bad_rows():
    bad = ({"id": "L-900", "date": "2026-07-13", "scope": "nope",
            "lesson": "x", "evidence": [], "status": "active"},
           {"id": "L-900", "date": "2026-07-13", "scope": "general",
            "lesson": "mentions kapil directly",
            "evidence": [{"repo": "r", "ref": "c"}],
            "status": "active"})
    problems = L.validate_lessons(bad)
    assert any("unknown scope" in p for p in problems)
    assert any("evidence" in p for p in problems)
    assert any("duplicate id" in p for p in problems)
    assert any("forbidden identity" in p for p in problems)


def test_cli_check_passes(capsys):
    assert main(["lessons", "--check"]) == 0
    assert "valid" in capsys.readouterr().out


def test_cli_listing_and_json(capsys):
    assert main(["lessons"]) == 0
    out = capsys.readouterr().out
    assert "L-001" in out and "evidence:" in out
    assert main(["lessons", "--json"]) == 0
    import json
    data = json.loads(capsys.readouterr().out)
    assert data["version"] == L.LESSONS_VERSION
    assert len(data["lessons"]) == len(L.LESSONS)


def test_onboard_refreshes_older_block_with_lessons(tmp_path):
    # a cohort repo with the previous (v4) block picks up the lessons
    # section on re-onboard — this is exactly how KP_SDLC stays aware
    md = tmp_path / "CLAUDE.md"
    md.write_text("# repo\n\n<!-- ctxpack:session-memory:v4 -->\nold "
                  "conventions\n<!-- /ctxpack:session-memory -->\n",
                  encoding="utf-8")
    assert main(["onboard", "--project-dir", str(tmp_path)]) == 0
    updated = md.read_text(encoding="utf-8")
    assert _CLAUDE_MD_MARKER in updated
    assert "old conventions" not in updated
    for row in L.active_lessons():
        assert row["id"] in updated
