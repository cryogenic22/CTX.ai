---
title: ADR 0001 — Tokeniser choice for the code packer
date: 2026-05-12
status: Accepted
context: CP-002.5 (Code Packer v0)
---

# ADR 0001 — Pin `tiktoken` `cl100k_base` as the BPE measurement source of truth

## Context

The code packer makes load-bearing claims about token counts:

- RFC §5 caps catalog rows at "≤120 BPE per symbol."
- RFC §7.2 enforces a 4K BPE budget on depth-1 hydration.
- Eval §8.1 reports tokens/task vs. raw stuffing and Aider.
- The §8.6 determinism CI gate requires byte-identical pack output
  across runs — including BPE-derived budgeting decisions.

If "BPE token" means different things at different call sites, every
one of these claims drifts. So one helper, one encoding, no
side channels.

## Decision

Pin **`tiktoken` with encoding `cl100k_base`** as the single source
of truth for BPE counting in the code packer. Expose via
``count_bpe(s)`` at ``ctxpack.core.code.tokens``.

Every code-packer task that measures or budgets tokens (CP-010.3,
CP-027, CP-032, CP-036, downstream evals) imports `count_bpe` from
this module. Bypassing the helper to call `tiktoken` directly is a
review-blocking smell.

## Alternatives considered

| Option | Why not |
|---|---|
| `tiktoken` `o200k_base` (GPT-4o family) | Newer, but counts drift vs. existing repo measurements (whitepaper v3 uses cl100k). Adopting it now would force a re-run of every prior benchmark for a marginal accuracy gain on a single model family. |
| Anthropic's `client.messages.count_tokens(...)` | Closest to "true" Claude bills but requires an API call per measurement — adds rate-limit failure modes and ~50ms latency to anything that budgets tokens. Unworkable for a pack-time helper called thousands of times. |
| Anthropic local tokeniser (if/when shipped) | Not generally available offline as of CP-002.5; re-evaluate when it is. |
| `~4 chars/token` estimate (existing fallback in `cost.py`) | Cheap and dependency-free, but off by 10–30% on code with operators/punctuation. Unfit for budget enforcement. |
| Per-call encoding (no pin) | Defers the decision and lets drift in. Defeats the point of the helper. |

## Rationale for `cl100k_base`

1. **Already de facto in this repo.** `ctxpack/benchmarks/metrics/cost.py`
   uses cl100k via tiktoken for BPE counts. The v3 whitepaper's
   measurements are cl100k counts. Adopting the same encoding in the
   code packer means new measurements compose with existing ones
   without conversion.
2. **Offline and fast.** No network, no rate-limits, sub-ms per
   measurement after the first.
3. **Cross-model proxy.** Claude tokens correlate with cl100k within
   ~10–15% in our practice. Imperfect, but the discipline this ADR
   pins is "single source of truth," not "perfect alignment with
   Claude's bills."
4. **Frozen.** cl100k_base was finalised at the GPT-4 release in 2023
   and has not changed. Future `tiktoken` upgrades will not shift
   counts under us. The test suite pins five reference counts so
   even a tiktoken bug that silently changed cl100k tokens would be
   caught.

## Known risks and mitigations

- **Risk: cl100k drift vs. Claude's actual tokeniser.**
  Counts can over- or under-shoot Claude's billed tokens by ~10–15%.
  This will surface most acutely on the 4K BPE budget in CP-027:
  agents may receive slightly more or less code than the budget
  suggests.
  *Mitigation*: not solved at v0. Documented here so the v0.1
  evaluation can quantify the drift on real workloads. If the drift
  is large enough to matter, the ADR moves to Superseded and we
  swap encodings (or move to a local Claude tokeniser if available).

- **Risk: a future caller uses `tiktoken` directly and bypasses the
  pin.**
  *Mitigation*: code review + the `test_default_encoding_is_cl100k_base`
  test that asserts the module constant. Lint rule (future, optional):
  forbid `import tiktoken` outside `ctxpack/core/code/tokens.py` and
  `ctxpack/benchmarks/metrics/cost.py`.

## Override hook

`count_bpe(s, encoding=...)` accepts an optional encoding name so
researchers can A/B encodings without forking. The default and every
internal CTX caller stay on cl100k_base.

## Reference counts (frozen via tests)

| Reference string | cl100k_base BPE count |
|---|---|
| `"hello"` | 1 |
| `""` | 0 |
| `"def foo(x: int) -> str: return str(x)"` | 13 |
| `"def Δ_change(α: int, β: int) -> int: return β - α"` | 19 |
| Long generic-heavy signature (see test_long_generic_signature) | 61 |

If any of these change on a tiktoken upgrade, `tests/code/test_tokens.py`
will catch it before measurements drift in production.
