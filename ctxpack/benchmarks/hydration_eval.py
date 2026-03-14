"""WS7: Hydration Fidelity Experiment.

Compares full L2 injection vs section-level hydration. For each eval
question, hydrates only the relevant sections (using the entity tags in
questions.yaml), then measures fidelity. The hypothesis: >95% fidelity
at <50% token count.
"""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .dotenv import load_dotenv
from .metrics.compression import count_tokens
from .metrics.fidelity import FidelityResult


@dataclass
class HydrationEvalResult:
    """Result of evaluating hydration vs full injection for one question."""

    question_id: str
    question: str
    expected: str
    difficulty: str
    entities: list[str]
    tokens_full_l2: int
    tokens_hydrated: int
    sections_hydrated: list[str]
    fidelity_full: bool       # Was the full-L2 answer correct?
    fidelity_hydrated: bool   # Was the hydrated answer correct?
    judge_full: bool
    judge_hydrated: bool
    token_savings_pct: float
    answer_full: str = ""
    answer_hydrated: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["token_savings_pct"] = round(self.token_savings_pct, 1)
        return d


@dataclass
class HydrationEvalMetrics:
    """Aggregate hydration eval results."""

    total: int = 0
    fidelity_full_rule: float = 0.0
    fidelity_full_judge: float = 0.0
    fidelity_hydrated_rule: float = 0.0
    fidelity_hydrated_judge: float = 0.0
    avg_token_savings_pct: float = 0.0
    results: list[HydrationEvalResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "fidelity_full_rule": round(self.fidelity_full_rule, 1),
            "fidelity_full_judge": round(self.fidelity_full_judge, 1),
            "fidelity_hydrated_rule": round(self.fidelity_hydrated_rule, 1),
            "fidelity_hydrated_judge": round(self.fidelity_hydrated_judge, 1),
            "avg_token_savings_pct": round(self.avg_token_savings_pct, 1),
            "details": [r.to_dict() for r in self.results],
        }


def _entity_to_section_name(entity: str) -> str:
    """Convert entity tag from questions.yaml to .ctx section name.

    E.g. 'COMPRESSOR' -> 'ENTITY-COMPRESSOR', 'IR-PIPELINE' -> 'ENTITY-IR-PIPELINE'
    """
    if entity.startswith("ENTITY-"):
        return entity
    return f"ENTITY-{entity}"


