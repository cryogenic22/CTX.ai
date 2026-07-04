"""ctxpack onboard — one-command session-memory setup for any repo."""

import json

from ctxpack.cli.main import _CLAUDE_MD_MARKER, main


def _onboard(project_dir):
    return main(["onboard", "--project-dir", str(project_dir)])


def test_onboard_fresh_repo(tmp_path):
    assert _onboard(tmp_path) == 0

    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert set(settings["hooks"]) >= {"PreCompact", "SessionStart",
                                      "SessionEnd", "Stop"}

    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["ctxpack"]["args"] == [
        "-m", "ctxpack.integrations.mcp_server"]

    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert _CLAUDE_MD_MARKER in claude_md
    assert "Decision:" in claude_md          # the load-bearing convention
    assert "ctxpack session" in claude_md    # the read path
    assert (tmp_path / ".claude" / "ctx").is_dir()


def test_onboard_is_idempotent(tmp_path):
    assert _onboard(tmp_path) == 0
    assert _onboard(tmp_path) == 0

    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_md.count(_CLAUDE_MD_MARKER) == 1, "block duplicated"

    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for event in ("PreCompact", "SessionStart", "SessionEnd", "Stop"):
        ctx_entries = [e for e in settings["hooks"][event]
                       if any("ctxpack" in str(h.get("command", ""))
                              for h in e.get("hooks", []))]
        assert len(ctx_entries) == 1, f"{event} hook duplicated"


def test_onboard_preserves_existing_config(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(
        "# My project\n\nExisting instructions.\n", encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"other": {"command": "node", "args": ["s.js"]}}
    }), encoding="utf-8")

    assert _onboard(tmp_path) == 0

    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Existing instructions." in claude_md
    assert _CLAUDE_MD_MARKER in claude_md

    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert "other" in mcp["mcpServers"]      # untouched
    assert "ctxpack" in mcp["mcpServers"]    # added


def test_onboard_refuses_unparseable_mcp_json(tmp_path):
    (tmp_path / ".mcp.json").write_text("{not json", encoding="utf-8")
    assert _onboard(tmp_path) == 1
    assert (tmp_path / ".mcp.json").read_text(encoding="utf-8") == "{not json"


# ── Fail-open guard: hook invocations may NEVER exit non-zero ──
# (a non-zero PreCompact hook blocks compaction — observed in the wild
# when a vendored stale ctxpack shadowed the installed one)


def test_hook_never_exits_nonzero_on_bad_event():
    assert main(["hook", "some-future-event"]) == 0


def test_hook_never_exits_nonzero_on_missing_args():
    # argparse would sys.exit(2) here without the guard
    assert main(["hook"]) == 0


def test_non_hook_commands_still_fail_normally(tmp_path, capsys):
    import pytest
    with pytest.raises(SystemExit):
        main(["definitely-not-a-command"])


def test_hook_command_uses_safe_path_on_modern_python():
    import sys as _sys

    from ctxpack.cli.main import _HOOK_CMD

    if _sys.version_info >= (3, 11):
        assert _HOOK_CMD.startswith("python -P -m"), (
            "-P is the vendored-copy shadowing fix; without it a repo "
            "with its own ctxpack/ dir runs stale hook code")


def test_onboard_writes_safe_path_hook_commands(tmp_path):
    import sys as _sys

    if _sys.version_info < (3, 11):
        return
    _onboard(tmp_path)
    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for event, entries in settings["hooks"].items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                assert hook["command"].startswith("python -P -m"), (
                    f"{event} hook not shadow-proof: {hook['command']}")


def test_onboard_refreshes_stale_conventions_block(tmp_path):
    # A repo onboarded on an older ctxpack has a v1 block; re-onboarding
    # after upgrade must refresh it in place, not skip or duplicate.
    stale = (
        "# My project\n\nKeep this.\n\n"
        "<!-- ctxpack:session-memory:v1 -->\n"
        "## Session memory (ctxpack ledger)\n"
        "old conventions text without the resume/literals tools\n"
        "<!-- /ctxpack:session-memory -->\n\n"
        "## After the block\n\nAlso keep this.\n"
    )
    (tmp_path / "CLAUDE.md").write_text(stale, encoding="utf-8")

    assert _onboard(tmp_path) == 0
    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert _CLAUDE_MD_MARKER in claude_md
    assert "ctxpack:session-memory:v1" not in claude_md, "stale block kept"
    assert claude_md.count("## Session memory") == 1, "block duplicated"
    assert "Keep this." in claude_md and "Also keep this." in claude_md
    assert "session resume" in claude_md          # new surfaces present
    assert "Constraint:" in claude_md
