# CtxPack session-memory scorecard

_Generated 2026-08-07T19:09:16+00:00 · schema ctxpack-scorecard/v2_

> **Measurement class: observational.** These numbers support adoption and token-economics claims only. Accuracy claims come from the resume-probe evals; causal claims from CompactBench.

## Cohort

| Metric | Value |
| --- | --- |
| Repos active | 6 / 7 |
| Sessions banked | 278 |
| Turns packed | 49,459 |
| Decisions / constraints / dead ends | 1101 / 89 / 120 |
| Raw-fallback rate | **45%** (54/119 fell back) |
| Sessions with explicit recall | 17 |
| Sessions with zero explicit recall | 260 |
| ...of which a gist was emitted | 8 |
| ...hook ran, emitted empty (per receipt) | 0 |
| ...emission attempt failed (per receipt) | 0 |
| ...emission unmeasured (no receipt) | 252 |
| Sessions using transcript fallback | 14 |
| Sessions with no read telemetry | 1 |
| Startup gists emitted to hook stdout / attempted | 52 / 52 |

Raw-fallback rate = raw-transcript greps ÷ (ledger reads + greps); lower is better — the earliest honest signal of whether the ledger earns its keep.

**Pull vs push.** Explicit recall counts deliberate queries (`ctx/session_*`, `ctxpack session`) only; the SessionStart hook is the push path and is not counted. Zero-recall sessions are split by what their emission receipts prove: gist emitted, hook ran empty, attempt failed, or unmeasured. A session without a receipt is unmeasured — absence of a receipt is never read as “no gist was emitted”.

**Emission is not use.** The push-path figures measure exactly one thing: bytes successfully written to the SessionStart hook's stdout. Whether the harness forwarded them, whether they entered the model's context, whether the model read them and whether they helped are four further steps, all unmeasured. No figure on this page may be described as delivery to an agent, consumption, use or value. What the read path is measured to be is *uncalled*; what the push path is measured to be is *emitted*. Any claim beyond those two needs the flat-file arm, not this table. Sessions with no telemetry were packed before these counters existed and are excluded from the denominator: unmeasured is not the same as unused.

### Incidents (agent-reported)

- saved: 20
- missed: 7
- native-better: 2
- wrong: 2
- stale: 1

## By repo

| Repo | Status | Sessions | Turns | Decisions | Constraints / dead ends | Ledger reads | Greps | Fallback |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CTX_mod | active | 11 | 9,342 | 155 | 52 / 4 | 31 | 21 | 40% (21/52) |
| market_zero | active | 4 | 5,182 | 85 | 1 / 6 | 13 | 10 | 44% (10/23) |
| KP_SDLC | active | 2 | 1,826 | 30 | 1 / 9 | 6 | 5 | 46% (5/11) |
| Scriptiva_SCA | active | 247 | 11,578 | 547 | 6 / 76 | 6 | 8 | 57% (8/14) |
| setu | active | 12 | 17,328 | 240 | 19 / 24 | 8 | 10 | 56% (10/18) |
| WhynotFamous | active | 2 | 4,203 | 44 | 10 / 1 | 1 | 0 | 0% (0/1) |
| OntoWiz | external unmeasured | — | — | — | — | — | — | — |

_Deterministic Layer-1 telemetry from each repo's committed `.claude/ctx/checkpoints.jsonl` — no content leaves the repo, only counts._
