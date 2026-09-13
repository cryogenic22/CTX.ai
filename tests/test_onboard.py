"""ctxpack onboard — one-command session-memory setup for any repo."""

import hashlib
import json
import os
import sys

import pytest

from ctxpack.cli.main import _CLAUDE_MD_MARKER, main


def _onboard(project_dir):
    return main(["onboard", "--project-dir", str(project_dir)])


# ── helpers for the runtime-identity probe tests (rc1 review Finding 1) ──

def _pkg_parent():
    """Directory that must be on sys.path for a -P subprocess to import the
    SAME ctxpack this test process imported (pins the probe to the approved
    copy regardless of any stale site-packages install)."""
    import ctxpack
    return os.path.dirname(os.path.dirname(os.path.abspath(ctxpack.__file__)))


def _write_shadow(project_dir, version):
    """Plant a vendored ./ctxpack that a plain `python -m` (cwd on sys.path)
    would import instead of the approved copy; its cli.main prints identity."""
    pkg = project_dir / "ctxpack"
    (pkg / "cli").mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8")
    (pkg / "cli" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "cli" / "main.py").write_text(
        "import json, os, sys\n"
        "def main(argv=None):\n"
        "    import ctxpack\n"
        "    print(json.dumps({'version': ctxpack.__version__, 'root':\n"
        "        os.path.dirname(os.path.abspath(ctxpack.__file__))}))\n"
        "    return 0\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main(sys.argv[1:]))\n",
        encoding="utf-8")


def _strip_safe_path(project_dir):
    """Drop -P from every stored hook + MCP launch (simulate a repo onboarded
    under Python 3.10, where the command is plain, cwd-shadowable `python -m`)."""
    sp = project_dir / ".claude" / "settings.json"
    s = json.loads(sp.read_text(encoding="utf-8"))
    for entries in s.get("hooks", {}).values():
        for e in entries:
            for h in e.get("hooks", []):
                h["command"] = h["command"].replace("python -P -m", "python -m")
    sp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    mp = project_dir / ".mcp.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["mcpServers"]["ctxpack"]["args"] = [
        a for a in m["mcpServers"]["ctxpack"]["args"] if a != "-P"]
    mp.write_text(json.dumps(m), encoding="utf-8")


def _set_executable(project_dir, exe):
    """Point the stored hook + MCP launches at a specific interpreter name."""
    sp = project_dir / ".claude" / "settings.json"
    s = json.loads(sp.read_text(encoding="utf-8"))
    for entries in s.get("hooks", {}).values():
        for e in entries:
            for h in e.get("hooks", []):
                h["command"] = h["command"].replace("python ", exe + " ", 1)
    sp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    mp = project_dir / ".mcp.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["mcpServers"]["ctxpack"]["command"] = exe
    mp.write_text(json.dumps(m), encoding="utf-8")


def _snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_onboard_fresh_repo(tmp_path):
    assert _onboard(tmp_path) == 0

    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert set(settings["hooks"]) >= {"PreCompact", "SessionStart",
                                      "SessionEnd", "Stop"}

    import sys as _sys
    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    expected_args = (["-P", "-m", "ctxpack.integrations.mcp_server"]
                     if _sys.version_info >= (3, 11)
                     else ["-m", "ctxpack.integrations.mcp_server"])
    assert mcp["mcpServers"]["ctxpack"]["args"] == expected_args

    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert _CLAUDE_MD_MARKER in claude_md
    assert "Decision:" in claude_md          # the load-bearing convention
    assert "ctxpack session" in claude_md    # the read path
    assert "turn-FINAL" in claude_md         # v4: mid-turn text is dropped
    assert "Supersedes: <fact_id>" in claude_md  # v4: override convention
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


