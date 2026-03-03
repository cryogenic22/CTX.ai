"""Gemini model family eval on .ctx fidelity.

Tests Gemini 2.5 Pro, 2.5 Flash, and optionally 3.x previews.
Uses Google AI Gemini REST API (generativelanguage.googleapis.com).
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.request
from typing import Any

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ctxpack.benchmarks.dotenv import load_dotenv
from ctxpack.benchmarks.metrics.fidelity import (
    _grade_answer,
    load_questions,
)
from ctxpack.core.packer import pack
from ctxpack.core.serializer import serialize

load_dotenv()

QA_SYSTEM = "You are a precise Q&A assistant. Answer concisely based only on the provided context."
JUDGE_SYSTEM = "You are an expert grader evaluating answer correctness."

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _gemini_generate(
    model: str,
    system: str,
    user_prompt: str,
    api_key: str,
    max_tokens: int = 300,
) -> str:
    """Call Gemini generateContent REST API."""
    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"

    # Gemini 2.5 Pro is a "thinking" model — reasoning tokens count
    # against maxOutputTokens, so use a higher budget for Pro models
    effective_max = max_tokens * 5 if "pro" in model else max_tokens

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

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")[:200]
        except Exception:
            pass
        return f"(error: HTTP {e.code} {body})"
    except Exception as e:
        return f"(error: {e})"

    return ""


def _build_qa_prompt(question: str, context: str) -> str:
    return (
        f"Given the following domain knowledge context, answer the question "
        f"concisely and accurately. If the answer is not in the context, say "
        f"'Not found in context'.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer:"
    )


def _judge(question: str, expected: str, answer: str, api_key: str) -> bool:
    """Use gpt-4o as judge for consistency with other evals."""
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

    # Use OpenAI gpt-4o for judging (cross-model consistency)
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        payload = json.dumps({
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 10,
            "temperature": 0,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {openai_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return "CORRECT" in text.upper() and "INCORRECT" not in text.upper()
        except Exception:
            pass

    # Fallback: use Gemini itself as judge
    resp = _gemini_generate("gemini-2.5-flash", JUDGE_SYSTEM, prompt, api_key, max_tokens=10)
    return "CORRECT" in resp.upper() and "INCORRECT" not in resp.upper()


def main():
    golden_set_path = os.path.join(os.path.dirname(__file__), "golden_set")
    questions_path = os.path.join(golden_set_path, "questions.yaml")
    corpus_dir = os.path.join(golden_set_path, "corpus")
    save_dir = os.path.join(golden_set_path, "results")
    logs_dir = os.path.join(save_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    questions = load_questions(questions_path)
    pack_result = pack(corpus_dir)
    l2_text = serialize(pack_result.document)
    l1_text = serialize(pack_result.document, natural_language=True)
    l2_tokens = len(l2_text.split())
    l1_tokens = len(l1_text.split())

    google_key = os.environ.get("GOOGLE_API_KEY", "")
    if not google_key:
        print("ERROR: GOOGLE_API_KEY not set in .env")
        return

    # Gemini models to test
    models = [
        ("gemini-2.5-pro", "gemini-2.5-pro"),
        ("gemini-2.5-flash", "gemini-2.5-flash"),
        ("gemini-2.5-flash-lite", "gemini-2.5-flash-lite"),
    ]

    print(f"Questions: {len(questions)}, L2={l2_tokens} tok, L1={l1_tokens} tok")
    print()

    version = "0.3.0-alpha"
    all_results: dict[str, Any] = {
        "version": version,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "eval_type": "gemini-models",
        "l2_tokens": l2_tokens,
        "l1_tokens": l1_tokens,
        "runs": {},
    }

    for model_label, model_id in models:
        for fmt_label, context, tokens in [("L2", l2_text, l2_tokens), ("L1", l1_text, l1_tokens)]:
            run_key = f"{model_label}-{fmt_label}"
            print(f"  Running: {run_key} ({len(questions)} Qs)...", end=" ", flush=True)

            t0 = time.perf_counter()
            results = []

            for q in questions:
                prompt = _build_qa_prompt(q["question"], context)
                answer = _gemini_generate(
                    model_id, QA_SYSTEM, prompt, google_key, max_tokens=300,
                )
                rule_ok = _grade_answer(answer, q.get("expected", ""))
                judge_ok = False
                if answer and not answer.startswith("(error"):
                    judge_ok = _judge(q["question"], q.get("expected", ""), answer, google_key)

                results.append({
                    "id": q.get("id", ""),
                    "question": q["question"],
                    "expected": q.get("expected", ""),
                    "answer": answer,
                    "rule_correct": rule_ok,
                    "judge_correct": judge_ok,
                    "difficulty": q.get("difficulty", "medium"),
                })

            elapsed = time.perf_counter() - t0
            rule_c = sum(1 for r in results if r["rule_correct"])
            judge_c = sum(1 for r in results if r["judge_correct"])
            total = len(results)

            run_data = {
                "model": model_label,
                "model_id": model_id,
                "provider": "google",
                "format": fmt_label,
                "tokens": tokens,
                "rule_score": round(rule_c / total, 3) if total else 0,
                "rule_correct": rule_c,
                "judge_score": round(judge_c / total, 3) if total else 0,
                "judge_correct": judge_c,
                "total": total,
                "elapsed_s": round(elapsed, 1),
                "per_question": results,
            }

            all_results["runs"][run_key] = run_data
            print(f"rule={rule_c/total:.0%} judge={judge_c/total:.0%} ({elapsed:.1f}s)")

            # Focus questions
            for r in results:
                if r["id"] in ("Q13", "Q23", "Q25", "Q05", "Q04"):
                    mark = "OK" if r["judge_correct"] else "FAIL"
                    ans = r["answer"][:120].replace("\n", " ")
                    print(f"    {r['id']} [{mark:>4s}] {ans}")

            # Save individual log
            log_path = os.path.join(
                logs_dir,
                f"{time.strftime('%Y-%m-%dT%H-%M-%S')}_{run_key}.json",
            )
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(run_data, f, indent=2, ensure_ascii=False)

    # Summary
    print()
    print("=" * 70)
    print("  GEMINI MODEL RESULTS")
    print("=" * 70)
    print()

    hdr = f"{'Run':<28s} {'Tokens':>7s} {'Rule':>6s} {'Judge':>7s}"
    print(hdr)
    print("-" * len(hdr))
    for rk, r in all_results["runs"].items():
        print(f"{rk:<28s} {r['tokens']:>7d} {r['rule_score']:>5.0%} {r['judge_score']:>6.0%}")

    # Save combined
    path = os.path.join(save_dir, f"{version}-gemini-models.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved: {path}")


if __name__ == "__main__":
    main()
