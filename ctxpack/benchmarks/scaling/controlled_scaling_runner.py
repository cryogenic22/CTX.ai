"""Controlled cross-scale eval: same 25 golden-set questions at every scale point.

Addresses Reviewer 2 concern: current scaling uses DIFFERENT questions per
scale, making it impossible to isolate the lost-in-the-middle effect.

Approach: embed golden-set corpus files into each scaling corpus directory,
re-pack the merged corpus, then run the fixed 25 golden-set questions at
every scale. This holds questions constant while varying context size.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
from typing import Any

from ..dotenv import load_dotenv
from ..metrics.compression import count_corpus_tokens, count_tokens
from ..metrics.cost import estimate_cost
from ..metrics.fidelity import load_questions, measure_fidelity, _detect_provider
from ..baselines.raw_stuffing import prepare_raw_context
from ..baselines.minified import prepare_minified_context
from .corpus_generator import generate_all_scaling_corpora


def _merge_corpus_dirs(golden_corpus_dir: str, scale_corpus_dir: str, merged_dir: str) -> None:
    """Copy golden-set corpus files and scaling corpus files into merged_dir."""
    os.makedirs(merged_dir, exist_ok=True)

    # Copy scaling corpus first (bulk content)
    if os.path.isdir(scale_corpus_dir):
        for item in os.listdir(scale_corpus_dir):
            src = os.path.join(scale_corpus_dir, item)
            dst = os.path.join(merged_dir, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    # Overlay golden-set corpus files (they take priority for entity names)
    # Put them in a golden/ subdirectory to avoid name collisions
    golden_subdir = os.path.join(merged_dir, "golden")
    os.makedirs(golden_subdir, exist_ok=True)
    for item in os.listdir(golden_corpus_dir):
        src = os.path.join(golden_corpus_dir, item)
        if item == "ctxpack.yaml":
            # Don't copy config — use the scaling one as base
            continue
        dst = os.path.join(golden_subdir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def run_controlled_scaling_eval(
    base_dir: str = "",
    *,
    regenerate: bool = False,
    provider: str = "",
    model: str = "",
    api_key: str = "",
    max_scale: int = 0,
    output_path: str = "",
) -> dict[str, Any]:
    """Run controlled scaling: same 25 Qs at each scale point.

    Scale points: golden_set (baseline), 1K, 5K, 20K, 37K merged corpora.
    Methods: ctxpack L2, raw stuffing, minified.
    """
    load_dotenv()

    benchmarks_dir = os.path.dirname(os.path.abspath(__file__))
    scaling_dir = os.path.join(benchmarks_dir)

    if not base_dir:
        base_dir = os.path.join(scaling_dir, "scaling_corpora")

    golden_set_dir = os.path.join(
        os.path.dirname(scaling_dir), "golden_set",
    )
    golden_corpus_dir = os.path.join(golden_set_dir, "corpus")
    questions_path = os.path.join(golden_set_dir, "questions.yaml")

    if not output_path:
        output_path = os.path.join(scaling_dir, "results", "controlled_scaling.json")

    # Resolve provider
    if not provider or not api_key:
        detected_provider, detected_key, detected_model = _detect_provider()
        provider = provider or detected_provider
        api_key = api_key or detected_key
        model = model or detected_model
    eval_model = model or "claude-sonnet-4-20250514"

    # Generate scaling corpora if needed
    all_scale_sizes = [1000, 5000, 20000, 50000]
    if max_scale > 0:
        all_scale_sizes = [s for s in all_scale_sizes if s <= max_scale]

    scale_dirs = [os.path.join(base_dir, f"scale_{t}") for t in all_scale_sizes]
    if regenerate or not all(os.path.isdir(os.path.join(d, "corpus")) for d in scale_dirs):
        generate_all_scaling_corpora(base_dir)

    # Load golden-set questions (fixed across all scales)
    questions = load_questions(questions_path)

    print(f"\nControlled Cross-Scale Experiment")
    print(f"{'='*60}")
    print(f"  Model: {eval_model}")
    print(f"  Fixed questions: {len(questions)} (golden set)")
    print(f"  Scale points: golden_set + {all_scale_sizes}")

    from ctxpack.core.packer import pack
    from ctxpack.core.serializer import serialize

    results: dict[str, Any] = {
        "experiment": "controlled_scaling",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": eval_model,
        "question_count": len(questions),
        "scales": [],
    }

    # ── Scale 0: golden set only (baseline) ──
    print(f"\n  {'='*50}")
    print(f"    Scale: golden_set (baseline)")
    print(f"  {'='*50}")

    pack_result = pack(golden_corpus_dir)
    ctx_text = serialize(pack_result.document)
    source_tokens = count_corpus_tokens(golden_corpus_dir)

    scale_result = _eval_scale(
        "golden_set", ctx_text, questions,
        source_tokens=source_tokens,
        corpus_dir=golden_corpus_dir,
        model=eval_model, api_key=api_key, provider=provider,
    )
    results["scales"].append(scale_result)

    # ── Scales 1-4: merged corpora ──
    for target_tokens in all_scale_sizes:
        scale_name = f"scale_{target_tokens}"
        scale_corpus_dir = os.path.join(base_dir, scale_name, "corpus")

        if not os.path.isdir(scale_corpus_dir):
            print(f"\n  Skipping {scale_name} (corpus not found)")
            continue

        print(f"\n  {'='*50}")
        print(f"    Scale: {scale_name}")
        print(f"  {'='*50}")

        # Create merged temp directory
        with tempfile.TemporaryDirectory(prefix=f"ctxpack_ctrl_{target_tokens}_") as merged_dir:
            _merge_corpus_dirs(golden_corpus_dir, scale_corpus_dir, merged_dir)

            # Pack merged corpus
            try:
                pack_result = pack(merged_dir)
                ctx_text = serialize(pack_result.document)
            except Exception as e:
                print(f"    Pack failed: {e}")
                continue

            source_tokens = count_corpus_tokens(merged_dir)

            scale_result = _eval_scale(
                scale_name, ctx_text, questions,
                source_tokens=source_tokens,
                corpus_dir=merged_dir,
                model=eval_model, api_key=api_key, provider=provider,
            )
            results["scales"].append(scale_result)

    # Save
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    _print_controlled_summary(results)

    return results


def _eval_scale(
    scale_name: str,
    ctx_text: str,
    questions: list[dict],
    *,
    source_tokens: int,
    corpus_dir: str,
    model: str,
    api_key: str,
    provider: str,
) -> dict[str, Any]:
    """Evaluate all methods at a single scale point."""
    ctx_tokens = count_tokens(ctx_text)
    print(f"    Source: {source_tokens} -> CTX: {ctx_tokens} ({source_tokens/max(1,ctx_tokens):.1f}x)")

    scale_result: dict[str, Any] = {
        "name": scale_name,
        "source_tokens": source_tokens,
        "ctx_tokens": ctx_tokens,
        "compression_ratio": round(source_tokens / max(1, ctx_tokens), 2),
        "methods": {},
    }

    # ── ctxpack L2 ──
    ctx_cost = estimate_cost(ctx_tokens, model=model)
    ctx_method: dict[str, Any] = {
        "tokens": ctx_tokens,
        "ratio": f"{source_tokens/max(1,ctx_tokens):.1f}x",
        "cost": ctx_cost.to_dict()["cost_per_query"],
    }
    if api_key and questions:
        print(f"    Running: ctxpack_l2 ({len(questions)} Qs)...", flush=True)
        fidelity = measure_fidelity(
            questions, ctx_text,
            model=model, api_key=api_key, provider=provider,
        )
        ctx_method["fidelity"] = fidelity.score
        ctx_method["llm_judge_score"] = fidelity.llm_judge_score
        print(f"      -> fidelity={fidelity.score:.2f} judge={fidelity.llm_judge_score:.2f}")
    scale_result["methods"]["ctxpack_l2"] = ctx_method

    # ── Raw stuffing ──
    raw_text = prepare_raw_context(corpus_dir)
    raw_tokens = count_tokens(raw_text)
    raw_cost = estimate_cost(raw_tokens, model=model)
    raw_method: dict[str, Any] = {
        "tokens": raw_tokens,
        "ratio": "1x",
        "cost": raw_cost.to_dict()["cost_per_query"],
    }
    if api_key and questions:
        print(f"    Running: raw_stuffing ({len(questions)} Qs)...", flush=True)
        fidelity = measure_fidelity(
            questions, raw_text,
            model=model, api_key=api_key, provider=provider,
        )
        raw_method["fidelity"] = fidelity.score
        raw_method["llm_judge_score"] = fidelity.llm_judge_score
        print(f"      -> fidelity={fidelity.score:.2f} judge={fidelity.llm_judge_score:.2f}")
    scale_result["methods"]["raw_stuffing"] = raw_method

    # ── Minified ──
    minified_text = prepare_minified_context(corpus_dir)
    min_tokens = count_tokens(minified_text)
    min_cost = estimate_cost(min_tokens, model=model)
    min_method: dict[str, Any] = {
        "tokens": min_tokens,
        "ratio": f"{source_tokens/max(1,min_tokens):.1f}x",
        "cost": min_cost.to_dict()["cost_per_query"],
    }
    if api_key and questions:
        print(f"    Running: minified ({len(questions)} Qs)...", flush=True)
        fidelity = measure_fidelity(
            questions, minified_text,
            model=model, api_key=api_key, provider=provider,
        )
        min_method["fidelity"] = fidelity.score
        min_method["llm_judge_score"] = fidelity.llm_judge_score
        print(f"      -> fidelity={fidelity.score:.2f} judge={fidelity.llm_judge_score:.2f}")
    scale_result["methods"]["minified"] = min_method

    return scale_result


def _print_controlled_summary(results: dict[str, Any]) -> None:
    """Print summary table."""
    print(f"\n{'='*80}")
    print(f"  CONTROLLED CROSS-SCALE RESULTS — {results['model']}")
    print(f"{'='*80}")
    print(f"  {'Scale':<15} {'Source':>8} {'CTX':>8} "
          f"{'ctxpack':>10} {'raw':>10} {'minified':>10}")
    print(f"  {'-'*15} {'-'*8} {'-'*8} "
          f"{'-'*10} {'-'*10} {'-'*10}")

    for s in results.get("scales", []):
        name = s["name"]
        src = s["source_tokens"]
        ctx = s["ctx_tokens"]

        def _fid(method: str) -> str:
            m = s.get("methods", {}).get(method, {})
            f = m.get("fidelity")
            return f"{f:.0%}" if f is not None else "N/A"

        print(f"  {name:<15} {src:>8} {ctx:>8} "
              f"{_fid('ctxpack_l2'):>10} {_fid('raw_stuffing'):>10} "
              f"{_fid('minified'):>10}")
    print()


def save_controlled_results(results: dict[str, Any], output_path: str) -> str:
    """Save with timestamped log."""
    results_dir = os.path.dirname(output_path)
    os.makedirs(results_dir, exist_ok=True)

    model = results.get("model", "unknown").replace("/", "-").replace(" ", "-")

    base, ext = os.path.splitext(output_path)
    labeled_path = f"{base}-{model}{ext}"
    with open(labeled_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Timestamped log
    logs_dir = os.path.join(results_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = results.get("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat())
    ts_safe = timestamp.replace(":", "-").replace("+", "p")[:19]
    log_path = os.path.join(logs_dir, f"{ts_safe}_controlled_{model}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return labeled_path


if __name__ == "__main__":
    results = run_controlled_scaling_eval()
    save_controlled_results(
        results,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "controlled_scaling.json"),
    )
