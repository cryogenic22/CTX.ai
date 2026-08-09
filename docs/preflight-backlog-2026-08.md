# Preflight Backlog — 2026-08 (push-conversion program) · v2

Status: **ratified 2026-08-07 with amendments** (owner + reviewer verdict at
`921fd59`, recorded on `AGENT_COORDINATION.md`). v1 was proposed 2026-08-05;
v2 applies the reviewer's five mandatory corrections and the adopted parts
of the 2026-08-06 adversarial-review assessment. This document **extends**
`docs/execution-plan-2026-07.md`. Same operating shape: one active owner,
one notes-only reviewer, one active thread, six-field contract per task.

**Authorization state (2026-08-07, post re-review):** Loops 1–2 EXECUTED;
the changes-requested re-review's residuals are fixed and a corrected
cohort artifact is committed (`scorecard-20260807T195126Z.json` — cite
the dated immutable file, never an unqualified "latest"). Loops 3, 4a
and 4b were implemented before the changes-requested verdict arrived
mid-session — disclosed on the board, presented for re-review. Mandated
sequence now: **re-review of the corrected range → PF-11 threat model
(defines the poisoning/authority boundary the committed PF-03 schema
must be validated against) → remaining E-6 units → Loops 5–6.** NO live
hook, NO paid experiment, NO parked-branch merge.

## Amendment log (v1 → v2)

1. **PF-01 rewritten.** The first-timestamp/coverage-window approach is
   rejected: backfilled checkpoint timestamps are not session-start
   timestamps, and absence of a receipt never proves "no emission".
   Replaced by a deterministic **per-session receipt fold** (see PF-01).
2. **Extraction basis is not authority.** `marker_stated`
   (`ctxpack/core/factid.py:31`) describes how text was extracted; an
   assistant can emit a `Decision:` marker. New PF-03 adds separate
   `source_role` and `authority` fields; legacy facts default
   unknown/candidate, never owner-approved.
3. **Eligibility split from relevance.** PF-13 no longer depends on the
   matcher (PF-21). Hard eligibility (security, lifecycle, authority,
   freshness, conflict) ships first as a pure policy module; the matcher
   applies relevance afterwards.
4. **Freshness/fork minimums moved before the experiment.** PF-51/PF-52
   minimum implementations now precede PF-41; otherwise its stale-assertion
   and fork-side-action endpoints would measure machinery that doesn't
   exist.
5. **No exact-BPE promise at runtime.** The live path enforces a
   conservative, explicitly labelled estimator budget; exact tokenizer
   counts live only in the evaluation harness where tiktoken can be
   required.
6. **Adopted from the adversarial-review assessment:** experiment scale
   strata + fair flat-file maintenance budget (PF-41); latency
   measured-then-frozen, precomputed index keyed by ledger sha (PF-21/31);
   batched ratification queue — merge evidence may create corroboration,
   never ratification of any kind (PF-03; PF-11 v2.1 later removed
   `user_ratified` entirely — local ratification is unauthenticated
   bookkeeping, owner approval unsatisfiable in v1); fork warnings
   scoped by semantic lineage
   match, not git branches (PF-24/52); drift-control boundaries designed
   now, activated later (new Phase 6); multi-writer safety as an
   external-pilot prerequisite (new §). **Rejected:** implicit
   merge-based ratification; git-branch-defined semantic forks; the
   arbitrary <150ms ceiling (measure first, then freeze).
7. **Language rule (product docs and marketing):** never "cryptographic
   provenance" or "mathematical proof". Hashes prove byte integrity, not
   truth or authorship. Provenance claims are exactly: attributable
   selection with receipts.

## Thesis

> prompt → secure facts → authority/freshness policy → deterministic match
> → fork override → bounded packet → outgoing scan → emission → auditable
> receipt

CTX prevents stale, conflicting, or unauthorized context from silently
steering an agent. Voluntary `recall`/`why` remain the human/reviewer audit
surface. Recall-call rate is retired as a metric. "Doubt" must be a system
state — low margin, stale evidence, competing heads, unknown authority →
CTX says "unknown — verify or reconcile", never silently selects.

## Loop map (reviewer's 10 loops → tasks)

| Loop | Task(s) | Status |
|---|---|---|
| 1 emission telemetry | PF-01 | executed + residuals fixed; re-review pending |
| 2 self-verifying scorecards | PF-02 | executed + residuals fixed; re-review pending |
| 3 authority provenance | PF-03 | executed ahead of mandated order (`6768b74`) — disclosed; PF-11 must validate the schema |
| 4 E-6 security boundary | PF-11..17 | 4a/4b executed (`d2747d5`, `7d389e0`); **PF-11 DRAFTED design-only** (`docs/preflight-threat-model-pf11.md`, awaiting reviewer approval) — post-approval: TM-1..4 P1 fixes → TM-5..7 P2s → retention, PF-16/16b, PF-17 (absorbs TC-1..14) |
| 5 eligibility + min freshness | PF-13, PF-51a | HELD pending re-review |
| 6 deterministic matcher | PF-21 | HELD pending re-review |
| 7 receipts + rendering | PF-22, PF-24 | after Loop 6 |
| 8 shadow evaluation | PF-23 | gates frozen post-calibration |
| 9 live canary | PF-31 | triple-gated |
| 10 falsification experiment | PF-41 | paid ⇒ fresh approvals |

