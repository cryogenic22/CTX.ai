"""drift-fork/v2 — independent-cluster fixture, fixed-budget arms,
negative controls, presence receipts, cluster-level analysis (Layer 2).

Pre-registered as amendment A5 in PREREGISTRATION-resume-probe.md
(committed 2026-07-11, before this code existed) plus harness notes v2
(2026-07-12, the consolidated-review remediation). A5 supersedes the A3
run design; the A3 fixture mechanics (planted through the REAL
producer) carry over; the A4 grade carries over with the A4.1 polarity
amendment (resume_probe.conflict_flag_positive).

Harness notes v2 (all pre-committed before any scored run):

- The TREATMENT is the parked product's own fork warning, rendered by
  the real checkpoint producer at the top of the gist — never a
  harness simulation. The padded-nowarn arm removes that exact span
  and grows the pinned neutral filler IN ITS PLACE to exact BPE
  parity. On a branch without the product renderer the harness ABORTS
  (run drift-fork/v2 on the updated feat/fork-surfacing-parked).
- The eight clusters are NOT structural clones: head checkpoint order,
  fork revision depth, unrelated-history load, transcript timestamps,
  decision phrasing, and probe phrasing all vary per the pinned
  _VARIATIONS table.
- Grading is polarity-aware (A4.1): a negated conflict token is a
  dismissal, arm-symmetrically.
- ANY failed presence receipt aborts the run (preflight is
  deterministic — there is nothing to exclude around). Unlock requires
  exactly N_CLUSTERS_PINNED complete clusters with exactly 2 paired
  fork probes each.
- Negative controls are hard gates: 0/8 false-alarm clusters and a
  displacement non-inferiority bound (at most 1 harmful-discordant
  cluster) both block the unlock.
- Arm call order is deterministically counterbalanced across clusters
  (arm_order).
- Budget parity requires the exact tokenizer (require_exact_tokenizer;
  the chars//4 fallback is forbidden), and every scored artifact
  stamps context sha256s, the filler sha/length actually inserted, the
  cluster-manifest sha256, and the harness commit.

The scored run stays gated on (i) reviewer approval of the A5 text AND
this harness, then (ii) owner authorization up to $2 (Q3 ruling,
2026-07-11). The runner enforces the interlock (--authorized-run), the
pinned model, and the $2 ceiling (preflight worst-case + running
guard + durable invocation ledger).
"""

from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ...agent.checkpoint import run_checkpoint
from ...agent.session_reader import load_supersession
from ..metrics.cost import count_bpe_tokens
from .fork_fixture import (
    PlantedFork,
    _decision_rows,
    _fid_for_value,
    _write_transcript,
)
from .resume_probe import (
    _FORK_FLAG_TOKENS,
    Probe,
    _grep_windows,
    _norm,
    conflict_flag_positive,
    ctx_context,
    grade,
)

A5_AS_OF = "2026-07-12"
DRIFT_FORK_V2_VERSION = "drift-fork/v2"
FORK_SOURCE = "synthetic-fixture"
N_CLUSTERS_PINNED = 8
PAD_DELTA_ABORT = 3         # |BPE(padded) - BPE(warn)| beyond this aborts

# Cost enforcement (harness notes v2; Q3 ruling ceiling). Prices are
# the pinned model's worst-case USD per MTok; the runner refuses any
# other model on a live run.
FORK_V2_MODEL = "claude-sonnet-4-6"
CEILING_USD = 2.00
PRICE_IN_PER_MTOK = 3.00
PRICE_OUT_PER_MTOK = 15.00
MAX_COMPLETION_TOKENS = 512

# Worst-case request pricing (harness notes v4, finding 3): the bound
# covers the ENTIRE request — _build_prompt's wrapper and the system
# prompt, not just context+question — with pinned headroom because
# cl100k only approximates Claude's billing tokenizer, plus a fixed
# allowance for role/message framing invisible in the prompt text.
# The SAME bound backs the preflight total and every per-attempt guard.
TOKENIZER_HEADROOM = 1.25
REQUEST_OVERHEAD_TOKENS = 64


def request_worst_case_usd(question_block: str, context: str) -> float:
    from ..metrics.fidelity import QA_SYSTEM_MSG, _build_prompt
    full = _build_prompt(question_block, context or "(no context provided)")
    in_bpe = count_bpe_tokens(QA_SYSTEM_MSG + "\n" + full, model="claude")
    in_bpe = math.ceil(in_bpe * TOKENIZER_HEADROOM) + REQUEST_OVERHEAD_TOKENS
    return (in_bpe * PRICE_IN_PER_MTOK
            + MAX_COMPLETION_TOKENS * PRICE_OUT_PER_MTOK) / 1_000_000

# Arms. Primary comparison is ctx-nowarn-padded vs ctx-warn (fixed
# total budget); ctx-nowarn is the disclosed additive-overhead
# secondary; grep is the standing over-powered null, fork probes only.
# The false-alarm control is ONE completion per cluster on the clean
# no-fork context ("ctx-clean") — the two ctx arms coincide there by
# construction, so a second identical call is not an arm comparison
# (consolidated review, answer (a)/(b)); the detector's own output is
# captured as a separate receipt instead.
FORK_ARMS = ("ctx-nowarn", "ctx-nowarn-padded", "ctx-warn", "grep")
PRIMARY_ARMS = ("ctx-nowarn-padded", "ctx-warn")
DISPLACEMENT_ARMS = ("ctx-nowarn-padded", "ctx-warn")
FALSE_ALARM_ARM = "ctx-clean"

# 2 fork probes x 4 arms + 1 displacement x 2 arms + 1 false-alarm x 1
EXPECTED_COMPLETIONS_PER_CLUSTER = 11

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

