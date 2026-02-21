"""Baseline: LLM-generated summary at same token budget as ctxpack.

This is the fair comparison — "why not just ask the LLM to summarise?"
Uses the same provider/model as fidelity testing.
"""

from __future__ import annotations

from typing import Optional


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
    return _summarise_anthropic(prompt, model=model, api_key=api_key)


def _summarise_anthropic(prompt: str, *, model: str, api_key: str) -> str:
    """Call Anthropic Messages API for summarisation."""
    import json
    import urllib.request

    payload = json.dumps({
        "model": model,
        "max_tokens": 500,
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


def _summarise_openai(prompt: str, *, model: str, api_key: str) -> str:
    """Call OpenAI Chat Completions API for summarisation."""
    import json
    import urllib.request

    payload = json.dumps({
        "model": model,
        "max_tokens": 500,
        "messages": [
            {"role": "system", "content": "You are a precise technical summarisation assistant."},
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except Exception as e:
        return f"(error: {e})"

    return ""
