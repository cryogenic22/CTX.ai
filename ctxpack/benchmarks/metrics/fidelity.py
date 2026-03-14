"""Fidelity metric: LLM Q&A accuracy with compressed vs raw context.

Supports both Anthropic (Claude) and OpenAI (GPT) APIs.
Configure via .env or environment variables.

v0.4 fixes:
- Retry with exponential backoff on transient HTTP errors (429, 500, 502, 503, 504)
- Error detection in judge (judge_error flag, judge_failures count)
- Cross-model judging: auto-select GPT-4o when OPENAI_API_KEY available
- max_tokens=512 for answer calls (was 200)
- Rate-limit-aware inter-call delay (0.5s)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.error import HTTPError

logger = logging.getLogger(__name__)

# Identical system message for both providers — eliminates cross-model prompt asymmetry
QA_SYSTEM_MSG = "You are a precise Q&A assistant. Answer concisely based only on the provided context."
JUDGE_SYSTEM_MSG = "You are an expert grader evaluating answer correctness."

# Transient HTTP status codes that should trigger retry
_TRANSIENT_CODES = frozenset({429, 500, 502, 503, 504})

# Inter-call delay to avoid API bursting (seconds)
_INTER_CALL_DELAY = 0.5


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

def _retry_api_call(
    fn: Callable[[], str],
    *,
    max_retries: int = 5,
    base_delay: float = 2.0,
) -> str:
    """Execute *fn* with exponential backoff on transient HTTP errors.

    Args:
        fn: Zero-argument callable that performs the API call and returns a string.
        max_retries: Maximum number of retry attempts (default 5).
        base_delay: Initial delay in seconds; doubles each retry (2, 4, 8, 16, 32).

    Returns:
        The string result from *fn*, or an "(error: ...)" string on permanent failure.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):  # attempt 0 is the initial call
        try:
            return fn()
        except HTTPError as e:
            last_error = e
            if e.code not in _TRANSIENT_CODES:
                # Non-transient (400, 401, 403, etc.) — fail immediately
                logger.warning("Non-transient HTTP %d — not retrying", e.code)
                return f"(error: HTTP {e.code} {e.msg})"

            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.info(
                    "Transient HTTP %d on attempt %d/%d — retrying in %.1fs",
                    e.code, attempt + 1, max_retries, delay,
                )
                time.sleep(delay)
            # else: fall through to return error after loop
        except Exception as e:
            # Non-HTTP exceptions (timeout, connection reset, etc.) — fail immediately
            last_error = e
            return f"(error: {e})"

    # All retries exhausted
    if last_error is not None:
        if isinstance(last_error, HTTPError):
            return f"(error: HTTP {last_error.code} {last_error.msg})"
        return f"(error: {last_error})"
    return "(error: unknown)"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FidelityResult:
    """Result of a single Q&A fidelity test."""

    question_id: str
    question: str
    expected: str
    answer: str = ""
    correct: bool = False
    llm_judge_correct: bool = False
    judge_error: bool = False
    difficulty: str = "medium"


