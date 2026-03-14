# Eval Pipeline Fixes Required Before Whitepaper

## CRITICAL
1. **Add retry logic with exponential backoff** to all API calls (_ask_anthropic, _ask_openai, _ask_anthropic_raw, _ask_openai_raw). Rate-limited calls must retry, not silently fail as "INCORRECT."
2. **Use cross-model judging.** Self-judging with the same rate-limited model is unreliable. Use GPT-4o to judge Claude Opus answers (or vice versa). Keys for both are in .env.
3. **Equalize eval pipelines.** Both arms must use the same call pattern — either both bulk-then-judge, or both interleaved. Currently raw uses bulk and hydration uses interleaved, creating a rate-limit asymmetry.

## SEVERE
4. **Increase max_tokens to 512+.** 200 tokens is insufficient for complex multi-entity answers at 92K context. Truncated answers are penalized unfairly.
5. **Add error detection in judge.** If the judge response starts with "(error:" it should be flagged as JUDGE_FAILED, not scored as INCORRECT.

## MODERATE
6. **Increase to 100+ questions.** 30 questions gives ±18pp margin at 95% CI. Need 100+ for publishable statistical significance.
7. **Add RAG baseline.** Compare against standard embedding+vector-search retrieval, not just raw stuffing.
8. **Test on real (non-synthetic) corpus.** Synthetic YAML with perfect structure is best-case for CtxPack.
9. **Report full grading matrix.** Show both rule AND judge scores for both arms. Don't cherry-pick.

## MINOR
10. **Include routing call cost in hydration total.** Currently undercounts by ~40%.
11. **Fix RT4 red team check.** Should flag suspiciously low raw scores as anomalous, not just check direction.
