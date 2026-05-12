---
title: Code Packer v0 — Backlog & Loop Discipline
parent: code-packer-v0-rfc.md
date: 2026-05-12
status: Draft for review before loop kickoff
---

# Code Packer v0 — Backlog

~56 tasks across two milestones (v0 = weeks 1–6, v0.1 = weeks 7–8).
Each task is sized to ~0.5–1.5 days so one loop iteration can carry
it through the full discipline (spec → design → TDD → red team →
fix → regression check → spec check → ship).

**ID convention**: `CP-NNN[.M]`. Strictly ordered; lower IDs first.
`.M` suffixes are insert tasks (e.g. `CP-002.5` slots between
`CP-002` and `CP-003`). Deps column lists hard prerequisites only —
soft "would-be-nice-to-have" ordering is implied by ID.

**Acceptance criteria** are deliberately concrete. The loop's
"check against spec" step matches output to these bullet points,
not to vibes.

---

## Task discipline template (run on every task)

```
For task CP-NNN:

[1] SPEC
    - Re-read CP-NNN entry in backlog: title, deps, acceptance criteria.
    - Write a short task spec (≤25 lines) in
      .ctx-cache/tasks/CP-NNN.spec.md:
        - What does done look like? (cite acceptance criteria)
        - What does this NOT do? (explicit non-goals)
        - What files will change?
        - What's the smallest test that proves it works?
    - If spec reveals scope creep or a dep was missed, STOP and
      flag in the loop log; do not proceed silently.

[2] DESIGN
    - Sketch the interface (function signatures, file layout) before
      writing implementation.
    - Identify the failure modes specific to this task.
    - One paragraph max. Append to .ctx-cache/tasks/CP-NNN.spec.md.

[3] TDD — RED
    - Write failing tests that pin the acceptance criteria.
    - Run pytest -k <test_pattern> and confirm they fail for the
      expected reason (not "ModuleNotFoundError").

[4] TDD — GREEN
    - Implement the minimum code that makes the failing tests pass.
    - Resist scope creep: if you find yourself fixing an adjacent
      bug, write it down for a future task instead.

[5] RED TEAM
    - For each acceptance criterion, ask "how could this be wrong
      and still pass the tests I wrote?"
    - Add a test for each plausible failure mode you find.
    - For tasks touching ranker/hydration: include at least one
      adversarial input (mis-named symbol, empty input, unicode).
    - For tasks touching MCP surface: include malformed-input case.

[6] ITERATE
    - Make new red-team tests pass.
    - If you discover the design is wrong (not just incomplete),
      STOP and flag. Don't paper over with band-aids.

[7] REGRESSION
    - Run the fast test suite:
      pytest -m "not slow"
    - Tests previously excluded with hardcoded path ignores
      (test_codebase.py, test_harness.py) should be tagged with the
      "slow" marker as part of CP-001 so this contract survives
      future test reorganisation.
    - All green required. If a pre-existing test fails, that's an
      orthogonal issue — flag and do not stuff it into this task.

[8] SPEC CHECK
    - Re-read CP-NNN acceptance criteria against the diff.
    - Confirm each bullet has either a test that proves it or a
      manual verification note.
    - Note any acceptance criterion you couldn't deliver and WHY.

[9] SHIP
    - git add only files the spec said would change.
    - git commit with message:
        CP-NNN: <title>
        <one-line why>
        Acceptance: <checked criteria>
    - Update .ctx-cache/tasks/CP-NNN.spec.md status to "shipped"
      with commit SHA.
    - Append one-liner to .ctx-cache/tasks/loop-log.md.
```

**Stop conditions** (the loop must halt and surface, not bulldoze):

- Test suite has pre-existing red tests on starting state.
- A task depends on a CP-NNN that isn't shipped.
- Spec for the task reveals it's actually 3 tasks.
- An acceptance criterion can't be met without changing the RFC.

---

## Milestone v0 — Week 1: Python front end

