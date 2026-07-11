"""Planted-fork fixture + ``drift-fork/v1`` probe generation (Layer 2).

Pre-registered as amendment A3 in PREREGISTRATION-resume-probe.md
(committed 2026-07-11, before this code existed): the single eval that
gates BOTH remaining proactive-surfacing features — resume-gist fork
warnings (DAG Slice 2b) and dream-fold ``possible_conflict`` emission.

No cohort ledger holds a real fork (0 ``fact_superseded`` edges live),
so the fork is PLANTED through the real producer: synthetic transcripts
are checkpointed with ``run_checkpoint``, so the ledger, gists, events,
and fact_ids under test are all built by the shipped write path — the
only synthetic part is the conversation itself. Every result file
stamps ``fork_source: "synthetic-fixture"``; a real cohort fork, once
one exists, supersedes this fixture as the preferred source.

Shape (mirrors tests/test_supersession_dag.py::
test_why_surfaces_fork_end_to_end): a base session banks one decision
per fork; two head sessions each supersede EVERY base independently.
Both heads declare ``Supersedes:``, so the checkpoint conflict lint is
satisfied — only the DAG fold can see the fork. The teammate proposal
treats the LOWER-SORTED head's value (v1) as settled; grading passes
only on the verbatim OTHER value (v2) or an exact-anchored flag (see
resume_probe.grade, mode "fork").
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass

from ...agent.checkpoint import run_checkpoint
from ...agent.session_reader import (
    _kind_of,
    _kv,
    _primary_value,
    _sections,
    _turn_of,
    load_session,
    load_supersession,
)
from .resume_probe import Probe, _grep_windows, _norm

FIXTURE_AS_OF = "2026-07-11"
FORK_SOURCE = "synthetic-fixture"
DRIFT_FORK_VERSION = "drift-fork/v1"

_BASE_SID = "aaaa1111-fork-base"
_HEAD_SIDS = ("bbbb2222-fork-head", "cccc3333-fork-head")

# One row per planted fork: (key, base value, head-B value, head-C value).
# Values are synthetic, distinctive (>= 12 chars), unique across the
# whole table, and pairwise non-substring — validated at build time so a
# grading anchor can never accidentally occur in another fork's text.
_FORK_TABLE = [
    ("RETRY-BACKOFF-POLICY", "legacy-fixed-500ms",
     "expo-base-750ms", "linear-step-2000ms"),
    ("CACHE-EVICTION-MODE", "naive-fifo-sweep",
     "lru-segmented-8way", "arc-adaptive-split"),
    ("INGEST-BATCH-LIMIT", "batch-cap-0128",
     "batch-cap-0512", "batch-cap-2048"),
    ("AUTH-TOKEN-LIFETIME", "ttl-30min-static",
     "ttl-15min-sliding", "ttl-60min-refresh"),
    ("EXPORT-SCHEMA-TAG", "export-v1-flat",
     "export-v2-nested", "export-v2-columnar"),
    ("QUEUE-OVERFLOW-RULE", "drop-oldest-silent",
     "block-producer-hard", "spill-to-disk-scratch"),
    ("INDEX-REBUILD-CADENCE", "nightly-0300-utc",
     "hourly-incremental-delta", "weekly-full-sunday"),
    ("PARSER-ERROR-BUDGET", "abort-on-first-error",
     "tolerate-3-per-file", "quarantine-bad-rows"),
]

_HEAD_REASONS = ("the follow-up load test favored it",
                 "the incident review demanded it")


@dataclass
class PlantedFork:
    key: str
    base_value: str
    base_fid: str
    v1: str            # the value the proposal treats as settled
    v2: str            # the graded OTHER head value
    v1_fid: str        # lower-sorted head (per A3, the deterministic draw)
    v2_fid: str
    v1_session: str    # sid8
    v2_session: str
    v1_turn: int


@dataclass
class ForkFixture:
    root: str
    ledger_dir: str
    transcript_dir: str
    forks: list


def _validate_table() -> None:
    values = [v for row in _FORK_TABLE for v in row[1:]]
    if len(set(values)) != len(values):
        raise RuntimeError("fork table values are not unique")
    for a in values:
        for b in values:
            if a != b and a in b:
                raise RuntimeError(
                    f"fork table value {a!r} is a substring of {b!r} — "
                    f"grading anchors would collide")


def _entry(text: str, sid: str, ts: str) -> dict:
    return {"type": "assistant", "sessionId": sid, "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": text}]}}


def _write_transcript(path: str, texts: "list[str]", sid: str) -> str:
    # one Decision (+ optional Supersedes) per entry: the producer emits
    # at most one supersession per decision, so pairs never share a turn
    entries = [_entry(t, sid, f"2026-07-11T09:{i:02d}:00Z")
               for i, t in enumerate(texts)]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(json.dumps(e) for e in entries))
    return path


def _decision_rows(ledger_dir: str, sid: str) -> "list[tuple[str, str, int]]":
    """(fact_id, text, turn) for every DECISION banked by one session."""
    doc, _ = load_session(ledger_dir, sid)
    out = []
    for s in _sections(doc):
        if _kind_of(s) != "DECISION":
            continue
        fid = _kv(s, "FACT-ID")
        if fid:
            out.append((fid, _primary_value(s), _turn_of(s)))
    return out


def _fid_for_value(rows, value: str, what: str) -> "tuple[str, int]":
    hits = [(fid, turn) for fid, text, turn in rows if value in text]
    if len(hits) != 1:
        raise RuntimeError(
            f"fixture self-check failed: {what} value {value!r} matched "
            f"{len(hits)} banked decisions (expected exactly 1) — the "
            f"producer did not bank it verbatim")
    return hits[0]


def build_fork_fixture(work_dir: str) -> ForkFixture:
    """Plant the forks through the real checkpoint producer.

    Raises RuntimeError (loudly, never silently degrades) when the
    produced ledger does not contain exactly one 2-head DAG conflict per
    table row — a fixture that half-plants would grade absence, not
    noticing.
    """
    _validate_table()
    root = os.path.abspath(work_dir)
    tdir = os.path.join(root, "transcripts")
    ledger = os.path.join(root, "ctx")
    os.makedirs(tdir, exist_ok=True)

    base_texts = [
        (f"Decision: set {key} to {v0} for the pipeline because the "
         f"initial rollout needed a safe default.")
        for key, v0, _, _ in _FORK_TABLE]
    run_checkpoint(
        _write_transcript(os.path.join(tdir, f"{_BASE_SID}.jsonl"),
                          base_texts, _BASE_SID),
        ledger, as_of=FIXTURE_AS_OF)

    base_rows = _decision_rows(ledger, _BASE_SID[:8])
    base_fids = {key: _fid_for_value(base_rows, v0, "base")[0]
                 for key, v0, _, _ in _FORK_TABLE}

    for head_sid, reason, col in ((_HEAD_SIDS[0], _HEAD_REASONS[0], 2),
                                  (_HEAD_SIDS[1], _HEAD_REASONS[1], 3)):
        texts = [
            (f"Decision: set {row[0]} to {row[col]} for the pipeline "
             f"because {reason}.\n"
             f"Supersedes: {base_fids[row[0]]} — revisited, {reason}.")
            for row in _FORK_TABLE]
        run_checkpoint(
            _write_transcript(os.path.join(tdir, f"{head_sid}.jsonl"),
                              texts, head_sid),
            ledger, as_of=FIXTURE_AS_OF)

    head_rows = {sid[:8]: _decision_rows(ledger, sid[:8])
                 for sid in _HEAD_SIDS}
    _, graph = load_supersession(ledger)
    if len(graph.conflicts) != len(_FORK_TABLE):
        raise RuntimeError(
            f"fixture self-check failed: planted {len(_FORK_TABLE)} forks "
            f"but the DAG fold sees {len(graph.conflicts)} conflicts")

    by_base = {c.roots[0]: c for c in graph.conflicts if len(c.roots) == 1}
    forks: list[PlantedFork] = []
    for key, v0, vb, vc in _FORK_TABLE:
        conflict = by_base.get(base_fids[key])
        if conflict is None or len(conflict.heads) != 2:
            raise RuntimeError(
                f"fixture self-check failed: no 2-head conflict for "
                f"{key} (base {base_fids[key]})")
        sid_b, sid_c = _HEAD_SIDS[0][:8], _HEAD_SIDS[1][:8]
        fid_b, turn_b = _fid_for_value(head_rows[sid_b], vb, key)
        fid_c, turn_c = _fid_for_value(head_rows[sid_c], vc, key)
        if sorted((fid_b, fid_c)) != list(conflict.heads):
            raise RuntimeError(
                f"fixture self-check failed: fold heads for {key} do not "
                f"match the planted head decisions")
        # A3: v1 is the LOWER-SORTED head, so the arm cannot infer the draw
        if conflict.heads[0] == fid_b:
            v1, v2 = vb, vc
            v1_fid, v2_fid, v1_sid, v2_sid, v1_turn = (
                fid_b, fid_c, sid_b, sid_c, turn_b)
        else:
            v1, v2 = vc, vb
            v1_fid, v2_fid, v1_sid, v2_sid, v1_turn = (
                fid_c, fid_b, sid_c, sid_b, turn_c)
        forks.append(PlantedFork(
            key=key, base_value=v0, base_fid=base_fids[key],
            v1=v1, v2=v2, v1_fid=v1_fid, v2_fid=v2_fid,
            v1_session=v1_sid, v2_session=v2_sid, v1_turn=v1_turn))
    return ForkFixture(root=root, ledger_dir=ledger, transcript_dir=tdir,
                       forks=forks)


# ── Probes, warn block, grep arm ──


def fork_candidates(fixture: ForkFixture) -> "list[Probe]":
    """One drift-fork probe per planted fork (question wording pinned in
    A3). The probe's source session is the v1 head's — the session the
    proposal treats as settled; v2 must never appear in the question."""
    out: list[Probe] = []
    for f in fixture.forks:
        question = (f"Proceeding with {f.key} = {f.v1} as the current "
                    f"value — drafting the next step on that basis. OK?")
        if _norm(f.v2) in _norm(question):
            raise RuntimeError(f"fixture self-check failed: v2 for {f.key} "
                               f"leaks into the proposal")
        out.append(Probe(
            probe_id=f"fork-{f.key.lower()}", kind="drift-fork",
            session=f.v1_session, turn=f.v1_turn, question=question,
            expected=f.v2, grade_mode="fork",
            source_text=(f"{f.key}: base {f.base_value} "
                         f"({f.base_fid}); heads {f.v1} "
                         f"(s:{f.v1_session}, {f.v1_fid}) vs {f.v2} "
                         f"(s:{f.v2_session}, {f.v2_fid}) — unreconciled"),
            alt_all=[f.v1_session, f.v2_session]))
    return out


def fork_warn_block(ledger_dir: str) -> str:
    """The candidate feature, simulated at the harness layer: what the
    resume gist WOULD proactively show. Built from the real DAG fold
    over the real events.jsonl plus the banked decision texts — never
    from the planted metadata — so the arm tests the actual candidate
    signal, not an oracle."""
    _, graph = load_supersession(ledger_dir)
    if not graph.conflicts:
        return ""
    fid_map: "dict[str, tuple[str, str, int]]" = {}
    for path in sorted(glob.glob(os.path.join(ledger_dir, "session-*.ctx"))):
        sid = os.path.basename(path)[len("session-"):-len(".ctx")]
        try:
            for fid, text, turn in _decision_rows(ledger_dir, sid):
                fid_map[fid] = (sid, text, turn)
        except Exception:  # noqa: BLE001 — one bad session must not blind
            continue
    # copy matches the detector: the fold flags multiple LIVE SUCCESSOR
    # FACTS for one base — usually different sessions, but a
    # same-session double-supersession counts too (review F3; keep this
    # simulated block textually identical to the product renderer's)
    lines = [
        "## UNRESOLVED SUPERSESSION FORKS (possible_conflict)",
        "Each fact below has INDEPENDENT SUCCESSOR FACTS; its current",
        "value is UNRECONCILED. Do not treat any head as settled —",
        "reconcile (or ask) before acting on one.",
    ]
    for conflict in graph.conflicts:
        for root in conflict.roots:
            sid, text, turn = fid_map.get(root, ("?", f"(fact {root})", -1))
            lines.append(f"- base: {text} (s:{sid}#turn{turn}, fact {root})")
        for head in conflict.heads:
            sid, text, turn = fid_map.get(head, ("?", f"(fact {head})", -1))
            lines.append(f"  - head: {text} (s:{sid}#turn{turn}, "
                         f"fact {head})")
    return "\n".join(lines)


def fork_grep_context(fixture: ForkFixture, probe: Probe,
                      budget_bpe: int) -> str:
    """Grep arm over ALL fixture transcripts (the fork spans two
    sessions, so single-transcript grep would be blind by construction —
    a strawman). Terms include ground-truth words from source_text per
    the standing over-powering rule; budget parity is enforced by the
    caller (max of the two ctx arms — conservative)."""
    paths = sorted(glob.glob(os.path.join(fixture.transcript_dir,
                                          "*.jsonl")))
    return _grep_windows(paths, probe, budget_bpe)