# Pre-committed per-cluster variation (consolidated review blocker 2 —
# the clusters must not be structural clones). head_order: which head
# session checkpoints first; depth: 1 = the heads supersede the base
# fact directly, 2 = a pinned linear revision lands first and the heads
# supersede IT (the fork sits deeper in the chain); distractors: how
# many pinned unrelated decisions the base session banks alongside
# (attention/history load); ts: transcript timestamp base (date+hour);
# template: decision phrasing; q_variant: probe question phrasing.
_VARIATIONS = {
    "c01": {"head_order": ("b", "c"), "depth": 1, "distractors": 0,
            "ts": "2026-07-12T08", "template": 0, "q_variant": 0},
    "c02": {"head_order": ("c", "b"), "depth": 1, "distractors": 4,
            "ts": "2026-07-12T11", "template": 1, "q_variant": 1},
    "c03": {"head_order": ("b", "c"), "depth": 2, "distractors": 2,
            "ts": "2026-07-12T14", "template": 2, "q_variant": 2},
    "c04": {"head_order": ("c", "b"), "depth": 1, "distractors": 6,
            "ts": "2026-07-12T17", "template": 3, "q_variant": 0},
    "c05": {"head_order": ("b", "c"), "depth": 2, "distractors": 0,
            "ts": "2026-07-13T08", "template": 1, "q_variant": 1},
    "c06": {"head_order": ("c", "b"), "depth": 1, "distractors": 8,
            "ts": "2026-07-13T11", "template": 0, "q_variant": 2},
    "c07": {"head_order": ("b", "c"), "depth": 2, "distractors": 4,
            "ts": "2026-07-13T14", "template": 3, "q_variant": 0},
    "c08": {"head_order": ("c", "b"), "depth": 1, "distractors": 2,
            "ts": "2026-07-13T17", "template": 2, "q_variant": 1},
}

# Depth-2 clusters: the pinned intermediate value the linear revision
# banks for each FORK key before the heads fork off it. Joined into the
# run-wide uniqueness/non-substring validation.
_REVISION_VALUES = {
    "c03": {"REPLICA-PLACEMENT-MODE": "place-hex-cell-grid",
            "BACKUP-CIPHER-SUITE": "cipher-kyber-hybrid"},
    "c05": {"BILLING-PRORATION-METHOD": "prorate-usage-weighted",
            "INVOICE-NUMBER-FORMAT": "inv-seq-checksum-b32"},
    "c07": {"FLAG-ROLLOUT-CURVE": "roll-shadow-mirror-only",
            "EXPERIMENT-BUCKET-SALT": "salt-site-scoped-daily"},
}

_DECISION_TEMPLATES = (
    "Decision: set {key} to {value} for the pipeline because {reason}.",
    "Decision: adopt {value} as the {key} setting because {reason}.",
    "Decision: standardize {key} on {value} because {reason}.",
    "Decision: switch {key} over to {value} because {reason}.",
)
_QUESTION_VARIANTS = (
    "Proceeding with {key} = {value} as the current value — drafting "
    "the next step on that basis. OK?",
    "Quick check before I implement: {key} is {value}, right? I'll "
    "build the rollout plan on that.",
    "Planning the next milestone assuming {key} stays at {value} — "
    "anything I should know first?",
)

_REASON_BASE = "the initial rollout needed a safe default"
_REASON_REV = "the mid-quarter tuning pass adjusted it"
_REASON_B = "the follow-up load test favored it"
_REASON_C = "the incident review demanded it"
_REASON_TIP = "the quarterly capacity review settled it"

# Pinned unrelated-history decisions (value-free, key-free): banked in
# the base session per the cluster's distractor count. Validated to
# contain no conflict-token vocabulary and no cluster term.
_DISTRACTOR_POOL = (
    "Decision: adopt the documented staging checklist for the release "
    "train because the ops calendar review approved it.",
    "Decision: keep the weekly dependency-update cadence because the "
    "audit trail stayed clean last quarter.",
    "Decision: archive standup notes to the shared drive monthly "
    "because retrieval requests were rare.",
    "Decision: leave the documentation style guide unchanged because "
    "the writers voted to defer the revision.",
    "Decision: publish the support rotation calendar quarterly because "
    "monthly churn confused the schedule.",
    "Decision: run the onboarding checklist review each cycle because "
    "tooling drift kept invalidating it.",
    "Decision: keep build dashboards on the team wall display because "
    "visibility shortened response times.",
    "Decision: batch routine chore tickets into one weekly sweep "
    "because scattered fixes fragmented focus.",
)

# Padding filler (pinned; A5): deterministic, value-free, neutral. It
# contains no fork content, no cluster key or value, and no A4
# conflict-token vocabulary — validated at build time. In v2 it grows
# IN PLACE of the removed product warning span (blocker 1), never as a
# tail block.
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


def cluster_manifest_sha256() -> str:
    """sha256 over every pinned run input (blocker 6): the cluster
    table, variation table, revision values, phrasing templates,
    distractor pool, and filler."""
    blob = json.dumps({
        "table": _CLUSTER_TABLE, "variations": _VARIATIONS,
        "revisions": _REVISION_VALUES, "templates": _DECISION_TEMPLATES,
        "questions": _QUESTION_VARIANTS, "distractors": _DISTRACTOR_POOL,
        "pad": (_PAD_HEADER,) + _PAD_SENTENCES,
        "arms": {"fork": FORK_ARMS, "displacement": DISPLACEMENT_ARMS,
                 "false_alarm": FALSE_ALARM_ARM},
    }, sort_keys=True, default=list).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# Exact-manifest gate (recheck residual): the sha above was STAMPED
# into artifacts but never VERIFIED — a drifted cluster table would
# run and merely record a different hash. Any run (dry or live) now
# aborts unless the computed manifest matches this pinned value, so
# changing any pinned input requires a conscious re-pin in the same
# reviewable diff.
PINNED_CLUSTER_MANIFEST_SHA256 = (
    "554f249271474f14491bb29bc793779212288c34a9248578490da9566b686c1b")


