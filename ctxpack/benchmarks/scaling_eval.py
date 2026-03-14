"""Scaling Evaluation — Tests CtxPack at enterprise corpus scale (50K+ tokens).

Proves the hypothesis: at large corpora, hydration beats raw stuffing on
both cost AND fidelity because:
  1. Raw stuffing suffers from lost-in-the-middle
  2. Hydration always injects ~800 BPE of focused context
  3. The cost ratio grows linearly with corpus size

Includes built-in RED TEAM checks that validate results as they're generated:
  - RT1: BPE/word ratio sanity (no metric gaming)
  - RT2: L3 size must be <10% of corpus BPE
  - RT3: Hydration avg BPE must be <20% of corpus BPE
  - RT4: If hydrated fidelity < 50%, flag as architecture failure
  - RT5: Cross-check rule-based vs judge scores (>30pp divergence = grading bug)
"""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from .dotenv import load_dotenv
from .metrics.compression import count_tokens
from .metrics.cost import count_bpe_tokens, estimate_cost


@dataclass
class RedTeamCheck:
    """Result of a built-in red team validation."""
    name: str
    passed: bool
    message: str
    threshold: str
    actual: str


def run_scaling_eval(
    corpus_dir: str,
    questions_path: str,
    *,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    eval_model: str = "claude-opus-4-6",
) -> dict[str, Any]:
    """Run the scaling evaluation with built-in red team checks."""
    from ..core.hydrator import hydrate_by_name, list_sections
    from ..core.hydration_protocol import build_system_prompt
    from ..core.packer import pack
    from ..core.serializer import serialize, serialize_section
    from .baselines.raw_stuffing import prepare_raw_context
    from .metrics.fidelity import (
        _ask_llm,
        _detect_provider,
        _grade_answer,
        _llm_judge,
        load_questions,
        measure_fidelity,
    )

    load_dotenv()

    if api_key is None:
        det_provider, det_key, det_model = _detect_provider()
        provider = provider or det_provider
        api_key = det_key
        eval_model = det_model or eval_model

    questions = load_questions(questions_path)

    # ── Source metrics ──
    raw_text = prepare_raw_context(corpus_dir)
    source_words = count_tokens(raw_text)
    source_bpe = count_bpe_tokens(raw_text, model=eval_model)

    # ── Pack ──
    print(f"Packing corpus ({source_words} words, {source_bpe} BPE)...")
    pack_result = pack(corpus_dir)
    doc = pack_result.document

    nl_text = serialize(doc, natural_language=True)
    nl_bpe = count_bpe_tokens(nl_text, model=eval_model)
    nl_words = count_tokens(nl_text)

    l3_prompt = build_system_prompt(doc)
    l3_bpe = count_bpe_tokens(l3_prompt, model=eval_model)

    sections = list_sections(doc)

    print(f"Packed: {nl_words} words, {nl_bpe} BPE ({source_bpe/nl_bpe:.2f}x)")
    print(f"L3 index: {l3_bpe} BPE ({l3_bpe/source_bpe*100:.1f}% of source)")
    print(f"Sections: {len(sections)}")
    print()

    # ── RED TEAM checks (pre-eval) ──
    rt_checks: list[RedTeamCheck] = []

    # RT1: BPE/word ratio
    bpe_word_ratio = nl_bpe / nl_words if nl_words > 0 else 999
    rt_checks.append(RedTeamCheck(
        name="RT1: BPE/word ratio",
        passed=bpe_word_ratio <= 5.0,
        message=f"NL prose BPE/word ratio is {bpe_word_ratio:.1f}",
        threshold="<= 5.0",
        actual=f"{bpe_word_ratio:.1f}",
    ))

    # RT2: L3 size
    l3_pct = l3_bpe / source_bpe * 100 if source_bpe > 0 else 999
    rt_checks.append(RedTeamCheck(
        name="RT2: L3 size vs corpus",
        passed=l3_pct <= 10,
        message=f"L3 is {l3_pct:.1f}% of source corpus",
        threshold="<= 10%",
        actual=f"{l3_pct:.1f}%",
    ))

    results: dict[str, Any] = {
        "experiment": "scaling_eval",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": eval_model,
        "corpus": {
            "word_tokens": source_words,
            "bpe_tokens": source_bpe,
            "packed_words": nl_words,
            "packed_bpe": nl_bpe,
            "bpe_compression": round(source_bpe / nl_bpe, 2) if nl_bpe > 0 else 0,
            "l3_bpe": l3_bpe,
            "sections": len(sections),
        },
        "methods": [],
        "hydration_details": [],
        "red_team_checks": [],
    }

    if not api_key:
        print("No API key — offline metrics only.")
        results["red_team_checks"] = [
            {"name": c.name, "passed": c.passed, "message": c.message}
            for c in rt_checks
        ]
        return results

    # ── Raw Stuffing ──
    print("Running: Raw Stuffing...")
    raw_fidelity = measure_fidelity(
        questions, raw_text,
        model=eval_model, api_key=api_key, provider=provider,
    )
    results["methods"].append({
        "method": "raw_stuffing",
        "bpe_tokens": source_bpe,
        "bpe_compression": "1.00x",
        "fidelity_rule": round(raw_fidelity.score * 100, 1),
        "fidelity_judge": round(raw_fidelity.llm_judge_score * 100, 1),
        "cost_per_query": f"${estimate_cost(source_bpe, model=eval_model).cost_per_query:.4f}",
    })
    print(f"  Raw: {raw_fidelity.score*100:.0f}% rule, {raw_fidelity.llm_judge_score*100:.0f}% judge")

    # ── NL Prose (full injection) ──
    print("Running: NL Prose (full)...")
    nl_fidelity = measure_fidelity(
        questions, nl_text,
        model=eval_model, api_key=api_key, provider=provider,
    )
    results["methods"].append({
        "method": "ctxpack_nl_prose",
        "bpe_tokens": nl_bpe,
        "bpe_compression": f"{source_bpe/nl_bpe:.2f}x" if nl_bpe > 0 else "N/A",
        "fidelity_rule": round(nl_fidelity.score * 100, 1),
        "fidelity_judge": round(nl_fidelity.llm_judge_score * 100, 1),
        "cost_per_query": f"${estimate_cost(nl_bpe, model=eval_model).cost_per_query:.4f}",
    })
    print(f"  NL: {nl_fidelity.score*100:.0f}% rule, {nl_fidelity.llm_judge_score*100:.0f}% judge")

    # ── Hydration (multi-turn) ──
    print("Running: Hydration (multi-turn)...")
    section_names = [s["name"] for s in sections]
    hydration_details = []
    import json as _json

    for q in questions:
        q_id = q.get("id", "")
        question = q.get("question", "")
        expected = q.get("expected", "")
        difficulty = q.get("difficulty", "medium")

        # Step 1: Route
        routing_prompt = (
            f"You have a knowledge base with these sections:\n"
            f"{_json.dumps(section_names)}\n\n"
            f"Question: \"{question}\"\n\n"
            f"Which 1-3 sections should be retrieved? "
            f"Respond with ONLY a JSON array, e.g. [\"ENTITY-CUSTOMER\"]. "
            f"If the answer isn't in the knowledge base, respond [\"NONE\"]."
        )

        response = _ask_llm(routing_prompt, l3_prompt,
                            model=eval_model, api_key=api_key, provider=provider)

        # Parse sections
        requested = _parse_sections(response, set(section_names))

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

        # Step 3: Answer
        answer = _ask_llm(question, hydrated_text,
                          model=eval_model, api_key=api_key, provider=provider)

        # Step 4: Grade
        correct_rule = _grade_answer(answer, expected)
        correct_judge = _llm_judge(question, expected, answer,
                                   model=eval_model, api_key=api_key, provider=provider)

        hydration_details.append({
            "id": q_id, "question": question, "expected": expected,
            "difficulty": difficulty, "sections_requested": requested,
            "bpe_total": total_bpe, "correct_rule": correct_rule,
            "correct_judge": correct_judge, "answer": answer,
        })

    results["hydration_details"] = hydration_details

    # Aggregate hydration
    total_q = len(hydration_details)
    if total_q > 0:
        avg_bpe = sum(h["bpe_total"] for h in hydration_details) / total_q
        hyd_rule = sum(1 for h in hydration_details if h["correct_rule"]) / total_q * 100
        hyd_judge = sum(1 for h in hydration_details if h["correct_judge"]) / total_q * 100

        results["methods"].append({
            "method": "ctxpack_hydrated",
            "bpe_tokens": int(avg_bpe),
            "bpe_compression": f"{source_bpe/avg_bpe:.1f}x" if avg_bpe > 0 else "N/A",
            "fidelity_rule": round(hyd_rule, 1),
            "fidelity_judge": round(hyd_judge, 1),
            "cost_per_query": f"${estimate_cost(int(avg_bpe), model=eval_model).cost_per_query:.4f}",
        })
        print(f"  Hydrated: {hyd_rule:.0f}% rule, {hyd_judge:.0f}% judge, avg {avg_bpe:.0f} BPE")

        # RT3: Hydration cost
        hyd_pct = avg_bpe / source_bpe * 100
        rt_checks.append(RedTeamCheck(
            name="RT3: Hydration cost vs raw",
            passed=hyd_pct <= 20,
            message=f"Avg hydration is {hyd_pct:.1f}% of raw corpus",
            threshold="<= 20%",
            actual=f"{hyd_pct:.1f}%",
        ))

        # RT4: Hydration fidelity floor
        rt_checks.append(RedTeamCheck(
            name="RT4: Hydration fidelity floor",
            passed=hyd_judge >= 50,
            message=f"Hydration judge fidelity is {hyd_judge:.0f}%",
            threshold=">= 50%",
            actual=f"{hyd_judge:.0f}%",
        ))

        # RT5: Rule vs Judge divergence
        divergence = abs(hyd_rule - hyd_judge)
        rt_checks.append(RedTeamCheck(
            name="RT5: Rule/Judge divergence",
            passed=divergence <= 30,
            message=f"Rule ({hyd_rule:.0f}%) vs Judge ({hyd_judge:.0f}%) diverge by {divergence:.0f}pp",
            threshold="<= 30pp",
            actual=f"{divergence:.0f}pp",
        ))

    # Print red team results
    print()
    print("=== RED TEAM CHECKS ===")
    for c in rt_checks:
        status = "PASS" if c.passed else "FAIL"
        print(f"  [{status}] {c.name}: {c.message} (threshold: {c.threshold})")

    results["red_team_checks"] = [
        {"name": c.name, "passed": c.passed, "message": c.message,
         "threshold": c.threshold, "actual": c.actual}
        for c in rt_checks
    ]

    return results


def _parse_sections(response: str, valid_names: set[str]) -> list[str]:
    """Parse section names from LLM routing response."""
    import json as _json
    import re

    clean = response.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = _json.loads(clean)
        if isinstance(parsed, list):
            return [s for s in parsed if s in valid_names or s == "NONE"]
    except (_json.JSONDecodeError, ValueError):
        pass

    found = re.findall(r'"(ENTITY-[\w-]+)"', response)
    return [s for s in found if s in valid_names] if found else ["NONE"]


def save_scaling_eval(results: dict[str, Any], output_dir: str) -> str:
    """Save results."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "scaling_eval.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    return path
