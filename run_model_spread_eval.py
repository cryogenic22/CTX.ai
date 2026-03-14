"""Run scaling eval on smaller models to test the Wang & Sun prediction.

Hypothesis: smaller models have lower interference resistance, so:
  - Raw stuffing fidelity drops (more interference = more errors)
  - Hydration fidelity stays constant (always ~3.5K BPE focused context)
  - At some model size, hydration crosses over raw

Models tested:
  - Claude Haiku 4.5 (small, cheap, fast)
  - GPT-4o-mini (small, cheap, fast)

Both use GPT-4o as cross-model judge for consistency with the Opus eval.
"""

import os
import sys
import json
import datetime
import time
import re

sys.path.insert(0, os.path.dirname(__file__))

from ctxpack.benchmarks.dotenv import load_dotenv
load_dotenv()

from ctxpack.core.packer import pack
from ctxpack.core.serializer import serialize, serialize_section
from ctxpack.core.hydration_protocol import build_system_prompt
from ctxpack.core.hydrator import hydrate_by_name, list_sections
from ctxpack.benchmarks.baselines.raw_stuffing import prepare_raw_context
from ctxpack.benchmarks.metrics.compression import count_tokens
from ctxpack.benchmarks.metrics.cost import count_bpe_tokens, estimate_cost
from ctxpack.benchmarks.metrics.fidelity import (
    _ask_llm, _detect_provider, _grade_answer, _llm_judge,
    _resolve_judge_params, _INTER_CALL_DELAY,
    load_questions, measure_fidelity,
)

CORPUS = os.path.join("ctxpack", "benchmarks", "scaling", "enterprise_corpus")
QUESTIONS = os.path.join("ctxpack", "benchmarks", "scaling", "enterprise_questions.yaml")
OUTPUT = os.path.join("ctxpack", "benchmarks", "results")

MODELS = [
    ("anthropic", "claude-haiku-4-5-20251001", "Haiku 4.5"),
    ("openai", "gpt-4o-mini", "GPT-4o-mini"),
]


def run_arm_raw(questions, raw_text, raw_bpe, model, api_key, provider):
    """Run raw stuffing arm with cross-model judge."""
    print(f"  Raw Stuffing ({len(questions)} Qs x {raw_bpe:,} BPE)...")
    t0 = time.time()
    fidelity = measure_fidelity(
        questions, raw_text,
        model=model, api_key=api_key, provider=provider,
    )
    elapsed = time.time() - t0
    print(f"    {fidelity.score*100:.0f}% rule, {fidelity.llm_judge_score*100:.0f}% judge "
          f"(judge_failures={fidelity.judge_failures}, {elapsed:.0f}s)")
    return fidelity, elapsed


