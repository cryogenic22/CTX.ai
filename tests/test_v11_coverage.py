"""Behavior coverage for the modules the 85% floor has to actually exercise.

Synthetic inputs only. Each test asserts a product outcome (a route, a
conflict, a hydrated field, a parsed table), not that a mock was called.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from ctxpack.cli.main import main
from ctxpack.core.errors import Span
from ctxpack.core.model import CTXDocument, Header, KeyValue, Layer, PlainLine, Section
from ctxpack.core.operators import (
    OperatorKind,
    extract_crossrefs,
    extract_operators,
    extract_operators_from_doc,
)
from ctxpack.core.packer.compressor import compress
from ctxpack.core.packer.ir import (
    Certainty,
    IRCorpus,
    IREntity,
    IRField,
    IRSource,
    IRWarning,
    Severity,
)
from ctxpack.core.packer.toml_parser import (
    _fallback_toml_parse,
    extract_entities_from_toml,
)
from ctxpack.modules.analytics import (
    build_analytics_l3,
    compile_domain_packs,
    parse_domain_pack,
)
from ctxpack.modules.codebase import (
    analyze_codebase,
    export_agents_md,
    export_claude_md,
    export_rules,
    generate_harness,
)

_PACK = """\
version: 1
domain: {domain}
metadata:
  title: {title}
  description: {desc}
  extends: base-pack
vocabulary:
  entities:
    customer: {synonym}
  agent_persona:
    tone: precise
    preferred_time_grain: day
fingerprints:
  columns:
    - id: customer_id
      patterns: ["cust_id", "customer_id"]
      description: stable customer key
      data_types: [string]
      confidence: 0.9
      hints:
        unique: true
  values:
    - id: channel_values
      values: [web, store]
      description: where the order was placed
  tables:
    - id: orders
      required_columns: [customer_id, amount]
      optional_columns: [channel]
      description: order facts
      tags: [fact]
guardrails:
  pii_patterns:
    - id: email
      description: mailbox
      severity: high
  compliance_rules:
    - id: retain-7y
      description: keep invoices seven years
      severity: medium
experience:
  kbq_templates:
    - id: {domain}.kbq.channel_mix
      question: How did channel mix move?
      intent: compare
      required_metrics: [gross_sales]
      required_dimensions: [channel]
ontology:
  metrics:
    - name: gross_sales
      description: Sum of order amount
      formula: "{formula}"
      owner: finance
      tags: [revenue]
      sources: [orders]
      dimensions: [channel]
  dimensions:
    - name: channel
      description: Sales channel
      hierarchy: [region, store]
      keys: [channel_code]
      attributes: [name]
  synonyms:
    - term: revenue
      canonical: {domain}.metrics.gross_sales
    - term: ""
      canonical: ""
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_parse_domain_pack_rejects_empty_and_non_objects() -> None:
    assert parse_domain_pack("") == []
    assert parse_domain_pack("  \n") == []
    assert parse_domain_pack("- just\n- a\n- list\n") == []


def test_compile_domain_packs_dedups_fingerprints_and_flags_formula_conflict(
    tmp_path: Path,
) -> None:
    retail = _PACK.format(
        domain="retail", title="Retail", desc="Store orders",
        synonym="shopper", formula="sum(amount)",
    )
    airline = _PACK.format(
        domain="airline", title="Airline", desc="Ticket sales",
        synonym="passenger", formula="sum(fare)",
    )
    _write(tmp_path / "retail" / "v1" / "pack.yaml", retail)
    _write(tmp_path / "airline" / "v1" / "pack.yaml", airline)
    _write(tmp_path / "notes.txt", "not a pack")

    corpus = compile_domain_packs(str(tmp_path))
    names = {entity.name for entity in corpus.entities}
    assert "RETAIL" in names and "AIRLINE" in names
    assert "METRIC-RETAIL-GROSS-SALES" in names
    assert "DIM-AIRLINE-CHANNEL" in names
    metric = next(e for e in corpus.entities if e.name == "METRIC-RETAIL-GROSS-SALES")
    assert "revenue" in metric.aliases
    assert any(field.key == "FORMULA" and "sum(amount)" in field.value
               for field in metric.fields)
    domain = next(e for e in corpus.entities if e.name == "RETAIL")
    assert any(field.key == "ENUM-CHANNEL" for field in domain.fields)
    assert any(field.key == "PII-PATTERNS" for field in domain.fields)
    assert any(field.key == "KBQ-CHANNEL-MIX" for field in domain.fields)
    # The identical customer_id fingerprint is kept once and the copy is dropped.
    fp_fields = [
        field for entity in corpus.entities for field in entity.fields
        if field.key == "FP-CUSTOMER-ID"
    ]
    assert len(fp_fields) == 1
    assert fp_fields[0].additional_sources
    assert any("Metric conflict on GROSS-SALES" in warning.message
               for warning in corpus.warnings)
    assert corpus.source_files == [
        "airline/v1/pack.yaml", "retail/v1/pack.yaml",
    ]

    index = build_analytics_l3(corpus)
    assert "RETAIL:" in index and "AIRLINE:" in index
    assert "Warnings:" in index

    empty = compile_domain_packs(str(tmp_path / "missing-packs"))
    assert empty.entities == []


