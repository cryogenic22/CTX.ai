"""Definitive CtxPack Evaluation — Fresh Benchmark (v0.4.0)

Tests the corrected architecture:
  1. Raw stuffing baseline (control)
  2. CtxPack L2 notation (legacy — for comparison)
  3. CtxPack NL prose (new — BPE-efficient serialization)
  4. CtxPack NL prose + hydration (the full architecture)

All metrics use BPE tokens (tiktoken cl100k_base) as the primary unit.
Word counts are reported as secondary/reference only.

The hydration eval simulates the LLM-as-router flow:
  - L3 map in system prompt
  - LLM decides which sections to hydrate (no pre-selection cheating)
  - Hydrated sections injected as context
  - LLM answers the question
"""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .dotenv import load_dotenv
from .metrics.compression import count_corpus_bpe, count_corpus_tokens, count_tokens
from .metrics.cost import count_bpe_tokens, estimate_cost


@dataclass
class EvalPoint:
    """One data point in the evaluation."""

    method: str
    bpe_tokens: int
    word_tokens: int
    bpe_compression: float  # vs raw corpus BPE
    fidelity_rule: float
    fidelity_judge: float
    cost_per_query: float
    model: str = ""
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "bpe_tokens": self.bpe_tokens,
            "word_tokens": self.word_tokens,
            "bpe_compression": f"{self.bpe_compression:.2f}x",
            "fidelity_rule": round(self.fidelity_rule, 1),
            "fidelity_judge": round(self.fidelity_judge, 1),
            "cost_per_query": f"${self.cost_per_query:.4f}",
            "model": self.model,
            "details": self.details,
        }


@dataclass
class HydrationPoint:
    """Per-question hydration result."""

    question_id: str
    question: str
    expected: str
    difficulty: str
    # What the LLM chose to hydrate (no cheating)
    sections_requested: list[str]
    bpe_l3: int
    bpe_hydrated: int
    bpe_total: int
    fidelity_rule: bool
    fidelity_judge: bool
    answer: str = ""


