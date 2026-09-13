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
- 2026-07-04 (later, still before any scored run): driver built
  (`driver.py`, `probes.py`, `run_compactbench.py`). Operationalization
  decisions, recorded here per the deviations rule:
  - **Forcing mechanism** (reproducibility, not a metric change): on
    Claude Code 2.1.201, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` alone does
    not trigger proactive autocompact — when the context-window source
    is "auto" the check defers to a reactive path. The driver pins
    `CLAUDE_CODE_AUTO_COMPACT_WINDOW=100000` (env minimum), flipping
    the source to "env" so the pct override applies. Verified live:
    trigger=auto boundary at pre=64,984 → post=2,099 tokens.
  - **Probe batching (default)**: a cell's 40 recall probes are asked
    in ONE fork invocation ('A<n>: ...' answer sheet). Per-probe grades
    and McNemar pairing are unchanged; unparsed answers are graded
    incorrect and flagged `parse_failure`. `--probe-mode single`
    preserves the one-call-per-probe form (~4x cost). Deviation
    motive: full-run cost ~$100 -> ~$25.
  - **Adherence grading**: a violation is a forbidden action the probe
    fork *attempted* (tool_use records in its transcript;
    permission-denied attempts count), or — only when no action was
    attempted — a reply with no rule-citation/refusal marker (text
    fallback). Strictness is identical across arms, so paired
    comparisons are unaffected. This adapts "deterministic action
    inspection" to headless auto-deny.
  - **claudemd arm**: CLAUDE.md carries the 10 planted ground rules
    verbatim (what a diligent team pins); no decisions/literals.
  - **llm-memory arm**: memory built once per seed by the model
    reading the full pre-compaction transcript, delivered via CLAUDE.md
    (the only auto-loaded file). Generous vs. real incremental systems
    — biases against ctx, acceptable.
  - **oracle arm**: never compacts; the same deterministic filler is
    appended per pseudo-cycle so token position/interference match.
  - **Generator fixes** (bytes changed, zero runs existed): filler
    emits tool_use/tool_result PAIRS (a dangling tool_use is rejected
    by the API on resume), session IDs are seed-derived UUIDs (Claude
    Code requires UUID session ids), and services/approaches are
    sampled without replacement so the 40 plants map 1:1 to 40
    unambiguous probes.
  - **Probe forks do not checkpoint**: ctx-arm probe invocations set
    `CTXPACK_HOOK_SKIP=stop,session-end,pre-compact` so observing the
    session cannot overwrite its ledger; gist injection (session-start)
    stays live.
- 2026-07-04 (post-smoke review; still zero scored runs). The K=2
  native+ctx smoke ran end-to-end (results committed, smoke-scale, not
  citable). Parameter and reporting decisions fixed BEFORE the scored
  run:
  - **pct=20 for any scored run.** pct=8 (a ~5.4K-token threshold)
    collapsed native decision recall to 0.0 by K=2 — an adversarial
    stress setting that invites a "benchmark-induced failure" critique.
    pct=8 remains available as a labelled stress mode only.
  - **Per-seed DR@K** is reported alongside the pooled curve and the
    McNemar comparisons (pooled-only pairing invites a pseudoreplication
    critique; one-seed b=15/c=0 is a smoke signal, not evidence).
  - **Cost accounting**: reports carry an explicit
    probe/compaction/memory-build cost split. The committed smoke JSON
    over-counted probe cost ~40x (batched call cost duplicated onto
    every probe row) — file left immutable, code fixed forward; the
    corrected smoke figures are ~$0.77 (native) / ~$1.01 (ctx).
  - **Run isolation**: scored runs use a run-scoped CLAUDE_CONFIG_DIR
    (credentials seeded, empty projects store; verified: no writes to
    the real ~/.claude) and a clean git worktree, after a concurrent
    session committed to the repo mid-smoke.
  - **Evidence ladder / sequential stopping**: a cheap sentinel
    (2 seeds x K=3 x native/ctx/grep, adherence on) gates the spend on
    the full six-arm run. If ctx is not clearly ahead of grep at the
    sentinel, we stop and reposition claims per the pre-committed grep
    rule instead of buying more data. The six-arm design itself is
    unchanged and remains the citable artifact.
