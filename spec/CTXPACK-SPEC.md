# CTXPACK-SPEC v1.0

## `.ctx` Format Specification

**Status:** Draft
**Version:** 1.0
**Date:** 2026-02-21
**Author:** Kapil Pant
**License:** CC-BY-SA 4.0

---

## Table of Contents

1. [Preamble & Motivation](#1-preamble--motivation)
2. [Document Structure](#2-document-structure)
3. [Layer Definitions](#3-layer-definitions)
4. [Operator Alphabet](#4-operator-alphabet)
5. [Notation Rules](#5-notation-rules)
6. [References and Linking](#6-references-and-linking)
7. [Multi-Layer File Organization](#7-multi-layer-file-organization)
8. [Salience, Ordering, and Positioning](#8-salience-ordering-and-positioning)
9. [Provenance](#9-provenance)
10. [Versioning and Diffing](#10-versioning-and-diffing)
11. [Encoding](#11-encoding)
12. [PEG Grammar](#12-peg-grammar)
13. [Conformance Levels](#13-conformance-levels)
14. [Context Protocol](#14-context-protocol)
15. [Examples](#15-examples)
16. [Design Rationale Appendix](#16-design-rationale-appendix)

---

## 1. Preamble & Motivation

### What `.ctx` Is

`.ctx` is a text-based, multi-resolution context compression format optimized for LLM consumption. It defines a portable, human-readable, machine-parseable encoding for compressed knowledge — enabling context to be packed once and hydrated adaptively per query.

### What `.ctx` Is Not

- Not a general-purpose serialization format (use JSON, YAML, Protobuf)
- Not a knowledge graph interchange format (use RDF, OWL)
- Not a prompt template language (use Jinja, Handlebars)
- Not a lossy token-deletion scheme (that's LLMLingua's approach)
- Not an opaque vector encoding (that's gist tokens)

### The MP3 Analogy

MP3 defines a frame structure (sync bits, header, audio data) and a perceptual codec (psychoacoustic model compresses for the human ear). `.ctx` mirrors this:

```
MP3:  [Sync bits] [Header] [Audio data]  — psychoacoustic model → human ear
.ctx: [§CTX magic] [Header] [Body]       — transformer perceptual model → attention mechanism
```

MP3 exploits the fact that human hearing has gaps (frequency masking, temporal masking). `.ctx` exploits analogous gaps in LLM attention: language is redundant, salience is non-uniform, positional attention decays in the middle, and LLMs already "know" well-known abstractions from training.

### Design Philosophy

**"Parseable scaffolding, semantic payload."**

The format has two tiers:
- **Tier 1 (scaffolding):** Header, section markers, key-value pairs, operators — strictly parseable by a PEG grammar, enabling tooling (indexing, diffing, validation).
- **Tier 2 (payload):** The semantic content within values and descriptions — written in expert-to-expert register, optimized for LLM comprehension, not formally constrained.

### Key Principle: Expert-to-Expert Register

`.ctx` content is written as if one domain expert is briefing another — like clinical shorthand between physicians, or architecture decision records between senior engineers. The "reader" (an LLM) has an enormous vocabulary and perfect inference from training data. This means:

- No persuasive prose (the LLM doesn't need convincing)
- No pedagogical scaffolding (the LLM doesn't need teaching)
- No navigational transitions (the LLM reads in parallel)
- Every fact, number, relationship, and constraint is preserved

---

## 2. Document Structure

### Anatomy

Every `.ctx` file has two parts separated by a blank line:

```
┌─────────────────────────────────┐
│ Status line: §CTX v1.0 L2 ...  │  ← Magic + version + layer
│ KEY:value metadata              │  ← Header fields
│ KEY:value metadata              │
│                                 │  ← Blank line terminates header
│ ±SECTION-NAME                   │  ← Body begins
│ content...                      │
│                                 │
│ ±ANOTHER-SECTION                │
│ content...                      │
└─────────────────────────────────┘
```

### Header

The header is the strictly parseable portion of a `.ctx` file.

**Line 1 (status line):** Must begin with the magic literal `§CTX` (or ASCII fallback `$CTX`), followed by space-separated fields:

```
§CTX v{major}.{minor} L{0-3} [FIELD:value ...]
```

The status line MUST contain at least:
1. `§CTX` — format magic identifier
2. `v{M}.{m}` — spec version (semver major.minor)
3. `L{0-3}` — compression layer

Additional `KEY:value` pairs MAY appear on the status line after the three required fields.

**Lines 2+ (metadata):** One `KEY:value` pair per line. The header ends at the first blank line.

### Required Header Fields

| Field | Format | Purpose | Example |
|-------|--------|---------|---------|
| `§CTX` | magic literal | Format identifier | `§CTX` |
| `v{M}.{m}` | semver | Spec version | `v1.0` |
| `L{0-3}` | layer enum | Compression layer | `L2` |
| `DOMAIN:{value}` | hyphenated-id | Semantic domain | `DOMAIN:data-engineering` |
| `COMPRESSED:{date}` | ISO-8601 | When packed | `COMPRESSED:2026-02-21` |
| `SOURCE_TOKENS:~{n}` | approx integer | Original token count | `SOURCE_TOKENS:~40000` |

The `DOMAIN` field may appear on the status line or on a subsequent header line. All other required fields must be present somewhere in the header (status line or subsequent lines).

### Recommended Header Fields

| Field | Format | Purpose |
|-------|--------|---------|
| `SCOPE:{value}` | hyphenated-id | Content scope descriptor |
| `AUTHOR:{value}` | hyphenated-id | Creator identity |
| `CTX_TOKENS:~{n}` | approx integer | Compressed token count |
| `SOURCE:{uri}` | path, git ref, or URL | What was compressed |
| `RATIO:~{n}x` | approx multiplier | Compression ratio |
| `GEN:{n}` | positive integer | Generation number (increments on re-pack) |
| `HASH:sha256:{hex}` | hash digest | Body integrity check (hex-encoded SHA-256 of body after header) |
| `PROVENANCE:{chain}` | arrow-separated | Compression lineage, e.g. `L0→L2` |
| `SCHEMA:{uri}` | URL | Link to spec version used |
| `TURNS:{n}` | positive integer | Source conversation turns (if from dialogue) |

### Header Parsing Rules

1. The first `:` on a header line splits key from value; subsequent colons are part of the value.
2. Keys are conventionally `UPPER-CASE-HYPHENATED` but parsers SHOULD accept any case.
3. Unknown keys MUST be preserved by conformant tools (forward compatibility).
4. The status line is syntactically special: it contains space-separated tokens, not colon-separated pairs.

### Compatibility Note

The existing `ctx_mod.ctx` reference file places `DOMAIN`, `SCOPE`, and `AUTHOR` on the status line (line 1) as space-separated fields. This is valid: any `KEY:value` token on the status line is parsed as a header field. The `TURNS` field is a valid recommended field.

---

## 3. Layer Definitions

Each layer represents a different compression level, analogous to audio bitrates. Layers are defined by: purpose, grammar strictness, body conventions, typical compression ratio, and provenance requirements.

### L0 — Raw

| Property | Value |
|----------|-------|
| **Purpose** | Verbatim source text, no compression |
| **Typical ratio** | 1x (no compression) |
| **Grammar** | Header-strict, body-unconstrained |
| **Body format** | Original text, unchanged |
| **Provenance** | N/A (is the source) |
| **Use case** | On-demand retrieval only; never pre-injected |

L0 files are the source material. They carry a `.ctx` header for metadata consistency but the body is the unmodified original. L0 is typically not stored in a `.ctxpack/` directory — it is referenced by path.

### L1 — Compressed Prose (~5-10x)

| Property | Value |
|----------|-------|
| **Purpose** | Terse natural language with structural markers |
| **Typical ratio** | 5-10x vs raw source |
| **Grammar** | Header-strict, body-soft (editorial policy, not grammar) |
| **Body format** | Compressed prose paragraphs with optional `.ctx` operators |
| **Provenance** | Per-paragraph `SRC:` encouraged |
| **Framing** | "MP3 at 320kbps — technically compressed, perceptually near-lossless" |

**L1 body conventions:**
- Declarative sentences, no filler, hedging, or transitions
- Expert register — assumes reader has domain knowledge
- `±` section markers for structure
- `KEY:value` pairs where useful for structured data
- `.ctx` operators (section 4) optional but encouraged
- Inline citations: `SRC:path/file.ext#L10-L50` encouraged per paragraph

**What L1 strips:**
- Persuasive/motivational prose
- Navigational scaffolding (section numbering, "as mentioned above")
- Examples of well-known abstractions (LLM has training data)
- Redundant context re-establishment

**What L1 preserves:**
- Every fact, number, relationship, constraint
- Domain-specific edge cases and exceptions
- Exact identifiers (function names, API endpoints, config keys)

### L2 — Semantic Graph (~20-50x)

| Property | Value |
|----------|-------|
| **Purpose** | Structured notation — entities, relations, assertions |
| **Typical ratio** | 20-50x vs raw source |
| **Grammar** | Header-strict, body-validatable (PEG grammar, section 12) |
| **Body format** | Sections, key-value pairs, operators, lists |
| **Provenance** | Per-section `SRC:` optional |
| **Role** | The "workhorse" layer — most commonly hydrated |

**L2 body conventions:**
- `±SECTION-NAME` markers divide content
- `KEY:value` is the primary notation pattern
- Operators from the alphabet (section 4) encode relationships
- Hyphenated compounds for multi-word concepts
- Inline lists: `[item1,item2,item3]`
- Ordering: **descending salience** within each section (most important first)
- Nesting via 2-space indentation

**L2 is the primary format for:**
- Codebase architecture summaries
- Domain knowledge rule graphs
- Entity-relationship documentation
- Decision records and constraints

`ctx_mod.ctx` is an L2 file and serves as the canonical reference for this layer.

### L3 — Abstract Gist (~100x+)

| Property | Value |
|----------|-------|
| **Purpose** | Ultra-compressed essence — themes, patterns, core facts |
| **Typical ratio** | 100x+ vs raw source |
| **Grammar** | Header-strict, body-validatable, near-schema |
| **Body format** | Fixed set of required slots |
| **Provenance** | Header-level `SOURCE:` only |
| **Size target** | <500 tokens |
| **Principle** | "Progressive JPEG — usable even alone" |

**Required L3 slots:**

Every L3 file MUST contain at least these sections:

| Slot | Purpose |
|------|---------|
| `±ENTITIES` | Named entities, their types, and relationships |
| `±PATTERNS` | Recurring patterns, conventions, architectural decisions |
| `±CONSTRAINTS` | Hard rules, invariants, non-negotiable requirements |
| `±WARNINGS` | Known pitfalls, gotchas, common failure modes |

**Optional L3 slots:**

| Slot | Purpose |
|------|---------|
| `±SUMMARY` | One-line project/domain description |
| `±STACK` | Technology stack / dependency overview |
| `±STATUS` | Current state, active work, blockers |

**L3 design constraint:** L3 must be **self-contained**. An LLM receiving only L3 must be able to orient itself and provide useful (if surface-level) responses. L3 is always injected — it is the "poster frame" of the context.

---

## 4. Operator Alphabet

The operator alphabet is a fixed set of symbols with defined semantics. These symbols are drawn from notations heavily represented in LLM training data (type theory, formal logic, programming languages, mathematics), ensuring high-confidence semantic interpretation.

### Core Operators (v1.0)

| Symbol | ASCII Fallback | Semantics | Training Source |
|--------|---------------|-----------|----------------|
| `→` | `->` | Implication, causation, dataflow | Type theory, logic, Haskell |
| `¬` | `!` | Negation ("not") | Formal logic, programming |
| `+` | `+` | Conjunction ("and", "also") | Universal |
| `\|` | `\|` | Disjunction, alternative ("or") | Programming, BNF |
| `>>` | `>>` | Temporal sequence ("then") | Shell pipes, Haskell monads |
| `~>` | `~>` | Weak association, correlation | Ruby, semver constraints |
| `★` | `***` | Emphasis flag | Markdown-adjacent |
| `⚠` | `WARN:` | Warning, caution | Unicode standard |
| `±` | `##` | Section marker | Repurposed (plus-minus → "heading") |
| `§` | `$CTX` | Format magic | Legal tradition (section sign) |
| `@` | `@` | Cross-reference | Email, social media, decorators |
| `≡` | `===` | Entity equivalence / identity | Math, logic, JS strict equality |
| `⊥` | `CONFLICT:` | Contradiction between assertions | Logic (bottom/falsum) |
| `?` (suffix) | `?` | Uncertainty modifier | Universal |
| `:` | `:` | Key-value separator | YAML, JSON, Python |
| `()` | `()` | Annotation, parenthetical | Universal |
| `[]` | `[]` | List, enumeration | Programming, Markdown |
| `~` | `~` | Approximation | Mathematics |

### Operator Rules

1. **Fixed symbols, not patterns.** Each operator is a specific character or character sequence. They are not regular expressions or wildcards.

2. **Disambiguation of arrow operators:**
   - `→` for **causation/implication** ("A causes B", "A implies B", "data flows from A to B")
   - `>>` for **temporal sequence** ("first A, then B", "A happens before B")
   - `~>` for **weak association** ("A correlates with B", "A is loosely related to B")

3. **`?` as trailing modifier only.** The `?` operator is valid only as a suffix: `VALUE:5%?` means "approximately 5%, with uncertainty". It does not function as a standalone operator.

4. **`★` and `⚠` are binary flags, not graduated scores.** Use `★` to flag high-emphasis content. Use `⚠` to flag warnings. Do not use multiples (e.g., `★★★`) — salience is expressed through layer assignment and ordering, not flag repetition.

5. **Extensibility.** New operators require a spec revision (minor version bump). The alphabet is intentionally small — a small set of high-confidence symbols is better than a large set of ambiguous ones. Operators not in this table are treated as literal text.

6. **Whitespace around operators.** Operators may appear with or without surrounding whitespace. `A→B` and `A → B` are equivalent. Parsers MUST handle both forms.

---

## 5. Notation Rules

### Section Markers

Section markers divide the body into logical units.

**Syntax:** `±SECTION-NAME` at the start of a line.

```
±ARCHITECTURE
content here...

±ARCHITECTURE MULTI-RESOLUTION-CODEC
content with subtitle...
```

- The `±` character (or `##` ASCII fallback) marks a section heading.
- `SECTION-NAME` is `UPPER-CASE-HYPHENATED` by convention.
- Optional subtitle(s) follow the name, space-separated, on the same line.
- A blank line before a section marker is conventional but not required.

**Nesting:**

Nesting is expressed via 2-space indentation:

```
±ARCHITECTURE
  ±LAYERS
  content about layers...
  ±PACKER
  content about packer...
```

Alternatively, explicit depth markers are supported: `±{depth} SECTION-NAME` where `{depth}` is a positive integer.

```
±1 ARCHITECTURE
±2 LAYERS
±2 PACKER
```

**Maximum depth:** 4 levels recommended. Beyond 4 levels, refactor into a separate `.ctx` file linked via `@` cross-reference.

### Key-Value Pairs

The primary notation pattern for structured data.

**Syntax:** `KEY:value`

```
LANGUAGE:Python
FRAMEWORK:FastAPI+SQLAlchemy
STATUS:production(stable)
```

**Rules:**
1. The **first** `:` on a line splits key from value. Subsequent colons are part of the value: `URL:https://example.com:8080` → key=`URL`, value=`https://example.com:8080`.
2. Keys are `UPPER-CASE-HYPHENATED` by convention. Parsers SHOULD accept any case.
3. Multi-value syntax uses `+` for conjunction or `[]` for lists:
   - `DEPS:FastAPI+SQLAlchemy+Redis`
   - `DEPS:[FastAPI,SQLAlchemy,Redis]`
4. Parenthetical annotations qualify values: `STATUS:production(stable,since-2025-Q3)`

### Hyphenated Compounds

Multi-word concepts are joined by hyphens:

```
domain-knowledge-compression
entity-resolution-pipeline
lost-in-middle-effect
```

**Rationale:**
- Most token-efficient joining convention (typically 1 token per compound vs. 2-3 for spaces)
- Unambiguous word boundaries
- Familiar from CSS properties, CLI flags, URL slugs
- Does not conflict with any operator in the alphabet

**Not used:** camelCase, snake_case, or spaces within compound terms.

### Lists

**Inline list:**
```
DEPS:[FastAPI,SQLAlchemy,Redis]
```

**Structured inline list:**
```
LAYERS:[L0:raw,L1:prose,L2:graph,L3:gist]
```

**Multi-line list:**
```
±FRAMEWORKS
  1.INFORMATION-BOTTLENECK(Tishby-1999)
  2.RATE-DISTORTION(Shannon-1959)
  3.RENORMALISATION-GROUP(Wilson-1982)
```

**Sequence list (ordered temporal/procedural):**
```
SEQUENCE[
  W1:LinkedIn-teaser,
  W2:arXiv-paper+GitHub-repo,
  W3-4:blog-post+community-engagement
]
```

**Rules:**
- Inline lists use `[]` with `,` separators.
- Multi-line lists use indentation under a parent section or key.
- Numbered items use `{n}.` prefix (no space required after dot).
- Items in a sequence list may use `KEY:value` syntax.

### Quoting and Escaping

**Inline literal:** Backtick quoting preserves content verbatim:

```
COMMAND:`ctxpack init --domain=finance`
PATTERN:`KEY:value→result`
```

Content within backticks is not parsed for operators or key-value syntax.

**Block literal:** Triple-backtick fenced blocks (Markdown convention):

````
```
def example():
    return "verbatim code"
```
````

**No backslash escaping.** The format does not use `\` as an escape character. Backtick quoting handles all cases where literal content might be confused with operators.

**Rationale:** Backtick quoting is deeply familiar to LLMs from Markdown training data — it triggers "treat as literal" semantics with high reliability.

### Compression Guidance: What Gets Stripped

When compressing source text to `.ctx` format, the following categories are stripped:

| Strip | Rationale |
|-------|-----------|
| Persuasive prose | LLM doesn't need convincing |
| Navigational scaffolding | LLM reads in parallel, doesn't "scroll" |
| Examples of well-known abstractions | LLM has training data |
| Context re-establishment | LLM holds full window in working memory |
| Filler words and hedging | "Perhaps", "It could be argued that" → delete |
| Transition phrases | "Furthermore", "As mentioned earlier" → delete |
| Repeated information | State once, reference via `@` |

**Preserved unconditionally:**
- Every fact and number
- Every relationship and dependency
- Every constraint and invariant
- Every warning and edge case
- Exact identifiers (names, paths, keys, versions)

---

## 6. References and Linking

### Internal Cross-Reference

Reference another section within the same file:

```
@SECTION-NAME
@SECTION-NAME/SUBSECTION
```

Example:
```
±PACKER
pipeline:raw-corpus→parse→entity-resolution→compress→output
SALIENCE-METHOD:see @SALIENCE-SCORER

±SALIENCE-SCORER
...
```

### External File Reference

Reference another `.ctx` file:

```
@filename.ctx
@filename.ctx#SECTION-NAME
@path/to/file.ctx#SECTION/SUBSECTION
```

### Entity Identity

Declare that two names refer to the same entity:

```
ENTITY-A≡ENTITY-B
CtxPack≡ctxpack
Independent-Researcher≡kapil-pant
```

The `≡` operator (or `===` ASCII fallback) establishes coreference. Once declared, either name may be used interchangeably.

### Namespace Prefixes (Large Packs)

For `.ctxpack/` directories with many files, namespace prefixes reduce verbosity:

```
@DEF data:=data-engineering.L2.ctx
@DEF fin:=financial-services.L2.ctx

data:@CUSTOMER/PII-RULES
fin:@RISK/CAPITAL-REQUIREMENTS
```

**Syntax:** `@DEF prefix:=filename.ctx` declares a namespace. Subsequent references use `prefix:@SECTION`.

Namespace declarations SHOULD appear at the top of the body, immediately after the header.

---

## 7. Multi-Layer File Organization

### `.ctxpack/` Directory Structure

A multi-layer context pack uses a directory with the `.ctxpack/` suffix:

```
project.ctxpack/
  manifest.ctx       # Index: layers, checksums, metadata
  project.L3.ctx     # Always loaded (~500 tok)
  project.L2.ctx     # Loaded for relevant domains (~2-5K tok)
  project.L1.ctx     # Loaded selectively (~10-20K tok)
  # L0 = raw source, referenced by path, not stored in pack
```

**Naming convention:** `{name}.L{n}.ctx` — the layer number is part of the filename.

### Manifest Format

The manifest is a `.ctx` file with layer `MANIFEST`:

```
§CTX v1.0 MANIFEST DOMAIN:project-name
COMPRESSED:2026-02-21
LAYERS:[L3:project.L3.ctx(~500tok),L2:project.L2.ctx(~3000tok),L1:project.L1.ctx(~15000tok)]
L0_SOURCE:./src/
```

**Manifest-specific fields:**

| Field | Purpose |
|-------|---------|
| `LAYERS:[...]` | Ordered list of layer files with approximate sizes |
| `L0_SOURCE:{path}` | Path to raw source material |
| `TOTAL_TOKENS:~{n}` | Combined compressed token count |

The manifest layer keyword is `MANIFEST` (not `L0`-`L3`).

### Single-File Mode

A standalone `.ctx` file without a `.ctxpack/` directory is valid. Single-file mode is the default for:
- Individual domain knowledge packs
- Project architecture summaries
- Compressed conversation context

No manifest is needed. The file's own header provides all metadata.

### File Extension

- `.ctx` — a single-layer context file
- `.ctxpack/` — a directory containing a multi-layer context pack
- `.ctx.prov` — a provenance companion file (see section 9)

---

## 8. Salience, Ordering, and Positioning

### No Numeric Salience Scores

The `.ctx` format does **not** include numeric salience scores. Salience is inherently query-dependent — a section about authentication has high salience for a login bug and low salience for a UI color change. Static scores would be premature and misleading.

### How Salience Is Expressed

Salience is encoded through three structural mechanisms:

1. **Layer assignment:** L3 content is the most universally salient. L1 content is the most specific/least universally salient. Layer assignment is the coarsest salience signal.

2. **Ordering within layer:** Content within each section is ordered by **descending salience** — most important information first. This enables a critical property: **truncation resilience**. If a consumer must cut content to fit a token budget, cutting from the bottom of a section loses the least important content first.

3. **Flags:** `★` marks high-emphasis content. `⚠` marks warnings. These are binary flags that draw attention, not graduated scores.

### The Progressive JPEG Principle

Like a progressive JPEG that renders a blurry-but-complete image first, then sharpens:

- **L3 alone** gives a usable overview (blurry but complete)
- **L3 + relevant L2** gives good working context (sharp for relevant areas)
- **L3 + L2 + relevant L1** gives near-complete context (full detail where needed)
- **L0** provides exact source text on demand

At every level of detail, the context is **complete** (no missing pieces) — just at different resolutions.

### Truncation Convention

When content must be truncated to fit a token budget:

1. Drop sections from the **bottom** of the file first (lowest salience)
2. Within a section, drop items from the **bottom** first
3. Never split a section across a truncation boundary — drop or keep whole sections
4. L3 is never truncated (it's the minimum viable injection)

---

## 9. Provenance

Provenance tracks the origin of compressed content — essential for auditability and for "drilling down" from compressed assertions to source material.

### Layered Provenance Model

Provenance detail scales **inversely** with compression — more compressed content has less inline provenance (because inline provenance would negate the compression benefit).

| Layer | Provenance Level | Mechanism |
|-------|-----------------|-----------|
| L3 | Header only | `SOURCE:` header field |
| L2 | Per-section (optional) | `SRC:path#lines` within sections |
| L1 | Per-paragraph (encouraged) | `SRC:path#lines` after paragraphs |
| L0 | Self-evident | Is the source |

### Inline Provenance Syntax

```
SRC:path/to/file.ext#L10-L50
SRC:git:abc1234:path/file.ext
SRC:https://confluence.example.com/page/12345
```

The `SRC:` key uses standard path/URL notation. Line ranges use `#L{start}-L{end}`.

### Provenance Companion File

For audit-critical domains (healthcare, finance, regulatory), a companion `.ctx.prov` file provides a full mapping from every assertion in the `.ctx` file to its source(s):

```
project.L2.ctx      → the compressed context
project.L2.ctx.prov → full provenance mapping
```

Referenced from the header: `PROVENANCE_MAP:project.L2.ctx.prov`

The `.ctx.prov` format is line-oriented:
```
SECTION:ENTITY-A/RULE-1 → SRC:rules/entity-a.yaml#L15-L30
SECTION:ENTITY-A/RULE-2 → SRC:regulations/reg-123.md#L100-L120+rules/entity-a.yaml#L31-L35
```

---

## 10. Versioning and Diffing

### Canonical Ordering

`.ctx` files SHOULD follow a canonical ordering convention to enable deterministic regeneration and meaningful diffs:

1. Header fields in a consistent order (required fields first, then recommended, then custom)
2. Body sections in a consistent order (defined by the packer, typically by domain or salience)
3. Items within sections in descending salience order

### Generation Counter

The `GEN:{n}` header field tracks how many times a `.ctx` file has been regenerated from source. It increments by 1 each time the packer re-compresses from L0.

```
GEN:1    # First generation
GEN:5    # Fifth regeneration (4 updates since initial pack)
```

### Semantic Diff

A semantic diff compares two `.ctx` files by **entity and assertion**, not by line. This is a tooling operation (not a format feature) defined as:

1. Parse both files into section → key-value → operator structure
2. Match sections by name
3. Within matched sections, compare key-value pairs and assertions
4. Report: added/removed/modified entities, changed relationships, new/removed constraints

Line-level diffs (e.g., `git diff`) remain useful for reviewing changes but semantic diff provides domain-meaningful comparisons.

### Snapshot Model

`.ctx` files are **complete snapshots**, not deltas. Each file is self-contained at its layer. Delta compression is delegated to the version control system (git handles this efficiently for text files).

---

## 11. Encoding

### Character Encoding

- **Primary:** UTF-8 with Unicode operators (`→`, `¬`, `±`, `§`, `★`, `⚠`, `≡`, `⊥`)
- **ASCII fallback:** Every Unicode operator has a defined ASCII equivalent (see section 4)
- **Requirement:** Conformant parsers MUST accept both Unicode and ASCII forms
- **Requirement:** Conformant packers SHOULD produce UTF-8 by default, with an ASCII mode flag

### Tokenizer Considerations

Unicode operators are typically 1-2 tokens each in modern tokenizers (cl100k_base, o200k_base) but replace 3-5 token English phrases:

| Expression | Tokens (English) | Tokens (operator) | Savings |
|------------|------------------|--------------------|---------|
| "implies that" | 2 | 1 (`→`) | 1 token |
| "is not" / "does not" | 2-3 | 1 (`¬`) | 1-2 tokens |
| "is equivalent to" | 3 | 1 (`≡`) | 2 tokens |
| "warning:" | 1-2 | 1 (`⚠`) | 0-1 tokens |
| "conflicts with" | 2 | 1 (`⊥`) | 1 token |

Over a typical L2 file with ~50-100 operator uses, this yields ~100-200 token savings — meaningful at scale.

### Line Endings

- LF (`\n`) is the canonical line ending
- Parsers MUST accept both LF and CRLF (`\r\n`)
- Packers SHOULD produce LF

---

## 12. PEG Grammar

The following PEG grammar defines the machine-parseable subset of the `.ctx` format (Tier 1: scaffolding). It covers header parsing, section markers, key-value pairs, lists, operators, and quoting.

This grammar is also available as a standalone file: `spec/ctx.peg`

```peg
# CTXPACK-SPEC v1.0 PEG Grammar
# Defines the parseable scaffolding (Tier 1) of the .ctx format
# Body content within values (Tier 2) is not formally constrained

# ─── Top-level ───

CTXFile         ← Header BlankLine Body EOF

# ─── Header ───

Header          ← StatusLine (Newline HeaderLine)*
StatusLine      ← Magic SP VersionTag SP LayerTag (SP StatusField)*
Magic           ← '§CTX' / '$CTX'
VersionTag      ← 'v' Digit+ '.' Digit+
LayerTag        ← 'L' [0-3] / 'MANIFEST'
StatusField     ← Key ':' Value

HeaderLine      ← Key ':' Value
Key             ← [A-Za-z_] [A-Za-z0-9_-]*
Value           ← (!Newline .)+

# ─── Body ───

Body            ← (Section / BodyLine)*
Section         ← SectionMarker (Newline BodyLine)*
SectionMarker   ← Indent? SectionSigil SectionName (SP SectionSubtitle)*
SectionSigil    ← '±' / '##'
SectionName     ← [A-Z] [A-Z0-9_-]*
SectionSubtitle ← (!Newline !SectionSigil .)+

BodyLine        ← !SectionMarker !BlankLine Indent? LineContent Newline
LineContent     ← KeyValueLine / OperatorLine / ListLine / QuotedBlock / PlainLine

# ─── Key-Value ───

KeyValueLine    ← Key ':' Value
# Note: first ':' splits key from value; subsequent ':' in value are literal

# ─── Lists ───

ListLine        ← InlineList / NumberedItem
InlineList      ← '[' ListItem (',' ListItem)* ']'
ListItem        ← (!(',' / ']') .)+
NumberedItem    ← Digit+ '.' (!Newline .)+

# ─── Operators ───

OperatorLine    ← (!Newline (Operator / .))+
Operator        ← Arrow / Negation / Conjunction / Disjunction
                 / Sequence / WeakAssoc / Emphasis / Warning
                 / SectionSigil / FormatMagic / CrossRef
                 / Equivalence / Conflict / Uncertainty / Approx

Arrow           ← '→' / '->'
Negation        ← '¬' / '!'
Conjunction     ← '+'
Disjunction     ← '|'
Sequence        ← '>>'
WeakAssoc       ← '~>'
Emphasis        ← '★' / '***'
Warning         ← '⚠' / 'WARN:'
FormatMagic     ← '§' / '$CTX'
CrossRef        ← '@' [A-Za-z_] [A-Za-z0-9_./-]*
Equivalence     ← '≡' / '==='
Conflict        ← '⊥' / 'CONFLICT:'
Uncertainty     ← '?'
Approx          ← '~'

# ─── Quoting ───

QuotedBlock     ← TripleBacktick (!TripleBacktick .)* TripleBacktick
TripleBacktick  ← '```'
InlineQuote     ← '`' (!'`' .)* '`'

# ─── Primitives ───

SP              ← ' '+
Indent          ← '  '+
Newline         ← '\r'? '\n'
BlankLine       ← SP? Newline
Digit           ← [0-9]
EOF             ← !.
```

### Grammar Notes

1. **Two-tier design:** This grammar handles Tier 1 (scaffolding). Content within `Value` productions is Tier 2 — it may contain operators and nested structures, but parsing them is optional for conformance Level 2.

2. **Section nesting:** The grammar recognizes section markers but does not enforce nesting via indentation depth. Nesting is determined by indentation level (each 2-space increment = one nesting level). Tooling MAY infer nesting from indentation.

3. **Ambiguity resolution:** PEG grammars are unambiguous by construction (ordered choice). `KeyValueLine` is tried before `OperatorLine` and `PlainLine`, so a line like `KEY:value→more` is parsed as a key-value pair (with `value→more` as the value), not an operator line.

4. **Cross-references:** The `CrossRef` rule matches `@` followed by an identifier path. It handles `@SECTION`, `@file.ctx`, and `@file.ctx#SECTION`.

---

## 13. Conformance Levels

Three conformance levels enable a spectrum of tooling, from simple file identification to full semantic analysis.

### Level 1 — Minimal

**Requirement:** Valid header (parseable status line with magic, version, layer) + UTF-8 body.

**Capability:** Any tool can identify a `.ctx` file, extract its version and layer, and read metadata.

**Use cases:** File managers, search indexers, syntax highlighters.

### Level 2 — Structural

**Requirement:** Valid header + parseable section markers (`±`) + parseable key-value pairs.

**Capability:** Tools can index sections, extract key-value data, navigate structure, build section-level search indices.

**Use cases:** Context managers, MCP servers, documentation browsers.

### Level 3 — Full

**Requirement:** Validates against the full PEG grammar (section 12), including operator recognition, list parsing, cross-reference resolution, and quoting rules.

**Capability:** Tools can perform semantic diff/merge, operator-aware search, reference graph construction, and full structural validation.

**Use cases:** Packers, unpackers, semantic diff tools, validation suites.

### Conformance Reporting

Tools SHOULD report their conformance level:
```
ctxpack-parser v1.0 (CTXPACK-SPEC v1.0, Level 3)
```

---

## 14. Context Protocol

The Context Protocol defines how `.ctx` content is transmitted to and consumed by LLMs. This is the "decoder" side of the codec — the unpacker's contract with the model.

### Hydration Rules

Hydration is the process of selecting and assembling `.ctx` content for injection into an LLM context window.

| Layer | Hydration Policy | When |
|-------|-----------------|------|
| L3 | **ALWAYS** injected | Every query, unconditionally |
| L2 | **RELEVANT** domains/entities | When query matches domain entities |
| L1 | **SELECTIVE** sections only | When query targets specific active-focus content |
| L0 | **ON-DEMAND** retrieval | Via tool call, not pre-injection |

**Minimum viable injection:** L3 alone. An LLM receiving only L3 must be able to orient itself. L3 is the irreducible minimum.

### Position Optimization (Lost-in-Middle Mitigation)

Research (Liu et al., 2023) shows that LLMs attend disproportionately to content at the **start** and **end** of the context window, with diminished attention to the middle.

The unpacker exploits this by positioning content strategically:

```
┌─────────────────────────────────────────────┐
│ START: High-salience content (★, ⚠, L3)    │  ← High attention
│                                             │
│ MIDDLE: Medium-salience content (L2 detail) │  ← Lower attention
│                                             │
│ END: High-salience content (constraints, ⚠) │  ← High attention
└─────────────────────────────────────────────┘
```

**Position-scoring function:**

```
position_priority(section) = w_layer × layer_score
                           + w_flag × flag_score
                           + w_order × (1 / order_index)

where:
  layer_score = {L3: 1.0, L2: 0.6, L1: 0.3}
  flag_score  = {★: 0.5, ⚠: 0.8, none: 0.0}
  order_index = position within parent section (1-indexed)
  w_layer, w_flag, w_order = tunable weights (default: 0.4, 0.3, 0.3)
```

Sections with the highest `position_priority` are placed at START and END of the assembled context. Remaining sections fill the MIDDLE.

### Chunking Rules

1. **Sections are atomic.** Never split a section across chunk boundaries. A section is the minimum unit of injection.
2. **Budget overflow:** If the assembled context exceeds the token budget, drop the lowest-salience sections (bottom of the file, per ordering convention).
3. **Section minimum:** Each injected section must include its section marker and at least its first key-value pair (the highest-salience content).
4. **L3 is non-droppable.** L3 is always injected in full, regardless of budget constraints.

### MCP Integration Surface

The `.ctx` format integrates with the Model Context Protocol (MCP) through four tool definitions:

#### `ctx/read`

Read a `.ctx` file or specific sections from it.

```json
{
  "name": "ctx/read",
  "description": "Read .ctx file content, optionally filtered by section",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": { "type": "string", "description": "Path to .ctx file" },
      "sections": {
        "type": "array",
        "items": { "type": "string" },
        "description": "Section names to extract (omit for full file)"
      },
      "layer": { "type": "string", "description": "Layer filter for .ctxpack directories" }
    },
    "required": ["path"]
  }
}
```

#### `ctx/hydrate`

Given a query, return optimally assembled context from a `.ctxpack/` directory.

```json
{
  "name": "ctx/hydrate",
  "description": "Query-adaptive context assembly from a .ctxpack",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": { "type": "string", "description": "Path to .ctxpack directory" },
      "query": { "type": "string", "description": "The query/task to hydrate context for" },
      "budget": { "type": "integer", "description": "Maximum tokens to return" }
    },
    "required": ["path", "query"]
  }
}
```

#### `ctx/manifest`

List available layers and their sizes from a `.ctxpack/` directory.

```json
{
  "name": "ctx/manifest",
  "description": "List layers and metadata from a .ctxpack",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": { "type": "string", "description": "Path to .ctxpack directory" }
    },
    "required": ["path"]
  }
}
```

#### `ctx/diff`

Semantic diff between two `.ctx` files.

```json
{
  "name": "ctx/diff",
  "description": "Semantic diff between two .ctx files (entity/assertion level)",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path_a": { "type": "string", "description": "Path to first .ctx file" },
      "path_b": { "type": "string", "description": "Path to second .ctx file" }
    },
    "required": ["path_a", "path_b"]
  }
}
```

### API Injection Format

When injecting `.ctx` content into a system or user message, wrap it in XML tags:

```xml
<ctx domain="project-name" layer="L2" sections="ARCHITECTURE,API">
[.ctx content here]
</ctx>
```

**Rules:**
- The `domain` attribute matches the `DOMAIN:` header field
- The `layer` attribute indicates which layer(s) are included
- The `sections` attribute lists which sections are included (for partial injection)
- Multiple `<ctx>` blocks can be injected in a single message (one per domain/layer combination)
- The XML wrapper enables the LLM to distinguish `.ctx` context from other prompt content

### Query-Adaptive Hydration Pipeline

The full hydration pipeline from query to injected context:

```
1. PARSE QUERY
   → Extract entities (names, concepts, identifiers)
   → Determine operation intent (debug, implement, explain, review)

2. MATCH AGAINST MANIFEST
   → Identify relevant domains from entity overlap
   → Score domain relevance

3. LOAD LAYERS
   → L3: ALWAYS (unconditionally)
   → L2: Score sections by entity overlap with query
   → L1: Score sections by specificity match with query intent
   → L0: Not loaded (available via ctx/read tool call)

4. ASSEMBLE
   → Merge selected sections within token budget
   → Drop lowest-salience sections if over budget

5. POSITION-OPTIMIZE
   → Apply position-scoring function
   → Place high-priority sections at START and END
   → Place remaining sections in MIDDLE

6. INJECT
   → Wrap in <ctx> XML tags
   → Insert into system/user message at appropriate position
```

---

## 15. Examples

### Example 1: Complete L3 (Codebase)

```
§CTX v1.0 L3 DOMAIN:ecommerce-platform
COMPRESSED:2026-02-21
SOURCE_TOKENS:~250000
CTX_TOKENS:~400
SOURCE:git:main:./src/
RATIO:~625x

±SUMMARY
B2C-ecommerce-platform:React+Node.js+PostgreSQL,microservices(12),~50K-MAU

±ENTITIES
SERVICES:[auth,catalog,cart,checkout,payment,shipping,notification,search,analytics,admin,gateway,worker]
DATASTORE:PostgreSQL-15(primary)+Redis-7(cache+sessions)+Elasticsearch-8(search)
GATEWAY:Kong→rate-limiting+auth-forwarding
QUEUE:RabbitMQ(order-events+notifications)

±PATTERNS
ARCH:event-driven-microservices,API-gateway-pattern,CQRS(read/write-split-on-catalog)
AUTH:JWT+refresh-tokens,RBAC(admin|merchant|customer)
DATA:soft-deletes(all-entities),UUID-primary-keys,created_at+updated_at(all-tables)
DEPLOY:Docker+K8s(EKS),GitHub-Actions-CI,blue-green-deploys

±CONSTRAINTS
PII:GDPR-compliant→PII-encrypted-at-rest+right-to-deletion(30-day-SLA)
PAYMENT:PCI-DSS-L1→payment-service-isolated-subnet+no-card-data-in-logs ★
PERF:p99-latency<200ms(gateway),search-results<500ms
API:REST+OpenAPI-3.0,versioned(/v1/,/v2/),no-breaking-changes-without-deprecation-cycle

±WARNINGS
⚠ checkout-service:race-condition-on-concurrent-cart-updates(known,mitigated-by-optimistic-locking,edge-cases-remain)
⚠ search-index:eventual-consistency(~2s-lag)→don't-rely-on-immediate-catalog-updates-in-search
⚠ legacy:payment-service-v1-endpoints-deprecated-but-still-called-by-mobile-app-v3.2
```

### Example 2: Complete L2 (Domain Knowledge)

```
§CTX v1.0 L2 DOMAIN:customer-data-platform
COMPRESSED:2026-02-21
SOURCE_TOKENS:~80000
CTX_TOKENS:~3500
SCOPE:entity-resolution-rules
AUTHOR:data-engineering-team

±ENTITY-CUSTOMER ★GOLDEN-SOURCE:CRM(Salesforce)
IDENTIFIER:customer_id(UUID,immutable)
MATCH-RULES:[
  email:exact-match(case-insensitive,trim-whitespace),
  phone:normalise(E.164-format)→exact-match,
  name+address:fuzzy-match(Jaro-Winkler>0.92)+manual-review-queue
]
PII-CLASSIFICATION:name+email+phone+address→RESTRICTED
RETENTION:active-customers→indefinite|churned→36-months→anonymise
SRC:rules/customer-entity.yaml#L1-L45

±ENTITY-ORDER
IDENTIFIER:order_id(UUID,immutable)
BELONGS-TO:@ENTITY-CUSTOMER(customer_id,mandatory)
STATUS-MACHINE:draft→submitted→processing→shipped→delivered|cancelled|returned
IMMUTABLE-AFTER:submitted(no-edits-to-line-items-after-submission) ★
FINANCIAL-FIELDS:[subtotal,tax,shipping_cost,total]→DECIMAL(19,4)¬FLOAT
SRC:rules/order-entity.yaml#L1-L60

±ENTITY-PRODUCT
IDENTIFIER:sku(string,unique-per-merchant)
CATALOG-STATUS:[active,discontinued,seasonal,pre-order]
PRICE-RULES:merchant-sets-base-price→platform-applies[promotions,bulk-discounts,regional-pricing]
INVENTORY:real-time-sync-from-warehouse-API(webhook+5min-poll-fallback)
⚠ KNOWN-ISSUE:SKU-format-inconsistency-across-merchants→normalisation-pipeline-required

±DATA-QUALITY-RULES
NULL-POLICY:customer_id+order_id→never-null|email→never-null-for-active|phone→nullable
FRESHNESS:customer-data→max-24h-stale|inventory→max-5min-stale|orders→real-time
DEDUP:daily-batch(customer-entity-resolution)+real-time-merge(on-new-registration)
ANOMALY:order-value>$10000→flag-for-review|>$50000→auto-hold+alert

±TRANSFORMATION-RULES
TIMEZONE:all-timestamps-stored-UTC→display-in-customer-locale
CURRENCY:stored-in-original+USD-equivalent(daily-ECB-rate)
ADDRESS:normalise-via-SmartyStreets-API→USPS-format(US)|Royal-Mail(UK)
NAME:no-normalisation(preserve-original-case+diacritics) ★cultural-sensitivity
```

### Example 3: L1 Excerpt

```
§CTX v1.0 L1 DOMAIN:customer-data-platform
COMPRESSED:2026-02-21
SOURCE_TOKENS:~80000
CTX_TOKENS:~12000
SCOPE:full-domain-rules

±ENTITY-CUSTOMER

The customer entity is the central node in the data model. The golden source is Salesforce CRM — all other systems sync from it via the customer-sync service (runs every 15 minutes, full reconciliation nightly at 02:00 UTC).

Customer matching uses a tiered approach: email match is preferred (exact, case-insensitive, whitespace-trimmed). Phone matching requires E.164 normalisation first — the normaliser handles US, UK, and EU formats but has known issues with APAC numbers (SRC:bugs/APAC-phone-normalise.md). Name+address matching uses Jaro-Winkler with a 0.92 threshold — below that, records go to a manual review queue staffed by the data ops team (SLA: 48 hours).
SRC:rules/customer-entity.yaml#L1-L45

PII handling follows GDPR. Fields classified as RESTRICTED (name, email, phone, address) are encrypted at rest using AES-256-GCM with keys rotated quarterly. Access requires the `pii:read` scope in the service JWT. The right-to-deletion pipeline (triggered by customer request via support portal) has a 30-day SLA and cascades to all downstream systems via the `customer.delete` event on RabbitMQ.
SRC:compliance/gdpr-implementation.md#L20-L80
```

### Example 4: Manifest

```
§CTX v1.0 MANIFEST DOMAIN:customer-data-platform
COMPRESSED:2026-02-21
AUTHOR:data-engineering-team
TOTAL_TOKENS:~16000

LAYERS:[L3:cdp.L3.ctx(~450tok),L2:cdp.L2.ctx(~3500tok),L1:cdp.L1.ctx(~12000tok)]
L0_SOURCE:./domain-knowledge/

±INDEX
L3:cdp.L3.ctx HASH:sha256:a1b2c3d4...
L2:cdp.L2.ctx HASH:sha256:e5f6a7b8...
L1:cdp.L1.ctx HASH:sha256:c9d0e1f2...
```

### Example 5: ASCII Fallback

The same L3 snippet from Example 1, in pure ASCII:

```
$CTX v1.0 L3 DOMAIN:ecommerce-platform
COMPRESSED:2026-02-21
SOURCE_TOKENS:~250000
CTX_TOKENS:~400

##SUMMARY
B2C-ecommerce-platform:React+Node.js+PostgreSQL,microservices(12),~50K-MAU

##ENTITIES
SERVICES:[auth,catalog,cart,checkout,payment,shipping,notification,search,analytics,admin,gateway,worker]
DATASTORE:PostgreSQL-15(primary)+Redis-7(cache+sessions)+Elasticsearch-8(search)
GATEWAY:Kong->rate-limiting+auth-forwarding
QUEUE:RabbitMQ(order-events+notifications)

##PATTERNS
ARCH:event-driven-microservices,API-gateway-pattern,CQRS(read/write-split-on-catalog)
AUTH:JWT+refresh-tokens,RBAC(admin|merchant|customer)

##CONSTRAINTS
PII:GDPR-compliant->PII-encrypted-at-rest+right-to-deletion(30-day-SLA)
PAYMENT:PCI-DSS-L1->payment-service-isolated-subnet+no-card-data-in-logs ***
PERF:p99-latency<200ms(gateway),search-results<500ms

##WARNINGS
WARN: checkout-service:race-condition-on-concurrent-cart-updates(known)
WARN: search-index:eventual-consistency(~2s-lag)->don't-rely-on-immediate-catalog-updates-in-search
```

### Example 6: Hydrated Injection

Given the query: *"Fix the race condition in checkout"*

The unpacker assembles:

```xml
<ctx domain="ecommerce-platform" layer="L3" sections="ALL">
§CTX v1.0 L3 DOMAIN:ecommerce-platform
...full L3 content (always injected)...
</ctx>

<ctx domain="ecommerce-platform" layer="L2" sections="CHECKOUT-SERVICE,CART-SERVICE,ORDER-ENTITY">
±CHECKOUT-SERVICE
...relevant L2 sections about checkout...

±CART-SERVICE
...relevant L2 sections about cart (related entity)...

±ORDER-ENTITY
...order processing rules (related entity)...
</ctx>
```

The query entity "checkout" matched `CHECKOUT-SERVICE` directly. The unpacker also pulled `CART-SERVICE` (the warning mentions "concurrent cart updates") and `ORDER-ENTITY` (checkout creates orders). L1 sections were not needed — the L2 detail is sufficient for a bug fix.

---

## 16. Design Rationale Appendix

This appendix documents the theoretical basis for each major design decision in the `.ctx` format. Each entry follows a consistent structure: **decision → rationale → theoretical grounding**. These entries bridge the spec and the planned arXiv whitepaper — the whitepaper can expand each into a full section with proofs and benchmarks.

### Why Multi-Resolution Layers

**Decision:** Four discrete layers (L0-L3) rather than a continuous compression spectrum.

**Rationale:** Continuous compression would require per-query recompression. Discrete layers enable pre-computation — pack once, hydrate adaptively. Four layers balance granularity against storage/maintenance cost.

**Theoretical grounding:** Information Bottleneck (Tishby, 1999). The IB objective `L[p(t|x)] = I(X;T) - β·I(T;Y)` has phase transitions at specific β values — the representation undergoes qualitative changes at these critical points. The four layers correspond to four regimes of the β parameter: L0 (β=0, no compression), L1 (low β, mild compression), L2 (medium β, structural compression), L3 (high β, maximum compression with key information preserved).

### Why Descending-Salience Ordering

**Decision:** Content within sections ordered most-important-first.

**Rationale:** Enables truncation resilience — cutting from the bottom always removes the least important content. This is the "progressive JPEG" property: partial content is always the best possible partial content.

**Theoretical grounding:** Rate-Distortion theory (Shannon, 1959). The R(D) curve is convex and monotonically decreasing — the first K tokens of an optimally-ordered representation capture disproportionately more information than the next K tokens. Descending-salience ordering approximates the optimal rate-distortion encoding order.

### Why This Specific Operator Alphabet

**Decision:** A small, fixed set of 18 operators drawn from formal logic, programming, and mathematics.

**Rationale:** LLMs have strong, well-calibrated semantic priors for symbols encountered frequently in training data. Using these symbols activates precise semantic representations with higher confidence than novel notation would.

**Theoretical grounding:** LLM training distribution analysis. Symbols like `→` (type theory, Haskell, logic), `¬` (formal logic), `|` (BNF, shell pipes) appear in millions of training documents with consistent semantics. An LLM's internal representation of `→` has lower entropy (higher confidence) than for arbitrary invented notation. The alphabet was selected by cross-referencing symbol frequency in code/math corpora with semantic consistency.

### Why Progressive Disclosure / Truncation Resilience

**Decision:** Each layer is self-contained and usable alone; higher compression layers contain the most essential information.

**Rationale:** Context budgets vary unpredictably (model limits, multi-turn conversations, tool results). The format must degrade gracefully.

**Theoretical grounding:** Renormalisation Group (Wilson, 1982; Mehta & Schwab, 2014). In physics, the RG block-spin transform coarsens a system while preserving essential behavior. The mapping: tokens→lattice sites, dependencies→spin interactions, compression→block transform, patterns surviving all compression→fixed points→L3 content. L3 content is analogous to RG fixed points: the information that is invariant under all levels of compression.

### Why Position Optimization

**Decision:** The unpacker places high-salience content at the start and end of the assembled context.

**Rationale:** Empirical evidence (Liu et al., 2023, "Lost in the Middle") shows LLMs attend less to content in the middle of long contexts. Position optimization mitigates this without modifying the model.

**Theoretical grounding:** Attention-as-Kernel-Density estimation (Tsai, 2019). Attention weights `Attn(q,K) = Σ κ(q,kⱼ)·vⱼ / Σ κ(q,kⱼ)` form a kernel density estimate. Positional encoding creates a position-dependent bias in the kernel — tokens at boundary positions receive higher base attention. Pre-computable attention approximation allows the unpacker to estimate which positions yield highest attention weight, placing the most important content there.

### Why Expert-to-Expert Register

**Decision:** `.ctx` content is written in compressed, jargon-dense expert notation rather than explanatory prose.

**Rationale:** The "reader" is an LLM with billions of parameters trained on the entire internet. It has the vocabulary of every domain expert simultaneously. Explanatory prose wastes tokens explaining things the LLM already knows from training.

**Theoretical grounding:** Clinical shorthand analogy. Physicians write "pt c/o SOB, r/o PE, CTA ordered" — 10 words that expand to a paragraph of explanation. This works because both writer and reader share a vast professional vocabulary. LLMs share an even vaster vocabulary — the `.ctx` register exploits this shared knowledge base to achieve compression ratios impossible with pedagogical text.

### Why PEG Not BNF

**Decision:** The formal grammar uses Parsing Expression Grammar (PEG), not Backus-Naur Form (BNF) or Extended BNF.

**Rationale:** PEG grammars are unambiguous by construction (ordered choice operator). A PEG always produces exactly one parse tree for any input. BNF grammars can be ambiguous, requiring disambiguation rules outside the grammar itself.

**Theoretical grounding:** PEG (Ford, 2004) provides a direct mapping from grammar to parser (packrat parsing). Every PEG grammar is a specification AND an implementation — there is no gap between "what the grammar says" and "what the parser does". This eliminates an entire class of spec-vs-implementation bugs.

### Why Backtick Quoting Not Backslash Escaping

**Decision:** Inline literals use backtick quoting (`` `content` ``), not backslash escaping (`\:`).

**Rationale:** LLMs encounter backtick quoting in millions of Markdown documents in training. The semantic association "backtick = treat as literal/code" is deeply ingrained. Backslash escaping is less consistently handled by LLMs and creates ambiguity with file paths on Windows.

**Theoretical grounding:** Markdown is one of the highest-frequency text formats in LLM training corpora. Leveraging established Markdown conventions means the LLM's existing weights handle `.ctx` quoting correctly without any fine-tuning — a form of transfer learning at the format level.

### Why No Inline Salience Scores

**Decision:** The format does not support numeric salience annotations like `[salience:0.85]`.

**Rationale:** Salience is fundamentally query-dependent. A section about database indexing has high salience for a performance query and near-zero salience for a UI query. Any static score baked into the file would be wrong for most queries.

**Theoretical grounding:** Information Bottleneck relevance term `I(T;Y)` depends on the target variable Y — which changes per query. Static salience scores assume a fixed Y, which is a category error. Instead, salience is expressed through structural mechanisms (layer assignment = coarse, ordering = fine, flags = binary) that are query-independent and composed with query-dependent scoring at hydration time.

---

## Appendix A: Backward Compatibility with `ctx_mod.ctx`

The reference file `ctx_mod.ctx` was written before this formal specification. The following documents its compatibility:

### Valid Under Spec
- Status line: `§CTX v1.0 L2 DOMAIN:ai-infrastructure SCOPE:ctxpack-concept-development AUTHOR:kapil-pant(Independent-Researcher)` — valid (multiple KEY:value fields on status line)
- `COMPRESSED:2026-02-21` — valid required field
- `SOURCE_TOKENS:~40000` — valid required field
- `TURNS:10` — valid recommended field
- All `±SECTION` markers — valid
- All operators (`→`, `¬`, `+`, `|`, `★`, `⚠`, `≡`) — valid per alphabet
- Hyphenated compounds — valid per notation rules
- Inline lists with `[]` — valid
- Key-value pairs — valid
- Nesting via 2-space indentation — valid

### Pre-Spec Conventions (Documented, Not Deviant)
- `TURNS:10` on header line 2 alongside `COMPRESSED:` — multiple fields per line. The spec allows this: header lines may contain multiple space-separated `KEY:value` pairs following the same pattern as the status line.
- `±SALIENCE_SCORER ★HEART-OF-SYSTEM` — section name uses underscore (`_`). The PEG grammar `SectionName ← [A-Z] [A-Z0-9_-]*` explicitly allows underscores for backward compatibility with this convention. However, new content SHOULD prefer hyphens.
- Mathematical notation (e.g., `ℒ[p(t|x)]`, `Σwⱼ·Sⱼ`, `κ(q,kⱼ)`) within values — valid as Tier 2 body content (not parsed by the PEG grammar, interpreted by LLM).
- Inline quoted strings with `"..."` — valid as Tier 2 content. The spec's backtick quoting is for cases where content might be confused with operators; double-quote strings are passthrough.

### Verdict

`ctx_mod.ctx` is **fully conformant** with CTXPACK-SPEC v1.0 at Level 2 (Structural). The minor conventions documented above informed the spec's design — the spec was made compatible with the reference file, not the other way around.

---

## Appendix B: Reference Implementation Checklist

A conformant implementation should handle the following test cases:

- [ ] Parse status line with 3+ fields (magic, version, layer, optional extras)
- [ ] Parse header key-value pairs with colons in values
- [ ] Identify blank line as header/body separator
- [ ] Recognize `±` and `##` as section markers
- [ ] Parse nested sections via indentation
- [ ] Extract key-value pairs from body
- [ ] Recognize all 18 operators (Unicode and ASCII forms)
- [ ] Handle backtick-quoted inline literals
- [ ] Handle triple-backtick fenced blocks
- [ ] Resolve `@` cross-references (internal and external)
- [ ] Parse inline lists `[a,b,c]`
- [ ] Preserve unknown header fields
- [ ] Accept both LF and CRLF line endings
- [ ] Validate L3 required slots (ENTITIES, PATTERNS, CONSTRAINTS, WARNINGS)

---

*End of CTXPACK-SPEC v1.0*
