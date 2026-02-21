"""Evaluation runner: orchestrates eval runs across baselines."""

from __future__ import annotations

import json
import os
import datetime
from typing import Any, Optional

from .dotenv import load_dotenv
from .eval_config import EvalConfig
from .metrics.compression import count_corpus_tokens, count_tokens, measure_compression
from .metrics.cost import estimate_cost
from .metrics.conflict import measure_conflicts
from .metrics.fidelity import load_questions, measure_fidelity
from .baselines.raw_stuffing import prepare_raw_context
from .baselines.naive_summary import prepare_naive_context
from .baselines.llm_summary import prepare_llm_summary
from .baselines.hand_authored import prepare_hand_context


def run_eval(
    config: EvalConfig,
    *,
    ctx_text: str,
    version: str = "0.2.0",
) -> dict[str, Any]:
    """Run evaluation and return results dict.

    Args:
        config: Evaluation configuration.
        ctx_text: The ctxpack-compressed .ctx output text.
        version: Version string for results tracking.

    Returns:
        Results dictionary (JSON-serializable).
    """
    # Load .env for API keys
    load_dotenv()

    corpus_dir = os.path.join(config.golden_set_path, "corpus")
    results: dict[str, Any] = {
        "version": version,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "baselines": {},
        "config": {
            "golden_set_path": config.golden_set_path,
            "baselines": config.baselines,
            "run_fidelity": config.run_fidelity,
            "run_conflicts": config.run_conflicts,
            "model": config.model,
        },
    }

    # Source token count
    source_tokens = count_corpus_tokens(corpus_dir)
    ctx_tokens = count_tokens(ctx_text)

    # Load questions
    questions_path = os.path.join(config.golden_set_path, "questions.yaml")
    questions = []
    if os.path.exists(questions_path):
        questions = load_questions(questions_path)

    # Detect provider and API key from environment
    from .metrics.fidelity import _detect_provider
    provider, api_key, detected_model = _detect_provider()
    if not config.run_fidelity:
        api_key = ""
    eval_model = config.model or detected_model

    # ── ctxpack L2 baseline ──
    ctx_compression = measure_compression(source_tokens, ctx_text)
    ctx_cost = estimate_cost(ctx_tokens, model=eval_model)
    ctx_result: dict[str, Any] = {
        "tokens": ctx_tokens,
        "ratio": f"{ctx_compression.compression_ratio:.1f}x",
        "cost": ctx_cost.to_dict()["cost_per_query"],
    }
    if config.run_fidelity and api_key:
        fidelity = measure_fidelity(
            questions, ctx_text,
            model=eval_model, api_key=api_key, provider=provider,
        )
        ctx_result["fidelity"] = fidelity.score
        ctx_result["fidelity_details"] = fidelity.to_dict()
    results["baselines"]["ctxpack_l2"] = ctx_result

    # ── Raw stuffing baseline ──
    if "raw" in config.baselines:
        raw_text = prepare_raw_context(corpus_dir)
        raw_tokens = count_tokens(raw_text)
        raw_cost = estimate_cost(raw_tokens, model=eval_model)
        raw_result: dict[str, Any] = {
            "tokens": raw_tokens,
            "ratio": "1x",
            "cost": raw_cost.to_dict()["cost_per_query"],
        }
        if config.run_fidelity and api_key:
            fidelity = measure_fidelity(
                questions, raw_text,
                model=eval_model, api_key=api_key, provider=provider,
            )
            raw_result["fidelity"] = fidelity.score
            raw_result["fidelity_details"] = fidelity.to_dict()
        results["baselines"]["raw_stuffing"] = raw_result

    # ── Naive summary baseline ──
    if "naive" in config.baselines:
        raw_text = prepare_raw_context(corpus_dir)
        naive_text = prepare_naive_context(raw_text, ctx_tokens)
        naive_tokens = count_tokens(naive_text)
        naive_cost = estimate_cost(naive_tokens, model=eval_model)
        naive_result: dict[str, Any] = {
            "tokens": naive_tokens,
            "ratio": f"{source_tokens / naive_tokens:.1f}x" if naive_tokens > 0 else "N/A",
            "cost": naive_cost.to_dict()["cost_per_query"],
        }
        if config.run_fidelity and api_key:
            fidelity = measure_fidelity(
                questions, naive_text,
                model=eval_model, api_key=api_key, provider=provider,
            )
            naive_result["fidelity"] = fidelity.score
            naive_result["fidelity_details"] = fidelity.to_dict()
        results["baselines"]["naive_summary"] = naive_result

    # ── LLM summary baseline ──
    if "llm_summary" in config.baselines and api_key:
        raw_text = prepare_raw_context(corpus_dir)
        llm_text = prepare_llm_summary(
            raw_text, ctx_tokens,
            model=eval_model, api_key=api_key, provider=provider,
        )
        llm_tokens = count_tokens(llm_text)
        llm_cost = estimate_cost(llm_tokens, model=eval_model)
        llm_result: dict[str, Any] = {
            "tokens": llm_tokens,
            "ratio": f"{source_tokens / llm_tokens:.1f}x" if llm_tokens > 0 else "N/A",
            "cost": llm_cost.to_dict()["cost_per_query"],
            "summary_preview": llm_text[:200] + "..." if len(llm_text) > 200 else llm_text,
        }
        if config.run_fidelity:
            fidelity = measure_fidelity(
                questions, llm_text,
                model=eval_model, api_key=api_key, provider=provider,
            )
            llm_result["fidelity"] = fidelity.score
            llm_result["fidelity_details"] = fidelity.to_dict()
        results["baselines"]["llm_summary"] = llm_result

    # ── Hand-authored baseline ──
    if "hand" in config.baselines:
        hand_path = os.path.join(config.golden_set_path, "expected", "hand.ctx")
        hand_text = prepare_hand_context(hand_path)
        if hand_text:
            hand_tokens = count_tokens(hand_text)
            hand_cost = estimate_cost(hand_tokens, model=eval_model)
            hand_result: dict[str, Any] = {
                "tokens": hand_tokens,
                "ratio": f"{source_tokens / hand_tokens:.1f}x" if hand_tokens > 0 else "N/A",
                "cost": hand_cost.to_dict()["cost_per_query"],
            }
            if config.run_fidelity and api_key:
                fidelity = measure_fidelity(
                    questions, hand_text,
                    model=eval_model, api_key=api_key, provider=provider,
                )
                hand_result["fidelity"] = fidelity.score
                hand_result["fidelity_details"] = fidelity.to_dict()
            results["baselines"]["hand_authored"] = hand_result

    # ── Conflict detection metrics ──
    if config.run_conflicts:
        # Count planted conflicts in questions
        planted = sum(1 for q in questions if q.get("tests_conflict_detection"))
        # Count ⚠ warning lines in ctx output (each ⚠ line = one detected conflict)
        warning_lines = [
            line for line in ctx_text.splitlines()
            if "⚠" in line or line.strip().startswith("WARN:")
        ]
        detected = len(warning_lines)
        # Match detected warnings to planted conflicts by keyword overlap
        planted_qs = [q for q in questions if q.get("tests_conflict_detection")]
        tp = 0
        for q in planted_qs:
            expected_lower = q.get("expected", "").lower()
            # Check if any warning line relates to this planted conflict
            for wl in warning_lines:
                wl_lower = wl.lower()
                # Match on entity names or key terms from expected answer
                terms = [t.strip() for t in expected_lower.split() if len(t.strip()) > 3]
                if any(t in wl_lower for t in terms):
                    tp += 1
                    break
        conflict_metrics = measure_conflicts(planted, detected, tp)
        results["conflict_detection"] = conflict_metrics.to_dict()

    return results


def save_results(results: dict[str, Any], config: EvalConfig) -> str:
    """Save results to JSON file and return the path."""
    os.makedirs(config.output_dir, exist_ok=True)
    version = results.get("version", "unknown")
    filename = f"v{version}.json"
    path = os.path.join(config.output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    return path
