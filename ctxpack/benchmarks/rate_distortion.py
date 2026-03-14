"""WS6: Rate-Distortion Experiment.

Packs the golden-set corpus at each compression preset (conservative,
balanced, aggressive), runs all eval questions, and measures fidelity,
compression ratio, and cost at each operating point.

The result is a set of (rate, distortion) points suitable for plotting
a Pareto frontier — the first empirical R-D curve for structured domain
knowledge compression.
"""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .dotenv import load_dotenv
from .metrics.compression import count_corpus_tokens, count_tokens, measure_compression
from .metrics.cost import count_bpe_tokens, estimate_cost


@dataclass
class RDPoint:
    """One point on the rate-distortion curve."""

    preset: str
    compression_ratio: float
    bpe_tokens: int
    word_tokens: int
    fidelity_rule: float      # Rule-based fidelity (0-100)
    fidelity_judge: float      # LLM-as-judge fidelity (0-100)
    cost_per_query: float
    model: str = ""
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["compression_ratio"] = round(self.compression_ratio, 2)
        d["fidelity_rule"] = round(self.fidelity_rule, 1)
        d["fidelity_judge"] = round(self.fidelity_judge, 1)
        d["cost_per_query"] = f"${self.cost_per_query:.4f}"
        return d


def run_rate_distortion(
    corpus_dir: str,
    *,
    presets: Optional[list[str]] = None,
    questions_path: Optional[str] = None,
    model: str = "",
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    eval_model: str = "gpt-4o",
    bpe_optimized: bool = True,
) -> list[RDPoint]:
    """Run the rate-distortion experiment.

    For each preset:
    1. Pack corpus at that preset
    2. Serialize to .ctx text
    3. Measure compression ratio and BPE tokens
    4. Run all eval questions and measure fidelity
    5. Compute cost per query

    Returns data points for plotting the Pareto frontier.
    """
    from ..core.packer import pack
    from ..core.serializer import serialize
    from .metrics.fidelity import _detect_provider, load_questions, measure_fidelity

    load_dotenv()

    if presets is None:
        presets = ["conservative", "balanced", "aggressive"]

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

    # Source token count
    source_tokens = count_corpus_tokens(corpus_dir)

    points: list[RDPoint] = []

    for preset in presets:
        # Pack at this preset
        result = pack(corpus_dir, preset=preset)
        ctx_text = serialize(result.document, bpe_optimized=bpe_optimized)

        word_tokens = count_tokens(ctx_text)
        bpe_tokens = count_bpe_tokens(ctx_text, model=eval_model)
        comp = measure_compression(source_tokens, ctx_text)
        cost = estimate_cost(word_tokens, model=eval_model)

        # Fidelity
        fidelity_rule = 0.0
        fidelity_judge = 0.0
        details: list[dict] = []

        if questions and api_key:
            fidelity = measure_fidelity(
                questions, ctx_text,
                model=eval_model, api_key=api_key, provider=provider,
            )
            fidelity_rule = fidelity.score * 100
            fidelity_judge = fidelity.llm_judge_score * 100
            details = [
                {
                    "id": r.question_id,
                    "correct": r.correct,
                    "llm_judge_correct": r.llm_judge_correct,
                    "difficulty": r.difficulty,
                }
                for r in fidelity.results
            ]

        points.append(RDPoint(
            preset=preset,
            compression_ratio=comp.compression_ratio,
            bpe_tokens=bpe_tokens,
            word_tokens=word_tokens,
            fidelity_rule=fidelity_rule,
            fidelity_judge=fidelity_judge,
            cost_per_query=cost.cost_per_query,
            model=eval_model,
            details=details,
        ))

    return points


def save_rate_distortion(
    points: list[RDPoint],
    output_dir: str,
) -> str:
    """Save rate-distortion results to JSON."""
    os.makedirs(output_dir, exist_ok=True)

    data = {
        "experiment": "rate_distortion",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": points[0].model if points else "",
        "points": [p.to_dict() for p in points],
    }

    path = os.path.join(output_dir, "rate_distortion.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path