def require_pinned_manifest() -> str:
    """Abort unless the computed cluster manifest matches the pinned
    sha256. Returns the (verified) sha for stamping."""
    got = cluster_manifest_sha256()
    if got != PINNED_CLUSTER_MANIFEST_SHA256:
        raise RuntimeError(
            "cluster manifest drifted from the pinned sha256 — the "
            "run inputs are not the reviewed inputs (exact-manifest "
            f"gate): pinned {PINNED_CLUSTER_MANIFEST_SHA256[:16]}…, "
            f"got {got[:16]}…. A deliberate change to any pinned "
            "input must re-pin PINNED_CLUSTER_MANIFEST_SHA256 in the "
            "same commit.")
    return got


def require_exact_tokenizer() -> str:
    """Budget parity must not depend on the environment (blocker 6):
    count_bpe_tokens silently falls back to chars//4 without tiktoken,
    which is forbidden for v2. Returns the stamp for the artifact."""
    try:
        import tiktoken
        tiktoken.get_encoding("cl100k_base")
        return f"tiktoken {tiktoken.__version__} cl100k_base"
    except Exception as exc:  # noqa: BLE001 — any failure means no parity
        raise RuntimeError(
            "drift-fork/v2 requires tiktoken for exact budget parity "
            f"(the chars//4 fallback is forbidden): {exc}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def arm_order(cluster_index: int) -> "tuple[str, ...]":
    """Deterministic counterbalancing (blocker 9): the fork-arm call
    order rotates by cluster index, pre-committed."""
    k = cluster_index % len(FORK_ARMS)
    return FORK_ARMS[k:] + FORK_ARMS[:k]


def displacement_arm_order(cluster_index: int) -> "tuple[str, ...]":
    k = cluster_index % len(DISPLACEMENT_ARMS)
    return DISPLACEMENT_ARMS[k:] + DISPLACEMENT_ARMS[:k]


# ── Budget-enforced execution (retry-level; recheck residual) ──
#
# The v2 ceiling guard was per PLAN ROW while the API helper retried up
# to 5x internally: retries were neither individually ceiling-guarded
# nor ledgered, and the ledger row was written only after a call
# returned (a crash mid-call left unrecorded spend). call_with_budget
# moves the attempt loop to the harness: EVERY attempt (initial or
# retry) is ceiling-guarded BEFORE issue and ledgered immediately
# before ("issued") and after ("result") the call.

ATTEMPT_MAX_RETRIES = 5      # pinned (harness notes v2 item 5, unchanged)
ATTEMPT_BASE_DELAY_S = 2.0   # exponential 2s..32s


def call_with_budget(attempt_fn: "Callable[[], tuple[str, dict, str]]",
                     *, worst_case_usd: float, spent_usd: float,
                     ceiling_usd: float,
                     record: "Callable[[dict], None]",
                     price_usage: "Callable[[dict], Optional[float]]",
                     max_retries: int = ATTEMPT_MAX_RETRIES,
                     base_delay: float = ATTEMPT_BASE_DELAY_S,
                     sleep: "Callable[[float], None]" = time.sleep,
                     ) -> "tuple[Optional[str], float, str]":
    """(answer, new_spent_usd, outcome) — outcome is "ok", "ceiling",
    "empty-response", or "api-error".

    An HTTP-200 completion with EMPTY (or whitespace-only) text is not
    a valid measurement — it cannot be told apart from API degeneracy,
    and grading it would bank a false miss. It aborts the scored run
    (recheck residual; no silent retry either — at temperature 0 a
    retry is a hidden regrade opportunity). Its cost IS charged: the
    call was billed.

    Cost accounting (pinned): an "ok" attempt adds its actual priced
    usage (worst case when usage is missing); a "transient" HTTP
    rejection was not billed by the API (no usage block) and adds 0; a
    "fatal" outcome (timeout, reset, non-retriable HTTP) has UNKNOWN
    billing and reserves the full worst case. The guard runs before
    every attempt, so spend can never cross the ceiling by more than
    zero — the run aborts first.
    """
    for attempt in range(max_retries + 1):
        if spent_usd + worst_case_usd > ceiling_usd:
            record({"phase": "guard-abort", "attempt": attempt,
                    "worst_case_usd": worst_case_usd,
                    "spent_usd": round(spent_usd, 6)})
            return None, spent_usd, "ceiling"
        record({"phase": "issued", "attempt": attempt,
                "worst_case_usd": worst_case_usd})
        text, usage, status = attempt_fn()
        cost = price_usage(usage)
        if status == "ok":
            spent_usd += cost if cost is not None else worst_case_usd
            if not (text or "").strip():
                record({"phase": "result", "attempt": attempt,
                        "status": "empty", "cost_usd": cost,
                        "usage": usage or None})
                return text, spent_usd, "empty-response"
            record({"phase": "result", "attempt": attempt,
                    "status": "ok", "cost_usd": cost,
                    "usage": usage or None})
            return text, spent_usd, "ok"
        if status == "transient":
            record({"phase": "result", "attempt": attempt,
                    "status": "transient", "cost_usd": cost or 0.0,
                    "error": (text or "")[:200]})
            spent_usd += cost or 0.0
            if attempt < max_retries:
                sleep(base_delay * (2 ** attempt))
                continue
            return text, spent_usd, "api-error"
        # fatal: billing unknown — reserve the worst case
        spent_usd += cost if cost is not None else worst_case_usd
        record({"phase": "result", "attempt": attempt,
                "status": "fatal",
                "cost_usd": cost if cost is not None else worst_case_usd,
                "error": (text or "")[:200]})
        return text, spent_usd, "api-error"
    return None, spent_usd, "api-error"  # retries exhausted (unreached)


# ── Product warning (the treatment is the product, never a simulation) ──


def _product_header() -> "Optional[str]":
    try:
        from ...agent.checkpoint import FORK_GIST_HEADER
        return FORK_GIST_HEADER
    except ImportError:
        return None


def split_product_warning(context: str) -> "tuple[str, str, str]":
    """(before, warn_block, after) around the PRODUCT fork warning in a
    context built from the real gist. Raises when the product renderer
    is absent (pre-feature branch) or the warning is missing — the v2
    treatment is the product output; the harness never simulates it
    (blocker 1; the F2 no-simulated-fallback semantics)."""
    header = _product_header()
    if header is None:
        raise RuntimeError(
            "product fork-warning renderer unavailable on this branch — "
            "run drift-fork/v2 on the updated parked branch "
            "(feat/fork-surfacing-parked); the harness never simulates "
            "the treatment")
    idx = context.find(header)
    if idx < 0:
        raise RuntimeError(
            "product fork warning absent from the built context — the "
            "warn arm cannot be constructed (no simulated fallback)")
    end = context.find("\n## ", idx + 1)
    if end < 0:
        end = len(context)
    return context[:idx], context[idx:end], context[end:]


# ── Run-wide validation ──


def _all_pinned_values() -> "list[str]":
    vals = [v for _, rows in _CLUSTER_TABLE for row in rows
            for v in row[1:]]
    vals += [v for m in _REVISION_VALUES.values() for v in m.values()]
    return vals


def _validate_run() -> None:
    keys = [row[0] for _, rows in _CLUSTER_TABLE for row in rows]
    values = _all_pinned_values()
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
    neutral_texts = ((_PAD_HEADER,) + _PAD_SENTENCES + _DISTRACTOR_POOL
                     + _DECISION_TEMPLATES + _QUESTION_VARIANTS
                     + (_REASON_BASE, _REASON_REV, _REASON_B, _REASON_C,
                        _REASON_TIP))
    for text in neutral_texts:
        n = _norm(text)
        for tok in _FORK_FLAG_TOKENS:
            if tok in n:
                raise RuntimeError(
                    f"pinned neutral text contains conflict-token "
                    f"vocabulary {tok!r}: {text[:60]!r}")
        for item in keys + values:
            if _norm(item) in n:
                raise RuntimeError(
                    f"pinned neutral text contains cluster term "
                    f"{item!r}: {text[:60]!r}")
    for cid, var in _VARIATIONS.items():
        if var["depth"] == 2 and cid not in _REVISION_VALUES:
            raise RuntimeError(f"{cid}: depth 2 but no pinned revision "
                               f"values")


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
    index: int          # position in the pinned table (counterbalancing)
    root: str
    fork_ledger: str
    fork_transcripts: str
    nofork_ledger: str
    forks: list         # 2 x PlantedFork
    disp: Displacement
    fa: FalseAlarm


def _checkpoint(tdir: str, ledger: str, sid: str, texts: "list[str]",
                ts_base: str) -> None:
    run_checkpoint(
        _write_transcript(os.path.join(tdir, f"{sid}.jsonl"), texts, sid,
                          ts_base=ts_base),
        ledger, as_of=A5_AS_OF)


def _decision_text(cid: str, key: str, value: str, reason: str) -> str:
    tpl = _DECISION_TEMPLATES[_VARIATIONS[cid]["template"]]
    return tpl.format(key=key, value=value, reason=reason)


def _build_fork_side(root: str, cid: str, rows) -> tuple:
    var = _VARIATIONS[cid]
    tdir = os.path.join(root, "fork", "transcripts")
    ledger = os.path.join(root, "fork", "ctx")
    os.makedirs(tdir, exist_ok=True)
    base_sid = f"{cid}aaaaa-fork-base"
    rev_sid = f"{cid}rrrrr-fork-rev"
    head_sids = {"b": f"{cid}bbbbb-fork-head",
                 "c": f"{cid}ccccc-fork-head"}
    ts = var["ts"]

    base_texts = [_decision_text(cid, key, v0, _REASON_BASE)
                  for key, v0, _, _ in rows]
    base_texts += list(_DISTRACTOR_POOL[:var["distractors"]])
    _checkpoint(tdir, ledger, base_sid, base_texts, ts)
    base_rows = _decision_rows(ledger, base_sid[:8])
    base_fids = {key: _fid_for_value(base_rows, v0, "base")[0]
                 for key, v0, _, _ in rows}

    # depth 2: a pinned linear revision supersedes the base for the two
    # FORK keys; the heads then fork off the REVISION fact, so the fork
    # sits deeper in the chain (blocker 2's revision-depth variation).
    # The DAG fold still roots the conflict at the CHAIN ORIGIN (the
    # base fact) — supersedes_targets only changes which fact the heads
    # declare against.
    supersede_targets = dict(base_fids)
    if var["depth"] == 2:
        rev_vals = _REVISION_VALUES[cid]
        _checkpoint(tdir, ledger, rev_sid, [
            (_decision_text(cid, row[0], rev_vals[row[0]], _REASON_REV)
             + f"\nSupersedes: {base_fids[row[0]]} — revisited, "
               f"{_REASON_REV}.")
            for row in rows[:2]], ts)
        rev_rows = _decision_rows(ledger, rev_sid[:8])
        for row in rows[:2]:
            fid, _ = _fid_for_value(rev_rows, rev_vals[row[0]], "revision")
            supersede_targets[row[0]] = fid

    # head B supersedes the fork roots for the 2 fork keys PLUS the
    # displacement key's base; head C only the two fork keys. The
    # checkpoint ORDER of the heads is the pinned head_order variation.
    def _head_texts(col: int, reason: str, with_disp: bool) -> "list[str]":
        texts = [
            (_decision_text(cid, row[0], row[col], reason)
             + f"\nSupersedes: {supersede_targets[row[0]]} — revisited, "
               f"{reason}.")
            for row in rows[:2]]
        if with_disp:
            drow = rows[2]
            texts.append(
                _decision_text(cid, drow[0], drow[2], reason)
                + f"\nSupersedes: {base_fids[drow[0]]} — revisited, "
                  f"{reason}.")
        return texts

    head_spec = {"b": (2, _REASON_B, True), "c": (3, _REASON_C, False)}
    for tag in var["head_order"]:
        col, reason, with_disp = head_spec[tag]
        _checkpoint(tdir, ledger, head_sids[tag],
                    _head_texts(col, reason, with_disp), ts)

    head_rows = {sid[:8]: _decision_rows(ledger, sid[:8])
                 for sid in head_sids.values()}
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
    sid_b, sid_c = head_sids["b"][:8], head_sids["c"][:8]
    for key, v0, vb, vc in rows[:2]:
        conflict = by_base.get(base_fids[key])
        if conflict is None or len(conflict.heads) != 2:
            raise RuntimeError(
                f"{cid}: no 2-head conflict for {key} "
                f"(chain root {base_fids[key]})")
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
    var = _VARIATIONS[cid]
    tdir = os.path.join(root, "nofork", "transcripts")
    ledger = os.path.join(root, "nofork", "ctx")
    os.makedirs(tdir, exist_ok=True)
    base_sid = f"{cid}ddddd-lin-base"
    mid_sid = f"{cid}eeeee-lin-mid"
    tip_sid = f"{cid}fffff-lin-tip"
    ts = var["ts"]

    base_texts = [_decision_text(cid, key, v0, _REASON_BASE)
                  for key, v0, _, _ in rows]
    base_texts += list(_DISTRACTOR_POOL[:var["distractors"]])
    _checkpoint(tdir, ledger, base_sid, base_texts, ts)
    base_rows = _decision_rows(ledger, base_sid[:8])
    base_fids = {key: _fid_for_value(base_rows, v0, "nofork base")[0]
                 for key, v0, _, _ in rows}

    _checkpoint(tdir, ledger, mid_sid, [
        (_decision_text(cid, row[0], row[2], _REASON_B)
         + f"\nSupersedes: {base_fids[row[0]]} — revisited, {_REASON_B}.")
        for row in rows], ts)
    mid_rows = _decision_rows(ledger, mid_sid[:8])
    mid_fids = {key: _fid_for_value(mid_rows, vb, "nofork mid")[0]
                for key, _, vb, _ in rows}

    _checkpoint(tdir, ledger, tip_sid, [
        (_decision_text(cid, row[0], row[3], _REASON_TIP)
         + f"\nSupersedes: {mid_fids[row[0]]} — revisited, "
           f"{_REASON_TIP}.")
        for row in rows], ts)

    _, graph = load_supersession(ledger)
    if graph.conflicts:
        raise RuntimeError(
            f"{cid}: no-fork variant shows {len(graph.conflicts)} "
            f"conflicts — the linear chain did not link")

    key, v0, vb, vc = rows[0]
    tip_rows = _decision_rows(ledger, tip_sid[:8])
    _, fa_turn = _fid_for_value(tip_rows, vc, "nofork tip")
    fa = FalseAlarm(key=key, v0=v0, prior=vb, current=vc,
                    mid_session=mid_sid[:8], tip_session=tip_sid[:8],
                    turn=fa_turn)
    return ledger, fa


def build_cluster(root: str, cid: str, index: int, rows) -> Cluster:
    root = os.path.abspath(root)
    fork_ledger, fork_tdir, forks, disp = _build_fork_side(root, cid, rows)
    nofork_ledger, fa = _build_nofork_side(root, cid, rows)
    return Cluster(cid=cid, index=index, root=root,
                   fork_ledger=fork_ledger, fork_transcripts=fork_tdir,
                   nofork_ledger=nofork_ledger,
                   forks=forks, disp=disp, fa=fa)


def build_clusters(work_dir: str,
                   n: int = N_CLUSTERS_PINNED) -> "list[Cluster]":
    if not 1 <= n <= len(_CLUSTER_TABLE):
        raise ValueError(f"n must be 1..{len(_CLUSTER_TABLE)}")
    _validate_run()
    return [build_cluster(os.path.join(work_dir, cid), cid, i, rows)
            for i, (cid, rows) in enumerate(_CLUSTER_TABLE[:n])]


# ── Probes ──


def cluster_probes(cluster: Cluster) -> "list[tuple[str, Probe]]":
    """(ptype, probe) per cluster: 2 fork + 1 displacement + 1
    false-alarm. Fork/false-alarm wording comes from the cluster's
    pinned question variant (blocker 2); the displacement probe reuses
    the superseded-probe wording."""
    q_tpl = _QUESTION_VARIANTS[_VARIATIONS[cluster.cid]["q_variant"]]
    out: list[tuple[str, Probe]] = []
    for f in cluster.forks:
        question = q_tpl.format(key=f.key, value=f.v1)
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
        question=q_tpl.format(key=fa.key, value=fa.current),
        expected=fa.prior, grade_mode="fork-inverted",
        source_text=(f"{fa.key}: {fa.v0} -> {fa.prior} -> current "
                     f"{fa.current} (linear, no fork)"),
        alt_all=[fa.mid_session, fa.tip_session])))
    return out


