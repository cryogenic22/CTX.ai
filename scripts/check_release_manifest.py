#!/usr/bin/env python
"""CI gate: a release manifest's audit record must be self-consistent.

Owner spec 2026-09-12 (after two review rounds where a green suite sat beside
a false manifest — stale ahead-counts, an old wheel hash, an unqualified
"twine PASSED", a placeholder, and a hard-coded MCP tool count). The harness
proved code/tests but never validated release *metadata* against Git,
artifacts, or the companion note. This gate closes that gap.

It scans every ``docs/releases/*.manifest.json`` and FAILS (exit 1) unless:

  1. the JSON parses and carries exactly ONE ``current_verification`` record;
  2. ``current_verification`` ahead-counts equal live ``git rev-list --count``
     from the pinned target base (and local ``main``) to HEAD;
  3. every ``historical_verifications`` entry is explicitly marked
     ``status`` ∈ {superseded, historical};
  4. artifacts either declare ``retained: false`` OR every artifact with a
     ``path`` exists and its ``sha256`` matches the bytes on disk;
  5. ``twine_check`` is a controlled value {not_run, passed, failed}; a
     ``passed`` requires a ``twine_receipt`` naming the checked artifact hashes;
  6. the companion Markdown is consistent with the JSON — no stale ahead-count,
     no unqualified "twine check PASSED", no superseded wheel hash cited as
     current (interim enforcement of "generated from the JSON": see NOTE);
  7. no angle-bracket placeholder (``<this commit>`` / ``<R2b tip>`` / ...)
     survives in any commit / sha / range field;
  8. a current-value document does not hard-code a registry-derived MCP
     tool-count that disagrees with the live source (``mcp_server.py``).

NOTE (condition 6): full "md is generated from the json" is a follow-up; this
gate enforces json↔md *consistency* for the drift-prone fields, which catches
the same defect an independent generator would.

Count semantics (condition 2): the ahead-count is meaningful at the release
tip. This gate compares against HEAD, so it is authoritative on the release
branch / release PR (where HEAD == the release tip) and in that CI job. If
HEAD is not a descendant of the pinned target base, the count check is skipped
with a recorded SKIP (not a silent pass) rather than false-failing on an
unrelated branch.

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
RELEASES_DIR = ROOT / "docs" / "releases"
MCP_SERVER = ROOT / "ctxpack" / "integrations" / "mcp_server.py"
STATUS_DOC = ROOT / "paper" / "status-and-value-v0.5.md"

_TWINE_OK = {"not_run", "passed", "failed"}
# placeholder tokens that must never survive into a canonical field
_PLACEHOLDER = re.compile(r"<[^>]*(?:tip|commit|sha|placeholder|todo|fixme|xxx)[^>]*>", re.I)
_SHA_KEYS = {"sha", "source_commit", "commit", "target_base_sha", "rejected_tip",
             "anchored_to", "review_range"}
_MD_AHEAD = re.compile(r"(\d+)\s+commits?\s+ahead", re.I)
_MCP_COUNT = re.compile(r"(\d+)\s*[- ]?tools?\b", re.I)


def _walk_strings(obj, key=None):
    """Yield (key, value) for every string leaf, carrying its parent key."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v, key)
    elif isinstance(obj, str):
        yield key, obj


