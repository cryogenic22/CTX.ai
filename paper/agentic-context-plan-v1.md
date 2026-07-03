# CTX for Long-Running Agents — Deep Analysis & Evolution Plan (v1)

**Date:** 2026-07-03 · **Status:** Working plan · **Scope:** codebase audit, eval-strategy audit, market/research landscape, pivot design, 90-day roadmap

---

## TL;DR

The direction is real, documented, and **unowned**: as of July 2026 there is no standard benchmark measuring whether a coding agent still knows what it decided 2M tokens ago, and no incumbent memory system (Mem0, Zep, Letta, LangMem, A-MEM, Cognee) ships a *deterministic, git-versioned, provenance-to-turn* memory substrate. Every one of them puts an LLM in the memory-write path — nondeterministic, unauditable, subject to ACE-documented "context collapse." CtxPack's zero-LLM pack loop is structurally immune to that failure, and ~60% of the needed parts already exist in the repo as unwired modules.

**But** the current eval cannot support a "prevents context rot" claim (single-shot QA, one self-authored corpus, n=30, ±13pp noise floor, embedding-RAG already ties hydration in our own results), and the agent path has verified bugs that must be fixed before anything ships — including a **negation-stripping bug that turns "do not force-push" into "force-push"**.

The winning form is **CtxPack Checkpoint**: a pack-on-compact decision/constraint ledger for Claude Code ("compaction is a commit, not a loss event"), paired with **CompactBench** — the category-defining public benchmark for decision recall across compaction cycles. New benchmark code shipped with this plan (agentic NIAH + GraphWalks-adapted) provides the first empirical data; results below.

---

## Part 1 — Where CTX stands today

### 1.1 What is genuinely strong

- **Deterministic, zero-dependency pack pipeline** (discovery → parse → entity-resolution → conflict-detection → provenance → compression → L3): no LLM in the loop, replayable, auditable. Nobody else has this property in the memory space.
- **Progressive hydration** (L3 directory index → LLM-as-router → section hydration via MCP) is architecturally identical to what Anthropic now prescribes ("just-in-time retrieval over lightweight identifiers", "progressive disclosure") and what RLM/Cloudflare/ACE converge on: context lives *outside* the window; the window holds a working set.
- **Current honest headline** (v0.5): hydrated fidelity **86.7% beats raw stuffing 83.3%** on Opus at ~24x fewer tokens/query; ties embedding-RAG. (Old 26x/93% claims are retracted; MEMORY.md must be purged of them.)
- **Trust scaffolding already designed**: ContextLayer (RULES/INFERRED/ELICITED/AMBIENT), confidence, observation_count, expires_at on IR and AST; ConfidenceTracker with decay/prune; telemetry JSONL (CP-040/041); ContextGuard; dream/consolidation pipeline; code packer with BM25 task scoring + PageRank centrality and per-file SHA incremental repack.
- **AgentSession prototype exists** (`ctxpack/agent/session.py`): rolling step-merge → entity resolution → conflict detection → budget-triggered eviction. Orphaned (no MCP/CLI surface, no persistence) but it proves the loop.
- **Eval discipline exists in places**: cross-model judging, retry/backoff, 7 CI-gated metric-sanity tests, 565 tests total.

### 1.2 Verified defects (found/confirmed in this audit)