def test_onboard_refreshes_v3_block_with_v4_conventions(tmp_path):
    # The live cohort state (review P1): repos onboarded at v3 lack the
    # turn-final and Supersedes: conventions — re-onboard must deliver
    # them, or "cohort picks up new conventions on refresh" is false.
    v3 = (
        "# Cohort repo\n\n"
        "<!-- ctxpack:session-memory:v3 -->\n"
        "## Session memory (ctxpack ledger)\n"
        "v3 conventions: Decision:/Constraint: markers, incidents.\n"
        "<!-- /ctxpack:session-memory -->\n"
    )
    (tmp_path / "CLAUDE.md").write_text(v3, encoding="utf-8")

    assert _onboard(tmp_path) == 0
    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "ctxpack:session-memory:v3" not in claude_md
    assert _CLAUDE_MD_MARKER in claude_md
    assert "turn-FINAL" in claude_md
    assert "Supersedes: <fact_id>" in claude_md


# ── Disposition 1 (rc1 product review): honest prior-state/verify-live memory
#    semantics — the generated block must NOT tell agents to unconditionally
#    trust the gist. Red-on-ee7b1e1 (that block says "Trust the gist ...").


def test_onboard_block_drops_unconditional_trust(tmp_path):
    assert _onboard(tmp_path) == 0
    md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Trust the gist's constraints and decisions" not in md, (
        "the unconditional-trust wording must be gone")
    assert "prior state, not verified truth" in md
    assert "VERIFY it against the live tree" in md
    assert "Standing vs superseded or retracted" in md


def test_onboard_block_marker_bumped_to_v6(tmp_path):
    # the wording change bumps the marker so re-onboard refreshes v5 blocks
    from ctxpack.cli.main import _CLAUDE_MD_MARKER_PREFIX
    assert _CLAUDE_MD_MARKER.startswith(_CLAUDE_MD_MARKER_PREFIX + "v6.")


def test_onboard_refreshes_v5_trust_block_to_verify_live(tmp_path):
    # a repo onboarded at v5 carries the retracted "Trust the gist" wording;
    # re-onboard must refresh it in place to the verify-live semantics.
    v5 = (
        "# Repo\n\n"
        "<!-- ctxpack:session-memory:v5.L1 -->\n"
        "## Session memory (ctxpack ledger)\n"
        "...previous session's gist. Trust the gist's constraints and decisions.\n"
        "<!-- /ctxpack:session-memory -->\n"
    )
    (tmp_path / "CLAUDE.md").write_text(v5, encoding="utf-8")
    assert _onboard(tmp_path) == 0
    md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Trust the gist's constraints and decisions" not in md, "stale trust wording kept"
    assert _CLAUDE_MD_MARKER in md
    assert "prior state, not verified truth" in md
    assert md.count("## Session memory") == 1, "block duplicated"


# ── rc1 combined-review correction (Finding 2): the generated block must
#    describe a banked fact with the CANONICAL lifecycle vocabulary — standing
#    until SUPERSEDED or RETRACTED — not "stays active until something
#    supersedes it" (a retracted fact is not active), and must not conflate
#    standing (lifecycle) with CURRENT (freshness). Red-on-285032c.


def test_onboard_block_names_both_terminal_lifecycle_states(tmp_path):
    assert _onboard(tmp_path) == 0
    md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "stays active until something supersedes it" not in md, (
        "retracted-blind wording must be gone (a retracted fact is not active)")
    lower = md.lower()
    assert "superseded" in lower and "retracted" in lower, (
        "both canonical terminal lifecycle states must be named")


def test_onboard_block_separates_standing_from_current(tmp_path):
    # standing (a lifecycle statement) must not imply freshness/CURRENT
    # (a verification statement) — the two-axis rule from core/states.py.
    assert _onboard(tmp_path) == 0
    md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "forward-only" in md, "lifecycle must be described as forward-only"
    assert "CURRENT" in md, (
        "the block must distinguish standing (lifecycle) from CURRENT "
        "(freshness/verification)")


