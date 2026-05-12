---
title: Code Packer v0 — RFC (rev 3)
author: Kapil Pant
date: 2026-05-12
status: Revised after second-pass review (rev 3) — week 1 cleared to start
audience: CTX maintainers, integrators evaluating CTX for coding agents
length: design doc, not a status report
changes_in_rev_3:
  - Added §8.0 oracle-set recall gate as pre-ship blocker
  - §6.2 ranker: rank-normalise both scores before combining; widen α sweep
  - §8.4 trust-label eval: adversarial cases + swapped-label control condition
  - Split eval slate (§10): ship §8.0-8.3 at week 6; §8.4-8.5 as v0.1 milestone +2 weeks
  - Added §7.4 ctx/raw_file escape hatch and §7.5 pack manifest footer
  - Added §8.6 determinism CI and §8.7 SWE-bench-as-CI
  - Added §10.5 post-ship safety net: shadow mode, A/B, telemetry signals
  - Added "Lost in the Middle" (Liu et al. 2023) to §3 prior work
  - §2: "don't defend regressions by over-serving" guiding principle
  - §9: flagged invalidation has same imprecision as static call graph
changes_in_rev_2:
  - Split ranking into persistent centrality_prior + per-turn task_score
  - Languages narrowed to Python (incl. FastAPI), React TSX
  - Added trust-label behavioural eval (§8.4) and retrieval-hard suite (§8.5)
  - SWE-bench Verified demoted to ceiling check, not primary differentiator
  - callers/callees renamed callers_static/callees_static symmetrically
  - Bidirectional invalidation rule clarified
  - Generated-file exclusion added
  - Karpathy reference cut as rhetorical
  - Framing reset around category difference, not token efficiency
---

# Code Packer v0 — Active, Token-Optimal Code Context for Coding Agents

> Companion to the domain packer described in `ctxpack-whitepaper-v3.md`.
> Same IR, same hydrator, same MCP surface. Different producer.

**Legend.** 📚 cites prior work · 🧪 proposed algorithm to test · ✅ already
shipped in CTX · ⚙️ to build · ⚠️ caveat / non-goal.

---

## 1. Problem

Coding agents on large TSX + Python codebases blow their context window
on three things, in roughly this order:

1. **Specs, plans, tasks, RFCs** — long-form prose the agent re-reads
   each session.
2. **Code the agent doesn't actually need this turn** — sibling files
   pulled in by directory walks, full class bodies when one method
   matters, vendored libraries.
3. **The same things, repeatedly** — every new session re-builds the
   same mental model from scratch.

The domain packer (v0.5.0) already solves (1) cleanly: prose with named
entities packs at 24× per-query cost vs. raw stuffing on the v3 eval.

Code is different. It has structure the prose packer doesn't model: a
function has a signature, a body, callers, callees, and tests. A class
is a container of methods. Imports form a graph. None of this survives
the entity/section abstraction without a code-aware producer.

**Goal of this RFC**: define that producer.

---

## 2. Non-goals (scope discipline)

⚠️ The packer does **not**:

- Lint, type-check, or test the code it serves. Those are `tsc`,
  `eslint`, `mypy`, `pytest`'s jobs. Mixing them produces a god-tool.
- Suggest edits or refactors. It serves bytes; the agent decides what
  to change.
- Reason about correctness across edits. Regression protection is
  git + the test suite, not the packer.
- Index third-party deps by default. They are typically read-once and
  bloat the catalog. Opt-in flag if a team wants them.

The one near-quality concern that *does* belong here is **symbol
hallucination guarding** — extending the existing `ContextGuard` to
flag agent output referencing symbols not in the served pack. That is
already a CTX capability; the extension is mechanical.

### Guiding principle

🧪 **Don't defend regressions by making the packer more conservative.**
The path of least resistance, when an agent fails on a task the packer
hid context from, is to lower thresholds, deepen hydration, and serve
bigger catalogs "just in case." That path ends at "raw stuffing with
extra steps" — and the thesis (§3) dies with it. Regression protection
comes from **gates** (§8.0), **escape hatches** (§7.4), and
**visibility into what was excluded** (§7.5 pack manifest). Not from
defensive over-serving.

---

## 3. Prior work we're standing on

📚 **Aider repo-map** (Paul Gauthier, 2023–present). Builds a
tree-sitter symbol graph, ranks symbols by PageRank against the
agent's recent edits, and serves a budgeted summary. The single best
production-tested artifact in this space. We borrow the PageRank
ranking idea (§6.2).

📚 **Agentless** (Princeton, Xia et al., 2024). Showed pure
retrieval+repair beats agentic browsing on SWE-bench Verified. The
implication for us: getting the *right* code to the agent in one shot
is more valuable than letting it explore. Justifies investing in the
L3 catalog (§5).

📚 **RepoCoder** (Zhang et al., EMNLP 2023). Iterative retrieval —
draft → retrieve → redraft — outperforms single-shot retrieval on
repo-level completion. Suggests `hydrate_symbol` should be re-callable
mid-turn (§7).

📚 **LongCoder** (Guo et al., ICML 2023). Bridge tokens that summarize
distant code regions outperform sliding-window attention. Validates
hierarchical summarization at the catalog level (signature + 1-line
purpose) rather than full bodies (§5).

