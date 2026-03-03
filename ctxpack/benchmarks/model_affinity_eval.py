"""Model affinity eval: L2 vs L1 across Claude, GPT-4o, GPT-4o-mini.

Runs full golden-set fidelity evaluation, saves structured results,
and produces per-question failure analysis.

Results saved to: ctxpack/benchmarks/golden_set/results/
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ctxpack.benchmarks.dotenv import load_dotenv
from ctxpack.benchmarks.metrics.fidelity import (
    FidelityMetrics,
    load_questions,
    measure_fidelity,
)
from ctxpack.core.packer import pack
from ctxpack.core.serializer import serialize

load_dotenv()


def run_model_affinity_eval(
    *,
    save_dir: str | None = None,
    version: str = "0.3.0-alpha",
) -> dict[str, Any]:
    """Run full L2 vs L1 eval across all available models.

    Returns combined results dict and saves per-run JSON files.
    """
    # Paths
    golden_set_path = os.path.join(
        os.path.dirname(__file__), "golden_set",
    )
    questions_path = os.path.join(golden_set_path, "questions.yaml")
    corpus_dir = os.path.join(golden_set_path, "corpus")
    if save_dir is None:
        save_dir = os.path.join(golden_set_path, "results")
    os.makedirs(save_dir, exist_ok=True)
    logs_dir = os.path.join(save_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Load questions & pack corpus
    questions = load_questions(questions_path)
    pack_result = pack(corpus_dir)

    l2_text = serialize(pack_result.document)
    l1_text = serialize(pack_result.document, natural_language=True)
    l2_tokens = len(l2_text.split())
    l1_tokens = len(l1_text.split())

    print(f"Questions: {len(questions)}")
    print(f"L2 tokens: {l2_tokens}, L1 tokens: {l1_tokens} ({l1_tokens/l2_tokens:.1f}x overhead)")
    print()

    # Build model grid
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    models = []
    if anthropic_key:
        models.append(("claude-sonnet-4.5", "anthropic", anthropic_key, "claude-sonnet-4-5-20250929"))
        models.append(("claude-haiku-4.5", "anthropic", anthropic_key, "claude-haiku-4-5-20251001"))
    if openai_key:
        models.append(("gpt-5.2", "openai", openai_key, "gpt-5.2"))
        models.append(("gpt-4.1", "openai", openai_key, "gpt-4.1"))
        models.append(("gpt-4o", "openai", openai_key, "gpt-4o"))
        models.append(("gpt-4o-mini", "openai", openai_key, "gpt-4o-mini"))

    if not models:
        print("ERROR: No API keys found.")
        return {}

    # Run evals
    all_results: dict[str, Any] = {
        "version": version,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "l2_tokens": l2_tokens,
        "l1_tokens": l1_tokens,
        "question_count": len(questions),
        "runs": {},
    }

    for model_label, provider, api_key, model_id in models:
        for fmt_label, context, tokens in [("L2", l2_text, l2_tokens), ("L1", l1_text, l1_tokens)]:
            run_key = f"{model_label}-{fmt_label}"
            print(f"  Running: {run_key} ({len(questions)} Qs)...", end=" ", flush=True)

            t0 = time.perf_counter()
            metrics = measure_fidelity(
                questions, context,
                model=model_id,
                api_key=api_key,
                provider=provider,
            )
            elapsed = time.perf_counter() - t0

            run_data = {
                "model": model_label,
                "model_id": model_id,
                "provider": provider,
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

            # Save individual run log
            log_path = os.path.join(
                logs_dir,
                f"{time.strftime('%Y-%m-%dT%H-%M-%S')}_{run_key}.json",
            )
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(run_data, f, indent=2, ensure_ascii=False)

    # Save combined results
    combined_path = os.path.join(save_dir, f"{version}-model-affinity.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved: {combined_path}")

    return all_results


def failure_analysis(results: dict[str, Any]) -> str:
    """Produce per-question failure analysis from eval results.

    Identifies:
    - Which questions each model/format gets wrong
    - L2-vs-L1 flip patterns (correct on one, wrong on other)
    - Complementary vs overlapping failure modes
    - Attention dilution evidence
    """
    lines: list[str] = []
    lines.append("=" * 90)
    lines.append("  MODEL AFFINITY FAILURE ANALYSIS")
    lines.append(f"  Version: {results.get('version', '?')}")
    lines.append(f"  Timestamp: {results.get('timestamp', '?')}")
    lines.append("=" * 90)
    lines.append("")

    runs = results.get("runs", {})
    if not runs:
        lines.append("No runs found.")
        return "\n".join(lines)

    # Get question IDs from first run
    first_run = next(iter(runs.values()))
    q_ids = [q["id"] for q in first_run["per_question"]]
    q_map = {q["id"]: q for q in first_run["per_question"]}

    # ── 1. Summary table ──
    lines.append("-- Summary --")
    lines.append("")
    hdr = f"{'Run':<24s} {'Tokens':>7s} {'Rule':>6s} {'Judge':>7s} {'Easy':>6s} {'Med':>6s} {'Hard':>6s}"
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for run_key, r in runs.items():
        by_d = r["by_difficulty"]
        easy = by_d.get("easy", {}).get("score", 0)
        med = by_d.get("medium", {}).get("score", 0)
        hard = by_d.get("hard", {}).get("score", 0)
        lines.append(
            f"{run_key:<24s} {r['tokens']:>7d} {r['rule_score']:>5.0%} "
            f"{r['judge_score']:>6.0%} {easy:>5.0%} {med:>5.0%} {hard:>5.0%}"
        )
    lines.append("")

    # ── 2. Per-question correctness matrix ──
    lines.append("-- Per-Question Correctness Matrix (Judge) --")
    lines.append("")

    # Build matrix: q_id -> {run_key: correct}
    matrix: dict[str, dict[str, bool]] = {}
    for q_id in q_ids:
        matrix[q_id] = {}
        for run_key, r in runs.items():
            for q in r["per_question"]:
                if q["id"] == q_id:
                    matrix[q_id][run_key] = q["judge_correct"]

    run_keys = list(runs.keys())
    # Short labels for column headers
    short_labels = []
    for rk in run_keys:
        fmt = rk.split("-")[-1]  # L2 or L1
        model = runs[rk]["model"]
        # Build short label from model name
        if "sonnet" in model:
            short_labels.append(f"Son-{fmt}")
        elif "haiku" in model:
            short_labels.append(f"Hai-{fmt}")
        elif "5.2" in model:
            short_labels.append(f"5.2-{fmt}")
        elif "4.1" in model:
            short_labels.append(f"4.1-{fmt}")
        elif "mini" in model:
            short_labels.append(f"mini-{fmt}")
        elif "4o" in model:
            short_labels.append(f"4o-{fmt}")
        else:
            short_labels.append(f"{model[:4]}-{fmt}")

    col_w = 8
    header_line = f"{'Q':>5s}  {'Diff':<7s}  " + "".join(f"{sl:>{col_w}s}" for sl in short_labels)
    lines.append(header_line)
    lines.append("-" * len(header_line))

    for q_id in q_ids:
        diff = q_map[q_id]["difficulty"][:4]
        marks = []
        for rk in run_keys:
            correct = matrix[q_id].get(rk, False)
            marks.append(f"{'OK':>{col_w}s}" if correct else f"{'FAIL':>{col_w}s}")
        lines.append(f"{q_id:>5s}  {diff:<7s}  " + "".join(marks))
    lines.append("")

    # ── 3. Identify L2-vs-L1 flips per model ──
    lines.append("-- L2 vs L1 Flip Analysis --")
    lines.append("")

    # Group runs by model
    model_names = list(dict.fromkeys(r["model"] for r in runs.values()))

    for model_name in model_names:
        l2_key = None
        l1_key = None
        for rk, r in runs.items():
            if r["model"] == model_name and r["format"] == "L2":
                l2_key = rk
            if r["model"] == model_name and r["format"] == "L1":
                l1_key = rk

        if not l2_key or not l1_key:
            continue

        l2_qs = {q["id"]: q for q in runs[l2_key]["per_question"]}
        l1_qs = {q["id"]: q for q in runs[l1_key]["per_question"]}

        flips_l2_wins = []  # Correct on L2, wrong on L1
        flips_l1_wins = []  # Wrong on L2, correct on L1
        both_fail = []
        both_pass = []

        for q_id in q_ids:
            l2_ok = l2_qs[q_id]["judge_correct"]
            l1_ok = l1_qs[q_id]["judge_correct"]
            if l2_ok and l1_ok:
                both_pass.append(q_id)
            elif l2_ok and not l1_ok:
                flips_l2_wins.append(q_id)
            elif not l2_ok and l1_ok:
                flips_l1_wins.append(q_id)
            else:
                both_fail.append(q_id)

        lines.append(f"  {model_name}:")
        lines.append(f"    Both correct:     {len(both_pass)} questions")
        lines.append(f"    Both wrong:       {len(both_fail)} questions  {both_fail}")
        lines.append(f"    L2 wins (L1 fails): {len(flips_l2_wins)} questions  {flips_l2_wins}")
        lines.append(f"    L1 wins (L2 fails): {len(flips_l1_wins)} questions  {flips_l1_wins}")
        lines.append("")

        # Detail the flips
        if flips_l2_wins:
            lines.append(f"    -- L2 wins over L1 (attention dilution candidates) --")
            for q_id in flips_l2_wins:
                q_l2 = l2_qs[q_id]
                q_l1 = l1_qs[q_id]
                lines.append(f"    {q_id} [{q_l2['difficulty']}]: {q_l2['question'][:80]}")
                lines.append(f"      Expected: {q_l2['expected'][:80]}")
                lines.append(f"      L2 answer: {q_l2['answer'][:120]}")
                lines.append(f"      L1 answer: {q_l1['answer'][:120]}")
                # Check if L1 answer is longer (attention dilution signal)
                l2_len = len(q_l2['answer'].split())
                l1_len = len(q_l1['answer'].split())
                lines.append(f"      Answer length: L2={l2_len}w, L1={l1_len}w")
                lines.append("")

        if flips_l1_wins:
            lines.append(f"    -- L1 wins over L2 (notation barrier candidates) --")
            for q_id in flips_l1_wins:
                q_l2 = l2_qs[q_id]
                q_l1 = l1_qs[q_id]
                lines.append(f"    {q_id} [{q_l2['difficulty']}]: {q_l2['question'][:80]}")
                lines.append(f"      Expected: {q_l2['expected'][:80]}")
                lines.append(f"      L2 answer: {q_l2['answer'][:120]}")
                lines.append(f"      L1 answer: {q_l1['answer'][:120]}")
                l2_len = len(q_l2['answer'].split())
                l1_len = len(q_l1['answer'].split())
                lines.append(f"      Answer length: L2={l2_len}w, L1={l1_len}w")
                lines.append("")

        if both_fail:
            lines.append(f"    -- Both formats fail (hard for this model) --")
            for q_id in both_fail:
                q_l2 = l2_qs[q_id]
                q_l1 = l1_qs[q_id]
                lines.append(f"    {q_id} [{q_l2['difficulty']}]: {q_l2['question'][:80]}")
                lines.append(f"      Expected: {q_l2['expected'][:80]}")
                lines.append(f"      L2 answer: {q_l2['answer'][:120]}")
                lines.append(f"      L1 answer: {q_l1['answer'][:120]}")
                lines.append("")

    # ── 4. Cross-model comparison: which questions are universally hard? ──
    lines.append("-- Cross-Model Hardness --")
    lines.append("")

    fail_counts: dict[str, int] = {}
    for q_id in q_ids:
        count = 0
        for rk in run_keys:
            if not matrix[q_id].get(rk, False):
                count += 1
        fail_counts[q_id] = count

    hard_qs = [(qid, count) for qid, count in fail_counts.items() if count > 0]
    hard_qs.sort(key=lambda x: -x[1])

    if hard_qs:
        lines.append(f"  Questions with at least 1 failure (across {len(run_keys)} runs):")
        for qid, count in hard_qs:
            q = q_map[qid]
            failed_on = [rk for rk in run_keys if not matrix[qid].get(rk, False)]
            lines.append(f"    {qid} [{q['difficulty']}] — fails {count}/{len(run_keys)}: {failed_on}")
            lines.append(f"      Q: {q['question'][:90]}")
            lines.append(f"      Expected: {q['expected'][:90]}")
    else:
        lines.append("  All questions passed on all runs.")
    lines.append("")

    # ── 5. Mechanism analysis ──
    lines.append("-- Mechanism Analysis --")
    lines.append("")

    # Count flip patterns
    total_l2_wins = 0
    total_l1_wins = 0
    total_both_fail = 0
    for model_name in model_names:
        l2_key = None
        l1_key = None
        for rk, r in runs.items():
            if r["model"] == model_name and r["format"] == "L2":
                l2_key = rk
            if r["model"] == model_name and r["format"] == "L1":
                l1_key = rk
        if not l2_key or not l1_key:
            continue

        for q_id in q_ids:
            l2_ok = matrix[q_id].get(l2_key, False)
            l1_ok = matrix[q_id].get(l1_key, False)
            if l2_ok and not l1_ok:
                total_l2_wins += 1
            elif not l2_ok and l1_ok:
                total_l1_wins += 1
            elif not l2_ok and not l1_ok:
                total_both_fail += 1

    lines.append(f"  Across all models:")
    lines.append(f"    L2-wins-over-L1 flips: {total_l2_wins}")
    lines.append(f"    L1-wins-over-L2 flips: {total_l1_wins}")
    lines.append(f"    Both-fail (format-independent): {total_both_fail}")
    lines.append("")

    if total_l2_wins > 0 and total_l1_wins > 0:
        lines.append("  FINDING: Complementary failure modes detected.")
        lines.append("  L2 and L1 fail on DIFFERENT questions, suggesting ensemble")
        lines.append("  context (serve both formats) could achieve higher fidelity")
        lines.append("  than either format alone.")
    elif total_l2_wins > total_l1_wins:
        lines.append("  FINDING: Attention dilution dominant.")
        lines.append("  L1's extra tokens cause more failures than L2's notation barrier.")
        lines.append("  Dense notation is net-positive for most models.")
    elif total_l1_wins > total_l2_wins:
        lines.append("  FINDING: Notation barrier dominant.")
        lines.append("  L2 notation causes more failures than L1's token overhead.")
        lines.append("  Natural language framing is net-positive for most models.")
    else:
        lines.append("  FINDING: Balanced — no dominant failure mode.")

    lines.append("")

    # Check for overlap between L2-wins and L1-wins across models
    all_l2_win_qs: set[str] = set()
    all_l1_win_qs: set[str] = set()
    for model_name in model_names:
        l2_key = None
        l1_key = None
        for rk, r in runs.items():
            if r["model"] == model_name and r["format"] == "L2":
                l2_key = rk
            if r["model"] == model_name and r["format"] == "L1":
                l1_key = rk
        if not l2_key or not l1_key:
            continue
        for q_id in q_ids:
            l2_ok = matrix[q_id].get(l2_key, False)
            l1_ok = matrix[q_id].get(l1_key, False)
            if l2_ok and not l1_ok:
                all_l2_win_qs.add(q_id)
            elif not l2_ok and l1_ok:
                all_l1_win_qs.add(q_id)

    overlap = all_l2_win_qs & all_l1_win_qs
    if overlap:
        lines.append(f"  Questions that flip BOTH ways across models: {sorted(overlap)}")
        lines.append("  (Same question: L2 wins for one model, L1 wins for another)")
        lines.append("  This confirms model-dependent format preference.")
    lines.append("")

    # Ensemble upper bound
    lines.append("-- Ensemble Upper Bound --")
    lines.append("  (If we served both L2 and L1 and took the best answer per question)")
    lines.append("")
    for model_name in model_names:
        l2_key = None
        l1_key = None
        for rk, r in runs.items():
            if r["model"] == model_name and r["format"] == "L2":
                l2_key = rk
            if r["model"] == model_name and r["format"] == "L1":
                l1_key = rk
        if not l2_key or not l1_key:
            continue

        l2_score = runs[l2_key]["judge_score"]
        l1_score = runs[l1_key]["judge_score"]

        ensemble_correct = 0
        for q_id in q_ids:
            l2_ok = matrix[q_id].get(l2_key, False)
            l1_ok = matrix[q_id].get(l1_key, False)
            if l2_ok or l1_ok:
                ensemble_correct += 1
        ensemble_score = ensemble_correct / len(q_ids)

        lines.append(
            f"  {model_name}: L2={l2_score:.0%}, L1={l1_score:.0%}, "
            f"ensemble={ensemble_score:.0%} ({ensemble_correct}/{len(q_ids)})"
        )

    lines.append("")
    lines.append("=" * 90)

    return "\n".join(lines)


def main():
    import io as _io
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    print("Running model affinity eval + failure analysis...")
    print()

    results = run_model_affinity_eval()
    if not results:
        return

    # Run failure analysis
    analysis = failure_analysis(results)
    print()
    print(analysis)

    # Save analysis report
    save_dir = os.path.join(
        os.path.dirname(__file__), "golden_set", "results",
    )
    report_path = os.path.join(save_dir, f"{results['version']}-failure-analysis.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(analysis)
    print(f"\nAnalysis saved: {report_path}")

    # Save combined results + analysis
    results["failure_analysis_text"] = analysis
    combined_path = os.path.join(save_dir, f"{results['version']}-model-affinity.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Full results saved: {combined_path}")


if __name__ == "__main__":
    main()
