"""Scaling experiment runner.

Runs the eval across multiple corpus sizes and collects results
for plotting compression ratio and fidelity curves.
"""

from __future__ import annotations

import json
import os
import random
import datetime
from typing import Any

from ..dotenv import load_dotenv
from ..metrics.compression import count_corpus_tokens, count_tokens, measure_compression
from ..metrics.cost import estimate_cost
from ..metrics.fidelity import load_questions, measure_fidelity, _detect_provider
from ..baselines.raw_stuffing import prepare_raw_context
from ..baselines.naive_summary import prepare_naive_context
from ..baselines.llm_summary import prepare_llm_summary
from .corpus_generator import generate_all_scaling_corpora


def run_scaling_eval(
    base_dir: str,
    *,
    max_questions_per_scale: int = 30,
    regenerate: bool = False,
    skip_fidelity: bool = False,
    seed: int = 42,
) -> dict[str, Any]:
    """Run eval at each corpus scale and collect results.

    Args:
        base_dir: Base directory for scaling corpora.
        max_questions_per_scale: Cap questions per scale to control API cost.
        regenerate: If True, regenerate corpora even if they exist.
        skip_fidelity: If True, skip LLM API calls (compression-only mode).
        seed: Random seed for question sampling.

    Returns:
        Results dict with per-scale metrics.
    """
    load_dotenv()

    # Generate corpora if needed
    scale_dirs = [
        os.path.join(base_dir, f"scale_{t}")
        for t in [1000, 5000, 20000, 50000]
    ]
    if regenerate or not all(os.path.isdir(d) for d in scale_dirs):
        generate_all_scaling_corpora(base_dir)

    # Detect provider
    provider, api_key, detected_model = _detect_provider()
    if skip_fidelity:
        api_key = ""
    eval_model = detected_model or "claude-sonnet-4-6"

    rng = random.Random(seed)

    results: dict[str, Any] = {
        "experiment": "scaling_curve",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": eval_model,
        "max_questions_per_scale": max_questions_per_scale,
        "scales": [],
    }

    # Also include the golden set as the smallest data point
    golden_set_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "golden_set"
    )

    all_scales = [
        ("golden_set", golden_set_path),
    ] + [
        (f"scale_{t}", os.path.join(base_dir, f"scale_{t}"))
        for t in [1000, 5000, 20000, 50000]
    ]

    for scale_name, scale_dir in all_scales:
        corpus_dir = os.path.join(scale_dir, "corpus")
        if not os.path.isdir(corpus_dir):
            continue

        print(f"\n{'='*50}")
        print(f"  Scale: {scale_name}")
        print(f"{'='*50}")

        # Pack
        from ctxpack.core.packer import pack
        from ctxpack.core.serializer import serialize

        pack_result = pack(corpus_dir)
        ctx_text = serialize(pack_result.document)
        source_tokens = count_corpus_tokens(corpus_dir)
        ctx_tokens = count_tokens(ctx_text)

        print(f"  Source: {source_tokens} tokens → Compressed: {ctx_tokens} tokens "
              f"({source_tokens/max(1,ctx_tokens):.1f}x)")

        # Load questions
        questions_path = os.path.join(scale_dir, "questions.yaml")
        questions = []
        if os.path.exists(questions_path):
            questions = load_questions(questions_path)

        # Sample questions if too many
        if len(questions) > max_questions_per_scale:
            # Stratified sample: keep difficulty distribution
            by_diff: dict[str, list] = {}
            for q in questions:
                by_diff.setdefault(q.get("difficulty", "medium"), []).append(q)

            sampled = []
            for diff, qs in by_diff.items():
                n = max(2, int(max_questions_per_scale * len(qs) / len(questions)))
                rng.shuffle(qs)
                sampled.extend(qs[:n])

            # Trim to exact count
            rng.shuffle(sampled)
            questions = sampled[:max_questions_per_scale]

        print(f"  Questions: {len(questions)}")

        scale_result: dict[str, Any] = {
            "name": scale_name,
            "source_tokens": source_tokens,
            "ctx_tokens": ctx_tokens,
            "compression_ratio": round(source_tokens / max(1, ctx_tokens), 2),
            "entity_count": len(pack_result.document.body),
            "question_count": len(questions),
            "baselines": {},
        }

        # ── ctxpack L2 ──
        ctx_cost = estimate_cost(ctx_tokens, model=eval_model)
        ctx_result: dict[str, Any] = {
            "tokens": ctx_tokens,
            "ratio": f"{source_tokens/max(1,ctx_tokens):.1f}x",
            "cost": ctx_cost.to_dict()["cost_per_query"],
        }
        if api_key and questions:
            print(f"  Running fidelity: ctxpack_l2 ({len(questions)} Qs)...", flush=True)
            fidelity = measure_fidelity(
                questions, ctx_text,
                model=eval_model, api_key=api_key, provider=provider,
            )
            ctx_result["fidelity"] = fidelity.score
            ctx_result["llm_judge_score"] = fidelity.llm_judge_score
            print(f"    → fidelity={fidelity.score:.2f} judge={fidelity.llm_judge_score:.2f}")
        scale_result["baselines"]["ctxpack_l2"] = ctx_result

        # ── Raw stuffing ──
        raw_text = prepare_raw_context(corpus_dir)
        raw_tokens = count_tokens(raw_text)
        raw_cost = estimate_cost(raw_tokens, model=eval_model)
        raw_result: dict[str, Any] = {
            "tokens": raw_tokens,
            "ratio": "1x",
            "cost": raw_cost.to_dict()["cost_per_query"],
        }
        if api_key and questions:
            print(f"  Running fidelity: raw_stuffing ({len(questions)} Qs)...", flush=True)
            fidelity = measure_fidelity(
                questions, raw_text,
                model=eval_model, api_key=api_key, provider=provider,
            )
            raw_result["fidelity"] = fidelity.score
            raw_result["llm_judge_score"] = fidelity.llm_judge_score
            print(f"    → fidelity={fidelity.score:.2f} judge={fidelity.llm_judge_score:.2f}")
        scale_result["baselines"]["raw_stuffing"] = raw_result

        # ── Naive truncation ──
        naive_text = prepare_naive_context(raw_text, ctx_tokens)
        naive_tokens = count_tokens(naive_text)
        naive_cost = estimate_cost(naive_tokens, model=eval_model)
        naive_result: dict[str, Any] = {
            "tokens": naive_tokens,
            "ratio": f"{source_tokens/max(1,naive_tokens):.1f}x",
            "cost": naive_cost.to_dict()["cost_per_query"],
        }
        if api_key and questions:
            print(f"  Running fidelity: naive_truncation ({len(questions)} Qs)...", flush=True)
            fidelity = measure_fidelity(
                questions, naive_text,
                model=eval_model, api_key=api_key, provider=provider,
            )
            naive_result["fidelity"] = fidelity.score
            naive_result["llm_judge_score"] = fidelity.llm_judge_score
            print(f"    → fidelity={fidelity.score:.2f} judge={fidelity.llm_judge_score:.2f}")
        scale_result["baselines"]["naive_truncation"] = naive_result

        # ── LLM summary (only if API key and not too expensive) ──
        if api_key and questions and source_tokens < 25000:
            print(f"  Running: LLM summary generation...", flush=True)
            llm_text = prepare_llm_summary(
                raw_text, ctx_tokens,
                model=eval_model, api_key=api_key, provider=provider,
            )
            llm_tokens = count_tokens(llm_text)
            llm_cost = estimate_cost(llm_tokens, model=eval_model)
            llm_result: dict[str, Any] = {
                "tokens": llm_tokens,
                "ratio": f"{source_tokens/max(1,llm_tokens):.1f}x",
                "cost": llm_cost.to_dict()["cost_per_query"],
            }
            print(f"  Running fidelity: llm_summary ({len(questions)} Qs)...", flush=True)
            fidelity = measure_fidelity(
                questions, llm_text,
                model=eval_model, api_key=api_key, provider=provider,
            )
            llm_result["fidelity"] = fidelity.score
            llm_result["llm_judge_score"] = fidelity.llm_judge_score
            print(f"    → fidelity={fidelity.score:.2f} judge={fidelity.llm_judge_score:.2f}")
            scale_result["baselines"]["llm_summary"] = llm_result

        results["scales"].append(scale_result)

    return results


