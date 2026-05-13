"""High-level code packer — end-to-end pipeline + MCP-shaped helpers.

The Pack object is the integration layer everything below feeds into:

    parse_python -> extract_symbols -> emit_irentities
                                    -> build_call_graph + resolve_callees
                                    -> compute_pagerank
                                    -> populate_centrality_prior

…and exposes the MCP tool surface as plain Python functions:

    pack_codebase(root)        -> Pack
    list_symbols(pack, ...)    -> dict (CP-026)
    hydrate_symbol(pack, ...)  -> dict (CP-027)
    search_symbols(pack, ...)  -> dict (CP-028)
    raw_file(pack, path)       -> dict (CP-029)
    render_manifest(pack, ...) -> dict (CP-030)
    pack_version(pack)         -> str  (CP-030.5)

Errors are returned as structured dicts (see ``docs/mcp-error-contract.md``)
rather than raised, so the MCP server wraps them directly into tool
responses.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from ctxpack.core.code.callgraph import (
    CallEdge,
    build_call_graph,
    resolve_callees,
)
from ctxpack.core.code.catalog import render_catalog_row
from ctxpack.core.code.emitter import emit_irentities
from ctxpack.core.code.exclusion import iter_python_files, load_exclusion_rules, is_excluded
from ctxpack.core.code.parser import ParseWarning, parse_python
from ctxpack.core.code.parser_tsx import parse_tsx
from ctxpack.core.code.task_scorer import (
    combined_scores,
    compute_task_scores,
)
from ctxpack.core.code.tsx import build_call_graph_tsx
from ctxpack.core.code.ranker import (
    compute_pagerank,
    populate_centrality_prior,
)
from ctxpack.core.code.tokens import count_bpe
from ctxpack.core.packer.ir import IREntity

PathLike = Union[str, Path]


# ── Pack object ─────────────────────────────────────────────────────────


@dataclass
class FileWarning:
    """A non-fatal issue from one source file."""

    file: str
    message: str
    line_start: int = 0
    line_end: int = 0


@dataclass
class Pack:
    """A packed codebase ready for hydrate/list queries."""

    root: str
    entities: list[IREntity]
    edges: list[CallEdge]
    scores: dict[str, float]
    files: list[str]
    warnings: list[FileWarning] = field(default_factory=list)
    version: str = ""
    # CP-024 — per-file content hash for incremental re-packs.
    file_hashes: dict[str, str] = field(default_factory=dict)

    @property
    def by_name(self) -> dict[str, IREntity]:
        """Cached lookup: qualified name → entity."""
        if not hasattr(self, "_by_name"):
            object.__setattr__(self, "_by_name", {e.name: e for e in self.entities})
        return self._by_name  # type: ignore[attr-defined]


# ── Top-level pack pipeline ─────────────────────────────────────────────


def pack_codebase(
    root: PathLike,
    *,
    include_body: bool = True,
    prior: Optional["Pack"] = None,
) -> Pack:
    """Pack a Python + TSX codebase into a :class:`Pack`.

    Steps (deterministic):
      1. Walk the tree, applying gitignore + ctxpackignore + heuristics.
      2. For each surviving file, compare its SHA-256 against
         ``prior.file_hashes`` (if a prior pack is supplied) — unchanged
         files reuse the prior pack's entities and edges (CP-024).
      3. Parse new/modified files, emit IREntity per symbol, build the
         call graph.
      4. Run PageRank over the merged graph; populate centrality_prior.
      5. Compute the content-hash pack_version.

    Pass ``prior=<last pack>`` to skip re-parsing unchanged files —
    typically reduces re-pack time from seconds to milliseconds on
    edits.
    """
    root_path = Path(root).resolve()
    # Walk for .py + .tsx + .ts; apply same exclusion rules.
    rules = load_exclusion_rules(root_path)
    files: list[Path] = []
    for pattern in ("*.py", "*.tsx", "*.ts"):
        for p in sorted(root_path.rglob(pattern)):
            if not is_excluded(p, root=root_path, rules=rules):
                files.append(p)

    # Pre-bucket prior entities + edges by file for fast reuse lookup.
    prior_entities_by_file: dict[str, list[IREntity]] = {}
    prior_edges_by_file: dict[str, list[CallEdge]] = {}
    if prior is not None:
        for e in prior.entities:
            file_key = e.sources[0].file if e.sources else ""
            prior_entities_by_file.setdefault(file_key, []).append(e)
        for ce in prior.edges:
            file_key = ce.caller.split("::", 1)[0] if "::" in ce.caller else ""
            prior_edges_by_file.setdefault(file_key, []).append(ce)

    all_entities: list[IREntity] = []
    all_edges: list[CallEdge] = []
    warnings: list[FileWarning] = []
    relative_files: list[str] = []
    file_hashes: dict[str, str] = {}
    reused_count = 0
    for f in files:
        rel = str(f.relative_to(root_path)).replace("\\", "/")
        relative_files.append(rel)
        cur_sha = _file_sha(f)
        file_hashes[rel] = cur_sha

        if prior is not None and prior.file_hashes.get(rel) == cur_sha:
            # Reuse entities and edges from the prior pack.
            #
            # Note: entity refs are SHARED with the prior pack.
            # populate_centrality_prior runs in-place at the end of
            # this pass, which mutates the prior pack's entities too.
            # That's acceptable because (a) on no-change input scores
            # are identical so the mutation is a no-op, (b) the prior
            # pack is by convention discarded once the new one returns.
            # Deep-copying was ~7x slower on CTX_mod and not worth it.
            all_entities.extend(prior_entities_by_file.get(rel, []))
            all_edges.extend(prior_edges_by_file.get(rel, []))
            reused_count += 1
            continue

        language = "tsx" if f.suffix in (".tsx", ".ts") else "python"
        parse_fn = parse_tsx if language == "tsx" else parse_python
        try:
            result = parse_fn(f)
        except Exception as e:
            warnings.append(
                FileWarning(file=rel, message=f"{type(e).__name__}: {e}")
            )
            continue
        for pw in result.warnings:
            warnings.append(
                FileWarning(
                    file=rel,
                    message=pw.message,
                    line_start=pw.line_start,
                    line_end=pw.line_end,
                )
            )
        all_entities.extend(
            emit_irentities(
                result, rel,
                include_body=include_body,
                language=language,
            )
        )
        if language == "tsx":
            all_edges.extend(build_call_graph_tsx(result, rel))
        else:
            all_edges.extend(build_call_graph(result, rel))

    # Resolve callees to qualified names and run PageRank.
    node_names = {e.name for e in all_entities}
    resolved = resolve_callees(all_edges, node_names)
    scores = compute_pagerank(
        node_names,
        resolved,
        test_node_predicate=lambda n: "tests/" in n or n.startswith("tests/"),
    )
    populate_centrality_prior(all_entities, scores)

    pack = Pack(
        root=str(root_path).replace("\\", "/"),
        entities=all_entities,
        edges=resolved,
        scores=scores,
        files=relative_files,
        warnings=warnings,
        file_hashes=file_hashes,
    )
    pack.version = _compute_version(pack)
    return pack


def _file_sha(path: Path) -> str:
    """SHA-256 of file contents — short hex, ASCII-safe key for the
    ``file_hashes`` map.
    """
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _compute_version(pack: Pack) -> str:
    """SHA-256 over a canonical serialisation of the entities + scores.

    Determinism: entities are written in their current order; fields
    likewise. PageRank produces consistent values (deterministic
    tie-break in compute_pagerank).
    """
    h = hashlib.sha256()
    for e in pack.entities:
        h.update(e.name.encode("utf-8"))
        for f in e.fields:
            h.update(b"|")
            h.update(f.key.encode("utf-8"))
            h.update(b"=")
            h.update(f.value.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


# ── MCP-shaped helpers ─────────────────────────────────────────────────


def pack_version(pack: Pack) -> dict:
    """CP-030.5 — cheap version probe.

    Returns ``{"pack_version": <sha256>}`` plus a few counts for
    sanity. Always succeeds (no pack_not_loaded — caller has the Pack
    in hand by construction).
    """
    return {
        "pack_version": pack.version,
        "entities": len(pack.entities),
        "files": len(pack.files),
        "edges": len(pack.edges),
    }


def list_symbols(
    pack: Pack,
    module: str,
    *,
    k: int = 50,
    context: Optional[str] = None,
    alpha: float = 0.7,
) -> dict:
    """CP-026 — top-k symbols in ``module``, ranked by
    ``α · task_score + (1 − α) · centrality_prior``.

    ``context`` is the agent's working-set hint (recent message
    history, task description). When provided, BM25 task scores are
    rank-normalised and combined with centrality_prior; without it,
    the function falls back to pure centrality (cold-start case).
    """
    if k <= 0:
        return _err("invalid_input", "k must be > 0")
    normalised_module = module.replace("\\", "/")
    if normalised_module not in pack.files:
        return _err(
            "unknown_module",
            f"Module {module!r} not in pack",
            hint=(
                "Use ctx/code_pack manifest to list known files; or check the "
                "path is relative to the pack root."
            ),
        )
    module_ents = [
        e for e in pack.entities
        if e.name.startswith(f"{normalised_module}::")
    ]
    rank_map = _rank_for_subset(
        pack, module_ents, context=context, alpha=alpha
    )
    rows: list[dict] = []
    for ent in module_ents:
        score = rank_map.get(ent.name, 0.0)
        rows.append({
            "name": ent.name,
            "row": render_catalog_row(ent),
            "score": score,
        })
    rows.sort(key=lambda r: (-r["score"], r["name"]))
    rows = rows[:k]
    return {
        "module": normalised_module,
        "symbols": rows,
        "alpha": alpha if context else 0.0,
        "pack_version": pack.version,
    }


def _rank_for_subset(
    pack: Pack,
    subset: list[IREntity],
    *,
    context: Optional[str],
    alpha: float,
) -> dict[str, float]:
    """Compute the combined per-turn ranking for a subset of entities."""
    centrality = {e.name: pack.scores.get(e.name, 0.0) for e in subset}
    if context:
        task = compute_task_scores(subset, context)
        return combined_scores(
            task_scores=task,
            centrality_scores=centrality,
            alpha=alpha,
        )
    return combined_scores(
        task_scores={},
        centrality_scores=centrality,
        alpha=0.0,
    )


def hydrate_symbol(
    pack: Pack,
    name: str,
    *,
    depth: int = 0,
) -> dict:
    """CP-027 — return a symbol's full IRField content.

    depth=0: signature/docstring/body/decorators/etc. for `name`.
    depth=1: also include neighbour bodies (callers/callees from
    the call graph), greedy-packed to a 4K BPE budget.
    """
    if depth not in (0, 1):
        return _err("invalid_input", "depth must be 0 or 1")
    ent = pack.by_name.get(name)
    if ent is None:
        return _err(
            "unknown_symbol",
            f"Symbol {name!r} not in pack",
            hint=(
                "Call ctx/code_list_symbols(module) or "
                "ctx/code_search_symbols(query) to find the right name."
            ),
        )
    payload = {
        "name": ent.name,
        "fields": {f.key: f.value for f in ent.fields},
        "sources": [
            {"file": s.file, "line_start": s.line_start, "line_end": s.line_end}
            for s in ent.sources
        ],
        "layer": ent.layer.value,
        "confidence": ent.confidence,
        "pack_version": pack.version,
    }
    if depth == 1:
        payload["neighbours"] = _depth1_neighbours(pack, ent)
    return payload


def _depth1_neighbours(pack: Pack, ent: IREntity) -> dict:
    """Greedy-pack callers + callees up to 4K BPE total, ordered by
    centrality (highest first), so high-signal neighbours win when the
    budget is tight.
    """
    callees = [e.callee for e in pack.edges if e.caller == ent.name]
    callers = [e.caller for e in pack.edges if e.callee == ent.name]
    candidates = []
    for n in callees:
        candidates.append(("callee", n))
    for n in callers:
        candidates.append(("caller", n))
    # Rank by centrality (high first).
    candidates.sort(key=lambda x: -pack.scores.get(x[1], 0.0))
    budget = 4_000
    used = 0
    callers_out: list[dict] = []
    callees_out: list[dict] = []
    seen: set[str] = set()
    for role, n in candidates:
        if n in seen:
            continue
        seen.add(n)
        neighbour = pack.by_name.get(n)
        if neighbour is None:
            continue
        body = next(
            (f.value for f in neighbour.fields if f.key == "body"),
            "",
        )
        cost = count_bpe(body)
        if cost == 0:
            continue
        if used + cost > budget:
            break
        used += cost
        item = {"name": n, "body": body}
        (callees_out if role == "callee" else callers_out).append(item)
    return {
        "callers": callers_out,
        "callees": callees_out,
        "bpe_used": used,
        "bpe_budget": budget,
    }


def search_symbols(
    pack: Pack,
    query: str,
    *,
    k: int = 10,
    alpha: float = 0.7,
) -> dict:
    """CP-028 — BM25 search over the catalog, blended with centrality.

    The query is treated as the working-set context. BM25 task scores
    are rank-normalised; centrality_prior is rank-normalised; the
    final ranking is the α-weighted combination (CP-021/22/23).
    """
    q = query.strip()
    if not q:
        return _err("invalid_input", "query must not be empty")
    if k <= 0:
        return _err("invalid_input", "k must be > 0")

    task = compute_task_scores(pack.entities, q)
    # Hide entities that scored nothing — BM25 is intentionally sparse.
    candidate_ents = [e for e in pack.entities if task.get(e.name, 0.0) > 0]
    if not candidate_ents:
        return {
            "query": query,
            "symbols": [],
            "alpha": alpha,
            "pack_version": pack.version,
        }
    centrality = {e.name: pack.scores.get(e.name, 0.0) for e in candidate_ents}
    filtered_task = {e.name: task[e.name] for e in candidate_ents}
    combined = combined_scores(
        task_scores=filtered_task,
        centrality_scores=centrality,
        alpha=alpha,
    )
    ents_by_name = {e.name: e for e in candidate_ents}
    ranked = sorted(combined.items(), key=lambda kv: (-kv[1], kv[0]))
    out: list[dict] = []
    for name, score in ranked[:k]:
        e = ents_by_name[name]
        out.append({
            "name": name,
            "row": render_catalog_row(e),
            "score": score,
        })
    return {
        "query": query,
        "symbols": out,
        "alpha": alpha,
        "pack_version": pack.version,
    }


def raw_file(pack: Pack, path: str) -> dict:
    """CP-029 — escape hatch returning raw file bytes."""
    if ".." in Path(path).parts:
        return _err("path_outside_root", "Path contains '..' segments")
    abs_path = Path(pack.root) / path
    try:
        rel = abs_path.resolve().relative_to(Path(pack.root).resolve())
    except ValueError:
        return _err("path_outside_root", f"{path!r} resolves outside pack root")
    rel_str = str(rel).replace("\\", "/")
    if rel_str not in pack.files:
        # Either ignored (heuristic / .gitignore / .ctxpackignore) or
        # genuinely missing.
        return _err(
            "ignored_path" if abs_path.exists() else "unknown_module",
            f"{path!r} is not in the pack" + (
                " (excluded by ignore rules)"
                if abs_path.exists() else " (file does not exist)"
            ),
        )
    try:
        content = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return _err("invalid_input", f"read failed: {e}")
    return {
        "path": rel_str,
        "content": content,
        "bytes": len(content.encode("utf-8")),
        "pack_version": pack.version,
    }


def render_manifest(
    pack: Pack,
    *,
    served_symbol_count: Optional[int] = None,
) -> dict:
    """CP-030 — pack manifest for inclusion in MCP responses.

    Aggregates what was served vs. excluded. Counts of excluded
    categories come from the pack itself (file warnings); per-call
    served counts are passed in.
    """
    return {
        "pack_version": pack.version,
        "served": {
            "entities": len(pack.entities)
            if served_symbol_count is None
            else served_symbol_count,
            "files": len(pack.files),
        },
        "excluded": {
            "parse_warnings": len(pack.warnings),
        },
        "caveats": [
            "Call graph is best-effort static; dynamic dispatch is invisible.",
            "centrality_prior is global PageRank; per-turn ranking (BM25 task score) not yet wired.",
        ],
        "escape_hatch": "ctx/code_raw_file(path)",
    }


# ── Helpers ────────────────────────────────────────────────────────────


def _err(code: str, message: str, *, hint: str = "") -> dict:
    """Render the structured error envelope from the contract."""
    out: dict = {"error": {"code": code, "message": message}}
    if hint:
        out["error"]["hint"] = hint
    return out
