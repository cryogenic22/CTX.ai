#!/usr/bin/env python3
"""DI-01 AC6 — clean installed-package smoke of the COMPLETE workflow.

Run this against a CLEAN install of the built wheel (NOT the editable dev
tree, NOT pytest). It drives the installed ``ctxpack`` CLI end to end and
asserts every DI-01 acceptance property with real subprocess invocations:

  AC1  case- AND punctuation-distinct literals survive
       parser -> checkpoint -> `session why`, with ORIGINAL values intact and
       DISTINCT 64-hex exact ids.
  AC2  a repeated checkpoint of the same transcript is byte-identical.
  AC3  a legacy 16-hex literal id stays LOOKUPABLE; a one-to-many legacy id
       reports EXPLICIT ambiguity (never a guessed successor); a 64-hex exact
       literal id is RATIFIABLE; a Supersedes line with a 64-hex target is
       captured.

Reproduce:
    python -m venv .smoke && .smoke/Scripts/pip install <built wheel>
    .smoke/Scripts/python scripts/di01_installed_smoke.py

Prints "DI-01 AC6 SMOKE PASSED" and exits 0 on success; on the first failed
check it prints the mismatch and exits 1. Identity is computed from the
installed ``ctxpack`` package, so this fails loudly if the wrong tree is
imported.
"""
from __future__ import annotations

import glob
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from ctxpack.core import factid

# ---- fixtures (independently pinned; NOT derived from the parser) -----------
CASE_A, CASE_B = "src/Foo/Bar.py", "src/foo/bar.py"          # subtype "path"
PUNCT_A, PUNCT_B = "https://ex.com/a.b", "https://ex.com/a-b"  # subtype "url"
EXP = {
    CASE_A: factid.exact_fact_id("LITERAL", CASE_A, key="path"),
    CASE_B: factid.exact_fact_id("LITERAL", CASE_B, key="path"),
    PUNCT_A: factid.exact_fact_id("LITERAL", PUNCT_A, key="url"),
    PUNCT_B: factid.exact_fact_id("LITERAL", PUNCT_B, key="url"),
}
LEGACY_PATH = factid.fact_id("LITERAL", CASE_A, key="path")   # == for CASE_B
SUPERSEDE_TARGET = factid.exact_fact_id("LITERAL", "CACHE_TTL", key="literal")
SID = "ac6smoke-0000-0000-0000-000000000000"