📚 **Sourcegraph SCIP** (Source Code Intelligence Protocol, 2023).
Standard cross-language symbol index format. We don't need to invent
the index shape; we can emit SCIP-compatible artifacts so existing
tooling reads them.

📚 **HyDE for code** (Hypothetical Document Embeddings, Gao et al.,
ACL 2023, adapted). Ask the LLM to imagine what the answer code would
look like, then retrieve against the hypothetical. Tensions with our
deterministic posture (§4); noted as a v1+ consideration only (§7.3).

📚 **Wang & Sun, "Unable to Forget: Proactive Interference"** (ICML
2025 Workshop). Already cited in the whitepaper; reinforces that
*less* relevant context beats *more*. Strengthens the case for
budget-aware serving.

📚 **Liu et al., "Lost in the Middle"** (TACL 2024). LLM attention
to context degrades sharply in the middle of long inputs — recall is
strongest at the start and end, weakest in the middle. Direct
implication for the packer: serving "more context" doesn't linearly
help; it can actively hurt by pushing the *useful* context into the
attention-dead zone. This is the second-strongest argument (alongside
Wang & Sun) for ruthless catalogs over big ones, and a reason §10.5's
shadow mode shouldn't measure "is more context safer?" as a default —
it often isn't.

📚 **Microsoft CodePlan** (Bairi et al., 2024). Plans repo-scale edits
as a task graph. Out of scope here (planning ≠ packing), but worth
noting as a future consumer of our pack.

### The category gap, stated plainly

🧪 The thesis of this RFC is **not** "we beat Aider by a constant
factor on tokens." That's evidence, not a position. The position is:

> Code retrieval and prose retrieval, through **one IR**, with **one
> trust model**, **deterministically packed**, **incrementally
> cached**, and **served over MCP**.

No public artifact today combines (i) layer-aware trust labelling
(RULES / INFERRED / ELICITED / AMBIENT), (ii) content-addressed
deterministic packing, (iii) SHA-based incremental change detection,
and (iv) MCP-native delivery, for **both** prose and code through the
same producer-agnostic hydrator. Each piece exists somewhere; the
combination is the contribution.

The token-efficiency numbers in §8.1 are how we *demonstrate* the
gap. The trust-label eval in §8.4 is how we *prove* the layer
typing earns its keep. If §8.4 comes back null, the trust model is
decorative and should be removed — that's part of why it ships in v0.

---

## 4. Scope of v0

✅ Already in CTX (reusable):

- `IREntity` / `IRField` / `Provenance` typing (layers, confidence,
  observation_count, expires_at).
- Hydrator, grounding sandwich, ContextGuard, telemetry.
- `IncrementalPacker` (SHA-256 + mtime change detection — Phase 3b).
- MCP server with 5 tools.
- ConfidenceTracker for observe/decay/prune.

⚙️ To build for v0 — scope locked:

- Tree-sitter front ends for **Python** (incl. FastAPI patterns:
  route decorators, `Depends(...)`, pydantic models as first-class
  entities) and **React TSX** (function components, hooks, exported
  utilities).
- Symbol → `IREntity` mapping.
- L3 **symbol catalog** distinct from the prose L3.
- Two-score ranking: persistent `centrality_prior` + per-turn
  `task_score` (§6.2).
- MCP tools `list_symbols`, `hydrate_symbol`, `search_symbols`.
- Generated-file exclusion (`.ctxpackignore` + `.gitignore` honoured
  + heuristic for declaration files, protobuf, Prisma client, build
  outputs).
- Eval harness covering §8.1–§8.5.

🧪 Deferred to v1:

- Additional languages (Go, Rust, Java, plain JS).
- Call-graph-aware hydration (depth ≥ 2).
- Cross-repo packing.
- HyDE retrieval — only if v0 baseline plateaus *and* we accept the
  determinism tradeoff (LLM in the retrieve path).

---

## 5. IR shape — one symbol, one entity

```
IREntity(
  name="src/foo.py::Foo.bar",                     # stable, file::dotted
  layer=ContextLayer.RULES,                       # source-of-truth code
  confidence=1.0,                                 # checked in, deterministic
  observation_count=0,                            # bumped by dream pipeline
  sources=[IRSource(file="src/foo.py",
                    line_start=42, line_end=87)],
  fields=[
    IRField(key="kind",            value="method"),
    IRField(key="signature",       value="def bar(self, x: int) -> str:"),
    IRField(key="docstring",       value="..."),
    IRField(key="body",            value="<full source>"),
    IRField(key="callers_static",  value="[src/baz.py::run, ...]"),
    IRField(key="callees_static",  value="[src/foo.py::Foo._helper, ...]"),
    IRField(key="imports",         value="[json, .helpers]"),
    IRField(key="tests",           value="[tests/test_foo.py::test_bar]"),
    IRField(key="centrality_prior",value="0.0731"),  # PageRank, persisted
  ]
)
```

The `_static` suffix on callers/callees is load-bearing: Python's
dynamic dispatch (getattr, decorators, MRO, kwargs forwarding) makes
any static call graph best-effort. Naming sets the expectation for
both the agent reading the field and the integrator reading the doc.

**Catalog row** = `name + kind + signature + docstring-first-line`.

⚠️ Per-symbol catalog size target is a **soft cap** of ~120 BPE, with
truncation rules: TypeScript generic-heavy signatures
(`type Foo<T extends Bar<U>, U = Baz<V>>`) and Python long type
unions blow past 120 routinely. Rule: if the signature exceeds the
cap, truncate the signature mid-generic and append `…` — the body
hydration recovers the full version when the agent needs it.

