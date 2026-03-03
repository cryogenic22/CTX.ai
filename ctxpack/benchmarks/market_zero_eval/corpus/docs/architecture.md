# Market-Zero Architecture

## Overview

Market-Zero is a war-gaming engine for pharmaceutical strategy. It evaluates drug launch strategies against live market signals using a deterministic risk scoring engine backed by source-verified data from 11 public APIs.

Core principle: No fabricated data. Every data point traces to a verifiable external source with complete provenance tracking.

## Five-Layer Data Architecture

- **Connector Layer**: 11 source adapters (FDA Orange Book, ClinicalTrials.gov, PubMed, SEC EDGAR, MeSH, FDA Shortages, openFDA FAERS, openFDA Labels, PubMed Central, User Document, User URL). Each implements BaseConnector.fetch() returning list of RawRecord objects with Provenance.
- **Integration Layer**: 5-step pipeline (Normalize, Resolve, Embed, Store, Cross-Link). Source-agnostic: same steps for FDA data, user PDFs, and web URLs.
- **Knowledge Layer**: PostgreSQL 16 with pgvector. Unified schema for all 9 entity types plus entity_links table for flattened relationship graph.
- **Semantic Layer**: Hybrid retrieval combining vector similarity (OpenAI text-embedding-3-small, 1536 dimensions) with structured SQL filters and ontology traversal.
- **Query Layer**: Risk scoring engine, multi-agent orchestration (LangGraph), FastAPI endpoints, React frontend.

## Domain Pack Abstraction

All domain-specific configuration lives in a single DomainPack dataclass. The pipeline is completely domain-agnostic. Swapping domains (e.g. pharma to genomics) requires only instantiating a different pack with no core code changes.

DomainPack contains: entity schemas, link rules, field mappings, source configurations, agent personas, mention normalizers, staleness tracking rules.

## Integration Pipeline Details

1. Normalize: Map source-specific field names to canonical schema (config-driven from domain pack field mappings)
2. Resolve: 6-strategy cascade - exact ID lookup, fuzzy name matching (threshold 0.85), embedding similarity (threshold 0.82), LLM resolution, auto-create (for trusted sources), human-in-the-loop (unresolved queue for admin review)
3. Embed: Batched OpenAI text-embedding-3-small calls for text-bearing records
4. Store: Upsert to correct table with SHA-256 content hash for dedup. Provenance preserved on every insert/update.
5. Cross-Link: Apply declarative link rules from domain pack. Ontology-mediated links via MeSH terms. Idempotent upsert prevents duplicates.

## Agent Orchestration (LangGraph)

Two query modes, auto-routed:
- **Research Mode**: Fact lookup via hybrid retrieval (vector + SQL) then LLM synthesis with citations
- **Simulation Mode**: Strategy evaluation via parameter extraction, live MarketSnapshot assembly, risk engine scoring, optional LLM critique (only if score > 7.0)

Four agent personas (configurable in domain pack): Clinical Researcher, Market Analyst, Regulatory Expert, Data Scientist. Each has its own system prompt and tool access.

## Entity Resolution

Fuzzy matching below 95% confidence goes to unresolved_entities table for admin review. Resolved matches become entity_aliases for instant future lookups. Auto-create threshold: 0.95. Review threshold: 0.85 to 0.95. Reject threshold: below 0.85.
