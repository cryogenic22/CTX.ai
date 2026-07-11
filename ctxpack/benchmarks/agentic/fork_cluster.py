"""drift-fork/v2 — independent-cluster fixture, fixed-budget arms,
negative controls, presence receipts, cluster-level analysis (Layer 2).

Pre-registered as amendment A5 in PREREGISTRATION-resume-probe.md
(committed 2026-07-11, before this code existed). A5 supersedes the A3
run design; the A3 fixture mechanics (planted through the REAL
producer) and the A4 grade carry over unchanged — this module changes
the sampling unit (>= 8 independent clusters), the primary comparison
(fixed total context budget: ctx-warn vs ctx-nowarn-padded), and adds
the pinned negative controls (no-fork false alarms + attention
displacement) and per-probe presence receipts.

The scored run this harness drives is gated on (i) reviewer approval
of the A5 text AND this harness, then (ii) owner authorization up to
$2 (Q3 ruling, 2026-07-11). The runner enforces the interlock: live
drift-fork-v2 runs refuse to start without --authorized-run.
"""

from __future__ import annotations

import glob
import hashlib
import math
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from ...agent.checkpoint import run_checkpoint
from ...agent.session_reader import load_supersession
from ..metrics.cost import count_bpe_tokens
from .fork_fixture import (
    PlantedFork,
    _decision_rows,
    _fid_for_value,
    _write_transcript,
    fork_warn_block,
)
from .resume_probe import (
    _FORK_FLAG_TOKENS,
    Probe,
    _grep_windows,
    _norm,
    grade,
    ctx_context,
)

A5_AS_OF = "2026-07-12"
DRIFT_FORK_V2_VERSION = "drift-fork/v2"
FORK_SOURCE = "synthetic-fixture"
N_CLUSTERS_PINNED = 8
MAX_RECEIPTS_FAILED = 1     # A5: a run with >1 excluded fork probe aborts
PAD_DELTA_ABORT = 3         # |BPE(padded) - BPE(warn)| beyond this aborts

# Arms (pinned in A5 + harness notes). Primary comparison is
# ctx-nowarn-padded vs ctx-warn (fixed total budget); ctx-nowarn is the
# disclosed additive-overhead secondary; grep is the standing
# over-powered null, fork probes only.
FORK_ARMS = ("ctx-nowarn", "ctx-nowarn-padded", "ctx-warn", "grep")
CONTROL_ARMS = ("ctx-nowarn-padded", "ctx-warn")
PRIMARY_ARMS = ("ctx-nowarn-padded", "ctx-warn")

