# Preflight Backlog — 2026-08 (push-conversion program)

Status: **proposed 2026-08-05** — owner ratification pending. Origin: the
2026-08-05 strategy verdict on the scriptiva field report (recorded
verbatim-in-substance on `AGENT_COORDINATION.md` under Reviewer Notes).
This document **extends** `docs/execution-plan-2026-07.md`; it does not
replace it. Same operating shape: one active owner, one notes-only
reviewer, one active thread at a time, six-field contract per task
(**failure addressed / baseline / target / validation loop / kill
condition / claim earned**).

## Thesis change this backlog implements

Three independent deployments (OntoWiz 0 recall calls, setu near-zero,
scriptiva 0.4%) show agent-initiated recall is not a viable primary
interface. The product becomes:

> A deterministic decision-control layer: before an agent acts, CTX
> supplies a bounded packet of relevant constraints, current decisions,
> unresolved forks and evidence status — with exact provenance and an
> auditable receipt (`ctx-preflight/v1`).

Voluntary `recall`/`why` remain the **human/reviewer audit surface**, not
the agent product. Recall-call rate is retired as a success metric;
prompt-time push deliberately makes it irrelevant.

Two owner-agent overclaims corrected per the verdict, on the record:
(1) near-zero pull usage does not prove deficient model metacognition is
the *sole* cause — low need, gist sufficiency, tool-selection friction
and incomplete telemetry are live alternatives; (2) prompt-time injection
is **not a cheap fix** — it is a synchronous, every-prompt security and
relevance boundary (the UserPromptSubmit hook blocks model processing
while it runs).

## Verified code receipts behind this backlog (checked 2026-08-05)

- `ctxpack/core/hydrator.py:244` — `hydrate_by_query` scores by
  **unweighted term overlap** (docstring: programmatic fallback path).
  Confirmed inadequate as a live injector; Phase 2 builds a new matcher.
- `ctxpack/agent/injection_log.py:109` + `session_reader.py:634` — the
  absent-log case is already reported as unmeasured, but a session that
  **predates the log's first row** while the log exists lands in
  `sessions_zero_recall_no_emission` ("handed nothing") at
  `session_reader.py:677-680`. Coverage is binary where it must be an
  interval. This is the Phase-0 defect, stated precisely.
- `ctxpack/cli/main.py:1420` — `_HOOK_SETTINGS` carries
  PreCompact/SessionStart/SessionEnd/Stop only; no UserPromptSubmit.
  Adding one is **new hook surface** and is gated (see Phase 3).

## Governing constraints (all standing; none relaxed here)

- E-6 remains the next owner thread. Phase 1 *is* E-6, with scope
  expanded per the verdict. Phase 0 is small enough to precede it and is
  a precondition for using any cohort numbers.
- Banked constraint s:eca3f61c#turn802 (no injection surface beyond what
  already exists). **Phase 3 activation requires an explicit owner
  ratification recorded as a `Supersedes:` of that constraint.** Building
  the matcher in shadow mode (Phase 2) does not touch the constraint.
- Query-surface expansion stays FROZEN (no new recall/MCP tools).
- Any paid run (Phase 4) requires fresh reviewer approval of the
  preregistration plus the owner's explicit budget authorization.
- Parked branch `feat/fork-surfacing-parked`: do-not-merge; parked→main
  banned; its outstanding code review gates PF-52.
- E-6 lands and is approved **before** any live injection; security and
  injection are one initiative but never one commit or review unit.
- Frozen for the duration: new recall/MCP tools, semantic-graph
  expansion, dream/consolidation, LLM memory rewriting, secondary
  trigger hooks (test-failed / raw-grep), broad vendor integrations,
  generic-memory or token-compression marketing.

## Dependency spine

```
PF-01..02 (Phase 0, observability) ─→ any use of cohort numbers
E-6 expanded (PF-11..17) ─┬─→ PF-21..24 shadow matcher ─→ gates green ─┐
                          │                                            ├─→ PF-31 live preflight ─→ PF-41 behavioral experiment ─→ PF-51..52 freshness + fork control
owner ratification superseding s:eca3f61c#turn802 ─────────────────────┘
```

---

## Phase 0 — Repair observability (before citing any cohort number)

### PF-01 · Injection-log coverage intervals
- **Failure addressed:** sessions predating the injection log are
  classified "handed nothing" rather than "unmeasured"
  (`session_reader.py:677-680` join against `injection_log.py:109`).