def run_arm_hydration(questions, doc, l3_prompt, l3_bpe, section_names,
                      model, api_key, provider, j_model, j_key, j_provider):
    """Run hydration arm with cross-model judge, equalized pipeline."""
    print(f"  Hydration ({len(questions)} Qs, LLM-as-router)...")
    t0 = time.time()
    details = []
    judge_failures = 0

    for i, q in enumerate(questions):
        q_id = q.get("id", "")
        question = q.get("question", "")
        expected = q.get("expected", "")
        difficulty = q.get("difficulty", "medium")

        # Route
        time.sleep(_INTER_CALL_DELAY)
        routing_prompt = (
            f"You have a knowledge base with these sections:\n"
            f"{json.dumps(section_names)}\n\n"
            f"Question: \"{question}\"\n\n"
            f"Which 1-3 sections should be retrieved? "
            f"Respond with ONLY a JSON array, e.g. [\"ENTITY-CUSTOMER\"]. "
            f"If the answer isn't in the knowledge base, respond [\"NONE\"]."
        )
        route_resp = _ask_llm(routing_prompt, l3_prompt,
                              model=model, api_key=api_key, provider=provider)
        requested = _parse_sections(route_resp, set(section_names))

        # Hydrate
        if requested and requested != ["NONE"]:
            hydration = hydrate_by_name(doc, requested, include_header=True)
            lines = []
            if hydration.header_text:
                lines.append(hydration.header_text)
            for section in hydration.sections:
                for line in serialize_section(section, natural_language=True):
                    lines.append(line)
            hydrated_text = "\n".join(lines)
        else:
            hydrated_text = l3_prompt

        hydrated_bpe = count_bpe_tokens(hydrated_text, model=model)
        total_bpe = l3_bpe + hydrated_bpe

        # Answer
        time.sleep(_INTER_CALL_DELAY)
        answer = _ask_llm(question, hydrated_text,
                          model=model, api_key=api_key, provider=provider)

        # Grade (cross-model judge)
        correct_rule = _grade_answer(answer, expected)
        time.sleep(_INTER_CALL_DELAY)
        judge_resp, judge_is_error = _llm_judge(
            question, expected, answer,
            model=j_model, api_key=j_key, provider=j_provider,
        )
        if judge_is_error:
            correct_judge = False
            judge_failures += 1
        else:
            correct_judge = (
                "CORRECT" in judge_resp.upper()
                and "INCORRECT" not in judge_resp.upper()
            )

        details.append({
            "id": q_id, "question": question, "expected": expected,
            "difficulty": difficulty, "sections_requested": requested,
            "bpe_total": total_bpe, "correct_rule": correct_rule,
            "correct_judge": correct_judge, "judge_error": judge_is_error,
            "answer": answer[:500],
        })

        status = "Y" if correct_judge else ("E" if judge_is_error else "N")
        print(f"    [{i+1}/{len(questions)}] {q_id} judge={status}")

    elapsed = time.time() - t0
    total_q = len(details)
    avg_bpe = sum(d["bpe_total"] for d in details) / total_q if total_q else 0
    rule_pct = sum(1 for d in details if d["correct_rule"]) / total_q * 100 if total_q else 0
    judge_pct = sum(1 for d in details if d["correct_judge"]) / total_q * 100 if total_q else 0

    print(f"    {rule_pct:.0f}% rule, {judge_pct:.0f}% judge "
          f"(judge_failures={judge_failures}, avg {avg_bpe:.0f} BPE, {elapsed:.0f}s)")
    return details, judge_failures, elapsed


def _parse_sections(response, valid_names):
    clean = response.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(clean)
        if isinstance(parsed, list):
            return [s for s in parsed if s in valid_names or s == "NONE"]
    except (json.JSONDecodeError, ValueError):
        pass
    found = re.findall(r'"([\w-]+)"', response)
    return [s for s in found if s in valid_names] if found else ["NONE"]