⚠️ The 50K-LOC ⇒ ~360K-BPE projection from rev 1 was a back-of-envelope
estimate; the real distribution depends on repo shape (a few fat
modules vs. many tiny ones). We measure it on the two eval repos in
week 4 and revisit the per-module hydration design if catalogs fail
to fit a 10K BPE budget.

**Why store body separately**: it's the hydration target. The catalog
serves intent; the body serves implementation. Most agent turns need
catalog + 1–3 bodies, not the whole directory.

**FastAPI specifics**: route decorators (`@app.get("/foo")`,
`@router.post(...)`) become entity-level metadata fields
(`http_method`, `http_path`), not just decorator strings. `Depends`
parameters become structured `dependencies` fields. Pydantic
`BaseModel` subclasses are first-class entities even when they're
nested in a router module — they're the API contract.

**TSX specifics**: function components and forwardRef components are
entities; their hooks (`useState`, `useEffect`, `useMemo`) are
listed as a `hooks` field for cheap "what does this component
depend on" queries.

---

## 6. Producer pipeline

```
.py / .tsx files
     │
     ▼
[1] tree-sitter parse  ──────────────►  AST per file
     │
     ▼
[2] symbol extractor   ──────────────►  list[Symbol]
     │                                  (functions, classes, methods,
     │                                   exported consts/types in TSX)
     ▼
[3] call-graph builder ──────────────►  edges (caller, callee)
     │                                  (best-effort static; not perfect)
     ▼
[4] importance ranker  ──────────────►  score per symbol
     │                                  (PageRank on call graph)
     ▼
[5] IREntity emitter   ──────────────►  one IREntity per symbol
     │
     ▼
[6] catalog packer     ──────────────►  per-module L3 catalog files
     │
     ▼
[7] IncrementalPacker  ──────────────►  cache state for next run
```

Steps 1–5 are deterministic, no LLM. Step 6 reuses the existing
compressor. Step 7 is already shipped.

### 6.1 Tree-sitter notes

📚 tree-sitter-python and tree-sitter-typescript (with the `.tsx`
scanner) are MIT-licensed, fast (~ms per file), and produce stable
AST node types we can pattern-match on. No regex-based parsing.

### 6.2 Importance ranking — two scores, not one

The first revision of this RFC baked PageRank into the entity as
`relevance_prior`. That's cache-friendly but task-blind: a utility
called everywhere sits at the top of every catalog regardless of
what the agent is doing this turn. Aider sidesteps this by
recomputing rank per turn against recent edits — useful, but it
gives up the persistence we want.

🧪 v0 carries **two** scores, combined at retrieve time:

- **`centrality_prior` (persisted on entity).** Weighted PageRank
  over the static call graph, computed at pack time.
  - Symbol = node.
  - Call edge (caller → callee), weight 1.
  - Test reference (test → tested symbol), weight 3 — tests are
    stronger evidence of importance than ordinary calls.
  - Export pin: exported symbols get a damping bonus because their
    influence leaks across module boundaries.
  - For FastAPI: a route handler being referenced from `app.include_router`
    counts as an export pin. For TSX: components used in `<App>` or
    the router are export-pinned.

- **`task_score` (per-turn, computed at retrieve time).** A cheap
  relevance signal against the agent's current working set:
  - Recent message-history tokens (last N agent turns, default 4K BPE).
  - File paths the agent has already hydrated this turn.
  - Symbol names the agent has already mentioned.
  - Implementation: BM25 over (symbol name + signature +
    docstring-first-line) against the working-set text. Sub-ms per
    catalog of a few thousand symbols.

**Critical normalisation step before combining.** BM25 and PageRank
live on different scales with different tail shapes — BM25 spikes on
rare-keyword hits, PageRank is bounded and roughly log-normal.
Linearly combining raw scores means α isn't actually "70% task /
30% centrality"; it's whatever the relative dynamic ranges happen to
produce on a given repo. Both scores are **rank-normalised to
[0, 1]** (or min-max, TBD by week-3 measurement) before combining.
This makes α a real knob that means what it reads.

The hydrator then combines:

```
final_score = α · norm(task_score) + (1 − α) · norm(centrality_prior)
```

with default `α = 0.7` (task signal dominates when present), falling
back to `α = 0.0` (pure centrality) when the working set is empty —
the cold-start case at session start.

🧪 **Wide α sweep, not narrow.** §8.5 sweeps α ∈ {0, 0.3, 0.5, 0.7,
1.0}. The interesting question isn't "what's the best α" but **"does
the combination beat either endpoint?"** If α = 1.0 wins,
`centrality_prior` is decorative and we simplify by deleting the
persistence layer. If α = 0.0 wins, BM25 is decorative and we
simplify by serving pure PageRank. The sweep is designed to falsify
the two-score architecture, not just tune it.

### 6.3 Incremental updates — bidirectional invalidation

✅ `IncrementalPacker` already classifies files into new / modified /
unchanged / deleted using SHA-256 + mtime. For v0, invalidation runs
**both directions**:

- A modified file invalidates its own symbols.
- It also invalidates symbols whose `callees_static` field points at
  the modified file's symbols (because if `foo` was renamed in F,
  every external caller's listed callees are now stale).