- **Baseline:** `emitted_sessions()` returns a set or `None`; no notion
  of when instrumentation began.
- **Target:** coverage represented as an interval (first-receipt
  timestamp); `classify_read_path` buckets pre-coverage sessions into
  `sessions_zero_recall_emission_unmeasured`.
- **Validation loop:** regression test with sessions before/after the
  log's first row; existing absent-log tests unchanged.
- **Kill condition:** none (telemetry honesty; reversible).
- **Claim earned:** zero-recall splits are trustworthy per-site.

### PF-02 · Scorecard denominators + staleness
- **Failure addressed:** measured/unmeasured/excluded conflated; a stale
  scorecard can present as "latest"; OntoWiz not a separate cohort row.
- **Baseline:** `scorecards/scorecard-latest.json` semantics.
- **Target:** three denominators reported separately; "latest" status
  fails automatically when inputs are newer than the artifact; OntoWiz
  as its own cohort/config change; scorecard regenerated.
- **Validation loop:** scorecard tests + regenerated artifact committed.
- **Kill condition:** none.
- **Claim earned:** cohort numbers usable in Phase-2 gate design.

## Phase 1 — E-6 expanded (the next owner thread, unchanged)

### PF-11 · Threat model (superset of original E-6)
Transcript ingestion, ledger storage, git commits, telemetry, hook
stdout, test fixtures — **plus memory poisoning and authority**:
automatic push makes a poisoned fact reach every future prompt, so the
threat model must treat assistant-inferred text as untrusted input.
Validation: threat-model doc reviewed; each threat maps to a control or
a disclosed gap. Claim earned: security review exists (directive T9).

### PF-12 · Ingest-side redaction
Redaction runs **before literal extraction or any persistent write**.
Default replacement is **type-only** (`[REDACTED:aws-key]`), never an
unsalted `hash8` fingerprint (low-entropy secrets are guessable from
short hashes); correlation, if ever needed, uses a repo-scoped keyed
HMAC whose key is never committed. Validation: leakage corpus tests +
false-positive corpus + determinism gate. Kill: >5% false-positive rate
on the benign corpus blocks default-on.

### PF-13 · Injection-eligibility policy (schema + evaluator, no hook)
A fact is auto-injectable only when policy passes: lifecycle (banked,
not retracted/superseded), authority (owner/user-approved or
deterministically tool-observed; agent-inferred defaults to
**candidate**, never authoritative), freshness (current or n/a),
security (passed PF-12 + PF-14), relevance (threshold + margin, PF-21),
conflict (no unresolved heads unless rendered as a conflict warning).
Validation: property tests over the policy table; poisoning fixtures
from PF-11 stay ineligible. Claim earned: the authority layer the
verdict calls "a critical addition to E-6".

### PF-14 · Outgoing-context scan
A second scan at every emission boundary — applies to the existing
SessionStart gist today, preflight later. Validation: planted-secret
fixtures never reach hook stdout. Kill: same false-positive bound as
PF-12.

### PF-15 · Retention + deletion controls
Retention windows for CTX-created artifacts (raw `.ctx`, gists,
receipts); deletion dry-run + explicit confirmation; documentation
reports — without overclaiming control over — upstream vendor transcript
retention. Validation: dry-run/confirm tests; docs reviewed.

### PF-16 · rank_v1 fixture re-label
`tests/fixtures/rank_v1/kp_sdlc_ca35891c_events.jsonl` (123
personal-path hits) re-generated synthetic-by-policy or formally
accepted by the owner; same class as the withdrawn calibration fixture.

### PF-17 · Security regression suite
Secret leakage, false positives, deterministic output, malicious memory
content — the durable gate for PF-12..14. Runs in the non-slow suite.

## Phase 2 — Shadow-mode matcher (build without installing any hook)

### PF-21 · Deterministic matcher cascade (new module)
- **Failure addressed:** no injector-grade matcher exists;
  `hydrate_by_query` is unweighted overlap and must not be reused.
- **Target:** cascade — (1) exact literal/path/fact-id/identifier,
  (2) normalized multi-word entity/decision-subject, (3) IDF-weighted
  lexical over fact fields, (4) kind+authority weighting, (5) threshold
  **plus winner margin**, (6) no match ⇒ **no injection** — never
  "closest available". Unresolved forks are a separate high-priority
  output class, not a ranked fact. Output ≤3 facts, hard 600–800 BPE
  ceiling; exact ceiling frozen after an unscored calibration.
