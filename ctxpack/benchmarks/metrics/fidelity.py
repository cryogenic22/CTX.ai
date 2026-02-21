"""Fidelity metric: LLM Q&A accuracy with compressed vs raw context.

Supports both Anthropic (Claude) and OpenAI (GPT) APIs.
Configure via .env or environment variables.
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
            "details": [
                {
                    "id": r.question_id,
                    "question": r.question,
                    "expected": r.expected,
                    "answer": r.answer,
                    "correct": r.correct,
                    "difficulty": r.difficulty,
                }
                for r in self.results
            ],
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
                "score": round(correct / len(items), 3) if items else 0.0,
            }
        return out


def load_questions(questions_path: str) -> list[dict[str, Any]]:
    """Load questions from a YAML file."""
    from ctxpack.core.packer.yaml_parser import yaml_parse

    with open(questions_path, encoding="utf-8") as f:
        data = yaml_parse(f.read(), filename=questions_path)
    if isinstance(data, list):
        return data
    return []


def _detect_provider() -> tuple[str, str, str]:
    """Detect which LLM provider to use from environment.

    Returns (provider, api_key, default_model).
    """
    provider = os.environ.get("CTXPACK_EVAL_PROVIDER", "").lower()
    model_override = os.environ.get("CTXPACK_EVAL_MODEL", "")

    # Explicit provider choice
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        model = model_override or "gpt-4o"
        return "openai", key, model
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        model = model_override or "claude-sonnet-4-6"
        return "anthropic", key, model

    # Auto-detect: try Anthropic first, then OpenAI
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        return "anthropic", anthropic_key, model_override or "claude-sonnet-4-6"

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        return "openai", openai_key, model_override or "gpt-4o"

    return "none", "", ""


def measure_fidelity(
    questions: list[dict],
    context: str,
    *,
    model: str = "",
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
) -> FidelityMetrics:
    """Run fidelity test: ask questions with context, grade answers.

    Auto-detects provider from .env / environment if not specified.
    """
    # Resolve provider and key
    if not provider or not api_key:
        detected_provider, detected_key, detected_model = _detect_provider()
        provider = provider or detected_provider
        api_key = api_key or detected_key
        model = model or detected_model

    if not model:
        model = "claude-sonnet-4-6" if provider == "anthropic" else "gpt-4o"

    results: list[FidelityResult] = []

    for q in questions:
        result = FidelityResult(
            question_id=q.get("id", ""),
            question=q.get("question", ""),
            expected=q.get("expected", ""),
            difficulty=q.get("difficulty", "medium"),
        )

        if api_key:
            answer = _ask_llm(
                q["question"], context,
                model=model, api_key=api_key, provider=provider,
            )
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


def _ask_llm(
    question: str,
    context: str,
    *,
    model: str,
    api_key: str,
    provider: str,
) -> str:
    """Ask a question with context via LLM API (Anthropic or OpenAI)."""
    if provider == "openai":
        return _ask_openai(question, context, model=model, api_key=api_key)
    return _ask_anthropic(question, context, model=model, api_key=api_key)


def _build_prompt(question: str, context: str) -> str:
    return (
        f"Given the following domain knowledge context, answer the question "
        f"concisely and accurately. If the answer is not in the context, say "
        f"'Not found in context'.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer:"
    )


def _ask_anthropic(question: str, context: str, *, model: str, api_key: str) -> str:
    """Call Anthropic Messages API."""
    import json
    import urllib.request

    prompt = _build_prompt(question, context)

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


def _ask_openai(question: str, context: str, *, model: str, api_key: str) -> str:
    """Call OpenAI Chat Completions API."""
    import json
    import urllib.request

    prompt = _build_prompt(question, context)

    payload = json.dumps({
        "model": model,
        "max_tokens": 200,
        "messages": [
            {"role": "system", "content": "You are a precise Q&A assistant. Answer concisely based only on the provided context."},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except Exception as e:
        return f"(error: {e})"

    return ""


def _grade_answer(answer: str, expected: str) -> bool:
    """Grade by checking if expected keywords appear in the answer."""
    if not expected or not answer:
        return False
    answer_lower = answer.lower()
    # Split expected into key terms and check each is present
    # This handles cases like "CRM (Salesforce)" matching "Salesforce" or "CRM"
    terms = [t.strip().lower() for t in expected.replace("(", " ").replace(")", " ").split() if len(t.strip()) > 2]
    if not terms:
        return expected.lower() in answer_lower
    # At least 60% of key terms should match
    matches = sum(1 for t in terms if t in answer_lower)
    return matches / len(terms) >= 0.6