- And symbols whose `callers_static` field points at the modified
  file's symbols (callers within the modified file may have moved
  in or out).

This keeps re-packing time roughly proportional to edit blast radius,
not repo size, while ensuring the served `callers_static` /
`callees_static` fields never lie about who points where after a
rename.

⚠️ Open question: how often to recompute the global PageRank
`centrality_prior`? Tentatively: lazily, on demand, when ≥5% of
symbols have changed since the last full pass. Cheap enough to rerun
in seconds for repos under 100K LOC.

---

## 7. MCP surface

Three new tools, slotting next to the existing `ctx/hydrate`. Note
the optional `context` parameter — that's where the per-turn
`task_score` (§6.2) gets fed in.

### 7.1 `ctx/list_symbols(module, k=50, context=None) → SymbolCatalog`

Returns the top-k symbols in `module` ranked by combined
`α · task_score + (1−α) · centrality_prior` (§6.2). When
`context=None`, falls back to pure centrality — useful at session
cold-start before the agent has done anything.

`context` is a short string the agent can pass — its recent message
history, the task description, or the prompt it's currently working
on. The packer hashes it for the telemetry log (never stores raw).

### 7.2 `ctx/hydrate_symbol(name, depth=0, context=None) → SymbolPack`

- `depth=0`: signature + docstring + body + callers_static +
  callees_static lists (names only, not bodies).
- `depth=1`: also include the bodies of direct callers and callees,
  budget-capped at 4K BPE total, ordered by combined ranking score
  (so high-`task_score` neighbours come first if budget is tight).

🧪 Depth 1 is where the iterative-retrieval idea from RepoCoder bites:
agents that draft, then realize they need a helper's body, can
re-call with `depth=1` instead of doing a fresh search.

### 7.3 `ctx/search_symbols(query, k=10, context=None) → SymbolCatalog`