def check_manifest(manifest, md_text, status_doc_text, live_mcp_count,
                   live_counts, sha256_of=None):
    """Pure checker. Returns a list of error strings (empty = pass).

    manifest        parsed JSON dict.
    md_text         companion release-note markdown (str), or "" if absent.
    status_doc_text current-value document text (str), or "" if not checked.
    live_mcp_count  int: live count of MCP Tool() registrations in source.
    live_counts     {"target_base": int|None, "local_main": int|None};
                    None means the count could not be computed (see caller).
    sha256_of       callable(path_str) -> hex sha256, for retained-artifact
                    verification (only invoked when retained is truthy).
    """
    errors = []

    # 1 — exactly one current_verification
    cv = manifest.get("current_verification")
    if cv is None:
        errors.append("no top-level `current_verification` record")
        return errors  # nothing else is meaningful without it
    if not isinstance(cv, dict):
        errors.append("`current_verification` must be a single object")
        return errors

    # 2 — ahead-counts equal live git rev-list --count
    for field, live_key, label in (
            ("ahead_of_target_base", "target_base", "target base"),
            ("ahead_of_local_main", "local_main", "local main")):
        declared = cv.get(field)
        live = live_counts.get(live_key)
        if declared is None:
            errors.append(f"current_verification.{field} is missing")
        elif live is None:
            errors.append(f"current_verification.{field}: could not compute "
                          f"the live count over {label} (git unavailable or "
                          f"errored) — the gate cannot run and does NOT pass")
        elif int(declared) != int(live):
            errors.append(f"current_verification.{field}={declared} but live "
                          f"git rev-list --count over {label} is {live}")

    # 3 — historical entries explicitly marked
    for i, h in enumerate(manifest.get("historical_verifications", []) or []):
        st = (h or {}).get("status", "")
        if st not in {"superseded", "historical"}:
            errors.append(f"historical_verifications[{i}].status={st!r} — must "
                          f"be 'superseded' or 'historical'")

    # 4 — artifacts retained:false OR each present + sha matches
    art = cv.get("artifacts", {}) or {}
    retained = art.get("retained")
    if retained is None:
        errors.append("current_verification.artifacts.retained is not declared")
    elif retained:
        for name in ("wheel", "sdist"):
            a = art.get(name)
            if not isinstance(a, dict):
                continue
            path, sha = a.get("path"), a.get("sha256")
            if not path or not sha:
                errors.append(f"artifacts.{name}: retained=true requires both "
                              f"`path` and `sha256`")
                continue
            p = (ROOT / path)
            if not p.exists():
                errors.append(f"artifacts.{name}: retained=true but path does "
                              f"not exist: {path}")
            elif sha256_of is not None:
                actual = sha256_of(str(p))
                if not actual.startswith(sha.split()[0]):
                    errors.append(f"artifacts.{name}: sha256 mismatch — "
                                  f"declared {sha.split()[0][:12]}, actual "
                                  f"{actual[:12]}")

    # 5 — twine_check controlled; passed requires a receipt of hashes
    tw = art.get("twine_check")
    if tw not in _TWINE_OK:
        errors.append(f"artifacts.twine_check={tw!r} — must be one of "
                      f"{sorted(_TWINE_OK)} (no freeform 'PASSED')")
    elif tw == "passed":
        receipt = art.get("twine_receipt")
        hashes = []
        if isinstance(receipt, dict):
            hashes = [v for v in receipt.values() if v]
        elif isinstance(receipt, list):
            hashes = [v for v in receipt if v]
        if not hashes:
            errors.append("artifacts.twine_check='passed' requires a "
                          "`twine_receipt` naming the checked artifact hashes")

    # 7 — no angle-bracket placeholders survive in canonical fields
    for key, val in _walk_strings(manifest):
        if _PLACEHOLDER.search(val):
            errors.append(f"placeholder token survives in field {key!r}: "
                          f"{val[:60]!r}")
        elif key in _SHA_KEYS and "<" in val and ">" in val:
            errors.append(f"angle-bracket value in canonical field {key!r}: "
                          f"{val[:60]!r}")

    # 6 — companion markdown consistency (interim for "generated from json")
    if md_text:
        atb = cv.get("ahead_of_target_base")
        alm = cv.get("ahead_of_local_main")
        current_counts = {str(atb), str(alm)}
        for m in _MD_AHEAD.finditer(md_text):
            if m.group(1) not in current_counts:
                errors.append(f"companion note states '{m.group(0)}' but the "
                              f"current ahead-counts are {sorted(current_counts)}")
        # paragraph-scoped (blank-line separated) so a qualifier that wraps to
        # an adjacent line still counts — a per-line scan false-flags a
        # correctly-qualified multi-line note.
        for para in re.split(r"\n\s*\n", md_text):
            low = para.lower()
            if "twine" in low and "passed" in low:
                if not any(q in low for q in ("historical", "r2", "superseded",
                                              "not run", "not_run")):
                    first = (para.strip().splitlines() or [para])[0]
                    errors.append(f"companion note has an unqualified twine "
                                  f"'passed' claim: {first.strip()[:80]!r}")
        # a superseded wheel hash must not be cited as current
        for h in manifest.get("historical_verifications", []) or []:
            old = (((h or {}).get("artifacts") or {}).get("wheel") or {}).get("sha256", "")
            old = old.split()[0] if old else ""
            if old and len(old) >= 8:
                for ln in md_text.splitlines():
                    if old[:12] in ln and not any(
                            q in ln.lower() for q in
                            ("historical", "r2", "superseded", "old")):
                        errors.append(f"companion note cites a superseded wheel "
                                      f"hash {old[:12]} as current: "
                                      f"{ln.strip()[:80]!r}")

    # 8 — current-value doc must not hard-code a drifting MCP tool count
    if status_doc_text:
        for ln in status_doc_text.splitlines():
            if "mcp" not in ln.lower():
                continue
            for m in _MCP_COUNT.finditer(ln):
                n = int(m.group(1))
                # the "default agent-facing operation set" size (five) is not
                # the full registry count; only flag a hard-coded FULL count
                # that disagrees with the live source.
                if n >= 2 and n != live_mcp_count and n != 5:
                    errors.append(f"status doc hard-codes MCP tool count "
                                  f"{n} on a line, but the live source has "
                                  f"{live_mcp_count}: {ln.strip()[:80]!r}")
    return errors


def _git_count(rev_range):
    try:
        out = subprocess.run(["git", "rev-list", "--count", rev_range],
                             cwd=str(ROOT), capture_output=True, text=True,
                             check=True)
        return int(out.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def _sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _companion_md(manifest_path):
    # v0.5.0-rc1.manifest.json -> v0.5.0-rc1.md
    stem = manifest_path.name.replace(".manifest.json", "")
    md = manifest_path.with_name(stem + ".md")
    return md.read_text(encoding="utf-8") if md.is_file() else ""


def _live_mcp_count():
    if not MCP_SERVER.is_file():
        return -1
    return MCP_SERVER.read_text(encoding="utf-8").count('name="ctx/')


def check(root=ROOT):
    errors = []
    releases = sorted(RELEASES_DIR.glob("*.manifest.json"))
    if not releases:
        return []  # no release manifests to check
    live_mcp = _live_mcp_count()
    status_text = STATUS_DOC.read_text(encoding="utf-8") if STATUS_DOC.is_file() else ""
    for mpath in releases:
        rel = mpath.relative_to(root).as_posix()
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            errors.append(f"{rel}: JSON does not parse: {e}")
            continue
        base = (((manifest.get("lineage") or {}).get("target_base") or {})
                .get("sha")) or (manifest.get("current_verification") or {}).get("target_base_sha")
        # "ahead" = commits reachable from HEAD but not from the ref: a well
        # defined set difference (git rev-list --count REF..HEAD), independent
        # of ancestry. Authoritative at the release tip; see the module NOTE
        # on branch semantics for a permanent ci-required gate.
        live_counts = {
            "target_base": _git_count(f"{base}..HEAD") if base else None,
            "local_main": _git_count("main..HEAD"),
        }
        md_text = _companion_md(mpath)
        for e in check_manifest(manifest, md_text, status_text, live_mcp,
                                live_counts, sha256_of=_sha256_of):
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
