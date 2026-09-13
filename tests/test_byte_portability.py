"""Byte-portability guard (Codex Finding 3c).

The claims gate (`scripts/check_claims.py`) and the PF-16 privacy gate
(`ctxpack/agent/fixture_privacy.py`) hash WORKING-COPY bytes against
recorded SHAs. If a checkout materializes any hash-bound file with
different line endings than its committed blob — the CRLF-vs-LF drift
that made those gates pass only on the owner's Windows disk and fail on a
faithful LF checkout / Linux CI — the gates break.

This forward guard proves every hash-bound worktree file is byte-identical
to its committed git blob, so the drift cannot recur silently; it also
implicitly proves `.gitattributes` covers the whole hash-bound surface
(a newly added benchmark/scorecard/artifact left un-pinned would drift and
trip this guard).

Kind: forward guard (bounds new behaviour). Its can-fail proof is
``test_nonportable_files_detects_a_mismatch`` — a synthetic
working-vs-blob difference that the checker must report. A guard never
observed failing is not a guard.
"""
import hashlib
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
from check_claims import parse_ledger  # noqa: E402 — the gate's own parser


def _blob_bytes(root, rel):
    """Committed blob bytes for a tracked path at HEAD, or None if the path
    is not a committed blob."""
    proc = subprocess.run(["git", "show", f"HEAD:{rel}"],
                          cwd=root, capture_output=True)
    if proc.returncode != 0:
        return None
    return proc.stdout


def _hash_bound_files(root):
    """Every worktree file whose exact bytes a gate hashes: the PF-16
    allowlist entry paths + the claims-ledger measured/directional artifact
    paths."""
    files = set()
    allow = json.load(open(
        os.path.join(root, "tests", "fixture_privacy_allowlist.json"),
        encoding="utf-8"))
    for e in allow["entries"]:
        files.add(e["path"].replace("\\", "/"))
    led = open(os.path.join(root, "docs", "claims-ledger.md"),
               encoding="utf-8").read()
    # Use the gate's own parser so the set matches exactly what the claims
    # gate hashes (measured/directional artifact rows), not prose examples.
    for _rid, path, _sha in parse_ledger(led)["artifacts"]:
        if path:
            files.add(path.replace("\\", "/"))
    return sorted(files)


def nonportable_files(root, files):
    """Files whose on-disk bytes differ from their committed blob (or that
    are missing / untracked). Empty list == fully portable."""
    bad = []
    for rel in files:
        disk = os.path.join(root, rel)
        if not os.path.isfile(disk):
            bad.append(f"{rel}: missing from worktree")
            continue
        blob = _blob_bytes(root, rel)
        if blob is None:
            bad.append(f"{rel}: not a committed blob")
            continue
        with open(disk, "rb") as f:
            work = f.read()
        if work != blob:
            bad.append(
                f"{rel}: worktree bytes != committed blob "
                f"(work sha {hashlib.sha256(work).hexdigest()[:12]} vs "
                f"blob {hashlib.sha256(blob).hexdigest()[:12]})")
    return bad


def test_every_hash_bound_file_matches_its_committed_blob():
    """THE guard: no byte drift (line-ending or otherwise) between the
    working tree and the committed blob for any file a gate hashes — the
    invariant `.gitattributes` eol=lf enforces across checkouts."""
    files = _hash_bound_files(REPO_ROOT)
    assert len(files) >= 40, (
        f"expected the full hash-bound surface, got {len(files)}")
    bad = nonportable_files(REPO_ROOT, files)
    assert bad == [], "\n".join(bad)


def test_nonportable_files_detects_a_mismatch(tmp_path):
    """Can-fail control: a working copy that differs from its blob (here a
    CRLF materialization of an LF blob) is reported — proving the checker
    can fail, not just pass on a clean tree."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_SYSTEM": os.devnull}
    run = lambda *a: subprocess.run(a, cwd=tmp_path, check=True,
                                    capture_output=True, env=env)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.invalid")
    run("git", "config", "user.name", "t")
    run("git", "config", "core.autocrlf", "false")
    f = tmp_path / "a.txt"
    f.write_bytes(b"one\ntwo\n")                       # LF blob
    run("git", "add", "a.txt")
    run("git", "commit", "-q", "-m", "x")
    assert nonportable_files(str(tmp_path), ["a.txt"]) == []   # portable now
    f.write_bytes(b"one\r\ntwo\r\n")                   # CRLF working copy
    bad = nonportable_files(str(tmp_path), ["a.txt"])
    assert bad and "!= committed blob" in bad[0]