Fuzzy match against `name + signature + docstring-first-line`. v0
uses BM25 over those three fields (no embeddings, no vector DB —
matches CTX's zero-dep posture). `context` biases the score the
same way as §7.1.

⚠️ HyDE retrieval (LLM in the loop to imagine the target code) is
**not** in v0. Reason: it breaks the deterministic posture set in
§4 ("no LLM in steps 1–5"), and the framing of CTX-as-deterministic-tool
is something we want to preserve. If the v0 eval shows BM25
plateauing, we revisit and explicitly mark `search_symbols` as
non-deterministic when HyDE is on.

### 7.4 `ctx/raw_file(path: str) → FileContents`  — escape hatch

⚙️ The packer is a *curated* view of the codebase. When the curation
is wrong (catalog incomplete, ranking missed, agent chasing a path
the call graph doesn't see), the agent needs a way out that doesn't
require re-architecting its session.

`ctx/raw_file` returns the literal bytes of a file path. No
filtering, no symbol extraction, no ranking. Subject to
`.ctxpackignore` only.

**Telemetry on this tool is load-bearing.** Every `raw_file` call is
logged with `(task_hash, prior_hydrate_calls, file_path)`. High
usage on a task class = the packer is failing that task class —
direct signal for ranker or exclusion-rule work. If a team sees
`raw_file` calls dominate over `hydrate_symbol` calls, the packer is
strictly negative-value for them and we should know that fast.

### 7.5 Pack manifest — receipt of what was excluded

⚙️ Every `SymbolPack` and `SymbolCatalog` response includes a
manifest footer:

```
---
ctxpack manifest:
  pack_version: sha256:8a2f...
  served:
    symbols: 23
    bytes: 4127
  excluded:
    below_relevance_threshold: 47
    generated_files: 12 files
    gitignored: 31 paths
    tests_not_in_layered_mode: 8
  caveats:
    call_graph_imprecision_in_module: ~14% of edges
    decorator_chain_unresolved: 2 cases
  escape_hatch: ctx/raw_file(path)
---
```

Two purposes:

1. The agent has the receipt of what it didn't see. Reframes its
   behavioural model from "I have the whole repo" to "I have a
   curated view; here's what's outside it." That reframe is what
   mitigates the agent-doesn't-know-the-view-is-curated failure
   mode (one of the three §10.5 regression vectors).
2. Determinism debugging: same `pack_version` hash on two runs =
   byte-identical pack. Cheap check; surfaces non-determinism
   leaks (hashmap iteration order, PageRank tie-breaks) before
   they become someone's confusing bug.

### 7.6 Generated-file exclusion

Bake into the producer at parse time, not at retrieve time —
indexing generated artifacts pollutes both centrality scores and
catalogs.

Rules, applied in order:

1. Honour `.gitignore` (treat anything ignored by git as out of scope
   for the pack).
2. Honour an explicit `.ctxpackignore` (overlay file, syntax matches
   `.gitignore`).
3. Heuristics for the common generated-code patterns:
   - TypeScript: `*.d.ts` outside `node_modules` are kept if they
     define exports a user wrote; rest dropped. Files containing the
     marker `Code generated by` or `DO NOT EDIT` in the first 200
     bytes are dropped.
   - Python: files under `__pycache__`, `*_pb2.py`, `*_pb2_grpc.py`,
     anything Alembic-versioned under `migrations/versions/` dropped.
   - TSX-specific: Prisma client (`@prisma/client`), GraphQL
     codegen outputs, Next.js `.next/` build outputs, dropped.
4. Symbols that survive but have no docstring AND are in the top 1%
   by call count get a stopword flag (the "logger" / "assert_eq"
   case from §9 rev 1).

---

## 8. Eval — what "best in class" actually means

**Seven measurements**, ordered by leverage. §8.0 is the
**pre-ship blocker** — the one that catches the headline failure
mode ("we hid code the agent needed") at the cheapest iteration
cost. §8.4 and §8.5 are the **category-claim evals** — they test
the §3 thesis, not just efficiency. §8.6/8.7 are CI-as-gates that
prevent the slow erosion that happens after a system ships and
everyone trusts it.

### 8.0 Oracle-set recall gate (pre-ship blocker — highest leverage)

🧪 The highest-leverage regression test in the whole eval suite, and
the one most likely to get skipped because it needs human work
upfront.

**Method.** For each task in the eval suite, a competent human (or
a small panel) writes down by hand **the set of symbols genuinely
needed** to complete the task — the "oracle set." This is purely a
retrieval-side annotation; no agent in the loop. ~20–30 tasks,
annotated in week 4 alongside the eval harness.

For each task, compute the packer's recall of the oracle set:

```
recall_t = |served_symbols ∩ oracle_set| / |oracle_set|
```

**Ship gate.** Below 95% recall on >10% of tasks = ship blocked.

**Why this is the single best regression test:**

- Catches "the ranker is hiding code the agent needs" without
  requiring agent-in-loop evals, which means we can iterate on
  the ranker at human-typing speed instead of agent-run-takes-an-hour
  speed.
- Decouples retrieval failure from agent-side failure. SWE-bench
  alone gives us "you're 2pp behind raw stuffing" with no signal
  on *why*. Oracle recall says: low recall = ranking bug; high
  recall but the agent still failed = something other than
  retrieval, look elsewhere.
- Reruns on every ranker change. Cheap CI; expensive to skip.

⚠️ Annotation discipline. Have two annotators do the first 5 tasks
independently, compare, document where they disagree. Disagreement
on "is this symbol needed?" is itself a signal — it usually means
the task is ambiguous or has multiple reasonable solutions, both
worth knowing about.

### 8.1 Tokens served per task (efficiency baseline)

**Method**: 30 representative agent tasks across the two eval repos
(one Python+FastAPI, one React TSX). For each task, count tokens
delivered by:

- Raw stuffing (top-level dir tree + relevant files cat'd whole).
- Aider repo-map baseline.
- CTX code packer (catalog + targeted `hydrate_symbol` calls).

**Target**: ≥3× reduction vs. raw stuffing. Target *parity-or-better*
with Aider; we don't expect dramatic daylight on this metric alone
(see §8.2 below for why).

### 8.2 SWE-bench Verified subset (ceiling check)

**Method**: ~50-task subset, each retrieval strategy feeding Claude
Opus 4.7, scored with the SWE-bench grader.

**Expected outcome**: parity between CTX and Aider, both well above
raw stuffing. SWE-bench tasks are issue→PR, which means the
retrieval target is usually telegraphed by the issue text — both
ranking strategies will look brilliant and we won't see daylight
between them. We run it to confirm we don't *regress* on the
standard benchmark, not to claim victory on it.

**Target**: within 2pp of Aider, within 2pp of raw stuffing on the
upper bound.

### 8.3 Hallucinated-symbol rate (correctness gate)

**Method**: parse the agent's output for symbol names (Python
identifiers + TSX JSX elements + imports); check each against the
served pack and the actual repo. Rate = fraction of referenced
symbols that don't exist anywhere.

**Target**: ≤1% AND strictly below the **measured** raw-stuffing
baseline on these two repos. The rev-1 "3–7% anecdotal" figure has
been pulled — we'll measure it on each repo in week 4 and set the
threshold from data, not memory.

### 8.4 Trust-label behavioural eval (the novel datapoint)

⚠️ **The naïve version of this eval cannot conclude anything.** Modern
LLMs have a strong baked-in TDD prior: show Claude or GPT a failing
test next to incomplete src, and even with no trust labels it will
usually guess "implement src to match test." The flat config will
look good, and we will fail to attribute layered-config wins to the
label vs. to the prior.

Three configurations, two task classes — designed so the layered
label has to do work the agent's prior doesn't already do.

**Configurations:**

- **A — flat**: tests and src both tagged `RULES`.
- **B — layered (canonical)**: tests `INFERRED`, src `RULES`.
- **C — swapped (control)**: tests `RULES`, src `INFERRED`.
  This is the single most important upgrade. If the agent ignores the
  swap and behaves the same as config B, the label is decorative and
  any layered-config wins are coming from the TDD prior, not the
  trust signal. If the agent flips behaviour under C (e.g. starts
  implementing test-to-match-src), the label is genuinely
  controlling.

**Task classes:**

1. **Canonical TDD (10 tasks)**: test specifies desired behaviour src
   doesn't yet implement. Measure: does the agent write src to match
   the test?
2. **Adversarial (10 tasks)**: the test is *wrong* — off-by-one in
   expected output, stale and contradicts another test, or asserts a
   buggy behaviour. This is where the label has to earn its keep:
   the agent's TDD prior pushes toward "trust the test"; only the
   trust label can correct that. Measure: does the agent question
   the test, flag the contradiction, or check src against external
   logic instead of "fixing" src to match a buggy test?

**Targets:**

- Canonical TDD: B > A by ≥10pp on "wrote src to match test"
  rate (necessary; insufficient on its own).
- Adversarial: B > A by ≥15pp on "questioned/flagged buggy test"
  rate (the harder ask — this is where prior fights label).
- Swapped (C) vs B: ≥10pp behavioural delta in the expected
  direction on either task class. **If C behaves like B, kill the
  trust label feature.** That's a real finding worth shipping.

**Why this matters.** Without the C config, a sceptical reviewer can
plausibly say "you've measured the TDD prior with extra steps." With
C, the eval can conclude one of three useful things:
(i) the label controls behaviour and the feature ships,
(ii) the label correlates with content the agent already knows and
the feature is decorative — drop it,
(iii) the label has partial effect — useful for adversarial cases
only, scope it appropriately.

### 8.5 Retrieval-hard synthetic suite (the differentiator)

The class of tasks SWE-bench doesn't have: greenfield additions,
multi-file refactors, "make this slow function faster" with no
filename hint. These are where retrieval, not patching, is the
bottleneck.

**Method**: 15 hand-crafted tasks across the two eval repos:

- 5 greenfield: "add an endpoint that does X" / "add a component
  that does Y" with no hint about which existing modules are
  involved.
- 5 wide refactor: "rename concept X to concept Y across the
  codebase" — 20–40 file edits expected.
- 5 perf / quality: "this function is slow, find out why and fix
  it" with the function name only, no hint about callees or
  helpers.

For each task, compare raw stuffing, Aider repo-map, and CTX (with
α-sweep over §6.2 weights). Score by:

- Task completion (manual grade, 0/1/2).
- Tokens to first correct edit.
- Number of MCP / retrieval calls to converge.

**Target**: CTX wins ≥2 of 3 sub-scores on ≥10 of 15 tasks, with a
defensible α value emerging from the sweep. **This is the eval that
proves the category claim in §3** — if CTX doesn't pull ahead on
these tasks, the IR/trust/incremental story is unmotivated.

### 8.6 Determinism CI (continuous gate)

⚙️ Same input, same output, byte-for-byte. The cache-friendliness
story (§5, §6.3) breaks silently if a tie-break in PageRank or a
hashmap iteration order leaks non-determinism into pack output.

**Method.** CI job: pack the fixture repo twice; assert the two
`pack_version` hashes (§7.5) match. Pack the two eval repos twice;
diff catalogs and entity emissions line-by-line.

**Cost.** ~ms per pack. **Gate.** Any non-determinism fails CI.

Cheap to add now, painful if it slips into v0.1 — non-determinism
bugs surface as "the agent saw something different last time" reports
weeks after they shipped, and bisecting them is miserable.

### 8.7 SWE-bench as continuous integration

⚙️ Every PR to the packer reruns §8.2 (SWE-bench Verified subset)
and blocks merges that move accuracy down. Not a one-time validation
milestone; an always-on test.

The pattern that kills systems like this is "we ran the eval once at
v0, it passed, ship it, then over the next 3 months a series of
1-pp regressions individually look fine but compound." Treating the
eval as a test rather than a milestone is what stops the slow erosion
that happens once everyone trusts the system.

**Cost.** ~$30–80 of compute per CI run on the ~50-task subset.
Reasonable for a packer with this much agent-facing impact.

---

## 9. What could go wrong

⚠️ **TSX parsing edge cases**. JSX inside generic-type positions,
satisfies-operator, decorators — tree-sitter handles most but not
all. Mitigation: log unparseable spans, fall back to file-level
chunking for those, fix forward.

⚠️ **Call-graph imprecision in Python**. Dynamic dispatch
(`getattr`, decorators that wrap, MRO, `**kwargs` forwarding) means
static call graphs miss 20–40% of edges in real codebases — well
documented in the static-analysis literature. For PageRank-style
centrality this averages out; for the `callers_static` /
`callees_static` fields shown to the agent, "best-effort" will be
visibly imperfect to early users.

Mitigation: ship in week 6 with known holes documented in the README
and surfaced in the field name. Don't chase perfect static analysis
— that's a year of work. The two-score ranking (§6.2) means the
agent's working set is the dominant signal once a task is underway,
which masks a lot of graph imprecision.

⚠️ **Catalog freshness vs. cost**. If we re-emit the catalog on
every file change, a busy repo never finishes packing. Mitigation:
debounce + the existing `IncrementalPacker` cache.

⚠️ **Invalidation has the same imprecision as the call graph.** An
undetected A→B edge (a decorator the static parser doesn't follow,
a `getattr` dispatch) means modifying A doesn't invalidate B's
`callers_static` field. Acceptable for v0 because (a) we re-pack
frequently and a subsequent file-touch on B will refresh it,
(b) the §7.5 pack manifest exposes the imprecision honestly, and
(c) chasing perfect static analysis is a year of work. But: the
risk is real, the bound is "as imprecise as the graph," and we
shouldn't pretend otherwise to early users.

⚠️ **Cold-start dominance by centrality**. At the start of a session
the working set is empty, so `task_score` is null and the catalog
falls back to pure `centrality_prior`. Heavily-called utilities
(`logger`, `assert_eq`) will outrank the subject of the task.
Mitigation: the §7.6 stopword flag (top 1% by call count + low
docstring length), plus the fact that the first turn typically
includes the task description as context — which feeds `task_score`
for turn 2 onwards.

⚠️ **α tuning**. The two-score formula (§6.2) introduces a knob.
If α is too high the cold-start case degrades; too low and we lose
the task adaptivity that's the point of having two scores. §8.5
sweep is how we settle this, but until it lands, default α = 0.7 is
a guess.

---

## 10. Build plan — split eval slate

Rev-2 plan compressed too much into a single ship. Rev 3 splits the
eval slate: **ship v0 at week 6 with the gating evals** (oracle
recall, tokens, SWE-bench parity, hallucination rate, determinism
CI). **§8.4 trust-label and §8.5 retrieval-hard ship as v0.1 evals
+2 weeks later**, because:

1. Shipping forces real-user friction faster than internal evals do.
2. §8.4 and §8.5 are the evals most likely to need fixture-design
   iteration after first contact; treating them as a follow-up
   milestone gives them room to be done properly rather than
   rushed into a release deadline.
3. SWE-bench parity (§8.2) is what defends "we didn't break
   anything." Category-claim evals (§8.4, §8.5) are what defend
   "we built something new." Those are different conversations
   with different audiences and don't need to ship together.

### v0 milestone (week 6)

| Week | Deliverable |
|---|---|
| 1 | Tree-sitter Python front end, symbol → IREntity emitter, FastAPI-aware metadata extraction (routes, Depends, pydantic models), unit tests on a tight fixture repo. |
| 2 | TSX front end (function components, hooks, exported utilities). Call-graph builder. Generated-file exclusion rules + `.ctxpackignore`. |
| 3 | Two-score ranker with rank-normalisation (§6.2): `centrality_prior` (PageRank, persisted) + `task_score` (BM25 over working set). Bidirectional invalidation in IncrementalPacker. Determinism CI gate (§8.6). |
| 4 | MCP tools `list_symbols`, `hydrate_symbol`, `search_symbols` with `context` param + `raw_file` escape hatch (§7.4) + pack manifest (§7.5). End-to-end smoke on CTX_mod + one external Python+FastAPI repo + one React TSX repo. **§8.0 oracle annotation** (20–30 tasks, 2 annotators on first 5 for inter-rater check). Measure catalog-size distribution and §8.3 hallucination baseline. |
| 5 | §8.0 (oracle recall) + §8.1 (tokens/task) + §8.3 (hallucination rate). **§8.0 below 95% recall on >10% of tasks = ship blocked**; iterate on ranker until gate passes. |
| 6 | §8.2 (SWE-bench Verified subset, also wired as §8.7 CI). Write up results; if all gates pass, ship `ctxpack code v0`. |

### v0.1 milestone (week 6 + 2 weeks)

| Week | Deliverable |
|---|---|
| 7 | §8.5 retrieval-hard suite with full α sweep over {0, 0.3, 0.5, 0.7, 1.0}. |
| 8 | §8.4 trust-label behavioural eval (flat / layered / swapped configs, canonical + adversarial task classes). Decision on whether trust label ships on by default. Write up category-claim results. |

⚠️ **Realistic estimate**. Rev-2's 6-week scope was tight. Rev-3's
expanded scope (two-score normalisation, oracle annotation, escape
hatch, manifest, determinism gate) honestly maps to 7–8 weeks if
nothing surprises us, 9–10 if call-graph quality bites
user-visible fields harder than expected. We hold the line at week
6 for v0 by deferring the category-claim evals to v0.1, *not* by
cutting safety scope.

🧪 Stretch (post-v0.1): dream-pipeline integration so co-retrieved
symbol pairs auto-promote to INFERRED pattern entities (reuses the
consolidated pipeline already shipped in Phase 3c). HyDE A/B *only
if* §8.1 / §8.5 plateau and we accept the determinism tradeoff.

---

## 10.5 Post-ship safety net

The gates in §8 catch issues before ship. These mechanisms catch
issues that only show up in real use — and they catch them quickly
enough to act on.

### Three failure modes specific to this design

1. **Hiding code the agent needed.** The packer serves less than
   raw stuffing. If it serves the wrong less, we regress on tasks
   the agent would have completed naively. Headline risk. Oracle
   gate (§8.0) catches pre-ship; telemetry catches post-ship.
2. **Stale or imprecise context.** Call graph misses 20–40% of
   edges → invalidation has gaps → the agent occasionally gets a
   symbol that should have been re-emitted. Raw stuffing doesn't
   have this failure mode.
3. **Agent behavioural drift.** Claude Code currently assumes it
   can list and read anything. The packer gives it a curated view.
   If the agent doesn't *know* the view is curated, it won't know
   to ask for more when the catalog is incomplete. Subtlest of the
   three; the §7.5 manifest is the primary mitigation.

### Telemetry signals (instrument from day one)

⚙️ Three behavioural patterns that are direct evidence of packer
failure, observable from the existing `HydrationEvent` log:

- **`hydrate_symbol` → `raw_file` on the same file in the same
  turn.** The hydration was insufficient. Log + dashboard.
- **Repeated `search_symbols` calls with reformulated queries in
  the same turn.** Vocabulary mismatch — the catalog isn't using
  the words the agent thinks in.
- **Agent edit introduces a symbol reference not in the served
  pack.** ContextGuard catches this already; surface it as a
  per-task metric so we can graph it over time.

### Shadow mode (first week on a new repo)

⚙️ For the first week on any repo a team adopts CTX for, the
packer runs but doesn't serve; raw context is served and the
*would-have-been-served* pack is logged. Compare oracle recall
(if annotations exist) and observed task outcomes. Only flip to
serving when shadow mode shows parity.

Cheap (storage only, no impact on agent), and prevents
repo-specific failure modes from being discovered in production
on a single team's session.

### A/B in production

⚙️ Random session-level or repo-level assignment of packed vs raw
context for the first N tasks after rollout. If packed regresses
on real-world distribution when synthetic evals said it
shouldn't, we have a flag to flip and a debugging starting
point. Standard practice; load-bearing for a system this
agent-facing.

📚 The shadow-mode + A/B pattern is borrowed from search-quality
deployments at Google / Bing scale, where retrieval changes are
shipped through a measured promotion ladder rather than a single
big-bang deploy. Same risk profile applies here: a retrieval
change can subtly degrade agent quality in ways unit tests don't
catch.

---

## 11. Open questions

1. **Granularity for TSX**: per-component or per-export? Components
   are often the right unit; tiny exported utilities also matter.
   Lean: per-export, with components annotated as `kind=component`.
2. **Should the catalog itself be hydratable from a higher-level
   index** (i.e. an L4)? Possibly for repos >200K LOC. **Decision
   gated on the week-4 catalog-size measurement.** If a typical
   per-module catalog fits in 10K BPE, we don't need L4. If
   modules are large/heterogenous and catalogs blow past that,
   L4 becomes a v1 add.
3. **Test files**: tagged `INFERRED` and shown in the same catalog
   as src tagged `RULES`. The §8.4 eval tells us whether that label
   actually changes agent behaviour. If yes, ship as default. If no,
   drop the layer distinction for code (keep it for the prose packer
   where the v3 whitepaper claim still stands).
4. **Stale-pack detection on the agent side**: if the agent has an
   old `SymbolPack` cached in conversation, how does it know to
   refetch? Lean: include a `pack_version` (content hash of producer
   output) in every `SymbolPack` response, plus a `ctx/version` MCP
   probe the agent can cheap-poll.
5. **α default**. §6.2 lists 0.7 as a guess. The §8.5 sweep settles
   it for the eval repos, but the right answer might be repo-shape
   dependent. Open whether α is configured at pack time or at
   retrieve time.
6. **FastAPI dependency-injection chains**: how deep to follow
   `Depends(...)` chains when hydrating a route handler? Default 1
   level; deeper feels like a power-user knob.

---

## 12. Why this fits CTX, not a separate tool

The temptation is to spin "code-packer" out as its own thing. Against
that:

- IR, hydrator, grounding, ContextGuard, telemetry, ConfidenceTracker,
  IncrementalPacker — every one of these is reusable as-is.
- Specs/plans/tasks (the user's first complaint) already pack well in
  the domain pipeline. One MCP surface, two producers, one mental
  model for the agent.
- The Phase 3 dream pipeline becomes immediately more useful: it can
  now mine co-retrieved *symbol* patterns, not just section pairs.

If we ship the code packer as a sibling producer in the same repo,
the agent operating on a real project gets prose context + code
context from one MCP server with one trust model. That is the thing
nobody else has shipped.

---

## 13. Decision asked of the reader

The thesis (§3): **one IR, one trust model, deterministic +
incremental + MCP, across prose and code.** The build plan
(§10) and evals (§8) are how we prove that thesis is real and not
just a slogan.

Locked after rev-1 review:

- ✅ Languages: Python (incl. FastAPI), React TSX.
- ✅ Eval: §8.1–§8.5 as written, with §8.5 (retrieval-hard) as the
  category-claim eval and SWE-bench (§8.2) demoted to ceiling check.
- ✅ Quality/regression stays out of scope (§2).

Locked after rev-2 review:

- ✅ Two-score ranking shape (§6.2), with rank-normalisation added.
  Wide α sweep designed to falsify the two-score architecture, not
  just tune it.
- ✅ §8.4 trust-label eval upgraded with adversarial cases +
  swapped-label control. If the swapped-label config behaves like
  the layered config, the trust feature is decorative and gets
  dropped.
- ✅ Build plan split: v0 ships week 6 with safety gates (§8.0
  oracle, §8.6 determinism, §8.7 SWE-bench CI). v0.1 evals
  (§8.4 trust-label, §8.5 retrieval-hard) ship +2 weeks.
- ✅ Safety net (§10.5): `ctx/raw_file` escape hatch, pack
  manifest footer, three telemetry signals, shadow mode on new
  repos, A/B in production.
- ✅ Guiding principle (§2): regression protection comes from
  gates, escape hatches, visibility — **not** from defensive
  over-serving.

Week 1 cleared to start. The remaining open questions (§11) are
hold-loosely-refine-on-contact items; they don't block the Python
tree-sitter scaffold. Specific surfaces to watch in week 1:

- How decorators and class-level attributes get extracted as
  symbols. FastAPI's `@app.get(...)` and Pydantic's
  `class Foo(BaseModel)` are the patterns most likely to need
  bespoke handling.
- Whether `from __future__ import annotations` changes type-string
  extraction in unhelpful ways.
- Where the symbol-name namespace (`file::Class.method`) needs
  disambiguation for things like overloads and conditional
  definitions.

If any of those bite hard enough to change the IR shape, that's a
rev-4 conversation. Otherwise the scaffold is the source of truth.