def _git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "Ada Lovelace",
        "GIT_AUTHOR_EMAIL": "ada@example.com",
        "GIT_COMMITTER_NAME": "Ada Lovelace",
        "GIT_COMMITTER_EMAIL": "ada@example.com",
    })
    subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True,
        capture_output=True, text=True,
    )


def _mini_repo(root: Path) -> None:
    _write(root / "pyproject.toml", """\
[tool.pytest.ini_options]
addopts = "--cov-fail-under=85"
testpaths = ["tests"]
""")
    _write(root / "routes" / "api.py", '''\
from fastapi import APIRouter

router = APIRouter(prefix="/v1")

@router.get("/orders")
async def list_orders():
    """List orders. Do not drop a cancelled row."""
    return []

@router.post("/orders")
def create_order(body: dict) -> dict:
    return body
''')
    _write(root / "models" / "order.py", '''\
import uuid
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    pass

class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[str]
    updated_at: Mapped[str]
''')
    _write(root / "src" / "services" / "billing.py", '''\
import celery

def charge(order_id: str) -> str:
    """Charge an order. Do not retry a captured payment."""
    return order_id
''')
    _write(root / "utils" / "helpers.py", '''\
def slug(text: str) -> str:
    return text.replace(" ", "-")
''')
    _write(root / "tests" / "test_billing.py", '''\
def test_charge_keeps_the_id():
    assert True
''')
    _write(root / "web" / "app" / "page.tsx", '''\
import React from "react";
export default function Home() { return <main>home</main>; }
''')
    _write(root / "web" / "app" / "products" / "page.tsx", '''\
import Link from "next/link";
export function ProductList() { return <Link href="/products">all</Link>; }
''')
    _write(root / "web" / "tailwind.config.ts", '''\
export const theme = { colors: { ink: "#111" } };
''')
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "feat(api): add the order route")
    _write(root / "src" / "services" / "tax.py", "def tax(amount: int) -> int:\n    return amount\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fix(billing): keep tax rounding")


