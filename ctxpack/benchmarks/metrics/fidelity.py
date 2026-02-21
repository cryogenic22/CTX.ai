"""Fidelity metric: LLM Q&A accuracy with compressed vs raw context.

Requires an API key for the configured model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FidelityResult:
    """Result of a single Q&A fidelity test."""

    question_id: str
    question: str
    expected: str
    answer: str = ""
    correct: bool = False
    difficulty: str = "medium"


@dataclass
class FidelityMetrics:
    """Aggregate fidelity results."""

    total: int = 0
    correct: int = 0
    score: float = 0.0
    results: list[FidelityResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "correct": self.correct,
            "score": round(self.score, 3),
            "by_difficulty": self._by_difficulty(),
        }

    def _by_difficulty(self) -> dict[str, dict]:
        groups: dict[str, list[FidelityResult]] = {}
        for r in self.results:
            groups.setdefault(r.difficulty, []).append(r)
        out = {}
        for diff, items in groups.items():
            correct = sum(1 for i in items if i.correct)
            out[diff] = {
                "total": len(items),
                "correct": correct,
                "score": correct / len(items) if items else 0.0,
            }
        return out


def load_questions(questions_path: str) -> list[dict[str, Any]]:
    """Load questions from a YAML file."""
    # Use our stdlib YAML parser
    from ctxpack.core.packer.yaml_parser import yaml_parse

    with open(questions_path, encoding="utf-8") as f:
        data = yaml_parse(f.read(), filename=questions_path)
    if isinstance(data, list):
        return data
    return []


def measure_fidelity(
    questions: list[dict],
    context: str,
    *,
    model: str = "claude-sonnet-4-6",
    api_key: Optional[str] = None,
) -> FidelityMetrics:
    """Run fidelity test: ask questions with context, grade answers.

    If no API key is available, returns empty metrics (score=0).
    """
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    results: list[FidelityResult] = []

    for q in questions:
        result = FidelityResult(
            question_id=q.get("id", ""),
            question=q.get("question", ""),
            expected=q.get("expected", ""),
            difficulty=q.get("difficulty", "medium"),
        )

        if api_key:
            answer = _ask_llm(q["question"], context, model=model, api_key=api_key)
            result.answer = answer
            result.correct = _grade_answer(answer, q.get("expected", ""))
        else:
            result.answer = "(skipped — no API key)"
            result.correct = False

        results.append(result)

    total = len(results)
    correct = sum(1 for r in results if r.correct)
    return FidelityMetrics(
        total=total,
        correct=correct,
        score=correct / total if total > 0 else 0.0,
        results=results,
    )


def _ask_llm(question: str, context: str, *, model: str, api_key: str) -> str:
    """Ask a question with context via the Anthropic API.

    Uses urllib to avoid external dependencies.
    """
    import json
    import urllib.request

    prompt = (
        f"Given the following context, answer the question concisely.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer:"
    )

    payload = json.dumps({
        "model": model,
        "max_tokens": 200,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "content" in data and data["content"]:
                return data["content"][0].get("text", "")
    except Exception as e:
        return f"(error: {e})"

    return ""


def _grade_answer(answer: str, expected: str) -> bool:
    """Simple grading: check if expected text appears in the answer."""
    if not expected or not answer:
        return False
    # Case-insensitive substring match
    return expected.lower() in answer.lower()
