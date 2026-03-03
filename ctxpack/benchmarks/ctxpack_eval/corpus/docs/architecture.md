# ctxpack Architecture

## Overview

ctxpack is a domain knowledge packer that compresses corpus directories into structured .ctx files.
It is designed as "MP3 for LLM context" — a multi-resolution compression codec for LLM context windows.

## Four-Layer Model

The .ctx format uses four compression layers:

- **L0 (Raw)**: Original source files, unmodified
- **L1 (Compressed Prose)**: Natural language summary with structure preserved
- **L2 (Semantic Graph)**: Structured entity-relationship notation with operators and salience scoring
- **L3 (Abstract Gist)**: Ultra-compressed gist under 500 tokens with topology and constraint extraction

## Zero-Dependency Principle

The entire packer pipeline is pure Python with zero external dependencies:

- No LLM or ML model is used at any stage
- All output is deterministic for the same input
- YAML parsing uses a custom stdlib-only subset parser
- Token counting uses simple whitespace splitting
- L3 generation is purely algorithmic extraction from L2 AST

## AST Design

The CTXDocument AST uses frozen (immutable) dataclasses:

- Header: magic, version, layer, status fields, metadata
- Body: tuple of Sections and BodyElements
- Section: name, subtitles, indent, depth, children
- BodyElements: KeyValue, PlainLine, NumberedItem, InlineList, QuotedBlock, Provenance

Immutability ensures the AST cannot be accidentally modified after parsing.

## Integration Points

- **CLI**: `ctxpack parse|validate|fmt|pack|eval|diff` commands
- **MCP Server**: Query-adaptive hydration via manifest entity/keyword indexes
- **Library**: `pack()` function returns PackResult with document, provenance, L3, and manifest
