# CTX vNext Assessment — Current-State Grounding & Disposition (2026-08)

**Status:** Assessment ratified into the working plan 2026-08-22 (owner: Kapil Pant); implementation sequencing gated behind PF-11 preflight completion. **Amended same day: Amendment A2 (below) records the owner's ratification of the second-round items — CI floor, federation envelope, discovery lane, and the product name — closing the architecture discussion.**
**Responds to:** *CTX vNext — Cross-Repo Engineering Knowledge Compiler and Agentic Harness Control Plane* (external design proposal, 2026-08-22)
**Audience:** the vNext author, external reviewers (Codex), and future CTX sessions
**Companion docs:** `paper/agentic-context-plan-v1.md` (operating plan, amended A1), `paper/status-and-value-v0.5.md` (canonical numbers), `docs/preflight-threat-model-pf11.md` (threat model)

---

## Part 0 — Executive summary

The vNext proposal's diagnosis is right and its scope is wrong for this stage. Its
central claim — **state is not memory; a resume packet must be compiled from
current evidence, not copied from yesterday's narrative** — independently names
the top failure our own field telemetry recorded (the OntoWiz stale-fact
incident, §1.7). When an outside review of the public mirror and our own
incident log converge on the same missing mechanism, that mechanism is the work.

**Disposition: adopt two mechanisms, defer four, reject six** (full table in
§2.4):

- **Adopted:** (1) evidence-anchored resume with fact invalidation — which
  this repo has **already owner-ratified as Track C**
  (`docs/track-c-verified-freshness-spec.md`, 2026-07-30, eight amendments,
  implementation gated on E-6 + a deterministic value spike); the vNext
  proposal independently converges on it, so adoption here means *confirming
  Track C as the first post-preflight milestone*, not designing anything new;
  (2) failure-to-eval codification — mechanizing the review loop this repo
  already runs by hand.
- **Rejected for now:** org hub, cross-repo federation, `ctxd` daemon, model
  router, autonomous loop runner, dedicated graph database.

An important correction to the proposal's baseline: it reviewed a stale public
mirror (`cryogenic22/CTX.ai`). Its Phases 0–1 ("formalise the model",
"reliable resume in one repo") are roughly 70% already built, shipped, and
field-tested in this repo. Part 1 below is the grounded current-state picture
that any reviewer should advise against.

---

## Part 1 — What CTX is today (grounded baseline for reviewers)

*Everything in this part is shipped and tested unless explicitly marked
otherwise. File pointers are given so claims can be verified against the tree,
not taken on faith.*

### 1.1 Identity in one paragraph

CtxPack is a **deterministic knowledge packer with progressive hydration** that
has evolved into a **session-memory substrate for long-running coding agents**
("CtxPack Checkpoint": *compaction is a commit, not a loss event*). The core
property, and the deliberate differentiator against every incumbent memory
product (Mem0, Zep, Letta, LangMem, A-MEM, Cognee): **no LLM in the memory
write path**. Same transcript + same version ⇒ byte-identical ledger. Memory is
git-versionable, diffable in PR review, and carries provenance to the exact
turn that produced each fact.

### 1.2 The deterministic core (`ctxpack/core/`, zero runtime dependencies)

- Pack pipeline: discovery → parse → entity resolution → conflict detection →
  salience → compression → serialization, producing L0–L3 resolution layers.
- **Byte-determinism is CI-gated** (`tests/test_p0_trust_repairs.py`): no
  wall-clock outside `clock.as_of_date()`, no unsorted directory walks; pack
  twice ⇒ identical SHA-256.
- **Negation preservation is CI-gated** (`tests/test_negation_preservation.py`):
  no compression path may strip or reorder negations. (This gate exists because
  an early audit found prose compression turning "do not force-push" into
  "force-push" — the class of bug that disqualifies a memory layer, caught and
  permanently pinned before anything shipped.)
- Temporal supersession: newer-supersedes-older with the full chain recorded
  and auditable (`SUPERSEDED-<KEY>: 250@step-0 -> 500@step-2 -> 750@step-4`),
  never silently dropped. A supersession DAG + conflict lint surfaces
  unresolved decision collisions at the top of the next session's gist; a
  declared `Supersedes: <fact_id> — <reason>` resolves the row. Design goal:
  "never change decisions silently", not "never change decisions".