- **Validation loop:** deterministic (byte-stable ranking) + adversarial
  common-word and identifier cases.
- **Kill condition:** PF-23 gates unreachable after calibration ⇒ no
  live injection (the concept survives as audit/receipt tooling only).

### PF-22 · `ctx-preflight/v1` receipt
Prompt **hash** (never plaintext), session/prompt ids, git HEAD + ledger
sha, matcher version, candidate fact-ids + scores, emitted fact-ids,
rejection reasons, lifecycle/freshness/authority per emitted fact,
emitted-context sha + BPE, runtime, outcome
(injected/empty/rejected/failed). Receipts prove what was selected and
emitted — behavioral benefit is Phase 4's question, never inferred from
receipts (the delivery-is-not-use lesson, again).

### PF-23 · Shadow replay + labelled gates
Replay historical prompts from the three sites; record what *would*
have been injected. Human-label a sanitized set: required / relevant-
but-unnecessary / harmful-stale / no-memory-needed / conflicting /
adversarial. **Candidate gates, frozen by commit after an unscored
pilot:** ≥95% precision among injected facts; ≥80% recall on critical
must-recall facts; ≤5% of no-memory-needed prompts receive anything;
zero authoritative rendering of stale/conflicting/untrusted facts; hard
budget respected; p50/p95 latency measured (no asserted target before
measurement). **Gates fail ⇒ live injection does not activate.**

### PF-24 · Packet rendering + SessionStart dedup
Visibly distinct classes: UNRESOLVED CONFLICT / APPLICABLE CONSTRAINT /
CURRENT DECISION / UNVERIFIED PRIOR OBSERVATION / SOURCE (fact-id +
repo-relative source). Stale/unverified never renders in the same form
as a current directive. Prompt-time injection never repeats a fact
already in-session unless its state changed, a new fork appeared, HEAD
invalidated the evidence, or the prompt contains an exact identifier
requiring it.

## Phase 3 — Live preflight (triple-gated)

### PF-31 · UserPromptSubmit hook
Gates: E-6 approved **and** PF-23 gates green **and** owner ratification
recorded as `Supersedes:` of s:eca3f61c#turn802 **and** reviewer
approval of the hook unit. Initial scope only: exact literal/entity
matches, owner-approved constraints, reviewed current decisions,
applicable unresolved-fork warnings. **No secondary triggers**
(test-failed, raw-grep) until the primary mechanism is proven. Fail-open
with a **durable failure receipt** — a timeout must never masquerade as
"no relevant memory". Latency budget from PF-23 measurements.

## Phase 4 — Behavioral experiment (preregistered; paid ⇒ fresh approvals)

### PF-41 · Three-arm comparison
Arms: (1) SessionStart gist only; (2) gist + prompt preflight;
(3) maintained flat file + grep/native memory. Primary analysis at
**fixed total context budget**; additive overhead secondary. Primary
outcomes: confident stale assertions, acting on one side of an
unresolved fork, constraint violations, repeating a documented failed
approach, time to recover the authoritative source, harmful false
alarms / attention displacement. **Recall-call rate is not a metric.**
Kill condition (verbatim from the verdict): if preflight does not beat
the flat-file condition, retain CTX as an audit/checkpoint utility and
stop broad memory claims.

## Phase 5 — Verified freshness + fork control (after Phase 4)

### PF-51 · TOOL_OBSERVED producer (pytest only) + HEAD verification
Only the pytest producer first; claims verified against current HEAD;
unverifiable facts render **unknown**, never current. Aligns with
`docs/track-c-verified-freshness-spec.md` and its standing gates
(E-6 + deterministic spike + calibration).

### PF-52 · Fork-surfacing into preflight
Integrate the reviewed fork-surfacing implementation into the preflight
packet; competing heads require explicit reconciliation recorded as a
new decision referencing both predecessors. **Depends on the parked
branch clearing its outstanding code review; do-not-merge stands until
then.**

---

## Decisions only the owner can make

1. Ratify this backlog (or edit) — Phase 0 + Phase 1 sequencing in
   particular.
2. Phase 3 activation — the supersession of s:eca3f61c#turn802 is the
   owner's call alone.
3. Phase 4 budget and go/no-go, after reviewer approval of its prereg.
4. PF-16 disposition of the rank_v1 fixture (re-label vs. formal
   acceptance) and whether the withdrawn calibration fixture's git
   history is purged.
