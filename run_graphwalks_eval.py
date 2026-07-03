"""GraphWalks-adapted eval: graph reasoning over a packed service catalog.

Three conditions, scored with exact set-F1 (no LLM judge):

  RAW       full service catalog prose in context; the model does in-context
            graph reasoning (this is what GraphWalks measures)
  CTX-L3    compact DIRECTED dependency index extracted from the packed .ctx
            document (~40x smaller); model reasons over the index
  CTX-TOOL  deterministic traversal over the packed document's edges
            (what an agent gets via an MCP graph tool) - zero answer-model
            tokens; errors here would mean packing lost edges

Usage:
  python run_graphwalks_eval.py            # scales: 40 and 120 nodes
  python run_graphwalks_eval.py --smoke    # 40 nodes, 3 questions
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ctxpack.benchmarks.dotenv import load_dotenv
load_dotenv()
os.environ["CTXPACK_EVAL_PROVIDER"] = "anthropic"
os.environ["CTXPACK_EVAL_MODEL"] = "claude-sonnet-4-6"

from ctxpack.agent.state_parser import parse_steps
from ctxpack.benchmarks.agentic.graph_gen import generate_service_graph
from ctxpack.benchmarks.metrics.cost import count_bpe_tokens
from ctxpack.benchmarks.metrics.fidelity import (
    _ask_llm, _detect_provider, _INTER_CALL_DELAY,
)
from ctxpack.core.model import KeyValue, Section
from ctxpack.core.packer.compressor import compress
from ctxpack.core.packer.entity_resolver import resolve_entities

SCALES = [40, 120]
RESULTS_DIR = os.path.join("ctxpack", "benchmarks", "agentic", "results")

_REF_RE = re.compile(r"@(ENTITY-[\w-]+)")


# ---------------------------------------------------------------------------
# Packed-document edge extraction (directed, from DEPENDS-ON values)
# ---------------------------------------------------------------------------

def _doc_edges(doc) -> dict[str, list[str]]:
    """Directed edges recovered from the PACKED document (not the generator)."""
    edges: dict[str, list[str]] = {}
    for elem in doc.body:
        if not isinstance(elem, Section) or not elem.name.startswith("ENTITY-"):
            continue
        edges.setdefault(elem.name, [])
        for child in elem.children:
            if isinstance(child, KeyValue) and "DEPENDS" in child.key.upper():
                edges[elem.name].extend(_REF_RE.findall(child.value))
    return edges


def _build_l3_index(edges: dict[str, list[str]]) -> str:
    lines = ["Service dependency index (directed). 'A -> B' means A depends on B."]
    for src in sorted(edges):
        short = src.replace("ENTITY-", "")
        if edges[src]:
            lines.append(f"  {short} -> {', '.join(d.replace('ENTITY-', '') for d in sorted(edges[src]))}")
        else:
            lines.append(f"  {short} (no dependencies)")
    return "\n".join(lines)


def _tool_answer(edges: dict[str, list[str]], kind: str, subject: str) -> set:
    """Deterministic traversal — the MCP-graph-tool condition."""
    key = f"ENTITY-{subject}"
    strip = lambda s: s.replace("ENTITY-", "")  # noqa: E731
    if kind == "forward":
        return {strip(d) for d in edges.get(key, [])}
    if kind == "reverse":
        return {strip(src) for src, ds in edges.items() if key in ds}
    adj: dict[str, set] = {}
    for src, ds in edges.items():
        adj.setdefault(src, set())
        for d in ds:
            adj[src].add(d)
            adj.setdefault(d, set()).add(src)
    frontier = set(adj.get(key, set()))
    for m in list(frontier):
        frontier |= adj.get(m, set())
    frontier.discard(key)
    return {strip(x) for x in frontier}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _parse_answer(resp: str) -> set:
    clean = resp.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        items = json.loads(clean)
        if isinstance(items, list):
            return {str(x).strip().upper().replace("ENTITY-", "") for x in items}
    except (json.JSONDecodeError, ValueError):
        pass
    return {m.upper() for m in re.findall(r"SVC-[\w-]+", resp.upper())}


def _f1(pred: set, gold: set) -> float:
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    tp = len(pred & gold)
    p = tp / len(pred)
    r = tp / len(gold)
    return 2 * p * r / (p + r) if (p + r) else 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    smoke = "--smoke" in sys.argv
    scales = [40] if smoke else SCALES

    provider, api_key, model = _detect_provider()
    if not api_key:
        print("No API key found - aborting.")
        sys.exit(1)
    print(f"Model: {model} ({provider})")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    all_results = {"model": model, "scales": {}}

    for n_nodes in scales:
        bundle = generate_service_graph(n_nodes)
        questions = bundle.questions[:3] if smoke else bundle.questions
        raw_bpe = count_bpe_tokens(bundle.catalog_text, model=model)

        corpus = parse_steps(bundle.steps, domain="service-catalog")
        resolve_entities(corpus)
        doc = compress(corpus)
        edges = _doc_edges(doc)
        l3_index = _build_l3_index(edges)
        l3_bpe = count_bpe_tokens(l3_index, model=model)

        # Packing fidelity: did any edges get lost/invented in the pack?
        gen_edges = {f"ENTITY-{k}": sorted(f"ENTITY-{d}" for d in v)
                     for k, v in bundle.deps.items()}
        packed = {k: sorted(v) for k, v in edges.items()}
        edge_faithful = gen_edges == packed

        print(f"\n=== {n_nodes} nodes: RAW {raw_bpe} BPE, L3 index {l3_bpe} BPE "
              f"({round(raw_bpe / max(1, l3_bpe), 1)}x smaller), "
              f"edges faithful: {edge_faithful} ===")

        rows = []
        for qi, q in enumerate(questions):
            gold = set(x.upper() for x in q["gold"])
            for cond in ["RAW", "CTX-L3", "CTX-TOOL"]:
                if cond == "CTX-TOOL":
                    pred = {x.upper() for x in
                            _tool_answer(edges, q["kind"], q["subject"])}
                    bpe = l3_bpe  # what the agent's context carries
                else:
                    ctx = bundle.catalog_text if cond == "RAW" else l3_index
                    bpe = raw_bpe if cond == "RAW" else l3_bpe
                    time.sleep(_INTER_CALL_DELAY)
                    resp = _ask_llm(q["question"], ctx, model=model,
                                    api_key=api_key, provider=provider)
                    pred = _parse_answer(resp)
                f1 = _f1(pred, gold)
                rows.append({"id": q["id"], "kind": q["kind"], "cond": cond,
                             "f1": round(f1, 3), "bpe": bpe,
                             "pred": sorted(pred), "gold": sorted(gold)})
                print(f"  [{qi + 1:2}/{len(questions)}] {q['id']} {q['kind']:8} "
                      f"{cond:9} F1={f1:.2f}")

        agg = {}
        for cond in ["RAW", "CTX-L3", "CTX-TOOL"]:
            sub = [r for r in rows if r["cond"] == cond]
            agg[cond] = {
                "macro_f1": round(sum(r["f1"] for r in sub) / len(sub), 3),
                "avg_bpe": round(sum(r["bpe"] for r in sub) / len(sub)),
                "by_kind": {
                    k: round(sum(r["f1"] for r in sub if r["kind"] == k)
                             / max(1, sum(1 for r in sub if r["kind"] == k)), 3)
                    for k in ["forward", "reverse", "bfs2"]
                },
            }
        all_results["scales"][str(n_nodes)] = {
            "raw_bpe": raw_bpe, "l3_bpe": l3_bpe,
            "edge_faithful": edge_faithful, "aggregate": agg, "rows": rows,
        }
        print(f"\n  {'condition':10} {'macro-F1':>9} {'avg BPE':>9}")
        for cond in ["RAW", "CTX-L3", "CTX-TOOL"]:
            a = agg[cond]
            print(f"  {cond:10} {a['macro_f1']:>9} {a['avg_bpe']:>9}")

    out = os.path.join(RESULTS_DIR,
                       f"graphwalks-{model}{'-smoke' if smoke else ''}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