| ID | Task | Deps | Effort | Acceptance |
|---|---|---|---|---|
| CP-001 | Scaffold `ctxpack/core/code/` + `tests/code/` + fixture repo `tests/code/fixtures/py_fastapi_min/` | — | 0.5d | Package importable; fixture has 3 files (app.py, models.py, deps.py); empty test module collects |
| CP-002 | Tree-sitter Python parser wrapper: file path → AST root | CP-001 | 0.5d | `parse_python(path) → tree-sitter.Tree`; handles syntax errors gracefully (returns partial tree + warnings list) |
| **CP-002.5** | **Tokeniser pin + `count_bpe(s) → int` helper as single source of truth for every BPE measurement and budget enforcement in the packer.** | CP-001 | 0.5d | Tokeniser choice (Claude tokenizer / tiktoken cl100k_base / etc.) documented + justified in ADR. Single helper at `ctxpack/core/code/tokens.py`; tests assert ≥4 known reference strings produce stable counts; every later task that measures/budgets tokens imports this helper and not a side channel. |
| CP-003 | Symbol extractor: top-level functions and classes from AST → `list[Symbol]` with name, kind, line range | CP-002 | 1d | All 3 fixture files yield the expected symbol count and line spans; no class methods yet |
| CP-004 | Class method extraction (incl. `__init__`, properties, staticmethods) | CP-003 | 0.5d | `Foo.bar` symbols emitted with `kind=method`; class-level attrs captured as `kind=class_attribute` |
| CP-005 | Decorator capture on functions/methods: list of decorator strings + arg literals | CP-004 | 0.5d | `@app.get("/foo")` produces `decorators=["app.get"]` with `decorator_args=[{"path":"/foo"}]` |
| CP-006 | FastAPI route detection: `@app.*` / `@router.*` decorators → `http_method`, `http_path` entity fields | CP-005 | 0.5d | Routes in fixture surface with correct method+path; non-routes don't |
| CP-007 | FastAPI `Depends(...)` extraction: parameter-level dependencies → `dependencies` field | CP-006 | 0.5d | A route with `Depends(get_db)` lists `get_db` in dependencies; nested Depends flagged for depth-1-only |
| CP-008 | Pydantic BaseModel detection: subclasses of BaseModel → `kind=pydantic_model` with field types | CP-004 | 0.5d | Each model in fixture emits one entity with `pydantic_fields=[{name, type}]` |
| CP-009 | Symbol naming scheme `<file>::<dotted.path>` with deterministic disambiguation for overloads | CP-004 | 0.5d | Two functions with same name in different scopes get distinct stable names; round-trips through serialization |
| CP-010 | `Symbol → IREntity` emitter wiring all field types from RFC §5 | CP-003–CP-009 | 1d | One entity per symbol, all required fields populated; `centrality_prior` placeholder 0.0 for now |
| **CP-010.3** | **Catalog-row renderer with soft cap (RFC §5)**: `render_catalog_row(entity) → str` producing `name + kind + signature + docstring-1st-line`, ≤120 BPE soft cap (uses `count_bpe` from CP-002.5). When over cap, truncate the signature mid-generic and append `…`; never truncate the name. | CP-010, CP-002.5 | 0.5d | Three test cases: short signature passes through verbatim; 200-BPE Python type-union signature truncates with `…`; deeply-nested TSX generic `Foo<T extends Bar<U>, U = Baz<V>>` truncates at a generic-boundary character, not mid-identifier |
| **CP-010.5** | **TSX minimal fixture repo** at `tests/code/fixtures/tsx_react_min/`: `App.tsx`, `Card.tsx`, `useFoo.ts`, `format.ts`. Includes at least one generic-heavy signature, one JSX-in-generic-position case, one forwardRef component, one custom hook. | CP-001 | 0.5d | Fixture parses with tree-sitter-tsx; intentional edge cases documented in `tests/code/fixtures/tsx_react_min/EDGE_CASES.md` so they double as regression coverage |

## Milestone v0 — Week 2: TSX + call graph + exclusion

