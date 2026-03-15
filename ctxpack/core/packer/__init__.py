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
from .csv_parser import csv_parse, extract_entities_from_csv
from .json_parser import extract_entities_from_json, json_parse
from .l3_generator import generate_l3
from .manifest import generate_manifest
from .md_parser import extract_entities_from_md
from .prov_generator import generate_provenance, inject_inline_provenance
from .templates import load_template, validate_corpus
from .toml_parser import extract_entities_from_toml, toml_parse
from .xref_resolver import resolve_xrefs
from .yaml_parser import extract_entities_from_yaml, yaml_parse


@dataclass
class PackResult:
    """Result of packing a corpus."""

    document: CTXDocument
    source_token_count: int = 0
    source_file_count: int = 0
    entity_count: int = 0
    warning_count: int = 0
    provenance_text: str = ""
    l3_document: Optional[CTXDocument] = None
    manifest_document: Optional[CTXDocument] = None


def pack(
    corpus_dir: str,
    *,
    domain: Optional[str] = None,
    scope: Optional[str] = None,
    author: Optional[str] = None,
    strict: bool = False,
    provenance: str = "companion",
    layers: Optional[list[str]] = None,
    max_ratio: float = 0,
    min_tokens_per_entity: int = 0,
    template: Optional[str] = None,
    randomize_order: bool = False,
    preset: str = "",
) -> PackResult:
    """Pack a corpus directory into a CTXDocument (L2).

    Pipeline: discover → parse → entity_resolve → dedup →
              salience_score → compress → detect_conflicts → CTXDocument

    Args:
        max_ratio: Maximum compression ratio (e.g. 10.0). 0 = no limit.
        min_tokens_per_entity: Minimum token budget per entity. 0 = no limit.
        preset: Named compression preset ("conservative", "balanced", "aggressive").
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

    # Parse JSON files
    for json_file in disc.json_files:
        _parse_json_file(json_file, corpus, disc.corpus_root)

    # Parse TOML files
    for toml_file in disc.toml_files:
        _parse_toml_file(toml_file, corpus, disc.corpus_root)

    # Parse CSV files
    for csv_file in disc.csv_files:
        _parse_csv_file(csv_file, corpus, disc.corpus_root)

    # Count source tokens
    total_tokens = 0
    all_files = disc.yaml_files + disc.md_files + disc.json_files + disc.toml_files + disc.csv_files
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

    # 3b. Template validation (after entity resolution, before conflict detection)
    template_name = template or config.template
    if template_name:
        tmpl = load_template(template_name)
        tmpl_warnings = validate_corpus(corpus, tmpl)
        corpus.warnings.extend(tmpl_warnings)

    # 4. Conflict detection
    conflicts = detect_conflicts(corpus)
    corpus.warnings.extend(conflicts)

    # 5. Provenance generation (before compression to allow inline mode)
    prov_text = ""
    if provenance == "companion":
        prov_text = generate_provenance(corpus)
    elif provenance == "inline":
        inject_inline_provenance(corpus)

    # 6. Compression → CTXDocument
    doc = compress(corpus, strict=strict,
                   max_ratio=max_ratio,
                   min_tokens_per_entity=min_tokens_per_entity,
                   randomize_order=randomize_order,
                   preset=preset)

    # 7. L3 generation (if requested)
    if layers is None:
        layers = ["L2"]
    l3_doc = None
    manifest_doc = None
    if "L3" in layers:
        l3_doc = generate_l3(doc)
        layer_map = {"L2": doc, "L3": l3_doc}
        manifest_doc = generate_manifest(
            layer_map,
            domain=config.domain or "unknown",
        )

    return PackResult(
        document=doc,
        source_token_count=total_tokens,
        source_file_count=len(all_files),
        entity_count=len(corpus.entities),
        warning_count=len(corpus.warnings),
        provenance_text=prov_text,
        l3_document=l3_doc,
        manifest_document=manifest_doc,
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

    # Resolve cross-references before entity extraction
    text = resolve_xrefs(text)

    entities, rules, warnings = extract_entities_from_md(
        text,
        filename=rel_path,
        alias_map=config.entity_aliases,
    )
    corpus.entities.extend(entities)
    corpus.standalone_rules.extend(rules)
    corpus.warnings.extend(warnings)


def _parse_json_file(path: str, corpus: IRCorpus, root: str) -> None:
    """Parse a JSON file and add entities/rules to corpus."""
    rel_path = os.path.relpath(path, root).replace("\\", "/")
    with open(path, encoding="utf-8") as f:
        text = f.read()

    data = json_parse(text, filename=rel_path)

    entities, rules, warnings = extract_entities_from_json(
        data, filename=rel_path
    )
    corpus.entities.extend(entities)
    corpus.standalone_rules.extend(rules)
    corpus.warnings.extend(warnings)


def _parse_toml_file(path: str, corpus: IRCorpus, root: str) -> None:
    """Parse a TOML file and add entities/rules to corpus."""
    rel_path = os.path.relpath(path, root).replace("\\", "/")
    with open(path, encoding="utf-8") as f:
        text = f.read()

    data = toml_parse(text, filename=rel_path)
    if not isinstance(data, dict):
        return

    entities, rules, warnings = extract_entities_from_toml(
        data, filename=rel_path
    )
    corpus.entities.extend(entities)
    corpus.standalone_rules.extend(rules)
    corpus.warnings.extend(warnings)


def _parse_csv_file(path: str, corpus: IRCorpus, root: str) -> None:
    """Parse a CSV file and add entities/rules to corpus."""
    rel_path = os.path.relpath(path, root).replace("\\", "/")
    with open(path, encoding="utf-8") as f:
        text = f.read()

    data = csv_parse(text, filename=rel_path)

    entities, rules, warnings = extract_entities_from_csv(
        data, filename=rel_path
    )
    corpus.entities.extend(entities)
    corpus.standalone_rules.extend(rules)
    corpus.warnings.extend(warnings)
