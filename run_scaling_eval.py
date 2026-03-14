"""Run scaling eval: Raw Stuffing + Hydration on enterprise corpus (Claude Opus)."""

import os
import sys
import json
import datetime
import time

sys.path.insert(0, os.path.dirname(__file__))

from ctxpack.benchmarks.dotenv import load_dotenv
load_dotenv()

# Override to Anthropic/Opus
os.environ["CTXPACK_EVAL_PROVIDER"] = "anthropic"
os.environ["CTXPACK_EVAL_MODEL"] = "claude-opus-4-6"

from ctxpack.core.packer import pack
from ctxpack.core.serializer import serialize, serialize_section
from ctxpack.core.hydration_protocol import build_system_prompt
from ctxpack.core.hydrator import hydrate_by_name, list_sections
from ctxpack.benchmarks.baselines.raw_stuffing import prepare_raw_context
from ctxpack.benchmarks.metrics.compression import count_tokens
from ctxpack.benchmarks.metrics.cost import count_bpe_tokens, estimate_cost
from ctxpack.benchmarks.metrics.fidelity import (
    _ask_llm, _detect_provider, _grade_answer, _llm_judge,
    load_questions, measure_fidelity,
)

CORPUS = os.path.join("ctxpack", "benchmarks", "scaling", "enterprise_corpus")
QUESTIONS = os.path.join("ctxpack", "benchmarks", "scaling", "enterprise_questions.yaml")
OUTPUT = os.path.join("ctxpack", "benchmarks", "results")


