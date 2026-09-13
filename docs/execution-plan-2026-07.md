# Execution Plan — 2026-07 (ratified)

Status: **ratified 2026-07-11** with statistical amendments — see the
ratification record at the end of `docs/notes.md`. Source directive and
alignment response: `docs/notes.md`. Governing benchmark contract:
`ctxpack/benchmarks/compactbench/PREREGISTRATION.md` (amended only by
commit, before any scored run).

Operating shape: one active owner (per `AGENT_COORDINATION.md`), one
notes-only reviewer, one active thread at a time. Every task below states
the six-field contract required by the directive: **failure addressed /
baseline / target / validation loop / kill condition / claim earned**.
No task is "done" on code merge — it is done when its loop runs green and
its artifact exists.

Standing constraint: all loops are **CI-or-manual**. No daemons, no
schedulers, no SessionStart injection beyond what already exists (banked
constraint, s:eca3f61c#turn802).

---

## Dependency spine

```
W1-5 cost fix ─────────┐
E-1 probe hardening ───┼─→ E-3 unscored pilot ─→ freeze power/budget ─→ E-4 powered run ─→ G-7 replication
E-2 prereg amendment ──┘                                                    │
E-5 fuzzing ─→ E-7 Track C spec spike                                       └─→ G-8 Track C full build
E-6 security ─┬─→ G-6 external onboarding  (recruitment W1-6 starts now)
G-4 doctor ───┘
W1-1..W1-4, G-1..G-3: independent, schedulable in gaps
```

---

## Week 1 — cheap, high-signal, no new preregistration

### W1-1 · Capability registry + README refocus  *(directive T1)*
- **Failure addressed:** broad feature surface makes the product story
  unfocused; experimental modules can be mistaken for validated capability.
- **Baseline:** README markets packing, hydration, guards, and session
  memory with equal weight; ContextGuard / `dream.py` / ConfidenceTracker /
  `state_parser.py` / IncrementalPacker have zero callers but no label.
- **Target:** `docs/capability-registry.md` classifying every module
  `core` / `experimental` / `legacy-deprecation-candidate`; README leads
  with session memory only; one product diagram; ten-minute quick start.
- **Validation loop:** `scripts/check_capability_registry.py` (CI) — fails
  if a module exists in `ctxpack/` with no registry row, or if README's
  top section names an `experimental`/`legacy` module without its label.
- **Kill condition:** none (docs + lint; fully reversible).
- **Claim earned:** "the flagship is deterministic session memory;
  everything else is labelled experimental."

### W1-2 · Claims ledger + CI gate  *(directive T3; owner decision #5)*
- **Failure addressed:** public claims can drift from evidence (it already
  happened once — the retracted 26x/93% numbers).
- **Baseline:** claims live in README/papers with no machine-checked link
  to result artifacts.
- **Target:** `docs/claims-ledger.md` — one row per public claim: text,
  supporting immutable result file, corpus type, n + CI, date/model/judge,
  status (`measured | directional | unmeasured | retracted`).
- **Validation loop:** `scripts/check_claims.py` (CI) — **fails** on
  numerical/comparative claims in README/papers not present in the ledger
  with a `measured` artifact link; **warns** on qualitative positioning.
  Retracted claims reappearing anywhere = hard fail (extends the existing
  ground rule).
- **Kill condition:** if the checker false-positives >3 times in week 1,
  narrow its claim-detection patterns before re-enabling CI-fail mode.
- **Claim earned:** "every number we publish traces to an immutable
  artifact — enforced, not promised."

### W1-3 · Token accounting unification  *(directive T4 — claim verified true)*
- **Failure addressed:** user-facing telemetry reports whitespace splits as
  "tokens" (`ctxpack/core/hydrator.py:55,196,297`,
  `ctxpack/integrations/mcp_server.py:642-644`) while the eval stack
  correctly uses BPE — the exact "BPE ≠ words" failure paid for once already.
- **Baseline:** `tokens_injected` / `ctx_tokens` = whitespace counts,
  unlabelled.
- **Target:** one core estimator (stdlib-only, deterministic, calibrated —
  tiktoken stays benchmarks-only per ground rule) returning
  `(count, estimator_label)`; every telemetry surface carries the label;
  exact BPE remains at the benchmarks/eval layer.
- **Validation loop:** `tests/test_token_accounting.py` + a calibration
  check in the benchmark suite: estimator within **≤5%** of cl100k on the
  benchmark corpus (measure first; if a calibrated stdlib estimator cannot
  reach 5%, report the achievable bound to the owner rather than silently
  relabelling).
- **Kill condition:** calibration worse than 15% → keep whitespace count
  but rename the field so it can never read as tokens.
- **Claim earned:** "all reported token numbers identify their tokenizer."

### W1-4 · Default tool surface  *(directive T16)*
- **Failure addressed:** 20 MCP tools advertised equally; agents burn
  context on tool descriptions and pick wrong surfaces.
- **Baseline:** flat tool list; no token budget on descriptions.
- **Target:** default surface = `resume`, `recall`, `why`, `literals`,
  `checkpoint`; timeline/decisions/graph/stats documented as advanced.
  Onboarding docs + CLAUDE.md block (v3) lead with the five.
- **Validation loop:** `tests/test_mcp_tool_budget.py` — total description
  bytes under a committed budget; docs lint that the five defaults appear
  before any advanced tool. Adoption check at the 07-18 cohort report:
  ≥90% of ledger reads use the five defaults.
- **Kill condition:** if cohort telemetry shows an "advanced" tool in the
  top five by real usage, promote it instead of fighting reality.
- **Claim earned:** "the agent surface is five operations, not twenty."

### W1-5 · CompactBench cost reporting fix  *(banked precondition, s:bdfbd48b#turn445)*
- **Failure addressed:** the smoke's "~$1/cell" projection was wrong
  ($60 full run, not $25); budget decisions can't be made on it.
- **Baseline:** per-cell cost estimated, not measured from API usage.
- **Target:** driver aggregates actual usage (input/output tokens × model
  price) per probe fork and per cell, stamps `cost_usd` +
  `usage_breakdown` into the results JSON; run-level total printed at exit.
- **Validation loop:** unit tests on synthetic usage records; one `--smoke`
  run whose reported total reconciles with the console bill within 5%.
- **Kill condition:** none (instrumentation; results schema is additive —
  existing result files untouched per immutability rule).
- **Claim earned:** unblocks decision #2's first gate; all future run
  costs are measured, not projected.

### W1-6 · Pilot recruitment brief  *(directive T12, start-now half; owner decision #3)*
- **Failure addressed:** external validation requires teams; recruitment
  has zero lead time budgeted.
- **Baseline:** 6-repo cohort, all one owner's repos; zero external teams.
- **Target:** a one-page brief (what a pilot gets, what is measured —
  fallback rate, resume time, stale-decision errors — what it costs them,
  the two-week protocol) that Kapil can send today.
- **Validation loop:** none automatable — the loop is Kapil's outreach;
  track responses on the coordination board.
- **Kill condition:** n/a. **Onboarding is hard-gated on E-6 + G-4** —
  the brief must say "pilot starts after security review", dated honestly.
- **Claim earned:** none yet; this only starts the clock.

---

## Weeks 2–5 — the evidence program

### E-1 · Probe hardening (anti-ceiling)  *(pre-committed 2026-07-04)*
- **Failure addressed:** sentinel probes were too easy — ctx and grep both
  near-ceiling on recall, so the run couldn't discriminate.
- **Baseline:** grep arm 207/240 (86%) overall; recall probes ~ceiling.
- **Target:** probe families keyed to the four co-primary endpoints:
  (1) **literal exactness** — full 12-hex SHA / exact version required,
  8-hex truncation graded wrong (20/30 of grep's sentinel misses);
  (2) **superseded-value** — probes ask for the *current* value after ≥2
  revisions; (3) **cycle reliability** — same probe re-asked at every k,
  graded on consistency; (4) **adherence** — pct=20 with real forbidden
  commands (tool-inspection grading proved out at pct=20).
- **Validation loop:** the E-3 unscored pilot is the loop — each probe
  family must land grep in the **30–70%** band (discriminating range).
  Any family where grep >85% goes back for hardening before scoring.
- **Kill condition:** if a family cannot be made discriminating without
  becoming unrealistic, drop it from co-primary status *in the prereg
  amendment*, documented — never silently.
- **Claim earned:** none directly; makes E-4's claims possible.

### E-2 · Preregistration amendment v2  *(directive T2/T10 + ratified statistical amendments)*
- **Failure addressed:** (a) 240 clustered probes from 2 seeds are not 240
  experiments — probe-level McNemar overstates evidence; (b) DR@K-only
  endpoints re-buy the ceiling; (c) missing LLM-summary baseline arm.
- **Baseline:** PREREGISTRATION.md v1: probe-level analysis, DR@K primary,
  five arms, no multiplicity control.
- **Target — amendment committed before any scored run**, containing:
  - **Unit of analysis: the seeded trajectory (cluster).** Per-endpoint
    arm comparisons via seed-level paired tests (permutation or Wilcoxon
    over per-seed success proportions); no probe-level p-values in
    headline claims.
  - **Endpoint hierarchy:** co-primary = literal fidelity, superseded-value
    accuracy, cycle reliability, adherence; secondary/descriptive = DR@K,
    input tokens + measured cost, latency.
  - **Multiplicity:** Holm–Bonferroni across the four co-primaries,
    family-wise α = 0.05; primary contrast ctx-vs-grep; native and
    LLM-summary arms are secondary contrasts.
  - **Arms:** + LLM-written-summary memory (the LangMem/ACE-style
    comparator).
  - **Power protocol:** seed count and budget computed from E-3 pilot
    variance, then **frozen by commit**; deviations log mandatory.
  - **Stop rule (verbatim from the directive):** if ctx does not beat grep
    on the preregistered endpoints, stop broad memory claims and
    reposition as an audit/provenance tool.
- **Validation loop:** the amendment is auditable only as a commit that
  predates the first scored result file (the A1 lesson, banked
  s:eca3f61c#turn446).
- **Kill condition:** n/a — this task *is* the kill-condition machinery.
- **Claim earned:** "the powered run's statistics were designed before the
  data existed."

### E-3 · Unscored pilot → frozen power + budget
- **Failure addressed:** powering a run without variance estimates guesses
  at n; budget approval needs a real number.
- **Baseline:** sentinel (2 seeds) gives point estimates only.
- **Target:** small unscored pilot (~2–3 seeds on hardened probes, all
  arms) → per-seed variance per endpoint → power calculation → frozen
  seed count + dollar budget, committed. Pilot results are marked
  UNSCORED and never cited.
- **Validation loop:** grep lands 30–70% per co-primary family (E-1's
  gate); power calc reproducible from the pilot artifact.
- **Kill condition:** if the frozen budget exceeds what Kapil approves,
  reduce scope by dropping secondary arms (never co-primary endpoints)
  and re-freeze.
- **Claim earned:** decision #2's remaining gates clear; E-4 is go
  pending Kapil's explicit budget sign-off.

### E-4 · Powered CompactBench run  *(directive T10 — conditional per decision #2)*
- **Failure addressed:** the core claim is unproven at power; everything
  downstream (deep tech, pilots, public claims) hinges here.
- **Baseline:** sentinel: decisive vs native *within-run*; parity with
  grep at ceiling; differentiation axes visible but unpowered.
- **Target:** the E-2 contract executed exactly; results in a new
  versioned file under `ctxpack/benchmarks/compactbench/results/`; run in
  a work dir **outside the repo** (known gitBranch-stamping leak).
- **Validation loop:** the preregistered analysis script over the results
  artifact; deviations log; claims-ledger rows created from the artifact.
- **Kill condition:** the preregistered stop rule. Executed honestly: a
  loss reframes the product as audit/provenance and the claims ledger is
  updated the same day.
- **Claim earned (if it wins):** the North Star claim, with cluster-aware
  CIs — the first citable superiority result. Also unblocks G-7, G-8.

### E-5 · Parser/ledger fuzzing  *(directive T6)*
- **Failure addressed:** the ledger's trust story depends on the parser
  never banking unsupported facts; adversarial inputs are untested
  (prompt-injected fake markers, nested quoted `Decision:`, truncated
  JSONL, huge tool payloads, duplicate/reordered events, conflicting
  supersessions).
- **Baseline:** guards exist (use-vs-mention, fenced-code, pasted-content)
  but only example-based tests; no reject-reason codes.
- **Target:** seeded deterministic fuzz generator + committed corpus in
  `tests/fuzz/`; every accepted fact carries a valid source span; every
  reject has a deterministic reason code; measured precision ≥99.5% on a
  labelled protected-fact corpus (markers, literals, negations).
- **Validation loop:** `python -m pytest tests/test_fuzz_parser.py`
  (deterministic, CI); the corpus grows by one case per parser bug found —
  the fuzz corpus *is* the regression loop.
- **Kill condition:** none; findings feed fixes.
- **Claim earned:** "no unsupported fact silently enters the ledger" —
  and the labelled corpus E-7 needs.

### E-6 · Threat model + secret redaction  *(directive T9 — elevated; blocks G-6)*
- **Failure addressed:** the ledger is git-committable by design and
  transcripts carry secrets (tokens, env vars, pasted credentials); one
  leak kills adoption in exactly the regulated wedge being targeted.
- **Baseline:** no redaction pass; no threat model; literals extractor
  actively hunts high-entropy identifiers (it would bank a leaked key
  *verbatim* — the feature is the vulnerability).
- **Target:** `docs/security-threat-model.md` (secrets retention, stored
  prompt injection, fake-decision injection via repo content,
  cross-project leakage, symlink/path traversal, untrusted MCP callers,
  ledger tampering) + a deterministic redaction pass in the literal/verbatim
  path (common credential patterns → `[REDACTED:<type>:<hash8>]`,
  preserving referential identity), on by default, limitations documented.
- **Validation loop:** `tests/test_secret_redaction.py` — seeded-secret
  corpus (AWS/GitHub/JWT/PEM/etc. shapes): **0** seeded secrets reach
  gist, `.ctx`, or `events.jsonl`; determinism gates still green
  (redaction must not break byte-determinism).
- **Kill condition:** if redaction false-positives destroy legitimate
  identifiers (SHAs, UUIDs are the product!), tighten patterns —
  identifier fidelity (`literal_fidelity` in `session stats`) must not
  regress below its current floor.
- **Claim earned:** "safe to commit to a shared repo" — the external
  onboarding gate (with G-4).

### E-7 · Track C spec spike  *(owner decision #4 — spec only)*
- **Failure addressed:** the deep-tech bet needs a concrete, criticizable
  design before any build decision.
- **Baseline:** spec v1.1 already carries ~80% of the certificate
  (fact_id, source_turn/session, verbatim, basis enum, status).
- **Target:** `docs/track-c-verifier-spec-draft.md`: certificate schema
  (adds source-span hash, extractor rule+version, canonicalization steps,
  literal/negation preservation checks), the verification algorithm, what
  it proves and explicitly what it does not, feasibility notes from
  running the idea mentally against the E-5 fuzz corpus. **No production
  code.**
- **Validation loop:** reviewer (Codex) critique on the board; the spec
  must answer "how does the verifier avoid trusting the extractor?"
- **Kill condition:** full build gated on E-4's result, per ratification.
- **Claim earned:** none — a design artifact.

---

## Gated — after evidence or before onboarding

| ID | Task | Gate | One-line contract |
|---|---|---|---|
| G-1 | Cross-platform determinism CI *(T5)* | capacity | Linux/macOS/Windows CI compare canonical ledger SHA-256 on shared fixtures + permuted transcripts; failure = ship-blocker |
| G-2 | Crash-safety fault injection *(T7)* | capacity | kill-during-checkpoint / concurrent hooks / disk-full / interrupted rename → never a partial hybrid ledger; replay idempotent |
| G-3 | Schema evolution fixtures *(T8)* | capacity | committed fixtures per released ledger/.ctx version stay readable; upgrades deterministic; no destructive auto-migration |
| G-4 | Onboarding hardening + `doctor` *(T14)* | before G-6 | fresh install → first checkpoint <10 min; idempotent re-install; clean uninstall; `ctxpack doctor` finds every broken integration |
| G-5 | Ops contract *(T15)* | with G-4 | supported versions, size limits, latency gates (5MB checkpoint p95 <2s; resume p95 <300ms), failure modes, recovery |
| G-6 | External pilot onboarding *(T12)* | **E-6 + G-4** | 2-week protocol, ≥50 sessions/≥10 compactions/≥100 decisions across ≥3 repo types; success = fallback <20%, ≥4/5 teams retain |
| G-7 | Independent replication *(T13)* | E-4 | non-author team reproduces the primary result within CI; <30 min setup; artifact published even if negative. Codex = replicator #0 |
| G-8 | Track C full build | **E-4 result** | certificates emitted at checkpoint + standalone LLM-free verifier; zero unsupported certified facts on the labelled corpus |

---

## Standing loops (all CI-or-manual — no daemons)

- **L-1 Claims gate** — `scripts/check_claims.py` on every PR (from W1-2).
  Fail: numeric/comparative claims without an artifact. Warn: qualitative.
- **L-2 Test loop** — scoped pytest per touched file during work; full
  suite (~35 min) before any release tag; negation-preservation +
  determinism gates are never skipped.
- **L-3 Fuzz regression** — every parser bug adds its minimized case to
  `tests/fuzz/`; the corpus only grows (from E-5).
- **L-4 Token-parity calibration** — estimator-vs-cl100k drift measured in
  the benchmark suite each time the corpus changes (from W1-3).
- **L-5 Cohort telemetry** — manual `ctxpack scorecard` sweep; next report
  ~2026-07-18 (adoption, fallback rate, identifier fidelity min/latest).
- **L-6 Coordination loop** — board read before work, handoff before stop;
  reviewer notes-only; decisions banked as `Decision:` lines with fact_ids
  linked on the board. Already operating.

## Explicitly not scheduled (per ratified do-not-do)

Dream-fold/consolidation (gated on telemetry), DAG Slice 2 (gated on real
`fact_superseded` edges), Tracks A/B/D-as-paper, vector DB, orchestration,
new memory types, dashboards, notation expansion without ablation — none
move until their gates clear. The no-feature-bloat constraint applies to
this plan itself: one active thread at a time.

---

## Amendment 2026-07-25 — trusted session resume (owner-ratified)

Triggered by two independent field reports (setu 2026-07-21, OntoWiz
2026-07-25) that converged: **the query tools went uncalled** (OntoWiz:
zero `ctx/session_*` calls in a full session) while the **SessionStart
injection is the surface those agents report benefiting from**, and a
hook plus a hand-maintained markdown file was estimated to reproduce
**~70%** of the value actually exercised.

Note the evidence classes, because the rest of this amendment depends on
not mixing them: the zero-call count is *observed*, the benefit is
*self-reported*, and delivery of an injected gist is neither — it proves
only that bytes were emitted. Nothing we can currently measure shows
that a model read or benefited from an injection.

**Product framing (replaces "agent memory" / "more recall tools"):**

> A flat file remembers. CTX explains what it remembers, how it knows
> it, what capture failed, and what may no longer be true.

### R-1 · Query-surface expansion FROZEN

No new MCP tools, DAG features, consolidation, salience learning or
generic recall work. Existing query tools remain as audit/debugging
escape hatches; they are no longer treated as the primary product. The
default five-tool surface (W1-4) stands.

### R-2 · Measurement slice — SHIPPED 2026-07-30

`fc2489f` (state algebra), `a815b78` (honest telemetry), `4ea08d4`
(H-4 oracle). This section carried "SHIPPED 2026-07-25" for five days
while nothing was committed; the correction stays on the record rather
than being tidied away, because a claim with no SHA behind it is exactly
the class of unverifiable assertion this workstream exists to eliminate.

Built before any roadmap argument, because it is needed either way:
sessions with explicit recall / zero explicit recall / missing read
telemetry / transcript fallback; startup injections
attempted-succeeded-empty-failed with injected size and hash; lint
armed-vs-silent comparison denominators; checkpoint receipts (turns
covered, turns new, ledger + gist sha256, lint status).

Rationale: `raw_fallback_rate` returned `None` both for "never queried"
and "no data", so **the exact phenomenon both field reports describe was
invisible to our own telemetry.** Honest self-reporting comes before
claiming that either push or pull usage works.

### R-3 · E-6 stays ahead of evidence anchoring

Storing commands, paths, output summaries and repository metadata
enlarges the privacy surface. Measurement and preregistration proceed
now; the `tool_observed` producer follows E-6. **Unchanged from the
original plan** — E-6 was already elevated.

### R-4 · Flat-file control before further spend

`PREREGISTRATION-flatfile-arm.md` (cross-referenced as A6): `ctx-push` /
`flatfile` / `grep`, four frozen handoffs, outcome **and maintenance
cost**, calibration-only. The flat file is maintained by an agent of the
same class under a fixed budget — a human-perfect file is an unfair
control.

### R-5 · Freshness derives from fact kind + producer, never literal presence

Corrected at ratification. "Contains a sha/path/version → perishable" is
unsafe: *"Never edit CLAUDE.md"* contains a path and is durable;
*"the reseal test is already red"* contains no literal and is
perishable. Two separate axes are maintained: **fact lifecycle**
and **evidence freshness**. The vocabulary is defined once in
`ctxpack/core/states.py` (`ctx-states/v1`) with property tests:
lifecycle is `draft / banked / superseded / retracted`, freshness is
`not_applicable / unanchored / not_checked / current / stale / invalid`,
and delivery (`attempted / injected / empty / failed`) is a third axis
that is never evidence of use.

This narrows the vocabulary ratified on 2026-07-25. `expired` leaves
lifecycle because evidence ageing is a freshness statement, not a
statement about a fact's standing; `prior_state` and
`needs_revalidation` leave freshness because the first describes what an
observation record *is* and the second collapses into `not_checked` or
`stale`. Both were the two-axis confusion surviving inside the fix for
it.

### R-6 · E-7 delivered; G-8 gate changed

E-7's deliverable is `docs/track-c-verified-freshness-spec.md` — an
owner-ratified design adopted with eight amendments, committed
2026-07-30 (it supersedes the planned `track-c-verifier-spec-draft.md`
filename). Its state vocabulary is not prose: it is
`ctxpack/core/states.py` (`fc2489f`), and where the spec and the enum
disagree the enum wins.

**G-8's gate changes from "E-4 result" to: (deterministic spike passes)
AND (flat-file calibration run) AND (four-arm H-4 result).** E-4 remains
required for CompactBench-class causal claims, which Track C does not
make. The post-E-6 build is narrowed to one vertical slice — the
pytest-only `tool_observed` producer — not a general invalidation
engine.

### Decision gate (binding)

Continue investing in session memory only if CTX shows **at least one**
differentiated advantage over the flat file, measured by the probe:
(1) fewer confident stale assertions; (2) better provenance; (3) lower
maintenance burden at similar continuity; (4) better recovery across
decision supersession. **If CTX only matches the flat file while costing
more to operate, narrow the product to a deterministic audit/checkpoint
utility and stop expanding memory features.**

The originally ratified fifth criterion — *independently verifiable
checkpoints* — is **removed from this gate**. It is already true before
the experiment runs (a flat file cannot emit a receipt at all), so
including it would let any result clear the gate and make the whole
decision unfalsifiable. It remains a real differentiator and is retained
as a claim for the narrower audit/checkpoint product; it just cannot
serve as evidence in a decision it can never fail.
