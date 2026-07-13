"""Cross-repo lessons registry — the distribution half of the
continuous-improvement loop across the cohort (CTX_mod, KP_SDLC, ...).

The loop has three deterministic stages:

1. COLLECT — sessions in every onboarded repo bank `ctx-incident:`
   rows and review findings into their own ledgers; the cohort
   scorecard aggregates them (`ctxpack scorecard`).
2. CURATE — a recurring, evidence-linked failure/fix is promoted into
   THIS registry by hand. Promotion is deliberately manual: the
   ratified learning-layer design requires >=2-repo incident evidence
   before any AUTOMATIC promotion, and that machinery does not exist
   yet — a curated registry with evidence links is the
   scope-firewalled v0. Every entry must cite its receipts.
3. DISTRIBUTE — `ctxpack onboard` (re-run in any cohort repo, e.g.
   KP_SDLC) bakes the active lessons into that repo's CLAUDE.md
   conventions block, so every future session there starts aware.
   Re-onboarding is idempotent; bumping LESSONS_VERSION changes the
   block's marker version, so a stale block refreshes in place.

Zero-dep, deterministic, code-as-data: the registry is this module, so
it ships with the package and needs no packaging config or file I/O.
"""

from __future__ import annotations

# Bump on ANY change to LESSONS — the onboard CLAUDE.md marker embeds
# this, which is what makes re-onboard refresh stale blocks in place.
LESSONS_VERSION = 1

_SCOPES = frozenset(("eval-harness", "privacy-release",
                     "memory-conventions", "general"))
_STATUSES = frozenset(("active", "retired"))

# Identity strings that must never appear in distributed lesson text
# (same class as the E-6A fixture gate — lessons travel to other repos).
_FORBIDDEN_IN_TEXT = ("kapil", "c--users-kapil")

LESSONS: "tuple[dict, ...]" = (
    {
        "id": "L-001",
        "date": "2026-07-13",
        "scope": "eval-harness",
        "lesson": "Grade evidence is the complete verbatim output plus "
                  "its sha256 — never store a truncated prefix of what "
                  "was graded. A gate whose evidence cannot be "
                  "independently reproduced from the artifact is a "
                  "failed gate, even when the underlying result is real.",
        "evidence": [{"repo": "CTX_mod",
                      "ref": "artifact review 2026-07-13 blocker 1; "
                             "fix commit 815c1ed "
                             "(validate_report_evidence)"}],
        "status": "active",
    },
    {
        "id": "L-002",
        "date": "2026-07-13",
        "scope": "privacy-release",
        "lesson": "Every committed artifact is a release surface: no "
                  "machine-local absolute paths, no real usernames. "
                  "Reference companion files by sibling-relative name "
                  "plus SHA-256, and audit the artifact BEFORE writing "
                  "it, not after committing it.",
        "evidence": [{"repo": "CTX_mod",
                      "ref": "artifact review 2026-07-13 blocker 2; "
                             "fix commit 815c1ed"}],
        "status": "active",
    },
    {
        "id": "L-003",
        "date": "2026-07-12",
        "scope": "privacy-release",
        "lesson": "Committed fixtures never carry real user or session "
                  "data. Replace with synthetic data from a committed "
                  "deterministic generator (or mechanically verifiable "
                  "pseudonymization), and enforce with a standing "
                  "repo-wide gate with a named fictional-user allowlist.",
        "evidence": [{"repo": "CTX_mod",
                      "ref": "E-6A remediation commits 73c3099, "
                             "7438514, aed94a5 "
                             "(tests/test_fixture_privacy.py)"}],
        "status": "active",
    },
    {
        "id": "L-004",
        "date": "2026-07-12",
        "scope": "eval-harness",
        "lesson": "Eval results are immutable and error rows are never "
                  "graded: each run writes a NEW versioned artifact, "
                  "and a failed, empty, or over-budget call aborts the "
                  "scored run instead of scoring as a miss.",
        "evidence": [{"repo": "CTX_mod",
                      "ref": "A5 harness notes v2-v5 (commits 2a3ec39, "
                             "e150b4d)"}],
        "status": "active",
    },
    {
        "id": "L-005",
        "date": "2026-07-12",
        "scope": "eval-harness",
        "lesson": "Text graders must be polarity-aware, with "
                  "adversarial cases pinned as tests BEFORE scoring: a "
                  "negated mention is a dismissal, not a detection, "
                  "and contrast markers can restore polarity "
                  "mid-clause.",
        "evidence": [{"repo": "CTX_mod",
                      "ref": "drift-fork grade lineage A4->A4.3 "
                             "(commits 1713ff9, ad1434d)"}],
        "status": "active",
    },
    {
        "id": "L-006",
        "date": "2026-07-12",
        "scope": "eval-harness",
        "lesson": "Paid API runs are interlocked in code, not "
                  "convention: pinned model, preflight worst-case "
                  "bound with tokenizer headroom, a ceiling guard "
                  "before EVERY attempt, and a durable fsync'd "
                  "per-invocation ledger.",
        "evidence": [{"repo": "CTX_mod",
                      "ref": "commits 1b7379f (retry-level budget), "
                             "e613139 (full-request worst case)"}],
        "status": "active",
    },
)