# ── Padding (fixed total context budget, filler IN PLACE) ──


def _fit_filler(prefix: str, suffix: str, target_bpe: int, *,
                model: str = "claude") -> "tuple[str, int, int]":
    """Grow the pinned neutral filler BETWEEN prefix and suffix until
    prefix+filler+suffix reaches target_bpe. Returns (filler_text,
    achieved_bpe, delta) with delta = target - achieved."""
    def bpe(f: str) -> int:
        return count_bpe_tokens(prefix + f + suffix, model=model)

    if bpe("") >= target_bpe:
        return "", bpe(""), target_bpe - bpe("")
    filler = _PAD_HEADER
    i = 0
    while bpe(filler) < target_bpe:
        filler += "\n" + _PAD_SENTENCES[i % len(_PAD_SENTENCES)]
        i += 1
    # largest filler prefix that stays at or below target, then a local
    # nudge to land exactly when BPE granularity allows it
    lo, hi = 0, len(filler)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if bpe(filler[:mid]) <= target_bpe:
            lo = mid
        else:
            hi = mid - 1
    best_len, best_bpe = lo, bpe(filler[:lo])
    for length in range(lo, min(lo + 8, len(filler)) + 1):
        b = bpe(filler[:length])
        if b == target_bpe:
            best_len, best_bpe = length, b
            break
        if best_bpe < b <= target_bpe:
            best_len, best_bpe = length, b
    return filler[:best_len], best_bpe, target_bpe - best_bpe


