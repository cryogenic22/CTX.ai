"""Agent session — rolling state management with token budget enforcement.

Provides incremental merge, snapshot, and eviction for long-running agent
conversations that continuously accumulate context.

Usage:
    session = AgentSession(domain="my-agent", token_budget=4000)
    session.update({"entities": [{"name": "USER", "email": "a@b.com"}]})
    session.update({"tool": "search", "result": {"count": 42}})
    result = session.snapshot()
    print(result.ctx_text)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.packer.compressor import compress, count_tokens
from ..core.packer.conflict import detect_conflicts
from ..core.packer.entity_resolver import resolve_entities
from ..core.packer.ir import IRCorpus, IREntity, IRField
from ..core.serializer import serialize
from . import AgentCompressResult
from .state_parser import parse_steps


@dataclass
class AgentSession:
    """Incremental agent state with token budget enforcement.

    Maintains a running IRCorpus that accumulates entities across
    multiple ``update()`` calls. Periodically compresses on ``snapshot()``.

    Args:
        domain: Domain label for the .ctx header.
        token_budget: Maximum compressed tokens before eviction triggers.
        strict: Suppress inferred fields.
    """

    domain: str = "agent-state"
    token_budget: int = 4000
    strict: bool = False

    # Internal state
    _corpus: IRCorpus = field(default_factory=IRCorpus)
    _step_count: int = 0
    _total_source_tokens: int = 0
    _initialized: bool = False

    def __post_init__(self) -> None:
        if not self._initialized:
            self._corpus = IRCorpus(domain=self.domain)
            self._initialized = True

    def update(self, step: dict[str, Any]) -> AgentCompressResult:
        """Incrementally merge a new step into the session state.

        The step is parsed into IR entities and merged with existing state
        via entity resolution (dedup + field merge). If the resulting
        compressed output exceeds ``token_budget``, eviction is triggered.

        Args:
            step: A single agent step dict (same formats as compress_state).

        Returns:
            AgentCompressResult reflecting the current post-merge state.
        """
        # Parse the new step into a temporary corpus
        new_corpus = parse_steps([step], domain=self.domain)
        self._step_count += 1
        self._total_source_tokens += new_corpus.source_token_count

        # Merge new entities into the running corpus
        for entity in new_corpus.entities:
            self._corpus.entities.append(entity)
        for rule in new_corpus.standalone_rules:
            self._corpus.standalone_rules.append(rule)

        # Update source tracking
        self._corpus.source_token_count = self._total_source_tokens
        self._corpus.source_files = [
            f"step-{i}" for i in range(self._step_count)
        ]

        # Re-resolve entities (merge duplicates)
        resolve_entities(self._corpus)

        # Check if eviction is needed
        result = self._compress_current()
        if result.tokens_compressed > self.token_budget:
            self.evict("lowest-salience")
            result = self._compress_current()

        return result

    def snapshot(self) -> AgentCompressResult:
        """Return the current compressed state without modifying it.

        Returns:
            AgentCompressResult reflecting the current state.
        """
        return self._compress_current()

    def evict(self, strategy: str = "lowest-salience") -> int:
        """Remove lowest-salience entities to fit within token budget.

        Args:
            strategy: Eviction strategy. Currently supports:
                - "lowest-salience": Remove entities with lowest salience first.
                - "oldest": Remove entities from earliest steps first.

        Returns:
            Number of entities evicted.
        """
        if not self._corpus.entities:
            return 0

        evicted = 0

        if strategy == "oldest":
            # Sort by source line (step index) — oldest first
            self._corpus.entities.sort(
                key=lambda e: (
                    e.sources[0].line_start if e.sources else 0
                ),
            )
        else:
            # Default: lowest-salience first
            self._corpus.entities.sort(key=lambda e: e.salience)

        # Remove entities one at a time until within budget
        while self._corpus.entities:
            trial = self._compress_current()
            if trial.tokens_compressed <= self.token_budget:
                break
            self._corpus.entities.pop(0)
            evicted += 1

        return evicted

    @property
    def entity_count(self) -> int:
        """Number of entities currently in the session."""
        return len(self._corpus.entities)

    @property
    def step_count(self) -> int:
        """Total number of steps ingested."""
        return self._step_count

    def _compress_current(self) -> AgentCompressResult:
        """Compress the current corpus state into a result."""
        # Work on a copy to avoid mutation by conflict detection
        corpus_copy = IRCorpus(
            domain=self._corpus.domain,
            scope=self._corpus.scope,
            author=self._corpus.author,
            entities=list(self._corpus.entities),
            standalone_rules=list(self._corpus.standalone_rules),
            warnings=[],
            source_token_count=self._corpus.source_token_count,
            source_files=list(self._corpus.source_files),
        )

        conflicts = detect_conflicts(corpus_copy)
        corpus_copy.warnings.extend(conflicts)

        doc = compress(corpus_copy, strict=self.strict)
        ctx_text = serialize(doc)
        tokens_compressed = count_tokens(doc.body)

        ratio = (
            self._total_source_tokens / tokens_compressed
            if tokens_compressed > 0
            else 0.0
        )

        return AgentCompressResult(
            ctx_text=ctx_text,
            document=doc,
            tokens_raw=self._total_source_tokens,
            tokens_compressed=tokens_compressed,
            compression_ratio=ratio,
            entities_merged=0,
            conflicts_detected=len(conflicts),
            warnings=[w.message for w in corpus_copy.warnings],
            step_count=self._step_count,
        )
