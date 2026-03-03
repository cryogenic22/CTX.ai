"""Tokenizer mapping: measure how different tokenizers count .ctx tokens.

Addresses Reviewer 2 concern about tokenizer specificity — paper reports
"tokens" but doesn't specify which tokenizer. This produces a mapping table
showing actual token counts per tokenizer family.
"""

from __future__ import annotations

import json
import os
import datetime
from typing import Any


def count_word_split(text: str) -> int:
    """Baseline: whitespace-split token count (used throughout ctxpack)."""
    return len(text.split())


def count_tiktoken(text: str, encoding_name: str) -> int:
    """Count tokens using tiktoken (OpenAI tokenizer)."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding(encoding_name)
        return len(enc.encode(text))
    except ImportError:
        return -1
    except Exception:
        return -1


def count_anthropic_estimate(text: str) -> int:
    """Estimate Anthropic token count.

    Claude uses a custom BPE tokenizer similar to tiktoken's cl100k.
    For structured .ctx text with Unicode operators (§, ★, ⚠, ±),
    character-level estimation (~4 chars/token) is more accurate than
    word-count scaling, since .ctx "words" are long compound strings
    like KEY:VALUE or status→flow→chains.
    """
    # ~4 chars per token is the standard BPE estimate for English+symbols
    return max(1, len(text) // 4)


def run_tokenizer_mapping(ctx_text: str) -> dict[str, Any]:
    """Produce tokenizer mapping table for a given .ctx text.

    Returns dict with per-tokenizer counts and ratios.
    """
    word_count = count_word_split(ctx_text)
    char_count = len(ctx_text)

    tokenizers: dict[str, dict[str, Any]] = {}

    # Word-split (ctxpack default)
    tokenizers["word_split"] = {
        "tokens": word_count,
        "ratio_vs_word_count": 1.0,
        "note": "ctxpack internal count (whitespace split)",
    }

    # tiktoken cl100k_base (GPT-4, GPT-4o)
    cl100k = count_tiktoken(ctx_text, "cl100k_base")
    if cl100k > 0:
        tokenizers["tiktoken_cl100k"] = {
            "tokens": cl100k,
            "ratio_vs_word_count": round(cl100k / word_count, 3),
            "models": "GPT-4, GPT-4o",
        }

    # tiktoken o200k_base (GPT-4o-mini, GPT-5.2, o3, o4-mini)
    o200k = count_tiktoken(ctx_text, "o200k_base")
    if o200k > 0:
        tokenizers["tiktoken_o200k"] = {
            "tokens": o200k,
            "ratio_vs_word_count": round(o200k / word_count, 3),
            "models": "GPT-4o-mini, GPT-5.2, o3, o4-mini",
        }

    # Anthropic estimate
    anthropic_est = count_anthropic_estimate(ctx_text)
    tokenizers["anthropic_estimate"] = {
        "tokens": anthropic_est,
        "ratio_vs_word_count": round(anthropic_est / word_count, 3),
        "models": "Claude Sonnet 4.5, Claude Haiku 4.5",
        "note": "estimated (~4 chars/token, BPE-calibrated)",
    }

    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "input_chars": char_count,
        "input_word_count": word_count,
        "tokenizers": tokenizers,
    }


def run_and_save(
    golden_set_dir: str = "",
    output_path: str = "",
) -> dict[str, Any]:
    """Pack golden set, run tokenizer mapping, save results."""
    from ctxpack.core.packer import pack
    from ctxpack.core.serializer import serialize

    if not golden_set_dir:
        golden_set_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "golden_set", "corpus",
        )

    if not output_path:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "results", "tokenizer_mapping.json",
        )

    # Pack and serialize
    result = pack(golden_set_dir)
    ctx_text = serialize(result.document)

    # Run mapping
    mapping = run_tokenizer_mapping(ctx_text)
    mapping["corpus"] = "golden_set"
    mapping["source_tokens"] = result.source_token_count

    # Save
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)

    # Print summary
    print(f"\nTokenizer Mapping Results")
    print(f"{'='*60}")
    print(f"  Input: {mapping['input_word_count']} words, {mapping['input_chars']} chars")
    print(f"  {'Tokenizer':<25} {'Tokens':>8} {'Ratio':>8}")
    print(f"  {'-'*25} {'-'*8} {'-'*8}")
    for name, info in mapping["tokenizers"].items():
        tokens = info["tokens"]
        ratio = info["ratio_vs_word_count"]
        print(f"  {name:<25} {tokens:>8} {ratio:>8.3f}")

    return mapping


def run_bpe_cost_comparison(
    golden_set_dir: str = "",
    output_path: str = "",
) -> dict[str, Any]:
    """Pack golden set in default + bpe_optimized modes, measure BPE tokens and
    real $ cost for ALL methods (ctxpack default, ctxpack bpe-optimized, raw
    stuffing, minified, LLM summary placeholder).

    Output: bpe_cost_comparison.json
    """
    from ctxpack.core.packer import pack
    from ctxpack.core.serializer import serialize
    from ctxpack.benchmarks.baselines.raw_stuffing import prepare_raw_context
    from ctxpack.benchmarks.baselines.minified import prepare_minified_context
    from ctxpack.benchmarks.metrics.cost import estimate_cost, estimate_cost_bpe, count_bpe_tokens

    if not golden_set_dir:
        golden_set_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "golden_set", "corpus",
        )

    if not output_path:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "results", "bpe_cost_comparison.json",
        )

    # Pack golden set
    result = pack(golden_set_dir)
    ctx_default = serialize(result.document)
    ctx_bpe_opt = serialize(result.document, bpe_optimized=True)
    raw_text = prepare_raw_context(golden_set_dir)
    minified_text = prepare_minified_context(golden_set_dir)

    models = ["claude-sonnet-4-5-20250929", "gpt-4o", "gemini-2.5-pro"]
    methods = {
        "ctxpack_default": ctx_default,
        "ctxpack_bpe_optimized": ctx_bpe_opt,
        "raw_stuffing": raw_text,
        "minified": minified_text,
    }

    comparison: dict[str, Any] = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_tokens_wordsplit": result.source_token_count,
        "methods": {},
    }

    for method_name, text in methods.items():
        word_count = count_word_split(text)
        char_count = len(text)

        method_data: dict[str, Any] = {
            "word_count": word_count,
            "char_count": char_count,
            "bpe_tokens": {},
            "cost_per_query": {},
        }

        # BPE counts per encoding
        cl100k = count_tiktoken(text, "cl100k_base")
        o200k = count_tiktoken(text, "o200k_base")
        anthropic_est = count_anthropic_estimate(text)

        method_data["bpe_tokens"]["cl100k_base"] = cl100k
        method_data["bpe_tokens"]["o200k_base"] = o200k
        method_data["bpe_tokens"]["anthropic_estimate"] = anthropic_est
        method_data["bpe_tokens"]["word_split"] = word_count

        # Cost per model (word-split vs BPE)
        for model in models:
            cost_ws = estimate_cost(word_count, model=model)
            cost_bpe = estimate_cost_bpe(text, model=model)
            method_data["cost_per_query"][model] = {
                "word_split": cost_ws.to_dict(),
                "bpe": cost_bpe.to_dict(),
            }

        comparison["methods"][method_name] = method_data

    # Compute BPE savings from bpe_optimized
    default_cl100k = comparison["methods"]["ctxpack_default"]["bpe_tokens"].get("cl100k_base", 0)
    opt_cl100k = comparison["methods"]["ctxpack_bpe_optimized"]["bpe_tokens"].get("cl100k_base", 0)
    if default_cl100k > 0 and opt_cl100k > 0:
        comparison["bpe_optimization_savings"] = {
            "cl100k_tokens_saved": default_cl100k - opt_cl100k,
            "cl100k_pct_reduction": round((default_cl100k - opt_cl100k) / default_cl100k * 100, 2),
        }

    # Save
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2)

    # Print summary
    print(f"\nBPE Cost Comparison")
    print(f"{'='*80}")
    print(f"  {'Method':<25} {'Words':>7} {'cl100k':>8} {'o200k':>8} {'~Claude':>8}")
    print(f"  {'-'*25} {'-'*7} {'-'*8} {'-'*8} {'-'*8}")
    for name, data in comparison["methods"].items():
        bpe = data["bpe_tokens"]
        print(
            f"  {name:<25} {data['word_count']:>7} "
            f"{bpe.get('cl100k_base', -1):>8} "
            f"{bpe.get('o200k_base', -1):>8} "
            f"{bpe.get('anthropic_estimate', -1):>8}"
        )

    if "bpe_optimization_savings" in comparison:
        s = comparison["bpe_optimization_savings"]
        print(f"\n  BPE optimization: -{s['cl100k_tokens_saved']} cl100k tokens ({s['cl100k_pct_reduction']}% reduction)")

    print(f"\n  Saved to: {output_path}")
    return comparison


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--bpe-cost":
        run_bpe_cost_comparison()
    else:
        run_and_save()