def placebo_context(warn_context: str, *, model: str = "claude"
                    ) -> "tuple[str, int, int, str]":
    """The padded-nowarn arm (blocker 1): the PRODUCT warning span is
    removed and the pinned neutral filler grows IN ITS PLACE — the
    same location, exact BPE parity with the intact context. Returns
    (padded_text, achieved_bpe, delta, filler_used)."""
    before, _warn, after = split_product_warning(warn_context)
    target = count_bpe_tokens(warn_context, model=model)
    filler, achieved, delta = _fit_filler(before, after, target,
                                          model=model)
    return before + filler + after, achieved, delta, filler


def pad_to_bpe(base_text: str, target_bpe: int, *,
               model: str = "claude") -> "tuple[str, int, int]":
    """Tail-append variant kept for parity mechanics tests. The v2 plan
    itself only pads IN PLACE via placebo_context."""
    cur = count_bpe_tokens(base_text, model=model)
    if cur >= target_bpe:
        return base_text, cur, target_bpe - cur
    filler, achieved, delta = _fit_filler(base_text + "\n\n", "",
                                          target_bpe, model=model)
    return base_text + "\n\n" + filler, achieved, delta


# ── Receipts ──


def _edges_ok(ledger_dir: str, fork: PlantedFork) -> bool:
    """Both fact_superseded edges visible to the fold: a conflict rooted
    at the fork's root whose heads are exactly the two planted heads."""
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


