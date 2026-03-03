"""Ablation experiments: isolate contribution of scope inference and salience ordering.

Experiment 3 (Reviewer 1 + 2): strict vs enriched mode → scope inference delta
Experiment 4 (Reviewer 2): scored vs random entity ordering → salience ordering delta

Also includes minified JSON/YAML baseline (Experiment 1, Reviewer 1 + 2).
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any, Optional

from .dotenv import load_dotenv
from .metrics.compression import count_tokens
from .metrics.cost import estimate_cost
from .metrics.fidelity import load_questions, measure_fidelity, _detect_provider
from .baselines.raw_stuffing import prepare_raw_context
from .baselines.minified import prepare_minified_context
from .baselines.structured_prompt import prepare_structured_prompt_context


def run_ablation_eval(
    golden_set_dir: str = "",
    *,
    provider: str = "",
    model: str = "",
    api_key: str = "",
    output_path: str = "",
) -> dict[str, Any]:
    """Run ablation experiments on the golden set.

    Variants tested:
    1. ctxpack-enriched (default) — includes inferred fields
    2. ctxpack-strict — suppresses inferred fields
    3. ctxpack-random-order — randomized entity ordering
    4. ctxpack-scored-order — salience-sorted ordering (same as default)
    5. raw-stuffing — full uncompressed baseline
    6. minified — whitespace-stripped baseline (Reviewer 1 + 2)
    7. structured-prompt — LLM-as-packer baseline (Reviewer 3)
    """
    load_dotenv()

    if not golden_set_dir:
        golden_set_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "golden_set",
        )

    corpus_dir = os.path.join(golden_set_dir, "corpus")
    questions_path = os.path.join(golden_set_dir, "questions.yaml")

    if not output_path:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "results", "ablation.json",
        )

    # Resolve provider
    if not provider or not api_key:
        detected_provider, detected_key, detected_model = _detect_provider()
        provider = provider or detected_provider
        api_key = api_key or detected_key
        model = model or detected_model
    eval_model = model or "claude-sonnet-4-20250514"

    questions = load_questions(questions_path)
    print(f"\nAblation Experiment")
    print(f"{'='*60}")
    print(f"  Model: {eval_model}")
    print(f"  Questions: {len(questions)}")
    print(f"  Provider: {provider}")

    from ctxpack.core.packer import pack
    from ctxpack.core.serializer import serialize

    results: dict[str, Any] = {
        "experiment": "ablation",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": eval_model,
        "question_count": len(questions),
        "variants": {},
    }

    # ── Variant 1: ctxpack-enriched (default) ──
    print(f"\n  [1/8] ctxpack-enriched (default)...", flush=True)
    pack_enriched = pack(corpus_dir, strict=False)
    ctx_enriched = serialize(pack_enriched.document)
    results["variants"]["ctxpack_enriched"] = _eval_variant(
        "ctxpack_enriched", ctx_enriched, questions,
        source_tokens=pack_enriched.source_token_count,
        model=eval_model, api_key=api_key, provider=provider,
    )

    # ── Variant 2: ctxpack-strict (no inferred fields) ──
    print(f"\n  [2/8] ctxpack-strict (no inferred)...", flush=True)
    pack_strict = pack(corpus_dir, strict=True)
    ctx_strict = serialize(pack_strict.document)
    results["variants"]["ctxpack_strict"] = _eval_variant(
        "ctxpack_strict", ctx_strict, questions,
        source_tokens=pack_strict.source_token_count,
        model=eval_model, api_key=api_key, provider=provider,
    )

    # ── Variant 3: ctxpack-random-order ──
    print(f"\n  [3/8] ctxpack-random-order...", flush=True)
    pack_random = pack(corpus_dir, randomize_order=True)
    ctx_random = serialize(pack_random.document)
    results["variants"]["ctxpack_random_order"] = _eval_variant(
        "ctxpack_random_order", ctx_random, questions,
        source_tokens=pack_random.source_token_count,
        model=eval_model, api_key=api_key, provider=provider,
    )

    # ── Variant 4: ctxpack-scored-order (same as enriched, explicit label) ──
    # Reuse enriched result to avoid redundant API calls
    results["variants"]["ctxpack_scored_order"] = results["variants"]["ctxpack_enriched"].copy()
    results["variants"]["ctxpack_scored_order"]["label"] = "ctxpack_scored_order"

    # ── Variant 5: raw stuffing ──
    print(f"\n  [4/8] raw-stuffing...", flush=True)
    raw_text = prepare_raw_context(corpus_dir)
    source_tokens = pack_enriched.source_token_count
    results["variants"]["raw_stuffing"] = _eval_variant(
        "raw_stuffing", raw_text, questions,
        source_tokens=source_tokens,
        model=eval_model, api_key=api_key, provider=provider,
    )

    # ── Variant 6: minified ──
    print(f"\n  [5/8] minified...", flush=True)
    minified_text = prepare_minified_context(corpus_dir)
    results["variants"]["minified"] = _eval_variant(
        "minified", minified_text, questions,
        source_tokens=source_tokens,
        model=eval_model, api_key=api_key, provider=provider,
    )

    # ── Variant 7: structured-prompt (LLM-as-packer) ──
    print(f"\n  [6/8] structured-prompt (LLM-as-packer)...", flush=True)
    if api_key:
        try:
            structured_text = prepare_structured_prompt_context(
                raw_text, target_tokens=count_tokens(ctx_enriched),
                model=eval_model, api_key=api_key, provider=provider,
            )
            if structured_text and not structured_text.startswith("(error"):
                results["variants"]["structured_prompt"] = _eval_variant(
                    "structured_prompt", structured_text, questions,
                    source_tokens=source_tokens,
                    model=eval_model, api_key=api_key, provider=provider,
                )
            else:
                print(f"    -> skipped (LLM error: {structured_text[:80]})")
        except Exception as e:
            print(f"    -> skipped (error: {e})")
    else:
        print(f"    -> skipped (no API key)")

    # ── Variant 8: ctxpack-bpe-optimized ──
    print(f"\n  [7/8] ctxpack-bpe-optimized...", flush=True)
    ctx_bpe_opt = serialize(pack_enriched.document, bpe_optimized=True)
    results["variants"]["ctxpack_bpe_optimized"] = _eval_variant(
        "ctxpack_bpe_optimized", ctx_bpe_opt, questions,
        source_tokens=pack_enriched.source_token_count,
        model=eval_model, api_key=api_key, provider=provider,
    )

    # ── Compute deltas ──
    print(f"\n  [8/8] Computing deltas...", flush=True)
    enriched_fid = results["variants"]["ctxpack_enriched"].get("fidelity", 0)
    strict_fid = results["variants"]["ctxpack_strict"].get("fidelity", 0)
    random_fid = results["variants"]["ctxpack_random_order"].get("fidelity", 0)
    minified_fid = results["variants"]["minified"].get("fidelity", 0)
    raw_fid = results["variants"]["raw_stuffing"].get("fidelity", 0)

    structured_fid = results["variants"].get("structured_prompt", {}).get("fidelity", 0)
    bpe_opt_fid = results["variants"].get("ctxpack_bpe_optimized", {}).get("fidelity", 0)

    results["deltas"] = {
        "scope_inference_delta": round(enriched_fid - strict_fid, 4),
        "salience_ordering_delta": round(enriched_fid - random_fid, 4),
        "ctxpack_vs_minified_delta": round(enriched_fid - minified_fid, 4),
        "ctxpack_vs_raw_delta": round(enriched_fid - raw_fid, 4),
        "ctxpack_vs_structured_prompt_delta": round(enriched_fid - structured_fid, 4) if structured_fid else None,
        "bpe_optimization_fidelity_delta": round(bpe_opt_fid - enriched_fid, 4) if bpe_opt_fid else None,
    }

    # Save results
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Print summary
    _print_ablation_summary(results)

    return results


def _eval_variant(
    label: str,
    context_text: str,
    questions: list[dict],
    *,
    source_tokens: int,
    model: str,
    api_key: str,
    provider: str,
) -> dict[str, Any]:
    """Evaluate a single variant: measure tokens, compression, fidelity."""
    ctx_tokens = count_tokens(context_text)
    cost = estimate_cost(ctx_tokens, model=model)

    result: dict[str, Any] = {
        "label": label,
        "tokens": ctx_tokens,
        "source_tokens": source_tokens,
        "ratio": f"{source_tokens / max(1, ctx_tokens):.1f}x",
        "cost": cost.to_dict()["cost_per_query"],
    }

    if api_key and questions:
        print(f"    Running fidelity ({len(questions)} Qs)...", flush=True)
        fidelity = measure_fidelity(
            questions, context_text,
            model=model, api_key=api_key, provider=provider,
        )
        result["fidelity"] = fidelity.score
        result["llm_judge_score"] = fidelity.llm_judge_score
        result["correct"] = fidelity.correct
        result["llm_judge_correct"] = fidelity.llm_judge_correct
        result["total"] = fidelity.total
        print(f"    -> fidelity={fidelity.score:.2f} judge={fidelity.llm_judge_score:.2f}")

    return result


def _print_ablation_summary(results: dict[str, Any]) -> None:
    """Print summary table."""
    print(f"\n{'='*70}")
    print(f"  ABLATION RESULTS — {results['model']}")
    print(f"{'='*70}")
    print(f"  {'Variant':<25} {'Tokens':>8} {'Ratio':>8} {'Fidelity':>10} {'Judge':>10}")
    print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*10} {'-'*10}")

    for name, v in results.get("variants", {}).items():
        tokens = v.get("tokens", 0)
        ratio = v.get("ratio", "N/A")
        fid = v.get("fidelity", None)
        judge = v.get("llm_judge_score", None)
        fid_str = f"{fid:.0%}" if fid is not None else "N/A"
        judge_str = f"{judge:.0%}" if judge is not None else "N/A"
        print(f"  {name:<25} {tokens:>8} {ratio:>8} {fid_str:>10} {judge_str:>10}")

    print()
    deltas = results.get("deltas", {})
    if deltas:
        print(f"  Deltas:")
        for k, v in deltas.items():
            sign = "+" if v > 0 else ""
            print(f"    {k}: {sign}{v:.1%}")
    print()


def save_ablation_results(results: dict[str, Any], output_path: str) -> str:
    """Save with timestamped log."""
    results_dir = os.path.dirname(output_path)
    os.makedirs(results_dir, exist_ok=True)

    model = results.get("model", "unknown").replace("/", "-").replace(" ", "-")

    # Save model-labeled results
    base, ext = os.path.splitext(output_path)
    labeled_path = f"{base}-{model}{ext}"
    with open(labeled_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Save generic copy
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Timestamped log
    logs_dir = os.path.join(results_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = results.get("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat())
    ts_safe = timestamp.replace(":", "-").replace("+", "p")[:19]
    log_path = os.path.join(logs_dir, f"{ts_safe}_ablation_{model}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return labeled_path


if __name__ == "__main__":
    results = run_ablation_eval()
    save_ablation_results(
        results,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "ablation.json"),
    )
