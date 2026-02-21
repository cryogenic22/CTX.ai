# Golden Set for ctxpack Evaluation

Fixed corpus + fixed Q&A pairs for apples-to-apples comparison across versions.

## Structure

- `corpus/` — Source YAML entities, rules, and Markdown docs (~30-50K tokens)
- `questions.yaml` — 20 Q&A pairs graded by difficulty (easy/medium/hard)
- `expected/` — Frozen .ctx reference outputs
- `results/` — Versioned eval results (JSON logs)

## Methodology

1. Pack `corpus/` with ctxpack → .ctx L2 output
2. Run `questions.yaml` against compressed context via LLM
3. Grade answers against expected values
4. Compare with baselines: raw stuffing, naive truncation, hand-authored

## Planted Conflicts

- Q15: Customer retention (36 months) vs regulatory retention (7 years)
- Q20: Payment PII classification vs entity retention overlap