def main():
    questions = load_questions(QUESTIONS)
    raw_text = prepare_raw_context(CORPUS)
    raw_bpe_gpt4o = count_bpe_tokens(raw_text, model="gpt-4o")

    pack_result = pack(CORPUS)
    doc = pack_result.document
    l3_prompt = build_system_prompt(doc)
    l3_bpe = count_bpe_tokens(l3_prompt, model="gpt-4o")
    sections = list_sections(doc)
    section_names = [s["name"] for s in sections]

    # Judge is always GPT-4o (cross-model, consistent with Opus eval)
    j_key = os.environ.get("OPENAI_API_KEY", "")
    j_model = "gpt-4o"
    j_provider = "openai"

    print("=" * 70)
    print("CtxPack Model Spread Eval — Wang & Sun Interference Test")
    print("=" * 70)
    print(f"Corpus: {raw_bpe_gpt4o:,} BPE | L3: {l3_bpe} BPE | Sections: {len(sections)}")
    print(f"Judge: {j_model} ({j_provider}) — same for all models")
    print(f"Questions: {len(questions)}")
    print()

    all_results = {
        "experiment": "model_spread_interference_test",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "judge": f"{j_model} ({j_provider})",
        "corpus_bpe": raw_bpe_gpt4o,
        "models": [],
    }

    # Also include Opus results from the saved file
    opus_path = os.path.join(OUTPUT, "scaling_eval.json")
    if os.path.exists(opus_path):
        with open(opus_path) as f:
            opus_data = json.load(f)
        opus_methods = {m["method"]: m for m in opus_data.get("methods", [])}
        raw_opus = opus_methods.get("raw_stuffing", {})
        hyd_opus = opus_methods.get("ctxpack_hydrated", {})
        all_results["models"].append({
            "model": "claude-opus-4-6",
            "label": "Opus 4.6",
            "provider": "anthropic",
            "params": "~2T (estimated)",
            "raw_judge": raw_opus.get("fidelity_judge", 0),
            "raw_rule": raw_opus.get("fidelity_rule", 0),
            "hyd_judge": hyd_opus.get("fidelity_judge", 0),
            "hyd_rule": hyd_opus.get("fidelity_rule", 0),
            "hyd_bpe": hyd_opus.get("bpe_per_query", 0),
            "raw_judge_failures": raw_opus.get("judge_failures", 0),
            "hyd_judge_failures": hyd_opus.get("judge_failures", 0),
            "source": "prior_run",
        })
        print(f"Opus 4.6 (from prior run): raw={raw_opus.get('fidelity_judge',0):.1f}% hyd={hyd_opus.get('fidelity_judge',0):.1f}%")
        print()

    for provider, model, label in MODELS:
        print(f"--- {label} ({model}) ---")
        api_key = os.environ.get(
            "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY", ""
        )
        if not api_key:
            print(f"  SKIP — no API key for {provider}")
            continue

        # Raw arm
        raw_fidelity, raw_time = run_arm_raw(
            questions, raw_text, raw_bpe_gpt4o, model, api_key, provider
        )

        # Hydration arm
        hyd_details, hyd_jf, hyd_time = run_arm_hydration(
            questions, doc, l3_prompt, l3_bpe, section_names,
            model, api_key, provider, j_model, j_key, j_provider,
        )

        total_q = len(hyd_details)
        avg_bpe = sum(d["bpe_total"] for d in hyd_details) / total_q if total_q else 0
        hyd_judge_pct = sum(1 for d in hyd_details if d["correct_judge"]) / total_q * 100
        hyd_rule_pct = sum(1 for d in hyd_details if d["correct_rule"]) / total_q * 100

        all_results["models"].append({
            "model": model,
            "label": label,
            "provider": provider,
            "raw_judge": round(raw_fidelity.llm_judge_score * 100, 1),
            "raw_rule": round(raw_fidelity.score * 100, 1),
            "hyd_judge": round(hyd_judge_pct, 1),
            "hyd_rule": round(hyd_rule_pct, 1),
            "hyd_bpe": int(avg_bpe),
            "raw_judge_failures": raw_fidelity.judge_failures,
            "hyd_judge_failures": hyd_jf,
            "raw_time": round(raw_time, 1),
            "hyd_time": round(hyd_time, 1),
            "hyd_details": hyd_details,
        })
        print()

    # Summary
    print("=" * 70)
    print("MODEL SPREAD RESULTS — Interference Test")
    print("=" * 70)
    print()
    print(f"Corpus: {raw_bpe_gpt4o:,} BPE | Judge: {j_model}")
    print()
    print(f"{'Model':<20} {'Raw-J':>7} {'Hyd-J':>7} {'Gap':>7} {'Hyd BPE':>9} {'Compress':>9} {'J-Fail':>7}")
    print("-" * 72)
    for m in all_results["models"]:
        gap = m["raw_judge"] - m["hyd_judge"]
        comp = f"{raw_bpe_gpt4o / m['hyd_bpe']:.1f}x" if m['hyd_bpe'] > 0 else "N/A"
        total_jf = m.get("raw_judge_failures", 0) + m.get("hyd_judge_failures", 0)
        print(f"{m['label']:<20} {m['raw_judge']:>6.1f}% {m['hyd_judge']:>6.1f}% "
              f"{gap:>+6.1f}pp {m['hyd_bpe']:>9,} {comp:>9} {total_jf:>7}")

    # Difficulty breakdown per model
    print()
    print("By difficulty (judge fidelity):")
    for m in all_results["models"]:
        if "hyd_details" not in m:
            continue
        print(f"\n  {m['label']}:")
        for diff in ["easy", "medium", "hard"]:
            hyd_d = [d for d in m["hyd_details"] if d["difficulty"] == diff]
            if hyd_d:
                hyd_pct = sum(1 for d in hyd_d if d["correct_judge"]) / len(hyd_d) * 100
                print(f"    {diff:<8} Hyd={hyd_pct:.0f}% ({len(hyd_d)} Qs)")

    # Save
    # Strip large answer text from saved details
    for m in all_results["models"]:
        if "hyd_details" in m:
            for d in m["hyd_details"]:
                d["answer"] = d.get("answer", "")[:200]

    os.makedirs(OUTPUT, exist_ok=True)
    path = os.path.join(OUTPUT, "model_spread_eval.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved: {path}")


if __name__ == "__main__":
    main()