def nofork_detector_receipt(ledger_dir: str,
                            context: str) -> "dict[str, bool]":
    """The detector's OWN output on the clean ledger, captured as a
    receipt (blocker 8): the product warning must be absent from the
    context, the fold must see zero conflicts, and no candidates file
    may exist. An empty product warning is itself a valid detector
    receipt (consolidated review, answer (b))."""
    header = _product_header()
    try:
        _, graph = load_supersession(ledger_dir)
        conflicts = len(graph.conflicts)
    except Exception:  # noqa: BLE001
        conflicts = -1
    return {
        "product_warning_absent": bool(header) and header not in context,
        "fold_conflicts_zero": conflicts == 0,
        "candidates_file_absent": not os.path.exists(
            os.path.join(ledger_dir, "candidates.jsonl")),
    }


# ── Run plan ──


@dataclass
class PlanRow:
    probe: Probe
    cluster: str
    cluster_index: int
    ptype: str              # fork | displacement | false-alarm
    arm: str
    context: str
    context_bpe: int
    context_sha256: str
    receipts: dict = field(default_factory=dict)
    pad_delta: Optional[int] = None
    filler_sha256: Optional[str] = None
    filler_len: Optional[int] = None
    fa_anchors: Optional[list] = None


def build_plan(clusters: "list[Cluster]", *, model: str = "claude"
               ) -> "list[PlanRow]":
    """Deterministic full enumeration (no sampling): every probe under
    its pinned arms, contexts and receipts computed pre-flight, arm
    order counterbalanced per cluster (blocker 9). ANY failed receipt
    raises — preflight is deterministic, so there is nothing to exclude
    around (blocker 7)."""
    rows: list[PlanRow] = []
    for cluster in clusters:
        forks_by_key = {f.key: f for f in cluster.forks}
        for ptype, probe in cluster_probes(cluster):
            if ptype == "false-alarm":
                context = ctx_context(cluster.nofork_ledger, probe)
                receipts = {"expected_present":
                            _norm(probe.expected) in _norm(context)}
                receipts.update(nofork_detector_receipt(
                    cluster.nofork_ledger, context))
                if not all(receipts.values()):
                    raise RuntimeError(
                        f"{probe.probe_id}: false-alarm receipts failed "
                        f"({receipts}) — the control requires a clean "
                        f"ledger and a present expected value")
                rows.append(PlanRow(
                    probe=probe, cluster=cluster.cid,
                    cluster_index=cluster.index, ptype=ptype,
                    arm=FALSE_ALARM_ARM, context=context,
                    context_bpe=count_bpe_tokens(context, model=model),
                    context_sha256=sha256_text(context),
                    receipts=receipts,
                    fa_anchors=[cluster.fa.prior, cluster.fa.v0]))
                continue

            # fork + displacement probes live on the fork ledger; the
            # warn context is the PRODUCT context as built (the gist
            # carries the product warning at the top); padded-nowarn
            # replaces the warning span in place; unpadded nowarn is
            # the clean removal (additive-overhead secondary)
            warn = ctx_context(cluster.fork_ledger, probe)
            before, _blk, after = split_product_warning(warn)
            padded, achieved, delta, filler = placebo_context(
                warn, model=model)
            if abs(delta) > PAD_DELTA_ABORT:
                raise RuntimeError(
                    f"{probe.probe_id}: pad delta {delta} exceeds "
                    f"±{PAD_DELTA_ABORT} BPE — budget parity failed")
            contexts = {"ctx-nowarn": before + after,
                        "ctx-nowarn-padded": padded,
                        "ctx-warn": warn}
            target = count_bpe_tokens(warn, model=model)

            if ptype == "fork":
                arms = arm_order(cluster.index)
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
                for arm in PRIMARY_ARMS:
                    r = receipts_by_arm[arm]
                    if not all(r.values()):
                        raise RuntimeError(
                            f"{probe.probe_id}: presence receipts failed "
                            f"on {arm} ({r}) — any failed receipt aborts "
                            f"the run (A5 harness notes v2)")
            else:
                arms = displacement_arm_order(cluster.index)
                receipts_by_arm = {
                    arm: {"expected_present":
                          _norm(probe.expected) in _norm(contexts[arm])}
                    for arm in arms}
                for arm, r in receipts_by_arm.items():
                    if not all(r.values()):
                        raise RuntimeError(
                            f"{probe.probe_id}: displacement receipt "
                            f"failed on {arm} — any failed receipt "
                            f"aborts the run")
            for arm in arms:
                is_padded = arm == "ctx-nowarn-padded"
                rows.append(PlanRow(
                    probe=probe, cluster=cluster.cid,
                    cluster_index=cluster.index, ptype=ptype, arm=arm,
                    context=contexts[arm],
                    context_bpe=count_bpe_tokens(contexts[arm],
                                                 model=model),
                    context_sha256=sha256_text(contexts[arm]),
                    receipts=receipts_by_arm[arm],
                    pad_delta=delta if is_padded else None,
                    filler_sha256=(sha256_text(filler) if is_padded
                                   else None),
                    filler_len=len(filler) if is_padded else None))
    expected = EXPECTED_COMPLETIONS_PER_CLUSTER * len(clusters)
    if len(rows) != expected:
        raise RuntimeError(
            f"plan enumerates {len(rows)} completions, expected "
            f"{expected} ({EXPECTED_COMPLETIONS_PER_CLUSTER} per "
            f"cluster) — the pinned counts drifted")
    return rows


