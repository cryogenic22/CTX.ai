"""Can-fail guard for the shipped-doc privacy gate (rc1 review Finding 3c).

Every boundary check ships a test that feeds a violation and requires
rejection (.claude/rules/test-requirements.md). Here the boundary is: no
machine-specific owner path in shipped docs.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from check_doc_privacy import main as gate_main, scan_doc  # noqa: E402


def _write(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_gate_flags_the_exact_owner_drive_path(tmp_path):
    # the exact leak the rc1 review caught
    doc = _write(tmp_path, "docs/guide.md",
                 "pip install -e C:\\Users\\kapil\\Documents\\CTX_mod\n")
    cats = {c for c, _ in scan_doc(str(doc))}
    assert "drive-letter path" in cats
    assert gate_main(str(tmp_path)) == 1, "owner drive path must fail the gate"


def test_gate_flags_posix_home_owner_path(tmp_path):
    # a POSIX owner path is caught by its /home segment (not the generic
    # POSIX-absolute category, which the gate deliberately does not block)
    _write(tmp_path, "docs/sub/x.md", "see /home/kapil/notes for details\n")
    assert gate_main(str(tmp_path)) == 1


def test_gate_flags_unc_path(tmp_path):
    _write(tmp_path, "docs/y.md", "copy from \\\\host\\share\\thing\n")
    assert gate_main(str(tmp_path)) == 1


def test_gate_allows_neutral_placeholder_and_git_install(tmp_path):
    # neutral cross-platform examples must NOT trip the gate (else the gate
    # would be unusable and teams would be pushed back to owner paths)
    _write(tmp_path, "docs/guide.md",
           "pip install -e /path/to/CTX_mod\n"
           "pip install \"ctxpack @ git+https://github.com/org/repo@v0.5.0-rc1\"\n")
    assert gate_main(str(tmp_path)) == 0


def test_gate_allows_author_attribution(tmp_path):
    # a bare owner-identity byline (no path) is legitimate attribution and
    # must not be blocked — only machine paths are
    _write(tmp_path, "docs/about.md", "Author: Kapil Pant (SynaptyX)\n")
    assert gate_main(str(tmp_path)) == 0


def test_gate_scans_declared_readme(tmp_path):
    # rc1 FINAL review: the pyproject-declared distribution readme (root
    # README.md) is shipped as the long-description and MUST be scanned, not
    # just docs/. An owner path there must fail even when docs/ is clean.
    _write(tmp_path, "pyproject.toml",
           '[project]\nname = "x"\nreadme = "README.md"\n')
    _write(tmp_path, "docs/ok.md", "clean content\n")
    _write(tmp_path, "README.md",
           "install: pip install -e C:\\Users\\kapil\\Documents\\CTX_mod\n")
    assert gate_main(str(tmp_path)) == 1, (
        "an owner path in the declared distribution readme must fail the gate")


def test_gate_fails_when_declared_readme_missing(tmp_path):
    # rc1 FINAL review (non-vacuous): a declared readme that does not exist on
    # disk is a release defect, not a clean scan.
    _write(tmp_path, "pyproject.toml",
           '[project]\nname = "x"\nreadme = "README.md"\n')
    _write(tmp_path, "docs/ok.md", "clean content\n")
    assert gate_main(str(tmp_path)) == 1


def test_gate_is_not_vacuous_with_no_shipped_docs(tmp_path):
    # rc1 FINAL review (non-vacuous): nothing to scan (no readme, no docs/)
    # must FAIL rather than pass green vacuously.
    assert gate_main(str(tmp_path)) == 1


def test_gate_passes_on_real_shipped_docs():
    # regression pin: the real shipped-doc surface (declared README + docs/)
    # is clean after the Finding-3 fix.
    assert gate_main(str(REPO)) == 0, (
        "a shipped doc (README or docs/) embeds a machine-specific owner path")