## Governing constraints (standing; none relaxed)

- s:eca3f61c#turn802 gates any new hook surface: Phase-3 activation
  requires an explicit owner `Supersedes:` of that constraint.
- Query-surface expansion FROZEN. No secondary trigger hooks.
- Paid runs (PF-41) require fresh reviewer approval of the prereg plus
  the owner's explicit budget authorization.
- Parked branch: do-not-merge; parked→main banned; its outstanding code
  review gates PF-52's renderer — until cleared, fork evaluation is
  excluded from shadow scoring, not simulated.
- E-6 lands and is approved before any live injection; security and
  injection are never one commit or review unit.
- Frozen: new recall/MCP tools, semantic-graph expansion,
  dream/consolidation, LLM memory rewriting, broad vendor integrations,
  generic-memory/token-compression marketing.

## Dependency spine

```
PF-01, PF-02 (Loops 1–2, authorized) ─→ trustworthy cohort numbers
E-6 (PF-11..17) ─→ PF-03 authority ─→ PF-13 eligibility ─→ PF-51a min freshness
                                                        └→ PF-21 matcher ─→ PF-22/24 receipts+rendering ─→ PF-23 shadow gates ─┐
owner supersession of s:eca3f61c#turn802 ──────────────────────────────────────────────────────────────────────────────────────┼─→ PF-31 canary ─→ PF-41 experiment
PF-52 min fork control (parked review cleared) ────────────────────────────────────────────────────────────────────────────────┘
Phase 6 (PreToolUse/PostToolUse/Stop) — DESIGN alongside PF-13; ACTIVATE only after PF-23 passes
Multi-writer safety — prerequisite for any external multi-agent pilot
```

---

## Phase 0 — Repair observability (Loops 1–2, authorized)

### PF-01 · Per-session emission-receipt fold  *(Loop 1)*
- **Failure addressed:** `emitted_sessions()` (set/None) lets absence of a
  receipt read as "no emission" (`session_reader.py` join); pre-log and
  backfilled sessions are misclassified as "handed nothing".
- **Baseline:** `sessions_zero_recall_no_emission` counts sessions that
  merely predate the log; banked constraint forbids quoting cohort
  numbers until fixed.
- **Target:** replace with `fold_emission_receipts()` → per-session
  outcomes {injected, empty, failed} + malformed-row count. Deterministic
  multi-receipt fold: any `injected` → injected; else any `failed` →
  failed; else empty. A missing receipt is **unmeasured** regardless of
  any timestamp; the `no_emission` bucket is abolished — the only proof
  the hook ran with nothing to say is an `empty` receipt. Report
  injected/empty/failed/malformed/unmeasured separately everywhere
  (classify, scorecard, dashboard).
- **Validation loop:** `tests/test_trust_telemetry.py` — multiple
  receipts per session, pre-log sessions, malformed rows, failed
  logging, backfilled sessions.
- **Kill condition:** none (telemetry honesty; reversible).
- **Claim earned:** zero-recall splits trustworthy; the no-quoting
  constraint on cohort telemetry resolves.

### PF-02 · Self-verifying scorecards  *(Loop 2)*
- **Failure addressed:** a stale `scorecard-latest.json` presents as
  current; population changes are not auditable; denominators conflated.
- **Baseline:** schema v1, no input fingerprints, no staleness check.
- **Target:** schema v2 with `cohort_config_sha256` and per-repo input
  fingerprints (checkpoints.jsonl + injections.jsonl; the capture block
  walks external transcript dirs and is documented as NOT covered);
  `ctxpack scorecard --check` recomputes and exits nonzero when latest
  is stale/missing/pre-v2; denominators measured / unmeasured / excluded
  reported separately; OntoWiz added as an **external unmeasured**
  cohort entry in its own configuration commit (no local ledger — a
  fake path would manufacture data), then the artifact regenerated so
  the population change is auditable.
- **Validation loop:** new `tests/test_scorecard_selfcheck.py` — clean
  check passes; mutated ledger input fails; mutated cohort fails;
  missing/pre-v2 latest fails; external entries appear unmeasured.
- **Kill condition:** none.
- **Claim earned (narrowed per re-review):** the **input freshness** of
  any quoted cohort number is verifiable by one command. Metric
  recomputation is NOT claimed — a hand-edited number over unchanged
  inputs would pass — and capture-block numbers are outside the
  fingerprints entirely. Citations must reference the dated immutable
  artifact, never an unqualified "latest".

