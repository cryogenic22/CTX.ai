# Market-Zero Constraints and Design Rules

## Data Integrity

- No fabricated data anywhere in the system. Every data point displayed to users traces back to verifiable external sources with complete provenance.
- Every database row carries source_api, source_url, and retrieved_at fields.
- Content deduplication uses SHA-256 hash of canonical payload (excludes embeddings and timestamps).

## Risk Engine Rules

- The risk scoring engine is purely deterministic and rule-based. No ML or LLM is used in score computation.
- Risk score is sum of triggered factor weights, capped at 10.0.
- Severity thresholds: Green 0-4, Yellow 4-7, Red 7-10.
- LLM critique is generated ONLY when score exceeds 7.0, and is grounded in source data only.
- MarketSnapshot is assembled at query time from live database state. Scores are never pre-computed or cached.

## Entity Resolution Thresholds

- Auto-create confidence: 0.95 or above (only for trusted sources: ClinicalTrials.gov, FDA Orange Book, PubMed, FDA Shortages)
- Review queue: 0.85 to 0.95 confidence (goes to unresolved_entities for admin review)
- Reject: below 0.85 confidence
- Fuzzy matching uses normalized company and drug names with skip lists for common terms

## Data Freshness

- Staleness amber threshold: 48 hours without update
- Staleness red threshold: 7 days without update
- ETL runs tracked in etl_runs table with status, record counts, and error messages

## System Boundaries

- Market-Zero is NOT a real-time streaming system. It processes batch ETL from public APIs on scheduled intervals.
- Market-Zero does NOT perform drug discovery or molecular simulation. It evaluates launch strategies.
- Market-Zero does NOT provide medical advice. It is a competitive intelligence tool for strategy analysts.
- The risk engine does NOT use machine learning. All 8 risk factors use deterministic rule evaluation.
- There is NO blockchain or distributed ledger in the architecture.

## Technology Constraints

- Backend: Python 3.11+, FastAPI, LangGraph
- Database: PostgreSQL 16 with pgvector extension
- Embeddings: OpenAI text-embedding-3-small (1536 dimensions)
- LLM: OpenAI GPT-4o for critiques and agent responses
- Frontend: React 18 with TypeScript, Vite, Tailwind CSS
- Deployment: Docker Compose

## Licensing

- Market-Zero is proprietary software (not open source)
