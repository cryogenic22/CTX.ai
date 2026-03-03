"""Real-world corpus evaluation runner.

Packs real-world corpora (FDA drug labels, Twilio API spec), then runs
fidelity eval across multiple models + baselines for whitepaper validation.
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
from ctxpack.benchmarks.metrics.compression import count_corpus_tokens, count_tokens
from ctxpack.benchmarks.metrics.cost import estimate_cost
from ctxpack.benchmarks.metrics.fidelity import load_questions, measure_fidelity, _detect_provider
from ctxpack.benchmarks.baselines.raw_stuffing import prepare_raw_context
from ctxpack.benchmarks.baselines.naive_summary import prepare_naive_context
from ctxpack.benchmarks.baselines.llm_summary import prepare_llm_summary
from ctxpack.core.packer import pack
from ctxpack.core.serializer import serialize

# ── Model configurations (same as multi_model_scaling) ──
MODEL_CONFIGS = [
    ("claude-sonnet-4.5", "anthropic", "claude-sonnet-4-5-20250929", "ANTHROPIC_API_KEY"),
    ("claude-haiku-4.5", "anthropic", "claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY"),
    ("o4-mini", "openai", "o4-mini", "OPENAI_API_KEY"),
    ("gpt-5.2", "openai", "gpt-5.2", "OPENAI_API_KEY"),
    ("gemini-2.5-pro", "google", "gemini-2.5-pro", "GOOGLE_API_KEY"),
]

# ── Corpus definitions ──
CORPORA = [
    {
        "name": "fda-drug-labels",
        "corpus_dir": os.path.join(os.path.dirname(__file__), "fda", "corpus"),
        "questions_path": os.path.join(os.path.dirname(__file__), "fda", "questions.yaml"),
        "results_dir": os.path.join(os.path.dirname(__file__), "fda", "results"),
    },
    {
        "name": "twilio-video-api",
        "corpus_dir": os.path.join(os.path.dirname(__file__), "twilio", "corpus"),
        "questions_path": os.path.join(os.path.dirname(__file__), "twilio", "questions.yaml"),
        "results_dir": os.path.join(os.path.dirname(__file__), "twilio", "results"),
    },
]


def eval_single_corpus(
    corpus_name: str,
    corpus_dir: str,
    questions_path: str,
    results_dir: str,
    *,
    models: list[tuple[str, str, str, str]] | None = None,
    max_questions: int = 25,
) -> dict[str, Any]:
    """Run full eval on a single real-world corpus.

    Returns:
        Results dict with per-model, per-baseline metrics.
    """
    load_dotenv()

    if models is None:
        models = MODEL_CONFIGS

    os.makedirs(results_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  CORPUS: {corpus_name}")
    print(f"{'='*60}")

    # Validate corpus exists
    if not os.path.isdir(corpus_dir):
        print(f"  ERROR: Corpus not found at {corpus_dir}")
        print(f"  Run the download script first.")
        return {"corpus": corpus_name, "error": "corpus_not_found"}

    # Validate questions exist
    if not os.path.isfile(questions_path):
        print(f"  ERROR: Questions not found at {questions_path}")
        print(f"  Author questions first (after downloading corpus).")
        return {"corpus": corpus_name, "error": "questions_not_found"}

    # Pack the corpus
    print(f"  Packing corpus...", end=" ", flush=True)
    pack_result = pack(corpus_dir)
    ctx_text = serialize(pack_result.document)
    source_tokens = count_corpus_tokens(corpus_dir)
    ctx_tokens = count_tokens(ctx_text)
    compression_ratio = round(source_tokens / max(1, ctx_tokens), 2)

    print(f"OK ({source_tokens} -> {ctx_tokens} tokens, {compression_ratio}x)")
    print(f"  Entities: {pack_result.entity_count}, Warnings: {pack_result.warning_count}")

    # Load questions
    questions = load_questions(questions_path)
    if len(questions) > max_questions:
        questions = questions[:max_questions]
    print(f"  Questions: {len(questions)}")

    # Prepare baselines
    raw_text = prepare_raw_context(corpus_dir)
    raw_tokens = count_tokens(raw_text)
    naive_text = prepare_naive_context(raw_text, ctx_tokens)
    naive_tokens = count_tokens(naive_text)

    results: dict[str, Any] = {
        "corpus": corpus_name,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_tokens": source_tokens,
        "ctx_tokens": ctx_tokens,
        "compression_ratio": compression_ratio,
        "entity_count": pack_result.entity_count,
        "question_count": len(questions),
        "model_results": {},
        "skipped": [],
    }

    for label, provider, model_id, key_env in models:
        api_key = os.environ.get(key_env, "")
        if not api_key:
            print(f"\n  SKIP: {label} — {key_env} not set")
            results["skipped"].append({"model": label, "reason": f"{key_env} not set"})
            continue

        print(f"\n  --- {label} ({model_id}) ---")

        model_result: dict[str, Any] = {
            "model": label,
            "model_id": model_id,
            "provider": provider,
            "baselines": {},
        }

        # ── ctxpack L2 ──
        print(f"    ctxpack_l2...", end=" ", flush=True)
        fidelity = measure_fidelity(
            questions, ctx_text,
            model=model_id, api_key=api_key, provider=provider,
        )
        ctx_cost = estimate_cost(ctx_tokens, model=model_id)
        model_result["baselines"]["ctxpack_l2"] = {
            "tokens": ctx_tokens,
            "ratio": f"{compression_ratio}x",
            "cost": ctx_cost.to_dict()["cost_per_query"],
            "fidelity": fidelity.score,
            "llm_judge_score": fidelity.llm_judge_score,
            "details": fidelity.to_dict(),
        }
        print(f"fidelity={fidelity.score:.0%} judge={fidelity.llm_judge_score:.0%}")

        # ── Raw stuffing ──
        print(f"    raw_stuffing...", end=" ", flush=True)
        fidelity = measure_fidelity(
            questions, raw_text,
            model=model_id, api_key=api_key, provider=provider,
        )
        raw_cost = estimate_cost(raw_tokens, model=model_id)
        model_result["baselines"]["raw_stuffing"] = {
            "tokens": raw_tokens,
            "ratio": "1x",
            "cost": raw_cost.to_dict()["cost_per_query"],
            "fidelity": fidelity.score,
            "llm_judge_score": fidelity.llm_judge_score,
        }
        print(f"fidelity={fidelity.score:.0%} judge={fidelity.llm_judge_score:.0%}")

        # ── Naive truncation ──
        print(f"    naive_truncation...", end=" ", flush=True)
        fidelity = measure_fidelity(
            questions, naive_text,
            model=model_id, api_key=api_key, provider=provider,
        )
        naive_cost = estimate_cost(naive_tokens, model=model_id)
        model_result["baselines"]["naive_truncation"] = {
            "tokens": naive_tokens,
            "ratio": f"{source_tokens/max(1,naive_tokens):.1f}x",
            "cost": naive_cost.to_dict()["cost_per_query"],
            "fidelity": fidelity.score,
            "llm_judge_score": fidelity.llm_judge_score,
        }
        print(f"fidelity={fidelity.score:.0%} judge={fidelity.llm_judge_score:.0%}")

        # ── LLM summary (only if corpus not too large) ──
        if source_tokens < 25000:
            print(f"    llm_summary...", end=" ", flush=True)
            llm_text = prepare_llm_summary(
                raw_text, ctx_tokens,
                model=model_id, api_key=api_key, provider=provider,
            )
            llm_tokens = count_tokens(llm_text)
            fidelity = measure_fidelity(
                questions, llm_text,
                model=model_id, api_key=api_key, provider=provider,
            )
            llm_cost = estimate_cost(llm_tokens, model=model_id)
            model_result["baselines"]["llm_summary"] = {
                "tokens": llm_tokens,
                "ratio": f"{source_tokens/max(1,llm_tokens):.1f}x",
                "cost": llm_cost.to_dict()["cost_per_query"],
                "fidelity": fidelity.score,
                "llm_judge_score": fidelity.llm_judge_score,
            }
            print(f"fidelity={fidelity.score:.0%} judge={fidelity.llm_judge_score:.0%}")

        results["model_results"][label] = model_result

    return results


def save_realworld_results(results: dict[str, Any], output_dir: str) -> str:
    """Save results with timestamped log."""
    os.makedirs(output_dir, exist_ok=True)

    corpus_name = results.get("corpus", "unknown").replace(" ", "_")
    output_path = os.path.join(output_dir, f"{corpus_name}_eval.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Timestamped log
    logs_dir = os.path.join(output_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    ts = results.get("timestamp", time.strftime("%Y-%m-%dT%H-%M-%S"))
    ts_safe = ts.replace(":", "-").replace("+", "p")[:19]
    log_path = os.path.join(logs_dir, f"{ts_safe}_{corpus_name}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return output_path


def print_realworld_summary(results: dict[str, Any]) -> None:
    """Print a summary table of real-world eval results."""
    corpus = results.get("corpus", "unknown")
    print(f"\n{'='*80}")
    print(f"  REAL-WORLD EVAL: {corpus}")
    print(f"  Source: {results.get('source_tokens', 0)} tokens -> "
          f"Compressed: {results.get('ctx_tokens', 0)} tokens "
          f"({results.get('compression_ratio', 0)}x)")
    print(f"{'='*80}")

    # Header
    models = list(results.get("model_results", {}).keys())
    hdr = f"  {'Baseline':<20}"
    for m in models:
        hdr += f" {m[:14]:>14}"
    print(hdr)
    print(f"  {'-'*20}" + (" " + "-" * 14) * len(models))

    # Rows by baseline
    baselines = ["ctxpack_l2", "raw_stuffing", "naive_truncation", "llm_summary"]
    for bl_name in baselines:
        row = f"  {bl_name:<20}"
        for m in models:
            model_data = results["model_results"].get(m, {})
            bl_data = model_data.get("baselines", {}).get(bl_name, {})
            fid = bl_data.get("fidelity")
            if fid is not None:
                row += f" {fid:>13.0%}"
            else:
                row += f" {'N/A':>14}"
        print(row)

    skipped = results.get("skipped", [])
    if skipped:
        print(f"\n  Skipped: {', '.join(s['model'] for s in skipped)}")
    print()


def run_all_realworld_evals(
    *,
    models: list[tuple[str, str, str, str]] | None = None,
    max_questions: int = 25,
    corpora: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run eval on all real-world corpora and produce combined results."""
    if corpora is None:
        corpora = CORPORA

    combined: dict[str, Any] = {
        "experiment": "realworld_eval",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corpora": {},
    }

    for corpus_def in corpora:
        name = corpus_def["name"]
        results = eval_single_corpus(
            corpus_name=name,
            corpus_dir=corpus_def["corpus_dir"],
            questions_path=corpus_def["questions_path"],
            results_dir=corpus_def["results_dir"],
            models=models,
            max_questions=max_questions,
        )

        # Save individual results
        save_realworld_results(results, corpus_def["results_dir"])
        print_realworld_summary(results)

        combined["corpora"][name] = results

    # Save combined
    combined_path = os.path.join(
        os.path.dirname(__file__), "combined_realworld_results.json"
    )
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)
    print(f"Combined results: {combined_path}")

    return combined


def main():
    """CLI entry point for real-world eval."""
    import argparse

    parser = argparse.ArgumentParser(description="Real-world corpus eval")
    parser.add_argument("--max-questions", type=int, default=25, help="Max questions per corpus")
    parser.add_argument("--models", nargs="*", help="Model labels to run (default: all)")
    parser.add_argument("--corpus", choices=["fda", "twilio", "all"], default="all",
                        help="Which corpus to evaluate")
    args = parser.parse_args()

    models = MODEL_CONFIGS
    if args.models:
        models = [m for m in MODEL_CONFIGS if m[0] in args.models]
        if not models:
            print(f"No matching models. Available: {[m[0] for m in MODEL_CONFIGS]}")
            return

    corpora = CORPORA
    if args.corpus != "all":
        corpora = [c for c in CORPORA if args.corpus in c["name"]]

    run_all_realworld_evals(
        models=models,
        max_questions=args.max_questions,
        corpora=corpora,
    )


if __name__ == "__main__":
    main()