# One tuple per cluster: (cid, ((key, v0, vB, vC) x 3)). Rows 0-1 are
# the fork keys (both heads supersede), row 2 is the displacement key
# (linearly superseded — head B only). The false-alarm control targets
# row 0 in the no-fork variant. Every key and value is unique and
# pairwise non-substring ACROSS THE WHOLE RUN (validated at build), and
# no key or value contains A4 conflict-token vocabulary.
_CLUSTER_TABLE = (
    ("c01", (
        ("SNAPSHOT-RETENTION-RULE", "keep-07d-rolling",
         "keep-30d-tiered", "keep-90d-coldline"),
        ("WEBHOOK-RETRY-CEILING", "retry-004-hard-stop",
         "retry-012-with-jitter", "retry-040-slow-lane"),
        ("METRIC-ROLLUP-GRAIN", "grain-060s-rawline",
         "grain-300s-meanfold", "grain-900s-p95fold"),
    )),
    ("c02", (
        ("LOGIN-LOCKOUT-POLICY", "lock-3-strikes-15m",
         "lock-5-strikes-60m", "lock-adaptive-risk"),
        ("PAYLOAD-SIZE-CEILING", "payload-max-002mb",
         "payload-max-016mb", "payload-max-064mb"),
        ("SESSION-IDLE-WINDOW", "idle-20m-logout",
         "idle-45m-softlock", "idle-90m-rememberme"),
    )),
    ("c03", (
        ("REPLICA-PLACEMENT-MODE", "place-same-zone-pair",
         "place-tri-zone-spread", "place-region-mirror"),
        ("BACKUP-CIPHER-SUITE", "cipher-aes128-gcm",
         "cipher-aes256-gcm", "cipher-chacha20-poly"),
        ("FAILOVER-TRIGGER-RULE", "trig-manual-only-ops",
         "trig-auto-30s-quorum", "trig-auto-05s-eager"),
    )),
    ("c04", (
        ("CRAWLER-POLITENESS-DELAY", "crawl-delay-10s-flat",
         "crawl-delay-02s-token", "crawl-delay-30s-peak"),
        ("SITEMAP-REFRESH-CYCLE", "sitemap-daily-0400z",
         "sitemap-hourly-light", "sitemap-weekly-deep"),
        ("ROBOTS-CACHE-LIFETIME", "robots-ttl-24h-hard",
         "robots-ttl-06h-soft", "robots-ttl-72h-lazy"),
    )),
    ("c05", (
        ("BILLING-PRORATION-METHOD", "prorate-daily-linear",
         "prorate-second-exact", "prorate-month-floor"),
        ("INVOICE-NUMBER-FORMAT", "inv-seq-yyyymm-plain",
         "inv-seq-ulid-opaque", "inv-seq-region-coded"),
        ("DUNNING-ESCALATION-STEP", "dun-email-then-pause",
         "dun-3emails-1call", "dun-soft-30d-grace"),
    )),
    ("c06", (
        ("THUMBNAIL-RENDER-PATH", "thumb-lambda-onfly",
         "thumb-batch-nightly", "thumb-edge-precompute"),
        ("VIDEO-TRANSCODE-PRESET", "vt-preset-fast720",
         "vt-preset-hq1080", "vt-preset-av1-2160"),
        ("ASSET-CDN-STRATEGY", "cdn-single-origin",
         "cdn-dual-failback", "cdn-anycast-tiered"),
    )),
    ("c07", (
        ("FLAG-ROLLOUT-CURVE", "roll-1-10-50-100pct",
         "roll-canary-5pct-48h", "roll-ring-by-region"),
        ("EXPERIMENT-BUCKET-SALT", "salt-static-2026q3",
         "salt-rotate-weekly", "salt-per-cohort-hash"),
        ("TELEMETRY-SAMPLE-RATE", "tel-sample-100pct",
         "tel-sample-10pct-adapt", "tel-sample-1pct-tail"),
    )),
    ("c08", (
        ("MIGRATION-LOCK-PROTOCOL", "mig-global-freeze",
         "mig-table-by-table", "mig-shadow-copy-swap"),
        ("SCHEMA-CHECK-CADENCE", "schk-on-deploy-only",
         "schk-hourly-sentinel", "schk-nightly-full"),
        ("QUEUE-DRAIN-DEADLINE", "drain-300s-forced",
         "drain-090s-strict", "drain-off-peak-only"),
    )),
)

_REASON_B = "the follow-up load test favored it"
_REASON_C = "the incident review demanded it"
_REASON_TIP = "the quarterly capacity review settled it"

# Padding filler (pinned; A5): deterministic, value-free, neutral. It
# contains no fork content, no cluster key or value, and no A4
# conflict-token vocabulary — validated at build time. Appended as a
# tail block, the same position the warn block occupies.
_PAD_HEADER = "## Routine operations notes"
_PAD_SENTENCES = (
    "The weekly maintenance window closed without any open action items.",
    "Meeting notes were archived to the shared drive after each standup.",
    "The documentation style guide was reviewed and left unchanged.",
    "Build times stayed within the usual range across the last sprint.",
    "The onboarding checklist was verified against the current tooling.",
    "Routine dependency updates were merged after the standard checks.",
    "The support rotation calendar was published for the coming month.",
    "Test dashboards remained green throughout the reporting period.",
)


def pad_filler_sha256() -> str:
    blob = "\n".join((_PAD_HEADER,) + _PAD_SENTENCES).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ── Run-wide validation ──


