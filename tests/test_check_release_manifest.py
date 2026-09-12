"""Can-fail tests for the release-manifest gate (scripts/check_release_manifest.py).

Forward guard: bounds the new gate's behavior. Each `*_fails` case feeds a
manifest/note/doc that violates one owner-spec rule and REQUIRES the checker to
reject it; `test_good_manifest_passes` pins the clean case. Pure-function tests
(no git, no filesystem) so they are hermetic and deterministic.
"""

import copy
import importlib.util
from pathlib import Path

_GATE = Path(__file__).resolve().parent.parent / "scripts" / "check_release_manifest.py"
_spec = importlib.util.spec_from_file_location("check_release_manifest", _GATE)
crm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crm)


def good_manifest():
    return {
        "lineage": {"target_base": {"sha": "2c7ed0f14d0a6d200fec9cb824e7c653440cdf3f"}},
        "current_verification": {
            "source_commit": "591e119b03e1fb79de0299ef70fd66f3b3c86d50",
            "ahead_of_target_base": 235,
            "ahead_of_local_main": 224,
            "target_base_sha": "2c7ed0f14d0a6d200fec9cb824e7c653440cdf3f",
            "artifacts": {
                "retained": False,
                "receipt_status": "unverified build receipt pending Gate-5 rebuild",
                "wheel": {"name": "ctxpack-0.5.0rc1-py3-none-any.whl",
                          "sha256": "93f794e6b1f27d4bbba47875839e48dcfc46d82c325b05745c2ac6cf89aa320d"},
                "twine_check": "not_run",
            },
        },
        "historical_verifications": [
            {"source_commit": "f246940589c18eb64abcb566f4dcec1e988d3654",
             "status": "superseded",
             "artifacts": {"wheel": {"sha256": "ee408f8611135fb700064901a9793b115fd26693b30c8ddd07f50ddedb8f867b"}}},
        ],
    }


GOOD_MD = ("Branch is 235 commits ahead of the pinned target base.\n"
           "twine check NOT RUN in this worktree (deferred to Gate 5).\n"
           "Wheel sha256 93f794e6 supersedes the historical R2 wheel ee408f86.\n")
GOOD_STATUS = ("- MCP server exposes the full ctxpack tool surface (enumerated "
               "in mcp_server.py and the capability registry); five are the "
               "default agent-facing operation set.\n")
LIVE = {"target_base": 235, "local_main": 224}
LIVE_MCP = 20


def _errs(manifest=None, md=GOOD_MD, status=GOOD_STATUS, mcp=LIVE_MCP, counts=None):
    return crm.check_manifest(manifest or good_manifest(), md, status, mcp,
                              counts or dict(LIVE))


def test_good_manifest_passes():
    assert _errs() == [], _errs()


def test_missing_current_verification_fails():
    m = good_manifest()
    del m["current_verification"]
    assert any("current_verification" in e for e in _errs(m))


def test_stale_ahead_count_fails():
    m = good_manifest()
    m["current_verification"]["ahead_of_target_base"] = 230  # git says 235
    errs = _errs(m)
    assert any("ahead_of_target_base" in e and "235" in e for e in errs), errs


def test_uncomputable_count_does_not_pass():
    # git unavailable -> None -> must be a loud failure, never a silent pass
    errs = _errs(counts={"target_base": None, "local_main": 224})
    assert any("could not compute" in e for e in errs), errs


def test_historical_not_marked_fails():
    m = good_manifest()
    m["historical_verifications"][0].pop("status")
    assert any("historical_verifications[0]" in e for e in _errs(m))


def test_retained_true_without_path_fails():
    m = good_manifest()
    m["current_verification"]["artifacts"]["retained"] = True  # now needs path+sha on disk
    assert any("retained=true" in e for e in _errs(m))


def test_twine_freeform_passed_fails():
    m = good_manifest()
    m["current_verification"]["artifacts"]["twine_check"] = "PASSED (wheel + sdist)"
    assert any("twine_check" in e for e in _errs(m))


def test_twine_passed_without_receipt_fails():
    m = good_manifest()
    m["current_verification"]["artifacts"]["twine_check"] = "passed"
    assert any("twine_receipt" in e for e in _errs(m))


def test_twine_passed_with_receipt_passes():
    m = good_manifest()
    art = m["current_verification"]["artifacts"]
    art["twine_check"] = "passed"
    art["twine_receipt"] = {"wheel": "93f794e6", "sdist": "970e8c19"}
    assert not any("twine" in e for e in _errs(m))


def test_placeholder_in_sha_fails():
    m = good_manifest()
    m["current_verification"]["notes_commit"] = "<this commit — the tip; see git log>"
    assert any("placeholder" in e.lower() for e in _errs(m))


def test_md_stale_ahead_count_fails():
    errs = _errs(md="The branch is 230 commits ahead of the base.\n")
    assert any("230" in e for e in errs), errs


def test_md_unqualified_twine_passed_fails():
    errs = _errs(md="twine check PASSED (wheel + sdist).\n")
    assert any("twine" in e.lower() for e in errs), errs


def test_md_qualified_twine_passed_ok():
    errs = _errs(md="Branch is 235 commits ahead.\nHistorical R2 receipt: twine check PASSED.\n")
    assert not any("twine" in e.lower() for e in errs), errs


def test_superseded_wheel_cited_as_current_fails():
    errs = _errs(md="Branch is 235 commits ahead.\nWheel sha256 ee408f8611135f is the release artifact.\n")
    assert any("superseded wheel" in e for e in errs), errs


def test_status_doc_hardcoded_mcp_count_fails():
    errs = _errs(status="- MCP server exposes a 99-tool surface.\n")
    assert any("MCP tool count" in e and "99" in e for e in errs), errs


def test_status_doc_correct_hardcoded_mcp_count_ok():
    # a hard-coded full count is tolerated ONLY when it matches the live source
    errs = _errs(status="- MCP server exposes a 20-tool surface.\n", mcp=20)
    assert not any("MCP tool count" in e for e in errs), errs