| ID | Task | Deps | Effort | Acceptance |
|---|---|---|---|---|
| CP-011 | Tree-sitter TSX parser wrapper + JSX handling | CP-002, CP-010.5 | 0.5d | `.tsx` fixture file parses; JSX inside generic-type positions doesn't crash (logs unparseable span instead) |
| CP-012 | TSX symbol extractor: function components, arrow components, exported utilities | CP-011 | 1d | Each export in `tests/code/fixtures/tsx_react_min/` yields an entity with `kind=component\|util\|type` |
| CP-013 | React hooks detection on components: `useState`/`useEffect`/`useMemo`/custom hooks → `hooks` field | CP-012 | 0.5d | Component using 3 hooks emits `hooks=["useState","useEffect","useFoo"]` |
| CP-014 | Python static call graph: caller → callee edges from AST (best-effort, named function calls only) | CP-004 | 1d | Edge count on fixture matches hand-counted expected; documented as best-effort with known holes |
| CP-015 | TSX call graph: component-import and component-usage edges via JSX element names | CP-012 | 1d | `<Foo />` inside `Bar` emits edge `Bar → Foo`; import edges captured for utils |
| CP-016 | `.ctxpackignore` parser (gitignore syntax) | CP-001 | 0.5d | Glob patterns + negation + comments parsed; ignored paths filtered before parse |
| CP-017 | `.gitignore` honoring | CP-016 | 0.5d | Files matched by either `.gitignore` or `.ctxpackignore` excluded; precedence documented |
| CP-018 | Generated-file heuristics: `*.d.ts`, `*_pb2.py`, Prisma client, Next build outputs, "DO NOT EDIT" marker | CP-017 | 0.5d | Generated fixtures dropped before parse; user-written `*.d.ts` retained |

## Milestone v0 — Week 3: Ranker + invalidation + determinism

| ID | Task | Deps | Effort | Acceptance |
|---|---|---|---|---|
| CP-019 | Weighted PageRank impl over call graph: edge weights (call=1, test=3, export-pin=bonus) | CP-014, CP-015 | 1d | Output scores normalised to sum to 1 (probability-distribution convention). Test edges weight 3× call edges in a controlled mini-graph. Tie-breaking on identical scores is deterministic (alphabetical by symbol name) to support the §8.6 determinism gate. |
| CP-020 | `centrality_prior` persistence: PageRank result baked into IREntity field at pack time | CP-019, CP-010 | 0.5d | After pack, each entity has populated `centrality_prior` ∈ [0,1] |
| CP-021 | BM25 `task_score` over `(name + signature + docstring-first-line)` against working-set string | CP-020 | 1d | Given a query "save user", a `save_user` function ranks above unrelated symbols; sub-ms on 3K-symbol catalog |
| CP-022 | Rank-normalisation helper: rank-normalise score list to [0,1] | — | 0.5d | Two scores with different distributions both map to uniform [0,1] post-normalisation; ties handled |
| CP-023 | Hydrator: combine `α · norm(task) + (1−α) · norm(centrality)` with default α=0.7 | CP-021, CP-022 | 0.5d | API takes optional `context` string; α=0 mode returns pure centrality ordering; α=1 mode returns pure BM25 ordering |
| CP-024 | Bidirectional invalidation in IncrementalPacker: modified file invalidates its symbols + `callers_static` and `callees_static` referrers | CP-019 | 1d | After modifying file F, recursively invalidated set matches hand-computed expectation on fixture |
| CP-025 | Determinism CI gate: pack-twice-assert-equal job in `tests/test_code_determinism.py` | CP-020 | 0.5d | Two packs of fixture produce byte-identical `pack_version` hashes; hashmap-order leak case caught by intentional negative test |

## Milestone v0 — Week 4: MCP surface + smoke + oracle annotation

