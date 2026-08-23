"""PF-17 TC coverage registry.

The PF-11 threat model's TC list is the acceptance surface for the
whole security program. This registry test parses the DOC for the
authoritative TC ids and requires each one to be referenced by at
least one test (docstring tag like ``TC-14`` or a name-embedded form
like ``test_tc14_...``) — or to sit in the explicit KNOWN_UNCOVERED
map with a reason. A TC added to the doc with no test fails here
(the "every remediation ships its TC immediately" rule, structural);
a KNOWN_UNCOVERED entry whose TC quietly gains a test also fails
(stale gap entries are how a gap register rots).

Reference-vs-coverage is a heuristic: a docstring can mention a TC it
does not prove. The registry makes ABSENCE loud; reviewers still judge
presence. This file excludes itself from the scan so the gap reasons
below cannot self-satisfy the check."""

import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(REPO_ROOT, "docs", "preflight-threat-model-pf11.md")

# TCs with NO test yet, each with the reason the gap is open. Entries
# leave this map only when their test lands (this test forces that).
# TC-15 landed 2026-08-23 (Finding 7): tests/test_claim_lint.py — the
# map is now empty, and this test fails if any doc TC loses coverage.
KNOWN_UNCOVERED: "dict[str, str]" = {}


def test_every_doc_tc_is_tested_or_an_explicit_known_gap():
    doc = open(DOC, encoding="utf-8").read()
    tc_ids = sorted(set(re.findall(r"\*\*TC-(\d+[a-z]?)", doc)),
                    key=lambda s: (int(re.match(r"\d+", s).group()), s))
    assert len(tc_ids) >= 20, "TC list unexpectedly small — doc moved?"

    tests_dir = os.path.dirname(os.path.abspath(__file__))
    corpus = []
    for name in sorted(os.listdir(tests_dir)):
        if (name.endswith(".py") and name.startswith("test_")
                and name != os.path.basename(__file__)):
            corpus.append(open(os.path.join(tests_dir, name),
                               encoding="utf-8", errors="replace").read())
    blob = "\n".join(corpus)

    missing, stale_gaps = [], []
    for tc in tc_ids:
        # (?![0-9a-z]) not \b: name-embedded tags like test_tc9_ sit
        # before an underscore, which \b treats as word-internal
        referenced = re.search(rf"tc[-_]?{tc}(?![0-9a-z])", blob,
                               re.IGNORECASE)
        if tc in KNOWN_UNCOVERED:
            if referenced:
                stale_gaps.append(tc)
        elif not referenced:
            missing.append(tc)
    assert not missing, (
        f"TCs in the threat model with no referencing test and no "
        f"KNOWN_UNCOVERED entry: {['TC-' + t for t in missing]}")
    assert not stale_gaps, (
        f"KNOWN_UNCOVERED entries now referenced by tests — remove the "
        f"stale gap rows: {['TC-' + t for t in stale_gaps]}")