| # | Defect | Evidence | Severity |
|---|--------|----------|----------|
| 1 | **Negation inversion**: `no`/`not` are in `_FILLER_WORDS` — `_compress_prose("Do not force-push to main")` → `"force-push main"` | `md_parser.py:227,246`; reproduced 2026-07-03 | **Disqualifying** for a memory layer; 1-line fix + regression test |
| 2 | **No temporal supersession**: a config revised 250→500→750 packs as three duplicate `BACKOFF-BASE-MS` keys, `conflicts=0`; changed decisions accumulate, never supersede | reproduced via `AgentSession` 2026-07-03 | Fatal for agent memory until fixed |
| 3 | **Provenance step-index bug**: `AgentSession.update()` parses each step as a single-item list → every source is `SRC:step-0`; temporal order lost | `session.py:70` + `state_parser.py:41`; reproduced | High |
| 4 | Per-tool-name entity collapse: 50 bash calls merge into one `TOOL-BASH` entity — causality destroyed | `state_parser.py:100-121` | High |
| 5 | **Whitespace "tokens" throughout the agent path** (`compressor.count_tokens`, session budget=4000 "tokens", L3 500-"token" budget) — the exact mistake MEMORY.md lists as a critical lesson; real BPE (`core/code/tokens.py`, pinned tiktoken) exists but is unwired | `compressor.py:569-611` | High |
| 6 | **Determinism is currently broken**: `datetime.date.today()` in every header; unsorted `os.walk` order → same corpus does not repack byte-identically | `compressor.py:133`, `l3_generator.py:69`, `manifest.py:83` | Embarrassing for a "deterministic" pitch; 1-day fix + CI SHA-256 gate |
| 7 | Judge tuple-truthiness bug in legacy eval modules reports 100% judge fidelity unconditionally | `definitive_eval.py:342`, `hydration_eval.py:186/197`, module `scaling_eval.py:228` | Invalidates any result produced by those paths |
| 8 | `len//4` pseudo-BPE for all Claude/Gemini runs (`cost.py:78`); corpus size varies 92,482 vs 85,223 across experiments purely from counting method | `cost.py` | Undermines every cost claim |
| 9 | Format/runtime schism: layer/confidence/expires_at have **no surface syntax** — a disk round-trip destroys all trust state | serializer/parser | Blocks the trust model entirely |
| 10 | Eviction is destructive (pop-and-forget, no L3 stub, no spill-to-disk) and O(n²); `expires_at` never enforced; ⊥ conflict operator spec'd but dead | `session.py:105-140` | High |
| 11 | Results files mutable/overwritten (scaling_eval.json silently replaced; whitepaper 87/80 vs current 86.7/83.3 contradiction survives only in `prior_run`) | benchmarks/results/ | Credibility |
| 12 | Doc rot: MEMORY.md + rough_notes + reviewer_article still assert retracted 26x/93%/4.7x numbers | multiple | Credibility |
| 13 | **HTTP 529 (Anthropic "overloaded") missing from `_TRANSIENT_CODES`** — treated as permanent, answer scores INCORRECT silently; same class as the v0.4 "429 scored as INCORRECT" lesson | `fidelity.py:30`; observed live during the 2026-07-03 benchmark run | High — add 529 (+ 408, 522, 524) and flag error-rows in aggregation |

### 1.3 Eval credibility debt (why "prevents context rot" is currently unsupportable)