def save_scaling_results(results: dict[str, Any], output_path: str) -> str:
    """Save scaling results to JSON. Also saves timestamped raw log."""
    results_dir = os.path.dirname(output_path)
    os.makedirs(results_dir, exist_ok=True)

    # Determine model label
    model = results.get("model", "unknown").replace("/", "-").replace(" ", "-")

    # Save model-labeled results
    base, ext = os.path.splitext(output_path)
    labeled_path = f"{base}-{model}{ext}"
    with open(labeled_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Save generic (latest) copy
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Save timestamped raw log for provenance
    logs_dir = os.path.join(results_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = results.get("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat())
    ts_safe = timestamp.replace(":", "-").replace("+", "p")[:19]
    log_entry = {
        "log_type": "scaling_run",
        "timestamp": timestamp,
        "model": model,
        "provenance": {
            "tool": "ctxpack scaling",
            "run_by": "automated",
            "platform": os.name,
        },
        "results": results,
    }
    log_path = os.path.join(logs_dir, f"{ts_safe}_{model}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_entry, f, indent=2)

    return labeled_path


def print_scaling_summary(results: dict[str, Any]) -> None:
    """Print a summary table of scaling results."""
    print(f"\n{'='*80}")
    print(f"  SCALING CURVE RESULTS")
    print(f"{'='*80}")
    print(f"  {'Scale':<15} {'Source':>8} {'CTX':>8} {'Ratio':>8} "
          f"{'ctxpack':>10} {'raw':>10} {'naive':>10} {'llm_sum':>10}")
    print(f"  {'-'*15} {'-'*8} {'-'*8} {'-'*8} "
          f"{'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    for s in results.get("scales", []):
        name = s["name"]
        src = s["source_tokens"]
        ctx = s["ctx_tokens"]
        ratio = f"{s['compression_ratio']:.1f}x"

        def _fid(baseline: str) -> str:
            bl = s.get("baselines", {}).get(baseline, {})
            f = bl.get("fidelity")
            if f is not None:
                return f"{f:.0%}"
            return "N/A"

        print(f"  {name:<15} {src:>8} {ctx:>8} {ratio:>8} "
              f"{_fid('ctxpack_l2'):>10} {_fid('raw_stuffing'):>10} "
              f"{_fid('naive_truncation'):>10} {_fid('llm_summary'):>10}")

    print()
