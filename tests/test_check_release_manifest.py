"""Can-fail tests for the release-manifest gate (scripts/check_release_manifest.py).

Forward guard. Pure-function cases feed a manifest/note/doc that violates one
owner-spec rule and REQUIRE rejection; a git-integration section proves the
count is anchored to the manifest commit (stable as HEAD advances, no local
`main`). The adversarial cases in the 2026-09-12 gate-hardening verdict — a
one-nibble artifact SHA, retained=true with no artifacts, a mismatched twine
receipt, the exact-live hard-coded MCP count, and a vacuously-missing manifest
— are pinned here as red-on-17e6446 regressions.
"""

import importlib.util
import subprocess
from pathlib import Path

_GATE = Path(__file__).resolve().parent.parent / "scripts" / "check_release_manifest.py"
_spec = importlib.util.spec_from_file_location("check_release_manifest", _GATE)
crm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crm)

W = "9" * 64  # a valid full sha256 shape for fixtures
S = "a" * 64


def good_manifest():
    return {
        "lineage": {"target_base": {"sha": "2c7ed0f14d0a6d200fec9cb824e7c653440cdf3f"}},
        "current_verification": {
            "source_commit": "591e119b03e1fb79de0299ef70fd66f3b3c86d50",
            "ahead_of_target_base": 235,
            "target_base_sha": "2c7ed0f14d0a6d200fec9cb824e7c653440cdf3f",
            "artifacts": {
                "retained": False,
                "wheel": {"name": "w.whl", "sha256": "93f794e6b1f27d4bbba47875839e48dcfc46d82c325b05745c2ac6cf89aa320d"},
                "twine_check": "not_run",
            },
        },
        "historical_verifications": [
            {"source_commit": "f246940589c18eb64abcb566f4dcec1e988d3654",
             "status": "superseded",
             "build": {"wheel": {"sha256": "ee408f8611135fb700064901a9793b115fd26693b30c8ddd07f50ddedb8f867b"}}},
        ],
    }


GOOD_MD = ("Branch is 235 commits ahead of the pinned target base.\n"
           "twine check NOT RUN in this worktree (deferred to Gate 5).\n"
           "Historical R2 wheel ee408f8611135f is superseded.\n")
GOOD_STATUS = ("- MCP server exposes the full ctxpack tool surface (enumerated "
               "in mcp_server.py and the capability registry); five are the "
               "default agent-facing operation set.\n")
CTX = {"ahead": 235, "descends": True, "anchor": "abc123"}
LIVE_MCP = 20


def _errs(manifest=None, md=GOOD_MD, status=GOOD_STATUS, mcp=LIVE_MCP, ctx=None,
          sha256_of=None, root=None):
    return crm.check_manifest(manifest or good_manifest(), md, status, mcp,
                              ctx or dict(CTX), sha256_of=sha256_of, root=root)


# ── canonical / counts (Finding 1) ──────────────────────────────────────────

def test_good_manifest_passes():
    assert _errs() == [], _errs()


def test_missing_current_verification_fails():
    m = good_manifest(); del m["current_verification"]
    assert any("current_verification" in e for e in _errs(m))


def test_stale_ahead_count_fails():
    m = good_manifest(); m["current_verification"]["ahead_of_target_base"] = 230
    assert any("ahead_of_target_base" in e and "235" in e for e in _errs(m))


def test_uncomputable_count_does_not_pass():
    assert any("could not compute" in e
               for e in _errs(ctx={"ahead": None, "descends": None, "anchor": None}))


def test_ancestry_violation_fails():
    assert any("descend" in e for e in
               _errs(ctx={"ahead": 235, "descends": False, "anchor": "x"}))


def test_local_main_field_must_be_removed():
    m = good_manifest(); m["current_verification"]["ahead_of_local_main"] = 223
    assert any("ahead_of_local_main" in e for e in _errs(m))


def test_historical_not_marked_fails():
    m = good_manifest(); m["historical_verifications"][0].pop("status")
    assert any("historical_verifications[0]" in e for e in _errs(m))


# ── artifact / twine evidence (Finding 2) ────────────────────────────────────

def test_retained_true_no_artifacts_fails():
    m = good_manifest()
    m["current_verification"]["artifacts"] = {"retained": True, "twine_check": "not_run"}
    errs = _errs(m)
    assert any("wheel missing" in e for e in errs) and any("sdist missing" in e for e in errs), errs


