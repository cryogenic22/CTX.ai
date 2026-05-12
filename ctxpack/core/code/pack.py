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
from ctxpack.core.code.exclusion import iter_python_files
from ctxpack.core.code.parser import ParseWarning, parse_python
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
) -> Pack:
    """Pack a Python codebase into a :class:`Pack`.

    Steps (deterministic):
      1. Walk the tree, applying gitignore + ctxpackignore + heuristics.
      2. Parse every surviving ``.py`` file.
      3. Emit IREntity per symbol.
      4. Build the call graph; resolve callees to qualified names.
      5. PageRank over the resolved graph.
      6. Populate centrality_prior on entities.
      7. Compute the content-hash pack_version.

    Files that fail to parse are skipped with a warning; the pack still
    returns successfully for the rest.
    """
    root_path = Path(root).resolve()
    files = list(iter_python_files(root_path))
    all_entities: list[IREntity] = []
    all_edges: list[CallEdge] = []
    warnings: list[FileWarning] = []
    relative_files: list[str] = []
    for f in files:
        rel = str(f.relative_to(root_path)).replace("\\", "/")
        relative_files.append(rel)
        try:
            result = parse_python(f)
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
            emit_irentities(result, rel, include_body=include_body)
        )
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
    )
    pack.version = _compute_version(pack)
    return pack


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
) -> dict:
    """CP-026 — top-k symbols in ``module``, ranked by centrality_prior.

    ``module`` is matched against the relative-path prefix of entity
    names. ``context`` is currently logged but not used in ranking;
    CP-021/22/23 wires it as a per-turn task score.
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
    rows: list[dict] = []
    for ent in pack.entities:
        if not ent.name.startswith(f"{normalised_module}::"):
            continue
        score = pack.scores.get(ent.name, 0.0)
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
        "truncated": False if len(rows) < k else None,
        "pack_version": pack.version,
    }


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
) -> dict:
    """CP-028 — fuzzy match against name + signature + docstring.

    v0 uses a simple lowercase substring match weighted by where the
    hit occurs (name > signature > docstring). Sub-millisecond on
    catalogs of a few thousand symbols. CP-021's BM25 replaces this
    when it ships.
    """
    q = query.strip().lower()
    if not q:
        return _err("invalid_input", "query must not be empty")
    if k <= 0:
        return _err("invalid_input", "k must be > 0")

    scored: list[tuple[float, IREntity]] = []
    for ent in pack.entities:
        fields = {f.key: f.value for f in ent.fields}
        name_lc = ent.name.lower()
        sig_lc = fields.get("signature", "").lower()
        doc_lc = fields.get("docstring", "").lower()
        score = 0.0
        if q in name_lc:
            score += 3.0
        if q in sig_lc:
            score += 1.5
        if q in doc_lc:
            score += 1.0
        if score > 0:
            # Tie-break: higher centrality wins.
            score += pack.scores.get(ent.name, 0.0) * 0.1
            scored.append((score, ent))
    scored.sort(key=lambda x: (-x[0], x[1].name))
    out = [
        {"name": e.name, "row": render_catalog_row(e), "score": s}
        for s, e in scored[:k]
    ]
    return {
        "query": query,
        "symbols": out,
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