# ── Grading (A4 carried over + A4.1 polarity; false-alarm inverts) ──


def flagged_conflict(answer: str, anchors_any: "list[str]",
                     sids_all: "Optional[list]") -> bool:
    """A4 grade inverted for the false-alarm control: a pinned conflict
    token OUTSIDE a negation scope (A4.1) PLUS an exact anchor (a prior
    chain value verbatim, or both chain session ids)."""
    if not answer:
        return False
    a = _norm(answer)
    if not conflict_flag_positive(a):
        return False
    if any(_norm(x) in a for x in anchors_any if x):
        return True
    sids = [_norm(s) for s in (sids_all or [])]
    return bool(sids) and all(s in a for s in sids)


def grade_row(row: PlanRow, answer: str
              ) -> "tuple[bool, Optional[bool]]":
    """(correct, flagged). Fork rows use the A4/A4.1 grade;
    displacement is exact containment; false-alarm is CORRECT when it
    does NOT flag."""
    if row.ptype == "false-alarm":
        fl = flagged_conflict(answer, row.fa_anchors or [],
                              row.probe.alt_all)
        return (not fl), fl
    return grade(row.probe, answer), None


# ── Cluster-level analysis (pinned in A5 + harness notes v2) ──


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
    """Hard gate (blocker 8): ZERO false-alarm clusters."""
    return n_clusters > 0 and fa_clusters == 0


MAX_HARMFUL_DISCORDANT = 1  # displacement non-inferiority bound (pinned)


def result_key(r: "dict") -> "tuple[str, str, str, str]":
    return (r["cluster"], r["ptype"], r["probe_id"], r["arm"])


def validate_result_manifest(rows: "list[dict]",
                             expected_keys=None) -> None:
    """Result-set manifest gate (substantive re-review finding 1): the
    COMPLETED result set must be the exact unique
    (cluster, ptype, probe_id, arm) enumeration before any analysis —
    absent control rows must never pass a gate by vacuity (no
    false-alarm rows → zero flags; no displacement rows → zero harmful
    clusters). Raises RuntimeError on any deviation."""
    keys = [result_key(r) for r in rows]
    keyset = set(keys)
    if len(keys) != len(keyset):
        seen: set = set()
        dups = sorted({k for k in keys if k in seen or seen.add(k)})
        raise RuntimeError(
            f"result-manifest gate: duplicate result rows {dups[:4]}")
    if expected_keys is not None:
        expected = set(expected_keys)
        missing = sorted(expected - keyset)
        unexpected = sorted(keyset - expected)
        if missing or unexpected:
            raise RuntimeError(
                "result-manifest gate: result set differs from the "
                f"enumerated plan (missing {missing[:4]}, unexpected "
                f"{unexpected[:4]})")
    cids = sorted({k[0] for k in keyset})
    if len(cids) != N_CLUSTERS_PINNED:
        raise RuntimeError(
            f"result-manifest gate: {len(cids)} clusters in results, "
            f"pinned {N_CLUSTERS_PINNED}")
    for cid in cids:
        ck = [k for k in keyset if k[0] == cid]
        fa = [k for k in ck if k[1] == "false-alarm"]
        if [k[3] for k in fa] != [FALSE_ALARM_ARM]:
            raise RuntimeError(
                f"result-manifest gate: {cid} must have exactly one "
                f"false-alarm observation on {FALSE_ALARM_ARM!r} "
                f"(got {sorted(k[3] for k in fa)})")
        disp = sorted(k[3] for k in ck if k[1] == "displacement")
        if disp != sorted(DISPLACEMENT_ARMS):
            raise RuntimeError(
                f"result-manifest gate: {cid} displacement pair "
                f"incomplete (got {disp}, need "
                f"{sorted(DISPLACEMENT_ARMS)})")
        fork = [k for k in ck if k[1] == "fork"]
        pids = sorted({k[2] for k in fork})
        if len(pids) != 2:
            raise RuntimeError(
                f"result-manifest gate: {cid} must have exactly 2 fork "
                f"probes (got {len(pids)})")
        for pid in pids:
            arms = sorted(k[3] for k in fork if k[2] == pid)
            if arms != sorted(FORK_ARMS):
                raise RuntimeError(
                    f"result-manifest gate: {cid}/{pid} fork arms "
                    f"incomplete (got {arms})")
        stray = [k for k in ck
                 if k[1] not in ("fork", "displacement", "false-alarm")]
        if stray:
            raise RuntimeError(
                f"result-manifest gate: unexpected ptype rows {stray[:4]}")
    expected_total = EXPECTED_COMPLETIONS_PER_CLUSTER * N_CLUSTERS_PINNED
    if len(keyset) != expected_total:
        raise RuntimeError(
            f"result-manifest gate: {len(keyset)} unique rows, "
            f"expected {expected_total}")