def _validate_run() -> None:
    keys = [row[0] for _, rows in _CLUSTER_TABLE for row in rows]
    values = [v for _, rows in _CLUSTER_TABLE for row in rows
              for v in row[1:]]
    for name, items in (("key", keys), ("value", values)):
        low = [x.lower() for x in items]
        if len(set(low)) != len(low):
            raise RuntimeError(f"cluster table {name}s are not unique")
        for a in low:
            for b in low:
                if a != b and a in b:
                    raise RuntimeError(
                        f"cluster table {name} {a!r} is a substring of "
                        f"{b!r} — grading anchors would collide")
            for tok in _FORK_FLAG_TOKENS:
                if tok in a:
                    raise RuntimeError(
                        f"cluster table {name} {a!r} contains conflict-"
                        f"token vocabulary {tok!r} — it would collide "
                        f"with the A4 grade")
    filler = _norm(" ".join((_PAD_HEADER,) + _PAD_SENTENCES))
    for tok in _FORK_FLAG_TOKENS:
        if tok in filler:
            raise RuntimeError(
                f"pad filler contains conflict-token vocabulary {tok!r}")
    for item in keys + values:
        if _norm(item) in filler:
            raise RuntimeError(f"pad filler contains cluster term {item!r}")


# ── Cluster fixture (built through the real producer) ──


@dataclass
class Displacement:
    key: str
    v0: str
    current: str        # vB — head B is the only superseder
    session: str        # sid8 where the current value was banked
    turn: int


@dataclass
class FalseAlarm:
    key: str
    v0: str
    prior: str          # vB — the mid link of the linear chain
    current: str        # vC — the true current value (proposal uses it)
    mid_session: str    # sid8
    tip_session: str    # sid8
    turn: int           # turn of the current value in the tip session


@dataclass
class Cluster:
    cid: str
    root: str
    fork_ledger: str
    fork_transcripts: str
    nofork_ledger: str
    forks: list         # 2 x PlantedFork
    disp: Displacement
    fa: FalseAlarm


def _checkpoint(tdir: str, ledger: str, sid: str,
                texts: "list[str]") -> None:
    run_checkpoint(
        _write_transcript(os.path.join(tdir, f"{sid}.jsonl"), texts, sid),
        ledger, as_of=A5_AS_OF)


def _build_fork_side(root: str, cid: str, rows) -> tuple:
    tdir = os.path.join(root, "fork", "transcripts")
    ledger = os.path.join(root, "fork", "ctx")
    os.makedirs(tdir, exist_ok=True)
    base_sid = f"{cid}aaaaa-fork-base"
    head_b_sid = f"{cid}bbbbb-fork-head"
    head_c_sid = f"{cid}ccccc-fork-head"

    _checkpoint(tdir, ledger, base_sid, [
        (f"Decision: set {key} to {v0} for the pipeline because the "
         f"initial rollout needed a safe default.")
        for key, v0, _, _ in rows])
    base_rows = _decision_rows(ledger, base_sid[:8])
    base_fids = {key: _fid_for_value(base_rows, v0, "base")[0]
                 for key, v0, _, _ in rows}

    # head B supersedes ALL THREE keys; head C only the two fork keys —
    # row 2 stays a linear chain (the displacement control's target)
    _checkpoint(tdir, ledger, head_b_sid, [
        (f"Decision: set {row[0]} to {row[2]} for the pipeline because "
         f"{_REASON_B}.\n"
         f"Supersedes: {base_fids[row[0]]} — revisited, {_REASON_B}.")
        for row in rows])
    _checkpoint(tdir, ledger, head_c_sid, [
        (f"Decision: set {row[0]} to {row[3]} for the pipeline because "
         f"{_REASON_C}.\n"
         f"Supersedes: {base_fids[row[0]]} — revisited, {_REASON_C}.")
        for row in rows[:2]])

    head_rows = {sid[:8]: _decision_rows(ledger, sid[:8])
                 for sid in (head_b_sid, head_c_sid)}
    _, graph = load_supersession(ledger)
    if len(graph.conflicts) != 2:
        raise RuntimeError(
            f"{cid}: planted 2 forks but the DAG fold sees "
            f"{len(graph.conflicts)} conflicts")
    by_base = {c.roots[0]: c for c in graph.conflicts if len(c.roots) == 1}
    disp_key = rows[2][0]
    if base_fids[disp_key] in by_base:
        raise RuntimeError(
            f"{cid}: displacement key {disp_key} shows as a conflict — "
            f"it must stay a linear chain")

    forks: list[PlantedFork] = []
    sid_b, sid_c = head_b_sid[:8], head_c_sid[:8]
    for key, v0, vb, vc in rows[:2]:
        conflict = by_base.get(base_fids[key])
        if conflict is None or len(conflict.heads) != 2:
            raise RuntimeError(
                f"{cid}: no 2-head conflict for {key} "
                f"(base {base_fids[key]})")
        fid_b, turn_b = _fid_for_value(head_rows[sid_b], vb, key)
        fid_c, turn_c = _fid_for_value(head_rows[sid_c], vc, key)
        if sorted((fid_b, fid_c)) != list(conflict.heads):
            raise RuntimeError(
                f"{cid}: fold heads for {key} do not match the planted "
                f"head decisions")
        # A3 (carried over): v1 is the LOWER-SORTED head — the
        # deterministic draw the arm cannot infer
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

    disp_fid, disp_turn = _fid_for_value(
        head_rows[sid_b], rows[2][2], disp_key)
    disp = Displacement(key=disp_key, v0=rows[2][1], current=rows[2][2],
                        session=sid_b, turn=disp_turn)
    return ledger, tdir, forks, disp