def test_retained_true_one_nibble_sha_fails():
    m = good_manifest()
    m["current_verification"]["artifacts"] = {
        "retained": True, "twine_check": "not_run",
        "wheel": {"path": "w.whl", "sha256": "9"},
        "sdist": {"path": "s.tar.gz", "sha256": "a"}}
    errs = _errs(m)
    assert sum("full 64-hex" in e for e in errs) == 2, errs


def test_retained_true_full_sha_exact_passes(tmp_path):
    (tmp_path / "w.whl").write_bytes(b"wheel-bytes")
    (tmp_path / "s.tar.gz").write_bytes(b"sdist-bytes")
    wsha = crm._sha256_of(str(tmp_path / "w.whl"))
    ssha = crm._sha256_of(str(tmp_path / "s.tar.gz"))
    m = good_manifest()
    m["current_verification"]["artifacts"] = {
        "retained": True, "twine_check": "not_run",
        "wheel": {"path": "w.whl", "sha256": wsha},
        "sdist": {"path": "s.tar.gz", "sha256": ssha}}
    errs = _errs(m, sha256_of=crm._sha256_of, root=tmp_path)
    assert not any("artifacts" in e for e in errs), errs


def test_retained_true_sha_mismatch_fails(tmp_path):
    (tmp_path / "w.whl").write_bytes(b"wheel-bytes")
    (tmp_path / "s.tar.gz").write_bytes(b"sdist-bytes")
    m = good_manifest()
    m["current_verification"]["artifacts"] = {
        "retained": True, "twine_check": "not_run",
        "wheel": {"path": "w.whl", "sha256": W},
        "sdist": {"path": "s.tar.gz", "sha256": S}}
    errs = _errs(m, sha256_of=crm._sha256_of, root=tmp_path)
    assert any("mismatch" in e for e in errs), errs


def test_twine_freeform_passed_fails():
    m = good_manifest(); m["current_verification"]["artifacts"]["twine_check"] = "PASSED (wheel + sdist)"
    assert any("twine_check" in e for e in _errs(m))


def test_twine_passed_without_receipt_fails():
    m = good_manifest(); m["current_verification"]["artifacts"]["twine_check"] = "passed"
    assert any("twine_receipt" in e for e in _errs(m))


def test_twine_passed_mismatched_receipt_fails():
    m = good_manifest(); art = m["current_verification"]["artifacts"]
    art["twine_check"] = "passed"
    art["sdist"] = {"name": "s", "sha256": S}
    art["twine_receipt"] = {"wheel": "deadbeef", "sdist": "cafebabe"}
    errs = _errs(m)
    assert any("does not exactly equal" in e for e in errs), errs


def test_twine_passed_extra_only_receipt_fails():
    m = good_manifest(); art = m["current_verification"]["artifacts"]
    art["twine_check"] = "passed"
    art["sdist"] = {"name": "s", "sha256": S}
    art["twine_receipt"] = {"note": "looks fine"}  # no wheel/sdist bindings
    assert any("twine_receipt" in e for e in _errs(m))


def test_twine_passed_matching_receipt_passes():
    m = good_manifest(); art = m["current_verification"]["artifacts"]
    art["twine_check"] = "passed"
    art["sdist"] = {"name": "s", "sha256": S}
    art["twine_receipt"] = {"wheel": art["wheel"]["sha256"], "sdist": S}
    assert not any("twine" in e for e in _errs(m))


# ── placeholders (condition 7) ───────────────────────────────────────────────

def test_placeholder_in_sha_fails():
    m = good_manifest(); m["current_verification"]["notes_commit"] = "<this commit — the tip>"
    assert any("placeholder" in e.lower() for e in _errs(m))


# ── companion md consistency (condition 6) ───────────────────────────────────

def test_md_stale_ahead_count_fails():
    assert any("230" in e for e in _errs(md="The branch is 230 commits ahead.\n"))


def test_md_unqualified_twine_passed_fails():
    assert any("twine" in e.lower() for e in _errs(md="twine check PASSED (wheel + sdist).\n"))


def test_md_qualified_twine_passed_ok():
    md = "Branch is 235 commits ahead.\n\nHistorical R2 receipt: twine check PASSED.\n"
    assert not any("twine" in e.lower() for e in _errs(md=md))