def _fail(msg: str) -> "None":
    print(f"  FAIL: {msg}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"  ok: {msg}")


def _cli(args, cwd) -> "subprocess.CompletedProcess[str]":
    # `-m ctxpack.cli.main` runs the INSTALLED package; cwd is a neutral temp
    # dir so no sibling `ctxpack/` can shadow the install on sys.path[0].
    return subprocess.run([sys.executable, "-m", "ctxpack.cli.main", *args],
                          cwd=cwd, capture_output=True, text=True)


def _why(cwd, ledger, key) -> dict:
    r = _cli(["session", "why", key, "--ledger", ledger], cwd)
    if r.returncode != 0:
        _fail(f"`session why {key!r}` exit {r.returncode}: {r.stderr.strip()}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        _fail(f"`session why {key!r}` did not emit JSON: {r.stdout[:200]!r}")


def _pairs(res) -> list:
    out = []
    for m in res.get("matches", []):
        f = {c["key"]: c["value"] for c in m.get("fields", [])}
        if "VALUE" in f:
            out.append((f["VALUE"], f.get("FACT-ID"), m.get("matched_on")))
    return out


def _write_transcript(path: Path) -> None:
    def e(t, content):
        return {"type": t, "sessionId": SID, "timestamp": "2026-07-05T09:00:00Z",
                "isSidechain": False, "isMeta": False,
                "message": {"role": t, "content": content}}
    body = f"{CASE_A} and {CASE_B} and {PUNCT_A} and {PUNCT_B}"
    entries = [
        e("user", f"Please look at {body}."),
        e("assistant", [{"type": "text", "text":
            "Decision: rename the cache knob for clarity.\n"
            f"Supersedes: {SUPERSEDE_TARGET} — CACHE_TTL replaced CacheTtl."}]),
    ]
    path.write_text("\n".join(json.dumps(x) for x in entries), encoding="utf-8")


def main() -> int:
    import ctxpack
    print(f"installed ctxpack: {ctxpack.__file__}")
    with tempfile.TemporaryDirectory() as td:
        cwd = Path(td)
        transcript = cwd / "session.jsonl"
        _write_transcript(transcript)
        ledger = cwd / "ctx"
        ledger2 = cwd / "ctx2"

        # -- checkpoint (write path) --------------------------------------
        for out in (ledger, ledger2):
            r = _cli(["checkpoint", "--transcript", str(transcript),
                      "--out", str(out), "--as-of", "2026-07-05"], cwd)
            if r.returncode != 0:
                _fail(f"checkpoint exit {r.returncode}: {r.stderr.strip()}")
        _ok("checkpoint packed the transcript")

        # -- AC2: byte-deterministic pack ---------------------------------
        b1 = Path(glob.glob(str(ledger / "session-*.ctx"))[0]).read_bytes()
        b2 = Path(glob.glob(str(ledger2 / "session-*.ctx"))[0]).read_bytes()
        if b1 != b2:
            _fail("AC2: repeated checkpoint produced different .ctx bytes")
        _ok("AC2: repeated checkpoint is byte-identical")

        # -- AC1: distinct literals recovered verbatim with distinct ids --
        for val in (CASE_A, CASE_B, PUNCT_A, PUNCT_B):
            pairs = _pairs(_why(cwd, str(ledger), val))
            if not any(v == val and fid == EXP[val] and mo == "value_exact"
                       for v, fid, mo in pairs):
                _fail(f"AC1: {val!r} not recovered verbatim with its exact id "
                      f"({EXP[val]}); got {pairs}")
        if EXP[CASE_A] == EXP[CASE_B] or EXP[PUNCT_A] == EXP[PUNCT_B]:
            _fail("AC1: variant exact ids collapsed")
        _ok("AC1: case/punctuation-distinct literals recovered, ids distinct")

        # -- AC3: legacy id lookupable -> one-to-many ambiguity -----------
        res = _why(cwd, str(ledger), LEGACY_PATH)
        if not res.get("legacy_alias_ambiguous"):
            _fail(f"AC3: legacy id did not report ambiguity: {res}")
        if res.get("candidate_count") != 2:
            _fail(f"AC3: expected 2 ambiguous candidates, got {res}")
        cand = {c["exact_fact_id"] for c in res.get("candidates", [])}
        if cand != {EXP[CASE_A], EXP[CASE_B]}:
            _fail(f"AC3: ambiguous candidates wrong: {cand}")
        if res.get("matches"):
            _fail("AC3: an ambiguous legacy id returned a guessed single match")
        _ok("AC3: one-to-many legacy id reports explicit ambiguity (no guess)")

        # -- AC3: a 64-hex exact literal id is RATIFIABLE -----------------
        r = _cli(["session", "ratify", EXP[CASE_A], "--ledger", str(ledger)], cwd)
        if r.returncode != 0:
            _fail(f"AC3: ratifying a 64-hex exact id failed: {r.stderr.strip()}")
        row = json.loads(r.stdout)
        if row.get("fact_id") != EXP[CASE_A] or row.get("action") != "ratify":
            _fail(f"AC3: ratification row wrong: {row}")
        _ok("AC3: 64-hex exact literal id is ratifiable")

        # -- AC3: Supersedes with a 64-hex target is captured -------------
        events = [json.loads(x) for x in
                  (ledger / "events.jsonl").read_text(encoding="utf-8").splitlines()
                  if x.strip()]
        if not any(ev.get("event") == "fact_superseded"
                   and ev.get("fact_id") == SUPERSEDE_TARGET for ev in events):
            _fail("AC3: 64-hex Supersedes target was not captured")
        _ok("AC3: Supersedes line with a 64-hex target captured")

    print("DI-01 AC6 SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
