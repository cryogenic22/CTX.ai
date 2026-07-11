# Claims Ledger

Every public numerical/comparative claim, traced to an immutable artifact.
Machine-checked by `scripts/check_claims.py` (CI via
`tests/test_claims_gate.py`). Execution-plan task **W1-2**
(`docs/execution-plan-2026-07.md`); enforcement level per owner decision
2026-07-11: **CI-fails** on numerical/comparative claims and retracted-claim
reappearance; **warns** on uncovered qualitative positioning.

Scope (initial): `README.md` is gated line-by-line; retracted signatures
are scanned across `README.md`, `paper/*.md`, and `docs/*.md` (excluding
this file and the `notes.md` dialogue log). Extending line-gating to the
papers is a follow-up once week-1 false-positive data is in (kill
condition: >3 false positives → narrow patterns first).

Statuses: `measured` (artifact required) · `directional`
(artifact required; underpowered or partial accounting — say so) ·
`external` (someone else's published number, cited not claimed) ·
`retracted` (must never reappear outside retraction context).

## Claims

| ID | Claim (canonical) | Status | Covers | Artifact | Basis | Stamp |
|---|---|---|---|---|---|---|
| C1 | Hydrated fidelity 86.7% vs raw stuffing 83.3% (+3.4pp) on Opus-class; ties embedding-RAG | measured | 86.7%, 83.3% | `ctxpack/benchmarks/results/definitive_eval.json` | synthetic 92K-BPE corpus, n=30 self-authored Qs, ±13–18pp CI — directional not definitive | 2026-06, Opus-class answerer, GPT-4o judge |
| C2 | ~24x fewer context tokens per query vs raw stuffing (full-loop accounting pending; likely 10–15x) | directional | 24x, 10–15x | `ctxpack/benchmarks/results/definitive_eval.json` | per-query context accounting only; full-loop audit outstanding (§5.2 gate before public use) | 2026-06 |
| C3 | n=30 fidelity results carry a ±13–18pp confidence interval | measured | ±13–18pp | `paper/status-and-value-v0.5.md` | self-computed CI on C1's sample | 2026-07 |
| C4 | Agentic NIAH: ~400 BPE per query flat; 166x less context than raw stuffing at 64K | measured | 166x | `ctxpack/benchmarks/agentic/results/agentic_niah-claude-sonnet-4-6.json` | synthetic coding-agent trajectories, 12 probes incl. updated-value + adversarial | 2026-07, Sonnet answerer, GPT-4o judge |
| C5 | GraphWalks-adapted: deterministic traversal exact — F1 = 1.000 at every scale; packing preserved 100% of edges | measured | F1 = 1.000, 100% of edges | `ctxpack/benchmarks/agentic/results/graphwalks-claude-sonnet-4-6.json` | synthetic service-dependency graphs, exact set-F1 | 2026-07 |
| C6 | Structured-signal extraction measured 100% on the convention; free-prose decision mining ~0% recall | directional | 100% on the convention, ~0% recall | `ctxpack/benchmarks/agentic/results/resume-probe-CTX_mod-recall-full-20260706T000341+0000.json` | real dogfood ledger, small n; needs a dedicated extraction-recall artifact | 2026-07 |
| C7 | On Haiku-class models raw stuffing wins (by 6.7pp); sub-Haiku routers collapse (GPT-4o-mini 20%) | measured | raw stuffing wins, raw stuffing can win | `paper/status-and-value-v0.5.md` | same corpus as C1; negative result, disclosed | 2026-06 |
| C8 | CompactBench sentinel: ctx beat native within-run; ctx-vs-grep p=0.25 N.S. — **no superiority claim**; 2 seeds, clustered probes, ceiling-limited | measured | p=0.25 | `ctxpack/benchmarks/compactbench/results/compactbench-sentinel-20260704T205254.json` | 2 seeds × K=3, pct=20; probes clustered within trajectories — NOT independent | 2026-07-04, haiku |

## External citations (their numbers, not ours)

| ID | Reference | Status | Covers |
|---|---|---|---|
| E1 | Letta filesystem baseline: grep-over-files 74% on LoCoMo | external | 74% on LoCoMo |
| E2 | ConstraintRot (arXiv 2606.22528): violations 0% → 30–59% after compaction | external | 30–59% |
| E3 | ACE (ICLR 2026): LLM-rewrite memory collapse 18,282 → 122 tokens | external | 18,282 |
| E4 | Wang & Sun (ICML 2025): updated-value recall degrades with update count | external | log-linearly |

## Retracted (must never reappear as claims)

| ID | Claim | Signatures | Where retracted |
|---|---|---|---|
| R1 | "26x cost reduction" | 26x | `paper/status-and-value-v0.5.md` |
| R2 | "~93% fidelity retention" | 93% retention, 93% fidelity | `paper/status-and-value-v0.5.md` |
| R3 | "7pp fidelity gap" (wrong direction) | 7pp gap | `paper/status-and-value-v0.5.md` |

## Change protocol

New public number → add a row **in the same PR**, linking the immutable
artifact (new versioned file under `ctxpack/benchmarks/**/results/`).
A claim losing its evidence (re-run flips, artifact superseded) → status
moves to `retracted`, signatures added, prose removed. The gate makes the
README physically unable to carry an unledgered number.