def _build_nofork_side(root: str, cid: str, rows) -> tuple:
    """Same keys, linear supersession only: base -> vB -> vC per key.
    The tip supersedes the MID facts, so the fold sees chains, never a
    fork — the false-alarm control's clean ledger."""
    tdir = os.path.join(root, "nofork", "transcripts")
    ledger = os.path.join(root, "nofork", "ctx")
    os.makedirs(tdir, exist_ok=True)
    base_sid = f"{cid}ddddd-lin-base"
    mid_sid = f"{cid}eeeee-lin-mid"
    tip_sid = f"{cid}fffff-lin-tip"

    _checkpoint(tdir, ledger, base_sid, [
        (f"Decision: set {key} to {v0} for the pipeline because the "
         f"initial rollout needed a safe default.")
        for key, v0, _, _ in rows])
    base_rows = _decision_rows(ledger, base_sid[:8])
    base_fids = {key: _fid_for_value(base_rows, v0, "nofork base")[0]
                 for key, v0, _, _ in rows}

    _checkpoint(tdir, ledger, mid_sid, [
        (f"Decision: set {row[0]} to {row[2]} for the pipeline because "
         f"{_REASON_B}.\n"
         f"Supersedes: {base_fids[row[0]]} — revisited, {_REASON_B}.")
        for row in rows])
    mid_rows = _decision_rows(ledger, mid_sid[:8])
    mid_fids = {key: _fid_for_value(mid_rows, vb, "nofork mid")[0]
                for key, _, vb, _ in rows}

    _checkpoint(tdir, ledger, tip_sid, [
        (f"Decision: set {row[0]} to {row[3]} for the pipeline because "
         f"{_REASON_TIP}.\n"
         f"Supersedes: {mid_fids[row[0]]} — revisited, {_REASON_TIP}.")
        for row in rows])

    _, graph = load_supersession(ledger)
    if graph.conflicts:
        raise RuntimeError(
            f"{cid}: no-fork variant shows {len(graph.conflicts)} "
            f"conflicts — the linear chain did not link")
    if fork_warn_block(ledger):
        raise RuntimeError(
            f"{cid}: no-fork variant yields a non-empty warn block — "
            f"the false-alarm control requires a clean ledger")

    key, v0, vb, vc = rows[0]
    tip_rows = _decision_rows(ledger, tip_sid[:8])
    _, fa_turn = _fid_for_value(tip_rows, vc, "nofork tip")
    fa = FalseAlarm(key=key, v0=v0, prior=vb, current=vc,
                    mid_session=mid_sid[:8], tip_session=tip_sid[:8],
                    turn=fa_turn)
    return ledger, fa


def build_cluster(root: str, cid: str, rows) -> Cluster:
    root = os.path.abspath(root)
    fork_ledger, fork_tdir, forks, disp = _build_fork_side(root, cid, rows)
    nofork_ledger, fa = _build_nofork_side(root, cid, rows)
    return Cluster(cid=cid, root=root, fork_ledger=fork_ledger,
                   fork_transcripts=fork_tdir,
                   nofork_ledger=nofork_ledger,
                   forks=forks, disp=disp, fa=fa)


