"""Baseline: LLM-generated summary at same token budget as ctxpack.

This is the fair comparison — "why not just ask the LLM to summarise?"
Uses the same provider/model as fidelity testing.
"""

from __future__ import annotations

from typing import Optional

# Identical system message for both providers
SUMMARY_SYSTEM_MSG = "You are a precise technical summarisation assistant."


def prepare_llm_summary(
    raw_text: str,
    target_tokens: int,
    *,
    model: str,
    api_key: str,
    provider: str,
) -> str:
    """Ask an LLM to summarise the corpus into target_tokens words."""
    prompt = (
        f"You are a domain knowledge compression expert. Summarise the following "
        f"source material into approximately {target_tokens} words. Preserve ALL "
        f"critical facts: entity names, identifiers, field types, thresholds, "
        f"status flows, retention policies, PII classifications, known conflicts, "
        f"and cross-entity relationships. Be as dense and precise as possible. "
        f"Do not add any information not present in the source.\n\n"
        f"Source material:\n{raw_text}\n\n"
        f"Compressed summary ({target_tokens} words max):"
    )

    if provider == "openai":
        return _summarise_openai(prompt, model=model, api_key=api_key)
    if provider == "google":
        return _summarise_google(prompt, model=model, api_key=api_key)
    return _summarise_anthropic(prompt, model=model, api_key=api_key)


def _summarise_anthropic(prompt: str, *, model: str, api_key: str) -> str:
    """Call Anthropic Messages API for summarisation."""
    import json
    import urllib.request

    payload = json.dumps({
        "model": model,
        "max_tokens": 500,
        "temperature": 0,
        "system": SUMMARY_SYSTEM_MSG,
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "content" in data and data["content"]:
                return data["content"][0].get("text", "")
    except Exception as e:
        return f"(error: {e})"

    return ""


def _summarise_google(prompt: str, *, model: str, api_key: str) -> str:
    """Call Google Gemini API for summarisation."""
    import json
    import urllib.request

    GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"

    effective_max = 2500 if "pro" in model else 500

    payload = json.dumps({
        "systemInstruction": {"parts": [{"text": SUMMARY_SYSTEM_MSG}]},
        "contents": [{"parts": [{"text": prompt}]}],
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
    except Exception as e:
        return f"(error: {e})"

    return ""


def _summarise_openai(prompt: str, *, model: str, api_key: str) -> str:
    """Call OpenAI Chat Completions API for summarisation.

    Reasoning models (o3, o4-mini, o1) need ``max_completion_tokens``
    with a larger budget because reasoning tokens count against the limit.
    """
    import json
    import urllib.request

    _REASONING_PREFIXES = ("o3", "o4", "o1")
    _NEW_STYLE_PREFIXES = ("gpt-5", "o3", "o4", "o1")
    is_reasoning = any(model.startswith(p) for p in _REASONING_PREFIXES)
    use_new = any(model.startswith(p) for p in _NEW_STYLE_PREFIXES)

    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_MSG},
            {"role": "user", "content": prompt},
        ],
    }

    if use_new:
        # Reasoning models need 10x budget for thinking overhead
        body["max_completion_tokens"] = 5000 if is_reasoning else 500
    else:
        body["max_tokens"] = 500
        body["temperature"] = 0

    payload = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    def _call(data: bytes) -> str:
        r = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(r, timeout=120) as resp:
            d = json.loads(resp.read().decode("utf-8"))
            choices = d.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
        return ""

    try:
        return _call(payload)
    except urllib.error.HTTPError as e:
        if e.code == 400:
            # Retry with the other param style
            fallback: dict = {
                "model": model,
                "messages": body["messages"],
            }
            if use_new:
                fallback["max_tokens"] = 500
                fallback["temperature"] = 0
            else:
                fallback["max_completion_tokens"] = 5000 if is_reasoning else 500
            try:
                return _call(json.dumps(fallback).encode("utf-8"))
            except Exception as e2:
                return f"(error: {e2})"
        return f"(error: {e})"
    except Exception as e:
        return f"(error: {e})"