1. **Wrong phenomenon**: context rot is longitudinal (degradation as tokens accumulate across turns/compactions). Every existing CTX eval is single-shot QA over a static corpus. Nothing measures facts that arrive, mutate, and get superseded over time. *(The new agentic-NIAH suite in this plan is the first step to fixing this.)*
2. **Noise floor**: n=30 questions, single run, no seeds/CIs — a 3.4pp gap has a ±13-18pp binomial CI; the headline even flipped sign between runs (87/80 → 83.3/86.7).
3. **Strong baselines missing**: embedding-RAG already *ties* hydration (86.7 = 86.7) in our own canonical file. BM25 top-k, grep-over-files (Letta's null hypothesis: 74% on LoCoMo with 4 filesystem tools, beating Mem0), compaction-summary, closed-book (contamination floor), and oracle-sections (ceiling) have never been run.
4. **Parametric contamination unmeasured**: the FDA eval scored judge=1.0 from a 159-token pack with zero extracted entities — the model answered from weights. No closed-book control exists for any corpus.
5. **Judge validity**: binary CORRECT/INCORRECT with a 10-token budget against 4-6-fact expected answers; no partial credit, no judge-agreement study.

---

## Part 2 — The landscape (mid-2026 evidence base)

### 2.1 Context rot is real, quantified, and worsening with scale

- **MRCR v2 (8-needle)**: even frontier models lose 20-25pp from 4K→256K and 40-65pp to 1M (Opus 4.6: 93.0% @256K → 76.0% @1M; GPT-5.4: 97.3% → 36.6%). Effective context ≈ 60-70% of nominal.
- **GraphWalks**: BFS <128K is near-solved (GPT-5.2: 0.94) but collapses to ~40% at 1M for the best models — the hardest published long-context reasoning task.
- **NoLiMa**: remove lexical overlap and 10 of 12 models drop to ≤50% of baseline by *just 32K*. Reasoning doesn't fix it (o3: 100→58.5 at 32K).
- **Chroma "Context Rot"**: even one distractor measurably hurts; focused ~300-token prompts beat full ~113K histories for *every* model family; coherent text degrades worse than shuffled.
- **Wang & Sun (ICML 2025)**: proactive interference — retrieval of the *latest* value degrades log-linearly with the number of prior updates. This is the agent-memory failure mode (decisions get revised constantly), and it's the one our update-chain probes target.

### 2.2 Compaction — the actual mechanism long agent sessions live or die by — is lossy and unmeasured

- **ConstraintRot (arXiv 2606.22528)**: policy violations 0% while constraints visible → **30% avg (up to 59%) after compaction**. The published fix, "Constraint Pinning" (isolate durable rules from lossy compression), *is literally a deterministic .ctx RULES layer*.
- **ACE (ICLR 2026)**: iterative LLM rewriting of accumulated context collapsed 18,282 tokens → 122 tokens at step 60; accuracy fell *below* the no-memory baseline. Summary-based memory can make agents worse than nothing.
- **RLM (Zhang/Kraska/Khattab)**: "compaction presumes that details early in the prompt can safely be forgotten." Summary Agent: 0.1% F1 on OOLONG-Pairs vs RLM 58.0%. Their answer: never summarize destructively; keep context externally addressable, pull slices on demand.
- **Factory.ai measurement**: LLM summarization retains 3.70/5 information per compaction cycle; after 3-4 cycles critical information is permanently gone. 200+ comments across Claude Code GitHub issues (#7530, #18866, #13112) document lost decisions, file paths, hypothesis chains.
- **Anthropic's own answer is external files**, not better compaction: memory tool (+39% quality, −84% tokens on their 100-turn eval), CLAUDE.md re-injection, structured note-taking, initializer-agent artifacts.

### 2.3 The white space nobody owns

1. Every major memory product is **chat-memory shaped** (preferences, personal facts, dialogue QA on LoCoMo/LongMemEval — now saturated at 92%+ and shown non-predictive of agentic performance by MemoryArena).
2. Every one puts an **LLM in the memory-write path** → nondeterministic, unauditable, un-reviewable, silently corruptible (MemTrace exists because memory errors can't be attributed).
3. **Nobody versions memory with the repo.** No "memory at commit X", no branch-scoped memory, no memory diffs in PR review. Claude Code auto-memory is machine-local; Mem0/Zep live in SaaS DBs divorced from git.
4. **No leaderboard-grade benchmark measures decision/constraint retention across compaction.** ConstraintRot (June 2026, single-author), SlipCodeBench, AMA-Bench (SOTA only 57.2%), Slipstream's "sufficiency" criterion — each invented a private harness. The scoreboard is unclaimed.
5. Research agents already vote with their feet: Kosmos (structured world model, 200 rollouts), Sakana AI Scientist-v2 (experiment journal), Google Co-Scientist (tournament ledger) — every serious long-horizon system externalizes state into a *structured, persistent store*. None relies on compaction. None of these stores is standardized, deterministic, or reusable.

### 2.4 Convergent design principles (RLM + ACE + Anthropic + Cloudflare)

1. Context as external variable — the window holds a working set, not the corpus.
2. Programmatic access beats both stuffing and embedding retrieval (grep/slice/filter with code; code-shaped interfaces are in-distribution).
3. Progressive disclosure from a compact index (CTX's L3 *is* this).
4. Destructive summarization is the enemy; the raw source of truth must survive.
5. **Delta updates, not rewrites** — with the merge done by deterministic non-LLM logic (ACE's exact design; CTX's natural home turf).
6. Small models + good harness beat big models raw (RLM(GPT-5-mini) > GPT-5; 4B RLM hits 100% MRCRv2).

**CTX's position in one sentence:** the mid-2026 literature independently converged on CTX's architecture — external store, tiny index, on-demand hydration, deterministic delta merge — but nobody shipped the *substrate*. ACE has the update discipline but no format, no provenance, no tooling. RLM has the read pattern but no store. CTX is the format ACE lacks and the variable RLM points at.

---

## Part 3 — The thesis: CtxPack Checkpoint

> **"Compaction is a commit, not a loss event."** — pack-on-compact session memory for long-running agents. **"Memory you can code-review."**

### 3.1 What it is

A deterministic, replayable **decision-and-constraint ledger** for coding/research agents, delivered through surfaces that exist today (Claude Code hooks + MCP), producing a git-committable artifact:

- **PreCompact hook** → `ctxpack checkpoint`: before the summarizer runs, deterministically pack everything since the last checkpoint from the session transcript (JSONL) into `.claude/ctx/session-<id>.ctx` + an append-only journal. The raw transcript is never deleted (it is L0).
- **SessionStart hook** (matchers: compact/resume/startup) → inject a ≤2K-BPE session gist: DECISIONS / CONSTRAINTS / OPEN-QUESTIONS / FAILED-APPROACHES / TIMELINE + one line advertising `ctx/session_recall`. This is Constraint Pinning, implemented deterministically.
- **MCP session tools** (read path): `ctx/session_recall` (progressive hydration over the session pack), `ctx/session_timeline` (ordered ops — the ordinal recall models pay attention-tax for), `ctx/session_decisions` (every live decision in one call), `ctx/why` (provenance chain: "you believe pool_size=25 because turn 141 superseded turn 87").
- **Git-committed** (optional): branch-scoped, diffable-in-PR, cross-machine memory. "Project memory at commit X."

### 3.2 Why it's defensible (the one-liner per competitor)

| Competitor | What they have | What they can't claim |
|---|---|---|
| MemGPT/Letta | LLM self-edits memory blocks | deterministic writes; repo-versioned |
| Mem0 / Zep / A-MEM / Cognee | LLM extraction/graph in write path | same-session→same-memory; auditability; PR-reviewable diffs |
| ACE | right update discipline (deltas, non-LLM merge) | no interchange format, no provenance, no tooling |
| RLM | right read pattern (context as variable) | no substrate — .ctx is the variable |
| Anthropic native (memory tool, auto-memory, compaction) | zero-install, in-distribution | git-versioned/cross-machine/cross-vendor; deterministic; provenance-to-turn; they own the *harness*, not your *repo* |

The three properties the platform vendor structurally won't ship: (1) **deterministic writes** (no LLM scribe — immune to context collapse by construction), (2) **versioned with the repo**, (3) **provenance to the turn**.

### 3.3 The scientific-research-agent story

Same substrate, different template: Kosmos-style world model as a .ctx pack — HYPOTHESES (with supersession as evidence accumulates), EXPERIMENTS (params + outcomes + provenance to notebook/run IDs), FINDINGS (with confidence + conflict detection between contradictory results), OPEN-QUESTIONS. Multi-week projects get "lab-notebook memory you can cite": every claim traces to the run that produced it. The conflict-detection + supersession machinery is *more* valuable here than in coding (contradictory experimental results are the norm). This is a v2 template on the same engine, not a separate product.

---

## Part 4 — Engineering plan (novel, grounded, sequenced)

### P0 — Trust repairs (week 1; all are small, all are load-bearing)

1. Remove `no`/`not`/`never` from `_FILLER_WORDS`; add a negation-preservation regression test (count negations pre/post compression; any loss fails CI).
2. Byte-determinism: content-hash-derived or `--as-of` header dates; sorted `os.walk`; CI gate "pack twice on two platforms → identical SHA-256."
3. Wire real BPE (`core/code/tokens.py`, pinned tiktoken) into compressor/budget/L3/session behind a tokenizer parameter; fix `cost.py` len//4 fallback for Claude via the tokenizer mapping.
4. Fix the judge tuple-truthiness bug (or quarantine `definitive_eval.py`/`hydration_eval.py`/module `scaling_eval.py`); CI test asserting judge fields are bool.
5. Fix `AgentSession` step-index provenance (pass running step offset to `parse_steps`).
6. Results immutability: `results/v0.6.0/<run-id>.json` with git SHA + config hash; never overwrite.
7. Purge retracted numbers (26x/93%/7pp-wrong-direction) from MEMORY.md, rough_notes, reviewer_article.

### P1 — Temporal semantics + format v1.1 (weeks 2-4)

- `IRSource` gains turn provenance + timestamp: `SRC:session:{id}#turn{n}`.
- **Newer-supersedes-older** rule in conflict.py for same-entity/same-key facts: a changed decision is a *state update* (old value tombstoned, auditable), not a permanent warning. Repurpose the dead `⊥` operator as structured supersession (`fact ⊥supersedes:id`).
- Spec v1.1 (additive, uses the unknown-header-field forward-compat rule): per-fact trailing trust annotations (layer/confidence/observed-at/expires), stable content-hash fact IDs, tombstones.
- **`.ctx.jrnl` append-only journal**: JSONL ops `{op: ASSERT|SUPERSEDE|RETRACT|EXPIRE, fact_id, path, value, turn, ts}`; the .ctx snapshot is the deterministic compaction of the journal. This is ACE's grow-and-refine with a non-LLM merge — and full replay.
- Enforce `expires_at` at hydrate time (AMBIENT facts).
- Eviction → demotion: evicted entities collapse to a one-line L3 stub ("EVICTED: 12 facts about X, hydrate session-pack#L88") and spill to disk.

### P2 — Transcript ingestion (weeks 3-5) — **the go/no-go**

`ctxpack/agent/transcript_parser.py`: parse Claude Code session JSONL → IR. Extract from **structured signals first** (this is the determinism-preserving hedge): tool_use/tool_result blocks (per-invocation identity `TOOL-BASH#0047`), TodoWrite items, plan-mode output, user messages (constraints — *never* prose-compressed), Edit/Write file paths, git commits. Assistant free-prose decision extraction is a second pass with explicit precision/recall measurement.

**GATE (week 4-5): extraction-recall audit.** Hand-label decisions/constraints/supersessions/failed-approaches in 10 real transcripts (~15-30 each). Deterministic parser must reach **≥80% recall on decisions/constraints**. 60-80% → restrict scope to structured-signal-only extraction and re-test. <60% → the zero-LLM thesis fails on real data; pivot (see kill criteria).

### P3 — Checkpoint engine + hooks (weeks 5-7)

- `ctxpack checkpoint --transcript <path> --out .claude/ctx/` — incremental (wire the orphaned `IncrementalPacker`, implement the missing IR-merge; budget <5s, zero network, zero LLM).
- `ctxpack install-hooks` — writes PreCompact / SessionStart / SessionEnd entries into `.claude/settings.json`. Uninstall = delete three entries. No behavior changes until compaction fires.
- Dogfood on CTX_mod development itself from day 45.

### P4 — Read path + telemetry (weeks 7-9)

- Four session MCP tools (contracts in §3.1) on the existing 12-tool server.
- Hydrate-time layer/confidence/expiry filtering (plumbing exists).
- Telemetry: checkpoint latency, `session_recall` calls, **raw-transcript-fallback rate** (the agent grepping the transcript despite having recall tools — the negative-value signal CP-041 was designed to catch).
- First real `dream consolidate` pass over dogfood telemetry.

---

## Part 5 — Eval strategy overhaul

### 5.1 New in this commit: two adapted public-benchmark suites (first data)

**A. Agentic NIAH / context-rot curve** (`run_agentic_niah.py`, `ctxpack/benchmarks/agentic/trajectory_gen.py`)
Deterministic synthetic coding-agent trajectories (payments-platform session; realistic tool-output filler) at 8K/32K/64K BPE with a fixed 12-question set: 5 static needles at controlled depths, **4 updated-value chains (Wang & Sun proactive-interference probes — value revised 3-4×, question asks the FINAL value)**, 1 cross-session aggregation, 2 NOT_IN_CONTEXT adversarials. Four conditions: RAW (stuffing), COMPACT (question-agnostic LLM summary ≈ auto-compaction), BM25 (top episodes, ~3.5K budget), CTX (steps → IR → entity-resolution → compress → index → route → hydrate). Cross-model judge (GPT-4o judges Sonnet answers).

**Results (2026-07-03, claude-sonnet-4-6 answerer, GPT-4o judge):**

| Length | RAW judge / BPE | COMPACT judge / BPE | BM25 judge / BPE | CTX judge / BPE |
|---|---|---|---|---|
| 8K | 100% / 8,376 | 100% / 775 | 91.7% / 740 | 100% / **403** |
| 32K | 100% / 33,400 | 100% / 960 | 91.7% / 817 | 100% / **405** |
| 64K | 100% / 66,377 | 100% / 861 | 91.7% / 835 | 91.7%† / **382** |

† The single CTX miss at 64K was an untreated **HTTP 529 killing the routing call** (defect #13), not a routing failure — and the GPT-4o judge then scored the model's explicit "not found" abstention as CORRECT against expected "4", a live demonstration of the binary-judge validity problem (we report the corrected number).

**What this run actually shows (read it honestly):**

1. **Fidelity does not differentiate at ≤64K** for a Sonnet-class answerer on a 12-probe set — every condition saturates, including one-shot compaction. This is consistent with the public curves (MRCR degradation bites beyond 128-256K) and **empirically confirms the critics: single-shot QA at practical scales cannot demonstrate "rot prevention." The differentiating eval must be K-cycle compaction (DR@K), 128K+ scale, or higher interference density.**
2. **Cost is the real curve**: CTX holds flat ~400 BPE per query regardless of session length — 166x less context than raw stuffing at 64K, and still 2.2x less than answering from a compaction summary (which itself costs a full-context summarization pass per cycle). RAW grows linearly with the session; CTX does not.
3. **Aggregation is where retrieval structurally fails**: BM25 missed the cross-session aggregation question (M1: "which configs were revised ≥3 times?") at *every* length — budget-bounded top-k recovered only 2 of 4 chains. CTX answers it from one ~860-BPE hydration because entity resolution has already gathered all revisions of each config into a single section. This mirrors the RULER CWE/FWE analysis: whole-corpus aggregation is the one job top-k retrieval cannot do and pack-time structure can.
4. **Abstention is nearly free in CTX**: the router returns NONE on adversarial questions and the model abstains correctly from the 151-BPE index alone.
5. **Supersession gap confirmed at scale**: 562 sections, 4 update chains, `conflicts=0`. The update-chain questions still passed because field order + `as_of_revision` markers let the answerer infer recency — but that is luck, not architecture (defect #2).
6. One-shot COMPACT did *not* lose the needles here — a temp-0 summarizer over ≤66K input preserves 12 salient facts. The documented compaction losses (Factory.ai 3.70/5 per cycle; ConstraintRot 0→30-59%) come from *repeated, question-agnostic* cycles at higher density — exactly what CompactBench must force (K=1..5 cycles), and single-shot summaries cannot reveal.

**B. GraphWalks-adapted** (`run_graphwalks_eval.py`, `graph_gen.py`)
Service-dependency catalogs (40/120 nodes, edges embedded in runbook prose with distractor mentions), exact set-F1 (no judge): forward deps, reverse deps ("parents"), BFS-2. Conditions: RAW stuffing; CTX-L3 (directed dependency index recovered from the packed doc, ~20-40x smaller); CTX-TOOL (deterministic traversal over packed edges — the "graph query becomes O(V+E) instead of model inference" claim, and a packing-fidelity check: any lost edge shows up as F1<1).

**Results (2026-07-03, claude-sonnet-4-6, exact set-F1):**

| Scale | Condition | macro-F1 | forward | reverse | bfs-2 | context BPE |
|---|---|---|---|---|---|---|
| 40 nodes (11.4K BPE) | RAW | 0.908 | 1.00 | 0.775 | 0.951 | 11,386 |
| | CTX-L3 | 0.947 | 1.00 | **1.00** | 0.840 | **594** (19.2x smaller) |
| | CTX-TOOL | **1.000** | 1.00 | 1.00 | 1.00 | 594 |
| 120 nodes (34.1K BPE) | RAW | 0.904 | 1.00 | 0.822 | 0.889 | 34,057 |
| | CTX-L3 | 0.916 | 1.00 | 0.857 | 0.892 | **1,671** (20.4x smaller) |
| | CTX-TOOL | **1.000** | 1.00 | 1.00 | 1.00 | 1,671 |

Packing preserved **100% of edges at both scales** (`edge_faithful: True` — generator edges == packed-doc edges).

**What this run shows:**

1. **Reverse-dependency ("parents") questions are where in-context reasoning breaks first** — RAW drops to 0.78-0.82 even at 11-34K BPE, because answering "who depends on X" requires a global backward scan over prose. The compact directed index fixes it at small scale (CTX-L3 = 1.00 @ 40 nodes) but model limits reappear as the index grows (0.857 @ 120) — consistent with the public GraphWalks finding that *any* in-context representation eventually hits the model's reasoning ceiling.
2. **The deterministic tool path is the only condition immune to scale**: exact answers at every size, zero answer-model tokens spent on traversal. This is the RLM "programmatic access" argument landed empirically: don't ask the model to walk graphs in-context — expose a deterministic traversal over packed structure.
3. **Actionable gap**: `EntityGraph` exists in core but is *not exposed as an MCP tool*. Ship `ctx/graph_query {entity, op: neighbors|parents|bfs|path, depth}` — it converts the hardest published long-context task class into an O(V+E) lookup, and the eval above is its proof. (Also: upgrade EntityGraph to directed edges — direction is currently only recoverable from `DEPENDS-ON` values, not the graph API.)

**Honesty notes (publish these):** CTX condition assumes structured event capture at the harness boundary (the integration contract — exactly what the PreCompact hook provides); needle events carry the same information in transcript and step form; `EntityGraph` is undirected (upgrade to directed is on the roadmap — the directed index in this eval is recovered from packed `DEPENDS-ON` values).

### 5.2 Immediate controls (run before any public claim)

1. **Closed-book contamination control** (half a day): all 30 enterprise questions + FDA/Twilio with *no context*. Headline fidelity becomes packed-minus-closed-book. Pass: closed-book ≤15%.
2. **Statistical rescue** (~$150): 200 generator-minted questions, arms = closed-book / raw / BM25 / embedding-RAG / CTX / oracle-sections, 3 seeds, fact-level rubric judge (2 judge models), bootstrap CIs, McNemar pairs. Decision rule: if CI on (CTX − BM25) includes 0, drop fidelity-superiority claims permanently and reposition on determinism/provenance/cost.
3. **Full-loop cost audit**: count routing turn + re-hydration + outputs + judge; restate the multiplier honestly (likely 10-15x, still strong, field-standard accounting).

### 5.3 CompactBench — the category benchmark (weeks 8-11)

Seeded generator mints realistic sessions with N=40 planted decisions/constraints/supersessions; drive **real Claude Code** with `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` lowered to force K=1..5 compaction cycles; probe recall + **adherence** (does the agent violate a pre-compaction constraint when given the opportunity — ConstraintRot's design) after each cycle.

- **Headline metric: DR@K — decision recall at K compactions** (survival curve). Deterministic exact-fact grading for the headline; rubric judge secondary. n≥5 seeds, binomial CIs.
- **Mandatory arms**: native compaction · +CLAUDE.md notes · **+grep-over-raw-transcript (the null hypothesis — if CTX doesn't beat this on recall OR tokens, kill or reposition)** · +LLM-summary memory (Mem0-style) · +CtxPack hooks · full-history oracle.
- Anchors from literature: compaction-only ≈ 60-70% retention after 3-4 cycles; constraint violations 0%→30-59%. Target: CTX arm ≥90% DR@5, violations restored to ≈0%.
- **Publish the harness regardless of result.** Whoever defines this scoreboard owns the category conversation.

### 5.4 Public-benchmark adaptations (external validity)

- **LongMemEval_S** (~1 week): pack session histories → route+hydrate vs full-context vs oracle-retrieval. Reports the five published sub-scores; *knowledge-updates* and *abstention* are the two CTX architecturally claims.
- **LongBench v2** (drop-in MCQ accuracy — the most credible single public number; RAG baselines already in the paper).
- **NoLiMa-adapted routing stress test**: zero-lexical-overlap needles defeat BM25 and vanilla embeddings *by construction* — if L3-routing + entity resolution surfaces them, that's the honest differentiator vs cheap retrieval; if not, the entity layer is decorative. High-information either way.
- **SWE Context Bench** (stretch): head-to-head vs published Mem0/LangMem/Supermemory numbers (leader: 30.3% resolution). Its core finding — 217-token curated summaries beat 25.6K raw trajectories — is CTX's thesis stated by a neutral third party.
- **Explicitly refuse** to claim wins on RULER-NIAH / MRCR (any indexed store trivially saturates them; claiming them reads as benchmark abuse — say so in the paper; pre-empting the accusation is itself credibility).

### 5.5 Rigor upgrades (standing policy)

Pre-register analysis plans in-repo before running; publish raw per-question JSONL for every headline run; fact-level rubric judging with judge-agreement (κ) reporting; seeded generators over hand-authored questions; immutable versioned results.

---

## Part 6 — 90-day roadmap

| Days | Work | Gate |
|---|---|---|
| 1-14 | P0 trust repairs; transcript_parser MVP; closed-book control; full-loop cost audit | All P0 CI gates green |
| 15-30 | Temporal semantics + spec v1.1 + journal; extraction-recall audit on 10 real transcripts | **≥80% decision/constraint recall or pivot extractor scope** |
| 31-45 | Checkpoint engine; `install-hooks`; begin dogfooding on CTX_mod | Checkpoint <5s; byte-determinism CI |
| 46-60 | Session MCP tools; expiry/layer filtering; telemetry; statistical-rescue eval run | (CTX−BM25) CI excludes 0, else reposition claims |
| 61-75 | CompactBench build + runs (5 arms × 5 seeds); NoLiMa-adapted test | DR@5 ≥90% vs native ~60-70%; **beat grep arm on recall OR tokens** |
| 76-90 | LongMemEval_S + LongBench v2 numbers; dogfood telemetry report; whitepaper v4 ("Compaction is a commit, not a loss"); v0.6 release | External-benchmark table complete |

---

## Part 7 — Risks & kill criteria

1. **Extraction ceiling** (the one objection engineering can't route around): if deterministic extraction recall on real transcripts is <60% for decisions/constraints, the zero-LLM thesis fails on this content type. *Hedge*: structured-signal-only extraction (TodoWrite, plan output, user messages, commits, tool args). *Kill*: if even that misses the load-bearing facts, adding an LLM extractor makes this Mem0-with-a-weirder-format — stop.
2. **The grep null hypothesis**: Claude Code keeps the full transcript on disk and the agent has Grep/Read. If CTX doesn't beat grep-over-transcript by ≥10pp recall at ≤50% tokens (and beat compaction-only by ≥20pp), the format adds nothing over a file-retention convention. Run this arm in *every* eval, preemptively.
3. **Platform subsumption**: Anthropic iterates monthly on compaction/memory and has published the prescription ("compaction should preserve architectural decisions"). The survivable slice is what they structurally won't ship: git-versioned, cross-vendor, deterministic, provenance-to-turn. If users don't value those properties, execution doesn't matter — the dogfood telemetry fortnight (spontaneous `session_recall` use, raw-fallback rate) is the earliest honest signal.
4. **Model-consumption gap**: our own pharma report concedes LLMs can't reliably consume raw .ctx notation — hence prose-default hydration everywhere; keep full sections greppable as plain prose files (in-distribution guaranteed path; MCP is the fast path).
5. **Credibility debt compounds**: publishing context-rot claims on the current evidence invites a takedown that a solo Apache-2.0 project cannot survive. Sequence: fix → measure → pre-register → publish.

---

## Build log

**2026-07-03 — P0–P3 built, tested, and dogfooding live on this repo.**

- **P0 trust repairs** ✅ — negation words out of the filler list (+ CI guard); `as_of`/`CTXPACK_AS_OF` deterministic dates via `clock.py`; sorted `os.walk`; HTTP 529/408/522/524 now transient; legacy judge tuple bugs fixed in all three modules; `parse_steps(start_index=)` provenance fix; `cost.py` uses cl100k for Claude counts (real BPE, labeled approximation).
- **P1 temporal supersession** ✅ — `resolve_entities(supersede_by_recency=True)`: latest value wins, full chain recorded as `SUPERSEDED-<KEY>: 250@step-0 -> 500@step-2 -> 750@step-4`, history absorbed (never stacks) across re-resolves; `IRSource.turn`/`timestamp` (`session:{id}#turn{n}`); hydrator `drop_expired_as_of`. AgentSession supersedes by default.
- **P2 transcript parser** ✅ with an honest gate result: on this repo's real session transcript (633 turns), **structured-signal extraction is excellent** (9/9 tasks, 33 files, 7 errors, 3/3 requests, all with turn provenance) and the pasted-content guard eliminated all 13 constraint false-positives from quoted material — but **free-prose decision recall was 0/N on this session's writing style**. Consequence (per the plan's hedge): decisions are now a *structured* signal — CLAUDE.md instructs sessions to state `Decision: ...` lines, which extract deterministically. This is the extraction-ceiling lesson landing on day 1, answered by convention rather than an LLM extractor.
- **P3 checkpoint engine + hooks** ✅ — `ctxpack checkpoint` (full deterministic re-pack, <2s on a 2.5MB transcript; two runs → **identical SHA-256**), ≤2K-BPE prose gist with stakes-ordered trimming, append-only `checkpoints.jsonl`, `ctxpack hook pre-compact|session-start|session-end` (fail-open: a broken ledger never breaks the session; `/clear` respected; ledger dir anchored to the hook's project cwd), `ctxpack install-hooks` (merge-preserving). **Installed in this repo**: `.claude/settings.json` + `CLAUDE.md` conventions; first real checkpoint packed this very session (130+ entities from 633 turns; gist 1,736 BPE).
- Tests: 1236 passed / 0 failed mid-build; +38 new tests across 5 new test files (negation, determinism, supersession, transcript parser, checkpoint).

**2026-07-03 (later) — dogfood day 1 + P4 read path shipped.**

- **First end-to-end hook injection verified live**: SessionStart delivered the previous session's gist after a Claude Code restart. Root cause of the initial silence: *hooks installed mid-session don't fire until the Claude Code process restarts* (hook config is snapshotted at startup; `/clear` does not reload it) — `install-hooks` must warn about this.
- **`Decision:` convention validated on real usage**: 2/2 properly-formatted decisions extracted with turn provenance. Dogfood also surfaced 5 false positives in one day, all fixed same-day with regression tests: unanchored markers firing on backticked *mentions* and list-introducer lines ending in "verdict:"; noun-phrase "root cause" firing without an assertion; `<task-notification>` harness blocks extracted as user requests. Use-vs-mention guard (backtick-stripped matching) now applies to all extractors.
- **P4 read path** ✅ — `ctxpack/agent/session_reader.py` + five MCP tools on the server (now 17): `ctx/session_recall` (index → hydrate, the L3 routing pattern over session memory), `ctx/session_timeline` (turn-ordered, kind-filterable), `ctx/session_decisions` (stakes trio in one call), `ctx/why` (provenance + SUPERSEDED chain surfacing), `ctx/graph_query` (deterministic traversal; **EntityGraph upgraded to directed edges** — `parents()` answers the reverse-dependency query the GraphWalks eval showed RAW fails at). CLI twin `ctxpack session <recall|timeline|decisions|why|graph>` so any agent with a shell can use the ledger; `.mcp.json` registered; CLAUDE.md now instructs sessions to use the read path before grepping the transcript (the raw-fallback rate is the telemetry signal). `session_recall` logs through the existing TelemetryLog.

**2026-07-03 (evening) — onboarding kit + adoption telemetry.**

- **`ctxpack onboard`** — one idempotent command wires a repo end-to-end: hooks (merge-preserving), `.mcp.json` server entry, marker-guarded CLAUDE.md conventions block (Decision: convention + read-path-first instruction), ledger dir. Team doc: `docs/session-memory-onboarding.md` (setup, usage, measurement protocol, troubleshooting).
- **Adoption telemetry is now automatic and deterministic**: the transcript parser counts `ledger_reads` (CLI/MCP read-path calls) vs `transcript_greps` (raw-transcript fallbacks, excluding checkpoint writes) per session; checkpoint journal gains `gist_bpe` + `latency_ms`. `ctxpack session stats` aggregates the journal (last checkpoint per session wins) into the benefits report — the **raw-fallback rate** is the headline value signal, computed from the transcript itself with zero extra plumbing.
- **First real baseline (this repo, day 1)**: 5 ledger reads vs 3 transcript greps (the greps predate the read path — this morning's hook diagnosis), fallback rate 0.375; checkpoint latency 142ms on a 1.2K-turn transcript; gist 1,029 BPE.

Remaining from the 90-day sequence: spec v1.1 trust annotations + op-level journal, CompactBench, and the two-week dogfood telemetry report.

## Appendix A — Benchmark methodology notes (this commit)

- Generators are fully deterministic (seeded); needle set fixed across lengths so curves are comparable; filler uses payments-domain vocabulary to create real interference; distractor numbers never contradict gold values for their exact keys.
- CTX condition uses the real pipeline: `parse_steps → resolve_entities → detect_conflicts → compress → list_sections → LLM routes (JSON array) → hydrate_by_name → answer`, with one `needs_rehydration`-triggered re-route. Token accounting includes index + routing context + hydrated sections.
- COMPACT condition: one question-agnostic summary per trajectory length (≤1500 tokens, temp 0) — mirrors auto-compaction's question-blindness; generated once and reused across questions, as real compaction is.
- BM25: Okapi (k1=1.5, b=0.75) over episodes, ~3.5K-BPE budget, chronological re-ordering — parity with CTX's typical hydration budget.
- Judge: GPT-4o cross-model (answers by claude-sonnet-4-6), same protocol as v0.4/0.5 evals; rule grader secondary.
