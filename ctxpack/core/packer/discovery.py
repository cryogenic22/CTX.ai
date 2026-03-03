"""Corpus scanning and file classification for the packer."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Optional

from .yaml_parser import yaml_parse


@dataclass
class PackConfig:
    """Configuration loaded from ctxpack.yaml."""

    domain: str = ""
    scope: str = ""
    author: str = ""
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    entity_aliases: dict[str, list[str]] = field(default_factory=dict)
    golden_sources: dict[str, str] = field(default_factory=dict)
    template: str = ""


@dataclass
class DiscoveryResult:
    """Result of scanning a corpus directory."""

    yaml_files: list[str] = field(default_factory=list)
    md_files: list[str] = field(default_factory=list)
    json_files: list[str] = field(default_factory=list)
    config: PackConfig = field(default_factory=PackConfig)
    corpus_root: str = ""


def discover(
    corpus_dir: str,
    *,
    domain: Optional[str] = None,
    scope: Optional[str] = None,
    author: Optional[str] = None,
) -> DiscoveryResult:
    """Walk corpus directory, classify files, and load config.

    Args:
        corpus_dir: Root directory of the corpus.
        domain: Override domain (takes priority over ctxpack.yaml).
        scope: Override scope.
        author: Override author.

    Returns:
        DiscoveryResult with classified files and merged config.
    """
    corpus_dir = os.path.abspath(corpus_dir)
    result = DiscoveryResult(corpus_root=corpus_dir)

    # Load config
    config_path = os.path.join(corpus_dir, "ctxpack.yaml")
    if not os.path.exists(config_path):
        config_path = os.path.join(corpus_dir, "ctxpack.yml")
    if os.path.exists(config_path):
        result.config = _load_config(config_path)

    # CLI overrides
    if domain:
        result.config.domain = domain
    if scope:
        result.config.scope = scope
    if author:
        result.config.author = author

    # Walk directory
    for root, _dirs, files in os.walk(corpus_dir):
        for fname in sorted(files):
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, corpus_dir).replace("\\", "/")

            # Skip config file itself
            if fname in ("ctxpack.yaml", "ctxpack.yml"):
                continue

            # Check exclude patterns
            if _matches_any(rel_path, result.config.exclude):
                continue

            # Check include patterns (empty means include all)
            if result.config.include and not _matches_any(
                rel_path, result.config.include
            ):
                continue

            # Classify
            lower = fname.lower()
            if lower.endswith((".yaml", ".yml")):
                result.yaml_files.append(full_path)
            elif lower.endswith(".md"):
                result.md_files.append(full_path)
            elif lower.endswith(".json"):
                result.json_files.append(full_path)

    return result


def _load_config(path: str) -> PackConfig:
    """Load PackConfig from a ctxpack.yaml file."""
    with open(path, encoding="utf-8") as f:
        data = yaml_parse(f.read(), filename=path)

    if not isinstance(data, dict):
        return PackConfig()

    config = PackConfig(
        domain=str(data.get("domain", "")),
        scope=str(data.get("scope", "")),
        author=str(data.get("author", "")),
    )

    inc = data.get("include")
    if isinstance(inc, list):
        config.include = [str(x) for x in inc]

    exc = data.get("exclude")
    if isinstance(exc, list):
        config.exclude = [str(x) for x in exc]

    aliases = data.get("entity_aliases")
    if isinstance(aliases, dict):
        for k, v in aliases.items():
            if isinstance(v, list):
                config.entity_aliases[str(k).upper()] = [str(a) for a in v]

    golden = data.get("golden_sources")
    if isinstance(golden, dict):
        config.golden_sources = {str(k).upper(): str(v) for k, v in golden.items()}

    tmpl = data.get("template")
    if isinstance(tmpl, str) and tmpl:
        config.template = tmpl

    return config


def _matches_any(path: str, patterns: list[str]) -> bool:
    """Check if path matches any glob pattern."""
    for pat in patterns:
        if fnmatch(path, pat):
            return True
    return False