def run_definitive_eval(
    corpus_dir: str,
    *,
    questions_path: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    eval_model: str = "gpt-4o",
) -> dict[str, Any]:
    """Run the definitive evaluation across all methods.

    Returns a complete results dict suitable for the whitepaper.
    """
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

    # Auto-detect provider
    if api_key is None:
        det_provider, det_key, det_model = _detect_provider()
        provider = provider or det_provider
        api_key = det_key
        eval_model = det_model or eval_model

    # Load questions
    if questions_path is None:
        questions_path = os.path.join(
            os.path.dirname(__file__), "ctxpack_eval", "questions.yaml"
        )
    questions = load_questions(questions_path) if os.path.exists(questions_path) else []

    # ── Source metrics (BPE-primary) ──
    raw_text = prepare_raw_context(corpus_dir)
    source_words = count_tokens(raw_text)
    source_bpe = count_bpe_tokens(raw_text, model=eval_model)

    # ── Pack corpus ──
    pack_result = pack(corpus_dir)
    doc = pack_result.document

    # Serialize in all modes
    l2_text = serialize(doc)
    nl_text = serialize(doc, natural_language=True)

    l2_bpe = count_bpe_tokens(l2_text, model=eval_model)
    nl_bpe = count_bpe_tokens(nl_text, model=eval_model)
    l2_words = count_tokens(l2_text)
    nl_words = count_tokens(nl_text)

    # L3 system prompt for hydration
    from ..core.packer.compressor import count_tokens as ast_count
    l3_prompt = build_system_prompt(doc)
    l3_bpe = count_bpe_tokens(l3_prompt, model=eval_model)

    points: list[EvalPoint] = []

    print(f"Source: {source_words} words, {source_bpe} BPE")
    print(f"L2 notation: {l2_words} words, {l2_bpe} BPE ({source_bpe/l2_bpe:.2f}x)")
    print(f"NL prose: {nl_words} words, {nl_bpe} BPE ({source_bpe/nl_bpe:.2f}x)")
    print(f"L3 system prompt: {l3_bpe} BPE")
    print()

    if not api_key:
        print("No API key — returning offline metrics only.")
        for label, bpe, words in [
            ("raw_stuffing", source_bpe, source_words),
            ("ctxpack_l2", l2_bpe, l2_words),
            ("ctxpack_nl_prose", nl_bpe, nl_words),
        ]:
            cost = estimate_cost(bpe, model=eval_model)
            points.append(EvalPoint(
                method=label, bpe_tokens=bpe, word_tokens=words,
                bpe_compression=source_bpe / bpe if bpe > 0 else 0,
                fidelity_rule=0, fidelity_judge=0,
                cost_per_query=cost.cost_per_query, model=eval_model,
            ))
        return _build_results(points, [], source_bpe, source_words, eval_model)

    # ── Baseline 1: Raw Stuffing ──
    print("Running: Raw Stuffing baseline...")
    raw_fidelity = measure_fidelity(
        questions, raw_text,
        model=eval_model, api_key=api_key, provider=provider,
    )
    raw_cost = estimate_cost(source_bpe, model=eval_model)
    points.append(EvalPoint(
        method="raw_stuffing",
        bpe_tokens=source_bpe, word_tokens=source_words,
        bpe_compression=1.0,
        fidelity_rule=raw_fidelity.score * 100,
        fidelity_judge=raw_fidelity.llm_judge_score * 100,
        cost_per_query=raw_cost.cost_per_query,
        model=eval_model,
        details=[{"id": r.question_id, "correct": r.correct,
                  "judge": r.llm_judge_correct, "difficulty": r.difficulty}
                 for r in raw_fidelity.results],
    ))
    print(f"  Raw: {raw_fidelity.score*100:.0f}% rule, {raw_fidelity.llm_judge_score*100:.0f}% judge")

    # ── Baseline 2: CtxPack L2 notation ──
    print("Running: CtxPack L2 notation...")
    l2_fidelity = measure_fidelity(
        questions, l2_text,
        model=eval_model, api_key=api_key, provider=provider,
    )
    l2_cost = estimate_cost(l2_bpe, model=eval_model)
    points.append(EvalPoint(
        method="ctxpack_l2",
        bpe_tokens=l2_bpe, word_tokens=l2_words,
        bpe_compression=source_bpe / l2_bpe if l2_bpe > 0 else 0,
        fidelity_rule=l2_fidelity.score * 100,
        fidelity_judge=l2_fidelity.llm_judge_score * 100,
        cost_per_query=l2_cost.cost_per_query,
        model=eval_model,
        details=[{"id": r.question_id, "correct": r.correct,
                  "judge": r.llm_judge_correct, "difficulty": r.difficulty}
                 for r in l2_fidelity.results],
    ))
    print(f"  L2: {l2_fidelity.score*100:.0f}% rule, {l2_fidelity.llm_judge_score*100:.0f}% judge")

    # ── Test: CtxPack NL Prose (full injection) ──
    print("Running: CtxPack NL Prose...")
    nl_fidelity = measure_fidelity(
        questions, nl_text,
        model=eval_model, api_key=api_key, provider=provider,
    )
    nl_cost = estimate_cost(nl_bpe, model=eval_model)
    points.append(EvalPoint(
        method="ctxpack_nl_prose",
        bpe_tokens=nl_bpe, word_tokens=nl_words,
        bpe_compression=source_bpe / nl_bpe if nl_bpe > 0 else 0,
        fidelity_rule=nl_fidelity.score * 100,
        fidelity_judge=nl_fidelity.llm_judge_score * 100,
        cost_per_query=nl_cost.cost_per_query,
        model=eval_model,
        details=[{"id": r.question_id, "correct": r.correct,
                  "judge": r.llm_judge_correct, "difficulty": r.difficulty}
                 for r in nl_fidelity.results],
    ))
    print(f"  NL: {nl_fidelity.score*100:.0f}% rule, {nl_fidelity.llm_judge_score*100:.0f}% judge")

    # ── Test: CtxPack NL Prose + Hydration (multi-turn) ──
    print("Running: CtxPack NL Prose + Hydration (multi-turn)...")
    hydration_results = _run_hydration_multiturn(
        doc=doc,
        questions=questions,
        l3_prompt=l3_prompt,
        l3_bpe=l3_bpe,
        eval_model=eval_model,
        api_key=api_key,
        provider=provider,
    )

    if hydration_results:
        total = len(hydration_results)
        avg_bpe = sum(h.bpe_total for h in hydration_results) / total
        rule_score = sum(1 for h in hydration_results if h.fidelity_rule) / total * 100
        judge_score = sum(1 for h in hydration_results if h.fidelity_judge) / total * 100
        avg_cost = estimate_cost(int(avg_bpe), model=eval_model)

        points.append(EvalPoint(
            method="ctxpack_nl_hydrated",
            bpe_tokens=int(avg_bpe), word_tokens=0,
            bpe_compression=source_bpe / avg_bpe if avg_bpe > 0 else 0,
            fidelity_rule=rule_score,
            fidelity_judge=judge_score,
            cost_per_query=avg_cost.cost_per_query,
            model=eval_model,
            details=[{"id": h.question_id, "sections": h.sections_requested,
                      "bpe_total": h.bpe_total, "correct": h.fidelity_rule,
                      "judge": h.fidelity_judge, "difficulty": h.difficulty}
                     for h in hydration_results],
        ))
        print(f"  Hydrated: {rule_score:.0f}% rule, {judge_score:.0f}% judge, avg {avg_bpe:.0f} BPE/query")

    return _build_results(points, hydration_results, source_bpe, source_words, eval_model)