# ── Disposition 2 (rc1 product review): unified, fail-loud hook/MCP runtime
#    identity — the read path (MCP) uses the SAME shadow-proof resolver as the
#    write path (hooks); onboard refreshes a legacy split; `onboard --check`
#    fails loud. Red-on-ee7b1e1 (MCP lacked -P; legacy entry left untouched;
#    no --check subcommand).


def test_mcp_entry_uses_safe_path_on_modern_python():
    import sys as _sys

    from ctxpack.cli.main import _MCP_SERVER_ENTRY
    if _sys.version_info >= (3, 11):
        assert _MCP_SERVER_ENTRY["args"][0] == "-P", (
            "the MCP read path must be shadow-proof like the hook write path — "
            "a split lets read and write resolve to different ctxpack copies")


def test_onboard_refreshes_legacy_mcp_entry(tmp_path):
    import sys as _sys
    if _sys.version_info < (3, 11):
        return
    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"ctxpack": {
            "command": "python",
            "args": ["-m", "ctxpack.integrations.mcp_server"]}}
    }), encoding="utf-8")
    assert _onboard(tmp_path) == 0
    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["ctxpack"]["args"] == [
        "-P", "-m", "ctxpack.integrations.mcp_server"], "legacy MCP entry not refreshed"


def test_onboard_check_passes_after_onboard(tmp_path, monkeypatch):
    if sys.version_info < (3, 11):
        pytest.skip("plain `python -m` is not shadow-proof below 3.11")
    assert _onboard(tmp_path) == 0
    # Pin the -P subprocess probe to the SAME ctxpack this process imported,
    # so a stale site-packages install can't make the identity comparison
    # spuriously differ.
    monkeypatch.setenv("PYTHONPATH", _pkg_parent())
    assert main(["onboard", "--project-dir", str(tmp_path), "--check"]) == 0


def test_onboard_check_fails_when_not_onboarded(tmp_path):
    assert main(["onboard", "--project-dir", str(tmp_path), "--check"]) == 1


def test_onboard_check_fails_on_split_mcp_resolver(tmp_path, monkeypatch):
    if sys.version_info < (3, 11):
        pytest.skip("split requires the 3.11 -P baseline")
    assert _onboard(tmp_path) == 0
    mcp_path = tmp_path / ".mcp.json"
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    mcp["mcpServers"]["ctxpack"]["args"] = ["-m", "ctxpack.integrations.mcp_server"]
    mcp_path.write_text(json.dumps(mcp), encoding="utf-8")
    # hooks probe cleanly (PYTHONPATH pins them); the MCP split is the failure.
    monkeypatch.setenv("PYTHONPATH", _pkg_parent())
    assert main(["onboard", "--project-dir", str(tmp_path), "--check"]) == 1


# ── rc1 combined-review correction (Finding 1): `onboard --check` must PROBE
#    the configured runtime identity, not compare command strings. It runs each
#    stored launch and verifies the imported version + package root; it fails
#    on an unavailable runtime, a vendored shadow, a 3.10 plain `python -m`, or
#    a version split, while staying read-only. Runtime __version__ == rc1.