def cluster_analysis(rows: "list[dict]") -> "dict[str, Any]":
    """Every inferential statistic at cluster level (A5). ``rows`` are
    answered result dicts with cluster/ptype/arm/correct/flagged/
    context_bpe/probe_id keys."""
    live = list(rows)
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
    complete_clusters = 0
    for cid in cids:
        n_padded = sum(1 for r in live if r["cluster"] == cid
                       and r["ptype"] == "fork"
                       and r["arm"] == "ctx-nowarn-padded")
        n_warn = sum(1 for r in live if r["cluster"] == cid
                     and r["ptype"] == "fork" and r["arm"] == "ctx-warn")
        if n_padded == 2 and n_warn == 2:
            complete_clusters += 1
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
    # a gate must never pass by vacuity (re-review finding 1): the
    # false-alarm gate additionally requires one OBSERVED control per
    # pinned cluster — absent rows fail it, they don't satisfy it
    fa_observed = sorted({r["cluster"] for r in live
                          if r["ptype"] == "false-alarm"})
    fa_cids = sorted({r["cluster"] for r in live
                      if r["ptype"] == "false-alarm" and r.get("flagged")})
    gate_pass = (len(fa_observed) == N_CLUSTERS_PINNED
                 and false_alarm_gate(len(fa_cids), n))
    mean_pm = round(sum(padded_miss) / n, 3) if n else None
    mean_wm = round(sum(warn_miss) / n, 3) if n else None

    # completeness (blocker 7): unlock requires EXACTLY the pinned
    # cluster count, each contributing exactly 2 paired fork probes
    complete = (n == N_CLUSTERS_PINNED
                and complete_clusters == N_CLUSTERS_PINNED)

    def disp_cluster_ok(cid: str, arm: str) -> "Optional[bool]":
        sub = [r for r in live if r["cluster"] == cid
               and r["ptype"] == "displacement" and r["arm"] == arm]
        if not sub:
            return None
        return all(r["correct"] for r in sub)

    def disp_acc(arm: str) -> "dict[str, Any]":
        per = [ok for cid in cids
               if (ok := disp_cluster_ok(cid, arm)) is not None]
        k, m = sum(per), len(per)
        return {"clusters_correct": k, "n_clusters": m,
                "accuracy": round(k / m, 3) if m else None,
                "wilson95": wilson_interval(k, m)}

    # displacement non-inferiority HARD gate (blocker 8): clusters
    # where the warning arm got the displacement key wrong while the
    # padded arm got it right — attention displacement harm
    harmful = sum(
        1 for cid in cids
        if disp_cluster_ok(cid, "ctx-warn") is False
        and disp_cluster_ok(cid, "ctx-nowarn-padded") is True)
    # same vacuity guard: the gate requires a COMPLETE displacement
    # pair (both arms observed) in every pinned cluster
    disp_pairs = sum(
        1 for cid in cids
        if disp_cluster_ok(cid, "ctx-warn") is not None
        and disp_cluster_ok(cid, "ctx-nowarn-padded") is not None)
    disp_gate_pass = (disp_pairs == N_CLUSTERS_PINNED
                      and harmful <= MAX_HARMFUL_DISCORDANT)

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

    unlock = bool(complete and p is not None and p < 0.05
                  and mean_pm is not None and mean_pm >= 0.40
                  and mean_wm is not None and mean_wm <= 0.10
                  and gate_pass and disp_gate_pass)
    return {
        "n_clusters": n,
        "completeness": {
            "required_clusters": N_CLUSTERS_PINNED,
            "clusters_with_two_paired_fork_probes": complete_clusters,
            "complete": complete,
        },
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
            "observed_clusters": len(fa_observed),
            "required_observed": N_CLUSTERS_PINNED,
            "rate_limit": "0 flagged clusters (hard gate, v2); all "
                          "pinned clusters must be OBSERVED (v4)",
            "passed": gate_pass,
        },
        "displacement_gate": {
            "harmful_discordant_clusters": harmful,
            "max_allowed": MAX_HARMFUL_DISCORDANT,
            "complete_pairs": disp_pairs,
            "required_pairs": N_CLUSTERS_PINNED,
            "passed": disp_gate_pass,
            "by_arm": {arm: disp_acc(arm) for arm in DISPLACEMENT_ARMS},
        },
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
        "unlock_rule": ("merge eligibility iff ALL of: completeness "
                        "(exactly 8 clusters x 2 paired fork probes); "
                        "sign-test p < 0.05; cluster-mean miss "
                        "(padded-nowarn) >= 0.40; cluster-mean miss "
                        "(warn) <= 0.10; false-alarm gate 0/8; "
                        "displacement non-inferiority gate (harmful "
                        "discordant <= 1). Pre-registered A5 + harness "
                        "notes v2; scored runs only. Merge additionally "
                        "requires the separate code review of the "
                        "parked branch."),
        "unlock": unlock,
    }