| ID | Task | Deps | Effort | Acceptance |
|---|---|---|---|---|
| **CP-025.5** | **MCP error contract spec**: enumerate failure modes per tool (`hydrate_symbol` on unknown name, `search_symbols` zero matches, `raw_file` on ignored path, malformed input on any tool) and pin the response shape for each. Use the existing CTX MCP error envelope. | CP-023 | 0.5d | One-page table in `docs/mcp-error-contract.md`: tool × failure-mode → response shape + agent-recovery hint. All downstream MCP tool tasks (CP-026 through CP-030.5) cite this contract in acceptance. |
| CP-026 | `ctx/list_symbols(module, k, context)` MCP tool | CP-023, CP-025.5 | 0.5d | Returns top-k with combined score; respects k; context=None falls back to centrality; errors per CP-025.5 contract |
| CP-027 | `ctx/hydrate_symbol(name, depth)` MCP tool, depth 0 and 1 | CP-026 | 1d | depth=0 returns sig+docstring+body+caller/callee names; depth=1 adds bodies; 4K BPE budget enforced via `count_bpe` from CP-002.5; errors per CP-025.5 contract |
| CP-028 | `ctx/search_symbols(query, k, context)` MCP tool (BM25) | CP-021, CP-025.5 | 0.5d | Fuzzy match against name+sig+docstring-1st-line; ranking biased by context; errors per CP-025.5 contract |
| CP-029 | `ctx/raw_file(path)` escape hatch MCP tool | CP-016, CP-025.5 | 0.5d | Returns literal file bytes; subject only to `.ctxpackignore`; logs to telemetry with `(task_hash, prior_hydrate_calls, file_path)`; errors per CP-025.5 contract |
| CP-030 | Pack manifest footer rendering on every pack/hydrate response | CP-027 | 0.5d | Manifest includes `pack_version`, served counts, excluded counts (by reason), caveats, escape_hatch hint. JSON schema at `ctxpack/schemas/manifest.schema.json` checked in; manifest output validates against the schema in a unit test. |
| **CP-030.5** | **Stale-pack detection** (RFC §11 Q4): every `SymbolPack` / `SymbolCatalog` response carries `pack_version` (content hash of producer output). Add `ctx/version()` MCP probe that returns the current pack_version cheaply. Document the cache-invalidation pattern for agent SDKs. | CP-030 | 0.5d | `pack_version` is byte-stable across runs of identical input (reuses CP-025 determinism). `ctx/version` response < 1KB. Doc note added to `docs/mcp-error-contract.md` covering stale-pack symptoms and the refetch protocol. |
| CP-031 | End-to-end smoke: CTX_mod self-pack + Python+FastAPI external repo + React TSX external repo | CP-026–CP-030.5 | 1d | All three pack without crashes; sample MCP queries return reasonable results; catalog sizes recorded |
| CP-033 | Oracle annotation: 20–30 tasks across the two eval repos, 2 annotators on first 5 for inter-rater | CP-031 | 1.5d | `eval/oracle_sets/*.json` populated with task_id, repo, oracle_symbol_set, annotator. **IRR rule: Jaccard ≥0.80 on the 5 overlap tasks.** If lower, the oracle has too much annotator-dependent variance and the §8.0 gate would be measuring noise — escalate before continuing. ⚠️ This task has an external-availability dependency (second annotator); plan for slip risk. |

## Milestone v0 — Week 5: Gating evals

> CP-032 and CP-034 moved here from week 4 — they feed the eval
> harnesses below and the week-4 schedule was overloaded.

| ID | Task | Deps | Effort | Acceptance |
|---|---|---|---|---|
| CP-032 | Catalog-size distribution measurement on two eval repos | CP-031 | 0.5d | Histogram + percentiles of catalog BPE per module (using `count_bpe` from CP-002.5); flag any module catalog >10K BPE for L4 follow-up |
| CP-034 | Baseline §8.3 hallucination rate measurement on raw stuffing for two repos | CP-031 | 0.5d | Recorded baseline; informs §8.3 target threshold |
| CP-035 | §8.0 oracle-recall eval harness: pack a repo, run each task's hydration path, compute recall vs oracle set | CP-033 | 1d | Outputs `recall_t` per task and pass/fail vs 95% threshold; CI-friendly exit code |
| CP-036 | §8.1 tokens/task eval harness: raw-stuff vs Aider vs CTX | CP-031, CP-002.5 | 1d | Outputs token counts per (task, strategy) using the pinned tokeniser; ratios computed |
| CP-037 | §8.3 hallucinated-symbol rate eval harness: parse agent output, check vs served pack + repo | CP-034 | 1d | Per-task rate computed; CI gate at measured baseline – ε |
| CP-038 | Ranker iteration: if §8.0 fails, tune until ≥95% recall on ≥90% of tasks (bounded to 5 rounds) | CP-035 | 1–3d | §8.0 gate passes; α default re-justified if changed. **Decision rule at round 5**: if recall isn't met, ship v0 with the actual recall number documented in release notes and a "known weakness" flag — do NOT slip the v0 milestone chasing the gate. The category-claim evals in v0.1 are where the ranker gets its real test; v0 only needs to demonstrate the architecture is sound. |