## Phase 1 — E-6 expanded (Loop 4; next thread after Loops 1–2)

PF-11 threat model (transcript ingestion, ledger storage, git commits,
telemetry, hook stdout, test fixtures, **memory poisoning, authority**);
PF-12 ingest-side redaction **between transcript normalization and
extraction** — type-only replacements (no unsalted `hash8`; repo-scoped
keyed HMAC only if correlation is required, key never committed);
PF-13 →moved to Phase 2a (eligibility, below) — E-6 provides its security
inputs; PF-14 outgoing scan of the final serialized context (applies to
SessionStart today, preflight later); PF-15 retention/deletion with
containment + symlink checks, dry-run + explicit confirm, honest
reporting (never overclaiming control) of upstream vendor transcript
retention; PF-16 privacy scan across ALL committed
fixtures (the rank_v1 fixture itself was already pseudonymized in
`7438514`); PF-16b committed-artifact path privacy (review finding
2026-08-07 #6): scorecard artifacts carry stable repo aliases with
machine-absolute paths confined to local configuration; PF-17 security
regression suite (leakage, false positives, determinism, malicious
memory content). **Fail-closed rule:** hook
commands stay operationally fail-open, but a scanner failure emits NO
memory and records `failed` — it must never present as a healthy empty
result. Each E-6 concern is its own commit/review unit.

## Phase 2a — Authority + eligibility (Loops 3 & 5, first half)

### PF-03 · Authority provenance  *(Loop 3)*
Separate `source_role` (who wrote the text: user/assistant/tool) and
`authority` (USER_STATED / TOOL_OBSERVED / AGENT_CANDIDATE /
LEGACY_UNKNOWN — PF-11 v2.1 removed `USER_RATIFIED`: local
ratification is a separate unauthenticated-bookkeeping axis, never an
authority value, and owner approval is unsatisfiable in v1) from
extraction basis
(`factid.py:31` `marker_stated` stays what it is: an extraction method).
Stamp source role during transcript parsing. Ratification is an explicit
event referencing a fact_id — never inferred from git presence or a
marker. Cold-start: a **batched ratification queue** (candidates linked
to commits/tests, one-step accept/reject) keeps friction low; a merge
may create corroborating TOOL_OBSERVED evidence for exact code/test
claims but must never silently become any ratification. Legacy facts
default LEGACY_UNKNOWN → render as candidates. Event schemas versioned
honestly.

### PF-13 · Injection-eligibility policy  *(Loop 5a)*
Pure `preflight_policy.py` returning an `EligibilityDecision` with
stable rejection codes; it must not know about matching scores. Hard
gates: security (PF-12/14 passed), lifecycle (banked, not
retracted/superseded), authority (per PF-03; AGENT_CANDIDATE and
LEGACY_UNKNOWN are never authoritative), freshness, conflict (no
unresolved heads unless rendered as a conflict warning). Wires the
existing lifecycle/freshness algebra in `ctxpack/core/states.py`.

### PF-51a · Minimum verified freshness  *(Loop 5b — moved before PF-41)*
The minimal pytest `TOOL_OBSERVED` producer + HEAD verification only.
Unverifiable or legacy facts render as prior observations, never
current directives.

## Phase 2b — Matcher, receipts, shadow gates (Loops 6–8)

### PF-21 · Deterministic matcher  *(Loop 6)*
New module — never calls `hydrate_by_query`. Order: exact
fact-id/path/identifier first; Unicode-safe entity/decision-subject
matching; stable IDF lexical scoring **over eligible facts only**; kind
and authority weights cannot rescue zero relevance; winner margin
applies to lexical ambiguity, not multiple exact matches; stable
tie-break by fact id; no qualifying match ⇒ no output; unresolved forks
bypass ordinary ranking when their **lineage/entity** is matched
(semantic supersession forks — git-branch state may influence ranking
but never defines whether the conflict exists). Runs off a precomputed
index keyed by ledger sha — no full-ledger rescan, no git subprocess
per prompt. Budget: ≤3 facts, conservative **labelled estimator**
ceiling (600–800 est. tokens), frozen after unscored calibration; no
exact-BPE promise at runtime.

### PF-22 · `ctx-preflight/v1` receipts  *(Loop 7a)*
Prompt SHA (never plaintext), session/prompt ids, ledger + HEAD sha,
matcher version, candidate ids + scores, rejection codes, lifecycle/
freshness/authority per emitted fact, output sha, estimator label,
runtime, outcome. **Two durable rows per attempt** — `attempted` before
output, terminal `injected/empty/rejected/failed` after, flushed +
fsynced; an interrupted attempt remains visibly uncertain.

### PF-24 · Rendering + dedup  *(Loop 7b)*
Visibly distinct classes: UNRESOLVED CONFLICT / APPLICABLE CONSTRAINT /
CURRENT DECISION / UNVERIFIED PRIOR OBSERVATION / SOURCE. Stale or
unverified never renders like a current directive. Dedup key: fact id +
state + HEAD + fork-head set; repeat within a session only when state
changes.

### PF-23 · Shadow evaluation  *(Loop 8)*
Calibration and held-out sets split by **repository/task cluster**, not
random prompts; raw customer prompts never committed. Controls include
poisoned, secret-bearing, stale, conflicting, common-word, Unicode and
no-memory prompts. Thresholds frozen by commit only after unscored
calibration; the held-out pass must meet: ≥95% injected-fact precision,
≥80% critical-fact recall, ≤5% no-memory pollution, zero authoritative
rendering of stale/conflicting/untrusted, hard budget, latency
p50/p95/p99 warm+cold **measured, then a ceiling frozen** (no asserted
target first). Fork evaluation excluded until the parked review clears.
Gates fail ⇒ no live hook.

## Phase 3 — Live canary (Loop 9; triple-gated)

### PF-31 · UserPromptSubmit hook
Only after PF-23 passes AND the owner supersedes s:eca3f61c#turn802 AND
reviewer approval of the hook unit. Initial scope: exact identifiers,
user-approved constraints, reviewed decisions, applicable fork
warnings. Cached parsed ledger/index state keyed by ledger sha.
Diagnostics to stderr (stdout becomes model context). Fail-open with a
durable failure receipt — a timeout never masquerades as "no relevant
memory". No secondary triggers.

## Phase 4 — Falsification experiment (Loop 10; paid ⇒ fresh approvals)

### PF-41 · Three-arm preregistered comparison
Arms: gist-only / gist+preflight / **maintained** flat-file+grep — both
memory arms get the same maintenance budget, maintenance time recorded
(a neglected flat file is a straw man). Cluster by independent
repository/task, never by prompt. Primary analysis at fixed total
context budget; **scale strata** (sessions, supersessions, handoffs) so
the small-history regime where flat files win is visible rather than
averaged away. One primary composite: **avoidable control failure**
(stale assertion, fork-side action, constraint violation, repeated
failed approach). Hard safety gates: harmful injection, attention
displacement. Secondary: recovery time, overhead. Complete responses +
invocation evidence preserved under the artifact self-audit rules.
Kill condition: preflight loses to flat-file ⇒ stop broad agent-memory
positioning; CTX remains a deterministic checkpoint/provenance/audit
utility.

## Phase 5 — Full freshness + fork control (post-experiment)

PF-51 full TOOL_OBSERVED expansion beyond pytest; PF-52 fork-surfacing
renderer integrated into preflight (parked review must clear first),
explicit reconciliation recorded as a new decision referencing both
predecessors.

## Phase 6 — Drift-control boundaries (design now, activate later)

The same policy engine reused at three additional boundaries, with four
graduated modes — observe / advise / ask / block:
- **PreToolUse:** ask or block when a proposed action deterministically
  violates a ratified constraint. Only exact, current, authoritative,
  deterministic policies qualify for block; matcher-based or ambiguous
  judgments stay advise/ask.
- **PostToolUse:** record TOOL_OBSERVED evidence; invalidate freshness
  where repository state changed.
- **Stop/TaskCompleted:** prevent "done" while required tests,
  deliverables or reconciliations remain outstanding.
Design may proceed alongside PF-13 (same policy engine); **activation
is frozen** until the PF-23 primary gates pass — this preserves the
secondary-trigger freeze.

## External-pilot prerequisite — multi-writer safety

Before any multi-agent/team pilot: replace shared writable journals
with immutable per-session/per-checkpoint event segments plus a
deterministic derived index, so concurrent agents append independent
segments without last-writer-wins corruption. The board's
one-active-owner rule is a workaround, not a product property.

## What CTX can and cannot guarantee (positioning discipline)

Can (if built as specified): ineligible/stale/unauthorized facts never
render as current directives; known conflicts never silently
linearized; hard constraints evaluated before guarded actions; every
packet attributable to fact ids + matcher version; CTX failure
distinguishable from "nothing relevant"; deterministic policy
violations blockable. Cannot: prove an extracted fact true without
evidence; force a model to obey advisory context; remember unrecorded
objectives; guarantee complete retrieval; guarantee generalization.
Market the first list only.

## Decisions only the owner can make

1. Loop-3 (authority) start timing relative to E-6.
2. Phase-3 activation (supersession of s:eca3f61c#turn802).
3. Phase-4 budget and go/no-go after reviewer prereg approval.
4. PF-16 fixture disposition; git-history purge of the withdrawn one.
5. External-pilot timing (gated on multi-writer safety).
