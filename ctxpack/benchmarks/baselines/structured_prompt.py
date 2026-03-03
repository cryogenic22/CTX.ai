"""Baseline: LLM-as-Packer — ask the LLM to compress into structured KV notation.

This is the strongest possible baseline: "why not just prompt the LLM to output
compact KEY:VALUE structured format matching CtxPack's style?"

Differentiator: CtxPack is deterministic, auditable, zero-cost at pack time.
This baseline is stochastic and costs an API call per pack.
"""

from __future__ import annotations

from typing import Optional


STRUCTURED_SYSTEM_MSG = "You are a domain knowledge compression expert."

STRUCTURED_PROMPT_TEMPLATE = """\
Compress the following source material into structured KEY:VALUE notation.

Rules:
1. Use UPPERCASE-HYPHENATED keys (e.g., IDENTIFIER, MATCH-RULES, PII, RETENTION)
2. Group related fields under entity headings prefixed with ±ENTITY-NAME
3. Use compact notation: arrows (→) for flows/transitions, pipes (|) for alternatives
4. Use @ENTITY-NAME for cross-references between entities
5. Preserve ALL critical facts: identifiers, types, thresholds, constraints, relationships
6. Target approximately {target_tokens} words of output
7. Do NOT use JSON or Markdown — use flat KEY:VALUE lines only
8. Do NOT add information not present in the source

Example output format:
±ENTITY-CUSTOMER
IDENTIFIER:customer_id(UUID,immutable)
MATCH-RULES:[email:exact,phone:normalise(E.164)]
PII:name+email+phone→RESTRICTED
RETENTION:active→indefinite|churned→36mo→anonymise

Source material:
{raw_text}

Compressed structured output ({target_tokens} words max):"""


def prepare_structured_prompt_context(
    raw_text: str,
    target_tokens: int,
    *,
    model: str,
    api_key: str,
    provider: str,
) -> str:
    """Ask an LLM to compress corpus into structured KV notation."""
    prompt = STRUCTURED_PROMPT_TEMPLATE.format(
        raw_text=raw_text,
        target_tokens=target_tokens,
    )

    if provider == "openai":
        return _structured_openai(prompt, model=model, api_key=api_key)
    if provider == "google":
        return _structured_google(prompt, model=model, api_key=api_key)
    return _structured_anthropic(prompt, model=model, api_key=api_key)


def _structured_anthropic(prompt: str, *, model: str, api_key: str) -> str:
    """Call Anthropic Messages API."""
    import json
    import urllib.request

    payload = json.dumps({
        "model": model,
        "max_tokens": 1000,
        "temperature": 0,
        "system": STRUCTURED_SYSTEM_MSG,
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


def _structured_google(prompt: str, *, model: str, api_key: str) -> str:
    """Call Google Gemini API."""
    import json
    import urllib.request

    GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"

    effective_max = 2500 if "pro" in model else 1000

    payload = json.dumps({
        "systemInstruction": {"parts": [{"text": STRUCTURED_SYSTEM_MSG}]},
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


def _structured_openai(prompt: str, *, model: str, api_key: str) -> str:
    """Call OpenAI Chat Completions API."""
    import json
    import urllib.request

    _REASONING_PREFIXES = ("o3", "o4", "o1")
    _NEW_STYLE_PREFIXES = ("gpt-5", "o3", "o4", "o1")
    is_reasoning = any(model.startswith(p) for p in _REASONING_PREFIXES)
    use_new = any(model.startswith(p) for p in _NEW_STYLE_PREFIXES)

    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": STRUCTURED_SYSTEM_MSG},
            {"role": "user", "content": prompt},
        ],
    }

    if use_new:
        body["max_completion_tokens"] = 10000 if is_reasoning else 1000
    else:
        body["max_tokens"] = 1000
        body["temperature"] = 0

    payload = json.dumps(body).encode("utf-8")

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
            fallback: dict = {
                "model": model,
                "messages": body["messages"],
            }
            if use_new:
                fallback["max_tokens"] = 1000
                fallback["temperature"] = 0
            else:
                fallback["max_completion_tokens"] = 10000 if is_reasoning else 1000
            try:
                return _call(json.dumps(fallback).encode("utf-8"))
            except Exception as e2:
                return f"(error: {e2})"
        return f"(error: {e})"
    except Exception as e:
        return f"(error: {e})"
