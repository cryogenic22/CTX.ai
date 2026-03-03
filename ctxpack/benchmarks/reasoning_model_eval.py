"""Targeted eval: reasoning-capable models (GPT-5.2, o3, o4-mini) on .ctx

Tests whether extended reasoning closes the precision gap on Q13/Q23/Q25.
Saves results alongside existing model-affinity data.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from typing import Any

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ctxpack.benchmarks.dotenv import load_dotenv
from ctxpack.benchmarks.metrics.fidelity import (
    load_questions,
    measure_fidelity,
)
from ctxpack.core.packer import pack
from ctxpack.core.serializer import serialize

load_dotenv()


def main():
    golden_set_path = os.path.join(os.path.dirname(__file__), "golden_set")
    questions_path = os.path.join(golden_set_path, "questions.yaml")
    corpus_dir = os.path.join(golden_set_path, "corpus")
    save_dir = os.path.join(golden_set_path, "results")
    logs_dir = os.path.join(save_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    questions = load_questions(questions_path)
    pack_result = pack(corpus_dir)
    l2_text = serialize(pack_result.document)
    l1_text = serialize(pack_result.document, natural_language=True)
    l2_tokens = len(l2_text.split())
    l1_tokens = len(l1_text.split())

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        print("ERROR: OPENAI_API_KEY not set.")
        return

    # Reasoning-capable models
    models = [
        ("o3", "o3"),
        ("o4-mini", "o4-mini"),
    ]

    print(f"Questions: {len(questions)}, L2={l2_tokens} tok, L1={l1_tokens} tok")
    print()

    version = "0.3.0-alpha"
    all_results: dict[str, Any] = {
        "version": version,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "eval_type": "reasoning-models",
        "l2_tokens": l2_tokens,
        "l1_tokens": l1_tokens,
        "runs": {},
    }

    for model_label, model_id in models:
        for fmt_label, context, tokens in [("L2", l2_text, l2_tokens), ("L1", l1_text, l1_tokens)]:
            run_key = f"{model_label}-{fmt_label}"
            print(f"  Running: {run_key} ({len(questions)} Qs)...", end=" ", flush=True)

            t0 = time.perf_counter()
            metrics = measure_fidelity(
                questions, context,
                model=model_id,
                api_key=openai_key,
                provider="openai",
                judge_model="gpt-4o",
                judge_api_key=openai_key,
                judge_provider="openai",
            )
            elapsed = time.perf_counter() - t0

            run_data = {
                "model": model_label,
                "model_id": model_id,
                "provider": "openai",
                "format": fmt_label,
                "tokens": tokens,
                "rule_score": metrics.score,
                "rule_correct": metrics.correct,
                "judge_score": metrics.llm_judge_score,
                "judge_correct": metrics.llm_judge_correct,
                "total": metrics.total,
                "elapsed_s": round(elapsed, 1),
                "by_difficulty": metrics._by_difficulty(),
                "per_question": [
                    {
                        "id": r.question_id,
                        "question": r.question,
                        "expected": r.expected,
                        "answer": r.answer,
                        "rule_correct": r.correct,
                        "judge_correct": r.llm_judge_correct,
                        "difficulty": r.difficulty,
                    }
                    for r in metrics.results
                ],
            }

            all_results["runs"][run_key] = run_data
            print(f"rule={metrics.score:.0%} judge={metrics.llm_judge_score:.0%} ({elapsed:.1f}s)")

            # Save individual log
            log_path = os.path.join(
                logs_dir,
                f"{time.strftime('%Y-%m-%dT%H-%M-%S')}_{run_key}.json",
            )
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(run_data, f, indent=2, ensure_ascii=False)

    # Print comparison with focus questions
    print()
    print("=" * 80)
    print("  REASONING MODEL RESULTS — Focus Questions")
    print("=" * 80)
    print()

    focus_qs = ["Q13", "Q23", "Q25", "Q04", "Q05"]
    run_keys = list(all_results["runs"].keys())

    # Summary table
    hdr = f"{'Run':<18s} {'Tokens':>7s} {'Rule':>6s} {'Judge':>7s}"
    print(hdr)
    print("-" * len(hdr))
    for rk, r in all_results["runs"].items():
        print(f"{rk:<18s} {r['tokens']:>7d} {r['rule_score']:>5.0%} {r['judge_score']:>6.0%}")

    # Focus question detail
    print()
    print("-- Focus Questions (previously failed by GPT-4o/5.2/mini) --")
    print()
    for q_id in focus_qs:
        print(f"  {q_id}:")
        for rk, r in all_results["runs"].items():
            for q in r["per_question"]:
                if q["id"] == q_id:
                    mark = "OK" if q["judge_correct"] else "FAIL"
                    ans = q["answer"][:100].replace("\n", " ")
                    print(f"    {rk:<16s} [{mark:>4s}] {ans}")
        print()

    # Save combined results
    path = os.path.join(save_dir, f"{version}-reasoning-models.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"Results saved: {path}")


if __name__ == "__main__":
    main()
