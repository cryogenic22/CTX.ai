"""Baseline: Minified JSON/YAML — whitespace-stripped, no structural compression.

Addresses Reviewer 1 & 2 concern: does CtxPack's advantage come from
whitespace removal alone, or from genuine structural compression?

For YAML/YML: parse → dump as compact JSON (separators=(',',':'))
For Markdown: strip blank lines, collapse whitespace
"""

from __future__ import annotations

import json
import os
import re


def prepare_minified_context(corpus_dir: str) -> str:
    """Walk corpus, minify each file, concatenate."""
    parts: list[str] = []
    for root, _dirs, files in os.walk(corpus_dir):
        for fname in sorted(files):
            path = os.path.join(root, fname)
            rel = os.path.relpath(path, corpus_dir).replace("\\", "/")

            if fname.endswith((".yaml", ".yml")):
                parts.append(f"--- {rel} ---\n{_minify_yaml(path)}")
            elif fname.endswith(".md"):
                parts.append(f"--- {rel} ---\n{_minify_md(path)}")
            elif fname.endswith(".json"):
                parts.append(f"--- {rel} ---\n{_minify_json(path)}")

    return "\n".join(parts)


def _minify_yaml(path: str) -> str:
    """Parse YAML and re-serialize as compact JSON."""
    from ctxpack.core.packer.yaml_parser import yaml_parse

    with open(path, encoding="utf-8") as f:
        text = f.read()

    try:
        data = yaml_parse(text, filename=path)
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        # Fallback: just strip comments and blank lines
        return _strip_yaml_whitespace(text)


def _strip_yaml_whitespace(text: str) -> str:
    """Fallback: strip comments and collapse blank lines."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return " ".join(lines)


def _minify_json(path: str) -> str:
    """Parse JSON and re-serialize compactly."""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    try:
        data = json.loads(text)
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        return text.strip()


def _minify_md(path: str) -> str:
    """Strip blank lines, collapse whitespace, preserve headings."""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Collapse internal whitespace
        stripped = re.sub(r"\s+", " ", stripped)
        lines.append(stripped)
    return "\n".join(lines)