def main():
    provider, api_key, eval_model = _detect_provider()

    questions = load_questions(QUESTIONS)
    raw_text = prepare_raw_context(CORPUS)
    raw_bpe = count_bpe_tokens(raw_text, model=eval_model)

    # Pack
    pack_result = pack(CORPUS)
    doc = pack_result.document
    l3_prompt = build_system_prompt(doc)
    l3_bpe = count_bpe_tokens(l3_prompt, model=eval_model)
    sections = list_sections(doc)
    section_names = [s["name"] for s in sections]

    print("=" * 70)
    print("CtxPack Scaling Eval — Enterprise Corpus — Claude Opus 4.6")
    print("=" * 70)
    print(f"Raw corpus: {raw_bpe:,} BPE tokens")
    print(f"L3 index: {l3_bpe} BPE ({l3_bpe/raw_bpe*100:.1f}% of raw)")
    print(f"Sections: {len(sections)}")
    print(f"Questions: {len(questions)}")
    print()

    results = {
        "experiment": "scaling_eval_enterprise",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": eval_model,
        "corpus": {"raw_bpe": raw_bpe, "l3_bpe": l3_bpe, "sections": len(sections)},
        "methods": [],
        "raw_details": [],
        "hydration_details": [],
        "red_team_checks": [],
    }

    # ═══ ARM 1: Raw Stuffing ═══
    print("ARM 1: Raw Stuffing (30 questions × 85K BPE)...")
    print("  This will take several minutes...")
    t0 = time.time()
    raw_fidelity = measure_fidelity(
        questions, raw_text,
        model=eval_model, api_key=api_key, provider=provider,
    )
    raw_time = time.time() - t0
    raw_cost = estimate_cost(raw_bpe, model=eval_model)

    results["methods"].append({
        "method": "raw_stuffing",
        "bpe_per_query": raw_bpe,
        "fidelity_rule": round(raw_fidelity.score * 100, 1),
        "fidelity_judge": round(raw_fidelity.llm_judge_score * 100, 1),
        "judge_failures": raw_fidelity.judge_failures,
        "cost_per_query": f"${raw_cost.cost_per_query:.4f}",
        "wall_time_s": round(raw_time, 1),
    })
    results["raw_details"] = [
        {"id": r.question_id, "correct": r.correct, "judge": r.llm_judge_correct,
         "judge_error": r.judge_error, "difficulty": r.difficulty, "answer": r.answer[:500]}
        for r in raw_fidelity.results
    ]

    print(f"  Raw: {raw_fidelity.score*100:.0f}% rule, {raw_fidelity.llm_judge_score*100:.0f}% judge"
          f" (judge_failures={raw_fidelity.judge_failures}, {raw_time:.0f}s)")
    print()

    # ═══ Resolve cross-model judge (same as measure_fidelity uses) ═══
    from ctxpack.benchmarks.metrics.fidelity import _resolve_judge_params, _INTER_CALL_DELAY
    j_model, j_key, j_provider = _resolve_judge_params(
        None, None, None, eval_model, api_key, provider
    )
    print(f"Judge: {j_model} ({j_provider})")
    print()

    # ═══ ARM 2: Hydration (multi-turn, equalized pipeline) ═══
    print("ARM 2: Hydration — LLM-as-router (30 questions)...")
    t0 = time.time()
    hydration_details = []
    hyd_judge_failures = 0

    for i, q in enumerate(questions):
        q_id = q.get("id", "")
        question = q.get("question", "")
        expected = q.get("expected", "")
        difficulty = q.get("difficulty", "medium")

        # Step 1: Route (uses same inter-call delay as measure_fidelity)
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
                              model=eval_model, api_key=api_key, provider=provider)
        requested = _parse_sections(route_resp, set(section_names))

        # Step 2: Hydrate
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

        hydrated_bpe = count_bpe_tokens(hydrated_text, model=eval_model)
        total_bpe = l3_bpe + hydrated_bpe

        # Step 3: Answer (with inter-call delay)
        time.sleep(_INTER_CALL_DELAY)
        answer = _ask_llm(question, hydrated_text,
                          model=eval_model, api_key=api_key, provider=provider)

        # Step 3b: Re-hydration if answer is low-confidence
        rehydrated = False
        from ctxpack.core.hydrator import needs_rehydration
        if needs_rehydration(answer) and requested != ["NONE"]:
            # Ask the LLM what additional sections it needs
            time.sleep(_INTER_CALL_DELAY)
            rehyd_prompt = (
                f"Your previous answer was incomplete. The question was: \"{question}\"\n"
                f"You already have context from: {json.dumps(requested)}\n"
                f"Available sections: {json.dumps(section_names)}\n\n"
                f"Which 1-3 ADDITIONAL sections would help you answer fully? "
                f"Respond with ONLY a JSON array. Do not repeat sections you already have."
            )
            rehyd_resp = _ask_llm(rehyd_prompt, l3_prompt,
                                  model=eval_model, api_key=api_key, provider=provider)
            additional = _parse_sections(rehyd_resp, set(section_names))

            # Deduplicate: only add sections not already hydrated
            already_have = set(r.upper() for r in requested)
            new_sections = [s for s in additional if s.upper() not in already_have and s != "NONE"]

            if new_sections:
                rehydrated = True
                rehyd_result = hydrate_by_name(doc, new_sections, include_header=False)
                for section in rehyd_result.sections:
                    for line in serialize_section(section, natural_language=True):
                        hydrated_text += "\n" + line
                requested = requested + new_sections

                # Re-count BPE and re-answer
                hydrated_bpe = count_bpe_tokens(hydrated_text, model=eval_model)
                total_bpe = l3_bpe + hydrated_bpe + 2000  # routing + re-routing calls

                time.sleep(_INTER_CALL_DELAY)
                answer = _ask_llm(question, hydrated_text,
                                  model=eval_model, api_key=api_key, provider=provider)

        # Step 4: Grade with CROSS-MODEL judge (same as raw arm)
        correct_rule = _grade_answer(answer, expected)
        time.sleep(_INTER_CALL_DELAY)
        judge_resp, judge_is_error = _llm_judge(
            question, expected, answer,
            model=j_model, api_key=j_key, provider=j_provider,
        )
        if judge_is_error:
            correct_judge = False
            hyd_judge_failures += 1
        else:
            correct_judge = (
                "CORRECT" in judge_resp.upper()
                and "INCORRECT" not in judge_resp.upper()
            )

        hydration_details.append({
            "id": q_id, "question": question, "expected": expected,
            "difficulty": difficulty, "sections_requested": requested,
            "bpe_total": total_bpe, "correct_rule": correct_rule,
            "correct_judge": correct_judge, "judge_error": judge_is_error,
            "rehydrated": rehydrated,
            "answer": answer[:500],
        })

        status = "Y" if correct_judge else ("E" if judge_is_error else "N")
        rehyd_tag = " [RE-HYD]" if rehydrated else ""
        secs_str = ', '.join(requested[:2])
        if len(secs_str) > 37:
            secs_str = secs_str[:37] + "..."
        print(f"  [{i+1}/30] {q_id} -> {secs_str:<40} {total_bpe:>5} BPE  judge={status}{rehyd_tag}")

    hyd_time = time.time() - t0
    results["hydration_details"] = hydration_details

    # Aggregate
    total_q = len(hydration_details)
    avg_bpe = sum(h["bpe_total"] for h in hydration_details) / total_q
    hyd_rule = sum(1 for h in hydration_details if h["correct_rule"]) / total_q * 100
    hyd_judge = sum(1 for h in hydration_details if h["correct_judge"]) / total_q * 100
    hyd_cost = estimate_cost(int(avg_bpe), model=eval_model)

    results["methods"].append({
        "method": "ctxpack_hydrated",
        "bpe_per_query": int(avg_bpe),
        "fidelity_rule": round(hyd_rule, 1),
        "fidelity_judge": round(hyd_judge, 1),
        "judge_failures": hyd_judge_failures,
        "cost_per_query": f"${hyd_cost.cost_per_query:.4f}",
        "wall_time_s": round(hyd_time, 1),
    })

    print(f"\n  Hydrated: {hyd_rule:.0f}% rule, {hyd_judge:.0f}% judge, avg {avg_bpe:.0f} BPE ({hyd_time:.0f}s)")

    # ═══ RED TEAM CHECKS ═══
    rt = []

    # RT1: BPE/word ratio
    rt.append({"name": "RT1: L3 BPE budget", "passed": l3_bpe < raw_bpe * 0.1,
               "actual": f"{l3_bpe/raw_bpe*100:.1f}%", "threshold": "<10%"})

    # RT2: Hydration cost savings
    cost_ratio = avg_bpe / raw_bpe * 100
    rt.append({"name": "RT2: Hydration cost vs raw", "passed": cost_ratio <= 20,
               "actual": f"{cost_ratio:.1f}%", "threshold": "<=20%"})

    # RT3: Hydration fidelity floor
    rt.append({"name": "RT3: Hydration fidelity floor", "passed": hyd_judge >= 50,
               "actual": f"{hyd_judge:.0f}%", "threshold": ">=50%"})

    # RT4: Fidelity comparison (the crossover test)
    raw_judge = raw_fidelity.llm_judge_score * 100
    fidelity_gap = raw_judge - hyd_judge
    rt.append({"name": "RT4: Fidelity gap (raw - hydrated)", "passed": fidelity_gap <= 15,
               "actual": f"{fidelity_gap:.0f}pp", "threshold": "<=15pp"})

    # RT5: Rule/Judge divergence
    divergence = abs(hyd_rule - hyd_judge)
    rt.append({"name": "RT5: Rule/Judge divergence", "passed": divergence <= 30,
               "actual": f"{divergence:.0f}pp", "threshold": "<=30pp"})

    # RT6: Judge failure rate (both arms)
    total_judged = len(raw_fidelity.results) + total_q
    total_failures = raw_fidelity.judge_failures + hyd_judge_failures
    failure_rate = total_failures / total_judged * 100 if total_judged > 0 else 0
    rt.append({"name": "RT6: Judge failure rate", "passed": failure_rate <= 10,
               "actual": f"{failure_rate:.1f}% ({total_failures}/{total_judged})",
               "threshold": "<=10%"})

    results["red_team_checks"] = rt

    print()
    print("=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print()
    print(f"{'Method':<25} {'BPE/Q':>10} {'Cmpr':>7} {'Fid-R':>7} {'Fid-J':>7} {'J-Fail':>7} {'Cost':>10}")
    print("-" * 78)
    for m in results["methods"]:
        comp = f"{raw_bpe/m['bpe_per_query']:.1f}x"
        jf = m.get('judge_failures', 0)
        print(f"{m['method']:<25} {m['bpe_per_query']:>10,} {comp:>7} "
              f"{m['fidelity_rule']:>6.1f}% {m['fidelity_judge']:>6.1f}% {jf:>7} {m['cost_per_query']:>10}")

    print()
    print("RED TEAM CHECKS:")
    for c in rt:
        status = "PASS" if c["passed"] else "FAIL"
        print(f"  [{status}] {c['name']}: {c['actual']} (threshold: {c['threshold']})")

    # Difficulty breakdown
    print()
    print("Fidelity by difficulty (judge):")
    for diff in ["easy", "medium", "hard"]:
        raw_d = [r for r in raw_fidelity.results if r.difficulty == diff]
        hyd_d = [h for h in hydration_details if h["difficulty"] == diff]
        if raw_d:
            raw_pct = sum(1 for r in raw_d if r.llm_judge_correct) / len(raw_d) * 100
            hyd_pct = sum(1 for h in hyd_d if h["correct_judge"]) / len(hyd_d) * 100
            print(f"  {diff:<8} Raw={raw_pct:.0f}%  Hydrated={hyd_pct:.0f}%  ({len(raw_d)} Qs)")

    # Save
    os.makedirs(OUTPUT, exist_ok=True)
    path = os.path.join(OUTPUT, "scaling_eval.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {path}")


def _parse_sections(response, valid_names):
    import re
    clean = response.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(clean)
        if isinstance(parsed, list):
            return [s for s in parsed if s in valid_names or s == "NONE"]
    except (json.JSONDecodeError, ValueError):
        pass
    found = re.findall(r'"(ENTITY-[\w-]+)"', response)
    if not found:
        found = re.findall(r'"([\w-]+)"', response)
    return [s for s in found if s in valid_names] if found else ["NONE"]


if __name__ == "__main__":
    main()