def build_clusters(work_dir: str,
                   n: int = N_CLUSTERS_PINNED) -> "list[Cluster]":
    if not 1 <= n <= len(_CLUSTER_TABLE):
        raise ValueError(f"n must be 1..{len(_CLUSTER_TABLE)}")
    _validate_run()
    return [build_cluster(os.path.join(work_dir, cid), cid, rows)
            for cid, rows in _CLUSTER_TABLE[:n]]


# ── Probes ──


def cluster_probes(cluster: Cluster) -> "list[tuple[str, Probe]]":
    """(ptype, probe) per cluster: 2 fork + 1 displacement + 1
    false-alarm. Fork wording is pinned in A3 and carried over; the
    displacement probe reuses the superseded-probe wording; the
    false-alarm probe is the fork proposal with the TRUE current
    value."""
    out: list[tuple[str, Probe]] = []
    for f in cluster.forks:
        question = (f"Proceeding with {f.key} = {f.v1} as the current "
                    f"value — drafting the next step on that basis. OK?")
        if _norm(f.v2) in _norm(question):
            raise RuntimeError(f"{cluster.cid}: v2 for {f.key} leaks "
                               f"into the proposal")
        out.append(("fork", Probe(
            probe_id=f"{cluster.cid}-fork-{f.key.lower()}",
            kind="drift-fork", session=f.v1_session, turn=f.v1_turn,
            question=question, expected=f.v2, grade_mode="fork",
            source_text=(f"{f.key}: base {f.base_value} ({f.base_fid}); "
                         f"heads {f.v1} (s:{f.v1_session}, {f.v1_fid}) "
                         f"vs {f.v2} (s:{f.v2_session}, {f.v2_fid}) — "
                         f"unreconciled"),
            alt_all=[f.v1_session, f.v2_session])))
    d = cluster.disp
    out.append(("displacement", Probe(
        probe_id=f"{cluster.cid}-disp-{d.key.lower()}",
        kind="fork-displacement", session=d.session, turn=d.turn,
        question=(f"The value of {d.key} was revised over time in this "
                  f"project. What is the CURRENT (final) value? Reply "
                  f"with the value only."),
        expected=d.current, grade_mode="exact",
        source_text=f"{d.key}: {d.v0} -> current {d.current} (linear)")))
    fa = cluster.fa
    out.append(("false-alarm", Probe(
        probe_id=f"{cluster.cid}-fa-{fa.key.lower()}",
        kind="fork-false-alarm", session=fa.tip_session, turn=fa.turn,
        question=(f"Proceeding with {fa.key} = {fa.current} as the "
                  f"current value — drafting the next step on that "
                  f"basis. OK?"),
        expected=fa.prior, grade_mode="fork-inverted",
        source_text=(f"{fa.key}: {fa.v0} -> {fa.prior} -> current "
                     f"{fa.current} (linear, no fork)"),
        alt_all=[fa.mid_session, fa.tip_session])))
    return out


# ── Padding (fixed total context budget) ──


def pad_to_bpe(base_text: str, target_bpe: int, *,
               model: str = "claude") -> "tuple[str, int, int]":
    """Append the pinned neutral filler until the text reaches
    target_bpe. Returns (padded_text, achieved_bpe, delta) where delta
    = target - achieved. Never trims base_text; if base already meets
    or exceeds target it is returned unchanged (delta <= 0)."""
    cur = count_bpe_tokens(base_text, model=model)
    if cur >= target_bpe:
        return base_text, cur, target_bpe - cur
    filler = _PAD_HEADER
    i = 0
    while count_bpe_tokens(base_text + "\n\n" + filler,
                           model=model) < target_bpe:
        filler += "\n" + _PAD_SENTENCES[i % len(_PAD_SENTENCES)]
        i += 1
    # largest filler prefix that stays at or below target, then a local
    # nudge to land exactly when BPE granularity allows it
    lo, hi = 0, len(filler)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        bpe = count_bpe_tokens(base_text + "\n\n" + filler[:mid],
                               model=model)
        if bpe <= target_bpe:
            lo = mid
        else:
            hi = mid - 1
    best_len, best_bpe = lo, count_bpe_tokens(
        base_text + "\n\n" + filler[:lo], model=model)
    for length in range(lo, min(lo + 8, len(filler)) + 1):
        bpe = count_bpe_tokens(base_text + "\n\n" + filler[:length],
                               model=model)
        if bpe == target_bpe:
            best_len, best_bpe = length, bpe
            break
        if best_bpe < bpe <= target_bpe:
            best_len, best_bpe = length, bpe
    padded = base_text + "\n\n" + filler[:best_len]
    return padded, best_bpe, target_bpe - best_bpe