@dataclass
class FidelityMetrics:
    """Aggregate fidelity results."""

    total: int = 0
    correct: int = 0
    score: float = 0.0
    llm_judge_correct: int = 0
    llm_judge_score: float = 0.0
    judge_failures: int = 0
    results: list[FidelityResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "correct": self.correct,
            "score": round(self.score, 3),
            "llm_judge_correct": self.llm_judge_correct,
            "llm_judge_score": round(self.llm_judge_score, 3),
            "judge_failures": self.judge_failures,
            "by_difficulty": self._by_difficulty(),
            "details": [
                {
                    "id": r.question_id,
                    "question": r.question,
                    "expected": r.expected,
                    "answer": r.answer,
                    "correct": r.correct,
                    "llm_judge_correct": r.llm_judge_correct,
                    "judge_error": r.judge_error,
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


# ---------------------------------------------------------------------------
# Question loader
# ---------------------------------------------------------------------------

def load_questions(questions_path: str) -> list[dict[str, Any]]:
    """Load questions from a YAML file."""
    from ctxpack.core.packer.yaml_parser import yaml_parse

    with open(questions_path, encoding="utf-8") as f:
        data = yaml_parse(f.read(), filename=questions_path)
    if isinstance(data, list):
        return data
    # Support questions nested under a 'questions' key
    if isinstance(data, dict) and "questions" in data:
        return data["questions"]
    return []


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

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
        model = model_override or "claude-sonnet-4-20250514"
        return "anthropic", key, model

    if provider == "google":
        key = os.environ.get("GOOGLE_API_KEY", "")
        model = model_override or "gemini-2.5-pro"
        return "google", key, model

    # Auto-detect: try Anthropic first, then OpenAI, then Google
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        return "anthropic", anthropic_key, model_override or "claude-sonnet-4-20250514"

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        return "openai", openai_key, model_override or "gpt-4o"

    google_key = os.environ.get("GOOGLE_API_KEY", "")
    if google_key:
        return "google", google_key, model_override or "gemini-2.5-pro"

    return "none", "", ""


# ---------------------------------------------------------------------------
# Judge auto-selection
# ---------------------------------------------------------------------------

def _resolve_judge_params(
    judge_model: str | None,
    judge_api_key: str | None,
    judge_provider: str | None,
    answer_model: str,
    answer_key: str | None,
    answer_provider: str | None,
) -> tuple[str, str, str]:
    """Resolve judge model/key/provider with cross-model default.

    If no explicit judge params are given AND OPENAI_API_KEY is available,
    default to GPT-4o as judge (cheap, fast, different rate-limit pool).
    Otherwise fall back to self-judging with the answerer model.
    """
    if judge_model or judge_api_key or judge_provider:
        # Explicit judge params — honour them, fill gaps from answerer
        return (
            judge_model or answer_model,
            judge_api_key or answer_key or "",
            judge_provider or answer_provider or "anthropic",
        )

    # Auto-select: prefer GPT-4o cross-model judge when key is available
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key and answer_provider != "openai":
        return "gpt-4o", openai_key, "openai"

    # Fallback: self-judge
    return answer_model, answer_key or "", answer_provider or "anthropic"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def measure_fidelity(
    questions: list[dict],
    context: str,
    *,
    model: str = "",
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    judge_model: Optional[str] = None,
    judge_api_key: Optional[str] = None,
    judge_provider: Optional[str] = None,
) -> FidelityMetrics:
    """Run fidelity test: ask questions with context, grade answers.

    Auto-detects provider from .env / environment if not specified.

    Cross-model judging: when judge_model/judge_api_key/judge_provider are
    set, the LLM-as-judge uses a DIFFERENT model from the answerer.
    Default: if OPENAI_API_KEY is available, use GPT-4o as judge.
    Fallback: self-judge with same model.
    """
    # Resolve provider and key
    if not provider or not api_key:
        detected_provider, detected_key, detected_model = _detect_provider()
        provider = provider or detected_provider
        api_key = api_key or detected_key
        model = model or detected_model

    if not model:
        model = "claude-sonnet-4-20250514" if provider == "anthropic" else "gpt-4o"

    # Resolve judge parameters — cross-model default
    j_model, j_key, j_provider = _resolve_judge_params(
        judge_model, judge_api_key, judge_provider,
        model, api_key, provider,
    )

    results: list[FidelityResult] = []

    for q in questions:
        result = FidelityResult(
            question_id=q.get("id", ""),
            question=q.get("question", ""),
            expected=q.get("expected", ""),
            difficulty=q.get("difficulty", "medium"),
        )

        if api_key:
            # Inter-call delay to avoid API bursting
            time.sleep(_INTER_CALL_DELAY)
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

    # LLM-as-judge: second pass grading for answers that have been collected
    judge_failures = 0
    if j_key:
        for r in results:
            if r.answer and not r.answer.startswith("(skipped"):
                # Inter-call delay to avoid API bursting
                time.sleep(_INTER_CALL_DELAY)
                judge_resp, is_error = _llm_judge(
                    r.question, r.expected, r.answer,
                    model=j_model, api_key=j_key, provider=j_provider,
                )
                if is_error:
                    r.judge_error = True
                    r.llm_judge_correct = False
                    judge_failures += 1
                else:
                    r.llm_judge_correct = (
                        "CORRECT" in judge_resp.upper()
                        and "INCORRECT" not in judge_resp.upper()
                    )

    # Warn if >20% of judge calls failed
    judged_count = sum(
        1 for r in results
        if r.answer and not r.answer.startswith("(skipped")
    )
    if judged_count > 0 and judge_failures / judged_count > 0.2:
        import warnings
        warnings.warn(
            f"Judge failure rate {judge_failures}/{judged_count} "
            f"({judge_failures / judged_count:.0%}) exceeds 20% threshold. "
            f"Results may be unreliable.",
            stacklevel=2,
        )

    total = len(results)
    correct = sum(1 for r in results if r.correct)
    llm_correct = sum(1 for r in results if r.llm_judge_correct)
    return FidelityMetrics(
        total=total,
        correct=correct,
        score=correct / total if total > 0 else 0.0,
        llm_judge_correct=llm_correct,
        llm_judge_score=llm_correct / total if total > 0 else 0.0,
        judge_failures=judge_failures,
        results=results,
    )


# ---------------------------------------------------------------------------
# LLM-as-judge
# ---------------------------------------------------------------------------

def _llm_judge(
    question: str,
    expected: str,
    answer: str,
    *,
    model: str,
    api_key: str,
    provider: str,
) -> tuple[str, bool]:
    """Use LLM as judge to grade answer correctness.

    Returns (response_text, is_error) tuple.
    - is_error is True if the response starts with "(error:" or is empty.
    """
    prompt = (
        f"You are an expert grader. Given a question, the expected answer, and "
        f"a candidate answer, determine if the candidate answer is CORRECT.\n\n"
        f"Rules:\n"
        f"- The candidate does NOT need to match the expected answer word-for-word.\n"
        f"- It is CORRECT if it conveys the same essential facts.\n"
        f"- If expected is 'NOT_IN_CONTEXT', the candidate is correct ONLY if it "
        f"explicitly states the information is not found/not specified.\n"
        f"- Minor wording differences, extra detail, or different formatting are OK.\n"
        f"- Missing key facts or wrong facts means INCORRECT.\n\n"
        f"Question: {question}\n"
        f"Expected answer: {expected}\n"
        f"Candidate answer: {answer}\n\n"
        f"Respond with ONLY the word 'CORRECT' or 'INCORRECT'."
    )

    if provider == "openai":
        resp = _ask_openai_raw(prompt, model=model, api_key=api_key)
    elif provider == "google":
        # Gemini thinking models (Pro) consume reasoning tokens against
        # maxOutputTokens, making short judge responses unreliable.
        # Use OpenAI as cross-model judge when available; fall back to Flash.
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            resp = _ask_openai_raw(prompt, model="gpt-4o", api_key=openai_key)
        else:
            resp = _ask_google_raw(
                prompt, model="gemini-2.5-flash", api_key=api_key,
            )
    else:
        resp = _ask_anthropic_raw(prompt, model=model, api_key=api_key)

    # Detect error responses
    is_error = resp.startswith("(error:") or resp == ""
    return resp, is_error


# ---------------------------------------------------------------------------
# LLM API callers (with retry)
# ---------------------------------------------------------------------------

def _ask_llm(
    question: str,
    context: str,
    *,
    model: str,
    api_key: str,
    provider: str,
) -> str:
    """Ask a question with context via LLM API (Anthropic, OpenAI, or Google)."""
    if provider == "openai":
        return _ask_openai(question, context, model=model, api_key=api_key)
    if provider == "google":
        return _ask_google(question, context, model=model, api_key=api_key)
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
    """Call Anthropic Messages API with retry on transient errors."""
    import json
    import urllib.request

    prompt = _build_prompt(question, context)

    def _call() -> str:
        payload = json.dumps({
            "model": model,
            "max_tokens": 512,
            "temperature": 0,
            "system": QA_SYSTEM_MSG,
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

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "content" in data and data["content"]:
                return data["content"][0].get("text", "")
        return ""

    return _retry_api_call(_call)


def _ask_openai(question: str, context: str, *, model: str, api_key: str) -> str:
    """Call OpenAI Chat Completions API."""
    import json
    import urllib.request

    prompt = _build_prompt(question, context)

    messages = [
        {"role": "system", "content": QA_SYSTEM_MSG},
        {"role": "user", "content": prompt},
    ]

    return _openai_chat(messages, model=model, api_key=api_key, max_tokens=512)


def _ask_anthropic_raw(prompt: str, *, model: str, api_key: str) -> str:
    """Call Anthropic Messages API with a raw prompt (no context wrapper)."""
    import json
    import urllib.request

    def _call() -> str:
        payload = json.dumps({
            "model": model,
            "max_tokens": 10,
            "temperature": 0,
            "system": JUDGE_SYSTEM_MSG,
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

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "content" in data and data["content"]:
                return data["content"][0].get("text", "")
        return ""

    return _retry_api_call(_call)


def _ask_openai_raw(prompt: str, *, model: str, api_key: str) -> str:
    """Call OpenAI Chat Completions API with a raw prompt (no context wrapper)."""
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_MSG},
        {"role": "user", "content": prompt},
    ]

    return _openai_chat(messages, model=model, api_key=api_key, max_tokens=10)


def _openai_chat(
    messages: list[dict],
    *,
    model: str,
    api_key: str,
    max_tokens: int = 512,
) -> str:
    """Call OpenAI Chat Completions API, handling both legacy and new param names.

    Newer models (gpt-5, o3, o4-mini) require ``max_completion_tokens``
    instead of ``max_tokens``. We try the preferred param first based on
    model name, falling back on 400 errors.

    Wraps the HTTP call in _retry_api_call for transient error resilience.
    """
    import json
    import urllib.request

    # Newer reasoning/frontier models use max_completion_tokens
    _NEW_STYLE_PREFIXES = ("gpt-5", "o3", "o4", "o1")
    _REASONING_PREFIXES = ("o3", "o4", "o1")
    use_new = any(model.startswith(p) for p in _NEW_STYLE_PREFIXES)
    is_reasoning = any(model.startswith(p) for p in _REASONING_PREFIXES)

    # Reasoning models need extra budget — reasoning tokens count against
    # max_completion_tokens, so multiply by 10x to leave room for thinking
    effective_max = max_tokens * 10 if is_reasoning else max_tokens

    def _build_payload(new_style: bool) -> bytes:
        body: dict = {
            "model": model,
            "messages": messages,
        }
        if new_style:
            body["max_completion_tokens"] = effective_max
        else:
            body["max_tokens"] = max_tokens
            body["temperature"] = 0
        return json.dumps(body).encode("utf-8")

    def _do_call(payload: bytes) -> str:
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
        return ""

    def _call() -> str:
        """Try preferred param style, fall back to the other on HTTP 400."""
        try:
            return _do_call(_build_payload(new_style=use_new))
        except HTTPError as e:
            if e.code == 400:
                # 400 = wrong param style, try the other — this is NOT transient
                return _do_call(_build_payload(new_style=not use_new))
            raise  # Let _retry_api_call handle transient codes

    return _retry_api_call(_call)


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _gemini_generate(
    model: str,
    system: str,
    user_prompt: str,
    api_key: str,
    max_tokens: int = 300,
) -> str:
    """Call Gemini generateContent REST API with retry on transient errors."""
    import json
    import urllib.request

    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"

    # Gemini 2.5 Pro is a "thinking" model — reasoning tokens count
    # against maxOutputTokens, so use a higher budget for Pro models
    effective_max = max_tokens * 5 if "pro" in model else max_tokens

    def _call() -> str:
        payload = json.dumps({
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "maxOutputTokens": effective_max,
                "temperature": 0,
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
        return ""

    return _retry_api_call(_call)


def _ask_google(question: str, context: str, *, model: str, api_key: str) -> str:
    """Call Google Gemini API for Q&A."""
    prompt = _build_prompt(question, context)
    return _gemini_generate(model, QA_SYSTEM_MSG, prompt, api_key, max_tokens=512)


def _ask_google_raw(prompt: str, *, model: str, api_key: str) -> str:
    """Call Google Gemini API with a raw prompt (no context wrapper)."""
    return _gemini_generate(model, JUDGE_SYSTEM_MSG, prompt, api_key, max_tokens=10)


# ---------------------------------------------------------------------------
# Rule-based grading (unchanged)
# ---------------------------------------------------------------------------

def _grade_answer(answer: str, expected: str) -> bool:
    """Grade by checking if expected keywords appear in the answer."""
    if not expected or not answer:
        return False

    # Adversarial: NOT_IN_CONTEXT means the LLM should say it's not found
    if expected == "NOT_IN_CONTEXT":
        a = answer.lower()
        not_found_signals = [
            "not found in context", "not in the context", "not specified",
            "not mentioned", "not provided", "not covered", "not included",
            "no information", "does not mention", "doesn't mention",
            "does not specify", "doesn't specify", "does not contain",
            "doesn't contain", "no explicit", "not explicitly",
            "cannot be determined", "not available", "not addressed",
        ]
        return any(signal in a for signal in not_found_signals)

    # Normalize both sides: lowercase, collapse hyphens/underscores to spaces,
    # strip punctuation that isn't part of words
    def _normalize(text: str) -> str:
        t = text.lower()
        t = t.replace("-", " ").replace("_", " ")
        # Strip common punctuation but keep alphanumeric + spaces
        t = "".join(c if c.isalnum() or c == " " else " " for c in t)
        # Collapse whitespace
        return " ".join(t.split())

    answer_norm = _normalize(answer)
    expected_norm = _normalize(expected)

    # Direct substring check on normalized text
    if expected_norm in answer_norm:
        return True

    # Split expected into key terms (>2 chars) and check presence
    # Delimiters: spaces, parens, commas
    terms = [t.strip() for t in expected_norm.split() if len(t.strip()) > 2]
    if not terms:
        return expected_norm in answer_norm

    # For each term, check exact presence OR prefix match (e.g. "locale" matches "local")
    def _term_matches(term: str, text: str) -> bool:
        if term in text:
            return True
        # Check if any word in text starts with the term or vice versa
        words = text.split()
        for w in words:
            if w.startswith(term) or term.startswith(w):
                if min(len(w), len(term)) >= 3:  # avoid trivial prefix matches
                    return True
        return False

    matches = sum(1 for t in terms if _term_matches(t, answer_norm))
    return matches / len(terms) >= 0.6