- Progressive hydration: compact L3 index → route → hydrate sections on demand,
  over MCP (~19 `ctx_*` tools) and a CLI twin so any agent with a shell can use
  the ledger.

### 1.3 CtxPack Checkpoint — the session-memory substrate (`ctxpack/agent/`)

**Write path** (all deterministic, no network, no LLM):

- Claude Code hooks (PreCompact / SessionEnd / Stop-debounced / SessionStart)
  pack the live transcript into `.claude/ctx/session-<id>.ctx` + a ≤2K-BPE
  gist + append-only journals. Checkpoint latency ~150ms–2s on real
  transcripts; fail-open — a broken ledger never breaks a session.
- Transcript parsing is **structured-signal-first** (`transcript_parser.py`):
  tool events, file paths, user imperatives, and convention-marked lines
  (`Decision:` / `Constraint:` / `ctx-incident:`) extract deterministically;
  free-prose extraction was measured at ~0 recall on real transcripts and the
  answer was **convention, not an LLM extractor** — the extraction-ceiling
  lesson taken on day 1. The parser is fence-aware (CommonMark-correct fence
  tracking incl. 4+-backtick and tilde fences), quote/mention-guarded, and
  hardened against harness-injected blocks — each guard carries an adversarial
  regression test.
- Adapters exist for Codex transcripts (auto-detected) and a generic
  `--format-spec` path, both fail-loud with pre-write hollow guards.

**Read path** (`session_reader.py` + CLI/MCP twins): `session resume`
(one-call orientation), `decisions`, `timeline`, `recall` (index→hydrate),
`why` (provenance + supersession chain), `literals` (every verbatim id
banked), `graph` (directed entity traversal incl. reverse-dependency
`parents()`). Cross-session project gist rolls up decisions/constraints across
all prior sessions (deduped, budgeted, stakes-ordered).

**Dogfood:** this repo runs on its own ledger; a 6-repo cohort was onboarded
2026-07-04 (idempotent `ctxpack onboard`). Adoption telemetry (ledger-reads vs
raw-transcript-grep fallbacks) is computed deterministically from transcripts.

### 1.4 Trust, authority, and the security preflight

- **Four separated authority axes** (`ctxpack/core/factid.py`, states in
  `states.py`): source provenance / local intent marker / owner approval /
  tool evidence. Owner approval is deliberately **unsatisfiable in v1** — a
  local CLI ratification is explicitly "bookkeeping by an unauthenticated
  local actor, never owner approval". **`TOOL_OBSERVED` is reserved with no
  producer** — this is the slot the adopted vNext slice fills (§3.1).