# ── Receipts ──


def _edges_ok(ledger_dir: str, fork: PlantedFork) -> bool:
    """Both fact_superseded edges visible to the fold: a conflict rooted
    at the fork's base whose heads are exactly the two planted heads."""
    try:
        _, graph = load_supersession(ledger_dir)
    except Exception:  # noqa: BLE001 — a broken fold is a failed receipt
        return False
    for c in graph.conflicts:
        if (list(c.roots) == [fork.base_fid]
                and sorted(c.heads) == sorted((fork.v1_fid, fork.v2_fid))):
            return True
    return False


def fork_receipts(context: str, fork: PlantedFork,
                  edges_ok: bool) -> "dict[str, bool]":
    n = _norm(context)
    return {
        "v1_present": _norm(fork.v1) in n,
        "v2_present": _norm(fork.v2) in n,
        "base_present": _norm(fork.base_value) in n,
        "supersession_edges_present": edges_ok,
    }


def fork_probe_excluded(receipts_by_arm: "dict[str, dict]") -> bool:
    """A5: a fork probe missing ANY receipt in an arm under test
    (ctx-warn or ctx-nowarn-padded) is excluded."""
    for arm in PRIMARY_ARMS:
        r = receipts_by_arm.get(arm)
        if not r or not all(r.values()):
            return True
    return False


# ── Run plan ──


@dataclass
class PlanRow:
    probe: Probe
    cluster: str
    ptype: str              # fork | displacement | false-alarm
    arm: str
    context: str
    context_bpe: int
    receipts: dict = field(default_factory=dict)
    pad_delta: Optional[int] = None
    excluded: bool = False
    fa_anchors: Optional[list] = None


def build_plan(clusters: "list[Cluster]", *, model: str = "claude"
               ) -> "tuple[list[PlanRow], list[str]]":
    """Deterministic full enumeration (no sampling): every probe under
    its pinned arms, contexts and receipts computed pre-flight. Returns
    (rows, excluded_fork_probe_ids)."""
    rows: list[PlanRow] = []
    excluded: list[str] = []
    for cluster in clusters:
        warn_blk = fork_warn_block(cluster.fork_ledger)
        if not warn_blk:
            raise RuntimeError(f"{cluster.cid}: empty warn block on the "
                               f"fork ledger — nothing to test")
        forks_by_key = {f.key: f for f in cluster.forks}
        for ptype, probe in cluster_probes(cluster):
            ledger = (cluster.nofork_ledger if ptype == "false-alarm"
                      else cluster.fork_ledger)
            blk = "" if ptype == "false-alarm" else warn_blk
            nowarn = ctx_context(ledger, probe)
            warn = nowarn + ("\n\n" + blk if blk else "")
            target = count_bpe_tokens(warn, model=model)
            padded, achieved, delta = pad_to_bpe(nowarn, target,
                                                 model=model)
            if abs(delta) > PAD_DELTA_ABORT:
                raise RuntimeError(
                    f"{probe.probe_id}: pad delta {delta} exceeds "
                    f"±{PAD_DELTA_ABORT} BPE — budget parity failed")
            contexts = {"ctx-nowarn": nowarn,
                        "ctx-nowarn-padded": padded,
                        "ctx-warn": warn}
            if ptype == "fork":
                arms = FORK_ARMS
                contexts["grep"] = _grep_windows(
                    sorted(glob.glob(os.path.join(
                        cluster.fork_transcripts, "*.jsonl"))),
                    probe, target)
                fork = forks_by_key[probe.probe_id.rsplit(
                    "-fork-", 1)[-1].upper()]
                edges = _edges_ok(cluster.fork_ledger, fork)
                receipts_by_arm = {
                    arm: fork_receipts(contexts[arm], fork, edges)
                    for arm in arms}
                is_excluded = fork_probe_excluded(receipts_by_arm)
                if is_excluded:
                    excluded.append(probe.probe_id)
            else:
                arms = CONTROL_ARMS
                receipts_by_arm = {
                    arm: {"expected_present":
                          _norm(probe.expected) in _norm(contexts[arm])}
                    for arm in arms}
                is_excluded = False
            fa_anchors = ([cluster.fa.prior, cluster.fa.v0]
                          if ptype == "false-alarm" else None)
            for arm in arms:
                rows.append(PlanRow(
                    probe=probe, cluster=cluster.cid, ptype=ptype,
                    arm=arm, context=contexts[arm],
                    context_bpe=count_bpe_tokens(contexts[arm],
                                                 model=model),
                    receipts=receipts_by_arm[arm],
                    pad_delta=(delta if arm == "ctx-nowarn-padded"
                               else None),
                    excluded=is_excluded, fa_anchors=fa_anchors))
    return rows, excluded


