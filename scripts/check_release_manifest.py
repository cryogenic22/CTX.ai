#!/usr/bin/env python
"""CI gate: a release manifest's audit record must be self-consistent.

Owner spec 2026-09-12 (after two review rounds where a green suite sat beside
a false manifest — stale ahead-counts, an old wheel hash, an unqualified
"twine PASSED", a placeholder, and a hard-coded MCP tool count) plus the
2026-09-12 gate-hardening verdict (the first gate was false-red in a clean CI
checkout and false-green on four evidence invariants). It scans every
``docs/releases/*.manifest.json`` and FAILS (exit 1) unless:

  1. the JSON parses and carries exactly ONE ``current_verification`` record;
  2. ``current_verification.ahead_of_target_base`` equals the immutable count
     ``git rev-list --count <target_base>..<anchor>`` where <anchor> is the
     commit that CONTAINS the manifest (``git log -1 --format=%H HEAD --
     <manifest>``), NOT moving HEAD; the anchor must descend from the pinned
     target base, else FAIL. There is NO dependency on a local ``main`` branch;
  3. every ``historical_verifications`` entry is explicitly marked
     ``status`` ∈ {superseded, historical};
  4. artifacts either declare ``retained: false`` OR the COMPLETE expected set
     (wheel AND sdist) is present, each with a repo-contained ``path`` that
     exists and a full 64-hex SHA-256 EXACTLY equal to the file bytes (no
     prefix acceptance);
  5. ``twine_check`` is a controlled value {not_run, passed, failed}; a
     ``passed`` requires a ``twine_receipt`` whose wheel/sdist hashes EXACTLY
     equal the canonical artifact hashes (missing, shortened, extra-only, or
     mismatched receipts fail);
  6. the companion Markdown is consistent with the JSON — no stale ahead-count,
     no unqualified "twine check PASSED", no superseded wheel hash cited as
     current (interim enforcement of "generated from the JSON": see NOTE);
  7. no angle-bracket placeholder (``<this commit>`` / ``<R2b tip>`` / ...)
     survives in any commit / sha / range field;
  8. a current-value document does not hard-code a full MCP tool-count at all
     (the count must live in source, not be independently maintained) — the
     only tolerated literal is the default agent-facing operation set (five).

  A ``docs/releases/`` directory that exists but holds NO manifest FAILS
  (release evidence missing) rather than passing vacuously.

NOTE (condition 6): full "md is generated from the json" is a follow-up; this
gate enforces json↔md *consistency* for the drift-prone fields, which catches
the same defect an independent generator would.

Count semantics (condition 2): anchoring to the manifest's own commit makes the
count immutable as HEAD advances (a later commit, a PR-merge descendant, a
merged main) and independent of any checkout's local branches — so a clean
detached clone of the release tip passes. The count is re-derived from git at
check time; the manifest never stores its own commit hash.

Stdlib + git only.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_TWINE_OK = {"not_run", "passed", "failed"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDER = re.compile(r"<[^>]*(?:tip|commit|sha|placeholder|todo|fixme|xxx)[^>]*>", re.I)
_SHA_KEYS = {"sha", "source_commit", "commit", "target_base_sha", "rejected_tip",
             "anchored_to", "review_range"}
_MD_AHEAD = re.compile(r"(\d+)\s+commits?\s+ahead", re.I)
_MCP_COUNT = re.compile(r"(\d+)\s*[- ]?tools?\b", re.I)
_DEFAULT_SURFACE_SIZE = 5  # the documented default agent-facing operation set


def _walk_strings(obj, key=None):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v, key)
    elif isinstance(obj, str):
        yield key, obj


def check_manifest(manifest, md_text, status_doc_text, live_mcp_count,
                   count_ctx, sha256_of=None, root=None):
    """Pure checker. Returns a list of error strings (empty = pass).

    count_ctx  {"ahead": int|None, "descends": bool|None, "anchor": str|None}
               ahead   = git rev-list --count target_base..<manifest anchor>;
                         None means it could not be computed (git unavailable).
               descends= whether the anchor descends from the target base.
    sha256_of  callable(path_str) -> hex sha256 (retained-artifact verify).
    root       Path for resolving/containing artifact paths (retained case).
    """
    errors = []
    root = Path(root) if root is not None else ROOT

    cv = manifest.get("current_verification")
    if cv is None:
        return ["no top-level `current_verification` record"]
    if not isinstance(cv, dict):
        return ["`current_verification` must be a single object"]

    # 2 — ahead-count anchored to the manifest commit (not HEAD); no local main
    declared = cv.get("ahead_of_target_base")
    if declared is None:
        errors.append("current_verification.ahead_of_target_base is missing")
    elif count_ctx.get("ahead") is None:
        errors.append("current_verification.ahead_of_target_base: could not "
                      "compute the anchored count (git unavailable/errored) — "
                      "the gate cannot run and does NOT pass")
    elif count_ctx.get("descends") is False:
        errors.append("current_verification: the manifest's anchor commit does "
                      "NOT descend from the pinned target base — ancestry "
                      "violation")
    elif int(declared) != int(count_ctx["ahead"]):
        errors.append(f"current_verification.ahead_of_target_base={declared} "
                      f"but git rev-list --count target_base..<manifest anchor "
                      f"{str(count_ctx.get('anchor'))[:12]}> is {count_ctx['ahead']}")
    if "ahead_of_local_main" in cv:
        errors.append("current_verification.ahead_of_local_main must be removed "
                      "— a local `main` branch is not a stable anchor (bind to "
                      "the pinned target base instead)")

    # 3 — historical entries explicitly marked
    for i, h in enumerate(manifest.get("historical_verifications", []) or []):
        st = (h or {}).get("status", "")
        if st not in {"superseded", "historical"}:
            errors.append(f"historical_verifications[{i}].status={st!r} — must "
                          f"be 'superseded' or 'historical'")

    # 4 — artifacts retained:false OR complete set, existing, full-sha exact
    art = cv.get("artifacts", {}) or {}
    retained = art.get("retained")
    if retained is None:
        errors.append("current_verification.artifacts.retained is not declared")
    elif retained:
        for name in ("wheel", "sdist"):
            a = art.get(name)
            if not isinstance(a, dict):
                errors.append(f"artifacts.{name}: retained=true requires the "
                              f"complete set (wheel AND sdist) — {name} missing")
                continue
            path, sha = a.get("path"), a.get("sha256")
            if not path or not sha:
                errors.append(f"artifacts.{name}: retained=true requires both "
                              f"`path` and `sha256`")
                continue
            if not _SHA256.match(str(sha)):
                errors.append(f"artifacts.{name}: sha256 must be a full 64-hex "
                              f"digest, not {str(sha)[:16]!r}")
                continue
            try:
                p = (root / path).resolve()
                p.relative_to(root.resolve())
            except (OSError, ValueError):
                errors.append(f"artifacts.{name}: path escapes the repo root: "
                              f"{path}")
                continue
            if not p.exists():
                errors.append(f"artifacts.{name}: retained=true but path does "
                              f"not exist: {path}")
            elif sha256_of is not None:
                actual = sha256_of(str(p))
                if actual != sha:
                    errors.append(f"artifacts.{name}: sha256 mismatch — "
                                  f"declared {sha[:12]}, actual {actual[:12]}")

    # 5 — twine controlled; passed binds the receipt to the artifact hashes
    tw = art.get("twine_check")
    if tw not in _TWINE_OK:
        errors.append(f"artifacts.twine_check={tw!r} — must be one of "
                      f"{sorted(_TWINE_OK)} (no freeform 'PASSED')")
    elif tw == "passed":
        receipt = art.get("twine_receipt")
        if not isinstance(receipt, dict):
            errors.append("artifacts.twine_check='passed' requires a "
                          "`twine_receipt` object binding the checked hashes")
        else:
            for name in ("wheel", "sdist"):
                want = ((art.get(name) or {}).get("sha256")) if isinstance(art.get(name), dict) else None
                got = receipt.get(name)
                if not want or not _SHA256.match(str(want)):
                    errors.append(f"twine_receipt: cannot bind {name} — the "
                                  f"canonical artifact sha256 is missing/short")
                elif got != want:
                    errors.append(f"twine_receipt.{name}={str(got)[:12]!r} does "
                                  f"not exactly equal the canonical "
                                  f"{name} sha256 {want[:12]}")

    # 7 — no angle-bracket placeholders survive
    for key, val in _walk_strings(manifest):
        if _PLACEHOLDER.search(val):
            errors.append(f"placeholder token survives in field {key!r}: "
                          f"{val[:60]!r}")
        elif key in _SHA_KEYS and "<" in val and ">" in val:
            errors.append(f"angle-bracket value in canonical field {key!r}: "
                          f"{val[:60]!r}")

    # 6 — companion markdown consistency
    if md_text:
        current = str(cv.get("ahead_of_target_base"))
        for m in _MD_AHEAD.finditer(md_text):
            if m.group(1) != current:
                errors.append(f"companion note states '{m.group(0)}' but the "
                              f"current anchored ahead-count is {current}")
        for para in re.split(r"\n\s*\n", md_text):
            low = para.lower()
            if "twine" in low and "passed" in low and not any(
                    q in low for q in ("historical", "r2", "superseded",
                                       "not run", "not_run")):
                first = (para.strip().splitlines() or [para])[0]
                errors.append(f"companion note has an unqualified twine "
                              f"'passed' claim: {first.strip()[:80]!r}")
        for h in manifest.get("historical_verifications", []) or []:
            old = (((h or {}).get("build") or {}).get("wheel") or {}).get("sha256", "")
            old = old.split()[0] if old else ""
            if old and len(old) >= 12:
                for ln in md_text.splitlines():
                    if old[:12] in ln and not any(
                            q in ln.lower() for q in
                            ("historical", "r2", "superseded", "old")):
                        errors.append(f"companion note cites a superseded wheel "
                                      f"hash {old[:12]} as current: "
                                      f"{ln.strip()[:80]!r}")

    # 8 — no independently-maintained full MCP tool count in a current doc
    if status_doc_text:
        for ln in status_doc_text.splitlines():
            if "mcp" not in ln.lower():
                continue
            for m in _MCP_COUNT.finditer(ln):
                n = int(m.group(1))
                if n != _DEFAULT_SURFACE_SIZE:
                    errors.append(f"status doc hard-codes a full MCP tool count "
                                  f"{n} (live source has {live_mcp_count}) — "
                                  f"point to the source/registry instead of "
                                  f"duplicating it: {ln.strip()[:80]!r}")
    return errors


# ── git plumbing (isolated so check_manifest stays pure & hermetic) ──────────

def _git(root, args):
    try:
        out = subprocess.run(["git", *args], cwd=str(root),
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def _resolve_anchor_count(root, manifest_rel, target_base_sha):
    """(anchor_sha, ahead_count, descends) from git, anchored to the commit
    that CONTAINS the manifest (immutable), NOT HEAD."""
    if not target_base_sha:
        return (None, None, None)
    anchor = _git(root, ["log", "-1", "--format=%H", "HEAD", "--", manifest_rel])
    if not anchor:
        return (None, None, None)
    descends = subprocess.run(
        ["git", "merge-base", "--is-ancestor", target_base_sha, anchor],
        cwd=str(root), capture_output=True).returncode == 0
    cnt = _git(root, ["rev-list", "--count", f"{target_base_sha}..{anchor}"])
    try:
        cnt = int(cnt)
    except (TypeError, ValueError):
        cnt = None
    return (anchor, cnt, descends)


def _sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _companion_md(manifest_path):
    stem = manifest_path.name.replace(".manifest.json", "")
    md = manifest_path.with_name(stem + ".md")
    return md.read_text(encoding="utf-8") if md.is_file() else ""


def check(root=ROOT):
    root = Path(root)
    releases_dir = root / "docs" / "releases"
    mcp_server = root / "ctxpack" / "integrations" / "mcp_server.py"
    status_doc = root / "paper" / "status-and-value-v0.5.md"
    if not releases_dir.exists():
        return []  # repo has no releases concept
    releases = sorted(releases_dir.glob("*.manifest.json"))
    if not releases:
        return ["docs/releases/ exists but contains no *.manifest.json — "
                "release evidence is missing (refusing vacuous success)"]
    live_mcp = mcp_server.read_text(encoding="utf-8").count('name="ctx/') if mcp_server.is_file() else -1
    status_text = status_doc.read_text(encoding="utf-8") if status_doc.is_file() else ""
    errors = []
    for mpath in releases:
        rel = mpath.relative_to(root).as_posix()
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            errors.append(f"{rel}: JSON does not parse: {e}")
            continue
        base = (((manifest.get("lineage") or {}).get("target_base") or {})
                .get("sha")) or (manifest.get("current_verification") or {}).get("target_base_sha")
        anchor, cnt, descends = _resolve_anchor_count(root, rel, base)
        count_ctx = {"ahead": cnt, "descends": descends, "anchor": anchor}
        md_text = _companion_md(mpath)
        for e in check_manifest(manifest, md_text, status_text, live_mcp,
                                count_ctx, sha256_of=_sha256_of, root=root):
            errors.append(f"{rel}: {e}")
    return errors


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    errors = check()
    for e in errors:
        print(f"RELEASE-MANIFEST-GATE FAIL: {e}")
    if errors:
        print(f"release-manifest gate: {len(errors)} failure(s)")
        return 1
    print("release-manifest gate: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