def run_hydration_eval(
    corpus_dir: str,
    *,
    questions_path: Optional[str] = None,
    model: str = "",
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    eval_model: str = "gpt-4o",
    bpe_optimized: bool = True,
) -> HydrationEvalMetrics:
    """Compare full L2 injection vs section-level hydration.

    For each question:
    1. Use entity tags from questions.yaml to determine sections to hydrate
    2. Hydrate those sections via hydrate_by_name()
    3. Ask the question with hydrated context
    4. Also ask with full L2 context (for comparison)
    5. Grade both answers

    Returns aggregate metrics.
    """
    from ..core.hydrator import hydrate_by_name, list_sections
    from ..core.packer import pack
    from ..core.serializer import serialize, serialize_section
    from .metrics.fidelity import (
        _ask_llm,
        _build_prompt,
        _detect_provider,
        _grade_answer,
        _llm_judge,
        load_questions,
    )

    load_dotenv()

    # Auto-detect provider — only when caller didn't pass explicit values
    if api_key is None:
        det_provider, det_key, det_model = _detect_provider()
        provider = provider or det_provider
        api_key = det_key
        eval_model = model or det_model or eval_model
    elif not eval_model and model:
        eval_model = model

    # Load questions
    if questions_path is None:
        questions_path = os.path.join(
            os.path.dirname(__file__), "ctxpack_eval", "questions.yaml"
        )
    questions = load_questions(questions_path) if os.path.exists(questions_path) else []

    # Pack corpus (default = no preset = balanced/full)
    pack_result = pack(corpus_dir)
    doc = pack_result.document
    full_l2_text = serialize(doc, bpe_optimized=bpe_optimized)
    full_l2_tokens = count_tokens(full_l2_text)

    results: list[HydrationEvalResult] = []

    for q in questions:
        q_id = q.get("id", "")
        question = q.get("question", "")
        expected = q.get("expected", "")
        difficulty = q.get("difficulty", "medium")
        entities = q.get("entities", [])

        # Determine sections to hydrate
        section_names = [_entity_to_section_name(e) for e in entities]

        # Hydrate those sections
        if section_names:
            hydration = hydrate_by_name(doc, section_names, include_header=True)
            # Build hydrated context text
            lines: list[str] = []
            if hydration.header_text:
                lines.append(hydration.header_text)
                lines.append("")
            for section in hydration.sections:
                for line in serialize_section(section, bpe_optimized=bpe_optimized):
                    lines.append(line)
                lines.append("")
            hydrated_text = "\n".join(lines)
        else:
            # No entity tags — use full L2 as fallback
            hydrated_text = full_l2_text

        hydrated_tokens = count_tokens(hydrated_text)
        token_savings = (1 - hydrated_tokens / full_l2_tokens) * 100 if full_l2_tokens > 0 else 0

        # Ask questions with both contexts
        fidelity_full = False
        fidelity_hydrated = False
        judge_full = False
        judge_hydrated = False
        answer_full = ""
        answer_hydrated = ""

        if api_key:
            # Full L2
            answer_full = _ask_llm(
                question, full_l2_text,
                model=eval_model, api_key=api_key, provider=provider,
            )
            fidelity_full = _grade_answer(answer_full, expected)
            judge_full = _llm_judge(
                question, expected, answer_full,
                model=eval_model, api_key=api_key, provider=provider,
            )

            # Hydrated
            answer_hydrated = _ask_llm(
                question, hydrated_text,
                model=eval_model, api_key=api_key, provider=provider,
            )
            fidelity_hydrated = _grade_answer(answer_hydrated, expected)
            judge_hydrated = _llm_judge(
                question, expected, answer_hydrated,
                model=eval_model, api_key=api_key, provider=provider,
            )

        sections_matched = [s.name for s in hydrate_by_name(doc, section_names).sections] if section_names else []

        results.append(HydrationEvalResult(
            question_id=q_id,
            question=question,
            expected=expected,
            difficulty=difficulty,
            entities=entities,
            tokens_full_l2=full_l2_tokens,
            tokens_hydrated=hydrated_tokens,
            sections_hydrated=sections_matched,
            fidelity_full=fidelity_full,
            fidelity_hydrated=fidelity_hydrated,
            judge_full=judge_full,
            judge_hydrated=judge_hydrated,
            token_savings_pct=token_savings,
            answer_full=answer_full,
            answer_hydrated=answer_hydrated,
        ))

    # Aggregate
    total = len(results)
    if total > 0:
        full_rule = sum(1 for r in results if r.fidelity_full) / total * 100
        full_judge = sum(1 for r in results if r.judge_full) / total * 100
        hyd_rule = sum(1 for r in results if r.fidelity_hydrated) / total * 100
        hyd_judge = sum(1 for r in results if r.judge_hydrated) / total * 100
        avg_savings = sum(r.token_savings_pct for r in results) / total
    else:
        full_rule = full_judge = hyd_rule = hyd_judge = avg_savings = 0.0

    return HydrationEvalMetrics(
        total=total,
        fidelity_full_rule=full_rule,
        fidelity_full_judge=full_judge,
        fidelity_hydrated_rule=hyd_rule,
        fidelity_hydrated_judge=hyd_judge,
        avg_token_savings_pct=avg_savings,
        results=results,
    )


def save_hydration_eval(
    metrics: HydrationEvalMetrics,
    output_dir: str,
) -> str:
    """Save hydration eval results to JSON."""
    os.makedirs(output_dir, exist_ok=True)

    data = {
        "experiment": "hydration_fidelity",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary": {
            "total_questions": metrics.total,
            "fidelity_full_rule": round(metrics.fidelity_full_rule, 1),
            "fidelity_full_judge": round(metrics.fidelity_full_judge, 1),
            "fidelity_hydrated_rule": round(metrics.fidelity_hydrated_rule, 1),
            "fidelity_hydrated_judge": round(metrics.fidelity_hydrated_judge, 1),
            "avg_token_savings_pct": round(metrics.avg_token_savings_pct, 1),
        },
        "details": [r.to_dict() for r in metrics.results],
    }

    path = os.path.join(output_dir, "hydration_eval.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path