def test_superseded_wheel_cited_as_current_fails():
    md = "Branch is 235 commits ahead.\nWheel sha256 ee408f8611135f is the release artifact.\n"
    assert any("superseded wheel" in e for e in _errs(md=md))


# ── MCP count (Finding 3) ────────────────────────────────────────────────────

def test_status_doc_live_hardcoded_mcp_count_fails():
    # the EXACT currently-live full count must fail (no duplicated count at all)
    assert any("MCP tool count" in e and "20" in e
               for e in _errs(status="- MCP server exposes a 20-tool surface.\n", mcp=20))


def test_status_doc_stale_hardcoded_mcp_count_fails():
    assert any("MCP tool count" in e and "22" in e
               for e in _errs(status="- MCP server exposes a 22-tool surface.\n", mcp=20))


def test_status_doc_pointer_and_default_surface_pass():
    ok = ("- MCP server exposes the full ctxpack tool surface (see mcp_server.py "
          "+ capability registry); five are the default operation set.\n")
    assert not any("MCP tool count" in e for e in _errs(status=ok))


# ── git-integration: anchoring, missing-manifest, root wiring (Findings 1,2c) ─

def _git(root, *args):
    subprocess.run(["git", *args], cwd=str(root), check=True,
                   capture_output=True, text=True)


def _init_release_repo(root):
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "seed.txt").write_text("seed\n")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "base")
    _git(root, "branch", "-M", "main")  # deterministic branch name
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                          capture_output=True, text=True).stdout.strip()
    rel = "docs/releases/v0.5.0-rc1.manifest.json"
    (root / "docs" / "releases").mkdir(parents=True)
    import json
    manifest = {
        "lineage": {"target_base": {"sha": base}},
        "current_verification": {
            "ahead_of_target_base": 1,  # base..<manifest commit> == 1
            "target_base_sha": base,
            "artifacts": {"retained": False, "twine_check": "not_run"},
        },
        "historical_verifications": [],
    }
    (root / rel).write_text(json.dumps(manifest, indent=2))
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "manifest")
    return base, rel


def test_missing_manifest_is_not_vacuous_success(tmp_path):
    (tmp_path / "docs" / "releases").mkdir(parents=True)
    assert any("release evidence is missing" in e for e in crm.check(root=tmp_path))


def test_anchored_count_stable_as_head_advances_and_pr_merge(tmp_path):
    _init_release_repo(tmp_path)
    assert crm.check(root=tmp_path) == [], crm.check(root=tmp_path)
    # unrelated descendant: HEAD advances, manifest untouched -> still passes
    (tmp_path / "other.txt").write_text("x\n")
    _git(tmp_path, "add", "-A"); _git(tmp_path, "commit", "-qm", "unrelated")
    assert crm.check(root=tmp_path) == [], crm.check(root=tmp_path)
    # PR-style merge descendant: branch + merge, manifest untouched -> passes
    _git(tmp_path, "checkout", "-qb", "feature")
    (tmp_path / "f.txt").write_text("f\n")
    _git(tmp_path, "add", "-A"); _git(tmp_path, "commit", "-qm", "feat")
    _git(tmp_path, "checkout", "-q", "main")
    subprocess.run(["git", "merge", "--no-ff", "-m", "merge", "feature"],
                   cwd=str(tmp_path), capture_output=True, text=True)
    assert crm.check(root=tmp_path) == [], crm.check(root=tmp_path)


def test_detached_head_no_local_main_passes(tmp_path):
    _init_release_repo(tmp_path)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(tmp_path),
                          capture_output=True, text=True).stdout.strip()
    _git(tmp_path, "checkout", "-q", head)  # detached; no branch ref in play
    assert crm.check(root=tmp_path) == [], crm.check(root=tmp_path)


def test_stale_count_after_manifest_edit_fails(tmp_path):
    _init_release_repo(tmp_path)
    import json
    rel = tmp_path / "docs" / "releases" / "v0.5.0-rc1.manifest.json"
    m = json.loads(rel.read_text())
    m["current_verification"]["ahead_of_target_base"] = 99  # now wrong
    rel.write_text(json.dumps(m, indent=2))
    _git(tmp_path, "add", "-A"); _git(tmp_path, "commit", "-qm", "stale")
    assert any("ahead_of_target_base" in e for e in crm.check(root=tmp_path))