## Milestone v0 — Week 6: SWE-bench + ship

| ID | Task | Deps | Effort | Acceptance |
|---|---|---|---|---|
| CP-039 | §8.2 SWE-bench Verified subset runner: ~50 tasks, three retrieval strategies, Opus 4.7 | CP-031 | 1.5d | Scored with SWE-bench grader; within 2pp of Aider, within 2pp of raw stuffing ceiling |
| CP-040 | §8.7 CI wiring: SWE-bench subset rerun gated on packer PRs, blocks merges that drop accuracy | CP-039 | 0.5d | GitHub Action / pre-merge job documented. **Cost-tiered gating** to keep CI bills bounded: per-PR runs a 10-task fast subset (~$6–16); the full 50-task subset (~$30–80) runs only on release-tag PRs and nightly main. Budget: ~$200–400/month at typical PR velocity. |
| **CP-040.5** | **Telemetry event schema** at `ctxpack/schemas/telemetry-events.schema.json`: defines `{ts, event_type, task_hash, …event-specific fields…}` for every event type CP-041 will emit. Versioned. | CP-029 | 0.5d | Schema covers at least: `hydration_event`, `raw_file_call`, `search_call`, `symbol_not_in_pack`, `pack_version_query`. CI test: every event written by the codebase validates against the schema. |
| CP-041 | Telemetry: `raw_file`-after-`hydrate_symbol` pattern + reformulated-search pattern + ContextGuard symbol-not-in-pack metric | CP-029, CP-040.5 | 1d | Three signals visible in `.ctx-cache/telemetry.jsonl` and validate against CP-040.5 schema; dashboard rendering deferred to follow-up |
| CP-042 | Shadow-mode harness: pack runs but doesn't serve; would-have-been-served pack logged | CP-031 | 1d | Toggleable via env var; comparison report renders against oracle and observed outcomes |
| CP-043 | A/B assignment hook: random session/repo gating between packed and raw context | CP-042 | 0.5d | Flag-switchable; default off; rollout policy doc note |
| CP-044 | v0 ship write-up: results across §8.0–§8.3, §8.6, §8.7; cite all gates; mark §8.4/§8.5 as v0.1 milestone | CP-040 | 0.5d | `paper/code-packer-v0-results.md` honest-graded same way as status-and-value-v0.5 |
| CP-045 | v0 release: tag, changelog, MCP server wiring documented in README | CP-044 | 0.5d | `ctxpack code v0` installs and runs end-to-end on a clean machine |

## Milestone v0.1 — Weeks 7–8: Category-claim evals

| ID | Task | Deps | Effort | Acceptance |
|---|---|---|---|---|
| CP-046 | §8.5 retrieval-hard task suite construction: 5 greenfield + 5 wide-refactor + 5 perf-no-hint | CP-045 | 1.5d | 15 tasks across both eval repos with grading rubric; tasks adversarial enough to distinguish strategies |
| CP-047 | §8.5 eval runner with α sweep over {0, 0.3, 0.5, 0.7, 1.0} | CP-046 | 1d | Per-task per-α scores recorded; "does combination beat endpoints?" answerable |
| CP-048 | §8.4 fixture construction: 10 canonical TDD + 10 adversarial (test is wrong) | CP-045 | 1d | Fixtures with intentionally buggy tests across both repos; manual rubric for "questioned test" vs "fixed src to match test" |
| CP-049 | §8.4 eval runner: flat / layered / swapped × canonical / adversarial = 6 cells | CP-048 | 1d | 6-cell matrix with per-cell rates; statistical comparison framework |
| CP-050 | v0.1 category-claim write-up: trust label kill-or-ship decision based on swapped-control result | CP-047, CP-049 | 1d | `paper/code-packer-v0.1-results.md`; if swapped == layered, propose dropping trust label from code-packer defaults |

---

## Telemetry tasks (woven through, not parallel milestone)

