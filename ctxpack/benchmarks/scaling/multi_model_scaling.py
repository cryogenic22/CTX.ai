"""Multi-model scaling evaluation.

Runs scaling eval across 5 models from 3 ecosystems (Anthropic, OpenAI, Google)
to validate cross-model fidelity at scale for the whitepaper.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

# Allow running as a script
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from ctxpack.benchmarks.dotenv import load_dotenv
from ctxpack.benchmarks.scaling.scaling_runner import (
    run_scaling_eval,
    save_scaling_results,
    print_scaling_summary,
)

# ── Model configurations ──
# Each entry: (label, provider, model_id, api_key_env)
MODEL_CONFIGS = [
    ("claude-sonnet-4.5", "anthropic", "claude-sonnet-4-5-20250929", "ANTHROPIC_API_KEY"),
    ("claude-haiku-4.5", "anthropic", "claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY"),
    ("o4-mini", "openai", "o4-mini", "OPENAI_API_KEY"),
    ("gpt-5.2", "openai", "gpt-5.2", "OPENAI_API_KEY"),
    ("gemini-2.5-pro", "google", "gemini-2.5-pro", "GOOGLE_API_KEY"),
]


def run_multi_model_scaling(
    base_dir: str,
    *,
    models: list[tuple[str, str, str, str]] | None = None,
    max_questions_per_scale: int = 25,
    max_scale: int = 0,
    seed: int = 42,
) -> dict[str, Any]:
    """Run scaling eval across multiple models.

    Args:
        base_dir: Base directory for scaling corpora.
        models: List of (label, provider, model_id, api_key_env) tuples.
            Defaults to MODEL_CONFIGS.
        max_questions_per_scale: Cap questions per scale to control API cost.
        max_scale: If > 0, only run scales up to this token count.
        seed: Random seed for question sampling.

    Returns:
        Combined results dict with per-model scaling curves.
    """
    load_dotenv()

    if models is None:
        models = MODEL_CONFIGS

    combined: dict[str, Any] = {
        "experiment": "multi_model_scaling",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models_requested": [m[0] for m in models],
        "max_questions_per_scale": max_questions_per_scale,
        "model_results": {},
        "skipped": [],
    }

    for label, provider, model_id, key_env in models:
        api_key = os.environ.get(key_env, "")
        if not api_key:
            print(f"\n  SKIP: {label} — {key_env} not set")
            combined["skipped"].append({"model": label, "reason": f"{key_env} not set"})
            continue

        print(f"\n{'#'*60}")
        print(f"  MODEL: {label} ({model_id})")
        print(f"  Provider: {provider}")
        print(f"{'#'*60}")

        t0 = time.perf_counter()

        results = run_scaling_eval(
            base_dir,
            max_questions_per_scale=max_questions_per_scale,
            regenerate=False,
            skip_fidelity=False,
            seed=seed,
            max_scale=max_scale,
            provider=provider,
            model=model_id,
            api_key=api_key,
        )

        elapsed = time.perf_counter() - t0
        results["elapsed_s"] = round(elapsed, 1)

        # Save individual model results
        results_dir = os.path.join(base_dir, "results")
        save_scaling_results(results, os.path.join(results_dir, "scaling_curve.json"))

        print_scaling_summary(results)

        combined["model_results"][label] = results

    return combined


def save_multi_model_results(results: dict[str, Any], output_path: str) -> str:
    """Save combined multi-model results to JSON."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Also save timestamped log
    logs_dir = os.path.join(os.path.dirname(output_path), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    ts = results.get("timestamp", time.strftime("%Y-%m-%dT%H-%M-%S"))
    ts_safe = ts.replace(":", "-").replace("+", "p")[:19]
    log_path = os.path.join(logs_dir, f"{ts_safe}_multi_model.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return output_path


def print_multi_model_summary(results: dict[str, Any]) -> None:
    """Print cross-model comparison table."""
    print(f"\n{'='*90}")
    print(f"  MULTI-MODEL SCALING COMPARISON")
    print(f"{'='*90}")

    # Collect all scale names across models
    all_scales: list[str] = []
    for model_data in results.get("model_results", {}).values():
        for s in model_data.get("scales", []):
            if s["name"] not in all_scales:
                all_scales.append(s["name"])

    # Header
    models = list(results.get("model_results", {}).keys())
    hdr = f"  {'Scale':<15}"
    for m in models:
        short = m[:12]
        hdr += f" {short:>12}"
    print(hdr)
    print(f"  {'-'*15}" + " " + ("-" * 12 + " ") * len(models))

    # Rows: one per scale, showing ctxpack_l2 fidelity
    for scale_name in all_scales:
        row = f"  {scale_name:<15}"
        for m in models:
            model_data = results["model_results"][m]
            scale_data = next(
                (s for s in model_data.get("scales", []) if s["name"] == scale_name),
                None,
            )
            if scale_data:
                fid = scale_data.get("baselines", {}).get("ctxpack_l2", {}).get("fidelity")
                if fid is not None:
                    row += f" {fid:>11.0%}"
                else:
                    row += f" {'N/A':>12}"
            else:
                row += f" {'—':>12}"
        print(row)

    # Skipped models
    skipped = results.get("skipped", [])
    if skipped:
        print(f"\n  Skipped: {', '.join(s['model'] for s in skipped)}")

    print()


def main():
    """CLI entry point for multi-model scaling eval."""
    import argparse

    parser = argparse.ArgumentParser(description="Multi-model scaling eval")
    parser.add_argument("--max-scale", type=int, default=0, help="Max scale (0=all)")
    parser.add_argument("--max-questions", type=int, default=25, help="Questions per scale")
    parser.add_argument("--models", nargs="*", help="Model labels to run (default: all)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))

    models = MODEL_CONFIGS
    if args.models:
        models = [m for m in MODEL_CONFIGS if m[0] in args.models]
        if not models:
            print(f"No matching models. Available: {[m[0] for m in MODEL_CONFIGS]}")
            return

    results = run_multi_model_scaling(
        base_dir,
        models=models,
        max_questions_per_scale=args.max_questions,
        max_scale=args.max_scale,
    )

    output_path = os.path.join(base_dir, "results", "multi_model_scaling.json")
    save_multi_model_results(results, output_path)
    print_multi_model_summary(results)
    print(f"Results saved: {output_path}")


if __name__ == "__main__":
    main()
