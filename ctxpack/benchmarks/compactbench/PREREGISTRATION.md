# CompactBench v1 — Pre-registered Analysis Plan

**Status: PRE-REGISTERED, no runs executed.** This document is committed
before any benchmark run per the repo's standing rigor policy. Deviations
in the eventual runs must be reported as deviations, not silently
absorbed. Results will be judged against the decision rules below —
including the ones that go against CtxPack.

## Research question

After K compaction cycles, does a coding agent still know what it decided,
what it must not do, and what the current values of revised settings are —
and at what token cost?

## Design

Seeded synthetic sessions with **planted facts** (the generator is
`planted_session_gen.py`; manifests carry ground truth):

- N=40 planted facts per session: 15 decisions (5 of which are revised
  2–3× — the final value is the graded answer), 10 constraints (negation-
  bearing), 10 exact literals (SHAs/IDs/versions), 5 failed approaches.
- Filler: realistic tool-call traffic between plants (the interference
  medium), generated deterministically per seed.
- Drive **real Claude Code** headless with `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`
  lowered to force K = 1, 2, 3, 4, 5 compaction cycles.
- After each cycle: probe recall (all 40 facts, exact/contains rule
  grading) and **adherence** (present an opportunity to violate each
  planted constraint; a violation is graded by deterministic action
  inspection, ConstraintRot-style).

## Arms (all six mandatory in every run)

1. `native` — compaction only (today's default)
2. `claudemd` — compaction + hand-curated CLAUDE.md notes
3. `grep` — compaction + Grep/Read over the retained raw transcript
   (the null hypothesis; if ctx does not beat this on recall OR tokens,
   the format adds nothing over a file-retention convention)
4. `llm-memory` — compaction + LLM-summary memory file (Mem0-style)
5. `ctx` — compaction + CtxPack hooks (gists + read path)
6. `oracle` — full history, no compaction (ceiling)

## Metrics (headline first)

- **DR@K** — decision recall at K compactions: fraction of planted
  decisions (final values for revised ones) correctly recalled after K
  cycles. Survival curve over K. Implementation: `drk.py`.
- **CV@K** — constraint-violation rate at K (adherence, not just recall).
- **LF@K** — literal fidelity: exact-match recall of planted identifiers;
  a *plausible-but-wrong* identifier counts as an error of the worst
  class and is reported separately.
- **Tokens-per-correct-answer** per arm (full-loop accounting: context +
  probe + answer).

## Statistical plan

- n ≥ 5 seeds per (arm, K) cell; probes graded by deterministic rules
  (exact / distinctive-phrase). LLM judge is SECONDARY and reported
  separately if used at all.
- Binomial 95% CIs per cell (Wilson); arm comparisons via McNemar on
  paired probes (same seed, same probe, different arm).
- No result is reported without its CI. No selective seed reporting:
  every seed run is published in the raw JSONL.

## Decision rules (pre-committed)

- **Claim supported** iff ctx DR@5 exceeds native by ≥ 20pp AND the
  McNemar p < 0.05 across seeds.
- **Grep rule**: if ctx does not beat `grep` on DR@5 **or** on
  tokens-per-correct (≤ 50%), we publish that result and reposition the
  project's claims accordingly — determinism/provenance/versioning only,
  no recall-superiority claims.
- **Kill criterion**: if ctx DR@5 < native DR@5 (memory system worse than
  nothing), the pack-on-compact thesis is falsified for this workload;
  publish and stop claiming otherwise.
- Anchors from literature (context, not targets): compaction-only ≈
  60–70% retention after 3–4 cycles; constraint violations 0% → 30–59%
  post-compaction (ConstraintRot).

## Publication

The harness, generator seeds, per-probe raw results, and this document
ship together regardless of outcome. Results files are immutable
(versioned under `results/`, never overwritten).

## Status / deviations log

- 2026-07-04: pre-registration committed. Generator + DR@K metric
  implemented; the Claude Code driver (forced-compaction loop) is NOT
  yet built — no runs have occurred.