# ── Grading (A4 carried over; false-alarm inverts it) ──


def flagged_conflict(answer: str, anchors_any: "list[str]",
                     sids_all: "Optional[list]") -> bool:
    """A4 grade inverted for the false-alarm control: a pinned conflict
    token PLUS an exact anchor (a prior chain value verbatim, or both
    chain session ids)."""
    if not answer:
        return False
    a = _norm(answer)
    if not any(t in a for t in _FORK_FLAG_TOKENS):
        return False
    if any(_norm(x) in a for x in anchors_any if x):
        return True
    sids = [_norm(s) for s in (sids_all or [])]
    return bool(sids) and all(s in a for s in sids)


def grade_row(row: PlanRow, answer: str
              ) -> "tuple[bool, Optional[bool]]":
    """(correct, flagged). Fork rows use the A4 grade; displacement is
    exact containment; false-alarm is CORRECT when it does NOT flag."""
    if row.ptype == "false-alarm":
        fl = flagged_conflict(answer, row.fa_anchors or [],
                              row.probe.alt_all)
        return (not fl), fl
    return grade(row.probe, answer), None


# ── Cluster-level analysis (pinned in A5) ──


def wilson_interval(k: int, n: int, z: float = 1.959964
                    ) -> "list[float]":
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, center - half), 3),
            round(min(1.0, center + half), 3)]


def sign_test_one_sided(pos: int, neg: int) -> "Optional[float]":
    """P(X >= pos | X ~ Binomial(pos+neg, 1/2)); ties are dropped
    before the call. None when there are no discordant clusters."""
    m = pos + neg
    if m == 0:
        return None
    return sum(math.comb(m, k) for k in range(pos, m + 1)) / (2 ** m)


def false_alarm_gate(fa_clusters: int, n_clusters: int) -> bool:
    """A5 gate: false-alarm rate must be <= 1/8 of clusters."""
    return n_clusters > 0 and fa_clusters * 8 <= n_clusters


