# Capability Registry

Machine-checked classification of every module in `ctxpack/`
(gate: `scripts/check_capability_registry.py`, run in CI via
`tests/test_capability_registry.py`). Execution-plan task **W1-1**
(`docs/execution-plan-2026-07.md`).

**Why this exists:** the product story is deterministic session memory.
Everything else in the tree is either evidence infrastructure, an
experiment, or a deprecation candidate — and must not be mistaken for
validated product capability (directive T1).

## Classes

- **core** — the product. Supported, tested, documented; changes need
  tests and are held to the ground rules (zero deps, determinism,
  negation preservation).
- **eval** — evidence infrastructure (benchmarks, corpora, metrics,
  judges). Not product; may have optional deps (tiktoken, API clients);
  results it produces are immutable versioned files.
- **experimental** — runnable prototypes with real surface (some are
  CLI-exposed) but **no evidence behind them**. May change or disappear
  without deprecation. Never marketed as capability.
- **legacy-deprecation-candidate** — no callers, superseded, or
  explicitly banked as "do not revive as-is". Scheduled for the next
  deprecation review (with the ~2026-07-18 cohort report).

Rules: a row is an exact file or a directory prefix (trailing `/`);
the most specific match wins; every `ctxpack/**/*.py` (except
`__init__.py`/`__main__.py`) must be covered. Reclassification happens by
PR to this file; promotion **to core requires a claims-ledger row** with
a measured artifact. The `Aka` column lists public names the gate scans
for in `README.md` — an experimental/legacy name may only appear there on
a line carrying its label.

## Registry

| Path | Class | Aka | Notes |
|---|---|---|---|
| `ctxpack/core/` | core | — | .ctx model, parser/serializer/validator, packer pipeline, hydrator, entity graph, fact IDs, supersession DAG, rank, telemetry |
| `ctxpack/core/code/` | core | — | code packer (`[code]` extra: tree-sitter, tiktoken) |
| `ctxpack/core/confidence.py` | experimental | ConfidenceTracker | prototype confidence learning; only consumer is `modules/dream.py`; banked "prototype evidence, never revive as-is" |
| `ctxpack/core/incremental.py` | legacy-deprecation-candidate | IncrementalPacker | zero callers |
| `ctxpack/agent/` | core | — | session-memory substrate: transcript parser, checkpoint engine, read path, conflict lint, scorecard |
| `ctxpack/agent/session.py` | legacy-deprecation-candidate | — | rolling merge+evict prototype; superseded by checkpoint/read-path architecture |
| `ctxpack/agent/state_parser.py` | legacy-deprecation-candidate | — | pre-transcript_parser prototype; no production callers |
| `ctxpack/cli/` | core | — | `ctxpack` CLI (note: `dream`/`elicit`/`codebase` subcommands drive *experimental* modules) |
| `ctxpack/integrations/` | core | — | MCP server (20 tools) |
| `ctxpack/benchmarks/` | eval | — | eval framework, agentic NIAH/graph generators, CompactBench, baselines, metrics |
| `ctxpack/modules/` | experimental | — | opt-in library modules (grounding, keywords, analytics, catalog queries); no production callers today |
| `ctxpack/modules/guard.py` | legacy-deprecation-candidate | ContextGuard | phrase/regex heuristic; not a hallucination detector; never market as one (directive do-not-do list) |
| `ctxpack/modules/dream.py` | experimental | — | consolidation prototype; the ratified path is the deterministic dream-fold (`docs/consolidation-dream-fold-v0.md`), gated on real telemetry — this module is design evidence only |
| `ctxpack/modules/elicit.py` | experimental | — | expert-elicitation capture; CLI-exposed, unvalidated |
| `ctxpack/modules/codebase.py` | experimental | — | codebase harness generator; CLI-exposed, unvalidated |

## Open action items

- The `ctxpack dream` / `ctxpack elicit` / `ctxpack codebase` CLI
  subcommands run experimental modules without saying so — add an
  experimental-status line to their `--help` epilogs (small follow-up,
  not part of W1-1).
- Deprecation review of all `legacy-deprecation-candidate` rows at the
  ~2026-07-18 cohort report: delete, or archive under `prototypes/`.