def test_analyze_codebase_reports_routes_models_and_architecture(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _mini_repo(repo)
    cmap = analyze_codebase(str(repo))
    assert cmap.architecture == "service-layer"
    assert "FastAPI" in cmap.frameworks
    assert "SQLAlchemy" in cmap.frameworks
    routes = [route for module in cmap.modules for route in module.routes]
    assert "GET /v1/orders" in routes
    assert "POST /v1/orders" in routes
    models = [name for module in cmap.modules for name in module.models]
    assert "Order" in models
    assert any(module.path.replace("\\", "/").endswith("products/page.tsx")
               for module in cmap.modules)
    assert sum(module.test_count for module in cmap.modules) >= 1

    claude = export_claude_md(cmap, max_lines=80)
    assert "Order" in claude or "orders" in claude
    agents = export_agents_md(cmap, max_lines=80)
    assert "service-layer" in agents
    rules = export_rules(cmap, str(tmp_path / "rules"))
    assert rules
    assert any(path.endswith(".md") for path in rules)

    created = generate_harness(
        str(repo), output_dir=str(tmp_path / "harness"),
        max_pattern_examples=2, max_utility_entries=5,
    )
    names = {Path(path).name for path in created}
    assert "anti-slop.md" in names
    assert "test-requirements.md" in names
    assert "commit-conventions.md" in names
    assert "quality-check.py" in names
    anti = (tmp_path / "harness" / "rules" / "anti-slop.md").read_text(encoding="utf-8")
    assert "helpers.py" in anti or "utils" in anti
    commits = (tmp_path / "harness" / "rules" / "commit-conventions.md").read_text(
        encoding="utf-8")
    assert "feat" in commits
    # A second run does not overwrite files that already exist.
    assert generate_harness(str(repo), output_dir=str(tmp_path / "harness")) == []
    hook = (tmp_path / "harness" / "hooks" / "quality-check.py").read_text(encoding="utf-8")
    assert "def check_python_file" in hook
    assert "tests" in hook


def test_codebase_cli_analyze_and_export(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    _mini_repo(repo)
    assert main(["codebase", "analyze", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "Architecture: service-layer" in out
    assert "FastAPI" in out
    out_file = tmp_path / "AGENTS.md"
    assert main([
        "codebase", "export", str(repo),
        "--format", "agents-md", "-o", str(out_file), "--max-lines", "40",
    ]) == 0
    assert "service-layer" in out_file.read_text(encoding="utf-8")
    assert main(["codebase", "analyze", str(tmp_path / "nope")]) == 1


def _corpus() -> IRCorpus:
    source = IRSource(file="orders.md", line_start=1, line_end=4)
    widget = IREntity(
        name="WIDGET",
        annotations={"description": "A widget that must not be dropped."},
        sources=[source],
        fields=[
            IRField(key="★GOLDEN-SOURCE", value="orders.md", source=source),
            IRField(
                key="RULE",
                value="do-not-drop-the-widget",
                raw_value={"keep": "the widget", "when": "cancelled"},
                source=source,
                salience=0.9,
            ),
            IRField(
                key="NOTE",
                value="inferred-note",
                certainty=Certainty.INFERRED,
                source=source,
                salience=0.05,
            ),
            IRField(
                key="ALIASES",
                value="gadget",
                raw_value=["gadget", "gizmo"],
                source=source,
            ),
            IRField(
                key="BELONGS-TO",
                value="@ENTITY-ORDER",
                source=source,
            ),
        ],
    )
    order = IREntity(
        name="ORDER",
        sources=[IRSource(file="orders.md")],
        fields=[IRField(key="ID", value="order-id", source=source)],
    )
    return IRCorpus(
        domain="orders",
        scope="billing",
        author="ada",
        entities=[widget, order],
        standalone_rules=[IRField(key="KEEP", value="audit-log", source=source)],
        warnings=[IRWarning(entity="WIDGET", message="two names", severity=Severity.WARNING)],
        source_token_count=8000,
    )


def test_compress_preset_unknown_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown preset"):
        compress(_corpus(), preset="nope")


def test_compress_hydrates_when_the_floor_is_missed() -> None:
    doc = compress(
        _corpus(), min_tokens_per_entity=500, max_ratio=2.0, as_of="2026-11-26",
    )
    text_bits = []
    for element in doc.body:
        if isinstance(element, Section):
            for child in element.children:
                if isinstance(child, PlainLine):
                    text_bits.append(child.text)
                elif isinstance(child, KeyValue):
                    text_bits.append(f"{child.key}={child.value}")
    joined = "\n".join(text_bits)
    assert "must not be dropped" in joined
    assert "do not drop the widget" in joined
    assert any(field.key == "SCOPE" and field.value == "billing"
               for field in doc.header.metadata)
    assert any(field.key == "AUTHOR" and field.value == "ada"
               for field in doc.header.metadata)
    strict = compress(_corpus(), min_tokens_per_entity=500, strict=True, as_of="2026-11-26")
    strict_keys = [
        child.key for element in strict.body if isinstance(element, Section)
        for child in element.children if isinstance(child, KeyValue)
    ]
    assert "NOTE" not in strict_keys


def test_compress_balanced_preset_and_shuffle_keep_both_entities() -> None:
    balanced = compress(_corpus(), preset="balanced", as_of="2026-11-26")
    shuffled = compress(_corpus(), randomize_order=True, as_of="2026-11-26")
    def names(doc):
        return {element.name for element in doc.body if isinstance(element, Section)}
    assert "ENTITY-WIDGET" in names(balanced)
    assert "ENTITY-ORDER" in names(shuffled)


def test_fallback_toml_parser_extracts_entities_and_scalars() -> None:
    text = """\
# comment
title = "Orders" # inline
count = 2
active = true
ratio = 1.5
tags = ["do_not_drop", "keep"]
empty = null

[entity.Widget]
description = "the widget"
aliases = ["gadget"]
status = "live"
keep_rule = "do_not_drop"

[audit]
note = "standalone"
"""
    data = _fallback_toml_parse(text, filename="orders.toml")
    assert data["title"] == "Orders"
    assert data["count"] == 2
    assert data["active"] is True
    assert data["tags"] == ["do_not_drop", "keep"]
    entities, rules, warnings = extract_entities_from_toml(data, filename="orders.toml")
    assert warnings == []
    widget = next(entity for entity in entities if entity.name == "WIDGET")
    assert widget.aliases == ["gadget"]
    assert widget.annotations["description"] == "the widget"
    assert any(field.key == "KEEP-RULE" and "do-not-drop" in field.value
               for field in widget.fields)
    assert any(field.key == "TITLE" for field in rules) or any(
        field.value == "Orders" for field in rules
    )
    bare = _fallback_toml_parse('name = "only"\n', filename="bare.toml")
    entities, rules, _warnings = extract_entities_from_toml(bare, filename="bare.toml")
    assert entities == []
    assert any(field.key == "NAME" for field in rules)
    assert extract_entities_from_toml({}) == ([], [], [])


def test_operators_skip_backticks_and_walk_a_document() -> None:
    ops = extract_operators("keep `->` inside quotes but a → real arrow and ¬negation")
    kinds = [(op.kind, op.text) for op in ops]
    assert (OperatorKind.ARROW, "→") in kinds
    assert (OperatorKind.NEGATION, "¬") in kinds
    assert all(op.text != "->" for op in ops)
    refs = extract_crossrefs("see @ORDER and @DEF ns:=ORDER plus @FILE#SECTION")
    targets = [ref.target for ref in refs]
    assert "ORDER" in targets and "FILE#SECTION" in targets
    doc = CTXDocument(
        header=Header(magic="§CTX", version="1.0", layer=Layer.L2),
        body=(
            Section(
                name="ENTITY-ORDER",
                subtitles=("★ golden",),
                children=(
                    KeyValue(key="RULE", value="a → b"),
                    PlainLine(text="warn ⚠ here", span=Span.lines(3, 3)),
                ),
            ),
        ),
    )
    found = extract_operators_from_doc(doc)
    assert any(op.kind is OperatorKind.ARROW for op in found["ENTITY-ORDER/RULE"])
    assert "ENTITY-ORDER:subtitle" in found
    assert any("line" in key for key in found)


def test_cli_validate_fmt_diff_and_hydrate(tmp_path: Path, capsys) -> None:
    corpus = tmp_path / "corpus"
    _write(corpus / "widget.json", json.dumps({
        "entity": "Widget",
        "description": "Do not drop the widget",
        "status": "live",
    }))
    out = tmp_path / "widget.ctx"
    assert main([
        "pack", str(corpus), "-o", str(out), "--as-of", "2026-11-26",
        "--domain", "orders", "--author", "ada",
    ]) == 0
    assert out.is_file()
    capsys.readouterr()
    assert main(["validate", str(out)]) == 0
    assert "OK" in capsys.readouterr().out
    assert main(["fmt", str(out), "--ascii"]) == 0
    formatted = capsys.readouterr().out
    assert "$CTX" in formatted
    other = tmp_path / "other.ctx"
    other.write_text(formatted.replace("live", "retired"), encoding="utf-8")
    rc = main(["diff", str(out), str(other)])
    diff_out = capsys.readouterr().out
    assert rc == 1
    assert "live" in diff_out or "retired" in diff_out
    assert main(["hydrate", str(out), "--list"]) == 0
    listed = capsys.readouterr().out
    assert "WIDGET" in listed or "Sections" in listed
    assert main(["hydrate", str(out), "--query", "widget"]) == 0
    hydrated = capsys.readouterr().out
    assert "widget" in hydrated.lower()
    assert main(["hydrate", str(out)]) == 1