def test_runtime_version_is_rc1_and_matches_pyproject():
    # Regression pin (source __version__ == rc1) + forward guard (installed
    # distribution metadata bound to source + target — catches a source bump
    # never rebuilt/reinstalled). The metadata binding was demonstrated RED
    # before the candidate was installed (dist 0.5.0 != source 0.5.0rc1).
    # Finding 1(e) + Finding 2(b): runtime __version__, the INSTALLED
    # distribution metadata, and the pyproject release target must ALL be
    # 0.5.0rc1. Runtime is pinned to the pyproject version, and the installed
    # metadata is bound to both — so a source bump that was never rebuilt /
    # reinstalled (stale wheel metadata) or a release-target drift is caught,
    # not just a source/pyproject mismatch.
    import re
    from importlib import metadata
    from pathlib import Path

    import ctxpack
    assert ctxpack.__version__ == "0.5.0rc1"
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"',
                  pyproject.read_text(encoding="utf-8"))
    assert m is not None, "pyproject [project] version not found"
    assert m.group(1) == ctxpack.__version__, (
        f"pyproject version {m.group(1)} != runtime {ctxpack.__version__}")
    # installed distribution metadata must equal the running source AND the
    # release target (the wheel's own recorded version). Absent install =>
    # fail loud (install the candidate), never skip — this is the guard that
    # the shipped artifact carries the version it claims.
    try:
        dist = metadata.version("ctxpack")
    except metadata.PackageNotFoundError:
        pytest.fail("ctxpack is not installed — install the candidate "
                    "(`pip install -e .`) so installed metadata is pinned")
    assert dist == ctxpack.__version__ == m.group(1), (
        f"installed metadata {dist} != runtime {ctxpack.__version__} "
        f"!= pyproject {m.group(1)} — rebuild/reinstall the candidate")


def test_onboard_output_is_honest_about_shadow_proofing_below_311(
        tmp_path, monkeypatch, capsys):
    # Finding 1(d) narrowing: on Python < 3.11 the stored commands are plain
    # `python -m` (no -P); onboard must NOT advertise them as shadow-proof.
    import ctxpack.cli.main as m
    monkeypatch.setattr(m, "_SAFE_PATH_ARGS", [])
    assert _onboard(tmp_path) == 0
    out = capsys.readouterr().out
    assert "NOT shadow-proof" in out
    assert "3.11" in out


def test_real_python_310_onboarding_is_not_shadow_proof(tmp_path, capsys):
    # Regression pin (freezes existing correct behavior): on real Python < 3.11
    # onboarding stays non-shadow-proof and --check catches it. Passes on the
    # parent under a 3.10 interpreter; it exists so a future change cannot
    # silently start certifying plain 3.10 `python -m` as shadow-proof.
    # Finding 2(a): a repo actually ONBOARDED under Python < 3.11 stores plain,
    # cwd-shadowable `python -m` (the interpreter has no -P flag at all — this
    # cannot be faked by monkeypatching a frozen module constant, which is why
    # the honest-output test above does not, on its own, pin 3.10 behavior).
    # This test EXECUTES (never skips) in the Python 3.10 CI cells: it performs
    # real onboarding, asserts the stored hook + MCP commands carry no -P, and
    # asserts a real `onboard --check` fails loud, naming the 3.11 requirement.
    if sys.version_info >= (3, 11):
        pytest.skip("pins Python < 3.11 onboarding (no -P flag on the runtime)")
    assert _onboard(tmp_path) == 0
    # (i) the stored write/read commands are plain `python -m`, no -P
    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hook_cmds = [h["command"]
                 for entries in settings["hooks"].values()
                 for e in entries for h in e.get("hooks", [])]
    assert hook_cmds, "onboarding wrote no hook commands"
    for c in hook_cmds:
        assert " -P " not in f" {c} ", f"3.10 hook unexpectedly carries -P: {c}"
    mcp_args = json.loads(
        (tmp_path / ".mcp.json").read_text(encoding="utf-8")
    )["mcpServers"]["ctxpack"]["args"]
    assert mcp_args == ["-m", "ctxpack.integrations.mcp_server"], (
        f"3.10 MCP args unexpectedly carry -P: {mcp_args}")
    # (ii) a real --check must refuse to certify plain `python -m` as
    #      shadow-proof and must name the 3.11 requirement (fail-loud).
    rc = main(["onboard", "--project-dir", str(tmp_path), "--check"])
    assert rc == 1, "plain 3.10 `python -m` must not pass --check as shadow-proof"
    err = capsys.readouterr().err
    assert "shadow-proof" in err.lower() and "3.11" in err