- Orthogonal state typing already exists (`states.py`: `Lifecycle`,
  `Freshness`, `Delivery`) — the proposal's §2.7 "add claim_kind + lifecycle"
  is partially pre-built; the non-inference rule ("emitted ≠ delivered ≠ read
  ≠ helped") is executable, not commented.
- **PF-11 security preflight** (`docs/preflight-threat-model-pf11.md`): threat
  model TM-1..TM-16 with acceptance cases TC-1..TC-20, being closed one
  mechanism per commit under external review. Shipped so far: type-only
  redaction (`[REDACTED:<type>]`, no fingerprints) at an ingest choke point
  plus an egress scan, fail-closed on scanner crash; a 33-entry secret corpus
  tested at unit level *and* through a 4-position transcript matrix to both
  ledger and emission; strict-decode append-only journals where validation and
  encoding failures cannot partially append a row (interrupted filesystem
  writes can still truncate; the strict reader detects and degrades); stable
  error codes at every security-boundary journal and hook stderr — free
  exception text is structurally coerced, never trusted. All security posture
  is **advisory mode by declared policy** (surface/flag/audit/degrade — never
  "guarantee/prevent/block").

### 1.5 Telemetry and receipts (absent-vs-zero discipline throughout)

- `events.jsonl` is derived at checkpoint from a transcript fold ONLY, so it
  stays byte-replayable. **Live events are deliberately kept out of it**:
  injection receipts (`injections.jsonl`) are a separate append-only stream
  because folding a live event into the replayable log would make it
  unreproducible. This two-ledger separation is load-bearing for the adopted
  slice (§3.3).
- Injection receipts measure exactly `emitted_to_hook_stdout` — the receipt is
  written *after* the emission it attests to, receipts route on declared
  schema (never id-length heuristics), an absent receipt is reported
  UNMEASURED and never inferred as "no emission".
- `ctx-incident` convention: sessions record when the ledger visibly helps or
  fails (`saved / missed / stale / wrong / conflicting / native-better /
  user-corrected`) — failure rows are valued over flattering ones. This is the
  standing instrument for §6.

### 1.6 Operating discipline (how work happens in this repo)

- **Conservation gates** (`.claude/rules/conservation-gates.md`): separation of
  authorship (no editing the bar to pass — preregistrations amend only by
  commit *before* a scored run; eval results are immutable versioned files;
  approval comes from an external reviewer, never self-declared);
  deterministic lane vs paid lane never mixed; every guard ships a test that
  feeds a violation and requires rejection.
- **Review loop:** an external reviewer (Codex) issues findings; fixes land as
  mechanism-scoped commits; every fix-detecting test is **demonstrated red on
  the parent commit** and the red count recorded; reviewer notes follow a
  mandated format (*Finding / Required acceptance cases / Fix SHA / Status per
  case*) and **a finding is not fixed until every acceptance case links to a
  test**. Multi-agent coordination runs through `AGENT_COORDINATION.md` with
  append-only handoffs.
- Retracted metric claims are gated by script (`scripts/check_claims.py`);
  the canonical current numbers live in `paper/status-and-value-v0.5.md`.

### 1.7 Field evidence — what is actually measured

- **v0.5 canonical result:** hydrated fidelity 86.7% vs raw stuffing 83.3% at
  ~24× fewer tokens/query; ties embedding-RAG. (Two earlier headline claims
  were retracted and are never cited; the claims gate enforces this.)
- **Agentic NIAH (2026-07):** ctx decision/constraint recall .85/.70 vs a
  naive automem baseline .00/.00; probe re-run 1.00/.90 vs baseline .85/.70;
  literal fidelity 5/7 vs 1/7 on KP_SDLC.
- **CompactBench sentinel run:** native compaction decision-recall **0.0**;
  ctx 240/240; a grep-over-transcript null 207/240. Consequence, recorded and
  ratified: **recall breadth is not the differentiator — literal exactness,
  reliability, and adherence are.** This calibrates how much sophistication
  context *selection* deserves (see §2.2 on the proposal's scoring formula).
- **Resume-probe A5 (drift-fork, scored, immutable artifact):** 8/8 correct
  (p=0.0039, exact binomial against a 50% chance null), $0.5056. The
  deliberately over-powered grep null scored 7/8 — the CTX-vs-grep gap
  itself is not significant at n=8; the p-value tests CTX against chance,
  never against grep.
- **setu field report (2026-07-21):** identifier fidelity 1.0 across 61
  banked literals; validated the "orientation, not truth" framing; exposed a
  whole-session capture gap, fixed same-day (`ctxpack backfill`).
- **OntoWiz field report (2026-07-25) — the load-bearing negative result:**
  in the report window the read path went entirely unused (0 recall/why
  calls); the agent attributed ~70% of exercised value to the SessionStart
  push alone; and one **stale-fact incident**: the ledger banked "test X is
  red", the test was green at HEAD, and nothing invalidated the fact. The
  report's explicit asks were evidence anchoring (`TOOL_OBSERVED` has no
  producer), freshness typing, and a real invalidation loop. *(Correction on
  record: a later look at the OntoWiz ledger shows explicit-recall sessions
  after the report — "unused" is per-report, not permanent.)*

### 1.8 Known gaps, honestly stated

1. **No CI.** The deterministic lane runs when an agent runs it — the
   guarantee is ceiling (discipline), not floor (enforcement). No branch
   protection, no CODEOWNERS. Recorded as an owner-level floor item, not
   silently patched.
2. **No invalidation loop / no `TOOL_OBSERVED` producer** — the stale-fact
   failure class is open. The *design* for closing it exists and is
   owner-ratified (Track C, `docs/track-c-verified-freshness-spec.md`);
   implementation is gated on E-6 plus a deterministic value spike and has
   not started.
3. **Read path underused in the field** — push dominates; the raw-fallback
   rate is tracked as the negative-value signal.
4. **`IncrementalPacker` (`ctxpack/core/incremental.py`):** zero callers, an
   mtime fast-path that hides equal-timestamp content changes, and its timing
   test is the suite's known flake. Queued as an owner decision:
   harden-or-retire before anything wires into AMBIENT (recommendation in
   §3.4).
5. **Eval scale:** several suites have small n; noise-floor lessons are
   recorded (never publish without CIs); `ctx-incident` adoption outside this
   repo is 0 so far.
6. **SOURCE-ROLES occurrence lists grow linearly** — a scale test gates any
   live injection, and the raw list must never be emitted into prompt context
   (accepted reviewer constraint).

### 1.9 Program state as of 2026-08-22

- PF-11 preflight in progress under external review: P1 batch approved;
  TM-5/6/7+14 implemented (`31fc0ad..644731f` — schema-routed receipts, one
  trust-annotation path for every `why` scope, stable error codes), review
  pending. Then PF-15 → PF-16/16b → PF-17 (raw-corpus egress fixture) → E-6
  re-review.
- Deterministic lane at last handoff: 1783 passed / 35 skipped (non-slow);
  claims gate OK; capability registry OK.
- **Standing frozen:** Loops 5–6, live UserPromptSubmit hook, paid runs,
  parked-branch merges; eval artifacts immutable.

---

## Part 2 — Assessment of the vNext proposal

### 2.1 What it gets right

1. **"State is not memory" (§2.3, §7, §18.3, Scenario B).** The proposal's
   sharpest line — *"a resume packet is compiled, not copied; generated from
   current evidence at resume time"* — is a precise description of the OntoWiz
   stale-fact incident (§1.7). Independent convergence between an outside
   review and our own incident telemetry is the strongest adoption signal in
   the document.
2. **The failure-to-eval compiler (§11.5)** is a mechanization of the review
   loop this repo already runs manually: reviewer finding → red-on-parent
   test → invariant. The mandated acceptance-case note format ("a finding is
   not fixed until every acceptance case links to a test") *is* this compiler
   in social/manual form. Codifying proven practice is the cheapest kind of
   product work and the correct framing of the compounding moat.
3. **The adversarial rejections (§2, §30) restate this repo's doctrine** — no
   LLM scribe, deterministic outer loop around probabilistic inner work, no
   god-graph, evidence over confidence scores, no premature graph database.
   Alignment is high; the author read the (public) repo carefully.
4. Also correct: context budget not maximum (§9.2's *intent*); context packets
   must be inspectable (§9.3 — our injection receipts already implement the
   honest version); subscriptions are workbenches, APIs are for unattended
   runs (§13.4); "cost per safely merged task" over cost per token.

### 2.2 What it gets wrong, or is stage-inappropriate

1. **Scope.** Six products, a local daemon, and an org hub — proposed for a
   single-maintainer repo whose recorded structural floor is "no CI,
   discipline only" (§1.8.1). Cross-repo federation presumes an organization
   of repos and operators that does not exist yet; today's field surface is
   one owner and a handful of report repos.
2. **It underweights what our measurements say.** The CompactBench sentinel
   showed recall breadth is not the moat (grep null 207/240); literal
   exactness, reliability, and adherence are. The seven-coefficient
   `context_score` (§9.2) walks into the unmeasured-weights trap our eval
   lessons pin — the differentiator is determinism and auditability, not
   smarter ranking.
3. **It collapses ledgers this repo deliberately keeps separate.** §7 sketches
   one engineering event ledger. Here, `events.jsonl` is transcript-fold
   derived and byte-replayable; live receipts are a separate stream *by
   design* (§1.5). A general live-evidence ledger (CI results, tool events)
   is a third stream and must sit **beside** the replayable spine, never
   inside it (§3.3).
4. **Capture expansion is attack surface.** Every new producer the proposal
   adds (CI adapter, PostToolUse events, cross-repo publication) expands the
   redaction/egress surface currently being hardened one threat-mechanism at a
   time under PF-11. Its §22 is a generic checklist; this repo's discipline is
   threat-cases-per-boundary with can-fail tests. Net effect: vNext state
   capture is *sequenced behind* PF-15/16/17 — which the existing AMBIENT gate
   already requires.
5. **`ctxd` fails the proposal's own Neo4j test.** It rejects a graph DB as
   premature operational commitment (§16.3), then proposes a daemon with no
   demonstrated query pattern demanding one. Hooks already provide restart-safe,
   zero-install local authority.
6. **The loop runner and model router (§12, §13, §19) conflict with standing
   constraints** (Loops 5–6, live hooks, paid runs frozen) and adapters
   commoditize. Deferred without prejudice; not a current milestone.

### 2.3 Blind spots from the stale public baseline

The proposal reviewed `cryogenic22/CTX.ai` main. It therefore does not know
that: `ctx resume`/checkpoints/hooks/timeline/`why`/graph queries are shipped
and field-tested; injection receipts, the ratification journal, separated
authority axes, the conflict lint, and the PF-11 preflight exist; orthogonal
lifecycle/freshness typing already exists in `states.py`; and — most
importantly — **the evidence-verified-state mechanism it proposes as the
flagship phase is already an owner-ratified design here (Track C,
2026-07-30)**, complete with data contracts, a status fold, spike gates, and
kill conditions. Its Phase 0 ("formalise the model") and Phase 1 ("reliable
resume in one repo") are ~70% built or ratified. **The genuine delta of its
flagship phase is implementation priority, not design**: the resume packet is
currently transcript-derived narrative + literals; Track C's verification
overlay is what turns it into evidence-checked state.

### 2.4 Disposition table

| vNext proposal element | Disposition | Reason |
|---|---|---|
| Evidence-derived state; resume compiled from current evidence (§7, §18) | **ADOPT — via Track C** (§3.1) | Owner-ratified design already exists; vNext independently corroborates its priority; fills the reserved `TOOL_OBSERVED` axis; deterministic by construction |
| Failure-to-eval compiler (§11.5) | **ADOPT** (§3.2) | Mechanizes the review loop already run manually; the acceptance-case rule is already a banked constraint |
| "Compiling live engineering reality" framing (§3, §34) | **ADOPT (framing)** | Better one-line pitch than "session memory"; use in the paper |
| `claim_kind` + `lifecycle` typing (§2.7) | **PARTIAL** | `Lifecycle`/`Freshness`/`Delivery` already exist in `states.py`; extend, don't duplicate |
| Task spec / gate manifests + eval selection (§8.2, §11.2) | **DEFER** | Valuable, but only after the state slice proves out; needs the evidence substrate first |
| Trajectory objects with structured rationale (§8.3) | **DEFER** | `Decision:`/`Supersedes:` convention already captures the load-bearing subset deterministically; richer schema later if measurement demands it |
| CI adapter as evidence producer (§14.4) | **DEFER** | Correct idea; prerequisite is CI existing at all (recorded owner floor item) |
| Context packet inspectability (§9.3) | **DEFER (mostly built)** | Injection receipts + hydration telemetry cover the honest core; per-section "why selected" later |
| Org hub / cross-repo federation (§10, §15.2) | **REJECT for now** | Stage-inappropriate; no organization of repos to federate; large new egress surface |
| `ctxd` local daemon (§15.1) | **REJECT for now** | Fails the proposal's own prematurity test; hooks suffice |
| Model router (§13) | **REJECT for now** | Adapters commoditize; conflicts with frozen paid-run regime |
| Autonomous loop runner / auto-merge (§12, §19, §20) | **REJECT for now** | Frozen by standing constraint; "an autonomous runner built on weak state automates confusion faster" — the proposal's own §32 argument |
| Dedicated graph database | **REJECT** (proposal agrees) | No demonstrated query pattern |
| Seven-coefficient `context_score` (§9.2) | **REJECT** | Unmeasured-weights trap; contradicts the measured moat (§2.2.2) |
| One unified event ledger (§7) | **REJECT as stated** | Violates the two-ledger replayability rule (§3.3); build the live stream beside the fold |

---

## Part 3 — The adopted slice, specified

### 3.1 Evidence-anchored resume — adopt by executing Track C

The mechanism the vNext proposal reaches for already has an owner-ratified
design in this repo: **Track C — Verified Freshness and Evidence Contracts**
(`docs/track-c-verified-freshness-spec.md`; drafted 2026-07-25 from the
OntoWiz incident, ratified with eight amendments 2026-07-30; implementation
gated on E-6 plus a deterministic value spike; no production code authorized
by the spec alone). Adoption therefore means **confirming Track C as the
first post-preflight milestone** — not designing anything new. Its ratified
shape, for reviewers who have only seen the vNext document:

- **Two axes, never conflated:** fact lifecycle (`draft` / `banked` /
  `superseded` / `retracted`) vs evidence freshness (six states from
  `ctx-states/v1`). A fact can be `banked` and `not_checked` at once —
  collapsing the axes into one status "is how a memory system starts lying."
- **Freshness anchors to content, never to git refs** (file digests, config
  values, output digests; the commit is receipt metadata). `git-ref/v1` was
  explicitly *removed* as an anchor (amendment A-3): HEAD changes on every
  commit, so ref-anchored facts would all go stale immediately — blowing the
  ≤2% false-stale gate and training users to ignore warnings. *(Note: the
  vNext proposal's §6.3 `valid_from_commit` anchoring repeats exactly this
  rejected design.)*
- **The spike vertical is the motivating incident:** `pytest-result/v1` —
  bank a test execution under the existing `tool_observed` basis and, next
  session, render *"Historical observation: test_reseal failed at revision A.
  Current state requires revalidation."* — never *"test_reseal is failing."*
  It fails safe by construction: a historical event can never render as
  current.
- **Agents see three states** (VERIFIED / STALE / UNVERIFIED) in the gist;
  the six-state precision lives in `why`, receipts, and CI output. Absence of
  evidence never renders as verification.
- **The system never rewrites a fact.** It marks the claim stale, shows why,
  and lets the agent explicitly supersede it — the same "never change
  silently" rule decisions already follow.
- **Build gate (amendment A-8):** offline three-adapter spike
  (`pytest-result/v1`, `toml-key/v1`, `json-pointer/v1`) AND flat-file
  calibration AND the four-arm H-4 result.

What vNext adds mechanically on top of Track C: **nothing** — but it
independently corroborates the track's priority from an outside vantage
(incident log → ratified design → external proposal all naming one
mechanism), and its failure Scenarios A ("agent says done, tests never
ran"), B ("summary says tests passed yesterday, main changed"), and H
("graph becomes stale") are additional acceptance framings the spike can
cite. Everything remains advisory (PF-11 B6): a stale flag surfaces and
demotes; it never claims to *prevent* an agent acting on stale data.

### 3.2 Failure-to-eval codification

`ReviewFinding` becomes a first-class ledger object linking finding →
red-on-parent test → (optionally) promoted invariant, with a lint that
refuses to mark a finding fixed while any acceptance case lacks a linked
test. The rule already exists socially (banked board constraint); this makes
it structural. The promotion path follows the existing conservative ladder —
observation → candidate → evidence-supported → explicitly adopted — and the
Dream pipeline never silently manufactures policy (the proposal's §17.4
agrees with the shipped design).

### 3.3 Design constraint: the two-ledger rule (already ratified as Track C A-5)

The vNext state plane, as adopted, is a **live evidence-receipt stream beside
the replayable transcript fold, never merged into `events.jsonl`**. This is
not new doctrine — Track C amendment A-5 ratifies it verbatim: verification
receipts follow the same rule as the injection log — observational, never an
input to packing, never folded into the replayable event stream. It is
restated here because the vNext proposal's §7 single-ledger sketch would
violate it. Byte-replayability of the deterministic spine is non-negotiable;
any design that folds live events into the replayable log is rejected at
review regardless of convenience.

### 3.4 `IncrementalPacker` disposition (queued owner decision — recommendation)

**Recommend retire, not harden.** Its mtime fast-path — equal timestamps
hiding content changes — is precisely the evidence-freshness bug Track C
exists to eliminate, and Track C's A-3 already ratifies the correct
primitive: **anchor freshness to content, never to timestamps or refs**.
Hardening a zero-caller module whose core shortcut contradicts a ratified
invariant is negative work; per-file SHA machinery already exists in the
code packer. (Decision remains with the owner as queued by the reviewer.)

---

## Part 4 — Sequencing against the current program

1. **Now:** finish the PF-11 preflight (TM-5..7 review in flight → PF-15 →
   PF-16/16b → PF-17 → E-6 re-review). No state-capture expansion lands
   before it: new evidence producers are new redaction/egress surface, and the
   AMBIENT gate already requires the preflight.
2. **Resolve the `IncrementalPacker` owner decision** (§3.4) — it removes the
   one module whose shortcut contradicts Track C's ratified freshness
   primitive.
3. **Milestone: execute Track C** (§3.1) per its own ratified delivery
   sequence and build gate — offline three-adapter spike, flat-file
   calibration, four-arm H-4 — with threat cases first (verification receipts
   are a new write surface; the journal-integrity and stable-error-code
   patterns from TM-3/TM-7 presumptively apply verbatim).
   Mechanism-per-commit, red-on-parent, external review — the same protocol as
   the preflight.
4. **Then: failure-to-eval codification** (§3.2).
5. **Reassess** gate manifests / eval selection (§2.4 deferred rows) against
   the measurements in §6 — not before.

Standing frozen throughout, unchanged: Loops 5–6, live UserPromptSubmit hook,
paid runs, parked-branch merges; eval artifacts immutable.

---

## Part 5 — Non-goals (recorded so they don't creep)

For the current planning horizon CTX will **not** build: a central org hub;
cross-repo federation/publication; a local daemon; a model router; an
autonomous loop runner or auto-merge policy engine; a dedicated graph
database; source-control/CI/test-framework replacements (the proposal's §25
list is endorsed as-is). Any of these re-enters only through a new owner-level
decision with its own review, not by accretion.

---

## Part 6 — How we'll know (measurement)

The instrument already exists: **`ctx-incident` telemetry**. The state slice
succeeds if, in dogfood + cohort use:

- `stale` incidents go to ~zero (the OntoWiz failure class);
- `saved` rows begin citing the `STATE` block / invalidation flags;
- no regression in checkpoint latency or determinism gates (byte-identity
  re-verified with probes active).

Secondary, from existing telemetry: raw-fallback rate does not rise;
resume-probe evals gain a "stale-fact probe" class (a banked fact whose
anchor diverged — the correct answer is "stale", not the banked value).

Measurement note (external-review amendment, 2026-08-22): freshness
reporting must be **two-sided** — the false-stale rate (Track C's ≤2%
budget) is reported together with stale-detection recall ("when evidence
really changed, did the fold notice?") and anchor coverage (share of
eligible facts carrying anchors at all). A checker that never fires aces
the false-stale budget while being useless; the detection side is the one
that matters. Absence of evidence never renders as verified (Track C A-6,
unchanged).
The proposal's north-star metric (*human interventions per safely merged,
policy-compliant change*) is recorded as aspirational — correct at scale,
unmeasurable at current n; we do not publish against it.

---

## Part 7 — Questions for reviewers

*(Invalidation semantics and the probe/adapter surface are NOT open
questions — Track C's ratified amendments answer them: never rewrite, mark
stale and show why; content anchors only; three-adapter spike set. Reviewers
should challenge those answers via a Track C amendment if warranted, not
re-litigate them here.)*

1. **Delta check:** does the vNext proposal contain anything that should
   become a Track C amendment — e.g. its resume-time state recompilation
   (Scenario B) as an explicit spike acceptance case — or is the ratified
   spec already strictly stronger on every overlapping point? (Our reading:
   strictly stronger; vNext's §6.3 `valid_from_commit` anchoring is the
   design A-3 already rejected.)
2. **Threat cases:** which TM/TC rows do verification receipts need before
   spike code? (A new append-only write surface — the journal-integrity and
   stable-error-code patterns from TM-3/TM-7 presumptively apply verbatim;
   confirm scope.)
3. **`IncrementalPacker`:** any objection to retire-over-harden (§3.4)?
4. **Failure-to-eval schema:** is `ReviewFinding` → test link → optional
   invariant promotion the minimal correct shape, or is there a smaller first
   increment?
5. **Sequencing:** any reason Track C should not be the first post-preflight
   milestone, given three independent sources (incident log, ratified design,
   external proposal) converge on it?

---

## Amendment A2 (2026-08-22) — owner ratification, second round

After the external architect's adversarial review of the plain-English brief
(three blocking issues, all applied) and this repo's counter-rulings, the
owner ratified the full second-round slate on 2026-08-22. The architecture
discussion is closed on the following terms.

### A2.1 CI floor — RATIFIED (prerequisite gate)

A minimal deterministic CI floor — the non-slow suite plus the determinism,
negation, and claims gates running on every push — is a **precondition for
unfreezing any autonomous-loop work**. Principle, now a standing constraint:
*agents are never the authority on whether their own work passed.*

Interface contract ratified with it: **`ctx verify --json`** emits a
machine-readable gate manifest (which gates ran, against what commit, with
what result). CI consumes it today; any future orchestrator consumes the
identical contract. This is autonomy-readiness without putting orchestration
inside CTX. Implementation is its own unit through normal review — ratified,
not yet built; no time estimate is recorded (reviewer amendment: the
principle is load-bearing, the estimate was not).

### A2.2 Federation envelope — RATIFIED (standing constraint, not a protocol)

Every persistent artifact carries a minimal envelope: `repo_id`,
`artifact_type`, `schema_version`, `producer_version`, `content_hash`,
`namespace`, `provenance`, `export_classification`. Much of this is already
repo practice via per-artifact schema declarations; the delta is codifying
the full header and the export field.

Explicitly bounded: the envelope is **not** a federation protocol — no
cross-repo exchange format is designed until a first real consumer exists.
`export_classification` is an egress boundary: it lands only through
threat-tested review (PF-line discipline) and **everything defaults to
repo-private**.

### A2.3 Discovery lane — RATIFIED (contingent design option)

An LLM may *propose* candidate knowledge (possible decisions, constraints,
failed approaches) only into a quarantined candidate namespace — never
rendered as fact in any gist — with promotion solely via evidence, an
explicit agent marker, or ratification. Activation is telemetry-gated: it
waits for `ctx-incident: missed` rows attributable to the extraction
ceiling, plus a precision-barred extraction eval, before any live use.
Headline property sharpened and ratified with it: **"no LLM in the
authoritative write path."**

### A2.4 Name — RATIFIED: "engineering continuity substrate"

"Control" is excluded from the name while the PF-11 B6 advisory posture
stands: on the reviewer's own architecture, control lives in the external
CI/orchestrator box, and CTX's claims remain surface/flag/audit/degrade.
The reviewer's formulation is otherwise adopted verbatim: CTX *preserves
intent and decisions, verifies mutable claims against current evidence,
turns discovered failures into executable learning, and serves a
machine-readable view of project reality to any agent or future
orchestrator; probabilistic models may reason over or propose additions to
that reality — they do not silently define it.* Thesis line: **engineering
reality that survives agents, sessions, models, and time.** Boundary
paragraph adopted with it: *CTX is not the future scheduler; it is the
authority the scheduler consults, and the orchestrator must not redefine
CTX's truth or its evaluation rules.*

### A2.5 Second-round refinements ratified as part of this amendment

- **Two-sided freshness reporting** (Part 6 measurement note): false-stale
  budget + stale-detection recall + anchor coverage, always together;
  absence never renders as verified.
- **Two-tier failure-to-eval:** every finding gets a local regression
  witness; only repeated or architecturally significant failure classes are
  promoted to standing cross-cutting gates, with flake rate, redundancy, and
  runtime tracked — the gate library must stay an asset, not a landfill.
- **Three-ledger vocabulary** (transcript / knowledge / evidence) adopted as
  the *logical target model* — two stores exist today; the evidence ledger
  ships with Track C; the stores are never merged.
- **Recall claim rewording:** recall is necessary but insufficient; the
  differentiator is reliable recall of the right *current* state with
  literal fidelity, provenance, and adherence.
- **IncrementalPacker:** disposition phrased as "retire the implementation,
  not the idea" — content-addressed incremental recomputation remains the
  future primitive (owner decision on the module itself still queued as per
  §3.4).
- **Claim hygiene:** "no LLM can directly mutate authoritative memory" and
  "captured by the capture contract" replace absolute phrasings; ledger is
  described as git-versionable/PR-diffable (committing is a choice); the A5
  p-value is attached to its actual hypothesis (§1.7); the ~24× figure
  stays scoped to the v0.5 synthetic-corpus evaluation.

### A2.6 Unchanged by this amendment

PF-11 preflight completion still gates all new capture surface; Track C
keeps its own build gate (E-6 + three-adapter spike + calibration + H-4)
and its kill conditions; the Part 5 non-goals stand (org hub, cross-repo
federation implementation, ctxd daemon, model router, autonomous loop
runner/auto-merge, graph database, multi-coefficient context scoring);
Loops 5–6, live hooks, paid runs, and parked merges remain frozen.
