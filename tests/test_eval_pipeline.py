"""Tests for eval pipeline robustness: retry logic, error detection, cross-model judging.

These tests verify fixes for critical bugs in the fidelity measurement module:
1. No retry logic — API rate-limit errors silently scored as INCORRECT
2. No error detection — "(error: HTTP 429)" responses scored as INCORRECT
3. Self-judging — same rate-limited model grades its own answers
4. max_tokens=200 — truncated complex answers
5. No inter-call delay — burst patterns trigger rate limits
"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import patch, MagicMock, call
from urllib.error import HTTPError
from io import BytesIO

import pytest

from ctxpack.benchmarks.metrics.fidelity import (
    FidelityResult,
    FidelityMetrics,
    measure_fidelity,
    _ask_anthropic,
    _ask_openai,
    _ask_google,
    _ask_anthropic_raw,
    _ask_openai_raw,
    _ask_google_raw,
    _llm_judge,
    _retry_api_call,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_error(code: int, msg: str = "Error") -> HTTPError:
    """Create an HTTPError with the given status code."""
    return HTTPError(
        url="https://api.example.com",
        code=code,
        msg=msg,
        hdrs=None,  # type: ignore[arg-type]
        fp=BytesIO(b""),
    )


def _anthropic_ok_response(text: str = "test answer") -> bytes:
    """Return a well-formed Anthropic Messages API JSON response."""
    return json.dumps({
        "content": [{"type": "text", "text": text}],
        "model": "claude-sonnet-4-20250514",
        "stop_reason": "end_turn",
    }).encode("utf-8")


def _openai_ok_response(text: str = "test answer") -> bytes:
    """Return a well-formed OpenAI Chat Completions API JSON response."""
    return json.dumps({
        "choices": [{"message": {"content": text}}],
        "model": "gpt-4o",
    }).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. Retry logic tests
# ---------------------------------------------------------------------------

class TestRetryOn429:
    """Verify exponential backoff on transient HTTP errors."""

    def test_retry_on_429(self):
        """Mock API returning 429 twice then 200 — verify answer is returned."""
        call_count = 0

        def mock_fn():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise _make_http_error(429, "Too Many Requests")
            return "success answer"

        result = _retry_api_call(mock_fn, max_retries=5, base_delay=0.01)
        assert result == "success answer"
        assert call_count == 3  # 2 failures + 1 success

    def test_retry_on_500(self):
        """Mock API returning 500 once then 200 — verify retry works."""
        call_count = 0

        def mock_fn():
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise _make_http_error(500, "Internal Server Error")
            return "recovered"

        result = _retry_api_call(mock_fn, max_retries=5, base_delay=0.01)
        assert result == "recovered"
        assert call_count == 2

    def test_retry_on_502_503_504(self):
        """Verify all transient codes trigger retry."""
        for code in (502, 503, 504):
            call_count = 0

            def mock_fn(c=code):
                nonlocal call_count
                call_count += 1
                if call_count <= 1:
                    raise _make_http_error(c, f"HTTP {c}")
                return f"ok after {c}"

            result = _retry_api_call(mock_fn, max_retries=5, base_delay=0.01)
            assert result == f"ok after {code}"

    def test_retry_gives_up_after_max(self):
        """Mock API returning 429 forever — verify error string returned."""
        def mock_fn():
            raise _make_http_error(429, "Too Many Requests")

        result = _retry_api_call(mock_fn, max_retries=3, base_delay=0.01)
        assert result.startswith("(error:")
        assert "429" in result

    def test_exponential_backoff_timing(self):
        """Verify delays increase exponentially (with tolerance)."""
        delays = []
        call_count = 0

        original_sleep = time.sleep

        def mock_sleep(seconds):
            delays.append(seconds)

        def mock_fn():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise _make_http_error(429, "Too Many Requests")
            return "ok"

        with patch("time.sleep", side_effect=mock_sleep):
            result = _retry_api_call(mock_fn, max_retries=5, base_delay=2.0)

        assert result == "ok"
        assert len(delays) == 3  # 3 retries before success
        # Delays should be approximately 2, 4, 8 (with some jitter tolerance)
        assert delays[0] >= 1.5  # ~2s
        assert delays[1] >= 3.0  # ~4s
        assert delays[2] >= 6.0  # ~8s


class TestNonTransientErrors:
    """Non-transient HTTP errors should fail immediately without retry."""

    def test_non_transient_error_no_retry(self):
        """Mock 401 — verify no retry, immediate error return."""
        call_count = 0

        def mock_fn():
            nonlocal call_count
            call_count += 1
            raise _make_http_error(401, "Unauthorized")

        result = _retry_api_call(mock_fn, max_retries=5, base_delay=0.01)
        assert call_count == 1  # No retry
        assert result.startswith("(error:")

    def test_400_no_retry(self):
        call_count = 0

        def mock_fn():
            nonlocal call_count
            call_count += 1
            raise _make_http_error(400, "Bad Request")

        result = _retry_api_call(mock_fn, max_retries=5, base_delay=0.01)
        assert call_count == 1
        assert "(error:" in result

    def test_403_no_retry(self):
        call_count = 0

        def mock_fn():
            nonlocal call_count
            call_count += 1
            raise _make_http_error(403, "Forbidden")

        result = _retry_api_call(mock_fn, max_retries=5, base_delay=0.01)
        assert call_count == 1
        assert "(error:" in result


# ---------------------------------------------------------------------------
# 2. Judge error detection tests
# ---------------------------------------------------------------------------

class TestJudgeErrorDetection:
    """Verify error-string responses are flagged, not scored as INCORRECT."""

    def test_judge_error_detection_error_prefix(self):
        """Verify '(error: ...)' response is flagged as judge_error."""
        result = FidelityResult(
            question_id="Q1",
            question="What is X?",
            expected="42",
            answer="42",
        )
        # Simulate calling measure_fidelity with a judge that returns an error
        questions = [{"id": "Q1", "question": "What is X?", "expected": "42"}]

        with patch(
            "ctxpack.benchmarks.metrics.fidelity._ask_llm",
            return_value="42",
        ), patch(
            "ctxpack.benchmarks.metrics.fidelity._llm_judge",
            return_value=("(error: HTTP 429 Too Many Requests)", True),
        ):
            metrics = measure_fidelity(
                questions, "context text",
                api_key="fake-key", provider="anthropic", model="claude-sonnet-4-20250514",
            )
            assert metrics.results[0].judge_error is True
            assert metrics.results[0].llm_judge_correct is False

    def test_judge_error_detection_empty_response(self):
        """Verify empty judge response is flagged as judge_error."""
        questions = [{"id": "Q1", "question": "What is X?", "expected": "42"}]

        with patch(
            "ctxpack.benchmarks.metrics.fidelity._ask_llm",
            return_value="42",
        ), patch(
            "ctxpack.benchmarks.metrics.fidelity._llm_judge",
            return_value=("", True),
        ):
            metrics = measure_fidelity(
                questions, "context text",
                api_key="fake-key", provider="anthropic", model="claude-sonnet-4-20250514",
            )
            assert metrics.results[0].judge_error is True


class TestJudgeFailureCount:
    """Verify FidelityMetrics.judge_failures counts error cases."""

    def test_judge_failure_count(self):
        """Verify FidelityMetrics.judge_failures counts errors correctly."""
        questions = [
            {"id": f"Q{i}", "question": f"Q{i}?", "expected": f"A{i}"}
            for i in range(5)
        ]

        # 2 out of 5 judge calls fail
        judge_returns = [
            ("CORRECT", False),
            ("(error: HTTP 429)", True),
            ("INCORRECT", False),
            ("(error: timeout)", True),
            ("CORRECT", False),
        ]
        judge_iter = iter(judge_returns)

        with patch(
            "ctxpack.benchmarks.metrics.fidelity._ask_llm",
            return_value="some answer",
        ), patch(
            "ctxpack.benchmarks.metrics.fidelity._llm_judge",
            side_effect=lambda *a, **kw: next(judge_iter),
        ):
            metrics = measure_fidelity(
                questions, "context",
                api_key="fake-key", provider="anthropic", model="claude-sonnet-4-20250514",
            )
            assert metrics.judge_failures == 2

    def test_judge_failure_count_in_dict(self):
        """Verify judge_failures appears in to_dict() output."""
        metrics = FidelityMetrics(
            total=10, correct=8, score=0.8,
            llm_judge_correct=7, llm_judge_score=0.7,
            judge_failures=2,
        )
        d = metrics.to_dict()
        assert "judge_failures" in d
        assert d["judge_failures"] == 2


# ---------------------------------------------------------------------------
# 3. Cross-model judge selection tests
# ---------------------------------------------------------------------------

class TestCrossModelJudgeSelection:
    """Verify GPT-4o is selected as judge when OPENAI_API_KEY is available."""

    def test_cross_model_judge_selection(self):
        """When OPENAI_API_KEY is set and no explicit judge, use GPT-4o."""
        questions = [{"id": "Q1", "question": "What?", "expected": "42"}]
        judge_calls = []

        def mock_llm_judge(question, expected, answer, *, model, api_key, provider):
            judge_calls.append({"model": model, "provider": provider})
            return ("CORRECT", False)

        env = {
            "ANTHROPIC_API_KEY": "sk-ant-fake",
            "OPENAI_API_KEY": "sk-openai-fake",
        }

        with patch.dict(os.environ, env, clear=False), \
             patch("ctxpack.benchmarks.metrics.fidelity._ask_llm", return_value="42"), \
             patch("ctxpack.benchmarks.metrics.fidelity._llm_judge", side_effect=mock_llm_judge):
            metrics = measure_fidelity(
                questions, "context",
                api_key="sk-ant-fake", provider="anthropic", model="claude-sonnet-4-20250514",
            )

        assert len(judge_calls) == 1
        assert judge_calls[0]["provider"] == "openai"
        assert judge_calls[0]["model"] == "gpt-4o"

    def test_self_judge_when_no_openai_key(self):
        """When only ANTHROPIC_API_KEY is set, self-judge."""
        questions = [{"id": "Q1", "question": "What?", "expected": "42"}]
        judge_calls = []

        def mock_llm_judge(question, expected, answer, *, model, api_key, provider):
            judge_calls.append({"model": model, "provider": provider})
            return ("CORRECT", False)

        env = {
            "ANTHROPIC_API_KEY": "sk-ant-fake",
        }

        with patch.dict(os.environ, env, clear=False), \
             patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False), \
             patch("ctxpack.benchmarks.metrics.fidelity._ask_llm", return_value="42"), \
             patch("ctxpack.benchmarks.metrics.fidelity._llm_judge", side_effect=mock_llm_judge):
            metrics = measure_fidelity(
                questions, "context",
                api_key="sk-ant-fake", provider="anthropic", model="claude-sonnet-4-20250514",
            )

        assert len(judge_calls) == 1
        assert judge_calls[0]["provider"] == "anthropic"

    def test_explicit_judge_params_override_auto(self):
        """Explicit judge_model/judge_provider overrides auto-selection."""
        questions = [{"id": "Q1", "question": "What?", "expected": "42"}]
        judge_calls = []

        def mock_llm_judge(question, expected, answer, *, model, api_key, provider):
            judge_calls.append({"model": model, "provider": provider})
            return ("CORRECT", False)

        with patch("ctxpack.benchmarks.metrics.fidelity._ask_llm", return_value="42"), \
             patch("ctxpack.benchmarks.metrics.fidelity._llm_judge", side_effect=mock_llm_judge):
            metrics = measure_fidelity(
                questions, "context",
                api_key="sk-ant-fake", provider="anthropic", model="claude-sonnet-4-20250514",
                judge_model="gemini-2.5-pro",
                judge_api_key="google-key",
                judge_provider="google",
            )

        assert len(judge_calls) == 1
        assert judge_calls[0]["provider"] == "google"
        assert judge_calls[0]["model"] == "gemini-2.5-pro"


# ---------------------------------------------------------------------------
# 4. max_tokens tests
# ---------------------------------------------------------------------------

class TestMaxTokensIncreased:
    """Verify answer calls use 512, judge calls use 10."""

    def test_max_tokens_increased(self):
        """Verify _ask_anthropic uses max_tokens=512 for answers."""
        import urllib.request

        captured_payloads = []

        def mock_urlopen(req, **kwargs):
            body = json.loads(req.data.decode("utf-8"))
            captured_payloads.append(body)
            resp = MagicMock()
            resp.read.return_value = _anthropic_ok_response("answer")
            resp.__enter__ = lambda s: resp
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = _ask_anthropic(
                "What is X?", "context here",
                model="claude-sonnet-4-20250514", api_key="fake-key",
            )

        assert len(captured_payloads) == 1
        assert captured_payloads[0]["max_tokens"] == 512

    def test_judge_max_tokens_unchanged(self):
        """Verify _ask_anthropic_raw (judge) still uses max_tokens=10."""
        captured_payloads = []

        def mock_urlopen(req, **kwargs):
            body = json.loads(req.data.decode("utf-8"))
            captured_payloads.append(body)
            resp = MagicMock()
            resp.read.return_value = _anthropic_ok_response("CORRECT")
            resp.__enter__ = lambda s: resp
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = _ask_anthropic_raw(
                "Is this correct?",
                model="claude-sonnet-4-20250514", api_key="fake-key",
            )

        assert len(captured_payloads) == 1
        assert captured_payloads[0]["max_tokens"] == 10


# ---------------------------------------------------------------------------
# 5. Inter-call delay tests
# ---------------------------------------------------------------------------

class TestInterCallDelay:
    """Verify a small delay is inserted between API calls."""

    def test_inter_call_delay(self):
        """Verify measure_fidelity inserts delays between API calls."""
        questions = [
            {"id": "Q1", "question": "Q1?", "expected": "A1"},
            {"id": "Q2", "question": "Q2?", "expected": "A2"},
        ]

        sleep_calls = []

        original_sleep = time.sleep

        def mock_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("ctxpack.benchmarks.metrics.fidelity.time.sleep", side_effect=mock_sleep), \
             patch("ctxpack.benchmarks.metrics.fidelity._ask_llm", return_value="answer"), \
             patch("ctxpack.benchmarks.metrics.fidelity._llm_judge", return_value=("CORRECT", False)):
            metrics = measure_fidelity(
                questions, "context",
                api_key="fake-key", provider="anthropic", model="claude-sonnet-4-20250514",
            )

        # At least some delays should have been inserted
        assert len(sleep_calls) > 0
        # Delays should be 0.5s
        for delay in sleep_calls:
            assert delay == pytest.approx(0.5, abs=0.1)


# ---------------------------------------------------------------------------
# 6. Integration: _llm_judge returns tuple (response, is_error)
# ---------------------------------------------------------------------------

class TestLlmJudgeReturnsTuple:
    """After the fix, _llm_judge should return (response_text, is_error) tuple."""

    def test_llm_judge_correct_answer(self):
        """_llm_judge returns ('CORRECT', False) for a correct answer."""
        with patch("ctxpack.benchmarks.metrics.fidelity._ask_anthropic_raw", return_value="CORRECT"):
            resp, is_error = _llm_judge(
                "What?", "42", "42",
                model="claude-sonnet-4-20250514", api_key="fake", provider="anthropic",
            )
        assert resp.strip().upper() == "CORRECT"
        assert is_error is False

    def test_llm_judge_error_response(self):
        """_llm_judge returns (error_text, True) when API returns error."""
        with patch(
            "ctxpack.benchmarks.metrics.fidelity._ask_anthropic_raw",
            return_value="(error: HTTP 429 Too Many Requests)",
        ):
            resp, is_error = _llm_judge(
                "What?", "42", "42",
                model="claude-sonnet-4-20250514", api_key="fake", provider="anthropic",
            )
        assert is_error is True

    def test_llm_judge_empty_response(self):
        """_llm_judge returns ('', True) when API returns empty."""
        with patch(
            "ctxpack.benchmarks.metrics.fidelity._ask_anthropic_raw",
            return_value="",
        ):
            resp, is_error = _llm_judge(
                "What?", "42", "42",
                model="claude-sonnet-4-20250514", api_key="fake", provider="anthropic",
            )
        assert is_error is True


# ---------------------------------------------------------------------------
# 7. FidelityResult.judge_error field exists
# ---------------------------------------------------------------------------

class TestFidelityResultJudgeError:
    """Verify FidelityResult has a judge_error field."""

    def test_judge_error_default_false(self):
        r = FidelityResult(
            question_id="Q1", question="What?", expected="42",
        )
        assert r.judge_error is False

    def test_judge_error_set_true(self):
        r = FidelityResult(
            question_id="Q1", question="What?", expected="42",
            judge_error=True,
        )
        assert r.judge_error is True

    def test_judge_error_in_to_dict(self):
        """Verify judge_error appears in FidelityMetrics.to_dict() details."""
        r = FidelityResult(
            question_id="Q1", question="What?", expected="42",
            answer="42", judge_error=True,
        )
        metrics = FidelityMetrics(
            total=1, correct=1, score=1.0,
            llm_judge_correct=0, llm_judge_score=0.0,
            judge_failures=1,
            results=[r],
        )
        d = metrics.to_dict()
        assert d["details"][0]["judge_error"] is True


# ---------------------------------------------------------------------------
# 8. Retry wrapper is importable
# ---------------------------------------------------------------------------

class TestRetryApiCallImport:
    """Verify _retry_api_call is importable from fidelity module."""

    def test_import(self):
        from ctxpack.benchmarks.metrics.fidelity import _retry_api_call
        assert callable(_retry_api_call)
