"""Domain knowledge packer: corpus → .ctx L2 file.

Usage:
    from ctxpack.core.packer import pack
    doc = pack("/path/to/corpus")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from ..model import CTXDocument
from .compressor import compress
from .conflict import detect_conflicts
from .discovery import PackConfig, discover
from .entity_resolver import resolve_entities
from .ir import IRCorpus, IRField, IRSource
from .md_parser import extract_entities_from_md
from .yaml_parser import extract_entities_from_yaml, yaml_parse


@dataclass
class PackResult:
    """Result of packing a corpus."""

    document: CTXDocument
    source_token_count: int = 0
    source_file_count: int = 0
    entity_count: int = 0
    warning_count: int = 0


def pack(
    corpus_dir: str,
    *,
    domain: Optional[str] = None,
    scope: Optional[str] = None,
    author: Optional[str] = None,
) -> PackResult:
    """Pack a corpus directory into a CTXDocument (L2).

    Pipeline: discover → parse → entity_resolve → dedup →
              salience_score → compress → detect_conflicts → CTXDocument
    """
    # 1. Discovery
    disc = discover(corpus_dir, domain=domain, scope=scope, author=author)
    config = disc.config

    # 2. Parse all files
    corpus = IRCorpus(
        domain=config.domain,
        scope=config.scope,
        author=config.author,
    )

    # Parse YAML files
    for yaml_file in disc.yaml_files:
        _parse_yaml_file(yaml_file, corpus, disc.corpus_root)

    # Parse Markdown files
    for md_file in disc.md_files:
        _parse_md_file(md_file, corpus, config, disc.corpus_root)

    # Count source tokens
    total_tokens = 0
    all_files = disc.yaml_files + disc.md_files
    for fpath in all_files:
        with open(fpath, encoding="utf-8") as f:
            total_tokens += len(f.read().split())
    corpus.source_token_count = total_tokens
    corpus.source_files = [
        os.path.relpath(f, disc.corpus_root).replace("\\", "/")
        for f in all_files
    ]

    # 3. Entity resolution
    resolve_entities(corpus, alias_map=config.entity_aliases)

    # 4. Conflict detection
    conflicts = detect_conflicts(corpus)
    corpus.warnings.extend(conflicts)

    # 5. Compression → CTXDocument
    doc = compress(corpus)

    return PackResult(
        document=doc,
        source_token_count=total_tokens,
        source_file_count=len(all_files),
        entity_count=len(corpus.entities),
        warning_count=len(corpus.warnings),
    )


def _parse_yaml_file(path: str, corpus: IRCorpus, root: str) -> None:
    """Parse a YAML file and add entities/rules to corpus."""
    rel_path = os.path.relpath(path, root).replace("\\", "/")
    with open(path, encoding="utf-8") as f:
        text = f.read()

    data = yaml_parse(text, filename=rel_path)
    if not isinstance(data, dict):
        return

    entities, rules, warnings = extract_entities_from_yaml(
        data, filename=rel_path
    )
    corpus.entities.extend(entities)
    corpus.standalone_rules.extend(rules)
    corpus.warnings.extend(warnings)


def _parse_md_file(path: str, corpus: IRCorpus, config: PackConfig, root: str) -> None:
    """Parse a Markdown file and add entities/rules/warnings to corpus."""
    rel_path = os.path.relpath(path, root).replace("\\", "/")
    with open(path, encoding="utf-8") as f:
        text = f.read()

    entities, rules, warnings = extract_entities_from_md(
        text,
        filename=rel_path,
        alias_map=config.entity_aliases,
    )
    corpus.entities.extend(entities)
    corpus.standalone_rules.extend(rules)
    corpus.warnings.extend(warnings)