def test_identity_subcommand_reports_running_ctxpack(capsys):
    import ctxpack
    from ctxpack.cli.main import _norm_root
    assert main(["identity", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["version"] == ctxpack.__version__
    assert _norm_root(data["root"]) == _norm_root(
        os.path.dirname(os.path.abspath(ctxpack.__file__)))


def _approving_probe():
    from ctxpack.cli.main import _runtime_identity
    ver, root = _runtime_identity()
    return lambda prefix, cwd: ({"version": ver, "root": root}, None)


def test_onboard_check_passes_when_probe_matches_approved(tmp_path):
    if sys.version_info < (3, 11):
        pytest.skip("needs the 3.11 -P baseline")
    from ctxpack.cli.main import _onboard_check
    assert _onboard(tmp_path) == 0
    assert _onboard_check(str(tmp_path), probe=_approving_probe()) == 0


def test_onboard_check_fails_when_runtime_unavailable(tmp_path):
    # Finding 1(b): the configured executable cannot start -> nonzero.
    if sys.version_info < (3, 11):
        pytest.skip("needs the 3.11 -P baseline")
    from ctxpack.cli.main import _onboard_check
    assert _onboard(tmp_path) == 0
    unavailable = lambda prefix, cwd: (None, "configured executable not found")
    assert _onboard_check(str(tmp_path), probe=unavailable) == 1


def test_onboard_check_fails_on_version_or_root_skew(tmp_path):
    # Finding 1(c): the launch resolves a DIFFERENT ctxpack (shadow / split).
    if sys.version_info < (3, 11):
        pytest.skip("needs the 3.11 -P baseline")
    from ctxpack.cli.main import _onboard_check, _runtime_identity
    assert _onboard(tmp_path) == 0
    ver, root = _runtime_identity()
    ver_skew = lambda prefix, cwd: ({"version": "9.9.9-shadow", "root": root}, None)
    root_skew = lambda prefix, cwd: ({"version": ver, "root": root + "_vendored"}, None)
    assert _onboard_check(str(tmp_path), probe=ver_skew) == 1
    assert _onboard_check(str(tmp_path), probe=root_skew) == 1


def test_onboard_check_rejects_plain_python_m_as_not_shadow_proof(tmp_path, capsys):
    # Finding 1(d): a repo onboarded under Python 3.10 stores plain `python -m`
    # (cwd-shadowable). Even when the runtime probe resolves fine, --check must
    # NOT call it shadow-proof: it fails and names the 3.11 requirement.
    if sys.version_info < (3, 11):
        pytest.skip("this env must emit -P so the strip is meaningful")
    from ctxpack.cli.main import _onboard_check
    assert _onboard(tmp_path) == 0
    _strip_safe_path(tmp_path)
    rc = _onboard_check(str(tmp_path), probe=_approving_probe())
    assert rc == 1, "plain `python -m` must not pass as shadow-proof"
    err = capsys.readouterr().err
    assert "shadow-proof" in err.lower() and "3.11" in err


def test_onboard_check_is_read_only(tmp_path):
    # Finding 1(f): --check never mutates the project.
    if sys.version_info < (3, 11):
        pytest.skip("needs the 3.11 -P baseline")
    from ctxpack.cli.main import _onboard_check
    assert _onboard(tmp_path) == 0
    before = _snapshot(tmp_path)
    assert _onboard_check(str(tmp_path), probe=_approving_probe()) == 0
    assert _snapshot(tmp_path) == before, "onboard --check modified the project"


def test_onboard_check_validates_claude_block_content_not_just_marker(
        tmp_path, capsys):
    # rc1 final review Finding 1: a CURRENT marker over a STALE body (the exact
    # defect — "trust its constraints and decisions" wording surviving under a
    # v6 marker) must fail --check. The complete block content is validated,
    # not just the marker string, so a marker bump without a real refresh
    # cannot pass.
    if sys.version_info < (3, 11):
        pytest.skip("needs the 3.11 -P baseline so only the block content varies")
    from ctxpack.cli.main import _CLAUDE_MD_MARKER, _onboard_check
    assert _onboard(tmp_path) == 0
    # the pristine onboarded (canonical) block passes
    assert _onboard_check(str(tmp_path), probe=_approving_probe()) == 0
    # tamper the block BODY while keeping the current marker intact
    claude = tmp_path / "CLAUDE.md"
    md = claude.read_text(encoding="utf-8")
    assert _CLAUDE_MD_MARKER in md
    tampered = md.replace("prior state, not verified truth",
                          "trust its constraints and decisions", 1)
    assert tampered != md, "canonical honest phrase should be present to tamper"
    claude.write_text(tampered, encoding="utf-8")
    assert _CLAUDE_MD_MARKER in tampered, "marker must remain current after tamper"
    rc = _onboard_check(str(tmp_path), probe=_approving_probe())
    assert rc == 1, "a stale block body under a current marker must fail --check"
    err = capsys.readouterr().err
    assert "CLAUDE.md" in err and "content" in err.lower()


def test_onboard_check_real_probe_catches_split_a_string_check_misses(
        tmp_path, monkeypatch):
    # Finding 1(a)+(c), the DISCRIMINATING case (RED on the string-only parent):
    # a canonical, -P, correctly-SHAPED config — one a string check accepts —
    # whose runtime nonetheless resolves to a DIFFERENT ctxpack. A fake
    # approved-shaped package with a different version is put on PYTHONPATH;
    # -P imports it (cwd ignored), so the real probe sees the version split the
    # string check cannot. On the parent (no probe) this config passes (rc 0).
    if sys.version_info < (3, 11):
        pytest.skip("-P shadow-proofing requires 3.11+")
    assert _onboard(tmp_path) == 0                     # canonical -P config
    fakeenv = tmp_path / "fakeenv"
    _write_shadow(fakeenv, "7.7.7-split")              # different-version ctxpack
    monkeypatch.setenv("PYTHONPATH", str(fakeenv))
    rc = main(["onboard", "--project-dir", str(tmp_path), "--check"])
    assert rc == 1, ("a -P launch that imports a different ctxpack version must "
                     "be caught by the runtime probe (a string check cannot)")


def test_onboard_check_real_probe_ignores_vendored_shadow_under_safe_path(
        tmp_path, monkeypatch):
    # Forward guard (passes on the parent too): Finding 1(c) positive proof — a
    # consumer repo carrying a vendored ./ctxpack. With -P the real probe still
    # imports the APPROVED root/version (cwd excluded); downgraded to plain
    # `python -m`, cwd wins and the vendored shadow is imported -> caught.
    if sys.version_info < (3, 11):
        pytest.skip("-P shadow-proofing requires 3.11+")
    proj = tmp_path / "consumer"
    proj.mkdir()
    _write_shadow(proj, "0.0.0-shadow")
    assert _onboard(proj) == 0
    monkeypatch.setenv("PYTHONPATH", _pkg_parent())
    assert main(["onboard", "--project-dir", str(proj), "--check"]) == 0, (
        "-P must ignore the vendored copy and resolve the approved ctxpack")
    _strip_safe_path(proj)
    assert main(["onboard", "--project-dir", str(proj), "--check"]) == 1, (
        "plain `python -m` imports the vendored shadow — must be caught")


def test_onboard_check_real_probe_fails_on_missing_executable(tmp_path, capsys):
    # Finding 1(b), end-to-end: the configured interpreter does not exist, so
    # neither launch can start. (Equivalent to the empty-PATH reproduction, but
    # deterministic across platforms.)
    if sys.version_info < (3, 11):
        pytest.skip("needs the 3.11 -P baseline")
    assert _onboard(tmp_path) == 0
    _set_executable(tmp_path, "ctxpack-no-such-python-xyz")
    rc = main(["onboard", "--project-dir", str(tmp_path), "--check"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err.lower()