def validate_lessons(lessons: "tuple[dict, ...]" = LESSONS) -> "list[str]":
    """Deterministic registry lint; returns problems (empty = valid)."""
    problems: "list[str]" = []
    seen: "set[str]" = set()
    for row in lessons:
        lid = row.get("id", "<missing id>")
        if lid in seen:
            problems.append(f"{lid}: duplicate id")
        seen.add(lid)
        for fieldname in ("id", "date", "scope", "lesson", "evidence",
                          "status"):
            if not row.get(fieldname):
                problems.append(f"{lid}: missing {fieldname}")
        if row.get("scope") not in _SCOPES:
            problems.append(f"{lid}: unknown scope {row.get('scope')!r}")
        if row.get("status") not in _STATUSES:
            problems.append(f"{lid}: unknown status {row.get('status')!r}")
        ev = row.get("evidence") or []
        if not isinstance(ev, list) or not ev:
            problems.append(f"{lid}: evidence must be a non-empty list")
        else:
            for e in ev:
                if not (isinstance(e, dict) and e.get("repo")
                        and e.get("ref")):
                    problems.append(f"{lid}: evidence entries need "
                                    f"repo + ref")
        text = (row.get("lesson", "") + " "
                + " ".join(str(e) for e in ev)).lower()
        for pat in _FORBIDDEN_IN_TEXT:
            if pat in text:
                problems.append(f"{lid}: forbidden identity string "
                                f"{pat!r} in distributed text")
    return problems


def active_lessons(lessons: "tuple[dict, ...]" = LESSONS) -> "list[dict]":
    return [r for r in lessons if r.get("status") == "active"]


def render_claude_md_section(
        lessons: "tuple[dict, ...]" = LESSONS) -> str:
    """The compact section baked into every onboarded repo's CLAUDE.md
    conventions block (KP_SDLC and the rest of the cohort receive it on
    the next `ctxpack onboard` re-run)."""
    lines = [
        f"**Cross-repo lessons (v{LESSONS_VERSION} — "
        f"`ctxpack lessons` for receipts):** hard-won rules from "
        f"reviewed incidents across the cohort; treat them as "
        f"constraints on quality of work:",
        "",
    ]
    for row in active_lessons(lessons):
        lines.append(f"- `{row['id']}` [{row['scope']}] {row['lesson']}")
    lines += [
        "",
        "When a lesson visibly applies (or fails), bank a "
        "`ctx-incident:` row naming its id — cross-repo incident "
        "evidence is what promotes and retires lessons.",
    ]
    return "\n".join(lines)


def render_cli_listing(lessons: "tuple[dict, ...]" = LESSONS) -> str:
    out: "list[str]" = []
    for row in lessons:
        flag = "" if row.get("status") == "active" else " [RETIRED]"
        out.append(f"{row['id']} ({row['date']}, {row['scope']}){flag}")
        out.append(f"  {row['lesson']}")
        for e in row.get("evidence", []):
            out.append(f"  evidence: {e.get('repo')} — {e.get('ref')}")
        out.append("")
    return "\n".join(out).rstrip()