Already in `CP-041` (week 6). Listed here for traceability against the RFC §10.5 safety-net commitments:

- `raw_file`-after-`hydrate_symbol` pattern → covered.
- Repeated-search-reformulation pattern → covered.
- Symbol-reference-not-in-pack metric → covered.

Shadow mode (`CP-042`) and A/B (`CP-043`) ship with v0, off by default. First teams to onboard run in shadow mode for one week before flipping.

---

## Decision: how to drive the loop

Three viable mechanisms. Each is a different posture on autonomy
vs. inspectability.

### Option A — `loop-driven-dev` skill (heavyweight, opinionated)

Invokes the harness skill's setup wizard, which lays down:
- Per-task discipline scaffolding (ADR/RFC templates, reversibility tags).
- 4-agent verification audit pattern (planner, implementer, reviewer, integrator).
- Anti-bloat gates wired into CI.

Best when: you want infrastructure that outlives this project and
enforces discipline beyond the honor system. Trade-off: invasive
repo changes; some of its conventions may not match the existing
CTX layout.

### Option B — `/loop` skill (medium, recommended default)

Self-paced loop where each iteration:
1. Reads `paper/code-packer-v0-backlog.md` to find next unshipped task.
2. Runs the 9-step discipline template against that task.
3. Commits, updates `.ctx-cache/tasks/loop-log.md`, exits.
4. Reschedules itself for the next iteration after a sensible delay.

Best when: you want hands-off progress with auditable per-task
artifacts (`.spec.md` files + commit messages) you can read between
iterations. Trade-off: trusts the discipline template; if it has
bugs, the loop carries the bugs forward.

### Option C — Manual per-task in this session (slowest, most inspectable)

We work one task at a time, you approve each ship, I move to the
next. The discipline template still applies, but you're the one
advancing the cursor.

Best when: early tasks (CP-001 through ~CP-005) where the contract
between the IR and the rest of CTX is being established and a
wrong call here pollutes everything downstream. Trade-off: scales
poorly past the foundational tasks.

### Recommendation

**Run Option C for CP-001 through CP-010 (the Python front end).
Hold an explicit IR-stability checkpoint before flipping mode.
Switch to Option B from CP-011 onwards only if the checkpoint
passes.**

Rationale: the first 10 tasks define the IR shape and naming
schemes everything else inherits. A wrong call in CP-009 (symbol
naming) costs more to undo than the time you save by automating
those 10 tasks. Once the IR is stable, the per-task work becomes
mechanical and well-suited to a loop.

### IR-stability checkpoint (between CP-010 and CP-011)

Don't flip to Option B mechanically at CP-011. Before the flip, run
this checkpoint and write the result to
`.ctx-cache/tasks/ir-stability-checkpoint.md`:

1. **Has the IR shape changed in any of CP-008, CP-009, CP-010
   beyond what the RFC §5 sketch anticipated?** If yes, the RFC
   needs an update before downstream tasks lock the shape further.
2. **Were any acceptance criteria in CP-001–CP-010 partially met or
   spec-flagged?** Each one is a latent bug the loop will carry
   forward and amplify.
3. **Does the catalog-row renderer (CP-010.3) produce sensible
   output for the 3 fixture files?** Eyeball the first few rows.
   This is the agent-facing surface; a malformed shape here is the
   single thing most likely to mislead the loop.
4. **Are the spec docs (`.ctx-cache/tasks/CP-001.spec.md`
   through `CP-010.spec.md`) readable by a stranger?** If the loop
   has to debug a downstream issue by reading them, they need to
   be self-contained — not "you had to be there."

If any of these come back wobbly, run a few more tasks manually
(CP-011, CP-012) before switching. Cheap insurance against the loop
inheriting drift.

Option A is the right choice if this is going to be a year-long
project with multiple contributors. For a 6–8 week solo build it's
overhead that doesn't pay back.

---

## What to sign off before kicking off

1. Backlog scope (40 tasks, two milestones). Anything missing?
   Anything to cut?
2. Per-task discipline template (9 steps + stop conditions).
   Tight enough? Too tight?
3. Loop mechanism choice (A / B / C / hybrid).

Once locked, the first loop iteration starts on CP-001.