def _run_hydration_multiturn(
    doc,
    questions: list[dict],
    l3_prompt: str,
    l3_bpe: int,
    eval_model: str,
    api_key: str,
    provider: str,
) -> list[HydrationPoint]:
    """Run multi-turn hydration: LLM reads L3, decides what to hydrate, answers.

    This is the REAL test — no pre-selected sections. The LLM must decide
    what to retrieve based on the L3 map + question.
    """
    from ..core.hydrator import hydrate_by_name, list_sections
    from ..core.serializer import serialize_section
    from .metrics.cost import count_bpe_tokens
    from .metrics.fidelity import _grade_answer, _llm_judge

    import json as _json
    import urllib.request

    sections = list_sections(doc)
    section_names = [s["name"] for s in sections]

    results: list[HydrationPoint] = []

    for q in questions:
        q_id = q.get("id", "")
        question = q.get("question", "")
        expected = q.get("expected", "")
        difficulty = q.get("difficulty", "medium")

        # Step 1: Ask the LLM which sections to hydrate
        routing_prompt = (
            f"You are a domain knowledge assistant. You have a knowledge base with these sections:\n"
            f"{_json.dumps(section_names)}\n\n"
            f"A user asks: \"{question}\"\n\n"
            f"Which sections (1-3 max) should be retrieved to answer this question? "
            f"If the answer likely isn't in the knowledge base, respond with NONE.\n"
            f"Respond with ONLY a JSON array of section names, e.g. [\"ENTITY-CUSTOMER\", \"ENTITY-ORDER\"] or [\"NONE\"]."
        )

        requested_sections = _ask_for_sections(
            routing_prompt, l3_prompt,
            model=eval_model, api_key=api_key, provider=provider,
            valid_names=set(section_names),
        )

        # Step 2: Hydrate the requested sections
        if requested_sections and requested_sections != ["NONE"]:
            hydration = hydrate_by_name(doc, requested_sections, include_header=True)
            lines: list[str] = []
            if hydration.header_text:
                lines.append(hydration.header_text)
                lines.append("")
            for section in hydration.sections:
                for line in serialize_section(section, natural_language=True):
                    lines.append(line)
                lines.append("")
            hydrated_text = "\n".join(lines)
        else:
            hydrated_text = l3_prompt  # fallback: just L3

        hydrated_bpe = count_bpe_tokens(hydrated_text, model=eval_model)
        total_bpe = l3_bpe + hydrated_bpe

        # Step 3: Answer the question with hydrated context
        answer = _ask_with_context(
            question, hydrated_text,
            model=eval_model, api_key=api_key, provider=provider,
        )

        # Step 4: Grade
        correct_rule = _grade_answer(answer, expected)
        correct_judge = _llm_judge(
            question, expected, answer,
            model=eval_model, api_key=api_key, provider=provider,
        )

        results.append(HydrationPoint(
            question_id=q_id,
            question=question,
            expected=expected,
            difficulty=difficulty,
            sections_requested=requested_sections,
            bpe_l3=l3_bpe,
            bpe_hydrated=hydrated_bpe,
            bpe_total=total_bpe,
            fidelity_rule=correct_rule,
            fidelity_judge=correct_judge,
            answer=answer,
        ))

    return results


def _ask_for_sections(
    routing_prompt: str,
    system_prompt: str,
    *,
    model: str,
    api_key: str,
    provider: str,
    valid_names: set[str],
) -> list[str]:
    """Ask the LLM which sections to hydrate. Returns list of section names."""
    import json as _json

    from .metrics.fidelity import _ask_llm

    response = _ask_llm(routing_prompt, system_prompt,
                        model=model, api_key=api_key, provider=provider)

    # Parse JSON array from response
    try:
        # Handle markdown code fences
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = _json.loads(clean)
        if isinstance(parsed, list):
            # Filter to valid section names
            return [s for s in parsed if s in valid_names or s == "NONE"]
    except (_json.JSONDecodeError, ValueError):
        pass

    # Fallback: extract any quoted section names from response
    import re
    found = re.findall(r'"(ENTITY-[\w-]+)"', response)
    return [s for s in found if s in valid_names] if found else ["NONE"]


def _ask_with_context(
    question: str,
    context: str,
    *,
    model: str,
    api_key: str,
    provider: str,
) -> str:
    """Ask a question with hydrated context."""
    from .metrics.fidelity import _ask_llm

    return _ask_llm(question, context,
                    model=model, api_key=api_key, provider=provider)


def _build_results(
    points: list[EvalPoint],
    hydration_results: list[HydrationPoint],
    source_bpe: int,
    source_words: int,
    model: str,
) -> dict[str, Any]:
    """Build the complete results dict."""
    return {
        "experiment": "definitive_eval_v0.4.0",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": model,
        "source": {
            "bpe_tokens": source_bpe,
            "word_tokens": source_words,
        },
        "methods": [p.to_dict() for p in points],
        "hydration_details": [
            {
                "id": h.question_id,
                "question": h.question,
                "expected": h.expected,
                "difficulty": h.difficulty,
                "sections_requested": h.sections_requested,
                "bpe_l3": h.bpe_l3,
                "bpe_hydrated": h.bpe_hydrated,
                "bpe_total": h.bpe_total,
                "correct_rule": h.fidelity_rule,
                "correct_judge": h.fidelity_judge,
                "answer": h.answer,
            }
            for h in hydration_results
        ] if hydration_results else [],
    }


def save_definitive_eval(results: dict[str, Any], output_dir: str) -> str:
    """Save results to JSON."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "definitive_eval.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    return path