def cluster_analysis(rows: "list[dict]") -> "dict[str, Any]":
    """Every inferential statistic at cluster level (A5). ``rows`` are
    answered result dicts with cluster/ptype/arm/correct/flagged/
    excluded/context_bpe/probe_id keys."""
    live = [r for r in rows if not r.get("excluded")]
    cids = sorted({r["cluster"] for r in live})

    def fork_miss(cid: str, arm: str) -> "Optional[float]":
        sub = [r for r in live if r["cluster"] == cid
               and r["ptype"] == "fork" and r["arm"] == arm]
        if not sub:
            return None
        return sum(1 for r in sub if not r["correct"]) / len(sub)

    pos = neg = ties = 0
    padded_miss: list[float] = []
    warn_miss: list[float] = []
    padded_any = warn_any = 0
    for cid in cids:
        pm, wm = (fork_miss(cid, "ctx-nowarn-padded"),
                  fork_miss(cid, "ctx-warn"))
        if pm is None or wm is None:
            continue
        padded_miss.append(pm)
        warn_miss.append(wm)
        padded_any += pm > 0
        warn_any += wm > 0
        if pm > wm:
            pos += 1
        elif pm < wm:
            neg += 1
        else:
            ties += 1
    n = len(padded_miss)
    p = sign_test_one_sided(pos, neg)
    fa_cids = sorted({r["cluster"] for r in live
                      if r["ptype"] == "false-alarm" and r.get("flagged")})
    gate_pass = false_alarm_gate(len(fa_cids), n)
    mean_pm = round(sum(padded_miss) / n, 3) if n else None
    mean_wm = round(sum(warn_miss) / n, 3) if n else None

    def disp_acc(arm: str) -> "dict[str, Any]":
        per: list[bool] = []
        for cid in cids:
            sub = [r for r in live if r["cluster"] == cid
                   and r["ptype"] == "displacement" and r["arm"] == arm]
            if sub:
                per.append(all(r["correct"] for r in sub))
        k, m = sum(per), len(per)
        return {"clusters_correct": k, "n_clusters": m,
                "accuracy": round(k / m, 3) if m else None,
                "wilson95": wilson_interval(k, m)}

    by_pid: "dict[str, dict[str, dict]]" = {}
    for r in live:
        if r["ptype"] == "fork":
            by_pid.setdefault(r["probe_id"], {})[r["arm"]] = r
    deltas: list[int] = []
    nw_correct = w_correct = grep_correct = n_pairs = n_grep = 0
    for arms_ in by_pid.values():
        if "ctx-nowarn" in arms_ and "ctx-warn" in arms_:
            n_pairs += 1
            deltas.append(arms_["ctx-warn"]["context_bpe"]
                          - arms_["ctx-nowarn"]["context_bpe"])
            nw_correct += bool(arms_["ctx-nowarn"]["correct"])
            w_correct += bool(arms_["ctx-warn"]["correct"])
        if "grep" in arms_:
            n_grep += 1
            grep_correct += bool(arms_["grep"]["correct"])

    unlock = bool(n and p is not None and p < 0.05
                  and mean_pm is not None and mean_pm >= 0.40
                  and mean_wm is not None and mean_wm <= 0.10
                  and gate_pass)
    return {
        "n_clusters": n,
        "primary": {
            "comparison": "ctx-nowarn-padded vs ctx-warn "
                          "(fixed total context budget)",
            "cluster_mean_miss_padded_nowarn": mean_pm,
            "cluster_mean_miss_warn": mean_wm,
            "sign_test": {"positive_clusters_warn_better": pos,
                          "negative_clusters_warn_worse": neg,
                          "ties_dropped": ties,
                          "p_one_sided": (round(p, 4)
                                          if p is not None else None)},
            "clusters_padded_missed_any": {
                "k": padded_any, "wilson95": wilson_interval(padded_any, n)},
            "clusters_warn_missed_any": {
                "k": warn_any, "wilson95": wilson_interval(warn_any, n)},
        },
        "false_alarm_gate": {
            "flagged_clusters": fa_cids,
            "rate_limit": "<= 1/8 of clusters",
            "passed": gate_pass,
        },
        "displacement_secondary": {
            arm: disp_acc(arm) for arm in CONTROL_ARMS},
        "additive_overhead_secondary": {
            "note": "disclosed, not inferential (A5): the A3-style "
                    "unpadded comparison, the real deployment delta",
            "n_fork_probes": n_pairs,
            "nowarn_unpadded_accuracy": (round(nw_correct / n_pairs, 3)
                                         if n_pairs else None),
            "warn_accuracy": (round(w_correct / n_pairs, 3)
                              if n_pairs else None),
            "mean_warn_block_bpe": (round(sum(deltas) / len(deltas))
                                    if deltas else None),
        },
        "grep_null_disclosed": {
            "n_fork_probes": n_grep,
            "accuracy": (round(grep_correct / n_grep, 3)
                         if n_grep else None),
        },
        "unlock_rule": ("merge eligibility iff ALL of: sign-test "
                        "p < 0.05; cluster-mean miss (padded-nowarn) "
                        ">= 0.40; cluster-mean miss (warn) <= 0.10; "
                        "false-alarm gate passed (pre-registered A5; "
                        "scored runs only). Merge additionally requires "
                        "the separate code review of cf2753c."),
        "unlock": unlock,
    }
